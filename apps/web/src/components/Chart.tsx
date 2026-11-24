import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as echarts from "echarts";
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
import type { Result, VisualizationSpec } from "vega-embed";
import { adaptVegaSpec, type AdaptedChart, type DrillTarget } from "../lib/echartsAdapter";
import { chartRows, type Interaction, interactive, toCsv } from "../lib/interactive";
import { LIGHT_TOKENS, useTheme } from "../lib/theme";
import type { ChartSpec } from "../lib/types";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

const VEGA_OPTIONS = {
  actions: false,
  renderer: "svg" as const,
  ast: true,
  mode: "vega-lite" as const,
  tooltip: true,
};

type Vega = {
  embed: typeof import("vega-embed").default;
  expr: typeof import("vega-interpreter").expressionInterpreter;
};
let vegaPromise: Promise<Vega> | null = null;
function loadVega(): Promise<Vega> {
  vegaPromise ??= Promise.all([import("vega-embed"), import("vega-interpreter")])
    .then(([e, i]) => ({ embed: e.default, expr: i.expressionInterpreter }))
    .catch((err: unknown) => {
      vegaPromise = null;
      throw err;
    });
  return vegaPromise;
}

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

interface BrushStats {
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
  const chartInst = useRef<echarts.ECharts | null>(null);

  const mode: Interaction = interaction ?? (compact ? "hover" : "full");
  const specObj = chart.spec as Obj;
  const title = isObj(specObj.title) ? String((specObj.title as Obj).text ?? "") : String(specObj.title ?? chart.title ?? "");
  const defaultHeight = compact ? (height ?? 156) : (height ?? (typeof specObj.height === "number" ? Math.max(260, Math.min(440, specObj.height + 54)) : 310));

  const adapted = useMemo<AdaptedChart | null>(
    () => adaptVegaSpec(specObj, tokens, compact, zoomSlider),
    [specObj, tokens, compact, zoomSlider],
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
      const svg = await chartToSvg(chart, 840, tokens);
      const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      download(`${slug(title)}.svg`, url);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    const inst = chartInst.current;
    if (inst) {
      const dataUrl = inst.getDataURL({
        type: "png",
        pixelRatio: 2,
        backgroundColor: tokens.isDark ? "#17191D" : "#FFFFFF",
      });
      download(`${slug(title)}.png`, dataUrl);
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
            {adapted?.canZoom ? (
              <button
                type="button"
                className={`chart-tool-pill${zoomSlider ? " active" : ""}`}
                onClick={() => setZoomSlider((v) => !v)}
                title="Toggle range zoom slider"
              >
                <SlidersHorizontal size={13} />
                <span>Range</span>
              </button>
            ) : null}
            {adapted?.canBrush ? (
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
            <button type="button" className="chart-tool-pill" onClick={() => void save("png")} title="Export PNG" aria-label="Download PNG">
              <Download size={12} />
              <span>PNG</span>
            </button>
            <button type="button" className="chart-tool-pill" onClick={() => void save("svg")} title="Export SVG" aria-label="Download SVG">
              <span>SVG</span>
            </button>
            <button type="button" className="chart-tool-pill" onClick={() => void save("csv")} title="Download chart data as CSV" aria-label="Download data as CSV">
              <FileSpreadsheet size={12} />
              <span>CSV</span>
            </button>
          </div>
        </div>
      ) : null}

      {brushStats ? (
        <div className="brush-banner">
          <div className="row-wrap" style={{ gap: 12 }}>
            <span className="badge b-brand">{brushStats.count.toLocaleString()} points brushed</span>
            <span className="mono small">
              X: [{brushStats.xMin.toPrecision(3)}, {brushStats.xMax.toPrecision(3)}] (μ={brushStats.meanX.toPrecision(3)})
            </span>
            <span className="mono small">
              Y: [{brushStats.yMin.toPrecision(3)}, {brushStats.yMax.toPrecision(3)}] (μ={brushStats.meanY.toPrecision(3)})
            </span>
            {brushStats.r !== null ? (
              <span className="mono small">
                Cluster r = <b>{brushStats.r >= 0 ? "+" : ""}{brushStats.r.toFixed(3)}</b>
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
        <EChartsSurface
          adapted={adapted}
          height={defaultHeight}
          brushActive={brushActive}
          resetTick={resetTick}
          chartRef={chartInst}
          onBrushStats={setBrushStats}
          onDrillTarget={mode === "full" ? onDrillTarget : undefined}
        />
      ) : (
        <VegaFallback spec={specObj} height={defaultHeight} compact={compact} mode={mode} />
      )}

      {mode === "full" && adapted ? (
        <div className="chart-footer-hint">
          {adapted.extractDrill && onDrillTarget ? "Click any bar or group to drill down · " : ""}
          {adapted.canZoom ? "Scroll to zoom · drag to pan · " : ""}
          Hover marks for exact values and intervals
        </div>
      ) : null}

      {expanded ? (
        <ExpandedChartModal
          chart={chart}
          title={title}
          onClose={() => setExpanded(false)}
          onDrillTarget={onDrillTarget}
        />
      ) : null}
    </figure>
  );
}

export function EChartsSurface({
  adapted,
  height,
  brushActive = false,
  resetTick = 0,
  chartRef,
  onBrushStats,
  onDrillTarget,
}: {
  adapted: AdaptedChart;
  height: number;
  brushActive?: boolean;
  resetTick?: number;
  chartRef?: React.MutableRefObject<echarts.ECharts | null>;
  onBrushStats?: (stats: BrushStats | null) => void;
  onDrillTarget?: (target: DrillTarget) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<echarts.ECharts | null>(null);
  const callbacks = useRef({ adapted, onBrushStats, onDrillTarget });
  callbacks.current = { adapted, onBrushStats, onDrillTarget };

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const inst = echarts.init(el, undefined, { renderer: "canvas" });
    instRef.current = inst;
    if (chartRef) chartRef.current = inst;

    inst.on("click", (params: unknown) => {
      const { adapted: ad, onDrillTarget: drill } = callbacks.current;
      if (!drill || !ad.extractDrill) return;
      const target = ad.extractDrill(params);
      if (target) drill(target);
    });

    inst.on("brushSelected", (params: unknown) => {
      const { adapted: ad, onBrushStats: report } = callbacks.current;
      if (!report || !ad.scatterPoints) return;
      const batch = (params as { batch?: { areas?: { coordRange?: [[number, number], [number, number]] }[] }[] })?.batch;
      const area = batch?.[0]?.areas?.[0]?.coordRange;
      if (!area) {
        report(null);
        return;
      }
      report(computeBrushStats(ad.scatterPoints, area[0], area[1]));
    });

    const ro = new ResizeObserver(() => {
      inst.resize();
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      inst.dispose();
      instRef.current = null;
      if (chartRef) chartRef.current = null;
    };
  }, [chartRef]);

  useEffect(() => {
    const inst = instRef.current;
    if (!inst) return;
    const opt: echarts.EChartsOption = brushActive
      ? {
          ...adapted.option,
          brush: {
            toolbox: ["rect", "clear"],
            xAxisIndex: 0,
            yAxisIndex: 0,
            brushStyle: {
              borderWidth: 1.5,
              color: "rgba(37, 99, 235, 0.14)",
              borderColor: "#2563EB",
            },
          },
          toolbox: { show: false },
        }
      : adapted.option;

    inst.setOption(opt, { notMerge: true });
    if (brushActive) {
      inst.dispatchAction({
        type: "takeGlobalCursor",
        key: "brush",
        brushOption: { brushType: "rect", brushMode: "single" },
      });
    } else {
      inst.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: false } });
    }
  }, [adapted, brushActive, resetTick]);

  return (
    <div
      ref={hostRef}
      style={{
        width: "100%",
        height,
        cursor: onDrillTarget && adapted.extractDrill ? "pointer" : "default",
      }}
    />
  );
}

function VegaFallback({
  spec,
  height,
  compact,
  mode,
}: {
  spec: Obj;
  height: number;
  compact: boolean;
  mode: Interaction;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const target = ref.current;
    if (!target) return;
    let cancelled = false;
    let viewResult: Result | null = null;
    const copy: Obj = { ...interactive(spec, mode), height };
    if (compact) copy.autosize = { type: "fit", contains: "padding" };
    loadVega()
      .then(({ embed, expr }) => (cancelled ? null : embed(target, copy as VisualizationSpec, { ...VEGA_OPTIONS, expr })))
      .then((r) => {
        if (!r) return;
        if (cancelled) r.finalize();
        else viewResult = r;
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      viewResult?.finalize();
    };
  }, [spec, height, compact, mode]);

  return (
    <div>
      <div ref={ref} style={{ minHeight: height }} />
      {error ? <div className="chart-error">The chart could not be drawn: {error}</div> : null}
    </div>
  );
}

function ExpandedChartModal({
  chart,
  title,
  onClose,
  onDrillTarget,
}: {
  chart: ChartSpec;
  title: string;
  onClose: () => void;
  onDrillTarget?: (target: DrillTarget) => void;
}) {
  const { tokens } = useTheme();
  const [resetTick, setResetTick] = useState(0);
  const [brushActive, setBrushActive] = useState(false);
  const [brushStats, setBrushStats] = useState<BrushStats | null>(null);
  const height = Math.max(380, Math.round(window.innerHeight * 0.68));
  const adapted = useMemo(
    () => adaptVegaSpec(chart.spec as Obj, tokens, false, true),
    [chart.spec, tokens],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="chart-modal" role="dialog" aria-modal="true" aria-label={title || "Chart"} onClick={onClose}>
      <div className="chart-modal-body" onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0 }}>{title || "Expanded chart"}</h3>
            <span className="small muted">Scroll to zoom · drag to pan · use bottom range slider to focus</span>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {adapted?.canBrush ? (
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
              X: [{brushStats.xMin.toPrecision(3)}, {brushStats.xMax.toPrecision(3)}] · Y: [{brushStats.yMin.toPrecision(3)}, {brushStats.yMax.toPrecision(3)}]
            </span>
          </div>
        ) : null}
        {adapted ? (
          <EChartsSurface
            adapted={adapted}
            height={height}
            brushActive={brushActive}
            resetTick={resetTick}
            onBrushStats={setBrushStats}
            onDrillTarget={(t) => {
              onClose();
              onDrillTarget?.(t);
            }}
          />
        ) : (
          <VegaFallback spec={chart.spec as Obj} height={height} compact={false} mode="full" />
        )}
      </div>
    </div>,
    document.body,
  );
}

/**
 * Renders a ChartSpec to a standalone, inert SVG string for self-contained HTML reports.
 */
export async function chartToSvg(
  chart: ChartSpec,
  width = 680,
  themeOverride = LIGHT_TOKENS,
): Promise<string> {
  const specObj = chart.spec as Obj;
  const adapted = adaptVegaSpec(specObj, themeOverride, false, false);
  if (adapted) {
    const height = typeof specObj.height === "number" ? Math.max(240, specObj.height + 50) : 290;
    const holder = document.createElement("div");
    holder.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px;height:${height}px`;
    document.body.appendChild(holder);
    try {
      const inst = echarts.init(holder, undefined, { renderer: "svg", width, height });
      inst.setOption({ ...adapted.option, animation: false });
      const svg = inst.renderToSVGString();
      inst.dispose();
      return svg;
    } finally {
      holder.remove();
    }
  }

  const holder = document.createElement("div");
  holder.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px`;
  document.body.appendChild(holder);
  try {
    const spec = { ...chart.spec, width: width - 80 } as VisualizationSpec;
    const { embed, expr } = await loadVega();
    const result = await embed(holder, spec, { ...VEGA_OPTIONS, expr, tooltip: false });
    const svg = await result.view.toSVG();
    result.finalize();
    return svg;
  } finally {
    holder.remove();
  }
}
