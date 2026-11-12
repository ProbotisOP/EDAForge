// Interactivity for the engine's Vega-Lite charts, added on screen only (exports stay static).
//
// The engine sends plain specifications; this adds Vega-Lite's own interaction parameters:
// * zoom and pan on continuous axes (interval selection bound to the scales; double-click resets),
// * a highlight ring on the mark under the pointer,
// * legends that isolate a series when clicked,
// * full tooltips on every mark.
// Nothing is computed: the data and encodings are the engine's.

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

const CONTINUOUS = new Set(["quantitative", "temporal"]);
const HOVERABLE = new Set(["bar", "circle", "point", "rect", "square", "tick"]);

export type Interaction = "none" | "hover" | "full";

function markType(unit: Obj): string | null {
  const m = unit.mark;
  if (typeof m === "string") return m;
  return isObj(m) && typeof m.type === "string" ? m.type : null;
}

function zoomChannels(unit: Obj, type: string): string[] {
  const enc = isObj(unit.encoding) ? unit.encoding : {};
  const out: string[] = [];
  for (const ch of ["x", "y"]) {
    const e = enc[ch];
    if (!isObj(e) || !CONTINUOUS.has(String(e.type)) || e.bin || e.aggregate || e.timeUnit) continue;
    if (type === "bar" && ch === "y" && !("x2" in enc)) continue; // bar heights keep their zero baseline
    out.push(ch);
  }
  return out;
}

function withTooltip(unit: Obj): Obj {
  const enc = isObj(unit.encoding) ? unit.encoding : {};
  if ("tooltip" in enc) return unit;
  const m = unit.mark;
  const mark = typeof m === "string" ? { type: m } : isObj(m) ? { ...m } : m;
  if (isObj(mark) && mark.tooltip === undefined) mark.tooltip = { content: "data" };
  return { ...unit, mark };
}

function decorate(unit: Obj, k: number, mode: Interaction, zoomTaken: { done: boolean }, zoomEvent: string): Obj {
  if (!unit.mark) return unit;
  let out = withTooltip(unit);
  const type = markType(out) ?? "";
  const enc: Obj = isObj(out.encoding) ? { ...out.encoding } : {};
  const params: unknown[] = Array.isArray(out.params) ? [...out.params] : [];
  if (mode === "full" && !zoomTaken.done) {
    const channels = zoomChannels(out, type);
    if (channels.length) {
      params.push({ name: `gh_zoom`, select: { type: "interval", encodings: channels, zoom: zoomEvent }, bind: "scales" });
      zoomTaken.done = true;
    }
  }
  if (HOVERABLE.has(type) && !("strokeWidth" in enc) && !("stroke" in enc)) {
    const name = `gh_hover_${k}`;
    params.push({ name, select: { type: "point", on: "pointerover", clear: "pointerout" } });
    enc.stroke = { condition: { param: name, empty: false, value: "#ffffff" }, value: null };
    enc.strokeWidth = { condition: { param: name, empty: false, value: 2 }, value: 0 };
  }
  const color = enc.color;
  if (mode === "full" && isObj(color) && typeof color.field === "string" && color.type === "nominal" && !("opacity" in enc)) {
    const name = `gh_legend_${k}`;
    params.push({ name, select: { type: "point", fields: [color.field] }, bind: "legend" });
    const base = isObj(out.mark) && typeof out.mark.opacity === "number" ? out.mark.opacity : 1;
    enc.opacity = { condition: { param: name, value: base }, value: 0.07 };
  }
  out = { ...out, encoding: enc };
  if (params.length) out.params = params;
  return out;
}

/** The specification with interaction added. ``mode``: "hover" for small previews, "full" otherwise. */
export function interactive(spec: Obj, mode: Interaction, zoomEvent = "wheel!"): Obj {
  if (mode === "none") return spec;
  const taken = { done: false };
  if (Array.isArray(spec.layer)) {
    return { ...spec, layer: spec.layer.map((l, k) => (isObj(l) ? decorate(l, k, mode, taken, zoomEvent) : l)) };
  }
  return decorate(spec, 0, mode, taken, zoomEvent);
}

/** Whether the chart has a zoomable axis (to show the hint and the reset button). */
export function canZoom(spec: Obj): boolean {
  const units = Array.isArray(spec.layer) ? spec.layer.filter(isObj) : [spec];
  return units.some((u) => zoomChannels(u, markType(u) ?? "").length > 0);
}

/** The rows embedded in the chart (the first data set found), for "download data". */
export function chartRows(spec: Obj): Obj[] {
  const pick = (o: Obj): Obj[] | null => (isObj(o.data) && Array.isArray(o.data.values) ? (o.data.values as Obj[]) : null);
  const top = pick(spec);
  if (top) return top;
  for (const l of Array.isArray(spec.layer) ? spec.layer : []) {
    if (isObj(l)) {
      const rows = pick(l);
      if (rows) return rows;
    }
  }
  return [];
}

export function toCsv(rows: Obj[]): string {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const cell = (v: unknown) => {
    let s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`; // spreadsheet formula injection
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.map(cell).join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n");
}
