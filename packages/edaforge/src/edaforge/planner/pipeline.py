"""The planner and the discovery funnel: Screen -> Refine -> Confirm -> Grade -> Explain.

Section 5.2. The planner owns the split: analyzers see exploration rows in ``screen`` and
``refine`` and sealed rows in ``confirm``, never both. Every candidate and every evidence draft
is checked against the Hypothesis Ledger before it can become a finding.

Split regimes (section 8.1):

* holdout: screen on the exploration split, freeze the candidate list, unseal, confirm, then
  apply BH across all confirmation tests of the run;
* cross-fit: discover on all rows (exploratory), then for each random half-split select on one
  half and test on the other; per-candidate p-values are aggregated with the
  Meinshausen-Meier-Buhlmann quantile rule (p = 1 on splits where a candidate is not selected),
  ledgered, and BH-adjusted;
* small sample: discover on all rows; nothing can be confirmed and grades are capped at D.

Search breadth per analyzer is counted in full: BH runs over every hypothesis the analyzer
registered during a pass, not only over the candidates it returned.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import polars as pl
from pydantic import JsonValue

from edaforge.config import EDAForgeConfig, budget_settings, config_hash
from edaforge.errors import ContractViolation
from edaforge.explain.render import lint_lenses
from edaforge.models import (
    AnalyzerRef,
    AssumptionCheck,
    Candidate,
    Confirmation,
    Contract,
    DataInput,
    EvidenceDraft,
    Finding,
    Lenses,
    LensText,
    Provenance,
    RunManifest,
    SplitName,
    SplitRecord,
)
from edaforge.plugins.sdk import (
    AnalysisData,
    Analyzer,
    DataProfile,
    RunContext,
    capabilities_met,
    profile_frame,
)
from edaforge.rigor.assumptions import run_assumption_checks
from edaforge.rigor.grading import grade_evidence
from edaforge.rigor.ledger import HypothesisLedger
from edaforge.rigor.splits import (
    SealedHoldout,
    SplitMode,
    choose_mode,
    half_splits,
    holdout_plan,
    mmb_quantile_aggregate,
)
from edaforge.runtime.clock import Clock
from edaforge.runtime.events import Event, EventBus
from edaforge.runtime.manifest import build_manifest, edaforge_version, manifest_hash
from edaforge.runtime.rng import make_rng
from edaforge.synthesis import interestingness

__all__ = ["RunResult", "SearchSummary", "run_pipeline"]

_EMPTY_LENS = LensText(headline="", markdown="")
_PLACEHOLDER = Lenses(plain=_EMPTY_LENS, analyst=_EMPTY_LENS, scientist=_EMPTY_LENS)


class SearchSummary(Contract):
    """What one analyzer searched: Law 8 and anti-pattern 15 (never hide null results)."""

    analyzer: str
    tested: int
    promoted: int
    confirmed: int

    def as_row(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class RunResult(Contract):
    """Everything a run produced, as plain data (it can be cached and reloaded)."""

    manifest: RunManifest
    manifest_hash: str
    config: EDAForgeConfig
    findings: tuple[Finding, ...]
    ledger: dict[str, JsonValue]
    events: tuple[dict[str, JsonValue], ...]
    searched: tuple[SearchSummary, ...]
    warnings: tuple[str, ...]


@dataclass
class _Screened:
    analyzer: Analyzer
    candidate: Candidate
    q: float
    assumptions: list[AssumptionCheck]

    @property
    def gkey(self) -> str:
        return f"{self.analyzer.name}:{self.candidate.key}"


@dataclass
class _Outcome:
    draft: EvidenceDraft
    confirmation: Confirmation
    caveats: list[str]


def _strata(frame: pl.DataFrame, data: AnalysisData) -> list[str] | None:
    """Stratify splits by environment and by a low-cardinality target, when present."""
    parts: list[pl.Series] = []
    env = data.profile.environment_column
    if env is not None:
        parts.append(frame[env].cast(pl.String).fill_null("<null>"))
    for target in data.profile.targets[:1]:
        column = frame[target]
        if column.n_unique() <= 20:
            parts.append(column.cast(pl.String).fill_null("<null>"))
    if not parts:
        return None
    labels = parts[0]
    for extra in parts[1:]:
        labels = labels + "|" + extra
    return [str(v) for v in labels.to_list()]


def _groups(frame: pl.DataFrame, data: AnalysisData) -> list[int] | None:
    """Entity codes when rows repeat per entity, so a split never divides an entity."""
    column = data.profile.group_column
    if column is None or column not in frame.columns:
        return None
    return [int(v) for v in frame[column].to_list()]


class _Pipeline:
    def __init__(
        self,
        data: AnalysisData,
        analyzers: Sequence[Analyzer],
        config: EDAForgeConfig,
        *,
        analyzer_refs: Sequence[AnalyzerRef],
        inputs: Sequence[DataInput],
        clock: Clock | None,
        on_event: Callable[[Event], None] | None,
    ) -> None:
        self.data = data
        self.config = config
        self.rigor = config.rigor
        self.settings = budget_settings(config.budget)
        self.seed = config.compute.seed
        self.analyzers = sorted(analyzers, key=lambda a: a.name)
        self.analyzer_refs = analyzer_refs
        self.inputs = inputs
        self.clock = clock
        self.on_event = on_event
        self.warnings: list[str] = []
        self.mode: SplitMode = choose_mode(data.frame.height, self.rigor)

    # ------------------------------------------------------------------ helpers
    def _ctx(
        self, analyzer: Analyzer, split: SplitName, scope: str, frame: pl.DataFrame
    ) -> RunContext:
        return RunContext(
            run_id=self.manifest.run_id,
            config=self.config,
            budget=self.config.budget,
            budget_settings=self.settings,
            ledger=self.ledger.view(
                analyzer=analyzer.name,
                analyzer_version=analyzer.version,
                split=split,
                scope=scope,
            ),
            events=self.events,
            split=split,
            data_hash=self.data.data_hash,
            profile=self._profile(frame),
            warnings=self.warnings,
        )

    def _profile(self, frame: pl.DataFrame) -> DataProfile:
        return profile_frame(
            frame,
            environment_column=self.data.profile.environment_column,
            targets=self.data.profile.targets,
            time_column=self.data.profile.time_column,
            group_column=self.data.profile.group_column,
        )

    def _check_candidate(self, analyzer: Analyzer, cand: Candidate, split: SplitName) -> None:
        if cand.analyzer != analyzer.name:
            msg = f"{analyzer.name} returned a candidate labelled {cand.analyzer!r}"
            raise ContractViolation(msg)
        entry = self.ledger.entry(cand.hypothesis_id)
        if entry.analyzer != analyzer.name or entry.split != split:
            msg = f"candidate {cand.key} cites {cand.hypothesis_id}, not its own {split} test"
            raise ContractViolation(msg)
        self.ledger.verify_p_value(cand.hypothesis_id, cand.p_value)

    # ------------------------------------------------------------------ screening
    def _screen_pass(self, frame: pl.DataFrame, split: SplitName, scope: str) -> list[_Screened]:
        """Screen every task, refine the survivors, and BH-adjust over the whole pass.

        Refine runs only on candidates whose screening q is within ``screen_q`` (the funnel's
        "expensive methods on survivors only"). Hypotheses that refine registers join the family,
        so the final q-values are computed over everything the analyzer registered in the pass.
        """
        out: list[_Screened] = []
        for analyzer in self.eligible:
            ctx = self._ctx(analyzer, split, scope, frame)
            plan_data = AnalysisData(
                frame=frame, name=self.data.name, data_hash=self.data.data_hash, profile=ctx.profile
            )
            start = self.ledger.registered_count
            screened: list[Candidate] = []
            for task in sorted(analyzer.plan(plan_data, ctx), key=lambda t: t.key):
                for cand in analyzer.screen(task, frame, ctx):
                    self._check_candidate(analyzer, cand, split)
                    screened.append(cand)
            keys = [c.key for c in screened]
            if len(set(keys)) != len(keys):
                msg = f"{analyzer.name} returned duplicate candidate keys"
                raise ContractViolation(msg)
            screening_family = self.ledger.ids_since(start)
            q_screen = self.ledger.adjust(screening_family) if screening_family else {}
            candidates: list[Candidate] = []
            for cand in sorted(screened, key=lambda c: c.key):
                if q_screen[cand.hypothesis_id] > self.rigor.screen_q:
                    candidates.append(cand)
                    continue
                refined = analyzer.refine(cand, frame, ctx)
                if (refined.key, refined.hypothesis_id, refined.p_value) != (
                    cand.key,
                    cand.hypothesis_id,
                    cand.p_value,
                ):
                    msg = f"{analyzer.name}.refine changed the identity or p-value of {cand.key}"
                    raise ContractViolation(msg)
                candidates.append(refined)
            family = self.ledger.ids_since(start)
            q_values = self.ledger.adjust(family) if family else {}
            for cand in candidates:
                q = q_values[cand.hypothesis_id]
                survivor = q <= self.rigor.screen_q
                checks = (
                    run_assumption_checks(analyzer.assumptions, frame, cand.params)
                    if survivor and split != "cross_fit"
                    else []
                )
                out.append(_Screened(analyzer, cand, q, checks))
                if split != "cross_fit" and survivor:
                    self.events.emit(
                        "candidate",
                        cand.title,
                        stage=split,
                        data={"analyzer": analyzer.name, "key": cand.key, "q": q},
                    )
            if split != "cross_fit":
                tested = sum(1 for h in family if self.ledger.entry(h).status == "tested")
                self.discovery_tested[analyzer.name] = (
                    self.discovery_tested.get(analyzer.name, 0) + tested
                )
        return out

    def _promote(self, screened: list[_Screened]) -> list[_Screened]:
        eligible = [s for s in screened if s.q <= self.rigor.screen_q]
        # Capping by q is a screening decision; the confirmation tests decide what is reported.
        eligible.sort(key=lambda s: (s.q, s.analyzer.name, s.candidate.key))
        if len(eligible) > self.rigor.max_confirmations:
            self.warnings.append(
                f"{len(eligible)} candidates passed screening; only the "
                f"{self.rigor.max_confirmations} with the smallest q were sent to confirmation"
            )
        kept = eligible[: self.rigor.max_confirmations]
        return sorted(kept, key=lambda s: (s.analyzer.name, s.candidate.key))

    # ------------------------------------------------------------------ confirmation
    def _check_draft(self, item: _Screened, draft: EvidenceDraft, split: SplitName) -> None:
        cand = item.candidate
        self.ledger.verify_p_value(cand.hypothesis_id, draft.p_value)
        if cand.hypothesis_id not in draft.hypothesis_ids:
            msg = f"evidence for {cand.key} does not cite its discovery test"
            raise ContractViolation(msg)
        ids = draft.confirmation.hypothesis_ids
        if not ids:
            msg = f"confirmation of {cand.key} cites no ledger entry"
            raise ContractViolation(msg)
        for hid in ids:
            entry = self.ledger.entry(hid)
            if entry.split != split or entry.analyzer != item.analyzer.name:
                msg = f"confirmation of {cand.key} cites {hid}, which is not its own {split} test"
                raise ContractViolation(msg)
        self.ledger.verify_p_value(ids[0], draft.confirmation.p_value)

    def _confirm_holdout(
        self, promoted: list[_Screened], sealed: SealedHoldout, frame: pl.DataFrame
    ) -> dict[str, _Outcome]:
        self.ledger.freeze([s.gkey for s in promoted])
        sealed_frame = frame[sealed.unseal(self.ledger, reason="confirm the frozen candidate list")]
        drafts: dict[str, EvidenceDraft] = {}
        for item in promoted:
            ctx = self._ctx(item.analyzer, "confirmation", "", sealed_frame)
            draft = item.analyzer.confirm(item.candidate, sealed_frame, ctx)
            self._check_draft(item, draft, "confirmation")
            drafts[item.gkey] = draft
        confirmation_ids = self.ledger.family_ids([], split="confirmation")
        q = self.ledger.adjust(confirmation_ids) if confirmation_ids else {}
        outcomes: dict[str, _Outcome] = {}
        for key, draft in drafts.items():
            primary = draft.confirmation.hypothesis_ids[0]
            conf = draft.confirmation.model_copy(
                update={
                    "method": "sealed_holdout",
                    "q_value": q[primary],
                    "n": sealed.n_confirmation,
                    "blind_violation": self.ledger.blind_violation,
                }
            )
            outcomes[key] = _Outcome(draft, conf, list(draft.caveats))
        return outcomes

    def _confirm_cross_fit(
        self, promoted: list[_Screened], frame: pl.DataFrame
    ) -> dict[str, _Outcome]:
        frozen = {s.gkey: s for s in promoted}
        self.ledger.freeze(list(frozen))
        rng = make_rng(self.seed, "cross_fit_splits", self.data.data_hash)
        halves = half_splits(
            frame.height,
            self.rigor.cross_fit_splits,
            rng,
            strata=_strata(frame, self.data),
            groups=_groups(frame, self.data),
        )
        per_split: dict[str, dict[int, EvidenceDraft]] = {k: {} for k in frozen}
        for b, (select_idx, test_idx) in enumerate(halves, start=1):
            select_frame = frame[select_idx]
            test_frame = frame[test_idx]
            selected = self._screen_pass(select_frame, "cross_fit", f"split{b}/select")
            for item in selected:
                if item.gkey not in frozen or item.q > self.rigor.screen_q:
                    continue
                ctx = self._ctx(item.analyzer, "cross_fit", f"split{b}/test", test_frame)
                draft = item.analyzer.confirm(item.candidate, test_frame, ctx)
                self._check_draft(item, draft, "cross_fit")
                per_split[item.gkey][b] = draft
        aggregate_ids: dict[str, str] = {}
        for key, item in frozen.items():
            p_values: list[float] = []
            for b in range(1, len(halves) + 1):
                split_draft = per_split[key].get(b)
                p_b = None if split_draft is None else split_draft.confirmation.p_value
                p_values.append(1.0 if p_b is None else p_b)
            p_agg = mmb_quantile_aggregate(p_values, self.rigor.cross_fit_gamma)
            layer = item.analyzer.name.split(".", 1)[0]
            hid = self.ledger.register(
                hypothesis=f"aggregate over {len(halves)} half-splits: {item.candidate.title}",
                family_path=[layer, item.analyzer.name, "cross_fit_aggregate"],
                analyzer=item.analyzer.name,
                analyzer_version=item.analyzer.version,
                test=f"mmb_quantile(gamma={self.rigor.cross_fit_gamma})",
                split="cross_fit",
                params={"per_split_p": [float(p) for p in p_values]},
                parent_id=item.candidate.hypothesis_id,
            )
            self.ledger.analytic_test(
                hid,
                statistic=float(len(per_split[key])),
                p_value=p_agg,
                n_obs=frame.height,
            )
            aggregate_ids[key] = hid
        q = self.ledger.adjust(list(aggregate_ids.values())) if aggregate_ids else {}
        outcomes: dict[str, _Outcome] = {}
        for key, item in frozen.items():
            hid = aggregate_ids[key]
            entry = self.ledger.entry(hid)
            drafts_by_split = per_split[key]
            caveats: list[str] = []
            representative: EvidenceDraft | None = None
            if drafts_by_split:
                # Report the test-half draft with the median p-value (ties: lowest split index).
                ordered = sorted(
                    drafts_by_split.items(),
                    key=lambda kv: (kv[1].confirmation.p_value or 1.0, kv[0]),
                )
                representative = ordered[(len(ordered) - 1) // 2][1]
                effect = representative.effect
                facts = representative.facts
                caveats.extend(representative.caveats)
            else:
                effect = item.candidate.effect
                facts = {}
                caveats.append(
                    "The effect was estimated on all rows, which the search also used; it may be "
                    "optimistic."
                )
            conf = Confirmation(
                status="pending",
                method="cross_fit",
                p_value=entry.p_value,
                q_value=q[hid],
                hypothesis_ids=[hid],
                n=frame.height,
                aggregation=(
                    f"mmb_quantile(gamma={self.rigor.cross_fit_gamma}) over {len(halves)} "
                    f"half-splits; selected on {len(drafts_by_split)}"
                ),
            )
            # Robustness measured on the representative held-out half travels with it, as in the
            # holdout regime, so the grade criteria are the same in both regimes.
            robust: dict[str, object] = {}
            if representative is not None:
                robust = {
                    "stability": representative.stability,
                    "specs_consistent": representative.specs_consistent,
                    "specs_total": representative.specs_total,
                    "assumptions": representative.assumptions,
                    "refutations": representative.refutations,
                }
            draft = EvidenceDraft(
                test=item.candidate.test,
                statistic=item.candidate.statistic,
                p_value=item.candidate.p_value,
                hypothesis_ids=[item.candidate.hypothesis_id, hid],
                n=frame.height,
                confirmation=conf,
                effect=effect,
                claimed_rung=item.candidate.claimed_rung,
                facts=facts,
                **robust,  # pyright: ignore[reportArgumentType]
            )
            outcomes[key] = _Outcome(draft, conf, caveats)
        return outcomes

    def _unconfirmed(self, promoted: list[_Screened]) -> dict[str, _Outcome]:
        outcomes: dict[str, _Outcome] = {}
        for item in promoted:
            cand = item.candidate
            conf = Confirmation(status="not_applicable", method="none")
            draft = EvidenceDraft(
                test=cand.test,
                statistic=cand.statistic,
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id],
                n=self.data.frame.height,
                confirmation=conf,
                effect=cand.effect,
                claimed_rung=cand.claimed_rung,
            )
            outcomes[item.gkey] = _Outcome(
                draft,
                conf,
                ["Found on a small sample with no data set aside to check it; exploratory."],
            )
        return outcomes

    # ------------------------------------------------------------------ assembly
    def _assemble(self, promoted: list[_Screened], outcomes: dict[str, _Outcome]) -> list[Finding]:
        findings: list[Finding] = []
        for index, item in enumerate(promoted, start=1):
            outcome = outcomes[item.gkey]
            cand = item.candidate
            draft = outcome.draft
            effect = draft.effect or cand.effect
            sesoi = None
            if effect is not None:
                sesoi = (
                    effect.sesoi
                    if effect.sesoi is not None
                    else self.config.sesoi.get(effect.measure)
                )
                if effect.sesoi is None and sesoi is not None:
                    effect = effect.model_copy(update={"sesoi": sesoi})
            checks = [*item.assumptions, *draft.assumptions]
            draft = draft.model_copy(update={"assumptions": checks, "effect": effect})
            evidence = grade_evidence(
                draft,
                confirmation=outcome.confirmation,
                exploration_q=item.q,
                rigor=self.rigor,
                small_sample=self.mode == "small_sample",
                sesoi=sesoi,
            )
            caveats = list(outcome.caveats)
            caveats.extend(
                f"Assumption '{c.name}' ({c.status}): {c.detail}"
                for c in checks
                if c.status in {"warn", "fail", "not_checked"}
            )
            fid = f"F-{index:06d}"
            hypothesis_ids = list(
                dict.fromkeys([*draft.hypothesis_ids, *outcome.confirmation.hypothesis_ids])
            )
            finding = Finding(
                id=fid,
                kind=cand.kind,
                pattern_class=cand.pattern_class,
                title_plain=cand.title,
                lenses=_PLACEHOLDER,
                variables=cand.variables,
                subgroup=cand.subgroup,
                effect=effect,
                facts={**cand.facts, **draft.facts},
                evidence=evidence,
                interestingness=interestingness(
                    effect, evidence.grade, self.config.interestingness
                ),
                caveats=caveats,
                provenance=Provenance(
                    analyzer=item.analyzer.name,
                    analyzer_version=item.analyzer.version,
                    params=cand.params,
                    seed=self.seed,
                    data_hash=self.data.data_hash,
                    run_id=self.manifest.run_id,
                    manifest_hash=self.manifest_hash,
                    edaforge_version=edaforge_version(),
                    hypothesis_ids=hypothesis_ids,
                    code=f"edaforge reproduce {fid} --run <run-directory>",
                ),
            )
            lenses = item.analyzer.render(finding)
            payload = finding.model_dump()
            payload.update({"lenses": lenses.model_dump(), "title_plain": lenses.plain.headline})
            finding = Finding.model_validate(payload)
            for problem in lint_lenses(finding):
                self.warnings.append(f"{fid} language check: {problem}")
            findings.append(finding)
            self.events.emit(
                "finding",
                finding.title_plain,
                stage="explain",
                data={
                    "id": fid,
                    "kind": finding.kind.value,
                    "grade": evidence.grade,
                    "rung": evidence.rung,
                },
            )
        return findings

    # ------------------------------------------------------------------ run
    def run(self) -> RunResult:
        frame = self.data.frame
        n = frame.height
        sealed: SealedHoldout | None = None
        if self.mode == "holdout":
            plan = holdout_plan(
                n,
                self.rigor.confirmation_fraction,
                make_rng(self.seed, "holdout", self.data.data_hash),
                strata=_strata(frame, self.data),
                groups=_groups(frame, self.data),
                order=None
                if self.data.profile.time_column is None
                else frame[self.data.profile.time_column].to_numpy(),
                embargo=self.rigor.embargo,
            )
            sealed = SealedHoldout(plan, self.data.data_hash)
            split_record = sealed.record(n)
        elif self.mode == "cross_fit":
            split_record = SplitRecord(
                mode="cross_fit",
                n_total=n,
                n_exploration=n,
                n_confirmation=0,
                n_splits=self.rigor.cross_fit_splits,
                strategy=(
                    f"{self.rigor.cross_fit_splits} random half-splits; select on one half, test "
                    "on the other"
                ),
            )
        else:
            split_record = SplitRecord(
                mode="small_sample",
                n_total=n,
                n_exploration=n,
                n_confirmation=0,
                strategy="no confirmation split (n below the cross-fitting minimum)",
            )
        self.manifest = build_manifest(
            seed=self.seed,
            config_hash=config_hash(self.config),
            inputs=self.inputs,
            analyzers=self.analyzer_refs,
            split=split_record,
            clock=self.clock,
        )
        self.manifest_hash = manifest_hash(self.manifest)
        self.events = EventBus(self.manifest.run_id, self.clock)
        if self.on_event is not None:
            self.events.subscribe(self.on_event)
        self.ledger = HypothesisLedger(
            self.manifest.run_id,
            self.seed,
            clock=self.clock,
            permutation_h=self.rigor.permutation_h,
            permutation_max=self.settings.permutation_max,
        )
        self.discovery_tested: dict[str, int] = {}
        self.events.emit(
            "run_started",
            f"{n} rows, {split_record.mode} mode",
            data={
                "mode": split_record.mode,
                "rows": n,
                "analyzers": [a.name for a in self.analyzers],
            },
        )
        self.eligible: list[Analyzer] = []
        for analyzer in self.analyzers:
            ok, missing = capabilities_met(analyzer.requires, self.data.profile)
            if ok:
                self.eligible.append(analyzer)
            else:
                message = f"{analyzer.name} skipped: needs {', '.join(missing)}"
                self.warnings.append(message)
                self.events.emit("warning", message, stage="plan")

        if self.mode == "holdout":
            assert sealed is not None  # noqa: S101
            explore = frame[sealed.exploration_indices]
            screened = self._screen_pass(explore, "exploration", "")
            self.events.emit("progress", "screening finished", stage="screen")
            promoted = self._promote(screened)
            outcomes = self._confirm_holdout(promoted, sealed, frame)
        elif self.mode == "cross_fit":
            screened = self._screen_pass(frame, "full", "")
            promoted = self._promote(screened)
            outcomes = self._confirm_cross_fit(promoted, frame)
        else:
            screened = self._screen_pass(frame, "full", "")
            promoted = self._promote(screened)
            outcomes = self._unconfirmed(promoted)
        self.events.emit("progress", "confirmation finished", stage="confirm")

        findings = self._assemble(promoted, outcomes)
        searched = tuple(
            SearchSummary(
                analyzer=a.name,
                tested=self.discovery_tested.get(a.name, 0),
                promoted=sum(1 for s in promoted if s.analyzer.name == a.name),
                confirmed=sum(
                    1
                    for f in findings
                    if f.provenance.analyzer == a.name
                    and f.evidence.confirmation.status == "confirmed"
                ),
            )
            for a in self.eligible
        )
        for message in self.warnings:
            if not any(e.message == message for e in self.events.history() if e.kind == "warning"):
                self.events.emit("warning", message, stage="report")
        self.events.emit(
            "run_finished",
            f"{len(findings)} findings",
            data={"findings": len(findings), "confirmed": sum(s.confirmed for s in searched)},
        )
        return RunResult(
            manifest=self.manifest,
            manifest_hash=self.manifest_hash,
            config=self.config,
            findings=tuple(findings),
            ledger=self.ledger.to_dict(),
            events=tuple(self.events.transcript()),
            searched=searched,
            warnings=tuple(self.warnings),
        )


def run_pipeline(
    data: AnalysisData,
    analyzers: Sequence[Analyzer],
    config: EDAForgeConfig,
    *,
    analyzer_refs: Sequence[AnalyzerRef],
    inputs: Sequence[DataInput],
    clock: Clock | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> RunResult:
    """Run the discovery funnel on one analysis frame."""
    return _Pipeline(
        data,
        analyzers,
        config,
        analyzer_refs=analyzer_refs,
        inputs=inputs,
        clock=clock,
        on_event=on_event,
    ).run()
