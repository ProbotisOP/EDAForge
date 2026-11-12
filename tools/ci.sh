#!/usr/bin/env bash
# Local equivalent of the GitHub workflows (.github/workflows/ci.yml, license-gate.yml and
# stat-gates.yml). Usage: tools/ci.sh [--with-gates]
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$*"; }

step "uv sync --locked"
uv sync --locked
step "ruff check"
uv run ruff check .
step "ruff format --check"
uv run ruff format --check .
step "pyright (strict for library code)"
uv run pyright
step "pytest (not slow)"
uv run pytest -m "not slow" -q
step "citation coverage"
if [ -f docs/archive/PROJECT_PROMPT.v1.md ]; then
  uv run edaforge-verify-refs coverage
else
  echo "skipped: docs/archive/PROJECT_PROMPT.v1.md is not in this checkout"
fi
step "license gate: core closure"
uv run edaforge-license-gate python --root edaforge
step "license gate: every installed distribution"
uv run edaforge-license-gate python --installed
step "license gate: model weights"
uv run edaforge-license-gate weights --manifest model-weights.toml
step "license gate canary: a planted GPL dependency must be blocked"
set +e
uv run edaforge-license-gate python --root rootpkg --path tools/tests/fixtures/planted_gpl_site
status=$?
set -e
if [ "$status" -ne 1 ]; then
  echo "FAIL: the license gate did not block the planted GPL package (exit $status)"
  exit 1
fi
echo "ok: planted GPL dependency blocked"
if [ "${1:-}" = "--with-gates" ]; then
  step "statistical gates (slow)"
  uv run pytest -m "slow" -q --durations=10
fi
step "local CI passed"
