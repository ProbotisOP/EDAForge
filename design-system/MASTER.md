# EDAForge Design System — Master Source of Truth

## Visual World: Floating Dock + Dual-World Bento Studio
Synthesizes the prototype references in `RefUI/`:
- **Light Mode (`RefUI` 1, 4, 5):** Mineral-mist outer frame (`#DCE8EB`), floating white vertical pill dock (`24px` radius), rounded off-white stage (`#F6F9FA`, `28px` radius), matte color-drenched Bento tiles (Deep Petrol `#19383D`, Sage `#D7ECE7`, Terracotta `#F6DDD3`, Sand `#F1E7D2`, Periwinkle Sky `#DCE5FA`), and Charcoal-Petrol pill CTAs (`#152329`).
- **Dark Mode (`RefUI` 3):** Deep espresso-obsidian frame (`#0D0B0F`), dark petrol dock (`#151C20`), rounded stage (`#12171A`), Deep Petrol-Teal tiles (`#1C393E`), Alabaster high-contrast hero tile (`#ECF1F3`), and Sky-Cyan accent blocks (`#3EC1EC` / `#4CC9F0` with `#081B23` ink).

## Typography (Self-Hosted Variable WOFF2)
- **Display & Bento Numerals:** `Bricolage Grotesque` (`500–800`), `-0.022em` to `-0.035em` tracking, `tabular-nums`.
- **UI Body & Controls:** `Public Sans` (`400–700`), `13.5px` base, `60–72ch` measure.
- **Code & Statistical Ledger:** `Azeret Mono` (`400–600`), `12px` floor, reserved strictly for code, SQL/Polars recipes, IDs, and statistical expressions.

## Motion & Scroll Choreography
- **Scroll-Vernier Rail:** Live spring-damped `scaleX` progress bar along the stage rim.
- **Scroll-Choreographed Bento Deck (`/`):** Parallax Bento tiles + SVG Sankey ribbon flow + reactive unit-alignment & Simpson's paradox charts, all `opacity: 1` at rest.
- **Shared-Layout Springs:** `motion/react` `layoutId` pills on the floating dock, segmented controls, and soft pill tabs (`stiffness: 420, damping: 32`).
- **Child-Surface Hover Physics:** `.bento-hit:hover .bento-inner` lifts `-2px` while the outer hit target stays stationary.
- **Reduced Motion:** Full `prefers-reduced-motion` support across CSS and JS.

## Anti-Slop Guarantees
- Zero purple-to-blue gradients or gradient text.
- Zero ALL-CAPS eyebrow kickers above headings.
- Zero 1-sided colored card stripes or nested bordered card boxes.
- Zero emoji UI icons (`lucide-react` + bespoke geometric SVGs only).
