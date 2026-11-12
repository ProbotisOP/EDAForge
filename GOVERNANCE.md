# Governance

## Decision records

- The specification is [docs/PROJECT_PROMPT.md](docs/PROJECT_PROMPT.md). Changes to it go
  through a pull request together with an ADR.
- Every significant design decision is recorded as an ADR in `docs/adr/NNNN-title.md`, using
  [docs/adr/0000-template.md](docs/adr/0000-template.md). An ADR is never edited after it is
  accepted; a later ADR supersedes it.

## Non-negotiables

The Laws (specification section 2) and the Rigor Kernel (section 8) are not traded
for convenience, speed or a passing test. A change that weakens either needs an ADR, review by
two maintainers including one with statistical expertise, and an entry in the phase report.

## License policy

The core is Apache-2.0. Changes to `license-policy.toml` need an ADR (see
[docs/adr/0006-license-gate.md](docs/adr/0006-license-gate.md)). Copyleft and non-commercial
integrations live in separate plugin repositories.

## Maintainers

The project is in Phase 0 and has not yet named its maintainer group. Until it does, the
repository owner acts as the maintainer of record.
