# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Data analysts, data scientists, researchers, and operations leads working with real-world tabular exports (CSV, TSV, Excel, Parquet, JSON/JSONL) and embedded databases (SQLite, DuckDB, Microsoft Access, dBase) on their own computer. They need to audit messy exports, combine split regional or temporal tables without silent row multiplication or unit mismatches, surface statistically verified patterns, and export trustworthy reports without uploading private data to third-party cloud services.

## Product Purpose

EDAForge automates the tedious, error-prone mechanics of exploratory data analysis locally on `127.0.0.1`: column profiling, data-health scoring, reproducible cleaning recipes, pre-flight join verification, false-discovery-controlled pattern search, out-of-sample confirmation, and multi-lens reporting. Success means users catch data bugs (duplicates, cents-vs-dollars unit mismatches, fan-out joins, Simpson's paradox reversals) before drawing conclusions, and only act on findings backed by transparent effect sizes and confirmation grades.

## Positioning

Unlike BI dashboards or LLM chat wrappers that hallucinate insights or cherry-pick noise, EDAForge records every tested hypothesis in a deterministic statistical ledger, applies Benjamini-Hochberg false-discovery-rate correction across the entire search, confirms candidates on sealed holdout splits (or repeated cross-fitting on mid-sized tables), grades evidence A through E, flags formula-derived columns, and renders deterministic Plain / Analyst / Scientist explanations straight from the ledger.

## Operating Context

Runs locally in the browser against a local Python FastAPI + Polars engine (`http://127.0.0.1:8000`) storing workspaces in `~/.edaforge`. Core workflow spans 4 primary stages (`Data` -> `Connect` -> `Discover` -> `Report`) plus the interactive `Data Universe` relationship graph/matrix and `Finding` deep-dive inspector. Source files are opened read-only and never mutated; macros and database views are never executed.

## Capabilities and Constraints

- **Capabilities:** Multi-file upload with byte progress; column role inference & manual override; health gauge & rule-based quality checks; interactive ECharts subgroup/time/scatter/brush `ExploreStudio`; one-click cleaning recipes exportable to Python (Polars) and SQL; `SchemaGraph` ER diagram + live `LinkPreview` with row-multiplication guardrails and unit-mismatch rescaling; 5-intent discovery planner with live SSE progress; ranked `InsightFeed` with compact uncertainty charts; `Data Universe` (2D force network, chord ring, association matrix, and Three.js 3D view); inert self-contained HTML report export + CSV/JSON exports; `Ctrl+K` / `Cmd+K` command palette; tactile opt-in Web Audio cues (muted by default).
- **Technical & Legal Constraints:** Permissive-only dependency policy enforced by `license-policy.toml` and `apps/web/scripts/check-licenses.mjs`. Self-hosted fonts and zero mandatory cloud runtime dependencies. Must preserve Playwright golden-path e2e workflow (`packages/edaforge/tests/test_e2e_golden_path.py`) and full keyboard/WCAG AA accessibility.

## Brand Commitments

- **Name:** EDAForge
- **Pinned Visual Direction:** Floating Dock + Dual-World Bento inspired by `RefUI` prototypes — soft mineral/pastel matte Bento tiles, floating slim vertical icon dock, and rounded stage window in Light mode (`RefUI` 1/4/5), morphing into Deep Petrol, Alabaster & Sky-Cyan Bento blocks on deep obsidian in Dark mode (`RefUI` 3), with scroll-choreographed Bento storytelling on `/` and purposeful motion + craft Easter eggs throughout.
- **Anti-Slop Commitment:** Zero purple-to-blue AI gradients, zero gradient text, zero decorative glass cards over neon blobs, zero 1-sided colored card stripes, zero ALL-CAPS eyebrow kickers above headings, zero emoji UI icons, zero nested card-in-card border clutter, and zero fabricated social proof.

## Evidence on Hand

- Real local analytical engine (`packages/edaforge/`), real ECharts uncertainty & subgroup plots, real demo generator (`examples/demo/make_demo.py` producing `customers_us.csv`, `customers_eu.csv`, `orders.xlsx` with planted cents/dollars mismatch, duplicate orders, price regime jump, and regional Simpson's paradox reversal).
- Prototype visual references in `RefUI/`.
- No external customer testimonials, company logos, or cloud vanity metrics exist and none may be fabricated.

## Product Principles

1. **Epistemic honesty over hype:** Show uncertainty intervals, null results, sample sizes, and grade penalties alongside every headline.
2. **Pre-flight safety before transformation:** Preview row multiplication, key match rates, and unit mismatches before any join or clean recipe commits, while keeping original files untouched.
3. **Tactile modular clarity:** Group analytical telemetry into color-committed Bento surfaces with clear typographic hierarchy rather than nested bordered boxes.
4. **Motion with meaning:** Use scroll choreography, spatial continuity, and tactile micro-interactions to orient attention and reward curiosity without hiding content or slowing frequent tasks.

## Accessibility & Inclusion

WCAG AA contrast (`>= 4.5:1` for body/UI text and controls across every Bento surface in both Light and Dark modes), full keyboard navigation (focusable dataset rows, roving arrow-key tabs/segmented controls, focus-trapped dialogs), visible focus rings, `12px` minimum metadata floor, responsive mobile/tablet adaptation (`375px`–`1440px+`), and complete `prefers-reduced-motion` support.
