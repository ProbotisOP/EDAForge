---
version: 1
slug: "apps-web-src"
primary_target: "apps/web/src"
related_targets: []
---

# Surface Brief — EDAForge Web Studio (`apps/web/src`)

## Scope and Visitor Mode

- **Primary target:** `apps/web/src` (`/` Launchpad + `/p/:projectId/*` Analytical Workbench)
- **Visitor mode:** Hybrid — **Persuade / Experience** on the scroll-choreographed `/` Bento Launchpad & Interactive Showcase; **Operate** across `/p/:projectId/data`, `/connect`, `/discover`, `/report`, `/universe`, and `/finding`

## Audience, Job, Action & Constraints

- **Audience:** Data analysts, scientists, and ops leads running EDAForge locally on `127.0.0.1`.
- **Primary actions:** Create or open a workspace (or launch the 1-click seeded Demo Workspace), upload tables, audit quality & clean recipes, preview & align joins/units, run FDR + holdout discovery, explore the Data Universe, and export self-contained reports.
- **Constraints:** Preserve all Playwright `test_e2e_golden_path.py` selectors/flows, permissive license policy, WCAG AA (`>= 4.5:1`) contrast across Light and Dark Bento worlds, self-hosted WOFF2 fonts, `12px` minimum metadata floor, and `prefers-reduced-motion` alternatives.

## Direction contract

THESIS: An architectural Dual-World Bento Analytical Instrument that pairs RefUI's tactile floating-dock modularity and color-drenched matte Bento surfaces with uncompromising statistical rigor—refusing both neon-purple AI-startup slop and sterile grey spreadsheet monotony.

OWN-WORLD: Soft atmospheric mineral-mist outer frame (`#DFE9EC`) housing a floating slim vertical icon dock (`22px` pill radius) and a generous rounded stage (`28px` radius, `#F9FAFB`) with matte color-committed Bento tiles (sage-petrol `#D9ECE9`, warm terracotta-blush `#F6DFD6`, sunlit sand `#F3EAD8`, periwinkle-mist `#E1E7F8`, and deep forest-petrol `#1D3B40` feature chart tile) plus charcoal-ink pill CTAs (`#161B22`) in Light mode; morphing in Dark mode into RefUI 3's deep espresso-obsidian frame (`#0E0D11`), deep petrol-teal tiles (`#1B393E`), crisp alabaster contrast card (`#F3F5F7`), and electric sky-cyan accent block (`#4CC9F0`), set in Bricolage Grotesque display numerals/headings, Public Sans UI prose, and Azeret Mono code/ledger metrics.

STORY: On `/`, visitors immediately launch or resume workspaces (or spin up a 1-click realistic multi-table Demo Workspace), while scrolling reveals interactive, live-reactive Bento specimens proving how EDAForge catches `×100` unit bugs, blocks fan-out joins, confirms signals on sealed holdout splits, and maps column relationships; inside `/p/:projectId`, every pipeline stage operates as a calm, tactile Bento studio with scroll-linked compacting headers, URL-persisted triage filters, and hidden statistical Easter eggs (Anscombe/Simpson's Secret Lab, peeking vector Studio Inspector, scroll-vernier rail, and `?` shortcut HUD).

FIRST VIEWPORT: Floating top studio bar inside the rounded stage frame (`EDAForge` custom precision mark, `Ctrl K` search pill, theme/audio/HUD controls, scroll-vernier progress bar), asymmetric 12-column Bento hero grid with primary charcoal-pill Workspace Creator + 1-click Demo Dataset launcher on the left (`7 cols`), color-drenched live Telemetry & Active Workspaces Bento tiles on the right (`5 cols`), and recent workspace Bento cards immediately accessible above/at the fold.

FORM: `seed: none (pinned)` "Floating Dock + Dual-World Bento: Soft mineral/pastel Bento tiles + floating icon dock + rounded white stage in Light mode (RefUI 1/4/5), morphing into Deep Petrol, Alabaster & Cyan Bento on Obsidian in Dark mode (RefUI 3)" + "Full Bento Studio + Scroll-Choreographed Home: Launchpad on '/' with instant workspaces & 1-click Demo Data on top + scroll-driven interactive Bento storytelling below, plus scroll-linked headers, smooth route transitions & tactile card physics across every app screen"

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
