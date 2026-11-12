# edaforge-plugin-example

An example analyzer plugin for EDAForge. It tests whether a numeric column's mean
differs between two environments (files, sites or periods), and it is the Phase 0 end-to-end
"dummy analyzer".

It shows the plugin contract:

- it registers through the `edaforge.analyzers` entry point (see `pyproject.toml`);
- it gets every p-value and bootstrap from `ctx.ledger`;
- `confirm` returns an `EvidenceDraft`, and the Rigor Kernel assigns the grade;
- it renders its three lenses with the core templates.

Enable it explicitly, after reviewing its license (Apache-2.0):

```yaml
plugins: [edaforge-plugin-example]
```
