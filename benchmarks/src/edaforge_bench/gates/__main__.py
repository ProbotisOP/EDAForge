"""Run the Proving Grounds gates from the command line: ``python -m edaforge_bench.gates``."""

from __future__ import annotations

import argparse
import sys

from edaforge_bench.gates import null_control_mean_shift, recall_mean_shift


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m edaforge_bench.gates")
    parser.add_argument("--datasets", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261110)
    args = parser.parse_args()
    results = [
        null_control_mean_shift(n_datasets=args.datasets, seed=args.seed),
        recall_mean_shift(n_datasets=max(10, args.datasets // 4), seed=args.seed + 1),
    ]
    for result in results:
        print(result.summary())
        for key, value in sorted(result.details.items()):
            print(f"    {key}: {value:.4g}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
