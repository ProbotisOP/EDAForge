"""Phase 0 end-to-end acceptance and Rigor Kernel contract enforcement."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import polars as pl
import pytest

import edaforge as gh
from edaforge.canonical import sha256_hex
from edaforge.errors import ContractViolation, ReproductionMismatch
from edaforge.explain.render import lint_lenses, render_lenses
from edaforge.models import (
    Candidate,
    ColumnRef,
    Confirmation,
    EvidenceDraft,
    Finding,
    FindingKind,
    Lenses,
    PatternClass,
)
from edaforge.plugins.sdk import AnalysisData, CostEstimate, DataProfile, RunContext, Task
from edaforge.rigor.assumptions import AssumptionSpec
from edaforge.runtime.clock import FixedClock
from edaforge.runtime.events import Event
from edaforge_bench.generators import MultiEnvSpec, multi_environment

PLUGIN = "edaforge-plugin-example"


@pytest.fixture(scope="module")
def shifted() -> pl.DataFrame:
    spec = MultiEnvSpec(n_per_env=1500, n_nodes=4, shift_nodes=(0,), shift_size=0.5)
    return multi_environment(spec, seed=3).frame


def test_phase0_acceptance_one_finding_end_to_end(shifted: pl.DataFrame, tmp_path: Path) -> None:
    """Ledger -> grade -> three lenses -> JSON and HTML, with full provenance (section 17)."""
    events: list[Event] = []
    run = gh.discover(
        shifted, plugins=[PLUGIN], budget="quick", clock=FixedClock(), on_event=events.append
    )
    kinds = [e.kind for e in events]
    assert kinds[0] == "run_started"
    assert kinds[-1] == "run_finished"
    assert kinds.index("candidate") < kinds.index("finding")

    confirmed = [f for f in run.findings if f.evidence.confirmation.status == "confirmed"]
    assert confirmed, "the planted shift must be confirmed"
    finding = confirmed[0]
    assert finding.variables[0].column == "x0"

    # Ledger: a discovery test on the exploration split and a child confirmation test.
    entries = {e.hypothesis_id: e for e in run.ledger}
    explore, confirm = (entries[h] for h in finding.provenance.hypothesis_ids)
    assert (explore.split, confirm.split) == ("exploration", "confirmation")
    assert confirm.parent_id == explore.hypothesis_id
    assert confirm.frozen_at is not None
    assert not confirm.blind_violation
    assert finding.evidence.p_value == explore.p_value
    assert finding.evidence.confirmation.p_value == confirm.p_value

    # Grade: stability and the multiverse are not measured in Phase 0, so C at best.
    assert finding.evidence.grade == "C"
    assert finding.evidence.rung == "R1"
    assert any("stability not measured" in r for r in finding.evidence.grade_reasons)

    # Three lenses that pass the language rules.
    for lens in (finding.lenses.plain, finding.lenses.analyst, finding.lenses.scientist):
        assert lens.headline
        assert lens.markdown
    assert lint_lenses(finding) == []
    assert len(finding.lenses.plain.headline.split()) <= 20
    assert "significant" not in finding.lenses.plain.markdown.lower()

    # Full provenance.
    prov = finding.provenance
    assert prov.analyzer == "example.mean_shift"
    assert prov.analyzer_version == "0.1.0"
    assert prov.params["column"] == "x0"
    assert prov.seed == run.result.config.compute.seed
    assert len(prov.data_hash) == 64
    assert len(prov.manifest_hash) == 64
    assert prov.run_id == run.run_id
    assert prov.code.startswith(f"edaforge reproduce {finding.id}")
    assert run.manifest.libraries["numpy"]
    assert run.manifest.split is not None
    assert run.manifest.split.mode == "holdout"

    # Exports.
    findings_json = json.loads(run.export(tmp_path / "findings.json").read_text("utf-8"))
    assert finding.id in {f["id"] for f in findings_json}
    html = run.export(tmp_path / "report.html").read_text("utf-8")
    assert finding.id in html
    assert "<script" not in html


def test_findings_json_is_byte_identical_across_processes(
    shifted: pl.DataFrame, tmp_path: Path
) -> None:
    """Gate 5 in miniature: same inputs, seed and versions, different process and clock."""
    data_path = tmp_path / "data.parquet"
    shifted.write_parquet(data_path)
    here = gh.discover(
        pl.read_parquet(data_path),
        plugins=[PLUGIN],
        budget="quick",
        clock=FixedClock(datetime(2030, 5, 5, tzinfo=UTC)),
    )
    code = (
        "import sys, hashlib, polars as pl, edaforge as gh;"
        f"run = gh.discover(pl.read_parquet({str(data_path)!r}), plugins=[{PLUGIN!r}], "
        f"budget='quick');"
        "sys.stdout.write(hashlib.sha256(run.findings_json().encode()).hexdigest())"
    )
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    other = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    assert other == sha256_hex(here.findings_json().encode())


def test_reproduce_in_memory_and_from_a_run_directory(tmp_path: Path) -> None:
    spec = MultiEnvSpec(n_per_env=1200, n_nodes=3, shift_nodes=(0,), shift_size=0.5)
    frame = multi_environment(spec, seed=5).frame
    a = frame.filter(pl.col("__source__") == "E0").drop("__source__")
    b = frame.filter(pl.col("__source__") == "E1").drop("__source__")
    paths = [tmp_path / "north.csv", tmp_path / "south.csv"]
    a.write_csv(paths[0])
    b.write_csv(paths[1])
    run = gh.discover(paths, plugins=[PLUGIN], budget="quick")
    finding = run.findings.top(1)[0]
    assert run.reproduce(finding.id).id == finding.id
    run_dir = run.save(tmp_path / "run")
    assert gh.reproduce_from_directory(run_dir, finding.id).id == finding.id
    paths[1].write_text(paths[1].read_text("utf-8") + "0,0,0\n", "utf-8")
    with pytest.raises(ReproductionMismatch, match="SHA-256"):
        gh.reproduce_from_directory(run_dir, finding.id)


def test_cache_returns_identical_results(shifted: pl.DataFrame, tmp_path: Path) -> None:
    first = gh.discover(shifted, plugins=[PLUGIN], budget="quick", cache_dir=tmp_path)
    second = gh.discover(shifted, plugins=[PLUGIN], budget="quick", cache_dir=tmp_path)
    assert not first.from_cache
    assert second.from_cache
    assert first.findings_json() == second.findings_json()


def test_small_samples_are_exploratory() -> None:
    spec = MultiEnvSpec(n_per_env=100, n_nodes=2, shift_nodes=(0,), shift_size=1.0)
    run = gh.discover(multi_environment(spec, seed=1).frame, plugins=[PLUGIN], budget="quick")
    assert run.manifest.split is not None
    assert run.manifest.split.mode == "small_sample"
    assert run.findings, "a large shift should at least be a lead"
    for finding in run.findings:
        assert finding.evidence.grade in {"D", "E"}
        assert finding.evidence.exploratory
        assert finding.evidence.confirmation.status == "not_applicable"


def test_cross_fitting_aggregates_half_splits() -> None:
    spec = MultiEnvSpec(n_per_env=500, n_nodes=2, shift_nodes=(0,), shift_size=0.6)
    run = gh.discover(multi_environment(spec, seed=2).frame, plugins=[PLUGIN], budget="quick")
    assert run.manifest.split is not None
    assert run.manifest.split.mode == "cross_fit"
    shifted_finding = next(f for f in run.findings if f.variables[0].column == "x0")
    assert shifted_finding.evidence.confirmation.method == "cross_fit"
    assert shifted_finding.evidence.confirmation.status == "confirmed"
    aggregates = [e for e in run.ledger if e.family_path[-1] == "cross_fit_aggregate"]
    assert aggregates
    assert all(len(e.params["per_split_p"]) == 10 for e in aggregates)  # type: ignore[arg-type]


def test_null_data_yields_no_confirmed_findings() -> None:
    from edaforge_bench.generators import NULL_VARIANTS, null_world

    world = null_world(NULL_VARIANTS["mixed"], seed=4)
    run = gh.discover(world.frame, plugins=[PLUGIN], budget="quick")
    assert not any(f.evidence.confirmation.status == "confirmed" for f in run.findings)
    assert run.searched[0].tested == 4  # every hypothesis is counted, even without findings


# ---------------------------------------------------------------- contract enforcement


class _Base:
    version: ClassVar[str] = "1.0"
    pattern_class: ClassVar[PatternClass] = PatternClass.ACROSS_FILES
    requires: ClassVar[frozenset[str]] = frozenset({"numeric>=1"})
    assumptions: ClassVar[Sequence[AssumptionSpec]] = ()

    def estimate_cost(self, profile: DataProfile, budget: str) -> CostEstimate:
        return CostEstimate(seconds=0.0, memory_mb=0.0)

    def plan(self, data: AnalysisData, ctx: RunContext) -> list[Task]:
        return [Task(key="t", params={"column": data.profile.numeric[0]})]

    def _candidate(self, ctx: RunContext, p_value: float, fake: bool) -> Candidate:
        hid = ctx.ledger.register(hypothesis="h", family=["f"], test="t")
        recorded = ctx.ledger.analytic_test(hid, statistic=3.0, p_value=0.001, n_obs=10)
        return Candidate(
            key="t",
            analyzer=self.name,  # type: ignore[attr-defined]
            kind=FindingKind.ASSOCIATION,
            pattern_class=self.pattern_class,
            title="t",
            variables=[ColumnRef(column="x0")],
            hypothesis_id=hid,
            test="t",
            p_value=p_value if fake else recorded.p_value,
        )

    def refine(self, cand: Candidate, data: pl.DataFrame, ctx: RunContext) -> Candidate:
        return cand

    def render(self, finding: Finding) -> Lenses:
        return render_lenses(finding)


class _FakePValue(_Base):
    name: ClassVar[str] = "rogue.fake_p"

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        return [self._candidate(ctx, 1e-9, fake=True)]

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        raise AssertionError("never reached")


class _ReusesDiscoveryTest(_Base):
    name: ClassVar[str] = "rogue.reuse"

    def screen(self, task: Task, data: pl.DataFrame, ctx: RunContext) -> list[Candidate]:
        return [self._candidate(ctx, 0.0, fake=False)]

    def confirm(self, cand: Candidate, sealed: pl.DataFrame, ctx: RunContext) -> EvidenceDraft:
        # Double dipping: cite the exploration test as the confirmation.
        return EvidenceDraft(
            test="t",
            p_value=cand.p_value,
            hypothesis_ids=[cand.hypothesis_id],
            n=10,
            confirmation=Confirmation(
                status="pending",
                method="sealed_holdout",
                p_value=cand.p_value,
                hypothesis_ids=[cand.hypothesis_id],
            ),
        )


@pytest.mark.parametrize(
    ("analyzer", "message"),
    [(_FakePValue(), "Law 2"), (_ReusesDiscoveryTest(), "not its own confirmation test")],
)
def test_the_kernel_rejects_contract_violations(
    shifted: pl.DataFrame, analyzer: object, message: str
) -> None:
    with pytest.raises(ContractViolation, match=message):
        gh.discover(shifted, analyzers=[analyzer], budget="quick")  # type: ignore[list-item]
