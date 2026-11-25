import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type WheelEvent,
} from "react";
import { createPortal, flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { ThemeProvider as MuiThemeProvider } from "@mui/material/styles";
import {
  barClasses,
  BarChart,
  ChartsBrushOverlay,
  ChartsContainer,
  ChartsGrid,
  ChartsReferenceLine,
  ChartsXAxis,
  ChartsYAxis,
  getValueToPositionMapper,
  LineChart,
  pieClasses,
  PieChart,
  radarClasses,
  RadarChart,
  ScatterChart,
  type ScatterItemIdentifier,
  useBrush,
  useDrawingArea,
  useXScale,
  useYScale,
} from "@mui/x-charts";
import {
  Crosshair,
  Download,
  FileSpreadsheet,
  GitBranch,
  Maximize2,
  RotateCcw,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { chartRows, type Interaction, toCsv } from "../lib/interactive";
import {
  adaptChartSpec,
  type AdaptedChart,
  type BarInterval,
  type BoxplotChartModel,
  type DrillTarget,
  fmtSmart,
  type ForestChartModel,
  type HeatmapChartModel,
  type HierarchyChartModel,
  type ScatterChartModel,
} from "../lib/muiChartsAdapter";
import {
  type ChartThemeTokens,
  createBentoMuiTheme,
  LIGHT_TOKENS,
  useTheme,
} from "../lib/theme";
import type { ChartSpec } from "../lib/types";
import { SpringSegmented } from "./kit";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

function download(name: string, href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function slug(text: string): string {
  return (
    (text || "chart")
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60)
      .toLowerCase() || "chart"
  );
}

function truncateLabel(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(4, maxChars - 1))}…`;
}

function parseHexRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "").trim();
  if (h.length === 3) {
    return [
      parseInt(h[0] + h[0], 16),
      parseInt(h[1] + h[1], 16),
      parseInt(h[2] + h[2], 16),
    ];
  }
  if (h.length >= 6) {
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  }
  return [21, 101, 112];
}

function interpolateRamp(ramp: string[], tRaw: number): { hex: string; lum: number } {
  const t = Math.max(0, Math.min(1, Number.isFinite(tRaw) ? tRaw : 0));
  if (!ramp.length) return { hex: "#156570", lum: 0.2 };
  if (ramp.length === 1) {
    const [r, g, b] = parseHexRgb(ramp[0]);
    return { hex: ramp[0], lum: (0.299 * r + 0.587 * g + 0.114 * b) / 255 };
  }
  const scaled = t * (ramp.length - 1);
  const idx = Math.min(ramp.length - 2, Math.floor(scaled));
  const frac = scaled - idx;
  const c0 = parseHexRgb(ramp[idx]);
  const c1 = parseHexRgb(ramp[idx + 1]);
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * frac);
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * frac);
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * frac);
  const hex = `#${[r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("")}`;
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return { hex, lum };
}

export interface BrushStats {
  count: number;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
  meanX: number;
  meanY: number;
  r: number | null;
}

function computeBrushStats(
  pts: { x: number; y: number }[],
  xRange: [number, number],
  yRange: [number, number],
): BrushStats | null {
  const [x0, x1] = xRange[0] <= xRange[1] ? xRange : [xRange[1], xRange[0]];
  const [y0, y1] = yRange[0] <= yRange[1] ? yRange : [yRange[1], yRange[0]];
  const sel = pts.filter((p) => p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1);
  if (!sel.length) return null;
  const mx = sel.reduce((s, p) => s + p.x, 0) / sel.length;
  const my = sel.reduce((s, p) => s + p.y, 0) / sel.length;
  let num = 0;
  let dx2 = 0;
  let dy2 = 0;
  for (const p of sel) {
    const dx = p.x - mx;
    const dy = p.y - my;
    num += dx * dy;
    dx2 += dx * dx;
    dy2 += dy * dy;
  }
  const r = sel.length >= 3 && dx2 > 0 && dy2 > 0 ? num / Math.sqrt(dx2 * dy2) : null;
  return { count: sel.length, xMin: x0, xMax: x1, yMin: y0, yMax: y1, meanX: mx, meanY: my, r };
}

export function serializeSvgFromContainer(
  container: HTMLElement,
  tokens: ChartThemeTokens,
  headerTitle?: string,
  headerSubtitle?: string,
): string | null {
  const liveSvg = container.querySelector("svg");
  if (!liveSvg) return null;

  const rect = liveSvg.getBoundingClientRect();
  const w = Math.max(320, Math.round(rect.width || Number(liveSvg.getAttribute("width")) || 680));
  const h = Math.max(180, Math.round(rect.height || Number(liveSvg.getAttribute("height")) || 280));
  const titleOffset = headerTitle ? (headerSubtitle ? 44 : 28) : 0;
  const totalH = h + titleOffset;

  const clone = liveSvg.cloneNode(true) as SVGSVGElement;

  const liveEls = liveSvg.querySelectorAll("*");
  const cloneEls = clone.querySelectorAll("*");
  const props = [
    "fill",
    "fill-opacity",
    "stroke",
    "stroke-width",
    "stroke-opacity",
    "stroke-dasharray",
    "stroke-linecap",
    "opacity",
    "font-family",
    "font-size",
    "font-weight",
  ];
  for (let i = 0; i < liveEls.length && i < cloneEls.length; i++) {
    const src = liveEls[i];
    const dst = cloneEls[i] as SVGElement;
    const cs = window.getComputedStyle(src);
    const inlineParts: string[] = [];
    for (const p of props) {
      const val = cs.getPropertyValue(p);
      if (val && val !== "initial" && val !== "normal") {
        inlineParts.push(`${p}:${val}`);
      }
    }
    if (inlineParts.length) {
      dst.setAttribute("style", `${dst.getAttribute("style") ?? ""};${inlineParts.join(";")}`);
    }
  }

  const ns = "http://www.w3.org/2000/svg";
  const out = document.createElementNS(ns, "svg");
  out.setAttribute("xmlns", ns);
  out.setAttribute("width", String(w));
  out.setAttribute("height", String(totalH));
  out.setAttribute("viewBox", `0 0 ${w} ${totalH}`);

  const bg = document.createElementNS(ns, "rect");
  bg.setAttribute("width", String(w));
  bg.setAttribute("height", String(totalH));
  bg.setAttribute("rx", "12");
  bg.setAttribute("fill", tokens.isDark ? "#182126" : "#FFFFFF");
  out.appendChild(bg);

  if (headerTitle) {
    const tEl = document.createElementNS(ns, "text");
    tEl.setAttribute("x", "16");
    tEl.setAttribute("y", "22");
    tEl.setAttribute("fill", tokens.text);
    tEl.setAttribute("font-family", "Bricolage Grotesque, Public Sans, sans-serif");
    tEl.setAttribute("font-size", "14");
    tEl.setAttribute("font-weight", "700");
    tEl.textContent = headerTitle;
    out.appendChild(tEl);

    if (headerSubtitle) {
      const sEl = document.createElementNS(ns, "text");
      sEl.setAttribute("x", "16");
      sEl.setAttribute("y", "38");
      sEl.setAttribute("fill", tokens.subtext);
      sEl.setAttribute("font-family", "Public Sans, sans-serif");
      sEl.setAttribute("font-size", "12");
      sEl.textContent = headerSubtitle;
      out.appendChild(sEl);
    }
  }

  const plotGroup = document.createElementNS(ns, "g");
  if (titleOffset > 0) {
    plotGroup.setAttribute("transform", `translate(0, ${titleOffset})`);
  }
  while (clone.firstChild) {
    plotGroup.appendChild(clone.firstChild);
  }
  out.appendChild(plotGroup);

  return new XMLSerializer().serializeToString(out);
}

export async function exportContainerAsPng(
  container: HTMLElement,
  filename: string,
  tokens: ChartThemeTokens,
  headerTitle?: string,
  headerSubtitle?: string,
): Promise<void> {
  const svgStr = serializeSvgFromContainer(container, tokens, headerTitle, headerSubtitle);
  if (!svgStr) return;

  const blob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("SVG rasterization failed"));
      img.src = url;
    });
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    download(filename, canvas.toDataURL("image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

export interface ChartProps {
  chart: ChartSpec;
  height?: number;
  compact?: boolean;
  interaction?: Interaction;
  onDrillTarget?: (target: DrillTarget) => void;
  onOpenExplorer?: () => void;
}

export function Chart({
  chart,
  height,
  compact = false,
  interaction,
  onDrillTarget,
  onOpenExplorer,
}: ChartProps) {
  const { tokens } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const [zoomSlider, setZoomSlider] = useState(false);
  const [brushActive, setBrushActive] = useState(false);
  const [brushStats, setBrushStats] = useState<BrushStats | null>(null);
  const [resetTick, setResetTick] = useState(0);
  const [viewId, setViewId] = useState<string>("");
  const surfaceHostRef = useRef<HTMLDivElement | null>(null);

  const mode: Interaction = interaction ?? (compact ? "hover" : "full");
  const specObj = chart.spec as Obj;
  const title = isObj(specObj.title)
    ? String((specObj.title as Obj).text ?? "")
    : String(specObj.title ?? chart.title ?? "");

  const baseAdapted = useMemo<AdaptedChart | null>(
    () => adaptChartSpec(specObj, tokens, compact),
    [specObj, tokens, compact],
  );

  useEffect(() => {
    setViewId(baseAdapted?.altViews?.[0]?.id ?? "");
  }, [specObj, baseAdapted?.altViews]);

  const adapted = useMemo<AdaptedChart | null>(() => {
    if (!baseAdapted) return null;
    if (!viewId || !baseAdapted.altViews?.length) return baseAdapted;
    const chosen = baseAdapted.altViews.find((v) => v.id === viewId);
    return chosen ? { ...baseAdapted, model: chosen.model } : baseAdapted;
  }, [baseAdapted, viewId]);

  const defaultHeight = compact
    ? (height ?? 172)
    : (height ??
      (adapted?.model.kind === "radar" || adapted?.model.kind === "pie"
        ? 300
        : typeof specObj.height === "number"
          ? Math.max(250, Math.min(420, specObj.height + 34))
          : 298));

  const hasDrill = Boolean(
    adapted &&
      (adapted.drillColumn ||
        (adapted.model.kind === "bar" && adapted.model.drillForIndex) ||
        (adapted.model.kind === "line" && adapted.model.drillForIndex) ||
        (adapted.model.kind === "scatter" && adapted.model.drillForSeries) ||
        (adapted.model.kind === "pie" && adapted.model.slices.some((s) => s.drill)) ||
        adapted.model.kind === "forest" ||
        adapted.model.kind === "heatmap" ||
        adapted.model.kind === "boxplot"),
  );

  const save = async (kind: "png" | "svg" | "csv") => {
    if (kind === "csv") {
      const blob = new Blob([toCsv(chartRows(specObj))], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      download(`${slug(title)}.csv`, url);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    if (kind === "svg") {
      const svg =
        (surfaceHostRef.current &&
          serializeSvgFromContainer(
            surfaceHostRef.current,
            tokens,
            adapted?.title ?? title,
            adapted?.subtitle,
          )) ||
        (await chartToSvg(chart, 840, tokens));
      const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      download(`${slug(title)}.svg`, url);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    if (surfaceHostRef.current) {
      await exportContainerAsPng(
        surfaceHostRef.current,
        `${slug(title)}.png`,
        tokens,
        adapted?.title ?? title,
        adapted?.subtitle,
      );
    }
  };

  return (
    <figure
      className={`chart-frame${mode === "full" ? " chart-live" : ""}`}
      aria-label={chart.alt_text}
    >
      {mode === "full" ? (
        <div className="chart-toolbar" role="toolbar" aria-label="Chart tools">
          <div className="chart-toolbar-left">
            {onOpenExplorer ? (
              <button
                type="button"
                className="chart-tool-pill accent"
                onClick={onOpenExplorer}
                title="Open subgroup & drill explorer"
              >
                <GitBranch size={13} />
                <span>Drill &amp; slice</span>
              </button>
            ) : null}

            {baseAdapted?.altViews && baseAdapted.altViews.length > 1 ? (
              <SpringSegmented<string>
                size="xs"
                role="group"
                ariaLabel="Chart view type"
                value={viewId || baseAdapted.altViews[0].id}
                onChange={(next) => {
                  setViewId(next);
                  setBrushActive(false);
                  setBrushStats(null);
                }}
                items={baseAdapted.altViews.map((v) => ({ id: v.id, label: v.label }))}
              />
            ) : null}

            {adapted?.canZoom &&
            (adapted.model.kind === "bar" ||
              adapted.model.kind === "line" ||
              adapted.model.kind === "scatter") ? (
              <button
                type="button"
                className={`chart-tool-pill${zoomSlider ? " active" : ""}`}
                onClick={() => setZoomSlider((v) => !v)}
                title="Toggle range zoom window"
              >
                <SlidersHorizontal size={13} />
                <span>Range</span>
              </button>
            ) : null}
            {adapted?.canBrush && adapted.model.kind === "scatter" ? (
              <button
                type="button"
                className={`chart-tool-pill${brushActive ? " active" : ""}`}
                onClick={() => {
                  setBrushActive((b) => {
                    const next = !b;
                    if (!next) setBrushStats(null);
                    return next;
                  });
                }}
                title="Drag a box over points to inspect cluster statistics"
              >
                <Crosshair size={13} />
                <span>Brush</span>
              </button>
            ) : null}
          </div>
          <div className="chart-toolbar-right">
            {adapted?.canZoom || brushStats ? (
              <button
                type="button"
                className="chart-icon-btn"
                onClick={() => {
                  setBrushActive(false);
                  setBrushStats(null);
                  setResetTick((t) => t + 1);
                }}
                title="Reset zoom & selection"
                aria-label="Reset zoom"
              >
                <RotateCcw size={13} />
              </button>
            ) : null}
            <button
              type="button"
              className="chart-icon-btn"
              onClick={() => setExpanded(true)}
              title="Fullscreen view"
              aria-label="Expand chart"
            >
              <Maximize2 size={13} />
            </button>
            <button
              type="button"
              className="chart-tool-pill"
              onClick={() => void save("png")}
              title="Export PNG"
              aria-label="Download PNG"
            >
              <Download size={12} />
              <span>PNG</span>
            </button>
            <button
              type="button"
              className="chart-tool-pill"
              onClick={() => void save("svg")}
              title="Export SVG"
              aria-label="Download SVG"
            >
              <span>SVG</span>
            </button>
            <button
              type="button"
              className="chart-tool-pill"
              onClick={() => void save("csv")}
              title="Download chart data as CSV"
              aria-label="Download data as CSV"
            >
              <FileSpreadsheet size={12} />
              <span>CSV</span>
            </button>
          </div>
        </div>
      ) : null}

      {!compact && (adapted?.title || adapted?.subtitle) ? (
        <div className="mui-chart-heading">
          {adapted.title ? <div className="mui-chart-title">{adapted.title}</div> : null}
          {adapted.subtitle ? <div className="mui-chart-subtitle">{adapted.subtitle}</div> : null}
        </div>
      ) : null}

      {brushStats ? (
        <div className="brush-banner">
          <div className="row-wrap" style={{ gap: 12 }}>
            <span className="badge b-brand">{brushStats.count.toLocaleString()} points brushed</span>
            <span className="mono small">
              X: [{brushStats.xMin.toPrecision(3)}, {brushStats.xMax.toPrecision(3)}] (μ=
              {brushStats.meanX.toPrecision(3)})
            </span>
            <span className="mono small">
              Y: [{brushStats.yMin.toPrecision(3)}, {brushStats.yMax.toPrecision(3)}] (μ=
              {brushStats.meanY.toPrecision(3)})
            </span>
            {brushStats.r !== null ? (
              <span className="mono small">
                Cluster r ={" "}
                <b>
                  {brushStats.r >= 0 ? "+" : ""}
                  {brushStats.r.toFixed(3)}
                </b>
              </span>
            ) : null}
          </div>
          {onDrillTarget ? (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() =>
                onDrillTarget({
                  low: brushStats.xMin,
                  high: brushStats.xMax,
                })
              }
            >
              Drill into cluster →
            </button>
          ) : null}
        </div>
      ) : null}

      {adapted ? (
        <MuiChartSurface
          adapted={adapted}
          height={defaultHeight}
          compact={compact}
          showRangeControls={zoomSlider}
          brushActive={brushActive}
          resetTick={resetTick}
          hostRef={surfaceHostRef}
          onBrushStats={setBrushStats}
          onDrillTarget={mode === "full" ? onDrillTarget : undefined}
        />
      ) : (
        <div className="chart-error">No renderable data in specification.</div>
      )}

      {mode === "full" && adapted ? (
        <div className="chart-footer-hint">
          {hasDrill && onDrillTarget ? "Click any mark or slice to drill down · " : ""}
          {adapted.canZoom ? "Scroll or use Range to zoom · " : ""}
          Hover marks to highlight &amp; inspect · Click legend items to toggle series
        </div>
      ) : null}

      {expanded && adapted ? (
        <ExpandedChartModal
          chart={chart}
          title={title}
          initialViewId={viewId}
          onClose={() => setExpanded(false)}
          onDrillTarget={onDrillTarget}
        />
      ) : null}
    </figure>
  );
}

interface FloatTipState {
  x: number;
  y: number;
  lines: string[];
}

function PieCenterLabel({ value, label, tokens }: { value?: string; label?: string; tokens: ChartThemeTokens }) {
  const { left, top, width, height } = useDrawingArea();
  if (!value) return null;
  const cx = left + width / 2;
  const cy = top + height / 2;
  return (
    <g pointerEvents="none">
      <text
        x={cx}
        y={label ? cy - 3 : cy + 5}
        textAnchor="middle"
        fill={tokens.text}
        fontSize={16}
        fontWeight={750}
        fontFamily="var(--display)"
      >
        {value}
      </text>
      {label ? (
        <text
          x={cx}
          y={cy + 14}
          textAnchor="middle"
          fill={tokens.subtext}
          fontSize={12}
          fontFamily="var(--sans)"
        >
          {label}
        </text>
      ) : null}
    </g>
  );
}

function ForestSvgLayer({
  model,
  tokens,
  compact,
  onHover,
  onDrill,
}: {
  model: ForestChartModel;
  tokens: ChartThemeTokens;
  compact: boolean;
  onHover: (tip: FloatTipState | null) => void;
  onDrill?: (target: DrillTarget) => void;
}) {
  const xScale = useXScale<"linear">();
  const yScale = useYScale<"band">();
  const { left, width } = useDrawingArea();
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (!xScale || !yScale) return null;
  const mapY = getValueToPositionMapper(yScale);
  const bandH = typeof yScale.bandwidth === "function" ? yScale.bandwidth() : 24;

  return (
    <g className="mui-forest-layer">
      {model.rows.map((r, idx) => {
        const cy = mapY(r.label);
        const px = xScale(r.point);
        const lx = xScale(r.low);
        const hx = xScale(r.high);
        if (cy === undefined || px === undefined || lx === undefined || hx === undefined) return null;

        const q1x = r.q1 !== undefined ? xScale(r.q1) : undefined;
        const q3x = r.q3 !== undefined ? xScale(r.q3) : undefined;
        const capH = compact ? 4 : 5;
        const iqrH = Math.min(bandH * 0.58, compact ? 11 : 15);
        const isHov = hoveredIdx === idx;
        const faded = hoveredIdx !== null && !isHov;

        return (
          <g
            key={r.label}
            style={{
              cursor: onDrill && r.drill ? "pointer" : "default",
              opacity: faded ? 0.35 : 1,
              transition: "opacity 0.16s ease",
            }}
            onMouseEnter={(e) => {
              setHoveredIdx(idx);
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines: r.tooltipLines,
              });
            }}
            onMouseMove={(e) => {
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines: r.tooltipLines,
              });
            }}
            onMouseLeave={() => {
              setHoveredIdx(null);
              onHover(null);
            }}
            onClick={() => {
              if (onDrill && r.drill) onDrill(r.drill);
            }}
          >
            <rect
              x={left}
              y={cy - bandH / 2}
              width={Math.max(0, width)}
              height={bandH}
              rx={7}
              fill={isHov ? tokens.primarySoft : "transparent"}
              opacity={isHov ? 0.5 : 0}
            />
            {q1x !== undefined && q3x !== undefined ? (
              <rect
                x={Math.min(q1x, q3x)}
                y={cy - iqrH / 2}
                width={Math.max(3, Math.abs(q3x - q1x))}
                height={iqrH}
                rx={iqrH / 2}
                fill={r.color}
                fillOpacity={0.22}
                stroke={r.color}
                strokeOpacity={0.45}
                strokeWidth={1}
              />
            ) : null}
            <line
              x1={lx}
              y1={cy}
              x2={hx}
              y2={cy}
              stroke={r.color}
              strokeWidth={compact ? 2.2 : 2.6}
              strokeLinecap="round"
            />
            <line
              x1={lx}
              y1={cy - capH}
              x2={lx}
              y2={cy + capH}
              stroke={r.color}
              strokeWidth={2}
              strokeLinecap="round"
            />
            <line
              x1={hx}
              y1={cy - capH}
              x2={hx}
              y2={cy + capH}
              stroke={r.color}
              strokeWidth={2}
              strokeLinecap="round"
            />
            <circle
              cx={px}
              cy={cy}
              r={compact ? 4.8 : 6}
              fill={r.color}
              stroke={tokens.tooltipBg}
              strokeWidth={2.2}
            />
            {!compact && r.n !== undefined ? (
              <text
                x={Math.min(left + width - 4, Math.max(hx, q3x ?? hx) + 8)}
                y={cy + 4}
                fill={tokens.subtext}
                fontSize={12}
                fontFamily="var(--mono)"
              >
                n={r.n.toLocaleString()}
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function BarIntervalLayer({
  categories,
  intervals,
  layout,
  isLollipop,
  compact,
  tokens,
}: {
  categories: string[];
  intervals: BarInterval[];
  layout: "horizontal" | "vertical";
  isLollipop?: boolean;
  compact?: boolean;
  tokens: ChartThemeTokens;
}) {
  const xScale = useXScale();
  const yScale = useYScale();
  const { left, width } = useDrawingArea();
  if (!xScale || !yScale) return null;

  if (layout === "horizontal") {
    const mapY = getValueToPositionMapper(yScale);
    const valX = xScale as unknown as (v: number) => number | undefined;
    return (
      <g pointerEvents="none">
        {intervals.map((iv) => {
          const cat = categories[iv.index];
          if (cat === undefined) return null;
          const cy = mapY(cat);
          const lx = valX(iv.low);
          const hx = valX(iv.high);
          const px = iv.point !== undefined ? valX(iv.point) : undefined;
          if (cy === undefined || lx === undefined || hx === undefined) return null;
          const col = iv.color ?? tokens.text;
          const rightEdge = Math.max(lx, hx, px ?? hx);
          return (
            <g key={iv.index}>
              {Math.abs(hx - lx) > 0.5 ? (
                <>
                  <line
                    x1={lx}
                    y1={cy}
                    x2={hx}
                    y2={cy}
                    stroke={col}
                    strokeWidth={2.2}
                    strokeLinecap="round"
                  />
                  <line x1={lx} y1={cy - 4.5} x2={lx} y2={cy + 4.5} stroke={col} strokeWidth={1.8} />
                  <line x1={hx} y1={cy - 4.5} x2={hx} y2={cy + 4.5} stroke={col} strokeWidth={1.8} />
                </>
              ) : null}
              {px !== undefined ? (
                <circle
                  cx={px}
                  cy={cy}
                  r={isLollipop ? 5.8 : 4}
                  fill={isLollipop ? tokens.primary : tokens.tooltipBg}
                  stroke={isLollipop ? tokens.tooltipBg : col}
                  strokeWidth={2}
                />
              ) : null}
              {!compact && iv.n !== undefined && rightEdge + 54 < left + width ? (
                <text
                  x={rightEdge + 8}
                  y={cy + 4}
                  fill={tokens.subtext}
                  fontSize={12}
                  fontFamily="var(--mono)"
                >
                  n={iv.n.toLocaleString()}
                </text>
              ) : null}
            </g>
          );
        })}
      </g>
    );
  }

  const mapX = getValueToPositionMapper(xScale);
  const valY = yScale as unknown as (v: number) => number | undefined;
  return (
    <g pointerEvents="none">
      {intervals.map((iv) => {
        const cat = categories[iv.index];
        if (cat === undefined) return null;
        const cx = mapX(cat);
        const ly = valY(iv.low);
        const hy = valY(iv.high);
        if (cx === undefined || ly === undefined || hy === undefined) return null;
        const col = iv.color ?? tokens.text;
        return (
          <g key={iv.index}>
            <line x1={cx} y1={ly} x2={cx} y2={hy} stroke={col} strokeWidth={2} />
            <line x1={cx - 4} y1={ly} x2={cx + 4} y2={ly} stroke={col} strokeWidth={1.6} />
            <line x1={cx - 4} y1={hy} x2={cx + 4} y2={hy} stroke={col} strokeWidth={1.6} />
          </g>
        );
      })}
    </g>
  );
}

function ScatterExtrasLayer({
  model,
  tokens,
  brushActive,
  scatterPoints,
  resetTick,
  onBrushStats,
}: {
  model: ScatterChartModel;
  tokens: ChartThemeTokens;
  brushActive: boolean;
  scatterPoints?: { x: number; y: number }[];
  resetTick: number;
  onBrushStats?: (stats: BrushStats | null) => void;
}) {
  const clipId = useId().replace(/:/g, "");
  const { left, top, width, height } = useDrawingArea();
  const xScale = useXScale<"linear">();
  const yScale = useYScale<"linear">();
  const brush = useBrush();
  const [savedBox, setSavedBox] = useState<[number, number, number, number] | null>(null);

  useEffect(() => {
    setSavedBox(null);
  }, [resetTick, brushActive]);

  useEffect(() => {
    if (!brushActive || !brush || !scatterPoints?.length || !onBrushStats) return;
    if (typeof xScale?.invert !== "function" || typeof yScale?.invert !== "function") return;
    const dx = Math.abs(brush.current.x - brush.start.x);
    const dy = Math.abs(brush.current.y - brush.start.y);
    if (dx < 5 || dy < 5) return;
    const x0 = xScale.invert(Math.min(brush.start.x, brush.current.x));
    const x1 = xScale.invert(Math.max(brush.start.x, brush.current.x));
    const y0 = yScale.invert(Math.max(brush.start.y, brush.current.y));
    const y1 = yScale.invert(Math.min(brush.start.y, brush.current.y));
    setSavedBox([x0, x1, y0, y1]);
    onBrushStats(computeBrushStats(scatterPoints, [x0, x1], [y0, y1]));
  }, [brush, brushActive, scatterPoints, onBrushStats, xScale, yScale]);

  if (!xScale || !yScale) return null;

  let bandPointsStr = "";
  if (model.band && model.band.length >= 2) {
    const upper = model.band.map((b) => `${xScale(b.x)},${yScale(b.high)}`);
    const lower = [...model.band].reverse().map((b) => `${xScale(b.x)},${yScale(b.low)}`);
    bandPointsStr = [...upper, ...lower].join(" ");
  }

  const haloSeries = model.series.filter((s) => s.halo);

  return (
    <g pointerEvents="none">
      <defs>
        <clipPath id={`scatter-clip-${clipId}`}>
          <rect x={left} y={top} width={Math.max(0, width)} height={Math.max(0, height)} />
        </clipPath>
      </defs>
      <g clipPath={`url(#scatter-clip-${clipId})`}>
        {model.densityCells?.map((cell, idx) => {
          const px0 = xScale(cell.x0);
          const px1 = xScale(cell.x1);
          const py0 = yScale(cell.y1);
          const py1 = yScale(cell.y0);
          if (px0 === undefined || px1 === undefined || py0 === undefined || py1 === undefined) return null;
          return (
            <rect
              key={idx}
              x={Math.min(px0, px1)}
              y={Math.min(py0, py1)}
              width={Math.max(1.5, Math.abs(px1 - px0) - 0.6)}
              height={Math.max(1.5, Math.abs(py1 - py0) - 0.6)}
              rx={3}
              fill={tokens.primary}
              fillOpacity={0.14 + 0.72 * cell.share}
            />
          );
        })}

        {bandPointsStr ? <polygon points={bandPointsStr} fill={tokens.bandFill} /> : null}

        {haloSeries.flatMap((s) =>
          s.data.map((pt) => {
            const cx = xScale(pt.x);
            const cy = yScale(pt.y);
            if (cx === undefined || cy === undefined) return null;
            return (
              <circle
                key={`halo-${s.id}-${pt.id}`}
                cx={cx}
                cy={cy}
                r={s.markerSize + 4.5}
                fill={s.color}
                fillOpacity={0.2}
                stroke={s.color}
                strokeOpacity={0.5}
                strokeWidth={1.2}
              />
            );
          }),
        )}

        {model.lines?.map((ln, idx) => {
          if (ln.points.length < 2) return null;
          const d = ln.points
            .map((pt, i) => `${i === 0 ? "M" : "L"} ${xScale(pt.x)} ${yScale(pt.y)}`)
            .join(" ");
          return (
            <path
              key={`${ln.label}-${idx}`}
              d={d}
              fill="none"
              stroke={ln.color}
              strokeWidth={ln.width ?? 2.8}
              strokeDasharray={ln.dashed ? "6 4" : undefined}
              strokeLinecap="round"
            />
          );
        })}

        {savedBox && !brush ? (
          <rect
            x={Math.min(xScale(savedBox[0]) ?? 0, xScale(savedBox[1]) ?? 0)}
            y={Math.min(yScale(savedBox[2]) ?? 0, yScale(savedBox[3]) ?? 0)}
            width={Math.abs((xScale(savedBox[1]) ?? 0) - (xScale(savedBox[0]) ?? 0))}
            height={Math.abs((yScale(savedBox[3]) ?? 0) - (yScale(savedBox[2]) ?? 0))}
            rx={6}
            fill={tokens.primarySoft}
            fillOpacity={0.35}
            stroke={tokens.primary}
            strokeWidth={1.5}
            strokeDasharray="5 3"
          />
        ) : null}
      </g>
    </g>
  );
}

function MatrixHeatmapLayer({
  model,
  tokens,
  compact,
  onHover,
  onDrill,
}: {
  model: HeatmapChartModel;
  tokens: ChartThemeTokens;
  compact: boolean;
  onHover: (tip: FloatTipState | null) => void;
  onDrill?: (target: DrillTarget) => void;
}) {
  const xScale = useXScale<"band">();
  const yScale = useYScale<"band">();
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  if (!xScale || !yScale) return null;

  const bwX = typeof xScale.bandwidth === "function" ? xScale.bandwidth() : 28;
  const bwY = typeof yScale.bandwidth === "function" ? yScale.bandwidth() : 24;
  const span = Math.max(1e-9, model.max - model.min);
  const showLabels =
    !compact && model.xCategories.length <= 12 && model.yCategories.length <= 12 && bwX >= 28 && bwY >= 20;

  return (
    <g className="mui-heatmap-layer">
      {model.cells.map((cell, idx) => {
        const xCat = model.xCategories[cell.xi];
        const yCat = model.yCategories[cell.yi];
        if (xCat === undefined || yCat === undefined) return null;
        const x0 = xScale(xCat);
        const y0 = yScale(yCat);
        if (x0 === undefined || y0 === undefined) return null;

        const norm = (cell.value - model.min) / span;
        const { hex, lum } = interpolateRamp(model.ramp, norm);
        const labelInk = lum > 0.54 ? "#12191D" : "#F8FAFC";
        const pad = 2.5;
        const w = Math.max(2, bwX - pad * 2);
        const h = Math.max(2, bwY - pad * 2);
        const textLabel = cell.badge ?? fmtSmart(cell.value, model.isPercent);
        const key = `${cell.xi}-${cell.yi}-${idx}`;
        const isHov = hoveredKey === key;

        return (
          <g
            key={key}
            style={{ cursor: onDrill && cell.drill ? "pointer" : "default" }}
            onMouseEnter={(e) => {
              setHoveredKey(key);
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines: cell.tooltipLines,
              });
            }}
            onMouseMove={(e) => {
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines: cell.tooltipLines,
              });
            }}
            onMouseLeave={() => {
              setHoveredKey(null);
              onHover(null);
            }}
            onClick={() => {
              if (onDrill && cell.drill) onDrill(cell.drill);
            }}
          >
            <rect
              x={x0 + pad}
              y={y0 + pad}
              width={w}
              height={h}
              rx={7}
              fill={hex}
              stroke={cell.selected ? tokens.warning : isHov ? tokens.text : "transparent"}
              strokeWidth={cell.selected ? 2.4 : isHov ? 1.8 : 0}
            />
            {showLabels ? (
              <text
                x={x0 + bwX / 2}
                y={y0 + bwY / 2 + 4}
                textAnchor="middle"
                fill={labelInk}
                fontSize={12}
                fontWeight={650}
                fontFamily="var(--sans)"
              >
                {textLabel}
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function BoxplotSvgLayer({
  model,
  tokens,
  onHover,
  onDrill,
}: {
  model: BoxplotChartModel;
  tokens: ChartThemeTokens;
  onHover: (tip: FloatTipState | null) => void;
  onDrill?: (target: DrillTarget) => void;
}) {
  const xScale = useXScale<"linear">();
  const yScale = useYScale<"band">();
  const { left, width } = useDrawingArea();
  const [hoveredCat, setHoveredCat] = useState<string | null>(null);
  if (!xScale || !yScale) return null;

  const mapY = getValueToPositionMapper(yScale);
  const bandH = typeof yScale.bandwidth === "function" ? yScale.bandwidth() : 28;
  const boxH = Math.min(22, Math.max(11, bandH * 0.58));

  return (
    <g className="mui-boxplot-layer">
      {model.rows.map((r, idx) => {
        const cy = mapY(r.category);
        const minX = xScale(r.min);
        const q1X = xScale(r.q1);
        const medX = xScale(r.median);
        const q3X = xScale(r.q3);
        const maxX = xScale(r.max);
        const meanX = xScale(r.mean);
        if (
          cy === undefined ||
          minX === undefined ||
          q1X === undefined ||
          medX === undefined ||
          q3X === undefined ||
          maxX === undefined ||
          meanX === undefined
        ) {
          return null;
        }

        const col = tokens.palette[idx % tokens.palette.length];
        const faded = hoveredCat !== null && hoveredCat !== r.category;
        const lines = [
          `${r.category} (n = ${r.n.toLocaleString()})`,
          `Median: ${fmtSmart(r.median)} · Mean: ${fmtSmart(r.mean)}`,
          `IQR: [${fmtSmart(r.q1)}, ${fmtSmart(r.q3)}]`,
          `Range: [${fmtSmart(r.min)}, ${fmtSmart(r.max)}]`,
        ];

        return (
          <g
            key={r.category}
            style={{
              cursor: onDrill && r.drill ? "pointer" : "default",
              opacity: faded ? 0.35 : 1,
              transition: "opacity 0.16s ease",
            }}
            onMouseEnter={(e) => {
              setHoveredCat(r.category);
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines,
              });
            }}
            onMouseMove={(e) => {
              const svgRect = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              onHover({
                x: e.clientX - svgRect.left,
                y: e.clientY - svgRect.top,
                lines,
              });
            }}
            onMouseLeave={() => {
              setHoveredCat(null);
              onHover(null);
            }}
            onClick={() => {
              if (onDrill && r.drill) onDrill(r.drill);
            }}
          >
            <rect x={left} y={cy - bandH / 2} width={Math.max(0, width)} height={bandH} fill="transparent" />
            <line x1={minX} y1={cy} x2={q1X} y2={cy} stroke={col} strokeWidth={1.8} />
            <line x1={q3X} y1={cy} x2={maxX} y2={cy} stroke={col} strokeWidth={1.8} />
            <line x1={minX} y1={cy - 5} x2={minX} y2={cy + 5} stroke={col} strokeWidth={1.8} />
            <line x1={maxX} y1={cy - 5} x2={maxX} y2={cy + 5} stroke={col} strokeWidth={1.8} />
            <rect
              x={Math.min(q1X, q3X)}
              y={cy - boxH / 2}
              width={Math.max(3, Math.abs(q3X - q1X))}
              height={boxH}
              rx={6}
              fill={col}
              fillOpacity={0.22}
              stroke={col}
              strokeWidth={2}
            />
            <line
              x1={medX}
              y1={cy - boxH / 2}
              x2={medX}
              y2={cy + boxH / 2}
              stroke={col}
              strokeWidth={2.8}
            />
            <polygon
              points={`${meanX},${cy - 5} ${meanX + 5},${cy} ${meanX},${cy + 5} ${meanX - 5},${cy}`}
              fill={tokens.secondary}
              stroke={tokens.tooltipBg}
              strokeWidth={1.4}
            />
          </g>
        );
      })}
    </g>
  );
}

function BentoTreemap({
  model,
  height,
  width,
  tokens,
  onDrillTarget,
}: {
  model: HierarchyChartModel;
  height: number;
  width?: number;
  tokens: ChartThemeTokens;
  onDrillTarget?: (target: DrillTarget) => void;
}) {
  const [tip, setTip] = useState<FloatTipState | null>(null);
  const w = width ?? 760;
  const h = height;
  const total = Math.max(
    1e-9,
    model.leaves.reduce((s, item) => s + Math.max(0, item.value), 0),
  );

  interface RectItem {
    item: HierarchyChartModel["leaves"][number];
    x: number;
    y: number;
    w: number;
    h: number;
  }
  const rects: RectItem[] = [];
  const partition = (
    items: HierarchyChartModel["leaves"],
    x: number,
    y: number,
    rw: number,
    rh: number,
  ) => {
    if (!items.length || rw <= 2 || rh <= 2) return;
    if (items.length === 1) {
      rects.push({ item: items[0], x, y, w: rw, h: rh });
      return;
    }
    const sum = items.reduce((s, it) => s + Math.max(0.0001, it.value), 0);
    let acc = 0;
    let split = 1;
    for (let i = 0; i < items.length - 1; i++) {
      acc += Math.max(0.0001, items[i].value);
      if (acc >= sum / 2) {
        split = i + 1;
        break;
      }
    }
    const leftSum = items.slice(0, split).reduce((s, it) => s + Math.max(0.0001, it.value), 0);
    const ratio = Math.max(0.12, Math.min(0.88, leftSum / sum));
    if (rw >= rh) {
      const wLeft = rw * ratio;
      partition(items.slice(0, split), x, y, wLeft, rh);
      partition(items.slice(split), x + wLeft, y, rw - wLeft, rh);
    } else {
      const hTop = rh * ratio;
      partition(items.slice(0, split), x, y, rw, hTop);
      partition(items.slice(split), x, y + hTop, rw, rh - hTop);
    }
  };
  partition(model.leaves.slice(0, 28), 4, 4, w - 8, h - 8);

  return (
    <div style={{ position: "relative", width: "100%", height }}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        style={{ width: "100%", height: "100%", display: "block" }}
        role="img"
        aria-label="Treemap breakdown"
      >
        {rects.map(({ item, x, y, w: rw, h: rh }) => {
          const pad = 2.5;
          const cw = Math.max(2, rw - pad * 2);
          const ch = Math.max(2, rh - pad * 2);
          return (
            <g
              key={item.id}
              style={{ cursor: onDrillTarget ? "pointer" : "default" }}
              onMouseEnter={(e) => {
                const box = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
                setTip({
                  x: e.clientX - box.left,
                  y: e.clientY - box.top,
                  lines: [
                    item.path,
                    `${model.metricLabel}: ${fmtSmart(item.value)} (${((item.value / total) * 100).toFixed(1)}%)`,
                    `Rows: ${item.n.toLocaleString()}`,
                  ],
                });
              }}
              onMouseLeave={() => setTip(null)}
              onClick={() =>
                onDrillTarget?.({
                  column: item.column,
                  value: item.rawName,
                })
              }
            >
              <rect
                x={x + pad}
                y={y + pad}
                width={cw}
                height={ch}
                rx={10}
                fill={item.color}
                fillOpacity={tokens.isDark ? 0.84 : 0.9}
              />
              {cw >= 64 && ch >= 34 ? (
                <>
                  <text
                    x={x + pad + 10}
                    y={y + pad + 20}
                    fill="#FFFFFF"
                    fontSize={12.5}
                    fontWeight={650}
                    fontFamily="var(--display)"
                  >
                    {truncateLabel(item.label, Math.floor(cw / 7.5))}
                  </text>
                  {ch >= 52 ? (
                    <text
                      x={x + pad + 10}
                      y={y + pad + 37}
                      fill="rgba(255,255,255,0.9)"
                      fontSize={12}
                      fontFamily="var(--mono)"
                    >
                      {fmtSmart(item.value)}
                    </text>
                  ) : null}
                </>
              ) : null}
            </g>
          );
        })}
      </svg>
      {tip ? <BentoFloatTooltip tip={tip} /> : null}
    </div>
  );
}

function BentoFloatTooltip({ tip }: { tip: FloatTipState }) {
  return (
    <div
      className="mui-bento-float-tip"
      style={{
        left: Math.max(8, tip.x + 14),
        top: Math.max(8, tip.y - 12),
      }}
    >
      {tip.lines.map((line, idx) => (
        <div key={idx} className={idx === 0 ? "tip-head" : "tip-row"}>
          {line}
        </div>
      ))}
    </div>
  );
}

export function MuiChartSurface({
  adapted,
  height,
  width,
  compact = false,
  showRangeControls = false,
  brushActive = false,
  resetTick = 0,
  skipAnimation = false,
  hostRef,
  onBrushStats,
  onDrillTarget,
}: {
  adapted: AdaptedChart;
  height: number;
  width?: number;
  compact?: boolean;
  showRangeControls?: boolean;
  brushActive?: boolean;
  resetTick?: number;
  skipAnimation?: boolean;
  hostRef?: MutableRefObject<HTMLDivElement | null>;
  onBrushStats?: (stats: BrushStats | null) => void;
  onDrillTarget?: (target: DrillTarget) => void;
}) {
  const { tokens } = useTheme();
  const gradUid = useId().replace(/:/g, "");
  const localRef = useRef<HTMLDivElement | null>(null);
  const [floatTip, setFloatTip] = useState<FloatTipState | null>(null);
  const [zoomWindow, setZoomWindow] = useState<[number, number]>([0, 1]);

  useEffect(() => {
    setZoomWindow([0, 1]);
  }, [resetTick, adapted]);

  const setRef = useCallback(
    (node: HTMLDivElement | null) => {
      localRef.current = node;
      if (hostRef) hostRef.current = node;
    },
    [hostRef],
  );

  const onWheelZoom = (e: WheelEvent<HTMLDivElement>) => {
    if (!adapted.canZoom || compact) return;
    if (!showRangeControls && !e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.16 : 0.84;
    setZoomWindow(([a, b]) => {
      const mid = (a + b) / 2;
      const half = Math.min(0.5, Math.max(0.05, ((b - a) / 2) * factor));
      const na = Math.max(0, mid - half);
      const nb = Math.min(1, mid + half);
      return [na, nb];
    });
  };

  const axisTickStyle = useMemo(
    () => ({
      fontSize: 12,
      fill: tokens.axisLabel,
      fontFamily: '"Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }),
    [tokens.axisLabel],
  );

  const axisLabelStyle = useMemo(
    () => ({
      fontSize: 12,
      fontWeight: 600,
      fill: tokens.subtext,
      fontFamily: '"Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }),
    [tokens.subtext],
  );

  const sharedSx = useMemo(
    () => ({
      "& .MuiChartsGrid-line": {
        stroke: tokens.splitLine,
        strokeDasharray: "3 4",
        strokeWidth: 1,
      },
      "& .MuiChartsAxis-line": {
        stroke: tokens.axisLine,
        strokeOpacity: 0.45,
      },
      "& .MuiChartsAxis-tick": {
        stroke: tokens.axisLine,
        strokeOpacity: 0.45,
      },
      "& .MuiChartsAxis-tickLabel": {
        fill: tokens.axisLabel,
        fontSize: 12,
      },
      "& .MuiChartsAxis-label": {
        fill: tokens.subtext,
        fontSize: 12,
        fontWeight: 600,
      },
      [`& .${barClasses.label}`]: {
        fill: tokens.text,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "var(--mono)",
      },
    }),
    [tokens],
  );

  const m = adapted.model;
  const maxLabelChars = compact ? 15 : 24;

  const computeLeftAxisWidth = (cats: string[]) => {
    const longest = cats.reduce((mx, c) => Math.max(mx, Math.min(maxLabelChars, c.length)), 4);
    return Math.min(compact ? 116 : 186, Math.max(52, Math.round(longest * 6.9 + 16)));
  };

  let body: React.ReactNode = null;

  if (m.kind === "forest") {
    const allNums = m.rows.flatMap((r) => [
      r.low,
      r.high,
      r.point,
      ...(r.q1 !== undefined ? [r.q1] : []),
      ...(r.q3 !== undefined ? [r.q3] : []),
    ]);
    const rawMin = m.xMin ?? Math.min(...allNums, 0);
    const rawMax = m.xMax ?? Math.max(...allNums, 1);
    const span = rawMax - rawMin || 1;
    const xMin = m.xMin ?? rawMin - span * 0.08;
    const xMax = m.xMax ?? rawMax + span * (compact ? 0.08 : 0.22);
    const yWidth = computeLeftAxisWidth(m.categories);

    body = (
      <ChartsContainer
        width={width}
        height={height}
        series={[]}
        margin={{
          top: 10,
          right: compact ? 14 : 22,
          bottom: m.xLabel ? 36 : 24,
          left: 8,
        }}
        xAxis={[
          {
            id: "fx",
            scaleType: "linear",
            min: xMin,
            max: xMax,
            label: m.xLabel || undefined,
            height: m.xLabel ? 42 : 28,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: number) => fmtSmart(v),
          },
        ]}
        yAxis={[
          {
            id: "fy",
            scaleType: "band",
            data: m.categories,
            width: yWidth,
            tickLabelStyle: { ...axisTickStyle, fill: tokens.text, fontWeight: 500 },
            valueFormatter: (v: string, ctx) =>
              ctx.location === "tick" ? truncateLabel(String(v), maxLabelChars) : String(v),
          },
        ]}
        sx={sharedSx}
      >
        <ChartsGrid vertical />
        {m.refX !== undefined ? (
          <ChartsReferenceLine
            x={m.refX}
            lineStyle={{
              stroke: tokens.subtext,
              strokeDasharray: "4 4",
              strokeWidth: 1.6,
            }}
          />
        ) : null}
        <ForestSvgLayer
          model={m}
          tokens={tokens}
          compact={compact}
          onHover={setFloatTip}
          onDrill={onDrillTarget}
        />
        <ChartsXAxis axisId="fx" disableLine disableTicks />
        <ChartsYAxis axisId="fy" disableLine disableTicks />
      </ChartsContainer>
    );
  } else if (m.kind === "bar") {
    const isHoriz = m.layout === "horizontal";
    const totalCats = m.categories.length;
    const sliceStart =
      !isHoriz && adapted.canZoom ? Math.floor(zoomWindow[0] * Math.max(0, totalCats - 2)) : 0;
    const sliceEnd =
      !isHoriz && adapted.canZoom
        ? Math.max(sliceStart + 2, Math.ceil(zoomWindow[1] * totalCats))
        : totalCats;

    const cats = m.categories.slice(sliceStart, sliceEnd);
    const barColors = m.barColors ? m.barColors.slice(sliceStart, sliceEnd) : undefined;
    const yWidth = isHoriz ? computeLeftAxisWidth(cats) : compact ? 44 : m.metricLabel ? 60 : 48;
    const showLegend = m.series.length > 1 && (!compact || m.series.length <= 4);
    const isMulti = m.series.length > 1;

    body = (
      <BarChart
        width={width}
        height={height}
        layout={m.layout}
        borderRadius={m.isLollipop ? 3 : (m.borderRadius ?? 7)}
        hideLegend={!showLegend}
        skipAnimation={skipAnimation}
        axisHighlight={isHoriz ? { y: "band" } : { x: "band" }}
        slotProps={{
          legend: {
            toggleVisibilityOnClick: true,
          },
        }}
        grid={isHoriz ? { vertical: true } : { horizontal: true }}
        margin={{
          top: showLegend ? 6 : 8,
          right: compact ? 16 : m.showBarLabels ? 44 : 24,
          bottom: !isHoriz && m.categoryLabel ? 40 : 26,
          left: 8,
        }}
        colors={m.series.map((s) => s.color)}
        xAxis={
          isHoriz
            ? [
                {
                  id: "bx",
                  scaleType: "linear",
                  min: m.min,
                  max: m.max,
                  disableLine: true,
                  disableTicks: true,
                  label: m.metricLabel || undefined,
                  height: m.metricLabel ? 40 : 26,
                  tickLabelStyle: axisTickStyle,
                  labelStyle: axisLabelStyle,
                  valueFormatter: (v: number) =>
                    m.isPercent
                      ? `${Math.round(v * 100)}%`
                      : m.isSigned && v > 0
                        ? `+${fmtSmart(v)}`
                        : fmtSmart(v),
                },
              ]
            : [
                {
                  id: "bx",
                  scaleType: "band",
                  data: cats,
                  disableTicks: true,
                  categoryGapRatio: isMulti ? 0.24 : 0.22,
                  barGapRatio: 0.14,
                  label: m.categoryLabel || undefined,
                  height: m.categoryLabel ? 42 : 28,
                  tickLabelStyle: axisTickStyle,
                  labelStyle: axisLabelStyle,
                  colorMap: barColors
                    ? {
                        type: "ordinal",
                        values: cats,
                        colors: barColors,
                      }
                    : undefined,
                  valueFormatter: (v: string, ctx) =>
                    ctx.location === "tick" ? truncateLabel(String(v), 12) : String(v),
                },
              ]
        }
        yAxis={
          isHoriz
            ? [
                {
                  id: "by",
                  scaleType: "band",
                  data: cats,
                  width: yWidth,
                  disableLine: true,
                  disableTicks: true,
                  categoryGapRatio: m.isLollipop ? 0.72 : 0.28,
                  barGapRatio: 0.16,
                  tickLabelStyle: { ...axisTickStyle, fill: tokens.text, fontWeight: 500 },
                  colorMap: barColors
                    ? {
                        type: "ordinal",
                        values: cats,
                        colors: barColors,
                      }
                    : undefined,
                  valueFormatter: (v: string, ctx) =>
                    ctx.location === "tick" ? truncateLabel(String(v), maxLabelChars) : String(v),
                },
              ]
            : [
                {
                  id: "by",
                  scaleType: "linear",
                  min: m.min,
                  max: m.max,
                  width: yWidth,
                  disableLine: true,
                  disableTicks: true,
                  label: m.metricLabel || undefined,
                  tickLabelStyle: axisTickStyle,
                  labelStyle: axisLabelStyle,
                  valueFormatter: (v: number) =>
                    m.isPercent ? `${Math.round(v * 100)}%` : fmtSmart(v),
                },
              ]
        }
        series={m.series.map((s) => ({
          id: s.id,
          label: s.label,
          stack: s.stack,
          data: s.data.slice(sliceStart, sliceEnd),
          color: s.color,
          layout: m.layout,
          barLabel:
            m.showBarLabels && !compact && m.series.length === 1
              ? (item) =>
                  item.value === null || item.value === undefined
                    ? ""
                    : m.isPercent
                      ? fmtSmart(item.value, true)
                      : fmtSmart(item.value)
              : undefined,
          barLabelPlacement: "outside",
          highlightScope: {
            highlight: isMulti ? "series" : "item",
            fade: "global",
          },
          valueFormatter: (v: number | null) =>
            v === null
              ? "—"
              : m.isPercent
                ? fmtSmart(v, true)
                : m.isSigned && v > 0
                  ? `+${fmtSmart(v)}`
                  : fmtSmart(v),
        }))}
        onItemClick={(_ev, item) => {
          if (!onDrillTarget || !m.drillForIndex) return;
          const sObj = m.series.find((s) => s.id === item.seriesId);
          const target = m.drillForIndex(sliceStart + item.dataIndex, sObj?.label);
          if (target) onDrillTarget(target);
        }}
        sx={{
          ...sharedSx,
          [`& .${barClasses.element}`]: {
            fillOpacity: m.intervals?.length && !m.isLollipop ? 0.86 : 0.94,
            transition: "opacity 0.18s ease, filter 0.18s ease",
          },
          cursor: onDrillTarget && m.drillForIndex ? "pointer" : "default",
        }}
      >
        {m.refLine ? (
          m.refLine.axis === "x" ? (
            <ChartsReferenceLine
              x={m.refLine.value}
              label={m.refLine.label}
              labelStyle={{ fill: m.refLine.color, fontSize: 12, fontWeight: 600 }}
              lineStyle={{
                stroke: m.refLine.color,
                strokeWidth: 2,
                strokeDasharray: m.refLine.dashed ? "5 4" : undefined,
              }}
            />
          ) : (
            <ChartsReferenceLine
              y={m.refLine.value}
              label={m.refLine.label}
              labelStyle={{ fill: m.refLine.color, fontSize: 12, fontWeight: 600 }}
              lineStyle={{
                stroke: m.refLine.color,
                strokeWidth: 2,
                strokeDasharray: m.refLine.dashed ? "5 4" : undefined,
              }}
            />
          )
        ) : null}
        {m.intervals?.length ? (
          <BarIntervalLayer
            categories={cats}
            intervals={m.intervals}
            layout={m.layout}
            isLollipop={m.isLollipop}
            compact={compact}
            tokens={tokens}
          />
        ) : null}
      </BarChart>
    );
  } else if (m.kind === "line") {
    const totalX = m.xValues.length;
    const sIdx = adapted.canZoom ? Math.floor(zoomWindow[0] * Math.max(0, totalX - 2)) : 0;
    const eIdx = adapted.canZoom
      ? Math.max(sIdx + 2, Math.ceil(zoomWindow[1] * totalX))
      : totalX;
    const xVals = m.xValues.slice(sIdx, eIdx);
    const showLegend = m.series.length > 1 && (!compact || m.series.length <= 4);

    const areaStyles: Record<string, Record<string, unknown>> = {};
    m.series.forEach((s) => {
      if (s.area) {
        areaStyles[`& .MuiAreaElement-series-${s.id}`] = {
          fill: `url(#area-grad-${gradUid}-${s.id})`,
        };
      }
      if (s.dashed) {
        areaStyles[`& .MuiLineElement-series-${s.id}`] = {
          strokeDasharray: "6 4",
          strokeWidth: 2.2,
        };
      }
    });

    body = (
      <LineChart
        width={width}
        height={height}
        hideLegend={!showLegend}
        skipAnimation={skipAnimation}
        axisHighlight={{ x: "line", y: "none" }}
        slotProps={{
          legend: {
            toggleVisibilityOnClick: true,
          },
        }}
        grid={{ horizontal: true }}
        margin={{
          top: showLegend ? 6 : 10,
          right: compact ? 16 : 24,
          bottom: m.xLabel ? 40 : 26,
          left: 8,
        }}
        colors={m.series.map((s) => s.color)}
        xAxis={[
          {
            id: "lx",
            scaleType: "point",
            data: xVals,
            disableTicks: true,
            label: m.xLabel || undefined,
            height: m.xLabel ? 40 : 26,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: string, ctx) =>
              ctx.location === "tick" ? truncateLabel(String(v), 12) : String(v),
          },
        ]}
        yAxis={[
          {
            id: "ly",
            scaleType: "linear",
            disableLine: true,
            disableTicks: true,
            width: compact ? 44 : m.yLabel ? 62 : 48,
            label: m.yLabel || undefined,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: number) =>
              m.isPercent ? `${Math.round(v * 100)}%` : fmtSmart(v),
          },
        ]}
        series={m.series.map((s) => ({
          id: s.id,
          label: s.label,
          stack: s.stack,
          data: s.data.slice(sIdx, eIdx),
          color: s.color,
          area: s.area,
          baseline: s.area ? "min" : undefined,
          curve: s.curve ?? "monotoneX",
          showMark: s.showMark ?? false,
          highlightScope: {
            highlight: "series",
            fade: "global",
          },
          valueFormatter: (v: number | null) =>
            v === null ? "—" : m.isPercent ? fmtSmart(v, true) : fmtSmart(v),
        }))}
        onAxisClick={(_ev, data) => {
          if (!onDrillTarget || !m.drillForIndex || !data) return;
          const target = m.drillForIndex(sIdx + data.dataIndex);
          if (target) onDrillTarget(target);
        }}
        sx={{
          ...sharedSx,
          "& .MuiLineElement-root": {
            strokeWidth: 2.6,
          },
          "& .MuiMarkElement-root": {
            strokeWidth: 2.2,
            fill: tokens.tooltipBg,
          },
          ...areaStyles,
          cursor: onDrillTarget && m.drillForIndex ? "pointer" : "default",
        }}
      >
        <defs>
          {m.series
            .filter((s) => s.area)
            .map((s) => (
              <linearGradient
                key={s.id}
                id={`area-grad-${gradUid}-${s.id}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={s.color} stopOpacity={0.38} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0.03} />
              </linearGradient>
            ))}
        </defs>
        {m.refLines?.map((rl, idx) =>
          rl.axis === "x" ? (
            xVals.includes(String(rl.value)) ? (
              <ChartsReferenceLine
                key={idx}
                x={rl.value}
                label={rl.label}
                labelStyle={{ fill: rl.color, fontSize: 12, fontWeight: 600 }}
                lineStyle={{
                  stroke: rl.color,
                  strokeWidth: 2,
                  strokeDasharray: rl.dashed ? "5 4" : undefined,
                }}
              />
            ) : null
          ) : (
            <ChartsReferenceLine
              key={idx}
              y={rl.value}
              label={rl.label}
              labelStyle={{ fill: rl.color, fontSize: 12, fontWeight: 600 }}
              lineStyle={{
                stroke: rl.color,
                strokeWidth: 2,
                strokeDasharray: rl.dashed ? "5 4" : undefined,
              }}
            />
          ),
        )}
      </LineChart>
    );
  } else if (m.kind === "scatter") {
    const allX: number[] = [];
    const allY: number[] = [];
    m.series.forEach((s) =>
      s.data.forEach((p) => {
        allX.push(p.x);
        allY.push(p.y);
      }),
    );
    m.densityCells?.forEach((c) => {
      allX.push(c.x0, c.x1);
      allY.push(c.y0, c.y1);
    });
    m.band?.forEach((b) => {
      allX.push(b.x);
      allY.push(b.low, b.high);
    });
    const rawMinX = allX.length ? Math.min(...allX) : 0;
    const rawMaxX = allX.length ? Math.max(...allX) : 1;
    const rawMinY = allY.length ? Math.min(...allY) : 0;
    const rawMaxY = allY.length ? Math.max(...allY) : 1;
    const spanX = rawMaxX - rawMinX || 1;
    const spanY = rawMaxY - rawMinY || 1;
    const padMinX = rawMinX - spanX * 0.04;
    const padMaxX = rawMaxX + spanX * 0.04;
    const zoomMinX = padMinX + (padMaxX - padMinX) * zoomWindow[0];
    const zoomMaxX = padMinX + (padMaxX - padMinX) * zoomWindow[1];
    const visibleSeries = m.series.filter((s) => s.opacity !== 0);
    const showLegend = visibleSeries.length > 1 && (!compact || visibleSeries.length <= 4);

    const opacitySx: Record<string, Record<string, unknown>> = {};
    m.series.forEach((s) => {
      if (s.opacity !== undefined) {
        opacitySx[`& .MuiScatter-series-${s.id}`] = { fillOpacity: s.opacity };
      }
    });

    body = (
      <ScatterChart
        width={width}
        height={height}
        hideLegend={!showLegend}
        skipAnimation={skipAnimation}
        slotProps={{
          legend: {
            toggleVisibilityOnClick: true,
          },
        }}
        grid={{ horizontal: true, vertical: true }}
        brushConfig={{
          enabled: brushActive,
          preventTooltip: brushActive,
          preventHighlight: brushActive,
        }}
        margin={{
          top: showLegend ? 6 : 10,
          right: compact ? 14 : 22,
          bottom: m.xLabel ? 40 : 26,
          left: 8,
        }}
        colors={m.series.map((s) => s.color)}
        xAxis={[
          {
            id: "sx",
            scaleType: "linear",
            min: zoomMinX,
            max: zoomMaxX,
            disableLine: true,
            disableTicks: true,
            label: m.xLabel || undefined,
            height: m.xLabel ? 40 : 26,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: number) => fmtSmart(v),
          },
        ]}
        yAxis={[
          {
            id: "sy",
            scaleType: "linear",
            min: rawMinY - spanY * 0.06,
            max: rawMaxY + spanY * 0.06,
            disableLine: true,
            disableTicks: true,
            width: compact ? 44 : m.yLabel ? 62 : 48,
            label: m.yLabel || undefined,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: number) => fmtSmart(v),
          },
        ]}
        series={m.series.map((s) => ({
          id: s.id,
          label: s.label,
          color: s.color,
          markerSize: s.markerSize,
          data: s.data,
          highlightScope: {
            highlight: visibleSeries.length > 1 ? "series" : "item",
            fade: "global",
          },
          valueFormatter: (pt) => (pt ? `(${fmtSmart(pt.x)}, ${fmtSmart(pt.y)})` : ""),
        }))}
        onItemClick={(_ev: unknown, item: ScatterItemIdentifier | null) => {
          if (!item || !onDrillTarget || !m.drillForSeries) return;
          const sObj = m.series.find((s) => s.id === item.seriesId);
          if (sObj) {
            const target = m.drillForSeries(sObj.label);
            if (target) onDrillTarget(target);
          }
        }}
        sx={{
          ...sharedSx,
          ...opacitySx,
          cursor: brushActive ? "crosshair" : "default",
        }}
      >
        <ScatterExtrasLayer
          model={m}
          tokens={tokens}
          brushActive={brushActive}
          scatterPoints={adapted.scatterPoints}
          resetTick={resetTick}
          onBrushStats={onBrushStats}
        />
        {brushActive ? <ChartsBrushOverlay /> : null}
      </ScatterChart>
    );
  } else if (m.kind === "pie") {
    const total = Math.max(
      1e-9,
      m.slices.reduce((s, sl) => s + Math.max(0, sl.value), 0),
    );
    body = (
      <PieChart
        width={width}
        height={height}
        hideLegend={compact && m.slices.length > 5}
        skipAnimation={skipAnimation}
        slotProps={{
          legend: {
            toggleVisibilityOnClick: true,
            direction: compact ? "horizontal" : "vertical",
          },
        }}
        margin={{ top: 8, right: 14, bottom: 8, left: 14 }}
        series={[
          {
            id: "pie-main",
            innerRadius: m.innerRadius ?? "55%",
            outerRadius: m.outerRadius ?? "86%",
            paddingAngle: 3,
            cornerRadius: 7,
            arcLabel: compact
              ? undefined
              : (item) => {
                  const pct = (item.value / total) * 100;
                  return pct >= 9 ? `${Math.round(pct)}%` : "";
                },
            arcLabelMinAngle: 26,
            highlightScope: { highlight: "item", fade: "global" },
            highlighted: { additionalRadius: 6 },
            faded: { innerRadius: 34, additionalRadius: -5, color: tokens.axisLine },
            data: m.slices.map((sl) => ({
              id: sl.id,
              label: sl.label,
              value: sl.value,
              color: sl.color,
            })),
            valueFormatter: (item) =>
              m.isPercent
                ? fmtSmart(item.value, true)
                : `${fmtSmart(item.value)} (${((item.value / total) * 100).toFixed(1)}%)`,
          },
        ]}
        onItemClick={(_ev, item) => {
          if (!onDrillTarget) return;
          const sl = m.slices[item.dataIndex];
          if (sl?.drill) onDrillTarget(sl.drill);
        }}
        sx={{
          [`& .${pieClasses.arcLabel}`]: {
            fill: "#FFFFFF",
            fontSize: 12,
            fontWeight: 700,
            fontFamily: "var(--mono)",
          },
          cursor: onDrillTarget ? "pointer" : "default",
        }}
      >
        {!compact && m.centerValue ? (
          <PieCenterLabel value={m.centerValue} label={m.centerLabel} tokens={tokens} />
        ) : null}
      </PieChart>
    );
  } else if (m.kind === "radar") {
    const showLegend = m.series.length > 1;
    body = (
      <RadarChart
        width={width}
        height={height}
        shape="circular"
        divisions={4}
        stripeColor={(idx) =>
          idx % 2 === 1
            ? tokens.isDark
              ? "rgba(56, 189, 248, 0.05)"
              : "rgba(21, 101, 112, 0.045)"
            : "none"
        }
        hideLegend={!showLegend}
        slotProps={{
          legend: {
            toggleVisibilityOnClick: true,
          },
        }}
        margin={{ top: showLegend ? 16 : 24, right: 42, bottom: 24, left: 42 }}
        radar={{
          max: m.max,
          labelGap: 10,
          metrics: m.metrics,
          labelFormatter: (name, ctx) =>
            ctx.location === "tick" ? truncateLabel(name, compact ? 11 : 16) : name,
        }}
        series={m.series.map((s) => ({
          id: s.id,
          label: s.label,
          data: s.data,
          color: s.color,
          fillArea: s.fillArea ?? true,
          highlightScope: { highlight: "series", fade: "global" },
          valueFormatter: (v) => (m.isPercent ? fmtSmart(v, true) : fmtSmart(v)),
        }))}
        sx={{
          [`& .${radarClasses.axisLabel}`]: {
            fill: tokens.text,
            fontSize: 12,
            fontWeight: 600,
            fontFamily: "var(--sans)",
          },
          [`& .${radarClasses.gridDivider}`]: {
            stroke: tokens.splitLine,
          },
          [`& .${radarClasses.gridRadial}`]: {
            stroke: tokens.splitLine,
          },
          [`& .${radarClasses.seriesArea}`]: {
            fillOpacity: 0.26,
            strokeWidth: 2.4,
          },
        }}
      />
    );
  } else if (m.kind === "heatmap") {
    const yWidth = computeLeftAxisWidth(m.yCategories);
    body = (
      <ChartsContainer
        width={width}
        height={height}
        series={[]}
        margin={{
          top: 10,
          right: compact ? 14 : 22,
          bottom: m.xLabel ? 44 : 30,
          left: 8,
        }}
        xAxis={[
          {
            id: "hx",
            scaleType: "band",
            data: m.xCategories,
            label: m.xLabel || undefined,
            height: m.xLabel ? 44 : 30,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: string, ctx) =>
              ctx.location === "tick" ? truncateLabel(String(v), 14) : String(v),
          },
        ]}
        yAxis={[
          {
            id: "hy",
            scaleType: "band",
            data: m.yCategories,
            width: yWidth,
            tickLabelStyle: { ...axisTickStyle, fill: tokens.text, fontWeight: 500 },
            valueFormatter: (v: string, ctx) =>
              ctx.location === "tick" ? truncateLabel(String(v), maxLabelChars) : String(v),
          },
        ]}
        sx={sharedSx}
      >
        <MatrixHeatmapLayer
          model={m}
          tokens={tokens}
          compact={compact}
          onHover={setFloatTip}
          onDrill={onDrillTarget}
        />
        <ChartsXAxis axisId="hx" disableLine disableTicks />
        <ChartsYAxis axisId="hy" disableLine disableTicks />
      </ChartsContainer>
    );
  } else if (m.kind === "boxplot") {
    const allV = m.rows.flatMap((r) => [r.min, r.max, r.mean]);
    const lo = allV.length ? Math.min(...allV) : 0;
    const hi = allV.length ? Math.max(...allV) : 1;
    const span = hi - lo || 1;
    const yWidth = computeLeftAxisWidth(m.categories);

    body = (
      <ChartsContainer
        width={width}
        height={height}
        series={[]}
        margin={{
          top: 10,
          right: 22,
          bottom: m.xLabel ? 42 : 28,
          left: 8,
        }}
        xAxis={[
          {
            id: "bpx",
            scaleType: "linear",
            min: lo - span * 0.06,
            max: hi + span * 0.06,
            label: m.xLabel || undefined,
            height: m.xLabel ? 42 : 28,
            tickLabelStyle: axisTickStyle,
            labelStyle: axisLabelStyle,
            valueFormatter: (v: number) => fmtSmart(v),
          },
        ]}
        yAxis={[
          {
            id: "bpy",
            scaleType: "band",
            data: m.categories,
            width: yWidth,
            tickLabelStyle: { ...axisTickStyle, fill: tokens.text, fontWeight: 500 },
            valueFormatter: (v: string, ctx) =>
              ctx.location === "tick" ? truncateLabel(String(v), maxLabelChars) : String(v),
          },
        ]}
        sx={sharedSx}
      >
        <ChartsGrid vertical />
        <BoxplotSvgLayer
          model={m}
          tokens={tokens}
          onHover={setFloatTip}
          onDrill={onDrillTarget}
        />
        <ChartsXAxis axisId="bpx" disableLine disableTicks />
        <ChartsYAxis axisId="bpy" disableLine disableTicks />
      </ChartsContainer>
    );
  } else if (m.kind === "hierarchy") {
    if (m.style === "treemap") {
      body = (
        <BentoTreemap
          model={m}
          height={height}
          width={width}
          tokens={tokens}
          onDrillTarget={onDrillTarget}
        />
      );
    } else {
      const nRings = Math.max(1, m.rings.length);
      const maxR = Math.floor(Math.min(height, width ?? 420) * 0.44);
      const minR = Math.max(24, Math.floor(maxR * 0.24));
      const step = (maxR - minR) / nRings;

      body = (
        <PieChart
          width={width}
          height={height}
          hideLegend={m.rings[0]?.items.length > 8}
          skipAnimation={skipAnimation}
          slotProps={{
            legend: { toggleVisibilityOnClick: true },
          }}
          margin={{ top: 10, right: 16, bottom: 10, left: 16 }}
          series={m.rings.map((ring, rIdx) => ({
            id: `ring-${rIdx}`,
            innerRadius: Math.round(minR + rIdx * step),
            outerRadius: Math.round(minR + (rIdx + 1) * step - 3),
            paddingAngle: 2,
            cornerRadius: 6,
            highlightScope: { highlight: "item", fade: "global" },
            highlighted: { additionalRadius: 4 },
            data: ring.items.map((it) => ({
              id: it.id,
              label: it.label,
              value: it.value,
              color: it.color,
            })),
            valueFormatter: (item) => `${fmtSmart(item.value)} (${m.metricLabel})`,
          }))}
          onItemClick={(_ev, item) => {
            if (!onDrillTarget) return;
            const ringIdx = Number(String(item.seriesId).replace("ring-", ""));
            const targetItem = m.rings[ringIdx]?.items[item.dataIndex];
            if (targetItem) {
              onDrillTarget({
                column: targetItem.column,
                value: targetItem.rawName,
              });
            }
          }}
        />
      );
    }
  }

  return (
    <div
      ref={setRef}
      className="mui-chart-surface"
      style={{ position: "relative", width: width ? `${width}px` : "100%" }}
      onWheel={onWheelZoom}
      onMouseLeave={() => setFloatTip(null)}
    >
      {body}
      {floatTip ? <BentoFloatTooltip tip={floatTip} /> : null}
      {m.kind === "heatmap" && !compact ? (
        <div className="mui-heatmap-scale" aria-hidden="true">
          <span className="mono tiny muted">{fmtSmart(m.min, m.isPercent)}</span>
          <span
            className="mui-heatmap-gradient"
            style={{
              background: `linear-gradient(90deg, ${m.ramp.join(", ")})`,
            }}
          />
          <span className="mono tiny muted">{fmtSmart(m.max, m.isPercent)}</span>
        </div>
      ) : null}
      {showRangeControls && adapted.canZoom ? (
        <div className="chart-range-bar" role="group" aria-label="Zoom range window">
          <span className="mono tiny muted">Window</span>
          <input
            type="range"
            min={0}
            max={85}
            value={Math.round(zoomWindow[0] * 100)}
            aria-label="Range start"
            onChange={(e) => {
              const nextStart = Number(e.target.value) / 100;
              setZoomWindow(([, end]) => [Math.min(nextStart, end - 0.1), end]);
            }}
          />
          <input
            type="range"
            min={15}
            max={100}
            value={Math.round(zoomWindow[1] * 100)}
            aria-label="Range end"
            onChange={(e) => {
              const nextEnd = Number(e.target.value) / 100;
              setZoomWindow(([start]) => [start, Math.max(nextEnd, start + 0.1)]);
            }}
          />
          <span className="mono tiny muted tabular-nums">
            {Math.round(zoomWindow[0] * 100)}%–{Math.round(zoomWindow[1] * 100)}%
          </span>
        </div>
      ) : null}
    </div>
  );
}

function ExpandedChartModal({
  chart,
  title,
  initialViewId,
  onClose,
  onDrillTarget,
}: {
  chart: ChartSpec;
  title: string;
  initialViewId?: string;
  onClose: () => void;
  onDrillTarget?: (target: DrillTarget) => void;
}) {
  const { tokens } = useTheme();
  const [resetTick, setResetTick] = useState(0);
  const [brushActive, setBrushActive] = useState(false);
  const [brushStats, setBrushStats] = useState<BrushStats | null>(null);
  const [viewId, setViewId] = useState(initialViewId ?? "");
  const height = Math.max(380, Math.round(window.innerHeight * 0.66));

  const baseAdapted = useMemo(
    () => adaptChartSpec(chart.spec as Obj, tokens, false),
    [chart.spec, tokens],
  );
  const adapted = useMemo(() => {
    if (!baseAdapted) return null;
    if (!viewId || !baseAdapted.altViews?.length) return baseAdapted;
    const hit = baseAdapted.altViews.find((v) => v.id === viewId);
    return hit ? { ...baseAdapted, model: hit.model } : baseAdapted;
  }, [baseAdapted, viewId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="chart-modal"
      role="dialog"
      aria-modal="true"
      aria-label={title || "Chart"}
      onClick={onClose}
    >
      <div className="chart-modal-body" onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ margin: 0 }}>{adapted?.title || title || "Expanded chart"}</h3>
            <span className="small muted">
              {adapted?.subtitle ||
                "Hover marks to highlight & inspect · Click legend items to toggle series"}
            </span>
          </div>
          <div className="row-wrap" style={{ gap: 8 }}>
            {baseAdapted?.altViews && baseAdapted.altViews.length > 1 ? (
              <SpringSegmented<string>
                size="xs"
                role="group"
                ariaLabel="Expanded chart view"
                value={viewId || baseAdapted.altViews[0].id}
                onChange={setViewId}
                items={baseAdapted.altViews.map((v) => ({ id: v.id, label: v.label }))}
              />
            ) : null}
            {adapted?.canBrush && adapted.model.kind === "scatter" ? (
              <button
                type="button"
                className={`btn btn-sm${brushActive ? " btn-primary" : ""}`}
                onClick={() => setBrushActive((b) => !b)}
              >
                <Crosshair size={14} /> Brush cluster
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setBrushActive(false);
                setBrushStats(null);
                setResetTick((v) => v + 1);
              }}
            >
              <RotateCcw size={14} /> Reset
            </button>
            <button type="button" className="btn btn-sm" onClick={onClose} aria-label="Close">
              <X size={15} />
            </button>
          </div>
        </div>
        {brushStats ? (
          <div className="brush-banner" style={{ marginBottom: 10 }}>
            <span className="badge b-brand">{brushStats.count.toLocaleString()} points</span>
            <span className="mono small">
              X: [{brushStats.xMin.toPrecision(3)}, {brushStats.xMax.toPrecision(3)}] · Y: [
              {brushStats.yMin.toPrecision(3)}, {brushStats.yMax.toPrecision(3)}]
            </span>
          </div>
        ) : null}
        {adapted ? (
          <MuiChartSurface
            adapted={adapted}
            height={height}
            showRangeControls={adapted.canZoom}
            brushActive={brushActive}
            resetTick={resetTick}
            onBrushStats={setBrushStats}
            onDrillTarget={(t) => {
              onClose();
              onDrillTarget?.(t);
            }}
          />
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

export async function chartToSvg(
  chart: ChartSpec,
  width = 680,
  themeOverride = LIGHT_TOKENS,
): Promise<string> {
  const specObj = chart.spec as Obj;
  const adapted = adaptChartSpec(specObj, themeOverride, false);
  if (!adapted) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="120" viewBox="0 0 ${width} 120"></svg>`;
  }

  const height =
    typeof specObj.height === "number" ? Math.max(230, Math.min(420, specObj.height + 24)) : 270;
  const holder = document.createElement("div");
  holder.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px;height:${height}px;pointer-events:none;`;
  document.body.appendChild(holder);

  const root = createRoot(holder);
  try {
    const muiTheme = createBentoMuiTheme(themeOverride);
    flushSync(() => {
      root.render(
        <MuiThemeProvider theme={muiTheme}>
          <MuiChartSurface
            adapted={adapted}
            width={width}
            height={height}
            compact={false}
            skipAnimation
          />
        </MuiThemeProvider>,
      );
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

    const svg = serializeSvgFromContainer(holder, themeOverride, adapted.title, adapted.subtitle);
    return (
      svg ??
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"></svg>`
    );
  } finally {
    root.unmount();
    holder.remove();
  }
}
