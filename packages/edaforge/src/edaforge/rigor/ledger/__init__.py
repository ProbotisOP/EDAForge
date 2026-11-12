"""The global Hypothesis Ledger (section 8.2).

Every test, including the implicit tests inside searches, gets an entry recording the
hypothesis, its family, the test, the statistic, the p-value or e-value, the split, the time,
and the analyzer version and parameters.

The ledger is the only source of p-values, permutations and bootstraps for analyzers. They reach
it through a :class:`LedgerView` that is bound to their name, version and the current split, so
an analyzer cannot label an exploration test as a confirmation test. Blind analysis
(section 8.1) is enforced here too:

* confirmation hypotheses can only be registered after the candidate list is frozen;
* every access to the sealed split is logged, and an access before the freeze marks all
  confirmation entries with ``blind_violation``, which downgrades confirmation at grading.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from edaforge.canonical import canonical_json
from edaforge.errors import BlindAnalysisError, ContractViolation, LedgerError
from edaforge.models import Contract, LedgerEntry, ResamplingRecord, SplitName
from edaforge.rigor.bootstrap import (
    BatchStatistic,
    BootstrapInterval,
    Statistic,
    bootstrap_interval,
)
from edaforge.rigor.fdr import bh_adjust, by_adjust
from edaforge.rigor.permutation import BatchDraw, besag_clifford_pvalue
from edaforge.runtime.clock import Clock, SystemClock
from edaforge.runtime.rng import derive_seed

__all__ = ["HypothesisLedger", "LedgerView", "SealedAccess", "TestResult"]

_P_TOLERANCE = 1e-12


@dataclass(frozen=True)
class TestResult:
    hypothesis_id: str
    statistic: float | None
    p_value: float | None
    e_value: float | None = None
    n_draws: int | None = None
    stopped_early: bool | None = None


class SealedAccess(Contract):
    reason: str
    at: datetime
    before_freeze: bool


@dataclass
class _Record:
    hypothesis_id: str
    hypothesis: str
    family_path: tuple[str, ...]
    analyzer: str
    analyzer_version: str
    test: str
    split: SplitName
    params: dict[str, JsonValue]
    parent_id: str | None
    created_at: datetime
    status: Literal["registered", "tested", "untestable"] = "registered"
    untestable_reason: str | None = None
    statistic: float | None = None
    p_value: float | None = None
    e_value: float | None = None
    n: int | None = None
    n_resamples: int | None = None
    stopped_early: bool | None = None
    seed: int | None = None
    tested_at: datetime | None = None
    frozen_at: datetime | None = None


@dataclass
class _State:
    records: dict[str, _Record] = field(default_factory=dict[str, _Record])
    resampling: list[ResamplingRecord] = field(default_factory=list[ResamplingRecord])
    resampling_keys: set[tuple[str, ...]] = field(default_factory=set[tuple[str, ...]])
    accesses: list[SealedAccess] = field(default_factory=list[SealedAccess])
    frozen_at: datetime | None = None
    frozen_keys: tuple[str, ...] = ()


class HypothesisLedger:
    def __init__(
        self,
        run_id: str,
        root_seed: int,
        *,
        clock: Clock | None = None,
        permutation_h: int = 10,
        permutation_max: int = 1000,
    ) -> None:
        self.run_id = run_id
        self.root_seed = root_seed
        self.permutation_h = permutation_h
        self.permutation_max = permutation_max
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._lock = threading.RLock()
        self._state = _State()

    # ------------------------------------------------------------------ registration
    def register(
        self,
        *,
        hypothesis: str,
        family_path: Sequence[str],
        analyzer: str,
        analyzer_version: str,
        test: str,
        split: SplitName,
        params: Mapping[str, JsonValue] | None = None,
        parent_id: str | None = None,
    ) -> str:
        if not family_path:
            msg = "family_path must not be empty"
            raise LedgerError(msg)
        with self._lock:
            if split == "confirmation" and self._state.frozen_at is None:
                msg = "confirmation hypotheses require a frozen candidate list (blind analysis)"
                raise BlindAnalysisError(msg)
            if parent_id is not None and parent_id not in self._state.records:
                msg = f"unknown parent hypothesis {parent_id}"
                raise LedgerError(msg)
            hid = f"H-{len(self._state.records) + 1:06d}"
            self._state.records[hid] = _Record(
                hypothesis_id=hid,
                hypothesis=hypothesis,
                family_path=tuple(family_path),
                analyzer=analyzer,
                analyzer_version=analyzer_version,
                test=test,
                split=split,
                params=dict(params or {}),
                parent_id=parent_id,
                created_at=self._clock.now(),
            )
            return hid

    def _open(self, hypothesis_id: str) -> _Record:
        record = self._state.records.get(hypothesis_id)
        if record is None:
            msg = f"unknown hypothesis {hypothesis_id}"
            raise LedgerError(msg)
        if record.status != "registered":
            msg = (
                f"{hypothesis_id} was already {record.status}; a hypothesis is closed exactly once"
            )
            raise LedgerError(msg)
        return record

    def _close(
        self,
        record: _Record,
        *,
        statistic: float | None,
        p_value: float | None,
        e_value: float | None,
        n_obs: int,
        n_resamples: int | None,
        stopped_early: bool | None,
        seed: int | None,
    ) -> None:
        record.status = "tested"
        record.statistic = statistic
        record.p_value = p_value
        record.e_value = e_value
        record.n = n_obs
        record.n_resamples = n_resamples
        record.stopped_early = stopped_early
        record.seed = seed
        record.tested_at = self._clock.now()
        record.frozen_at = self._state.frozen_at

    def mark_untestable(self, hypothesis_id: str, *, reason: str, n_obs: int) -> None:
        """Close a registered hypothesis that could not be tested (for example too few rows).

        The attempt stays in the ledger with its reason and sample size but no statistic or
        p-value, so it can never be cited as evidence: :meth:`verify_p_value` accepts only
        ``None`` for it, and FDR adjustment counts it as p = 1.
        """
        with self._lock:
            record = self._open(hypothesis_id)
            record.status = "untestable"
            record.untestable_reason = reason
            record.n = n_obs
            record.tested_at = self._clock.now()
            record.frozen_at = self._state.frozen_at

    # ------------------------------------------------------------------ tests
    def permutation_test(
        self,
        hypothesis_id: str,
        *,
        observed: float,
        draw: BatchDraw,
        n_obs: int,
        h: int | None = None,
        n_max: int | None = None,
    ) -> TestResult:
        """Sequential permutation p-value (Besag-Clifford); larger statistics are more extreme."""
        with self._lock:
            record = self._open(hypothesis_id)
            seed = derive_seed(self.root_seed, "test", hypothesis_id)
        outcome = besag_clifford_pvalue(
            observed,
            draw,
            np.random.Generator(np.random.PCG64(seed)),
            h=h or self.permutation_h,
            n_max=n_max or self.permutation_max,
        )
        with self._lock:
            self._close(
                record,
                statistic=float(observed),
                p_value=outcome.p_value,
                e_value=None,
                n_obs=n_obs,
                n_resamples=outcome.n_draws,
                stopped_early=outcome.stopped_early,
                seed=seed,
            )
        return TestResult(
            hypothesis_id=hypothesis_id,
            statistic=float(observed),
            p_value=outcome.p_value,
            n_draws=outcome.n_draws,
            stopped_early=outcome.stopped_early,
        )

    def analytic_test(
        self, hypothesis_id: str, *, statistic: float, p_value: float, n_obs: int
    ) -> TestResult:
        """Record a test whose null distribution is analytic or exact (named in ``test``)."""
        if not np.isfinite(statistic) or not 0.0 <= p_value <= 1.0:
            msg = "analytic tests need a finite statistic and a p-value in [0, 1]"
            raise LedgerError(msg)
        with self._lock:
            record = self._open(hypothesis_id)
            self._close(
                record,
                statistic=float(statistic),
                p_value=float(p_value),
                e_value=None,
                n_obs=n_obs,
                n_resamples=None,
                stopped_early=None,
                seed=None,
            )
        return TestResult(hypothesis_id=hypothesis_id, statistic=statistic, p_value=p_value)

    def e_value_test(
        self, hypothesis_id: str, *, e_value: float, statistic: float | None, n_obs: int
    ) -> TestResult:
        if not np.isfinite(e_value) or e_value < 0.0:
            msg = "e-values must be finite and non-negative"
            raise LedgerError(msg)
        with self._lock:
            record = self._open(hypothesis_id)
            self._close(
                record,
                statistic=statistic,
                p_value=None,
                e_value=float(e_value),
                n_obs=n_obs,
                n_resamples=None,
                stopped_early=None,
                seed=None,
            )
        return TestResult(
            hypothesis_id=hypothesis_id, statistic=statistic, p_value=None, e_value=e_value
        )

    # ------------------------------------------------------------------ resampling
    def _resampling_seed(
        self, analyzer: str, split: SplitName, purpose: str, method: str, n_resamples: int
    ) -> int:
        key = (analyzer, split, purpose)
        with self._lock:
            if key in self._state.resampling_keys:
                msg = f"resampling purpose {purpose!r} reused by {analyzer} on the {split} split"
                raise LedgerError(msg)
            self._state.resampling_keys.add(key)
            seed = derive_seed(self.root_seed, "resample", *key)
            self._state.resampling.append(
                ResamplingRecord(
                    purpose=purpose,
                    analyzer=analyzer,
                    method=method,
                    split=split,
                    n_resamples=n_resamples,
                    seed=seed,
                    created_at=self._clock.now(),
                )
            )
            return seed

    def bootstrap(
        self,
        *,
        analyzer: str,
        split: SplitName,
        purpose: str,
        samples: Sequence[NDArray[np.float64]],
        statistic: Statistic,
        n_resamples: int,
        level: float,
        method: Literal["bca", "percentile"] = "bca",
        batch_statistic: BatchStatistic | None = None,
    ) -> BootstrapInterval:
        seed = self._resampling_seed(analyzer, split, purpose, f"bootstrap:{method}", n_resamples)
        return bootstrap_interval(
            samples,
            statistic,
            np.random.Generator(np.random.PCG64(seed)),
            n_resamples=n_resamples,
            level=level,
            method=method,
            batch_statistic=batch_statistic,
        )

    def rng(self, *, analyzer: str, split: SplitName, purpose: str) -> np.random.Generator:
        """Randomness for non-inferential purposes (model fitting, tie breaking), audited."""
        seed = self._resampling_seed(analyzer, split, purpose, "rng", 0)
        return np.random.Generator(np.random.PCG64(seed))

    # ------------------------------------------------------------------ blind analysis
    def freeze(self, candidate_keys: Sequence[str]) -> datetime:
        with self._lock:
            if self._state.frozen_at is not None:
                msg = "the candidate list is already frozen"
                raise BlindAnalysisError(msg)
            self._state.frozen_at = self._clock.now()
            self._state.frozen_keys = tuple(candidate_keys)
            return self._state.frozen_at

    @property
    def frozen_at(self) -> datetime | None:
        return self._state.frozen_at

    @property
    def frozen_keys(self) -> tuple[str, ...]:
        return self._state.frozen_keys

    def note_sealed_access(self, reason: str) -> bool:
        """Log an access to the sealed split; returns True when it breaks blinding."""
        with self._lock:
            before = self._state.frozen_at is None
            self._state.accesses.append(
                SealedAccess(reason=reason, at=self._clock.now(), before_freeze=before)
            )
            return before

    @property
    def blind_violation(self) -> bool:
        return any(a.before_freeze for a in self._state.accesses)

    @property
    def sealed_accesses(self) -> tuple[SealedAccess, ...]:
        return tuple(self._state.accesses)

    # ------------------------------------------------------------------ queries
    def _entry(self, record: _Record) -> LedgerEntry:
        return LedgerEntry(
            hypothesis_id=record.hypothesis_id,
            hypothesis=record.hypothesis,
            family_path=list(record.family_path),
            analyzer=record.analyzer,
            analyzer_version=record.analyzer_version,
            test=record.test,
            status=record.status,
            untestable_reason=record.untestable_reason,
            statistic=record.statistic,
            p_value=record.p_value,
            e_value=record.e_value,
            split=record.split,
            params=record.params,
            parent_id=record.parent_id,
            n=record.n,
            n_resamples=record.n_resamples,
            stopped_early=record.stopped_early,
            seed=record.seed,
            frozen_at=record.frozen_at,
            blind_violation=record.split == "confirmation" and self.blind_violation,
            created_at=record.created_at,
            tested_at=record.tested_at,
        )

    def entries(self) -> tuple[LedgerEntry, ...]:
        with self._lock:
            return tuple(self._entry(r) for r in self._state.records.values())

    def entry(self, hypothesis_id: str) -> LedgerEntry:
        with self._lock:
            record = self._state.records.get(hypothesis_id)
            if record is None:
                msg = f"unknown hypothesis {hypothesis_id}"
                raise LedgerError(msg)
            return self._entry(record)

    def family_ids(self, prefix: Sequence[str], split: SplitName | None = None) -> list[str]:
        """IDs whose family path starts with ``prefix`` (and on ``split``, if given)."""
        n = len(prefix)
        with self._lock:
            return [
                r.hypothesis_id
                for r in self._state.records.values()
                if r.family_path[:n] == tuple(prefix) and (split is None or r.split == split)
            ]

    @property
    def registered_count(self) -> int:
        with self._lock:
            return len(self._state.records)

    def ids_since(self, start: int) -> list[str]:
        """IDs registered after the first ``start`` registrations, in order."""
        with self._lock:
            return list(self._state.records)[start:]

    def adjust(
        self, hypothesis_ids: Sequence[str], method: Literal["bh", "by"] = "bh"
    ) -> dict[str, float]:
        """FDR-adjusted p-values over ``hypothesis_ids``.

        Registered but untested hypotheses count with p = 1, so dropping a test never shrinks
        the family.
        """
        with self._lock:
            p: list[float] = []
            for hid in hypothesis_ids:
                record = self._state.records.get(hid)
                if record is None:
                    msg = f"unknown hypothesis {hid}"
                    raise LedgerError(msg)
                p.append(1.0 if record.p_value is None else record.p_value)
        adjusted = bh_adjust(p) if method == "bh" else by_adjust(p)
        return {hid: float(q) for hid, q in zip(hypothesis_ids, adjusted, strict=True)}

    def verify_p_value(self, hypothesis_id: str, p_value: float | None) -> None:
        """Raise unless ``p_value`` is exactly what the ledger recorded for the hypothesis."""
        entry = self.entry(hypothesis_id)
        if entry.status == "untestable":
            if p_value is not None:
                msg = (
                    f"{hypothesis_id} could not be tested ({entry.untestable_reason}); it "
                    f"has no p-value to cite"
                )
                raise ContractViolation(msg)
            return
        if entry.status != "tested":
            msg = f"{hypothesis_id} has no recorded test"
            raise ContractViolation(msg)
        if p_value is None and entry.p_value is None:
            return
        if p_value is None or entry.p_value is None or abs(p_value - entry.p_value) > _P_TOLERANCE:
            msg = (
                f"p-value {p_value} does not match the ledger value {entry.p_value} for "
                f"{hypothesis_id}: numbers must come from the ledger (Law 2)"
            )
            raise ContractViolation(msg)

    def view(
        self, *, analyzer: str, analyzer_version: str, split: SplitName, scope: str = ""
    ) -> LedgerView:
        return LedgerView(
            self, analyzer=analyzer, analyzer_version=analyzer_version, split=split, scope=scope
        )

    # ------------------------------------------------------------------ export
    def to_dict(self) -> dict[str, JsonValue]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "entries": [e.model_dump(mode="json") for e in self.entries()],
                "resampling": [r.model_dump(mode="json") for r in self._state.resampling],
                "sealed_accesses": [a.model_dump(mode="json") for a in self._state.accesses],
                "frozen_at": None
                if self._state.frozen_at is None
                else self._state.frozen_at.isoformat(),
                "frozen_keys": list(self._state.frozen_keys),
            }

    def to_jsonl(self) -> str:
        return "".join(canonical_json(e) + "\n" for e in self.entries())

    @staticmethod
    def entries_from_jsonl(text: str) -> list[LedgerEntry]:
        return [LedgerEntry.model_validate(json.loads(line)) for line in text.splitlines() if line]


class LedgerView:
    """The ledger as seen by one analyzer on one split.

    ``scope`` distinguishes repeated passes on the same split label, such as the half-splits of
    cross-fitting; it prefixes resampling purposes so that each pass gets its own streams.
    """

    def __init__(
        self,
        ledger: HypothesisLedger,
        *,
        analyzer: str,
        analyzer_version: str,
        split: SplitName,
        scope: str = "",
    ) -> None:
        self._ledger = ledger
        self.analyzer = analyzer
        self.analyzer_version = analyzer_version
        self.split: SplitName = split
        self.scope = scope

    def _purpose(self, purpose: str) -> str:
        return f"{self.scope}/{purpose}" if self.scope else purpose

    def register(
        self,
        *,
        hypothesis: str,
        family: Sequence[str],
        test: str,
        params: Mapping[str, JsonValue] | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Register a hypothesis under ``[layer, analyzer, *family]`` (section 8.2 hierarchy)."""
        layer = self.analyzer.split(".", 1)[0]
        return self._ledger.register(
            hypothesis=hypothesis,
            family_path=[layer, self.analyzer, *family],
            analyzer=self.analyzer,
            analyzer_version=self.analyzer_version,
            test=test,
            split=self.split,
            params=params,
            parent_id=parent_id,
        )

    def permutation_test(
        self,
        hypothesis_id: str,
        *,
        observed: float,
        draw: BatchDraw,
        n_obs: int,
        h: int | None = None,
        n_max: int | None = None,
    ) -> TestResult:
        self._check_owner(hypothesis_id)
        return self._ledger.permutation_test(
            hypothesis_id, observed=observed, draw=draw, n_obs=n_obs, h=h, n_max=n_max
        )

    def analytic_test(
        self, hypothesis_id: str, *, statistic: float, p_value: float, n_obs: int
    ) -> TestResult:
        self._check_owner(hypothesis_id)
        return self._ledger.analytic_test(
            hypothesis_id, statistic=statistic, p_value=p_value, n_obs=n_obs
        )

    def mark_untestable(self, hypothesis_id: str, *, reason: str, n_obs: int) -> None:
        self._check_owner(hypothesis_id)
        self._ledger.mark_untestable(hypothesis_id, reason=reason, n_obs=n_obs)

    def bootstrap(
        self,
        *,
        purpose: str,
        samples: Sequence[NDArray[np.float64]],
        statistic: Statistic,
        n_resamples: int,
        level: float,
        method: Literal["bca", "percentile"] = "bca",
        batch_statistic: BatchStatistic | None = None,
    ) -> BootstrapInterval:
        return self._ledger.bootstrap(
            analyzer=self.analyzer,
            split=self.split,
            purpose=self._purpose(purpose),
            samples=samples,
            statistic=statistic,
            n_resamples=n_resamples,
            level=level,
            method=method,
            batch_statistic=batch_statistic,
        )

    def rng(self, purpose: str) -> np.random.Generator:
        return self._ledger.rng(
            analyzer=self.analyzer, split=self.split, purpose=self._purpose(purpose)
        )

    def _check_owner(self, hypothesis_id: str) -> None:
        entry = self._ledger.entry(hypothesis_id)
        if entry.analyzer != self.analyzer or entry.split != self.split:
            msg = (
                f"{self.analyzer} on the {self.split} split cannot test {hypothesis_id}, "
                f"registered by {entry.analyzer} on the {entry.split} split"
            )
            raise ContractViolation(msg)
