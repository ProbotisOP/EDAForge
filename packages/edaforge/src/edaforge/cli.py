"""Command-line interface (section 12.4).

Phase 0 commands: ``version``, ``run``, ``ledger``, ``reproduce`` and ``plugins``. ``analyze`` (the
full ingest, health and discovery pipeline) and ``serve`` arrive in Phases 1 and 7.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from edaforge.api import discover, ledger_entries, load_run, reproduce_from_directory
from edaforge.config import EDAForgeConfig, load_config
from edaforge.errors import EDAForgeError
from edaforge.models import LedgerEntry
from edaforge.plugins.registry import discover_plugins
from edaforge.runtime.manifest import edaforge_version

__all__ = ["main"]

_LEDGER_COLUMNS = (
    "hypothesis_id",
    "family_path",
    "analyzer",
    "analyzer_version",
    "test",
    "split",
    "status",
    "statistic",
    "p_value",
    "e_value",
    "n",
    "n_resamples",
    "parent_id",
    "frozen_at",
    "blind_violation",
    "created_at",
    "hypothesis",
)


def _neutralize(cell: str) -> str:
    """Neutralize spreadsheet formula injection in exported text (section 15)."""
    if cell[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + cell
    return cell


def _ledger_csv(entries: Sequence[LedgerEntry]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_LEDGER_COLUMNS)
    for entry in entries:
        row = entry.model_dump(mode="json")
        cells: list[str] = []
        for column in _LEDGER_COLUMNS:
            value = row[column]
            if column == "family_path":
                text = "/".join(str(v) for v in value)
            elif value is None:
                text = ""
            else:
                text = str(value)
            numeric = column in {"statistic", "p_value", "e_value", "n", "n_resamples"}
            cells.append(text if numeric else _neutralize(text))
        writer.writerow(cells)
    return buffer.getvalue()


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"edaforge {edaforge_version()}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config)) if args.config else EDAForgeConfig()
    run = discover(
        [Path(p) for p in args.files],
        config=config,
        targets=args.target or None,
        budget=args.budget,
        plugins=args.plugin or None,
        seed=args.seed,
    )
    out = run.save(Path(args.out))
    confirmed = sum(1 for f in run.findings if f.evidence.confirmation.status == "confirmed")
    print(f"run {run.run_id}: {len(run.findings)} findings ({confirmed} confirmed) -> {out}")
    for warning in run.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _cmd_ledger(args: argparse.Namespace) -> int:
    entries = ledger_entries(load_run(Path(args.run)))
    if args.format == "csv":
        sys.stdout.write(_ledger_csv(entries))
    else:
        for entry in entries:
            sys.stdout.write(entry.model_dump_json() + "\n")
    return 0


def _cmd_reproduce(args: argparse.Namespace) -> int:
    finding = reproduce_from_directory(Path(args.run), args.finding_id)
    print(f"{finding.id} reproduced exactly (run {finding.provenance.run_id})")
    return 0


def _cmd_plugins(_: argparse.Namespace) -> int:
    plugins = discover_plugins()
    if not plugins:
        print("no analyzer plugins installed")
    for plugin in plugins:
        print(f"{plugin.distribution} {plugin.version}: {plugin.entry_point} = {plugin.value}")
    print("enable a plugin by listing its distribution under `plugins:` in edaforge.yaml")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edaforge", description="EDAForge")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the version").set_defaults(func=_cmd_version)

    run = sub.add_parser("run", help="run discovery on CSV, TSV, Parquet or JSON files")
    run.add_argument("files", nargs="+")
    run.add_argument("--out", required=True, help="run directory to write")
    run.add_argument("--config", help="edaforge.yaml")
    run.add_argument("--target", action="append")
    run.add_argument("--budget", choices=["quick", "deep", "exhaustive"])
    run.add_argument("--plugin", action="append", help="enable an installed plugin distribution")
    run.add_argument("--seed", type=int)
    run.set_defaults(func=_cmd_run)

    ledger = sub.add_parser("ledger", help="print the Hypothesis Ledger of a run")
    ledger.add_argument("--run", required=True)
    ledger.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    ledger.set_defaults(func=_cmd_ledger)

    reproduce = sub.add_parser("reproduce", help="re-execute a finding from its provenance")
    reproduce.add_argument("finding_id")
    reproduce.add_argument("--run", required=True)
    reproduce.set_defaults(func=_cmd_reproduce)

    sub.add_parser("plugins", help="list installed analyzer plugins").set_defaults(
        func=_cmd_plugins
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args))
    except EDAForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
