# Contributing

Thank you for helping. EDAForge is a statistics engine first: correctness and
honesty come before features.

## Set up

```bash
uv sync            # Python 3.12 or 3.13; installs every workspace package and dev tool
tools/ci.sh        # what CI runs: ruff, pyright (strict), pytest, citation coverage, license gate
tools/ci.sh --with-gates   # also the slow statistical gates (section 16.3)
uv run pre-commit install  # optional: run the same checks before each commit
```

## Rules that reviews enforce

1. **Every p-value, permutation and bootstrap goes through `ctx.ledger`.** Analyzers that compute
   p-values elsewhere are rejected by the kernel (`ContractViolation`).
2. **Analyzers never grade themselves.** `confirm` returns an `EvidenceDraft`; the Rigor Kernel
   assigns the grade and the causal rung.
3. **Assumptions are checked, not assumed.** Declare each one as an `AssumptionSpec`; if a check
   is impossible, say so (`check=None`), and give a fallback or a downgrade.
4. **No number without a computation.** Lens templates only quote fields of the finding, through
   the formatting filters. Run the language linter (`lint_lenses`) on new templates.
5. **Reference equivalence.** Every statistical routine needs a test against a reference
   implementation or published values, plus a test of its behaviour under the null.
6. **Licenses.** New dependencies must pass `edaforge-license-gate`. Copyleft or non-commercial
   code belongs in a separate plugin repository.
7. **Citations.** Cite methods in docstrings and add the reference to
   `docs/references-supplement.toml` if section 21 does not have it; never type a DOI from
   memory.
8. **Decisions.** Record significant design decisions as ADRs in `docs/adr/`.
9. **Honesty.** When a test fails, report it. Do not weaken a test, a gate or the kernel to make
   it pass; if a test was wrong, explain why in the pull request.

## Writing an analyzer plugin

See `packages/edaforge-plugin-example`: it registers through the `edaforge.analyzers` entry point
and is enabled by listing its distribution under `plugins:` in `edaforge.yaml`.
