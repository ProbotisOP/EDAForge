import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Result, VisualizationSpec } from "vega-embed";
import { canZoom, chartRows, type Interaction, interactive, toCsv } from "../lib/interactive";
import type { ChartSpec } from "../lib/types";

// Charts are Vega-Lite specifications produced by the analysis engine with the data embedded.
// The CSP-safe expression interpreter is used so that no code is evaluated with eval().
// On-screen charts sit on the dark theme; exported reports keep Vega's light defaults.
const DARK = {
  background: "transparent",
  axis: { labelColor: "#aab1df", titleColor: "#d6dafc", gridColor: "rgba(139,150,255,0.12)", domainColor: "rgba(139,150,255,0.3)", tickColor: "rgba(139,150,255,0.3)" },
  legend: { labelColor: "#c9cdf0", titleColor: "#e0e4ff" },
  title: { color: "#eef1ff", subtitleColor: "#9aa1cf" },
  view: { stroke: "transparent" },
  text: { color: "#e0e4ff" },
};
const OPTIONS = {
  actions: false,
  renderer: "svg" as const,
  ast: true,
  mode: "vega-lite" as const,
  tooltip: true,
};

type Vega = { embed: typeof import("vega-embed").default; expr: typeof import("vega-interpreter").expressionInterpreter };
let vega: Promise<Vega> | null = null;
/** Vega loads with the first chart, so pages without charts do not download it. */
function loadVega(): Promise<Vega> {
  vega ??= Promise.all([import("vega-embed"), import("vega-interpreter")])
    .then(([e, i]) => ({ embed: e.default, expr: i.expressionInterpreter }))
    .catch((err: unknown) => {
      vega = null; // let a later chart try again
      throw err;
    });
  return vega;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
/** The engine's chart config with the dark theme's colours laid over it (theme wins on colour keys only). */
function themed(config: unknown): Obj {
  const base: Obj = isObj(config) ? { ...config } : {};
  for (const [key, value] of Object.entries(DARK)) base[key] = isObj(value) && isObj(base[key]) ? { ...(base[key] as Obj), ...value } : value;
  return base;
}

// Mark colours chosen for the light report, swapped for screen-legible ones on the dark theme.
const SCREEN_COLOR: Record<string, string> = {
  "#111827": "#e5e7eb",
  "#1f2937": "#e5e7eb",
  "#374151": "#cbd5e1",
  "#4b5563": "#94a3b8",
  "#5f6b7a": "#9aa1cf",
  "#6b7280": "#9aa1cf",
  "#9ca3af": "#7c84b8",
  "#39414d": "#c9cdf0",
  "#4338ca": "#a5b4fc",
  "#dc2626": "#f87171",
  "#d97706": "#fbbf24",
  "#e0e7ff": "rgba(165,180,252,0.32)",
  "#e5e7eb": "rgba(165,180,252,0.25)",
  "#eef1f5": "rgba(139,150,255,0.12)",
};
function recolor(value: unknown): unknown {
  if (typeof value === "string") return SCREEN_COLOR[value.toLowerCase()] ?? value;
  if (Array.isArray(value)) return value.map(recolor);
  if (isObj(value)) {
    const out: Obj = {};
    for (const [k, v] of Object.entries(value)) out[k] = k === "data" || k === "values" ? v : recolor(v);
    return out;
  }
  return value;
}

// Inline charts zoom with Ctrl/⌘/Shift + wheel so that scrolling the page still scrolls the page;
// the expanded view zooms with the plain wheel.
const INLINE_ZOOM = "wheel![event.ctrlKey || event.metaKey || event.shiftKey]";

function sized(spec: Record<string, unknown>, height?: number, compact?: boolean, mode: Interaction = "none", zoom = INLINE_ZOOM): VisualizationSpec {
  const copy: Record<string, unknown> = { ...(interactive(recolor(spec) as Obj, mode, zoom)), config: themed(spec.config) };
  if (height) copy.height = height;
  if (compact) {
    const title = copy.title as Record<string, unknown> | undefined;
    if (title && typeof title === "object") copy.title = { ...title, text: "", subtitle: "" };
    copy.autosize = { type: "fit", contains: "padding" };
  }
  return copy as VisualizationSpec;
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
  return (text || "chart").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 60).toLowerCase() || "chart";
}

function useEmbed(chart: ChartSpec, visible: boolean, height: number | undefined, compact: boolean, mode: Interaction, zoom: string, version: number) {
  const ref = useRef<HTMLDivElement>(null);
  const result = useRef<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!visible || !ref.current) return;
    const target = ref.current;
    let cancelled = false;
    setError(null);
    loadVega()
      .then(({ embed, expr }) => (cancelled ? null : embed(target, sized(chart.spec, height, compact, mode, zoom), { ...OPTIONS, expr })))
      .then((r) => {
        if (!r) return;
        if (cancelled) r.finalize();
        else result.current = r;
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      result.current?.finalize();
      result.current = null;
    };
  }, [chart, height, compact, visible, mode, zoom, version]);
  return { ref, result, error };
}

export function Chart({ chart, height, compact = false, interaction }: { chart: ChartSpec; height?: number; compact?: boolean; interaction?: Interaction }) {
  const holder = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(!compact);
  const [version, setVersion] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const mode: Interaction = interaction ?? (compact ? "hover" : "full");
  const { ref, result, error } = useEmbed(chart, visible, height, compact, mode, INLINE_ZOOM, version);
  const zoomable = mode === "full" && canZoom(chart.spec as Obj);
  const title = isObj(chart.spec.title) ? String((chart.spec.title as Obj).text ?? "") : String(chart.spec.title ?? "");

  useEffect(() => {
    if (!compact || !holder.current) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    });
    observer.observe(holder.current);
    return () => observer.disconnect();
  }, [compact]);

  const save = async (kind: "png" | "svg" | "csv") => {
    if (kind === "csv") {
      const blob = new Blob([toCsv(chartRows(chart.spec as Obj))], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      download(`${slug(title)}.csv`, url);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    const view = result.current?.view;
    if (!view) return;
    download(`${slug(title)}.${kind}`, await view.toImageURL(kind, kind === "png" ? 2 : 1));
  };

  return (
    <figure className={`chart-frame${mode === "full" ? " chart-live" : ""}`} aria-label={chart.alt_text} ref={holder}>
      {mode === "full" ? (
        <div className="chart-tools" role="toolbar" aria-label="Chart tools">
          <button onClick={() => setExpanded(true)} title="Expand (scroll to zoom)" aria-label="Expand chart">⤢</button>
          {zoomable ? <button onClick={() => setVersion((v) => v + 1)} title="Reset zoom" aria-label="Reset zoom">⟲</button> : null}
          <button onClick={() => save("png")} title="Download PNG" aria-label="Download PNG">PNG</button>
          <button onClick={() => save("svg")} title="Download SVG" aria-label="Download SVG">SVG</button>
          <button onClick={() => save("csv")} title="Download the chart's data" aria-label="Download data as CSV">CSV</button>
        </div>
      ) : null}
      <div ref={ref} style={{ minHeight: compact ? height ?? 150 : undefined }} />
      {zoomable ? <div className="chart-hint">Ctrl/⌘ + scroll to zoom · drag to pan · double-click to reset · click a legend entry to isolate it</div> : null}
      {error ? <div className="chart-error">The chart could not be drawn: {error}</div> : null}
      {expanded ? <ExpandedChart chart={chart} title={title} onClose={() => setExpanded(false)} /> : null}
    </figure>
  );
}

function ExpandedChart({ chart, title, onClose }: { chart: ChartSpec; title: string; onClose: () => void }) {
  const [version, setVersion] = useState(0);
  const height = Math.max(320, Math.round(window.innerHeight * 0.62));
  const { ref, error } = useEmbed(chart, true, height, false, "full", "wheel!", version);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Rendered at the page root: a card's backdrop filter would otherwise contain the fixed overlay.
  return createPortal(
    <div className="chart-modal" role="dialog" aria-modal="true" aria-label={title || "Chart"} onClick={onClose}>
      <div className="chart-modal-body" onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 8 }}>
          <span className="small muted">Scroll to zoom · drag to pan · double-click or ⟲ to reset · Esc to close</span>
          <span className="row" style={{ gap: 6 }}>
            <button className="btn btn-sm" onClick={() => setVersion((v) => v + 1)}>⟲ Reset</button>
            <button className="btn btn-sm" onClick={onClose} aria-label="Close">✕</button>
          </span>
        </div>
        <div ref={ref} className="chart-modal-chart" />
        {error ? <div className="chart-error">The chart could not be drawn: {error}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

/** Render a chart to a standalone SVG string (used for the self-contained HTML report). */
export async function chartToSvg(chart: ChartSpec, width = 680): Promise<string> {
  const holder = document.createElement("div");
  holder.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px`;
  document.body.appendChild(holder);
  try {
    const spec = { ...chart.spec, width: width - 80 } as VisualizationSpec;
    const { embed, expr } = await loadVega();
    const result = await embed(holder, spec, { ...OPTIONS, expr, tooltip: false });
    const svg = await result.view.toSVG();
    result.finalize();
    return svg;
  } finally {
    holder.remove();
  }
}
