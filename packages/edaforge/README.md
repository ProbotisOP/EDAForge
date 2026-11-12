# edaforge

The engine of EDAForge: local-first, statistically rigorous, multi-file pattern
discovery.

EDAForge finds patterns with a measured false-alarm rate. Every number traces to a computation,
every candidate is tested against an explicit null in a global Hypothesis Ledger, discoveries
must be confirmed on data the search never touched, and every finding is explained through three
lenses (Plain, Analyst and Scientist) with a reproduce action. It does not find every pattern,
and it does not prove causation.

```python
import edaforge as gh

run = gh.discover(frames, plugins=["edaforge-plugin-example"])
for finding in run.findings.top(5):
    print(finding.evidence.grade, finding.title_plain)
run.export("report.html")
```

Status: pre-alpha (Phase 0, foundations). See `docs/PROJECT_PROMPT.md` in the repository for the
full specification and `docs/reports/` for what each phase delivered, failures included.

License: Apache-2.0.
