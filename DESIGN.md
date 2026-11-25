---
name: EDAForge
description: Local-first statistical discovery studio with Dual-World Bento architecture
colors:
  petrol-deep: "#19383D"
  petrol-brand: "#155861"
  charcoal-cta: "#152329"
  terracotta-coral: "#C84B31"
  bento-sage: "#D7ECE7"
  bento-coral: "#F6DDD3"
  bento-sand: "#F1E7D2"
  bento-sky: "#DCE5FA"
  mineral-frame: "#DCE8EB"
  stage-paper: "#F6F9FA"
  surface-white: "#FFFFFF"
  ink-primary: "#12191D"
  ink-muted: "#46545D"
  line-hairline: "#DDE5E8"
  obsidian-frame: "#0D0B0F"
  sky-cyan-dark: "#4CC9F0"
typography:
  display:
    fontFamily: "Bricolage Grotesque, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "2.375rem"
    fontWeight: 750
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Bricolage Grotesque, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.022em"
  title:
    fontFamily: "Bricolage Grotesque, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "0.96875rem"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Public Sans, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.84375rem"
    fontWeight: 400
    lineHeight: 1.52
  label:
    fontFamily: "Azeret Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  sm: "9px"
  md: "14px"
  bento: "20px"
  dock: "24px"
  stage: "28px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "12px"
  md: "18px"
  lg: "28px"
  xl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.charcoal-cta}"
    textColor: "{colors.surface-white}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "42px"
  button-secondary:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.pill}"
    padding: "0 14px"
    height: "35px"
  card-bento-petrol:
    backgroundColor: "{colors.petrol-deep}"
    textColor: "{colors.stage-paper}"
    rounded: "{rounded.bento}"
    padding: "20px 22px"
  card-bento-sage:
    backgroundColor: "{colors.bento-sage}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.bento}"
    padding: "16px 18px"
---

# Design System: EDAForge

## Overview

**Creative North Star: "The Tactile Statistical Bento Studio"**

EDAForge pairs warm, modular Bento architecture with uncompromising statistical precision. Rather than dressing a local analytical workbench in purple-neon AI-startup tropes or flattening it into an austere spreadsheet, the interface frames work inside an atmospheric outer mat (`#DCE8EB` mineral mist in Light mode; `#0D0B0F` warm obsidian in Dark mode) with a floating vertical pill dock and a generous rounded stage window (`28px` radius).

Inside the stage, primary telemetry, data-health gauges, join previews, and confirmation counts occupy matte, color-drenched Bento tiles—Deep Petrol, Sage Mint, Blush Terracotta, Sunlit Sand, and Periwinkle Sky in Light mode, morphing into Deep Petrol-Teal, high-contrast Alabaster, and Electric Sky-Cyan in Dark mode. Dense analytical artifacts—MUI X Charts (`@mui/x-charts` v9) IQR + 95% CI plots, schema ER diagrams, and tabular ledgers—sit on calm, high-contrast surfaces where uncertainty intervals carry visual priority.

**Key Characteristics:**
- Floating vertical pill dock (`24px` radius) separated cleanly from a rounded stage window (`28px` radius).
- Color-committed matte Bento tiles grouped by spatial gap (`14px–18px`) rather than nested borders or side stripes.
- Expressive geometric display numerals (`Bricolage Grotesque`) paired with neutral UI prose (`Public Sans`) and true code/ledger monospace (`Azeret Mono`).
- Purposeful, reduced-motion-safe choreography: scroll-vernier progress rail, spring `layoutId` pills, child-surface hover lift, and interactive Sankey/paradox specimens.

## Colors

A Dual-World mineral and petrol palette where color commits to whole Bento surfaces in Light and Dark modes while maintaining `>= 4.8:1` WCAG AA text contrast across every tile.

### Primary
- **Deep Petrol** (`#19383D`): Anchor surface for feature chart tiles, brand mark background, and statistical highlights.
- **Petrol Brand** (`#155861`): Interactive links, focus rings, active filter chips, and progress vernier in Light mode.
- **Charcoal Petrol CTA** (`#152329`): Primary pill button fill in Light mode, delivering `15.5:1` contrast against white labels.
- **Electric Sky-Cyan** (`#4CC9F0`): Primary action pill and focal Bento accent in Dark mode (`10.3:1` contrast with `#081B23` ink).

### Secondary
- **Terracotta Coral** (`#C84B31`): Unit-mismatch callouts, scatter specimen points, and Loupe's inspector cap.
- **Bento Sage** (`#D7ECE7` light / `#18332C` dark): Confirmed holdout metrics, healthy dataset scores (`>= 85`), and methods summary tiles.

### Tertiary
- **Bento Sand** (`#F1E7D2` light / `#332B1A` dark): Column counts, moderate Grade C badges, and secondary telemetry tiles.
- **Bento Periwinkle Sky** (`#DCE5FA` light / `#3EC1EC` dark): Row counts, interactive lab triggers, and hypothesis-ledger counters.

### Neutral
- **Mineral Mist Frame** (`#DCE8EB`) & **Obsidian Frame** (`#0D0B0F`): Outer viewport mat surrounding the floating dock and stage.
- **Stage Paper** (`#F6F9FA`) & **Dark Stage** (`#12171A`): Main rounded stage canvas.
- **Primary Ink** (`#12191D` light / `#EFF4F6` dark) & **Muted Ink** (`#46545D` light / `#A2B3BC` dark): High-legibility body and metadata text.

### Named Rules
**The Full-Surface Commitment Rule.** Color belongs to whole Bento tiles or genuine semantic badges (`Grade A–E`, `warning`, `critical`), never to 1-sided card stripes (`border-left`) or gradient text.

**The Dual-World Contrast Rule.** In Dark mode, exactly 1 focal telemetry tile may invert to crisp Alabaster (`#ECF1F3` with `#11181C` ink) to anchor visual hierarchy without washing out neighboring dark charts.

## Typography

**Display Font:** Bricolage Grotesque (with `-apple-system, BlinkMacSystemFont, sans-serif` fallback)
**Body Font:** Public Sans (with `-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif` fallback)
**Label/Mono Font:** Azeret Mono (with `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` fallback)

**Character:** `Bricolage Grotesque` gives oversized Bento numerals and view titles architectural warmth and unmistakable personality, while `Public Sans` keeps dense statistical explanations calm and scannable, and `Azeret Mono` marks exact formulas, SQL/Polars code, and test statistics.

### Hierarchy
- **Display** (`750`, `clamp(28px, 3.1vw, 38px)`, `1.12` line-height, `-0.03em` tracking): Launchpad headline and oversized Bento hero counters (`36px`).
- **Headline** (`700`, `20px–26px`, `1.2` line-height, `-0.022em` tracking): Route titles (`Data`, `Connect files`, `Discover`, `Report`) and dataset headers.
- **Title** (`650`, `15px–16px`, `1.25` line-height, `-0.015em` tracking): Bento tile headers, finding card headlines, and inspector panel titles.
- **Body** (`400–500`, `13.5px`, `1.52` line-height, `60–72ch` max measure): Explanations, quality rules, and form controls.
- **Label / Mono** (`500`, `12px` minimum floor, `tabular-nums`): Reserved strictly for code, SQL/Polars snippets, SHA/hypothesis IDs, numeric table cells, and statistical test readouts (`p`, `q`, `CI`, `r`).

### Named Rules
**The No-Eyebrow Rule.** Never place an uppercase tracked kicker or eyebrow label above a heading; headings carry their own hierarchy, with supporting context placed below.

**The 12px Ledger Floor Rule.** No statistical count, sample size, or column type may render below `12px`, and monospace classes never compound `em` scaling inside small footers.

## Layout

Desktop views (`> 920px`) use a 2-part floating shell inside a `30px 14px 14px`-padded outer frame (`max-width: 1640px`): a sticky `74px` slim floating icon pill dock (`24px` radius, expandable on demand to `234px`) paired with a detached bottom squircle preference pod (`22px` radius), and a fluid rounded stage window (`1fr`, `28px` radius). Inside the stage, content uses `22px 30px 48px` padding and modular CSS grids (`12`-column asymmetric Bento on `/`, `5`-tile KPI strip on `Data`, `4`-tile KPI row on `RunPage`, and sticky left filter/source rails paired with fluid workspaces).

Below `920px`, the floating dock collapses into a `54px` rounded mobile header bar with a slide-over drawer, and multi-column Bento rows reflow cleanly to `2` columns (`<= 920px`) and `1` column (`<= 600px`) with zero horizontal scroll.

## Elevation & Depth

Depth is established primarily through architectural framing (stage-on-mat contrast + matte tonal Bento blocks) supported by soft, downward-offset physical shadows—never zero-offset colored glows or frosted glass cards.

### Shadow Vocabulary
- **Stage Elevation** (`box-shadow: 0 20px 48px -18px rgba(15, 34, 40, 0.12), 0 2px 8px rgba(15, 34, 40, 0.04)`): Separates the floating dock and rounded stage window from the outer mineral/obsidian frame.
- **Card Rest** (`box-shadow: 0 4px 14px -4px rgba(15, 34, 40, 0.05)`): Subtle grounding on white/dark-slate data cards.
- **Floating Overlay** (`box-shadow: 0 18px 42px -10px rgba(15, 28, 34, 0.2), 0 4px 10px rgba(15, 28, 34, 0.07)`): Reserved for modals, command palette (`Ctrl+K`), tooltips, and sticky scrolled bars.

### Named Rules
**The Stationary Hit-Target Rule.** Interactive Bento cards keep their outer hit container motionless on hover while lifting `.bento-inner` by `-2px` (`cubic-bezier(0.16, 1, 0.3, 1)`), preventing pointer-edge flicker.

## Shapes

Radii step deliberately by structural scale so hierarchy is legible by silhouette alone:
- **Stage Window:** `28px` outer architectural container.
- **Floating Dock:** `24px` vertical navigation rail.
- **Bento Tiles & Modals:** `20px–22px` modular blocks.
- **Data Cards & ER Nodes:** `14px` analytical containers with `1px solid` hairlines.
- **Inputs & Code Chips:** `9px` form fields and `5px` inline code tokens.
- **Buttons, Badges & Segmented Controls:** `999px` tactile full pills.

## Components

### Buttons
- **Shape:** Full pill (`999px` radius), `35px` standard height (`42px` hero CTA, `29px` compact).
- **Primary:** Charcoal Petrol (`#152329`) with `#FFFFFF` text in Light mode; Electric Sky-Cyan (`#4CC9F0`) with `#081B23` text in Dark mode.
- **Hover / Focus:** `150ms` background shift (`#21363F` light / `#72D6F5` dark) and `2px solid` brand focus ring with `2px` offset.
- **Secondary / Ghost:** Surface fill with `--line-strong` border for secondary actions; borderless transparent fill for inline row utilities (`Rename`, `Delete`).

### Chips & Tabs
- **Style:** Soft pill containers (`13px` container radius on `.tabs`, `999px` on `.seg` and `.chip`) set on `--bg-subtle`.
- **State:** Active tab/segment slides a shared `motion/react` `layoutId` pill (`--surface` fill) behind the label; supports `ArrowLeft` / `ArrowRight` roving focus.

### Cards / Containers
- **Corner Style:** `20px` on tonal Bento tiles (`.bento-tile`); `14px` on bordered analytical panels (`.card`).
- **Background:** Matte tonal fills (`petrol`, `sage`, `coral`, `sand`, `sky`, `alabaster`) for summary KPIs; `--surface` for tables and ECharts canvases.
- **Internal Padding:** `20px 22px` on Bento tiles; `18px 20px` on `.card-pad`.

### Inputs / Fields
- **Style:** `35px` height (`42px` pill input on Launchpad), `1px solid var(--line-strong)` border on `--surface`, themed `--brand` caret.
- **Focus:** Border shifts to `--brand` with a `3px` soft ring (`var(--brand-soft)`).

### Navigation
- **Floating Slim Pill Dock + Detached Pod:** `74px` default sticky left icon rail (`24px` radius, expandable to `234px`) containing `BrandMark`, `Ctrl+K` search trigger, workspace back pill, 4 pipeline `NavLink` items (`Data`, `Connect`, `Discover`, `Report`) with an animated `dock-active-pill` background and tabular item counts, plus a separate detached bottom squircle pod (`22px` radius) housing Dual-World theme, shortcut (`?`), and opt-in sound controls.

### Signature Components
- **Sankey Join Medallion & Unit Guard:** Multi-ribbon Bezier flow with HTML side ledgers converging on a circular row-multiplication dial (`1.00× base`), paired with 1-click unit rescale pills (`× 100` / `× 0.01`).
- **Scroll-Vernier & Peeking Companion ("Loupe"):** A `3px` spring-damped scroll progress bar along the stage rim and a toggleable geometric vector inspector gripping the outer top rim of the rounded stage window from the `--frame-bg` mat (`RefUI` 1 homage) that shares statistical reminders and responds to the Konami code.

## Do's and Don'ts

### Do:
- **Do** group KPI metrics into color-committed matte Bento tiles (`20px` radius) with `Bricolage Grotesque` `tabular-nums` counters.
- **Do** keep every page element and compact chart at `opacity: 1` by default, using scroll progress to drive continuous data curves, ribbon flows, and header compaction.
- **Do** sync tabs and triage filters to URL search params with `{ replace: true }` so browser back-navigation preserves analyst context.
- **Do** provide full `prefers-reduced-motion` alternatives and verify `>= 4.5:1` contrast across both Light and Dark Bento worlds.

### Don't:
- **Don't** add uppercase tracked eyebrow labels above headings (`FEATURES`, `PIPELINE`, `OVERVIEW`).
- **Don't** use purple-to-blue gradients, `bg-clip-text` gradient headlines, neon drop-shadows, or frosted glass cards over blurred blobs.
- **Don't** put 1-sided colored borders (`border-left: 4px`) on cards or nest bordered cards inside bordered cards.
- **Don't** use emojis as UI icons or allow `Azeret Mono` metadata to shrink below `12px`.
