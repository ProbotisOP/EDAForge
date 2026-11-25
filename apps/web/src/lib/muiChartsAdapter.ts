import type { ChartThemeTokens } from "./theme";
import type { ExploreResponse } from "./types";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

export interface DrillTarget {
  column?: string;
  value?: string;
  low?: number;
  high?: number;
  period?: string;
  periodEnd?: string;
  extraColumn?: string;
  extraValue?: string;
}

export type ExploreVisualStyle =
  | "bar"
  | "stacked"
  | "radar"
  | "donut"
  | "lollipop"
  | "boxplot"
  | "sunburst"
  | "treemap"
  | "line"
  | "area";

export interface ForestRow {
  label: string;
  point: number;
  low: number;
  high: number;
  q1?: number;
  q3?: number;
  median?: number;
  n?: number;
  color: string;
  drill?: DrillTarget;
  tooltipLines: string[];
}

export interface ForestChartModel {
  kind: "forest";
  categories: string[];
  xLabel: string;
  xMin?: number;
  xMax?: number;
  refX?: number;
  rows: ForestRow[];
}

export interface BarInterval {
  index: number;
  low: number;
  high: number;
  point?: number;
  n?: number;
  color?: string;
}

export interface BarChartModel {
  kind: "bar";
  layout: "horizontal" | "vertical";
  categories: string[];
  categoryLabel?: string;
  metricLabel?: string;
  min?: number;
  max?: number;
  isPercent?: boolean;
  isSigned?: boolean;
  isLollipop?: boolean;
  showBarLabels?: boolean;
  borderRadius?: number;
  barColors?: string[];
  series: {
    id: string;
    label: string;
    data: (number | null)[];
    color: string;
    stack?: string;
  }[];
  intervals?: BarInterval[];
  refLine?: {
    axis: "x" | "y";
    value: number | string;
    label?: string;
    color: string;
    dashed?: boolean;
  };
  drillForIndex?: (index: number, seriesLabel?: string) => DrillTarget | null;
}

export interface LineChartModel {
  kind: "line";
  xValues: string[];
  xLabel?: string;
  yLabel?: string;
  isPercent?: boolean;
  zeroBaseline?: boolean;
  series: {
    id: string;
    label: string;
    data: (number | null)[];
    color: string;
    area?: boolean;
    stack?: string;
    curve?: "monotoneX" | "catmullRom" | "natural" | "linear" | "stepAfter";
    showMark?: boolean;
    dashed?: boolean;
  }[];
  refLines?: {
    axis: "x" | "y";
    value: string | number;
    label?: string;
    color: string;
    dashed?: boolean;
  }[];
  drillForIndex?: (index: number) => DrillTarget | null;
}

export interface ScatterChartModel {
  kind: "scatter";
  xLabel: string;
  yLabel: string;
  series: {
    id: string;
    label: string;
    color: string;
    markerSize: number;
    opacity?: number;
    halo?: boolean;
    data: { x: number; y: number; id: string | number; meta?: string }[];
  }[];
  densityCells?: {
    x0: number;
    x1: number;
    y0: number;
    y1: number;
    rows: number;
    share: number;
  }[];
  band?: { x: number; low: number; high: number }[];
  lines?: {
    label: string;
    color: string;
    dashed?: boolean;
    width?: number;
    points: { x: number; y: number }[];
  }[];
  drillForSeries?: (seriesLabel: string) => DrillTarget | null;
}

export interface PieChartModel {
  kind: "pie";
  metricLabel: string;
  isPercent?: boolean;
  innerRadius?: string | number;
  outerRadius?: string | number;
  centerValue?: string;
  centerLabel?: string;
  slices: {
    id: string;
    label: string;
    value: number;
    color: string;
    drill?: DrillTarget;
  }[];
}

export interface RadarChartModel {
  kind: "radar";
  metrics: { name: string; min?: number; max?: number }[];
  max?: number;
  isPercent?: boolean;
  series: {
    id: string;
    label: string;
    data: number[];
    color: string;
    fillArea?: boolean;
  }[];
}

export interface HeatmapCell {
  xi: number;
  yi: number;
  value: number;
  n?: number;
  badge?: string;
  selected?: boolean;
  tooltipLines: string[];
  drill?: DrillTarget;
}

export interface HeatmapChartModel {
  kind: "heatmap";
  xCategories: string[];
  yCategories: string[];
  xLabel?: string;
  yLabel?: string;
  min: number;
  max: number;
  ramp: string[];
  isPercent?: boolean;
  diverging?: boolean;
  cells: HeatmapCell[];
}

export interface BoxplotRow {
  category: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  mean: number;
  n: number;
  drill?: DrillTarget;
}

export interface BoxplotChartModel {
  kind: "boxplot";
  categories: string[];
  xLabel: string;
  rows: BoxplotRow[];
}

export interface HierarchyChartModel {
  kind: "hierarchy";
  style: "sunburst" | "treemap";
  metricLabel: string;
  rings: {
    depth: number;
    items: {
      id: string;
      label: string;
      value: number;
      n: number;
      color: string;
      column: string;
      rawName: string;
    }[];
  }[];
  leaves: {
    id: string;
    label: string;
    path: string;
    value: number;
    n: number;
    color: string;
    column: string;
    rawName: string;
  }[];
}

export type ChartModel =
  | ForestChartModel
  | BarChartModel
  | LineChartModel
  | ScatterChartModel
  | PieChartModel
  | RadarChartModel
  | HeatmapChartModel
  | BoxplotChartModel
  | HierarchyChartModel;

export interface ChartAltView {
  id: string;
  label: string;
  model: ChartModel;
}

export interface AdaptedChart {
  title?: string;
  subtitle?: string;
  model: ChartModel;
  altViews?: ChartAltView[];
  drillColumn?: string;
  drillExtraColumn?: string;
  canBrush?: boolean;
  canZoom?: boolean;
  scatterPoints?: { x: number; y: number; row?: number; group?: string }[];
}

export function fmtSmart(v: unknown, pct = false): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  if (pct) return `${(v * 100).toFixed(1)}%`;
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (a >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (a >= 1) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (a >= 0.001) return Number(v.toPrecision(3)).toString();
  return v.toExponential(2);
}

function uniqMetrics(labels: string[]): string[] {
  const seen = new Map<string, number>();
  return labels.map((raw) => {
    const base = raw.trim() || "Group";
    const c = seen.get(base) ?? 0;
    seen.set(base, c + 1);
    return c === 0 ? base : `${base} (${c + 1})`;
  });
}

function parseTitle(spec: Obj, compact: boolean): { title?: string; subtitle?: string } {
  if (compact) return {};
  const raw = spec.title;
  const title = isObj(raw) ? String(raw.text ?? "") : typeof raw === "string" ? raw : "";
  const subtitle = isObj(raw) ? String(raw.subtitle ?? "") : "";
  return {
    title: title || undefined,
    subtitle: subtitle || undefined,
  };
}

function olsLine(
  pts: { x: number; y: number }[],
): [{ x: number; y: number }, { x: number; y: number }] | null {
  if (pts.length < 2) return null;
  let sx = 0;
  let sy = 0;
  for (const p of pts) {
    sx += p.x;
    sy += p.y;
  }
  const mx = sx / pts.length;
  const my = sy / pts.length;
  let num = 0;
  let den = 0;
  let minX = Infinity;
  let maxX = -Infinity;
  for (const p of pts) {
    const dx = p.x - mx;
    num += dx * (p.y - my);
    den += dx * dx;
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
  }
  if (den === 0 || !Number.isFinite(minX) || minX === maxX) return null;
  const slope = num / den;
  const intercept = my - slope * mx;
  return [
    { x: minX, y: intercept + slope * minX },
    { x: maxX, y: intercept + slope * maxX },
  ];
}

/**
 * Translates EDAForge statistical specifications into rich MUI X Charts v9 models
 * with interactive multi-view alternatives (Bar, Radar, Donut, Area, Scatter, Heatmap, Forest).
 */
export function adaptChartSpec(
  spec: Obj,
  tokens: ChartThemeTokens,
  compact = false,
): AdaptedChart | null {
  const { title, subtitle } = parseTitle(spec, compact);
  const layers = Array.isArray(spec.layer) ? spec.layer.filter(isObj) : null;
  const topValues =
    isObj(spec.data) && Array.isArray(spec.data.values) ? (spec.data.values as Obj[]) : null;

  // 1. Group difference: { group, mean, low, high, median, q1, q3, n }
  if (
    topValues?.length &&
    "group" in topValues[0] &&
    "q1" in topValues[0] &&
    "mean" in topValues[0]
  ) {
    const rowsRaw = [...topValues];
    const yEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y)
        ? ((layers[0].encoding as Obj).y as Obj)
        : {};
    const xEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x)
        ? ((layers[0].encoding as Obj).x as Obj)
        : {};
    const groupTitle = String(yEnc.title ?? "Group");
    const metricTitle = String(xEnc.title ?? "Value");
    const cats = uniqMetrics(rowsRaw.map((r) => String(r.group)));
    const colors = cats.map((_, idx) => tokens.palette[idx % tokens.palette.length]);
    const maxHigh = Math.max(...rowsRaw.map((r) => Number(r.high ?? r.mean ?? 0)), 1);

    const barModel: BarChartModel = {
      kind: "bar",
      layout: "horizontal",
      categories: cats,
      categoryLabel: groupTitle,
      metricLabel: compact ? "" : metricTitle,
      max: maxHigh * (compact ? 1.08 : 1.18),
      borderRadius: 8,
      barColors: colors,
      series: [
        {
          id: "grp-mean",
          label: `Mean ${metricTitle}`,
          data: rowsRaw.map((r) => Number(r.mean)),
          color: tokens.primary,
        },
      ],
      intervals: rowsRaw.map((r, idx) => ({
        index: idx,
        low: Number(r.low),
        high: Number(r.high),
        point: Number(r.mean),
        n: Number(r.n ?? 0),
        color: tokens.text,
      })),
      drillForIndex: (idx) =>
        rowsRaw[idx] ? { column: groupTitle, value: String(rowsRaw[idx].group) } : null,
    };

    const forestRows: ForestRow[] = rowsRaw.map((r, idx) => ({
      label: cats[idx],
      point: Number(r.mean),
      low: Number(r.low),
      high: Number(r.high),
      q1: Number(r.q1),
      q3: Number(r.q3),
      median: Number(r.median),
      n: Number(r.n ?? 0),
      color: colors[idx],
      drill: { column: groupTitle, value: String(r.group) },
      tooltipLines: [
        `${groupTitle}: ${String(r.group)}`,
        `Mean: ${fmtSmart(r.mean)} [${fmtSmart(r.low)}, ${fmtSmart(r.high)}]`,
        `Median: ${fmtSmart(r.median)} · IQR: [${fmtSmart(r.q1)}, ${fmtSmart(r.q3)}]`,
        `Rows: ${Number(r.n ?? 0).toLocaleString()}`,
      ],
    }));

    const forestModel: ForestChartModel = {
      kind: "forest",
      categories: cats,
      xLabel: compact ? "" : metricTitle,
      rows: forestRows,
    };

    const totalN = rowsRaw.reduce((s, r) => s + Math.max(0, Number(r.n ?? 0)), 0);
    const donutModel: PieChartModel = {
      kind: "pie",
      metricLabel: "Rows analyzed",
      centerValue: totalN.toLocaleString(),
      centerLabel: "rows",
      slices: rowsRaw.map((r, idx) => ({
        id: `slice-${idx}`,
        label: cats[idx],
        value: Math.max(0, Number(r.n ?? 0)),
        color: colors[idx],
        drill: { column: groupTitle, value: String(r.group) },
      })),
    };

    const altViews: ChartAltView[] = [{ id: "bar", label: "Bars + CI", model: barModel }];
    if (cats.length >= 3 && cats.length <= 10 && rowsRaw.every((r) => Number(r.mean) >= 0)) {
      const radarMax = Math.max(
        ...rowsRaw.map((r) => Math.max(Number(r.mean ?? 0), Number(r.median ?? 0))),
        1,
      );
      altViews.push({
        id: "radar",
        label: "Radar",
        model: {
          kind: "radar",
          metrics: cats.map((name) => ({ name, min: 0, max: Number((radarMax * 1.12).toPrecision(4)) })),
          max: Number((radarMax * 1.12).toPrecision(4)),
          series: [
            {
              id: "r-mean",
              label: `Mean ${metricTitle}`,
              data: rowsRaw.map((r) => Number(r.mean ?? 0)),
              color: tokens.primary,
              fillArea: true,
            },
            {
              id: "r-med",
              label: `Median ${metricTitle}`,
              data: rowsRaw.map((r) => Number(r.median ?? 0)),
              color: tokens.secondary,
              fillArea: false,
            },
          ],
        },
      });
    }
    if (totalN > 0) {
      altViews.push({ id: "donut", label: "Row Share", model: donutModel });
    }
    altViews.push({ id: "forest", label: "Forest + IQR", model: forestModel });

    return {
      title,
      subtitle: compact
        ? undefined
        : "Rounded bars show group mean with 95% confidence intervals · switch views above for Radar, Share, or IQR",
      drillColumn: groupTitle,
      model: barModel,
      altViews,
    };
  }

  // 2. Category association rates: { level, rate, low, high, n }
  if (
    topValues?.length &&
    "level" in topValues[0] &&
    "rate" in topValues[0] &&
    "low" in topValues[0]
  ) {
    const rowsRaw = [...topValues];
    const yEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y)
        ? ((layers[0].encoding as Obj).y as Obj)
        : {};
    const xEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x)
        ? ((layers[0].encoding as Obj).x as Obj)
        : {};
    const dimTitle = String(yEnc.title ?? "Category");
    const rateTitle = String(xEnc.title ?? "Share");
    const cats = uniqMetrics(rowsRaw.map((r) => String(r.level)));
    const colors = cats.map((_, idx) => tokens.palette[idx % tokens.palette.length]);
    const maxHigh = Math.min(1, Math.max(...rowsRaw.map((r) => Number(r.high ?? r.rate ?? 0)), 0.1) * 1.15);

    const barModel: BarChartModel = {
      kind: "bar",
      layout: "horizontal",
      categories: cats,
      categoryLabel: dimTitle,
      metricLabel: compact ? "" : rateTitle,
      max: maxHigh,
      isPercent: true,
      borderRadius: 8,
      barColors: colors,
      series: [
        {
          id: "rate",
          label: rateTitle,
          data: rowsRaw.map((r) => Number(r.rate)),
          color: tokens.primary,
        },
      ],
      intervals: rowsRaw.map((r, idx) => ({
        index: idx,
        low: Number(r.low),
        high: Number(r.high),
        point: Number(r.rate),
        n: Number(r.n ?? 0),
        color: tokens.text,
      })),
      drillForIndex: (idx) =>
        rowsRaw[idx] ? { column: dimTitle, value: String(rowsRaw[idx].level) } : null,
    };

    const altViews: ChartAltView[] = [{ id: "bar", label: "Bars + CI", model: barModel }];
    if (cats.length >= 3 && cats.length <= 10) {
      altViews.push({
        id: "radar",
        label: "Radar",
        model: {
          kind: "radar",
          metrics: cats.map((name) => ({ name, min: 0, max: maxHigh })),
          max: maxHigh,
          isPercent: true,
          series: [
            {
              id: "rate-radar",
              label: rateTitle,
              data: rowsRaw.map((r) => Number(r.rate)),
              color: tokens.primary,
              fillArea: true,
            },
          ],
        },
      });
    }
    const totalN = rowsRaw.reduce((s, r) => s + Math.max(0, Number(r.n ?? 0)), 0);
    if (totalN > 0) {
      altViews.push({
        id: "donut",
        label: "Sample Share",
        model: {
          kind: "pie",
          metricLabel: "Rows",
          centerValue: totalN.toLocaleString(),
          centerLabel: "rows",
          slices: rowsRaw.map((r, idx) => ({
            id: `rs-${idx}`,
            label: cats[idx],
            value: Math.max(0, Number(r.n ?? 0)),
            color: colors[idx],
            drill: { column: dimTitle, value: String(r.level) },
          })),
        },
      });
    }

    return {
      title,
      subtitle,
      drillColumn: dimTitle,
      model: barModel,
      altViews,
    };
  }

  // 3. Contingency Heatmap: { a, b, share, n }
  if (
    topValues?.length &&
    "a" in topValues[0] &&
    "b" in topValues[0] &&
    "share" in topValues[0] &&
    !layers
  ) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const aTitle = isObj(enc.y) ? String(enc.y.title ?? "Row") : "Row";
    const bTitle = isObj(enc.x) ? String(enc.x.title ?? "Column") : "Column";
    const xCats = [...new Set(topValues.map((r) => String(r.b)))];
    const yCats = [...new Set(topValues.map((r) => String(r.a)))];
    const maxShare = Math.max(...topValues.map((r) => Number(r.share) || 0), 0.01);

    const heatmapModel: HeatmapChartModel = {
      kind: "heatmap",
      xCategories: xCats,
      yCategories: yCats,
      xLabel: compact ? "" : bTitle,
      yLabel: compact ? "" : aTitle,
      min: 0,
      max: maxShare,
      ramp: tokens.heatmapRamp,
      isPercent: true,
      cells: topValues.map((r) => ({
        xi: xCats.indexOf(String(r.b)),
        yi: yCats.indexOf(String(r.a)),
        value: Number(r.share ?? 0),
        n: Number(r.n ?? 0),
        tooltipLines: [
          `${aTitle}: ${String(r.a)} × ${bTitle}: ${String(r.b)}`,
          `Row share: ${fmtSmart(r.share, true)}`,
          `Records: ${Number(r.n ?? 0).toLocaleString()}`,
        ],
        drill: {
          column: aTitle,
          value: String(r.a),
          extraColumn: bTitle,
          extraValue: String(r.b),
        },
      })),
    };

    const stackedModel: BarChartModel = {
      kind: "bar",
      layout: "horizontal",
      categories: yCats,
      categoryLabel: aTitle,
      metricLabel: "Row share",
      isPercent: true,
      borderRadius: 5,
      series: xCats.map((bVal, idx) => ({
        id: `stk-${idx}`,
        label: bVal,
        stack: "share",
        color: tokens.palette[idx % tokens.palette.length],
        data: yCats.map((aVal) => {
          const hit = topValues.find((r) => String(r.a) === aVal && String(r.b) === bVal);
          return hit ? Number(hit.share ?? 0) : 0;
        }),
      })),
      drillForIndex: (idx, sLabel) =>
        yCats[idx]
          ? { column: aTitle, value: yCats[idx], extraColumn: bTitle, extraValue: sLabel }
          : null,
    };

    return {
      title,
      subtitle,
      drillColumn: aTitle,
      drillExtraColumn: bTitle,
      model: heatmapModel,
      altViews: [
        { id: "heatmap", label: "Matrix", model: heatmapModel },
        { id: "stacked", label: "Stacked Bars", model: stackedModel },
      ],
    };
  }

  // 4. Interaction plot: { first, second, value, n }
  if (
    topValues?.length &&
    "first" in topValues[0] &&
    "second" in topValues[0] &&
    "value" in topValues[0]
  ) {
    const firstEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x)
        ? ((layers[0].encoding as Obj).x as Obj)
        : {};
    const valEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y)
        ? ((layers[0].encoding as Obj).y as Obj)
        : {};
    const colEnc =
      layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).color)
        ? ((layers[0].encoding as Obj).color as Obj)
        : {};
    const isPct = isObj(valEnc.axis) && String(valEnc.axis.format ?? "").includes("%");
    const firstTitle = String(firstEnc.title ?? "Condition 1");
    const secondTitle = String(colEnc.title ?? "Condition 2");
    const yTitle = String(valEnc.title ?? "Outcome");

    const xLevels = ["no", "yes"];
    const sLevels = ["no", "yes"];

    const lineModel: LineChartModel = {
      kind: "line",
      xValues: xLevels.map((l) => `${firstTitle}: ${l}`),
      yLabel: compact ? "" : yTitle,
      isPercent: isPct,
      series: sLevels.map((sec, sIdx) => ({
        id: `inter-${sIdx}`,
        label: `${secondTitle}: ${sec}`,
        color: sIdx === 0 ? tokens.secondary : tokens.primary,
        curve: "linear",
        showMark: true,
        area: sIdx === 1,
        data: xLevels.map((f) => {
          const hit = topValues.find((r) => String(r.first) === f && String(r.second) === sec);
          return hit ? Number(hit.value) : null;
        }),
      })),
    };

    const barModel: BarChartModel = {
      kind: "bar",
      layout: "vertical",
      categories: xLevels.map((l) => `${firstTitle}: ${l}`),
      metricLabel: compact ? "" : yTitle,
      isPercent: isPct,
      borderRadius: 8,
      series: sLevels.map((sec, sIdx) => ({
        id: `inter-b-${sIdx}`,
        label: `${secondTitle}: ${sec}`,
        color: sIdx === 0 ? tokens.secondary : tokens.primary,
        data: xLevels.map((f) => {
          const hit = topValues.find((r) => String(r.first) === f && String(r.second) === sec);
          return hit ? Number(hit.value) : null;
        }),
      })),
    };

    return {
      title,
      subtitle,
      model: lineModel,
      altViews: [
        { id: "line", label: "Interaction Slopes", model: lineModel },
        { id: "bar", label: "Grouped Bars", model: barModel },
      ],
    };
  }

  // 5. Conditional / Simpson's paradox Spearman plot: { what, rho, low, high, kind }
  if (
    topValues?.length &&
    "what" in topValues[0] &&
    "rho" in topValues[0] &&
    "kind" in topValues[0]
  ) {
    const colorOf = (k: string, rho: number) => {
      if (k === "before" || rho > 0) return tokens.secondary;
      if (k === "after") return tokens.primary;
      return tokens.positive;
    };

    const cats = uniqMetrics(topValues.map((r) => String(r.what)));
    const barColors = topValues.map((r) => colorOf(String(r.kind), Number(r.rho)));

    const divergingBarModel: BarChartModel = {
      kind: "bar",
      layout: "horizontal",
      categories: cats,
      metricLabel: compact ? "" : "Spearman correlation (ρ)",
      min: -1,
      max: 1,
      isSigned: true,
      borderRadius: 7,
      barColors,
      series: [
        {
          id: "rho-div",
          label: "Spearman ρ",
          data: topValues.map((r) => Number(r.rho)),
          color: tokens.primary,
        },
      ],
      intervals: topValues.map((r, idx) => ({
        index: idx,
        low: Number(r.low),
        high: Number(r.high),
        point: Number(r.rho),
        color: tokens.text,
      })),
      refLine: {
        axis: "x",
        value: 0,
        color: tokens.subtext,
        dashed: true,
      },
    };

    const forestRows: ForestRow[] = topValues.map((r, idx) => ({
      label: cats[idx],
      point: Number(r.rho),
      low: Number(r.low),
      high: Number(r.high),
      color: barColors[idx],
      tooltipLines: [
        String(r.what),
        `Spearman ρ: ${Number(r.rho).toFixed(3)} [${Number(r.low).toFixed(3)}, ${Number(r.high).toFixed(3)}]`,
      ],
    }));

    const forestModel: ForestChartModel = {
      kind: "forest",
      categories: cats,
      xLabel: compact ? "" : "Spearman correlation (ρ)",
      xMin: -1,
      xMax: 1,
      refX: 0,
      rows: forestRows,
    };

    return {
      title,
      subtitle,
      model: divergingBarModel,
      altViews: [
        { id: "diverging", label: "Diverging Bars", model: divergingBarModel },
        { id: "forest", label: "Forest CIs", model: forestModel },
      ],
    };
  }

  // 6. Reversal Scatter coloured by group: { x, y, z } + per-group OLS + overall dashed OLS
  if (topValues?.length && "x" in topValues[0] && "y" in topValues[0] && "z" in topValues[0]) {
    const enc0 = layers?.[0] && isObj(layers[0].encoding) ? (layers[0].encoding as Obj) : {};
    const xTitle = isObj(enc0.x) ? String(enc0.x.title ?? "X") : "X";
    const yTitle = isObj(enc0.y) ? String(enc0.y.title ?? "Y") : "Y";
    const zTitle = isObj(enc0.color) ? String(enc0.color.title ?? "Group") : "Group";

    const groups = [...new Set(topValues.map((r) => String(r.z)))];
    const allPts = topValues.map((r, idx) => ({
      x: Number(r.x),
      y: Number(r.y),
      group: String(r.z),
      row: idx + 1,
    }));

    const series = groups.map((g, i) => {
      const col = tokens.palette[i % tokens.palette.length];
      const gPts = allPts.filter((p) => p.group === g);
      return {
        id: `grp-${i}`,
        label: g,
        color: col,
        markerSize: compact ? 4 : 5,
        opacity: 0.78,
        data: gPts.map((p, k) => ({ x: p.x, y: p.y, id: `${i}-${k}` })),
      };
    });

    const lines: NonNullable<ScatterChartModel["lines"]> = [];
    groups.forEach((g, i) => {
      const col = tokens.palette[i % tokens.palette.length];
      const reg = olsLine(allPts.filter((p) => p.group === g));
      if (reg) {
        lines.push({ label: `${g} fit`, color: col, width: 2.5, points: reg });
      }
    });
    const overall = olsLine(allPts);
    if (overall) {
      lines.push({
        label: "Overall trend",
        color: tokens.text,
        dashed: true,
        width: 2.5,
        points: overall,
      });
    }

    return {
      title,
      subtitle,
      canZoom: true,
      canBrush: !compact,
      scatterPoints: allPts,
      drillColumn: zTitle,
      model: {
        kind: "scatter",
        xLabel: compact ? "" : xTitle,
        yLabel: compact ? "" : yTitle,
        series,
        lines,
        drillForSeries: (sName) =>
          groups.includes(sName) ? { column: zTitle, value: sName } : null,
      },
    };
  }

  // 7. Layered charts without top-level data (subgroup, change_point, numeric_pair)
  if (layers?.length) {
    const l0Data =
      isObj(layers[0].data) && Array.isArray(layers[0].data.values)
        ? (layers[0].data.values as Obj[])
        : [];

    // 7a. Subgroup comparison: layer[0] has { group, value, n }, layer[1] has { overall }
    if (l0Data.length && "group" in l0Data[0] && "value" in l0Data[0] && layers[1]) {
      const l1Data =
        isObj(layers[1].data) && Array.isArray(layers[1].data.values)
          ? (layers[1].data.values as Obj[])
          : [];
      if (l1Data.length && "overall" in l1Data[0]) {
        const xEnc =
          isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x)
            ? ((layers[0].encoding as Obj).x as Obj)
            : {};
        const isPct = isObj(xEnc.axis) && String(xEnc.axis.format ?? "").includes("%");
        const xTitle = String(xEnc.title ?? "Value");
        const overall = Number(l1Data[0].overall);
        const cats = uniqMetrics(l0Data.map((r) => String(r.group)));
        const colors = l0Data.map((r) =>
          String(r.group) === "In the segment" ? tokens.primary : tokens.secondary,
        );

        const barModel: BarChartModel = {
          kind: "bar",
          layout: "horizontal",
          categories: cats,
          metricLabel: compact ? "" : xTitle,
          isPercent: isPct,
          showBarLabels: !compact,
          borderRadius: 8,
          barColors: colors,
          series: [
            {
              id: "subgroup",
              label: xTitle,
              data: l0Data.map((r) => Number(r.value)),
              color: tokens.primary,
            },
          ],
          refLine: Number.isFinite(overall)
            ? {
                axis: "x",
                value: overall,
                label: !compact ? `All: ${fmtSmart(overall, isPct)}` : undefined,
                color: tokens.warning,
                dashed: true,
              }
            : undefined,
        };

        const totalN = l0Data.reduce((s, r) => s + Math.max(0, Number(r.n ?? 0)), 0);
        const altViews: ChartAltView[] = [{ id: "bar", label: "Segment Bars", model: barModel }];
        if (totalN > 0) {
          altViews.push({
            id: "donut",
            label: "Segment Size",
            model: {
              kind: "pie",
              metricLabel: "Rows",
              centerValue: totalN.toLocaleString(),
              centerLabel: "rows",
              slices: l0Data.map((r, idx) => ({
                id: `sg-${idx}`,
                label: cats[idx],
                value: Math.max(0, Number(r.n ?? 0)),
                color: colors[idx],
              })),
            },
          });
        }

        return {
          title,
          subtitle,
          model: barModel,
          altViews,
        };
      }
    }

    // 7b. Change-point timeline: layer[0] has { period, value, n }
    if (l0Data.length && "period" in l0Data[0] && "value" in l0Data[0]) {
      const segs =
        layers[1] && isObj(layers[1].data) && Array.isArray(layers[1].data.values)
          ? (layers[1].data.values as Obj[])
          : [];
      const brks =
        layers[2] && isObj(layers[2].data) && Array.isArray(layers[2].data.values)
          ? (layers[2].data.values as Obj[])
          : [];
      const brkDate = brks[0]?.break ? String(brks[0].break) : null;
      const yEnc =
        isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y)
          ? ((layers[0].encoding as Obj).y as Obj)
          : {};
      const yTitle = String(yEnc.title ?? "Value");

      const periods = l0Data.map((p) => String(p.period));
      const meanBefore = segs[0]?.mean !== undefined ? Number(segs[0].mean) : null;
      const meanAfter = segs[1]?.mean !== undefined ? Number(segs[1].mean) : null;
      const brkHit = brkDate ? periods.find((d) => d >= brkDate) ?? null : null;

      const regimeLine = periods.map((p) => {
        if (brkDate && p < brkDate && meanBefore !== null) return meanBefore;
        if (brkDate && p >= brkDate && meanAfter !== null) return meanAfter;
        return null;
      });

      const series: LineChartModel["series"] = [
        {
          id: "cp-main",
          label: yTitle,
          data: l0Data.map((p) => Number(p.value)),
          color: tokens.primary,
          area: true,
          curve: "natural",
          showMark: l0Data.length <= 36 && !compact,
        },
      ];
      if (regimeLine.some((v) => v !== null)) {
        series.push({
          id: "cp-regime",
          label: "Regime mean",
          data: regimeLine,
          color: tokens.secondary,
          curve: "stepAfter",
          showMark: false,
          dashed: true,
        });
      }

      const lineModel: LineChartModel = {
        kind: "line",
        xValues: periods,
        yLabel: compact ? "" : yTitle,
        series,
        refLines: brkHit
          ? [
              {
                axis: "x",
                value: brkHit,
                label: !compact ? `Shift: ${brkDate}` : undefined,
                color: tokens.negative,
              },
            ]
          : undefined,
      };

      const barModel: BarChartModel = {
        kind: "bar",
        layout: "vertical",
        categories: periods,
        metricLabel: compact ? "" : yTitle,
        borderRadius: 6,
        barColors: periods.map((p) =>
          brkDate && p >= brkDate ? tokens.secondary : tokens.primary,
        ),
        series: [
          {
            id: "cp-bars",
            label: yTitle,
            data: l0Data.map((p) => Number(p.value)),
            color: tokens.primary,
          },
        ],
      };

      return {
        title,
        subtitle,
        canZoom: true,
        model: lineModel,
        altViews: [
          { id: "area", label: "Regime Area", model: lineModel },
          { id: "bar", label: "Period Bars", model: barModel },
        ],
      };
    }

    // 7c. Numeric Pair: Scatter (or binned 2D rect) + Spline + 95% Band
    const fitLayer = layers.find(
      (l) =>
        isObj(l.data) &&
        Array.isArray(l.data.values) &&
        l.data.values.length > 0 &&
        "fit" in (l.data.values[0] as Obj),
    );
    if (fitLayer && l0Data.length) {
      const curveRaw = ((fitLayer.data as Obj).values as Obj[]).map((c) => ({
        x: Number(c.x),
        fit: Number(c.fit),
        low: Number(c.low ?? c.fit),
        high: Number(c.high ?? c.fit),
      }));
      const areaLayer = layers.find(
        (l) =>
          isObj(l.data) &&
          Array.isArray(l.data.values) &&
          l.data.values.length > 0 &&
          "low" in (l.data.values[0] as Obj),
      );
      const bandData = areaLayer
        ? ((areaLayer.data as Obj).values as Obj[]).map((c) => ({
            x: Number(c.x),
            low: Number(c.low),
            high: Number(c.high),
          }))
        : curveRaw;

      const enc0 = isObj(layers[0].encoding) ? (layers[0].encoding as Obj) : {};
      const xTitle = isObj(enc0.x) ? String(enc0.x.title ?? "X") : "X";
      const yTitle = isObj(enc0.y) ? String(enc0.y.title ?? "Y") : "Y";

      const isBinned = "x_end" in l0Data[0] && "rows" in l0Data[0];
      const scatterPts = isBinned
        ? undefined
        : l0Data.map((r, idx) => ({ x: Number(r.x), y: Number(r.y), row: idx + 1 }));

      const densityCells = isBinned
        ? l0Data.map((r) => {
            const rowsN = Number(r.rows);
            return {
              x0: Number(r.x),
              x1: Number(r.x_end),
              y0: Number(r.y),
              y1: Number(r.y_end),
              rows: rowsN,
              share: Math.min(1, Math.log1p(rowsN) / 5.5),
            };
          })
        : undefined;

      const scatterModel: ScatterChartModel = {
        kind: "scatter",
        xLabel: compact ? "" : xTitle,
        yLabel: compact ? "" : yTitle,
        series: scatterPts
          ? [
              {
                id: "obs",
                label: "Observations",
                color: tokens.primary,
                markerSize: compact ? 3.8 : 4.8,
                opacity: 0.56,
                data: scatterPts.map((p, k) => ({ x: p.x, y: p.y, id: k })),
              },
            ]
          : [
              {
                id: "fit-anchor",
                label: "Spline fit",
                color: tokens.secondary,
                markerSize: 0.1,
                opacity: 0,
                data: curveRaw.map((c, k) => ({ x: c.x, y: c.fit, id: k })),
              },
            ],
        densityCells,
        band: bandData,
        lines: [
          {
            label: "Spline fit",
            color: tokens.secondary,
            width: 3,
            points: curveRaw.map((c) => ({ x: c.x, y: c.fit })),
          },
        ],
      };

      const curveAreaModel: LineChartModel = {
        kind: "line",
        xValues: curveRaw.map((c) => fmtSmart(c.x)),
        xLabel: xTitle,
        yLabel: yTitle,
        series: [
          {
            id: "sp-high",
            label: "95% Upper",
            data: curveRaw.map((c) => c.high),
            color: tokens.neutral,
            curve: "natural",
            dashed: true,
          },
          {
            id: "sp-fit",
            label: "Fitted curve",
            data: curveRaw.map((c) => c.fit),
            color: tokens.primary,
            area: true,
            curve: "natural",
          },
          {
            id: "sp-low",
            label: "95% Lower",
            data: curveRaw.map((c) => c.low),
            color: tokens.neutral,
            curve: "natural",
            dashed: true,
          },
        ],
      };

      return {
        title,
        subtitle,
        canZoom: true,
        canBrush: !compact && !!scatterPts,
        scatterPoints: scatterPts,
        model: scatterModel,
        altViews: [
          { id: "scatter", label: "Scatter + Spline", model: scatterModel },
          { id: "curve", label: "Response Curve", model: curveAreaModel },
        ],
      };
    }
  }

  // 8. Cross-file numeric overlaid distribution: { source, x0, x1, share, n }
  if (
    topValues?.length &&
    "source" in topValues[0] &&
    "x0" in topValues[0] &&
    "share" in topValues[0]
  ) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";
    const sources = [...new Set(topValues.map((r) => String(r.source)))];
    const firstSrcRows = topValues.filter((r) => String(r.source) === sources[0]);
    const midLabels = uniqMetrics(
      firstSrcRows.map((r) => fmtSmart((Number(r.x0) + Number(r.x1)) / 2)),
    );

    const areaModel: LineChartModel = {
      kind: "line",
      xValues: midLabels,
      xLabel: compact ? "" : xTitle,
      yLabel: compact ? "" : "Share of rows",
      isPercent: true,
      series: sources.map((src, idx) => ({
        id: `src-area-${idx}`,
        label: src,
        color: tokens.palette[idx % tokens.palette.length],
        area: true,
        curve: "catmullRom",
        showMark: false,
        data: topValues.filter((r) => String(r.source) === src).map((r) => Number(r.share)),
      })),
    };

    const barModel: BarChartModel = {
      kind: "bar",
      layout: "vertical",
      categories: midLabels,
      categoryLabel: compact ? "" : xTitle,
      metricLabel: compact ? "" : "Share of rows",
      isPercent: true,
      borderRadius: 5,
      series: sources.map((src, idx) => ({
        id: `src-${idx}`,
        label: src,
        color: tokens.palette[idx % tokens.palette.length],
        data: topValues.filter((r) => String(r.source) === src).map((r) => Number(r.share)),
      })),
    };

    return {
      title,
      subtitle,
      canZoom: true,
      model: areaModel,
      altViews: [
        { id: "area", label: "Density Area", model: areaModel },
        { id: "bar", label: "Histogram Bars", model: barModel },
      ],
    };
  }

  // 9. Cross-file categorical comparison: { level, source, share }
  if (
    topValues?.length &&
    "level" in topValues[0] &&
    "source" in topValues[0] &&
    "share" in topValues[0]
  ) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const yTitle = isObj(enc.y) ? String(enc.y.title ?? "Category") : "Category";
    const sources = [...new Set(topValues.map((r) => String(r.source)))];
    const levels = uniqMetrics([...new Set(topValues.map((r) => String(r.level)))]);
    const rawLevels = [...new Set(topValues.map((r) => String(r.level)))];

    const groupedBarModel: BarChartModel = {
      kind: "bar",
      layout: "horizontal",
      categories: levels,
      categoryLabel: yTitle,
      metricLabel: compact ? "" : "Share of rows",
      isPercent: true,
      borderRadius: 6,
      series: sources.map((src, idx) => ({
        id: `csrc-${idx}`,
        label: src,
        color: tokens.palette[idx % tokens.palette.length],
        data: rawLevels.map((lv) => {
          const hit = topValues.find((r) => String(r.level) === lv && String(r.source) === src);
          return hit ? Number(hit.share) : 0;
        }),
      })),
      drillForIndex: (idx) => (rawLevels[idx] ? { column: yTitle, value: rawLevels[idx] } : null),
    };

    const stackedBarModel: BarChartModel = {
      ...groupedBarModel,
      series: groupedBarModel.series.map((s) => ({ ...s, stack: "source" })),
    };

    const altViews: ChartAltView[] = [
      { id: "grouped", label: "Grouped Bars", model: groupedBarModel },
    ];
    if (levels.length >= 3 && levels.length <= 10) {
      const maxVal = Math.max(...topValues.map((r) => Number(r.share) || 0), 0.1) * 1.15;
      altViews.push({
        id: "radar",
        label: "Radar Compare",
        model: {
          kind: "radar",
          metrics: levels.map((name) => ({ name, min: 0, max: Math.min(1, maxVal) })),
          max: Math.min(1, maxVal),
          isPercent: true,
          series: sources.map((src, idx) => ({
            id: `rsrc-${idx}`,
            label: src,
            color: tokens.palette[idx % tokens.palette.length],
            fillArea: true,
            data: rawLevels.map((lv) => {
              const hit = topValues.find((r) => String(r.level) === lv && String(r.source) === src);
              return hit ? Number(hit.share) : 0;
            }),
          })),
        },
      });
    }
    altViews.push({ id: "stacked", label: "Stacked", model: stackedBarModel });

    return {
      title,
      subtitle,
      drillColumn: yTitle,
      model: groupedBarModel,
      altViews,
    };
  }

  // 10. Single Histogram with outlier flag: { x0, x1, n, flag }
  if (
    topValues?.length &&
    "x0" in topValues[0] &&
    "x1" in topValues[0] &&
    "n" in topValues[0] &&
    "flag" in topValues[0]
  ) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";
    const uniqCats = uniqMetrics(
      topValues.map((r) => `${fmtSmart(r.x0)}–${fmtSmart(r.x1)}`),
    );

    const barModel: BarChartModel = {
      kind: "bar",
      layout: "vertical",
      categories: uniqCats,
      categoryLabel: compact ? "" : xTitle,
      metricLabel: compact ? "" : "Rows",
      borderRadius: 6,
      barColors: topValues.map((r) => (r.flag ? tokens.secondary : tokens.primary)),
      series: [
        {
          id: "hist-n",
          label: "Rows",
          data: topValues.map((r) => Number(r.n)),
          color: tokens.primary,
        },
      ],
      drillForIndex: (idx) =>
        topValues[idx]
          ? {
              column: xTitle,
              low: Number(topValues[idx].x0),
              high: Number(topValues[idx].x1),
            }
          : null,
    };

    const areaModel: LineChartModel = {
      kind: "line",
      xValues: uniqCats,
      xLabel: compact ? "" : xTitle,
      yLabel: compact ? "" : "Rows",
      series: [
        {
          id: "hist-area",
          label: "Rows",
          data: topValues.map((r) => Number(r.n)),
          color: tokens.primary,
          area: true,
          curve: "catmullRom",
          showMark: topValues.length <= 24,
        },
      ],
    };

    return {
      title,
      subtitle,
      drillColumn: xTitle,
      model: barModel,
      altViews: [
        { id: "bar", label: "Histogram", model: barModel },
        { id: "area", label: "Density Area", model: areaModel },
      ],
    };
  }

  // 11. Anomaly scatter: { x, y, flag, row }
  if (topValues?.length && "x" in topValues[0] && "y" in topValues[0] && "flag" in topValues[0]) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "X") : "X";
    const yTitle = isObj(enc.y) ? String(enc.y.title ?? "Y") : "Y";
    const normal = topValues.filter((r) => !r.flag);
    const flagged = topValues.filter((r) => Boolean(r.flag));

    return {
      title,
      subtitle,
      canZoom: true,
      canBrush: !compact,
      scatterPoints: topValues.map((r) => ({
        x: Number(r.x),
        y: Number(r.y),
        row: Number(r.row ?? 0),
      })),
      model: {
        kind: "scatter",
        xLabel: compact ? "" : xTitle,
        yLabel: compact ? "" : yTitle,
        series: [
          {
            id: "normal-pts",
            label: "Normal rows",
            color: tokens.primary,
            markerSize: compact ? 3.5 : 4.5,
            opacity: 0.48,
            data: normal.map((r, i) => ({
              x: Number(r.x),
              y: Number(r.y),
              id: `n-${i}`,
              meta: r.row ? `Row #${String(r.row)}` : undefined,
            })),
          },
          {
            id: "anom-pts",
            label: "Flagged anomalies",
            color: tokens.secondary,
            markerSize: compact ? 6.2 : 7.6,
            opacity: 0.96,
            halo: true,
            data: flagged.map((r, i) => ({
              x: Number(r.x),
              y: Number(r.y),
              id: `f-${i}`,
              meta: r.row ? `Row #${String(r.row)}` : undefined,
            })),
          },
        ],
      },
    };
  }

  // 12. Simple horizontal bars: { <y_field>, value }
  if (topValues?.length && "value" in topValues[0] && isObj(spec.encoding)) {
    const enc = spec.encoding;
    const yField = isObj(enc.y) && typeof enc.y.field === "string" ? enc.y.field : null;
    if (yField && yField in topValues[0]) {
      const sorted = [...topValues].sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0));
      const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";
      const isPct =
        isObj(enc.x) && isObj(enc.x.axis) && String(enc.x.axis.format ?? "").includes("%");
      const cats = uniqMetrics(sorted.map((r) => String(r[yField])));
      const colors = cats.map((_, idx) => tokens.palette[idx % tokens.palette.length]);

      const barModel: BarChartModel = {
        kind: "bar",
        layout: "horizontal",
        categories: cats,
        categoryLabel: yField,
        metricLabel: compact ? "" : xTitle,
        isPercent: isPct,
        showBarLabels: !compact,
        borderRadius: 8,
        barColors: colors,
        series: [
          {
            id: "simple-bar",
            label: xTitle,
            data: sorted.map((r) => Number(r.value)),
            color: tokens.primary,
          },
        ],
        drillForIndex: (idx) =>
          sorted[idx] ? { column: yField, value: String(sorted[idx][yField]) } : null,
      };

      const altViews: ChartAltView[] = [{ id: "bar", label: "Bars", model: barModel }];
      if (cats.length >= 2 && cats.length <= 10 && sorted.every((r) => Number(r.value) >= 0)) {
        altViews.push({
          id: "donut",
          label: "Donut",
          model: {
            kind: "pie",
            metricLabel: xTitle,
            isPercent: isPct,
            slices: sorted.map((r, idx) => ({
              id: `sb-${idx}`,
              label: cats[idx],
              value: Math.max(0, Number(r.value)),
              color: colors[idx],
              drill: { column: yField, value: String(r[yField]) },
            })),
          },
        });
      }

      return {
        title,
        subtitle,
        drillColumn: yField,
        model: barModel,
        altViews,
      };
    }
  }

  return null;
}

/**
 * Builds interactive MUI X Charts v9 models for the Explore & Drill-Down Studio.
 */
export function buildExploreChart(
  res: ExploreResponse,
  tokens: ChartThemeTokens,
  visualStyle?: ExploreVisualStyle,
): AdaptedChart {
  const d = res.data;

  if (res.mode === "hierarchy") {
    const tree = (d.tree as Obj[]) ?? [];
    const style = visualStyle === "treemap" ? "treemap" : "sunburst";
    const metricLabel = String(d.metric_label ?? "Value");

    const ringsMap = new Map<number, HierarchyChartModel["rings"][number]["items"]>();
    const leaves: HierarchyChartModel["leaves"] = [];

    const walk = (nodes: Obj[], depth: number, parentColor?: string, prefix = "") => {
      nodes.forEach((node, idx) => {
        const name = String(node.name ?? "Item");
        const col = String(node.column ?? res.x ?? "");
        const val = Math.max(0, Number(node.value ?? 0));
        const n = Number(node.n ?? 0);
        const color = parentColor ?? tokens.palette[idx % tokens.palette.length];
        const path = prefix ? `${prefix} › ${name}` : name;
        const id = `h-${depth}-${path}-${idx}`;

        const arr = ringsMap.get(depth) ?? [];
        arr.push({ id, label: path, value: val, n, color, column: col, rawName: name });
        ringsMap.set(depth, arr);

        const children = Array.isArray(node.children) ? (node.children as Obj[]) : [];
        if (children.length > 0) {
          walk(children, depth + 1, color, path);
        } else {
          leaves.push({ id, label: name, path, value: val, n, color, column: col, rawName: name });
        }
      });
    };
    walk(tree, 0);

    const rings = [...ringsMap.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([depth, items]) => ({ depth, items }));

    return {
      model: {
        kind: "hierarchy",
        style,
        metricLabel,
        rings,
        leaves: leaves.sort((a, b) => b.value - a.value),
      },
    };
  }

  if (res.mode === "time") {
    const pts = (d.points as Obj[]) ?? [];
    const seriesList = (d.series as { name: string; values: (number | null)[] }[]) ?? [];
    const periods = pts.map((p) => String(p.period));
    const metricLabel = String(d.metric_label ?? "Value");
    const isArea = visualStyle !== "bar" && visualStyle !== "line";
    const isBar = visualStyle === "bar";

    const drillForIndex = (idx: number): DrillTarget | null => {
      if (pts[idx] && res.x) {
        return {
          column: res.x,
          period: String(pts[idx].period),
          periodEnd: String(pts[idx].period_end),
        };
      }
      return null;
    };

    if (isBar) {
      return {
        canZoom: true,
        drillColumn: res.x ?? undefined,
        model: {
          kind: "bar",
          layout: "vertical",
          categories: periods,
          metricLabel,
          borderRadius: 6,
          series: seriesList.length
            ? seriesList.map((s, idx) => ({
                id: `tb-${idx}`,
                label: s.name,
                color: tokens.palette[idx % tokens.palette.length],
                data: s.values,
              }))
            : [
                {
                  id: "tb-main",
                  label: metricLabel,
                  color: tokens.primary,
                  data: pts.map((p) =>
                    p.value === null || p.value === undefined ? null : Number(p.value),
                  ),
                },
              ],
          drillForIndex: (idx) => drillForIndex(idx),
        },
      };
    }

    return {
      canZoom: true,
      drillColumn: res.x ?? undefined,
      model: {
        kind: "line",
        xValues: periods,
        yLabel: metricLabel,
        series: seriesList.length
          ? seriesList.map((s, idx) => ({
              id: `tl-${idx}`,
              label: s.name,
              color: tokens.palette[idx % tokens.palette.length],
              area: isArea && seriesList.length <= 3,
              curve: "natural",
              showMark: periods.length <= 30,
              data: s.values,
            }))
          : [
              {
                id: "tl-main",
                label: metricLabel,
                color: tokens.primary,
                area: isArea,
                curve: "natural",
                showMark: periods.length <= 36,
                data: pts.map((p) =>
                  p.value === null || p.value === undefined ? null : Number(p.value),
                ),
              },
            ],
        drillForIndex,
      },
    };
  }

  if (res.mode === "histogram") {
    const bins = (d.bins as Obj[]) ?? [];
    const grouped = (d.series as { name: string; counts: number[]; shares: number[] }[]) ?? [];
    const st = (d.stats as Obj) ?? {};
    const labels = uniqMetrics(bins.map((b) => String(b.label)));
    const medIdx =
      typeof st.median === "number"
        ? bins.findIndex((b) => Number(b.x1) >= Number(st.median))
        : -1;

    if (visualStyle === "area") {
      return {
        canZoom: true,
        drillColumn: res.x ?? undefined,
        model: {
          kind: "line",
          xValues: labels,
          xLabel: res.x ?? "Value",
          yLabel: grouped.length ? "Share" : "Rows",
          isPercent: grouped.length > 0,
          series: grouped.length
            ? grouped.map((g, idx) => ({
                id: `hga-${idx}`,
                label: g.name,
                color: tokens.palette[idx % tokens.palette.length],
                area: true,
                curve: "catmullRom",
                data: g.shares,
              }))
            : [
                {
                  id: "ha-count",
                  label: "Rows",
                  color: tokens.primary,
                  area: true,
                  curve: "catmullRom",
                  data: bins.map((b) => Number(b.count)),
                },
              ],
          drillForIndex: (idx) =>
            bins[idx] && res.x
              ? { column: res.x, low: Number(bins[idx].x0), high: Number(bins[idx].x1) }
              : null,
        },
      };
    }

    return {
      drillColumn: res.x ?? undefined,
      model: {
        kind: "bar",
        layout: "vertical",
        categories: labels,
        categoryLabel: res.x ?? "Value",
        metricLabel: grouped.length ? "Share" : "Rows",
        isPercent: grouped.length > 0,
        borderRadius: 6,
        series: grouped.length
          ? grouped.map((g, idx) => ({
              id: `hg-${idx}`,
              label: g.name,
              color: tokens.palette[idx % tokens.palette.length],
              data: g.shares,
            }))
          : [
              {
                id: "h-count",
                label: "Rows",
                color: tokens.primary,
                data: bins.map((b) => Number(b.count)),
              },
            ],
        refLine:
          !grouped.length && medIdx >= 0 && labels[medIdx]
            ? {
                axis: "x",
                value: labels[medIdx],
                label: `Median: ${fmtSmart(st.median)}`,
                color: tokens.warning,
                dashed: true,
              }
            : undefined,
        drillForIndex: (idx) =>
          bins[idx] && res.x
            ? { column: res.x, low: Number(bins[idx].x0), high: Number(bins[idx].x1) }
            : null,
      },
    };
  }

  if (res.mode === "scatter") {
    const pts =
      (d.points as { x: number; y: number; row?: number; group?: string | null }[]) ?? [];
    const curve = (d.curve as { x: number; fit: number; low: number; high: number }[]) ?? [];
    const xLabel = String(d.x_label ?? res.x ?? "X");
    const yLabel = String(d.y_label ?? res.y ?? "Y");
    const gLabel = d.group_label ? String(d.group_label) : null;

    const series: ScatterChartModel["series"] = [];
    if (gLabel) {
      const groups = [...new Set(pts.map((p) => String(p.group ?? "(missing)")))];
      groups.forEach((g, idx) => {
        series.push({
          id: `sg-${idx}`,
          label: g,
          color: tokens.palette[idx % tokens.palette.length],
          markerSize: 5,
          opacity: 0.78,
          data: pts
            .filter((p) => String(p.group ?? "(missing)") === g)
            .map((p, k) => ({
              x: p.x,
              y: p.y,
              id: `${idx}-${k}`,
              meta: p.row ? `Row #${p.row}` : undefined,
            })),
        });
      });
    } else {
      series.push({
        id: "s-all",
        label: "Records",
        color: tokens.primary,
        markerSize: 4.5,
        opacity: 0.62,
        data: pts.map((p, k) => ({
          x: p.x,
          y: p.y,
          id: k,
          meta: p.row ? `Row #${p.row}` : undefined,
        })),
      });
    }

    return {
      canZoom: true,
      canBrush: true,
      scatterPoints: pts.map((p) => ({
        x: p.x,
        y: p.y,
        row: p.row,
        group: p.group ?? undefined,
      })),
      model: {
        kind: "scatter",
        xLabel,
        yLabel,
        series,
        band: curve.length ? curve.map((c) => ({ x: c.x, low: c.low, high: c.high })) : undefined,
        lines: curve.length
          ? [
              {
                label: "Spline trend",
                color: tokens.secondary,
                width: 3,
                points: curve.map((c) => ({ x: c.x, y: c.fit })),
              },
            ]
          : undefined,
      },
    };
  }

  if (res.mode === "heatmap") {
    const xCats = (d.x_categories as string[]) ?? [];
    const yCats = (d.y_categories as string[]) ?? [];
    const cells = (d.cells as Obj[]) ?? [];
    const isPct = Boolean(d.is_percent);
    const vals = cells.map((c) => Number(c.value ?? 0)).filter(Number.isFinite);
    const maxV = Math.max(...vals, 1e-6);
    const minV = Math.min(...vals, 0);

    return {
      drillColumn: res.x ?? undefined,
      drillExtraColumn: res.y ?? undefined,
      model: {
        kind: "heatmap",
        xCategories: xCats,
        yCategories: yCats,
        xLabel: res.x ?? undefined,
        yLabel: res.y ?? undefined,
        min: minV,
        max: maxV,
        ramp: tokens.heatmapRamp,
        isPercent: isPct,
        cells: cells.map((c) => {
          const xi = Number(c.xi);
          const yi = Number(c.yi);
          const v = c.value === null ? 0 : Number(c.value);
          return {
            xi,
            yi,
            value: v,
            n: Number(c.n ?? 0),
            tooltipLines: [
              `${res.y ?? "Row"}: ${yCats[yi]} × ${res.x ?? "Col"}: ${xCats[xi]}`,
              `${String(d.metric_label ?? "Value")}: ${fmtSmart(v, isPct)}`,
              `Rows: ${Number(c.n ?? 0).toLocaleString()}`,
            ],
            drill:
              res.x && res.y
                ? {
                    column: res.x,
                    value: xCats[xi],
                    extraColumn: res.y,
                    extraValue: yCats[yi],
                  }
                : undefined,
          };
        }),
      },
    };
  }

  // Group / Boxplot / Lollipop / Radar / Donut / Split Bar
  const rawCategories = (d.categories as string[]) ?? [];
  const categories = uniqMetrics(rawCategories);
  const splitSeries = (d.series as { name: string; points: Record<string, Obj> }[]) ?? [];
  const rows = (d.rows as Obj[]) ?? [];
  const isPct = Boolean(d.is_percent);
  const metricLabel = String(d.metric_label ?? "Value");

  if (splitSeries.length) {
    if (visualStyle === "radar" && categories.length >= 3 && categories.length <= 12) {
      const allVals = splitSeries.flatMap((s) =>
        rawCategories.map((cat) => Math.max(0, Number(s.points[cat]?.value ?? 0))),
      );
      const maxVal = Math.max(...allVals, 1e-6) * 1.12;
      return {
        drillColumn: res.x ?? undefined,
        drillExtraColumn: res.group ?? undefined,
        model: {
          kind: "radar",
          metrics: categories.map((name) => ({ name, min: 0, max: maxVal })),
          max: maxVal,
          isPercent: isPct,
          series: splitSeries.map((s, idx) => ({
            id: `spr-${idx}`,
            label: s.name,
            color: tokens.palette[idx % tokens.palette.length],
            fillArea: true,
            data: rawCategories.map((cat) => Math.max(0, Number(s.points[cat]?.value ?? 0))),
          })),
        },
      };
    }

    const isStacked = visualStyle === "stacked";
    return {
      drillColumn: res.x ?? undefined,
      drillExtraColumn: res.group ?? undefined,
      model: {
        kind: "bar",
        layout: "vertical",
        categories,
        categoryLabel: res.x ?? undefined,
        metricLabel,
        isPercent: isPct,
        borderRadius: isStacked ? 4 : 6,
        series: splitSeries.map((s, idx) => ({
          id: `sp-${idx}`,
          label: s.name,
          stack: isStacked ? "split" : undefined,
          color: tokens.palette[idx % tokens.palette.length],
          data: rawCategories.map((cat) => {
            const pt = s.points[cat];
            return pt?.value !== undefined && pt?.value !== null ? Number(pt.value) : 0;
          }),
        })),
        drillForIndex: (idx, sLabel) =>
          res.x && rawCategories[idx]
            ? {
                column: res.x,
                value: rawCategories[idx],
                extraColumn: res.group ?? undefined,
                extraValue: sLabel,
              }
            : null,
      },
    };
  }

  if ((visualStyle === "boxplot" || res.mode === "boxplot") && Boolean(d.has_box)) {
    return {
      drillColumn: res.x ?? undefined,
      model: {
        kind: "boxplot",
        categories: uniqMetrics(rows.map((r) => String(r.category))),
        xLabel: res.y ?? metricLabel,
        rows: rows.map((r) => ({
          category: String(r.category),
          min: Number(r.min ?? 0),
          q1: Number(r.q1 ?? 0),
          median: Number(r.median ?? 0),
          q3: Number(r.q3 ?? 0),
          max: Number(r.max ?? 0),
          mean: Number(r.mean ?? 0),
          n: Number(r.n ?? 0),
          drill: res.x ? { column: res.x, value: String(r.category) } : undefined,
        })),
      },
    };
  }

  const rowCats = uniqMetrics(rows.map((r) => String(r.category)));
  const rowColors = rowCats.map((_, idx) => tokens.palette[idx % tokens.palette.length]);

  if (visualStyle === "donut" && rows.length > 0) {
    const total = rows.reduce((s, r) => s + Math.max(0, Number(r.value ?? 0)), 0);
    return {
      drillColumn: res.x ?? undefined,
      model: {
        kind: "pie",
        metricLabel,
        isPercent: isPct,
        centerValue: isPct ? "100%" : fmtSmart(total),
        centerLabel: metricLabel,
        slices: rows.slice(0, 12).map((r, idx) => ({
          id: `ed-${idx}`,
          label: rowCats[idx],
          value: Math.max(0, Number(r.value ?? 0)),
          color: rowColors[idx],
          drill: res.x ? { column: res.x, value: String(r.category) } : undefined,
        })),
      },
    };
  }

  if (visualStyle === "radar" && rowCats.length >= 3 && rowCats.length <= 12) {
    const maxV = Math.max(...rows.map((r) => Math.max(0, Number(r.value ?? 0))), 1e-6) * 1.15;
    return {
      drillColumn: res.x ?? undefined,
      model: {
        kind: "radar",
        metrics: rowCats.map((name) => ({ name, min: 0, max: maxV })),
        max: maxV,
        isPercent: isPct,
        series: [
          {
            id: "er-main",
            label: metricLabel,
            data: rows.map((r) => Math.max(0, Number(r.value ?? 0))),
            color: tokens.primary,
            fillArea: true,
          },
        ],
      },
    };
  }

  const overall = typeof d.overall === "number" ? d.overall : null;
  const isLollipop = visualStyle === "lollipop";
  const hasCi = rows.some((r) => typeof r.ci_low === "number" && typeof r.ci_high === "number");

  return {
    drillColumn: res.x ?? undefined,
    model: {
      kind: "bar",
      layout: "horizontal",
      categories: rowCats,
      categoryLabel: res.x ?? undefined,
      metricLabel,
      isPercent: isPct,
      isLollipop,
      showBarLabels: !hasCi && !isLollipop,
      borderRadius: 8,
      barColors: isLollipop ? undefined : rowColors,
      series: [
        {
          id: "grp-main",
          label: metricLabel,
          color: isLollipop ? tokens.primarySoft : tokens.primary,
          data: rows.map((r) => Number(r.value ?? 0)),
        },
      ],
      intervals: hasCi
        ? rows.map((r, idx) => ({
            index: idx,
            low: Number(r.ci_low ?? r.value ?? 0),
            high: Number(r.ci_high ?? r.value ?? 0),
            point: isLollipop ? Number(r.value ?? 0) : undefined,
            n: Number(r.n ?? 0),
            color: tokens.text,
          }))
        : isLollipop
          ? rows.map((r, idx) => ({
              index: idx,
              low: Number(r.value ?? 0),
              high: Number(r.value ?? 0),
              point: Number(r.value ?? 0),
              color: tokens.primary,
            }))
          : undefined,
      refLine:
        overall !== null
          ? {
              axis: "x",
              value: overall,
              label: `Overall: ${fmtSmart(overall, isPct)}`,
              color: tokens.warning,
              dashed: true,
            }
          : undefined,
      drillForIndex: (idx) =>
        rows[idx] && res.x ? { column: res.x, value: String(rows[idx].category) } : null,
    },
  };
}
