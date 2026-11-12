"""``edaforge-license-gate``: fail the build on license-policy violations (section 13.3).

Examples::

    edaforge-license-gate python --root edaforge              # core runtime closure
    edaforge-license-gate python --installed                 # every installed distribution
    edaforge-license-gate npm --lockfile apps/web/package-lock.json
    edaforge-license-gate weights --manifest model-weights.toml

Exit codes: 0 pass, 1 violations, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from edaforge_devtools.license_gate.classify import Decision
from edaforge_devtools.license_gate.npm import check_npm_lockfile
from edaforge_devtools.license_gate.policy import load_policy
from edaforge_devtools.license_gate.python_env import (
    PackageVerdict,
    check_distributions,
    closure,
    installed,
)
from edaforge_devtools.license_gate.weights import check_weights_manifest

__all__ = ["main", "summarize"]

_LABEL = {
    Decision.ALLOWED: "ok",
    Decision.ALLOWED_UNMODIFIED: "ok (unmodified only)",
    Decision.UNKNOWN: "REVIEW",
    Decision.DENIED: "DENIED",
}


def summarize(results: Sequence[PackageVerdict], *, verbose: bool) -> str:
    lines: list[str] = []
    for r in sorted(results, key=lambda r: (r.verdict.decision, r.ecosystem, r.package.lower())):
        if not verbose and r.verdict.decision == Decision.ALLOWED:
            continue
        lines.append(
            f"{_LABEL[r.verdict.decision]:<21} {r.ecosystem:<13} {r.package}=={r.version}  "
            f"[{r.verdict.expression}] via {r.source}: {r.verdict.detail}"
        )
    failed = [r for r in results if r.failed]
    unmodified = [r for r in results if r.verdict.decision == Decision.ALLOWED_UNMODIFIED]
    lines.append(
        f"{len(results)} checked, {len(failed)} violations, "
        f"{len(unmodified)} allowed only as unmodified dependencies"
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edaforge-license-gate", description=__doc__)
    parser.add_argument("--policy", default="license-policy.toml")
    parser.add_argument("--json", help="also write the full results as JSON")
    parser.add_argument("--verbose", action="store_true", help="list allowed packages too")
    sub = parser.add_subparsers(dest="target", required=True)
    py = sub.add_parser("python")
    py.add_argument("--root", action="append", default=[], help="root distribution[extras]")
    py.add_argument("--installed", action="store_true", help="check every installed package")
    py.add_argument("--path", action="append", default=[], help="site directory to scan")
    npm = sub.add_parser("npm")
    npm.add_argument("--lockfile", action="append", required=True)
    weights = sub.add_parser("weights")
    weights.add_argument("--manifest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_policy(Path(args.policy))
        results: list[PackageVerdict] = []
        notes: list[str] = []
        if args.target == "python":
            paths = [Path(p) for p in args.path] or None
            if args.installed:
                results = check_distributions(installed(paths=paths), policy)
            if args.root:
                dists, missing = closure(args.root, paths=paths)
                if args.installed:
                    notes.append(f"closure of {', '.join(args.root)}: {len(dists)} distributions")
                else:
                    results = check_distributions(dists, policy)
                notes.extend(f"not installed (skipped): {m}" for m in missing)
            if not args.installed and not args.root:
                print("error: give --root and/or --installed", file=sys.stderr)
                return 2
        elif args.target == "npm":
            for lockfile in args.lockfile:
                results.extend(check_npm_lockfile(Path(lockfile), policy))
        else:
            results = check_weights_manifest(Path(args.manifest), policy)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(summarize(results, verbose=args.verbose))
    for note in notes:
        print(f"note: {note}")
    if args.json:
        payload = [
            {
                "ecosystem": r.ecosystem,
                "package": r.package,
                "version": r.version,
                "expression": r.verdict.expression,
                "elected": r.verdict.elected,
                "decision": r.verdict.decision.name,
                "source": r.source,
                "detail": r.verdict.detail,
            }
            for r in results
        ]
        Path(args.json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return 1 if any(r.failed for r in results) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
