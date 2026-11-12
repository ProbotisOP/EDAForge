"""The Phase 0 CLI: run, ledger, reproduce, plugins, version."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import polars as pl
import pytest

from edaforge.cli import _neutralize, main
from edaforge_bench.generators import MultiEnvSpec, multi_environment


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    frame = multi_environment(MultiEnvSpec(n_per_env=1100, n_nodes=3, shift_size=0.5), seed=9).frame
    paths = []
    for env in ("E0", "E1"):
        path = tmp_path / f"site_{env}.csv"
        frame.filter(pl.col("__source__") == env).drop("__source__").write_csv(path)
        paths.append(path)
    return paths


def test_run_ledger_reproduce(
    files: list[Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "run"
    code = main(
        [
            "run",
            *map(str, files),
            "--out",
            str(out),
            "--plugin",
            "edaforge-plugin-example",
            "--budget",
            "quick",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "findings" in printed
    assert "confirmed" in printed
    for name in (
        "result.json",
        "manifest.json",
        "findings.json",
        "ledger.json",
        "events.jsonl",
        "report.html",
    ):
        assert (out / name).is_file(), name

    assert main(["ledger", "--run", str(out), "--format", "csv"]) == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0][:3] == ["hypothesis_id", "family_path", "analyzer"]
    assert len(rows) > 3

    finding_id = pl.read_json(out / "findings.json")["id"][0]
    assert main(["reproduce", finding_id, "--run", str(out)]) == 0
    assert "reproduced exactly" in capsys.readouterr().out


def test_errors_are_reported_without_tracebacks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ledger", "--run", str(tmp_path)]) == 2
    assert "not a run directory" in capsys.readouterr().err


def test_version_and_plugins(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert capsys.readouterr().out.startswith("edaforge ")
    assert main(["plugins"]) == 0
    assert "edaforge-plugin-example" in capsys.readouterr().out


@pytest.mark.parametrize("cell", ["=1+1", "+cmd", "-2", "@SUM(A1)"])
def test_csv_formula_injection_is_neutralized(cell: str) -> None:
    assert _neutralize(cell) == "'" + cell
    assert _neutralize("plain") == "plain"
