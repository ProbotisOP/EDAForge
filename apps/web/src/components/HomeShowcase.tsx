import { useRef, useState } from "react";
import { BarChart, ScatterChart, useXScale, useYScale } from "@mui/x-charts";
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { CheckCircle2, Database, GitMerge, Scale, ShieldCheck } from "lucide-react";
import { playDetent, playTick } from "../lib/sound";

const BIN_LABELS = [
  "$200",
  "$400",
  "$600",
  "$800",
  "$1.0k",
  "$1.2k",
  "20k¢",
  "40k¢",
  "60k¢",
  "80k¢",
  "100k¢",
  "120k¢",
];
const US_BINS = [12, 34, 68, 84, 52, 22, 0, 0, 0, 0, 0, 0];
const EU_RAW_BINS = [0, 0, 0, 0, 0, 0, 10, 29, 61, 76, 44, 18];
const EU_ALIGNED_BINS = [10, 29, 61, 76, 44, 18, 0, 0, 0, 0, 0, 0];

const PARADOX_REGIONS = [
  {
    id: "north",
    label: "North",
    color: "#5EEAD4",
    pts: [
      { id: "n1", x: 2.2, y: 4.8 },
      { id: "n2", x: 3.4, y: 4.3 },
      { id: "n3", x: 4.6, y: 3.9 },
      { id: "n4", x: 5.5, y: 3.5 },
    ],
    line: [
      [1.8, 5.0],
      [5.9, 3.3],
    ] as const,
  },
  {
    id: "south",
    label: "South",
    color: "#38BDF8",
    pts: [
      { id: "s1", x: 6.2, y: 6.4 },
      { id: "s2", x: 7.4, y: 5.9 },
      { id: "s3", x: 8.6, y: 5.5 },
      { id: "s4", x: 9.6, y: 5.1 },
    ],
    line: [
      [5.8, 6.6],
      [10.0, 4.9],
    ] as const,
  },
  {
    id: "east",
    label: "East",
    color: "#FBBF24",
    pts: [
      { id: "e1", x: 10.4, y: 8.0 },
      { id: "e2", x: 11.6, y: 7.5 },
      { id: "e3", x: 12.8, y: 7.0 },
      { id: "e4", x: 13.8, y: 6.6 },
    ],
    line: [
      [10.0, 8.2],
      [14.2, 6.4],
    ] as const,
  },
  {
    id: "west",
    label: "West",
    color: "#FB7185",
    pts: [
      { id: "w1", x: 14.6, y: 9.6 },
      { id: "w2", x: 15.8, y: 9.1 },
      { id: "w3", x: 17.0, y: 8.6 },
      { id: "w4", x: 18.2, y: 8.1 },
    ],
    line: [
      [14.2, 9.8],
      [18.6, 7.9],
    ] as const,
  },
];

function ParadoxRegressionLayer({ splitByRegion }: { splitByRegion: boolean }) {
  const xScale = useXScale<"linear">();
  const yScale = useYScale<"linear">();
  if (!xScale || !yScale) return null;

  if (splitByRegion) {
    return (
      <g pointerEvents="none">
        {PARADOX_REGIONS.map((rg) => {
          const x1 = xScale(rg.line[0][0]);
          const y1 = yScale(rg.line[0][1]);
          const x2 = xScale(rg.line[1][0]);
          const y2 = yScale(rg.line[1][1]);
          if (x1 === undefined || y1 === undefined || x2 === undefined || y2 === undefined) return null;
          return (
            <line
              key={rg.id}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={rg.color}
              strokeWidth={2.6}
              strokeLinecap="round"
            />
          );
        })}
      </g>
    );
  }

  const x1 = xScale(2.0);
  const y1 = yScale(3.9);
  const x2 = xScale(18.4);
  const y2 = yScale(9.1);
  if (x1 === undefined || y1 === undefined || x2 === undefined || y2 === undefined) return null;

  return (
    <line
      pointerEvents="none"
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke="#FBBF24"
      strokeWidth={3}
      strokeDasharray="7 5"
      strokeLinecap="round"
    />
  );
}

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
        {/* TILE 1: Sankey Ribbon Join Contract */}
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

        {/* TILE 2: Interactive MUI X BarChart Unit Mismatch Guard */}
        <motion.article style={{ y: yFloatFast }} className="bento-tile showcase-span-5 bento-coral">
          <div className="spread" style={{ marginBottom: 8, flexWrap: "wrap" }}>
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
              ? "Medians aligned ($753 US vs $757 EU). Stacking now preserves true lifetime_value scale."
              : "EU export stores lifetime_value in cents (75,700¢) while US stores dollars ($753)."}
          </p>

          <div style={{ margin: "2px -8px -6px" }}>
            <BarChart
              height={148}
              borderRadius={5}
              slotProps={{
                legend: { toggleVisibilityOnClick: true },
              }}
              margin={{ top: 4, right: 10, bottom: 24, left: 10 }}
              xAxis={[
                {
                  scaleType: "band",
                  data: unitAligned ? BIN_LABELS.slice(0, 6) : BIN_LABELS,
                  disableLine: true,
                  disableTicks: true,
                  height: 22,
                  categoryGapRatio: 0.24,
                  tickLabelStyle: { fontSize: 12, fill: "currentColor", opacity: 0.8 },
                },
              ]}
              yAxis={[{ disableLine: true, disableTicks: true, width: 0 }]}
              series={[
                {
                  id: "us-usd",
                  label: "US ($)",
                  color: "#156570",
                  data: unitAligned ? US_BINS.slice(0, 6) : US_BINS,
                  highlightScope: { highlight: "series", fade: "global" },
                  valueFormatter: (v) => `${v} rows`,
                },
                {
                  id: "eu-scale",
                  label: unitAligned ? "EU (rescaled $)" : "EU (raw ¢)",
                  color: "#C84B31",
                  data: unitAligned ? EU_ALIGNED_BINS.slice(0, 6) : EU_RAW_BINS,
                  highlightScope: { highlight: "series", fade: "global" },
                  valueFormatter: (v) => `${v} rows`,
                },
              ]}
            />
          </div>
        </motion.article>

        {/* TILE 3: Deep Petrol Feature Tile — Live MUI X ScatterChart Simpson's Paradox */}
        <motion.article style={{ y: yFloatSlow }} className="bento-tile showcase-span-6 bento-petrol">
          <div className="spread" style={{ marginBottom: 8, flexWrap: "wrap" }}>
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
            <div style={{ margin: "-4px -8px" }}>
              <ScatterChart
                height={158}
                hideLegend={!splitByRegion}
                slotProps={{
                  legend: { toggleVisibilityOnClick: true },
                }}
                grid={{ horizontal: true }}
                margin={{ top: 6, right: 12, bottom: 22, left: 6 }}
                xAxis={[
                  {
                    min: 1,
                    max: 19.5,
                    disableLine: true,
                    disableTicks: true,
                    height: 22,
                    tickLabelStyle: { fontSize: 12, fill: "rgba(243,249,250,0.72)" },
                  },
                ]}
                yAxis={[
                  {
                    min: 2.8,
                    max: 10.4,
                    disableLine: true,
                    disableTicks: true,
                    width: 28,
                    tickLabelStyle: { fontSize: 12, fill: "rgba(243,249,250,0.72)" },
                  },
                ]}
                series={
                  splitByRegion
                    ? PARADOX_REGIONS.map((rg) => ({
                        id: rg.id,
                        label: rg.label,
                        color: rg.color,
                        markerSize: 5.2,
                        data: rg.pts,
                        highlightScope: { highlight: "series" as const, fade: "global" as const },
                        valueFormatter: (pt: { x: number; y: number } | null) =>
                          pt ? `(${pt.x}, ${pt.y})` : "",
                      }))
                    : [
                        {
                          id: "pooled",
                          label: "All rows",
                          color: "#93C5FD",
                          markerSize: 5.2,
                          data: PARADOX_REGIONS.flatMap((rg) => rg.pts),
                          highlightScope: { highlight: "item" as const, fade: "global" as const },
                          valueFormatter: (pt: { x: number; y: number } | null) =>
                            pt ? `(${pt.x}, ${pt.y})` : "",
                        },
                      ]
                }
                sx={{
                  "& .MuiChartsGrid-line": {
                    stroke: "rgba(255,255,255,0.12)",
                    strokeDasharray: "3 4",
                  },
                  "& .MuiChartsLegend-label": {
                    color: "#F3F9FA !important",
                    fill: "#F3F9FA !important",
                    fontSize: 12,
                  },
                }}
              >
                <ParadoxRegressionLayer splitByRegion={splitByRegion} />
              </ScatterChart>
            </div>

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

        {/* TILE 4: Typographic Format Specification Ledger */}
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
