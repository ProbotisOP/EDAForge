import { useRef, useState } from "react";
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { CheckCircle2, Database, GitMerge, Scale, ShieldCheck } from "lucide-react";
import { playDetent, playTick } from "../lib/sound";

const US_BINS = [8, 22, 48, 76, 62, 34, 14, 4, 1, 0, 0, 0];
const EU_RAW_BINS = [0, 0, 0, 0, 0, 2, 11, 36, 68, 54, 24, 9];
const ALIGNED_BINS = [9, 26, 58, 94, 82, 46, 20, 7, 2, 0, 0, 0];

const FORMATS = [
  { ext: ".csv / .tsv", desc: "Auto-delimiter, encoding & messy-date repair" },
  { ext: ".xlsx", desc: "Multi-sheet workbook extraction (macros ignored)" },
  { ext: ".parquet", desc: "Zero-copy Polars columnar scan" },
  { ext: ".duckdb / .sqlite", desc: "Every table indexed read-only as a dataset" },
  { ext: ".mdb / .accdb", desc: "Legacy Microsoft Access tables without Office" },
  { ext: ".json / .dbf", desc: "Nested records, NDJSON logs & FoxPro archives" },
];

export function HomeShowcase({ onTryDemo, demoBusy }: { onTryDemo: () => void; demoBusy: boolean }) {
  const sectionRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start 85%", "end 25%"],
  });

  const [unitAligned, setUnitAligned] = useState(false);
  const [joinSafe, setJoinSafe] = useState(true);
  const [splitByRegion, setSplitByRegion] = useState(true);

  const yFloatSlow = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [16, -12]);
  const yFloatFast = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [24, -18]);
  const ribbonDash = useTransform(scrollYProgress, [0, 0.65], reduce ? [0, 0] : [140, 0]);

  return (
    <section ref={sectionRef} className="showcase-section" aria-labelledby="showcase-heading">
      <div className="showcase-head spread">
        <div>
          <h2 id="showcase-heading">Built to catch what summary dashboards miss</h2>
          <p className="muted">
            Interact with any sample specimen below — or load the 3-table demo dataset above to test them on real rows.
          </p>
        </div>
        <button
          type="button"
          className="btn"
          disabled={demoBusy}
          onClick={() => {
            playTick();
            onTryDemo();
          }}
        >
          <span>{demoBusy ? "Building demo…" : "Open in live studio →"}</span>
        </button>
      </div>

      <div className="showcase-bento-grid">
        {/* TILE 1: Sankey Ribbon Join Contract (RefUI #1 bottom-right ribbon flow widget!) */}
        <motion.article style={{ y: yFloatSlow }} className="bento-tile showcase-span-7 bento-surface-card">
          <div className="spread" style={{ marginBottom: 10, flexWrap: "wrap" }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="bento-icon-circle tone-petrol">
                <GitMerge size={16} />
              </span>
              <div>
                <h3>Pre-flight join contract before rows multiply</h3>
                <div className="small muted">Sample demo · inspect cardinality, unmatched keys, and fan-out risk</div>
              </div>
            </div>

            <div className="seg seg-xs" role="group" aria-label="Join mode">
              <button
                type="button"
                className={joinSafe ? "active" : ""}
                onClick={() => {
                  playDetent();
                  setJoinSafe(true);
                }}
              >
                <span className="seg-label-inner">1:1 / m:1 Safe</span>
              </button>
              <button
                type="button"
                className={!joinSafe ? "active" : ""}
                onClick={() => {
                  playDetent();
                  setJoinSafe(false);
                }}
              >
                <span className="seg-label-inner">m:m Fan-out</span>
              </button>
            </div>
          </div>

          <div className="sankey-widget">
            <div className="sankey-side-labels left">
              <span><i style={{ background: "#E06D53" }} /> customers_us.csv (897)</span>
              <span><i style={{ background: "#2A8C96" }} /> orders.xlsx (3,400)</span>
              <span><i style={{ background: "#D99B26" }} /> customers_eu.csv (603)</span>
            </div>

            <div className="sankey-flow-core">
              <svg viewBox="0 0 360 156" className="sankey-svg" preserveAspectRatio="none" role="img" aria-label="Multi-table join ribbon flow">
                <motion.path
                  d="M 4 24 C 95 24, 120 72, 170 76"
                  fill="none"
                  stroke="#E06D53"
                  strokeWidth="15"
                  strokeLinecap="round"
                  style={{ strokeDashoffset: ribbonDash }}
                  strokeDasharray="400"
                  opacity="0.88"
                />
                <motion.path
                  d="M 4 78 C 88 78, 120 78, 170 78"
                  fill="none"
                  stroke="#2A8C96"
                  strokeWidth="19"
                  strokeLinecap="round"
                  opacity="0.9"
                />
                <motion.path
                  d="M 4 132 C 95 132, 120 86, 170 80"
                  fill="none"
                  stroke="#D99B26"
                  strokeWidth="12"
                  strokeLinecap="round"
                  opacity="0.85"
                />

                <path
                  d="M 190 76 C 242 72, 268 38, 356 38"
                  fill="none"
                  stroke={joinSafe ? "#0F766E" : "#DC2626"}
                  strokeWidth={joinSafe ? "17" : "26"}
                  strokeLinecap="round"
                  opacity="0.88"
                />
                <path
                  d="M 190 82 C 242 86, 268 122, 356 122"
                  fill="none"
                  stroke={joinSafe ? "#3B82F6" : "#F59E0B"}
                  strokeWidth={joinSafe ? "11" : "20"}
                  strokeLinecap="round"
                  opacity="0.82"
                />
              </svg>

              <div className={`sankey-medallion${joinSafe ? "" : " warn"}`}>
                <span className="medallion-val tabular-nums">{joinSafe ? "3,400" : "9,840"}</span>
                <span className="medallion-sub">{joinSafe ? "1.00× base" : "2.89× fan-out"}</span>
              </div>
            </div>

            <div className="sankey-side-labels right">
              <strong>{joinSafe ? "Matched grain preserved" : "Row inflation blocked"}</strong>
              <span className="muted">{joinSafe ? "99.6% sample keys verified" : "Requires explicit review"}</span>
            </div>
          </div>
        </motion.article>

        {/* TILE 2: Unit Mismatch Rescale Bento */}
        <motion.article style={{ y: yFloatFast }} className="bento-tile showcase-span-5 bento-coral">
          <div className="spread" style={{ marginBottom: 10, flexWrap: "wrap" }}>
            <div className="row" style={{ gap: 9 }}>
              <span className="bento-icon-circle on-tinted">
                <Scale size={16} />
              </span>
              <h3>Cross-file unit guard (×100)</h3>
            </div>
            <button
              type="button"
              className={`bento-pill-toggle${unitAligned ? " active" : ""}`}
              onClick={() => {
                playDetent();
                setUnitAligned((v) => !v);
              }}
            >
              {unitAligned ? "✓ Rescaled ×0.01" : "Align EU cents → $"}
            </button>
          </div>

          <p className="bento-body-copy">
            {unitAligned
              ? "Sample medians aligned ($753 US vs $757 EU sample). Stacking now preserves true lifetime_value scale."
              : "Sample EU export stores lifetime_value in cents (75,700) while US sample stores dollars ($753 sample)."}
          </p>

          <div className="unit-bars-stage" aria-label="Unit distribution comparison">
            {(unitAligned ? ALIGNED_BINS : US_BINS).map((v, idx) => {
              const euVal = unitAligned ? 0 : EU_RAW_BINS[idx];
              return (
                <div key={idx} className="unit-bar-col">
                  <motion.div
                    className="unit-bar-us"
                    initial={false}
                    animate={{ height: `${Math.max(4, v * 0.92)}%` }}
                    transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 24 }}
                  />
                  {!unitAligned && euVal > 0 ? (
                    <motion.div
                      className="unit-bar-eu"
                      initial={{ height: 0 }}
                      animate={{ height: `${Math.max(4, euVal * 0.92)}%` }}
                      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 24 }}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>

          <div className="spread small" style={{ marginTop: 8, opacity: 0.86, flexWrap: "wrap" }}>
            <span className="tabular-nums">Sample range: 150–1,400 USD</span>
            <span className="tabular-nums">{unitAligned ? "Unified scale" : "15,000–140,000 cents"}</span>
          </div>
        </motion.article>

        {/* TILE 3: Deep Petrol Feature Tile — Simpson's Paradox & Sealed Holdout */}
        <motion.article style={{ y: yFloatSlow }} className="bento-tile showcase-span-6 bento-petrol">
          <div className="spread" style={{ marginBottom: 10, flexWrap: "wrap" }}>
            <div className="row" style={{ gap: 9 }}>
              <span className="bento-icon-circle on-dark">
                <ShieldCheck size={16} />
              </span>
              <div>
                <h3>Simpson’s paradox &amp; sealed holdout grading</h3>
                <div className="small bento-sub-on-dark">Sample demo · Benjamini–Hochberg FDR + 30% confirmation split</div>
              </div>
            </div>

            <button
              type="button"
              className="bento-dark-pill"
              onClick={() => {
                playDetent();
                setSplitByRegion((v) => !v);
              }}
            >
              {splitByRegion ? "Conditioned by region" : "Pooled aggregate"}
            </button>
          </div>

          <div className="paradox-stage">
            <svg viewBox="0 0 420 144" className="paradox-svg" role="img" aria-label="Simpson's paradox slope reversal">
              {splitByRegion ? (
                <>
                  <motion.line initial={{ opacity: 0.3 }} animate={{ opacity: 1 }} x1="34" y1="98" x2="118" y2="124" stroke="#5EEAD4" strokeWidth="3" strokeLinecap="round" />
                  <motion.line initial={{ opacity: 0.3 }} animate={{ opacity: 1 }} x1="118" y1="74" x2="206" y2="102" stroke="#4CC9F0" strokeWidth="3" strokeLinecap="round" />
                  <motion.line initial={{ opacity: 0.3 }} animate={{ opacity: 1 }} x1="204" y1="48" x2="296" y2="78" stroke="#FBBF24" strokeWidth="3" strokeLinecap="round" />
                  <motion.line initial={{ opacity: 0.3 }} animate={{ opacity: 1 }} x1="292" y1="22" x2="388" y2="54" stroke="#FB7185" strokeWidth="3" strokeLinecap="round" />
                </>
              ) : (
                <motion.line
                  initial={{ opacity: 0.3 }}
                  animate={{ opacity: 1 }}
                  x1="36"
                  y1="118"
                  x2="386"
                  y2="30"
                  stroke="#FBBF24"
                  strokeWidth="3.5"
                  strokeDasharray="7 5"
                  strokeLinecap="round"
                />
              )}
              {[
                [52, 102, "#5EEAD4"], [78, 112, "#5EEAD4"], [104, 120, "#5EEAD4"],
                [136, 79, "#4CC9F0"], [166, 89, "#4CC9F0"], [192, 97, "#4CC9F0"],
                [222, 54, "#FBBF24"], [252, 63, "#FBBF24"], [280, 73, "#FBBF24"],
                [310, 28, "#FB7185"], [342, 39, "#FB7185"], [372, 49, "#FB7185"],
              ].map(([cx, cy, fill], idx) => (
                <circle key={idx} cx={Number(cx)} cy={Number(cy)} r="4.5" fill={String(fill)} opacity="0.92" />
              ))}
            </svg>

            <div className="paradox-readout">
              <div>
                <div className="paradox-big tabular-nums">{splitByRegion ? "r = −0.52" : "r = +0.54"}</div>
                <div className="small bento-sub-on-dark">
                  {splitByRegion ? "Within every region (Grade A)" : "Naive pooled slope (misleading)"}
                </div>
              </div>
              <span className="paradox-grade-chip">Holdout verified</span>
            </div>
          </div>
        </motion.article>

        {/* TILE 4: Typographic Format Specification Ledger (No nested cards, no inert icon) */}
        <motion.article style={{ y: yFloatFast }} className="bento-tile showcase-span-6 bento-sage">
          <div className="row" style={{ gap: 10, marginBottom: 12 }}>
            <span className="bento-icon-circle on-tinted">
              <Database size={16} />
            </span>
            <div>
              <h3>Read-only local ingestion &amp; Polars/SQL export</h3>
              <div className="small" style={{ opacity: 0.84 }}>Original files are never mutated; every fix exports to code</div>
            </div>
          </div>

          <dl className="format-spec-ledger">
            {FORMATS.map((f) => (
              <div key={f.ext} className="format-spec-row">
                <dt className="mono">
                  <CheckCircle2 size={13} style={{ flexShrink: 0 }} aria-hidden="true" />
                  <span>{f.ext}</span>
                </dt>
                <dd>{f.desc}</dd>
              </div>
            ))}
          </dl>
        </motion.article>
      </div>
    </section>
  );
}
