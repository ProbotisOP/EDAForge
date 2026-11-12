# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through a GitHub security advisory on this repository
("Security" tab, "Report a vulnerability"). Do not open public issues for security problems.
We aim to acknowledge reports within five working days.

## Scope

EDAForge reads untrusted files and renders reports, so these classes of issue are
in scope:

- code or markup injection through file contents, column names or category labels (for example
  into HTML reports, Markdown lenses, CSV or Excel exports, or LLM prompts);
- path traversal, decompression bombs, XML external entities or macro execution during ingest;
- data leaving the machine without explicit opt-in (raw rows must never be sent to a remote
  LLM by default);
- bypasses of the Hypothesis Ledger that let an unledgered p-value reach a finding.

## Defaults

- The local web app binds to 127.0.0.1 and there is no telemetry.
- HTML reports contain no scripts and are served under a strict Content-Security-Policy.
- Exported spreadsheet cells are neutralized against formula injection.
- LLM narration is off by default and, when enabled, receives aggregates only.

## Supported versions

Pre-release: only the `main` branch receives fixes.
