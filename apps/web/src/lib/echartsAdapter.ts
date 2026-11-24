import type { EChartsOption } from "echarts";
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

export interface AdaptedChart {
  option: EChartsOption;
  drillColumn?: string;
  drillExtraColumn?: string;
  canBrush?: boolean;
  canZoom?: boolean;
  scatterPoints?: { x: number; y: number; row?: number; group?: string }[];
  extractDrill?: (params: unknown) => DrillTarget | null;
}

function fmtSmart(v: unknown, pct = false): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  if (pct) return `${(v * 100).toFixed(1)}%`;
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (a >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (a >= 1) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (a >= 0.001) return v.toPrecision(3);
  return v.toExponential(2);
}

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function baseTooltip(tokens: ChartThemeTokens): EChartsOption["tooltip"] {
  return {
    backgroundColor: tokens.tooltipBg,
    borderColor: tokens.tooltipBorder,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: {
      color: tokens.tooltipText,
      fontSize: 12,
      fontFamily: '"Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    },
    extraCssText: "border-radius: 7px; box-shadow: 0 8px 20px rgba(0,0,0,0.22);",
  };
}

function baseGrid(compact: boolean, hasLegend = false, hasDataZoom = false, leftPad?: number): EChartsOption["grid"] {
  return {
    top: compact ? 14 : hasLegend ? 58 : 48,
    right: compact ? 14 : 26,
    bottom: compact ? 24 : hasDataZoom ? 58 : 34,
    left: leftPad ?? (compact ? 44 : 56),
    containLabel: true,
  };
}

function titleBlock(spec: Obj, tokens: ChartThemeTokens, compact: boolean): EChartsOption["title"] | undefined {
  if (compact) return undefined;
  const raw = spec.title;
  const text = isObj(raw) ? String(raw.text ?? "") : typeof raw === "string" ? raw : "";
  const subtext = isObj(raw) ? String(raw.subtitle ?? "") : "";
  if (!text && !subtext) return undefined;
  return {
    text,
    subtext,
    left: 4,
    top: 0,
    itemGap: 3,
    textStyle: { color: tokens.text, fontSize: 13.5, fontWeight: 600 },
    subtextStyle: { color: tokens.subtext, fontSize: 11.5, fontWeight: 400 },
  };
}

function olsLine(pts: { x: number; y: number }[]): [[number, number], [number, number]] | null {
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
    [minX, intercept + slope * minX],
    [maxX, intercept + slope * maxX],
  ];
}

function makeConfidencePolygonSeries(
  curve: { x: number; low: number; high: number }[],
  fillColor: string,
): Record<string, unknown> | null {
  const clean = curve.filter(
    (c) => Number.isFinite(c.x) && Number.isFinite(c.low) && Number.isFinite(c.high),
  );
  if (clean.length < 2) return null;
  return {
    type: "custom",
    name: "95% confidence band",
    silent: true,
    z: 2,
    renderItem: (_params: unknown, api: { coord: (v: [number, number]) => [number, number] }) => {
      const pts: [number, number][] = [];
      for (const c of clean) pts.push(api.coord([c.x, c.high]));
      for (let i = clean.length - 1; i >= 0; i--) pts.push(api.coord([clean[i].x, clean[i].low]));
      return {
        type: "polygon",
        shape: { points: pts },
        style: { fill: fillColor },
      };
    },
    data: [0],
  };
}

/**
 * Translates EDAForge Vega-Lite specifications into native, hardware-accelerated ECharts options.
 * Returns null if an unknown plugin chart spec should fall back to Vega-Lite.
 */
export function adaptVegaSpec(
  spec: Obj,
  tokens: ChartThemeTokens,
  compact = false,
  enableZoomSlider = false,
): AdaptedChart | null {
  const layers = Array.isArray(spec.layer) ? spec.layer.filter(isObj) : null;
  const topValues = isObj(spec.data) && Array.isArray(spec.data.values) ? (spec.data.values as Obj[]) : null;

  // 1. Group difference: { group, mean, low, high, median, q1, q3, n }
  if (topValues?.length && "group" in topValues[0] && "q1" in topValues[0] && "mean" in topValues[0]) {
    const rows = [...topValues].reverse();
    const cats = rows.map((r) => String(r.group));
    const yEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y) ? ((layers[0].encoding as Obj).y as Obj) : {};
    const xEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x) ? ((layers[0].encoding as Obj).x as Obj) : {};
    const groupTitle = String(yEnc.title ?? "Group");
    const metricTitle = String(xEnc.title ?? "Value");

    const option: EChartsOption = {
      animationDuration: 420,
      animationEasing: "cubicOut",
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
          const r = rows[idx];
          if (!r) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(groupTitle)}: ${esc(r.group)}</div>`,
            `<div>Mean: <b>${fmtSmart(r.mean)}</b> <span style="opacity:.75">[${fmtSmart(r.low)}, ${fmtSmart(r.high)}]</span></div>`,
            `<div>Median: <b>${fmtSmart(r.median)}</b> · IQR: [${fmtSmart(r.q1)}, ${fmtSmart(r.q3)}]</div>`,
            `<div style="opacity:.75;margin-top:2px">Rows: ${Number(r.n ?? 0).toLocaleString()}</div>`,
          ].join("");
        },
      },
      grid: baseGrid(compact, false, false, 16),
      xAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : metricTitle,
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "category",
        data: cats,
        axisLabel: { color: tokens.text, fontSize: 11.5, width: compact ? 90 : 140, overflow: "truncate" },
        axisLine: { lineStyle: { color: tokens.axisLine } },
        axisTick: { show: false },
      },
      series: [
        {
          type: "custom",
          name: "IQR & 95% CI",
          renderItem: (params: unknown, api: { value: (i: number) => number; coord: (v: [number, number]) => [number, number] }) => {
            const idx = (params as { dataIndex: number }).dataIndex;
            const q1 = api.coord([api.value(1), idx]);
            const q3 = api.coord([api.value(2), idx]);
            const lo = api.coord([api.value(3), idx]);
            const hi = api.coord([api.value(4), idx]);
            const h = compact ? 8 : 12;
            return {
              type: "group",
              children: [
                {
                  type: "rect",
                  shape: { x: Math.min(q1[0], q3[0]), y: q1[1] - h / 2, width: Math.max(2, Math.abs(q3[0] - q1[0])), height: h, r: 3 },
                  style: { fill: tokens.iqrFill },
                },
                {
                  type: "line",
                  shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] },
                  style: { stroke: tokens.primary, lineWidth: 2.2 },
                },
                {
                  type: "line",
                  shape: { x1: lo[0], y1: lo[1] - 4, x2: lo[0], y2: lo[1] + 4 },
                  style: { stroke: tokens.primary, lineWidth: 1.8 },
                },
                {
                  type: "line",
                  shape: { x1: hi[0], y1: hi[1] - 4, x2: hi[0], y2: hi[1] + 4 },
                  style: { stroke: tokens.primary, lineWidth: 1.8 },
                },
              ],
            };
          },
          data: rows.map((r, idx) => [idx, Number(r.q1), Number(r.q3), Number(r.low), Number(r.high)]),
          z: 2,
        } as never,
        {
          type: "scatter",
          name: "Mean",
          symbolSize: compact ? 8 : 10,
          itemStyle: { color: tokens.primary, borderColor: tokens.tooltipBg, borderWidth: 1.5 },
          data: rows.map((r) => Number(r.mean)),
          z: 4,
        },
      ],
    };

    return {
      option,
      drillColumn: groupTitle,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        if (typeof idx === "number" && rows[idx]) {
          return { column: groupTitle, value: String(rows[idx].group) };
        }
        return null;
      },
    };
  }

  // 2. Category association rates: { level, rate, low, high, n }
  if (topValues?.length && "level" in topValues[0] && "rate" in topValues[0] && "low" in topValues[0]) {
    const rows = [...topValues].reverse();
    const yEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y) ? ((layers[0].encoding as Obj).y as Obj) : {};
    const xEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x) ? ((layers[0].encoding as Obj).x as Obj) : {};
    const dimTitle = String(yEnc.title ?? "Category");
    const rateTitle = String(xEnc.title ?? "Share");

    const option: EChartsOption = {
      animationDuration: 400,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
          const r = rows[idx];
          if (!r) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(dimTitle)}: ${esc(r.level)}</div>`,
            `<div>Share: <b>${fmtSmart(r.rate, true)}</b> <span style="opacity:.75">[${fmtSmart(r.low, true)}, ${fmtSmart(r.high, true)}]</span></div>`,
            `<div style="opacity:.75">Rows: ${Number(r.n ?? 0).toLocaleString()}</div>`,
          ].join("");
        },
      },
      grid: baseGrid(compact, false, false, 16),
      xAxis: {
        type: "value",
        name: compact ? "" : rateTitle,
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11, formatter: (v: number) => `${Math.round(v * 100)}%` },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "category",
        data: rows.map((r) => String(r.level)),
        axisLabel: { color: tokens.text, fontSize: 11.5, width: compact ? 90 : 140, overflow: "truncate" },
        axisLine: { lineStyle: { color: tokens.axisLine } },
        axisTick: { show: false },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 22,
          itemStyle: { color: tokens.primarySoft, borderColor: tokens.primary, borderWidth: 1, borderRadius: [0, 4, 4, 0] },
          data: rows.map((r) => Number(r.rate)),
        },
        {
          type: "custom",
          name: "95% Wilson CI",
          renderItem: (params: unknown, api: { value: (i: number) => number; coord: (v: [number, number]) => [number, number] }) => {
            const idx = (params as { dataIndex: number }).dataIndex;
            const lo = api.coord([api.value(1), idx]);
            const hi = api.coord([api.value(2), idx]);
            return {
              type: "group",
              children: [
                { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: tokens.primary, lineWidth: 2 } },
                { type: "line", shape: { x1: lo[0], y1: lo[1] - 4, x2: lo[0], y2: lo[1] + 4 }, style: { stroke: tokens.primary, lineWidth: 1.5 } },
                { type: "line", shape: { x1: hi[0], y1: hi[1] - 4, x2: hi[0], y2: hi[1] + 4 }, style: { stroke: tokens.primary, lineWidth: 1.5 } },
              ],
            };
          },
          data: rows.map((r, idx) => [idx, Number(r.low), Number(r.high)]),
          z: 3,
        } as never,
      ],
    };

    return {
      option,
      drillColumn: dimTitle,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        return typeof idx === "number" && rows[idx] ? { column: dimTitle, value: String(rows[idx].level) } : null;
      },
    };
  }

  // 3. Contingency Heatmap: { a, b, share, n }
  if (topValues?.length && "a" in topValues[0] && "b" in topValues[0] && "share" in topValues[0] && !layers) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const aTitle = isObj(enc.y) ? String(enc.y.title ?? "Row") : "Row";
    const bTitle = isObj(enc.x) ? String(enc.x.title ?? "Column") : "Column";
    const xCats = [...new Set(topValues.map((r) => String(r.b)))];
    const yCats = [...new Set(topValues.map((r) => String(r.a)))].reverse();
    const maxShare = Math.max(...topValues.map((r) => Number(r.share) || 0), 0.01);

    const heatData = topValues.map((r) => [
      xCats.indexOf(String(r.b)),
      yCats.indexOf(String(r.a)),
      Number(r.share ?? 0),
      Number(r.n ?? 0),
    ]);

    const option: EChartsOption = {
      animationDuration: 360,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        formatter: (p: unknown) => {
          const val = (p as { value?: number[] })?.value;
          if (!val) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(aTitle)}: ${esc(yCats[val[1]])} × ${esc(bTitle)}: ${esc(xCats[val[0]])}</div>`,
            `<div>Row share: <b>${fmtSmart(val[2], true)}</b></div>`,
            `<div style="opacity:.75">Records: ${Number(val[3]).toLocaleString()}</div>`,
          ].join("");
        },
      },
      grid: baseGrid(compact, false, false, 16),
      xAxis: {
        type: "category",
        data: xCats,
        name: compact ? "" : bTitle,
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: yCats,
        axisLabel: { color: tokens.text, fontSize: 11 },
      },
      visualMap: compact
        ? { show: false, min: 0, max: maxShare, inRange: { color: tokens.heatmapRamp } }
        : {
            min: 0,
            max: maxShare,
            calculable: false,
            orient: "horizontal",
            right: 16,
            top: 4,
            itemWidth: 10,
            itemHeight: 70,
            textStyle: { color: tokens.subtext, fontSize: 10.5 },
            formatter: (v: unknown) => `${Math.round(Number(v) * 100)}%`,
            inRange: { color: tokens.heatmapRamp },
          },
      series: [
        {
          type: "heatmap",
          data: heatData,
          label: {
            show: !compact && xCats.length <= 8 && yCats.length <= 8,
            formatter: (p: unknown) => {
              const v = (p as { value?: number[] })?.value?.[2] ?? 0;
              return `${Math.round(v * 100)}%`;
            },
            fontSize: 10.5,
            color: tokens.text,
          },
          itemStyle: { borderColor: tokens.isDark ? "#0B0F17" : "#FFFFFF", borderWidth: 2, borderRadius: 3 },
        },
      ],
    };

    return {
      option,
      drillColumn: aTitle,
      drillExtraColumn: bTitle,
      extractDrill: (p: unknown) => {
        const val = (p as { value?: number[] })?.value;
        if (!val) return null;
        return { column: aTitle, value: yCats[val[1]], extraColumn: bTitle, extraValue: xCats[val[0]] };
      },
    };
  }

  // 4. Interaction plot: { first, second, value, n }
  if (topValues?.length && "first" in topValues[0] && "second" in topValues[0] && "value" in topValues[0]) {
    const firstEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x) ? ((layers[0].encoding as Obj).x as Obj) : {};
    const valEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y) ? ((layers[0].encoding as Obj).y as Obj) : {};
    const colEnc = layers?.[0] && isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).color) ? ((layers[0].encoding as Obj).color as Obj) : {};
    const isPct = isObj(valEnc.axis) && String(valEnc.axis.format ?? "").includes("%");
    const firstTitle = String(firstEnc.title ?? "Condition 1");
    const secondTitle = String(colEnc.title ?? "Condition 2");
    const yTitle = String(valEnc.title ?? "Outcome");

    const xLevels = ["no", "yes"];
    const sLevels = ["no", "yes"];

    const option: EChartsOption = {
      animationDuration: 420,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "axis",
      },
      legend: compact
        ? undefined
        : {
            top: 28,
            right: 12,
            textStyle: { color: tokens.subtext, fontSize: 11.5 },
          },
      grid: baseGrid(compact, true),
      xAxis: {
        type: "category",
        data: xLevels.map((l) => `${firstTitle}: ${l}`),
        axisLabel: { color: tokens.text, fontSize: 11.5 },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : yTitle,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: {
          color: tokens.axisLabel,
          fontSize: 11,
          formatter: (v: number) => (isPct ? `${Math.round(v * 100)}%` : fmtSmart(v)),
        },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: sLevels.map((sec, sIdx) => ({
        type: "line",
        name: `${secondTitle}: ${sec}`,
        symbolSize: 9,
        symbol: sIdx === 0 ? "circle" : "diamond",
        lineStyle: { width: 2.8, color: sIdx === 0 ? tokens.neutral : tokens.primary },
        itemStyle: { color: sIdx === 0 ? tokens.neutral : tokens.primary },
        data: xLevels.map((f) => {
          const hit = topValues.find((r) => String(r.first) === f && String(r.second) === sec);
          return hit ? Number(hit.value) : null;
        }),
      })),
    };
    return { option };
  }

  // 5. Conditional / Partial correlation forest plot: { what, rho, low, high, kind }
  if (topValues?.length && "what" in topValues[0] && "rho" in topValues[0] && "kind" in topValues[0]) {
    const rows = [...topValues].reverse();
    const colorOf = (k: string) =>
      k === "after" ? tokens.primary : k === "within" ? tokens.positive : tokens.neutral;

    const option: EChartsOption = {
      animationDuration: 420,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
          const r = rows[idx];
          if (!r) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(r.what)}</div>`,
            `<div>Spearman ρ: <b>${Number(r.rho).toFixed(3)}</b> <span style="opacity:.75">[${Number(r.low).toFixed(3)}, ${Number(r.high).toFixed(3)}]</span></div>`,
          ].join("");
        },
      },
      grid: baseGrid(compact, false, false, 16),
      xAxis: {
        type: "value",
        min: -1,
        max: 1,
        name: compact ? "" : "Spearman correlation (ρ)",
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "category",
        data: rows.map((r) => String(r.what)),
        axisLabel: { color: tokens.text, fontSize: 11.5, width: compact ? 110 : 185, overflow: "truncate" },
        axisLine: { lineStyle: { color: tokens.axisLine } },
        axisTick: { show: false },
      },
      series: [
        {
          type: "custom",
          name: "95% CI",
          renderItem: (params: unknown, api: { value: (i: number) => number; coord: (v: [number, number]) => [number, number] }) => {
            const idx = (params as { dataIndex: number }).dataIndex;
            const lo = api.coord([api.value(1), idx]);
            const hi = api.coord([api.value(2), idx]);
            const col = colorOf(String(rows[idx]?.kind ?? "before"));
            return {
              type: "group",
              children: [
                { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: col, lineWidth: 2.5 } },
                { type: "line", shape: { x1: lo[0], y1: lo[1] - 4, x2: lo[0], y2: lo[1] + 4 }, style: { stroke: col, lineWidth: 1.8 } },
                { type: "line", shape: { x1: hi[0], y1: hi[1] - 4, x2: hi[0], y2: hi[1] + 4 }, style: { stroke: col, lineWidth: 1.8 } },
              ],
            };
          },
          data: rows.map((r, i) => [i, Number(r.low), Number(r.high)]),
        } as never,
        {
          type: "scatter",
          symbolSize: 10,
          data: rows.map((r) => ({
            value: Number(r.rho),
            itemStyle: { color: colorOf(String(r.kind)) },
          })),
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed", color: tokens.subtext, width: 1.2 },
            data: [{ xAxis: 0 }],
            label: { show: false },
          },
          z: 4,
        },
      ],
    };
    return { option };
  }

  // 6. Reversal Scatter coloured by group: topValues has { x, y, z } and layers has regression
  if (topValues?.length && "x" in topValues[0] && "y" in topValues[0] && "z" in topValues[0]) {
    const enc0 = layers?.[0] && isObj(layers[0].encoding) ? (layers[0].encoding as Obj) : {};
    const xTitle = isObj(enc0.x) ? String(enc0.x.title ?? "X") : "X";
    const yTitle = isObj(enc0.y) ? String(enc0.y.title ?? "Y") : "Y";
    const zTitle = isObj(enc0.color) ? String(enc0.color.title ?? "Group") : "Group";

    const groups = [...new Set(topValues.map((r) => String(r.z)))];
    const allPts = topValues.map((r) => ({ x: Number(r.x), y: Number(r.y), group: String(r.z) }));
    const overallLine = olsLine(allPts);

    const series: EChartsOption["series"] = [];
    groups.forEach((g, i) => {
      const col = tokens.palette[i % tokens.palette.length];
      const gPts = allPts.filter((p) => p.group === g);
      series.push({
        type: "scatter",
        name: g,
        symbolSize: compact ? 5 : 6.5,
        itemStyle: { color: col, opacity: 0.55 },
        data: gPts.map((p) => [p.x, p.y]),
      });
      const reg = olsLine(gPts);
      if (reg) {
        series.push({
          type: "line",
          name: `${g} fit`,
          showSymbol: false,
          silent: true,
          lineStyle: { color: col, width: 2.4 },
          data: reg,
        });
      }
    });
    if (overallLine) {
      series.push({
        type: "line",
        name: "Overall trend",
        showSymbol: false,
        lineStyle: { color: tokens.text, width: 2.4, type: "dashed" },
        data: overallLine,
      });
    }

    const option: EChartsOption = {
      animationDuration: 400,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "item",
        formatter: (p: unknown) => {
          const item = p as { seriesName?: string; value?: [number, number] };
          if (!item.value) return "";
          return `<div><b>${esc(zTitle)}: ${esc(item.seriesName)}</b></div><div>${esc(xTitle)}: <b>${fmtSmart(item.value[0])}</b></div><div>${esc(yTitle)}: <b>${fmtSmart(item.value[1])}</b></div>`;
        },
      },
      legend: compact
        ? undefined
        : {
            top: 28,
            right: 12,
            data: [...groups, "Overall trend"],
            textStyle: { color: tokens.subtext, fontSize: 11 },
          },
      grid: baseGrid(compact, true, enableZoomSlider),
      dataZoom: compact
        ? undefined
        : [
            { type: "inside", xAxisIndex: 0, filterMode: "none" },
            { type: "inside", yAxisIndex: 0, filterMode: "none" },
            ...(enableZoomSlider ? [{ type: "slider" as const, xAxisIndex: 0, height: 18, bottom: 8 }] : []),
          ],
      xAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : xTitle,
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : yTitle,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series,
    };

    return {
      option,
      canZoom: true,
      canBrush: !compact,
      scatterPoints: allPts,
      drillColumn: zTitle,
      extractDrill: (p: unknown) => {
        const sName = (p as { seriesName?: string })?.seriesName;
        if (sName && groups.includes(sName)) return { column: zTitle, value: sName };
        return null;
      },
    };
  }

  // 7. Layered charts without top-level data (numeric_pair, subgroup, change_point)
  if (layers?.length) {
    const l0Data = isObj(layers[0].data) && Array.isArray(layers[0].data.values) ? (layers[0].data.values as Obj[]) : [];

    // 7a. Subgroup comparison: layer[0] has { group, value, n }, layer[1] has { overall }
    if (l0Data.length && "group" in l0Data[0] && "value" in l0Data[0] && layers[1]) {
      const l1Data = isObj(layers[1].data) && Array.isArray(layers[1].data.values) ? (layers[1].data.values as Obj[]) : [];
      if (l1Data.length && "overall" in l1Data[0]) {
        const rows = [...l0Data].reverse();
        const xEnc = isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).x) ? ((layers[0].encoding as Obj).x as Obj) : {};
        const isPct = isObj(xEnc.axis) && String(xEnc.axis.format ?? "").includes("%");
        const xTitle = String(xEnc.title ?? "Value");
        const overall = Number(l1Data[0].overall);

        const option: EChartsOption = {
          animationDuration: 400,
          title: titleBlock(spec, tokens, compact),
          tooltip: {
            ...baseTooltip(tokens),
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: (params: unknown) => {
              const arr = Array.isArray(params) ? params : [params];
              const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
              const r = rows[idx];
              if (!r) return "";
              return [
                `<div style="font-weight:600;margin-bottom:4px">${esc(r.group)}</div>`,
                `<div>${esc(xTitle)}: <b>${fmtSmart(r.value, isPct)}</b></div>`,
                `<div style="opacity:.75">Rows: ${Number(r.n ?? 0).toLocaleString()}</div>`,
              ].join("");
            },
          },
          grid: baseGrid(compact, false, false, 16),
          xAxis: {
            type: "value",
            name: compact ? "" : xTitle,
            nameLocation: "middle",
            nameGap: 24,
            nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
            axisLabel: {
              color: tokens.axisLabel,
              fontSize: 11,
              formatter: (v: number) => (isPct ? `${Math.round(v * 100)}%` : fmtSmart(v)),
            },
            splitLine: { lineStyle: { color: tokens.splitLine } },
          },
          yAxis: {
            type: "category",
            data: rows.map((r) => String(r.group)),
            axisLabel: { color: tokens.text, fontSize: 11.5, width: compact ? 105 : 170, overflow: "truncate" },
            axisLine: { lineStyle: { color: tokens.axisLine } },
            axisTick: { show: false },
          },
          series: [
            {
              type: "bar",
              barMaxWidth: 24,
              data: rows.map((r) => ({
                value: Number(r.value),
                itemStyle: {
                  color: String(r.group) === "In the segment" ? tokens.primary : tokens.neutral,
                  borderRadius: [0, 4, 4, 0],
                },
              })),
              markLine: Number.isFinite(overall)
                ? {
                    silent: true,
                    symbol: "none",
                    lineStyle: { color: tokens.warning, type: "dashed", width: 1.8 },
                    label: {
                      show: !compact,
                      formatter: `All: ${fmtSmart(overall, isPct)}`,
                      color: tokens.warning,
                      fontSize: 10.5,
                    },
                    data: [{ xAxis: overall }],
                  }
                : undefined,
            },
          ],
        };
        return { option };
      }
    }

    // 7b. Change-point timeline: layer[0] has { period, value, n }
    if (l0Data.length && "period" in l0Data[0] && "value" in l0Data[0]) {
      const segs = layers[1] && isObj(layers[1].data) && Array.isArray(layers[1].data.values) ? (layers[1].data.values as Obj[]) : [];
      const brks = layers[2] && isObj(layers[2].data) && Array.isArray(layers[2].data.values) ? (layers[2].data.values as Obj[]) : [];
      const brkDate = brks[0]?.break ? String(brks[0].break) : null;
      const yEnc = isObj(layers[0].encoding) && isObj((layers[0].encoding as Obj).y) ? ((layers[0].encoding as Obj).y as Obj) : {};
      const yTitle = String(yEnc.title ?? "Value");

      const periods = l0Data.map((p) => String(p.period));
      const meanBefore = segs[0]?.mean !== undefined ? Number(segs[0].mean) : null;
      const meanAfter = segs[1]?.mean !== undefined ? Number(segs[1].mean) : null;
      const brkIdx = brkDate ? periods.findIndex((d) => d >= brkDate) : -1;

      const regimeLine = periods.map((p) => {
        if (brkDate && p < brkDate && meanBefore !== null) return meanBefore;
        if (brkDate && p >= brkDate && meanAfter !== null) return meanAfter;
        return null;
      });

      const option: EChartsOption = {
        animationDuration: 450,
        title: titleBlock(spec, tokens, compact),
        tooltip: {
          ...baseTooltip(tokens),
          trigger: "axis",
          axisPointer: { type: "cross" },
        },
        grid: baseGrid(compact, false, enableZoomSlider),
        dataZoom: compact
          ? undefined
          : [
              { type: "inside", xAxisIndex: 0 },
              ...(enableZoomSlider ? [{ type: "slider" as const, xAxisIndex: 0, height: 18, bottom: 8 }] : []),
            ],
        xAxis: {
          type: "category",
          data: periods,
          axisLabel: { color: tokens.axisLabel, fontSize: 11 },
          axisLine: { lineStyle: { color: tokens.axisLine } },
        },
        yAxis: {
          type: "value",
          scale: true,
          name: compact ? "" : yTitle,
          nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
          axisLabel: { color: tokens.axisLabel, fontSize: 11 },
          splitLine: { lineStyle: { color: tokens.splitLine } },
        },
        series: [
          {
            type: "line",
            name: yTitle,
            smooth: 0.2,
            symbolSize: compact ? 4 : 6,
            lineStyle: { color: tokens.primary, width: 2.4 },
            itemStyle: { color: tokens.primary },
            areaStyle: { color: tokens.bandFill },
            data: l0Data.map((p) => Number(p.value)),
            markLine:
              brkIdx >= 0
                ? {
                    silent: true,
                    symbol: ["none", "none"],
                    lineStyle: { color: tokens.negative, width: 2, type: "solid" },
                    label: {
                      show: !compact,
                      formatter: `Shift: ${brkDate}`,
                      color: tokens.negative,
                      fontSize: 11,
                      fontWeight: 600,
                    },
                    data: [{ xAxis: brkIdx }],
                  }
                : undefined,
          },
          ...(regimeLine.some((v) => v !== null)
            ? [
                {
                  type: "line" as const,
                  name: "Regime mean",
                  step: "end" as const,
                  showSymbol: false,
                  lineStyle: { color: tokens.warning, width: 1.8, type: "dashed" as const },
                  data: regimeLine,
                },
              ]
            : []),
        ],
      };
      return { option, canZoom: true };
    }

    // 7c. Numeric Pair: Scatter (or binned 2D rect) + Spline + 95% Band
    const fitLayer = layers.find(
      (l) => isObj(l.data) && Array.isArray(l.data.values) && l.data.values.length > 0 && "fit" in (l.data.values[0] as Obj),
    );
    if (fitLayer && l0Data.length) {
      const curveRaw = ((fitLayer.data as Obj).values as Obj[]).map((c) => ({
        x: Number(c.x),
        fit: Number(c.fit),
        low: Number(c.low ?? c.fit),
        high: Number(c.high ?? c.fit),
      }));
      const areaLayer = layers.find(
        (l) => isObj(l.data) && Array.isArray(l.data.values) && l.data.values.length > 0 && "low" in (l.data.values[0] as Obj),
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
      const polySeries = makeConfidencePolygonSeries(bandData, tokens.bandFill);

      const baseSeries: Record<string, unknown>[] = [];
      let scatterPts: { x: number; y: number }[] | undefined;

      if (isBinned) {
        baseSeries.push({
          type: "custom",
          name: "Density",
          renderItem: (_p: unknown, api: { value: (i: number) => number; coord: (v: [number, number]) => [number, number] }) => {
            const p0 = api.coord([api.value(0), api.value(3)]);
            const p1 = api.coord([api.value(1), api.value(2)]);
            const share = Math.min(1, Math.log1p(api.value(4)) / 5.5);
            return {
              type: "rect",
              shape: {
                x: Math.min(p0[0], p1[0]),
                y: Math.min(p0[1], p1[1]),
                width: Math.max(1.5, Math.abs(p1[0] - p0[0]) - 0.5),
                height: Math.max(1.5, Math.abs(p1[1] - p0[1]) - 0.5),
              },
              style: {
                fill: tokens.primary,
                opacity: 0.14 + 0.72 * share,
              },
            };
          },
          data: l0Data.map((r) => [Number(r.x), Number(r.x_end), Number(r.y), Number(r.y_end), Number(r.rows)]),
          z: 1,
        });
      } else {
        scatterPts = l0Data.map((r) => ({ x: Number(r.x), y: Number(r.y) }));
        baseSeries.push({
          type: "scatter",
          name: "Observations",
          symbolSize: compact ? 4.5 : 6,
          itemStyle: { color: tokens.isDark ? "#94A3B8" : "#64748B", opacity: 0.42 },
          emphasis: { itemStyle: { color: tokens.primary, opacity: 1, borderColor: "#fff", borderWidth: 1.5 } },
          data: scatterPts.map((p) => [p.x, p.y]),
          z: 1,
        });
      }

      if (polySeries) baseSeries.push(polySeries);
      baseSeries.push({
        type: "line",
        name: "Spline fit",
        smooth: true,
        showSymbol: false,
        lineStyle: { color: tokens.primary, width: 2.8 },
        data: curveRaw.map((c) => [c.x, c.fit]),
        z: 4,
      });

      const option: EChartsOption = {
        animationDuration: 420,
        title: titleBlock(spec, tokens, compact),
        tooltip: {
          ...baseTooltip(tokens),
          trigger: "axis",
          axisPointer: { type: "cross", lineStyle: { color: tokens.axisLine } },
        },
        grid: baseGrid(compact, false, enableZoomSlider),
        dataZoom: compact
          ? undefined
          : [
              { type: "inside", xAxisIndex: 0, filterMode: "none" },
              { type: "inside", yAxisIndex: 0, filterMode: "none" },
              ...(enableZoomSlider ? [{ type: "slider" as const, xAxisIndex: 0, height: 18, bottom: 8 }] : []),
            ],
        xAxis: {
          type: "value",
          scale: true,
          name: compact ? "" : xTitle,
          nameLocation: "middle",
          nameGap: 25,
          nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
          axisLabel: { color: tokens.axisLabel, fontSize: 11 },
          splitLine: { lineStyle: { color: tokens.splitLine } },
        },
        yAxis: {
          type: "value",
          scale: true,
          name: compact ? "" : yTitle,
          nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
          axisLabel: { color: tokens.axisLabel, fontSize: 11 },
          splitLine: { lineStyle: { color: tokens.splitLine } },
        },
        series: baseSeries as EChartsOption["series"],
      };
      return {
        option,
        canZoom: true,
        canBrush: !compact && !!scatterPts,
        scatterPoints: scatterPts,
        extractDrill: !isBinned
          ? () => null
          : (p: unknown) => {
              const val = (p as { value?: number[] })?.value;
              if (val && val.length >= 2) return { column: xTitle, low: val[0], high: val[1] };
              return null;
            },
      };
    }
  }

  // 8. Cross-file numeric overlaid histogram: { source, x0, x1, share, n }
  if (topValues?.length && "source" in topValues[0] && "x0" in topValues[0] && "share" in topValues[0]) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";
    const sources = [...new Set(topValues.map((r) => String(r.source)))];
    const firstSrcRows = topValues.filter((r) => String(r.source) === sources[0]);
    const labels = firstSrcRows.map((r) => `${fmtSmart(r.x0)}–${fmtSmart(r.x1)}`);

    const option: EChartsOption = {
      animationDuration: 400,
      title: titleBlock(spec, tokens, compact),
      tooltip: { ...baseTooltip(tokens), trigger: "axis", axisPointer: { type: "shadow" } },
      legend: compact ? undefined : { top: 28, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } },
      grid: baseGrid(compact, true),
      xAxis: {
        type: "category",
        data: labels,
        name: compact ? "" : xTitle,
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 10, interval: "auto" },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: tokens.axisLabel, fontSize: 11, formatter: (v: number) => `${Math.round(v * 100)}%` },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: sources.map((src, idx) => ({
        type: "bar",
        name: src,
        barGap: "-75%",
        itemStyle: {
          color: idx === 0 ? tokens.primary : tokens.warning,
          opacity: 0.55,
          borderRadius: [3, 3, 0, 0],
        },
        data: topValues.filter((r) => String(r.source) === src).map((r) => Number(r.share)),
      })),
    };
    return { option };
  }

  // 9. Cross-file categorical grouped bars: { level, source, share }
  if (topValues?.length && "level" in topValues[0] && "source" in topValues[0] && "share" in topValues[0]) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const yTitle = isObj(enc.y) ? String(enc.y.title ?? "Category") : "Category";
    const sources = [...new Set(topValues.map((r) => String(r.source)))];
    const levels = [...new Set(topValues.map((r) => String(r.level)))].reverse();

    const option: EChartsOption = {
      animationDuration: 400,
      title: titleBlock(spec, tokens, compact),
      tooltip: { ...baseTooltip(tokens), trigger: "axis", axisPointer: { type: "shadow" } },
      legend: compact ? undefined : { top: 28, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } },
      grid: baseGrid(compact, true, false, 16),
      xAxis: {
        type: "value",
        axisLabel: { color: tokens.axisLabel, fontSize: 11, formatter: (v: number) => `${Math.round(v * 100)}%` },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "category",
        data: levels,
        axisLabel: { color: tokens.text, fontSize: 11.5 },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      series: sources.map((src, idx) => ({
        type: "bar",
        name: src,
        barMaxWidth: 16,
        itemStyle: { color: idx === 0 ? tokens.primary : tokens.warning, borderRadius: [0, 3, 3, 0] },
        data: levels.map((lv) => {
          const hit = topValues.find((r) => String(r.level) === lv && String(r.source) === src);
          return hit ? Number(hit.share) : 0;
        }),
      })),
    };
    return {
      option,
      drillColumn: yTitle,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        return typeof idx === "number" && levels[idx] ? { column: yTitle, value: levels[idx] } : null;
      },
    };
  }

  // 10. Single Histogram with outlier flag: { x0, x1, n, flag }
  if (topValues?.length && "x0" in topValues[0] && "x1" in topValues[0] && "n" in topValues[0] && "flag" in topValues[0]) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";

    const option: EChartsOption = {
      animationDuration: 380,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
          const r = topValues[idx];
          if (!r) return "";
          return `<div><b>${fmtSmart(r.x0)} – ${fmtSmart(r.x1)}</b></div><div>Rows: <b>${Number(r.n).toLocaleString()}</b>${r.flag ? ` <span style="color:${tokens.warning}">(outlier range)</span>` : ""}</div>`;
        },
      },
      grid: baseGrid(compact),
      xAxis: {
        type: "category",
        data: topValues.map((r) => fmtSmart(r.x0)),
        name: compact ? "" : xTitle,
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 10.5 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: [
        {
          type: "bar",
          barCategoryGap: "6%",
          data: topValues.map((r) => ({
            value: Number(r.n),
            itemStyle: {
              color: r.flag ? tokens.warning : tokens.primary,
              opacity: r.flag ? 0.92 : 0.72,
              borderRadius: [3, 3, 0, 0],
            },
          })),
        },
      ],
    };
    return {
      option,
      drillColumn: xTitle,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        if (typeof idx === "number" && topValues[idx]) {
          return { column: xTitle, low: Number(topValues[idx].x0), high: Number(topValues[idx].x1) };
        }
        return null;
      },
    };
  }

  // 11. Anomaly scatter: { x, y, flag, row }
  if (topValues?.length && "x" in topValues[0] && "y" in topValues[0] && "flag" in topValues[0]) {
    const enc = isObj(spec.encoding) ? spec.encoding : {};
    const xTitle = isObj(enc.x) ? String(enc.x.title ?? "X") : "X";
    const yTitle = isObj(enc.y) ? String(enc.y.title ?? "Y") : "Y";
    const normal = topValues.filter((r) => !r.flag);
    const flagged = topValues.filter((r) => Boolean(r.flag));

    const option: EChartsOption = {
      animationDuration: 420,
      title: titleBlock(spec, tokens, compact),
      tooltip: {
        ...baseTooltip(tokens),
        trigger: "item",
        formatter: (p: unknown) => {
          const v = (p as { value?: [number, number, number]; seriesName?: string })?.value;
          if (!v) return "";
          return `<div><b>${esc((p as { seriesName?: string }).seriesName)}</b>${v[2] ? ` · Row #${v[2]}` : ""}</div><div>${esc(xTitle)}: <b>${fmtSmart(v[0])}</b></div><div>${esc(yTitle)}: <b>${fmtSmart(v[1])}</b></div>`;
        },
      },
      legend: compact ? undefined : { top: 28, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } },
      grid: baseGrid(compact, true, enableZoomSlider),
      dataZoom: compact
        ? undefined
        : [
            { type: "inside", xAxisIndex: 0, filterMode: "none" },
            { type: "inside", yAxisIndex: 0, filterMode: "none" },
            ...(enableZoomSlider ? [{ type: "slider" as const, xAxisIndex: 0, height: 18, bottom: 8 }] : []),
          ],
      xAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : xTitle,
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: compact ? "" : yTitle,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: [
        {
          type: "scatter",
          name: "Normal rows",
          symbolSize: compact ? 4.5 : 5.5,
          itemStyle: { color: tokens.neutral, opacity: 0.38 },
          data: normal.map((r) => [Number(r.x), Number(r.y), Number(r.row ?? 0)]),
        },
        {
          type: "scatter",
          name: "Flagged anomalies",
          symbolSize: compact ? 7.5 : 10,
          symbol: "diamond",
          itemStyle: { color: tokens.warning, borderColor: tokens.negative, borderWidth: 1.2 },
          data: flagged.map((r) => [Number(r.x), Number(r.y), Number(r.row ?? 0)]),
          z: 4,
        },
      ],
    };
    return {
      option,
      canZoom: true,
      canBrush: !compact,
      scatterPoints: topValues.map((r) => ({ x: Number(r.x), y: Number(r.y), row: Number(r.row ?? 0) })),
    };
  }

  // 12. Simple horizontal bars: { <y_field>, value }
  if (topValues?.length && "value" in topValues[0] && isObj(spec.encoding)) {
    const enc = spec.encoding;
    const yField = isObj(enc.y) && typeof enc.y.field === "string" ? enc.y.field : null;
    if (yField && yField in topValues[0]) {
      const sorted = [...topValues].sort((a, b) => Number(a.value ?? 0) - Number(b.value ?? 0));
      const xTitle = isObj(enc.x) ? String(enc.x.title ?? "Value") : "Value";
      const isPct = isObj(enc.x) && isObj(enc.x.axis) && String(enc.x.axis.format ?? "").includes("%");

      const option: EChartsOption = {
        animationDuration: 360,
        title: titleBlock(spec, tokens, compact),
        tooltip: { ...baseTooltip(tokens), trigger: "axis", axisPointer: { type: "shadow" } },
        grid: baseGrid(compact, false, false, 16),
        xAxis: {
          type: "value",
          name: compact ? "" : xTitle,
          nameLocation: "middle",
          nameGap: 24,
          nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
          axisLabel: {
            color: tokens.axisLabel,
            fontSize: 11,
            formatter: (v: number) => (isPct ? `${Math.round(v * 100)}%` : fmtSmart(v)),
          },
          splitLine: { lineStyle: { color: tokens.splitLine } },
        },
        yAxis: {
          type: "category",
          data: sorted.map((r) => String(r[yField])),
          axisLabel: { color: tokens.text, fontSize: 11.5, width: compact ? 100 : 160, overflow: "truncate" },
          axisLine: { lineStyle: { color: tokens.axisLine } },
          axisTick: { show: false },
        },
        series: [
          {
            type: "bar",
            barMaxWidth: 20,
            itemStyle: { color: tokens.primary, borderRadius: [0, 4, 4, 0] },
            data: sorted.map((r) => Number(r.value)),
          },
        ],
      };
      return {
        option,
        drillColumn: yField,
        extractDrill: (p: unknown) => {
          const idx = (p as { dataIndex?: number })?.dataIndex;
          return typeof idx === "number" && sorted[idx] ? { column: yField, value: String(sorted[idx][yField]) } : null;
        },
      };
    }
  }

  return null;
}

export type ExploreVisualStyle = "bar" | "lollipop" | "boxplot" | "sunburst" | "treemap" | "line" | "area";

/**
 * Builds interactive ECharts options for the Explore & Drill-Down Studio.
 */
export function buildExploreOption(
  res: ExploreResponse,
  tokens: ChartThemeTokens,
  visualStyle?: ExploreVisualStyle,
): AdaptedChart {
  const d = res.data;
  const tooltip = baseTooltip(tokens);

  if (res.mode === "hierarchy") {
    const tree = (d.tree as Obj[]) ?? [];
    const kind = visualStyle === "treemap" ? "treemap" : "sunburst";
    const option: EChartsOption = {
      animationDuration: 500,
      animationEasing: "cubicOut",
      tooltip: {
        ...tooltip,
        formatter: (p: unknown) => {
          const info = (p as { data?: Obj; treePathInfo?: { name: string }[] }) ?? {};
          const path = (info.treePathInfo ?? []).map((x) => x.name).filter(Boolean).join(" › ");
          const node = info.data ?? {};
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(path || node.name)}</div>`,
            `<div>Value: <b>${fmtSmart(node.value)}</b></div>`,
            node.n !== undefined ? `<div style="opacity:.75">Rows: ${Number(node.n).toLocaleString()}</div>` : "",
          ].join("");
        },
      },
      color: tokens.palette,
      series:
        kind === "treemap"
          ? [
              {
                type: "treemap",
                data: tree as never[],
                roam: false,
                leafDepth: 2,
                breadcrumb: {
                  show: true,
                  bottom: 6,
                  itemStyle: { color: tokens.tooltipBg, borderColor: tokens.axisLine, textStyle: { color: tokens.text } },
                },
                label: { show: true, formatter: "{b}\n{c}", fontSize: 11.5 },
                upperLabel: { show: true, height: 24, color: tokens.text, backgroundColor: "transparent" },
                itemStyle: { borderColor: tokens.isDark ? "#0B0F17" : "#FFFFFF", borderWidth: 2, gapWidth: 2 },
              },
            ]
          : [
              {
                type: "sunburst",
                data: tree as never[],
                radius: ["16%", "90%"],
                sort: "desc",
                emphasis: { focus: "ancestor" },
                itemStyle: { borderRadius: 5, borderColor: tokens.isDark ? "#0B0F17" : "#FFFFFF", borderWidth: 2 },
                label: { rotate: "radial", minAngle: 10, color: tokens.text, fontSize: 11 },
              },
            ],
    };
    return { option };
  }

  if (res.mode === "time") {
    const pts = ((d.points as Obj[]) ?? []);
    const seriesList = ((d.series as { name: string; values: (number | null)[] }[]) ?? []);
    const periods = pts.map((p) => String(p.period));
    const metricLabel = String(d.metric_label ?? "Value");
    const isArea = visualStyle !== "bar" && visualStyle !== "line";
    const isBar = visualStyle === "bar";

    const option: EChartsOption = {
      animationDuration: 420,
      tooltip: { ...tooltip, trigger: "axis", axisPointer: { type: "cross" } },
      legend: seriesList.length
        ? { top: 4, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } }
        : undefined,
      grid: { top: seriesList.length ? 36 : 20, right: 24, bottom: 52, left: 48, containLabel: true },
      dataZoom: [
        { type: "inside", xAxisIndex: 0 },
        { type: "slider", xAxisIndex: 0, height: 18, bottom: 8, borderColor: tokens.axisLine },
      ],
      xAxis: {
        type: "category",
        data: periods,
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      yAxis: {
        type: "value",
        scale: !isBar,
        name: metricLabel,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11, formatter: (v: number) => fmtSmart(v) },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: seriesList.length
        ? seriesList.map((s, idx) => ({
            type: isBar ? ("bar" as const) : ("line" as const),
            name: s.name,
            smooth: 0.2,
            symbolSize: 6,
            itemStyle: { color: tokens.palette[idx % tokens.palette.length] },
            data: s.values,
          }))
        : [
            {
              type: isBar ? "bar" : "line",
              name: metricLabel,
              smooth: 0.22,
              symbolSize: 7,
              itemStyle: { color: tokens.primary, borderRadius: isBar ? [4, 4, 0, 0] : 0 },
              lineStyle: { color: tokens.primary, width: 2.6 },
              areaStyle: isArea && !isBar ? { color: tokens.bandFill } : undefined,
              data: pts.map((p) => (p.value === null || p.value === undefined ? null : Number(p.value))),
            },
          ],
    };

    return {
      option,
      canZoom: true,
      drillColumn: res.x ?? undefined,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        if (typeof idx === "number" && pts[idx] && res.x) {
          return {
            column: res.x,
            period: String(pts[idx].period),
            periodEnd: String(pts[idx].period_end),
          };
        }
        return null;
      },
    };
  }

  if (res.mode === "histogram") {
    const bins = ((d.bins as Obj[]) ?? []);
    const grouped = ((d.series as { name: string; counts: number[]; shares: number[] }[]) ?? []);
    const st = (d.stats as Obj) ?? {};

    const option: EChartsOption = {
      animationDuration: 380,
      tooltip: {
        ...tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
      },
      legend: grouped.length ? { top: 4, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } } : undefined,
      grid: { top: grouped.length ? 36 : 20, right: 24, bottom: 34, left: 48, containLabel: true },
      xAxis: {
        type: "category",
        data: bins.map((b) => String(b.label)),
        axisLabel: { color: tokens.axisLabel, fontSize: 10.5, interval: "auto", rotate: bins.length > 18 ? 25 : 0 },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      yAxis: {
        type: "value",
        name: grouped.length ? "Share" : "Rows",
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: {
          color: tokens.axisLabel,
          fontSize: 11,
          formatter: (v: number) => (grouped.length ? `${Math.round(v * 100)}%` : fmtSmart(v)),
        },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: grouped.length
        ? grouped.map((g, idx) => ({
            type: "bar",
            name: g.name,
            barGap: "-70%",
            itemStyle: { color: tokens.palette[idx % tokens.palette.length], opacity: 0.52, borderRadius: [3, 3, 0, 0] },
            data: g.shares,
          }))
        : [
            {
              type: "bar",
              name: "Count",
              barCategoryGap: "8%",
              itemStyle: { color: tokens.primary, opacity: 0.82, borderRadius: [3, 3, 0, 0] },
              emphasis: { itemStyle: { opacity: 1, color: tokens.secondary } },
              data: bins.map((b) => Number(b.count)),
              markLine:
                typeof st.median === "number"
                  ? {
                      silent: true,
                      symbol: "none",
                      label: { formatter: `Median: ${fmtSmart(st.median)}`, color: tokens.warning, fontSize: 11 },
                      lineStyle: { color: tokens.warning, type: "dashed", width: 1.8 },
                      data: [
                        {
                          xAxis: Math.max(
                            0,
                            bins.findIndex((b) => Number(b.x1) >= Number(st.median)),
                          ),
                        },
                      ],
                    }
                  : undefined,
            },
          ],
    };

    return {
      option,
      drillColumn: res.x ?? undefined,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        if (typeof idx === "number" && bins[idx] && res.x) {
          return { column: res.x, low: Number(bins[idx].x0), high: Number(bins[idx].x1) };
        }
        return null;
      },
    };
  }

  if (res.mode === "scatter") {
    const pts = ((d.points as { x: number; y: number; row?: number; group?: string | null }[]) ?? []);
    const curve = ((d.curve as { x: number; fit: number; low: number; high: number }[]) ?? []);
    const xLabel = String(d.x_label ?? res.x ?? "X");
    const yLabel = String(d.y_label ?? res.y ?? "Y");
    const gLabel = d.group_label ? String(d.group_label) : null;

    const series: Record<string, unknown>[] = [];
    if (gLabel) {
      const groups = [...new Set(pts.map((p) => String(p.group ?? "(missing)")))];
      groups.forEach((g, idx) => {
        series.push({
          type: "scatter",
          name: g,
          symbolSize: 6.5,
          itemStyle: { color: tokens.palette[idx % tokens.palette.length], opacity: 0.65 },
          data: pts.filter((p) => String(p.group ?? "(missing)") === g).map((p) => [p.x, p.y, p.row ?? 0]),
        });
      });
    } else {
      series.push({
        type: "scatter",
        name: "Records",
        symbolSize: 6,
        itemStyle: { color: tokens.primary, opacity: 0.52 },
        emphasis: { itemStyle: { opacity: 1, borderColor: "#fff", borderWidth: 1.5 } },
        data: pts.map((p) => [p.x, p.y, p.row ?? 0]),
      });
    }

    const poly = makeConfidencePolygonSeries(curve, tokens.bandFill);
    if (poly) series.push(poly);
    if (curve.length) {
      series.push({
        type: "line",
        name: "Spline trend",
        smooth: true,
        showSymbol: false,
        lineStyle: { color: tokens.warning, width: 2.6 },
        data: curve.map((c) => [c.x, c.fit]),
        z: 5,
      });
    }

    const option: EChartsOption = {
      animationDuration: 420,
      tooltip: {
        ...tooltip,
        trigger: "item",
        formatter: (p: unknown) => {
          const item = p as { seriesName?: string; value?: [number, number, number] };
          if (!item.value) return "";
          return [
            gLabel ? `<div style="font-weight:600">${esc(gLabel)}: ${esc(item.seriesName)}</div>` : "",
            item.value[2] ? `<div style="opacity:.7">Row #${item.value[2]}</div>` : "",
            `<div>${esc(xLabel)}: <b>${fmtSmart(item.value[0])}</b></div>`,
            `<div>${esc(yLabel)}: <b>${fmtSmart(item.value[1])}</b></div>`,
          ].join("");
        },
      },
      legend: gLabel ? { top: 4, right: 12, textStyle: { color: tokens.subtext, fontSize: 11 } } : undefined,
      grid: { top: gLabel ? 36 : 20, right: 24, bottom: 52, left: 52, containLabel: true },
      dataZoom: [
        { type: "inside", xAxisIndex: 0, filterMode: "none" },
        { type: "inside", yAxisIndex: 0, filterMode: "none" },
        { type: "slider", xAxisIndex: 0, height: 18, bottom: 8 },
      ],
      xAxis: {
        type: "value",
        scale: true,
        name: xLabel,
        nameLocation: "middle",
        nameGap: 26,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: yLabel,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: series as EChartsOption["series"],
    };

    return {
      option,
      canZoom: true,
      canBrush: true,
      scatterPoints: pts.map((p) => ({ x: p.x, y: p.y, row: p.row, group: p.group ?? undefined })),
    };
  }

  if (res.mode === "heatmap") {
    const xCats = ((d.x_categories as string[]) ?? []);
    const yCats = ((d.y_categories as string[]) ?? []);
    const cells = ((d.cells as Obj[]) ?? []);
    const isPct = Boolean(d.is_percent);
    const vals = cells.map((c) => Number(c.value ?? 0)).filter(Number.isFinite);
    const maxV = Math.max(...vals, 1e-6);
    const minV = Math.min(...vals, 0);

    const option: EChartsOption = {
      animationDuration: 380,
      tooltip: {
        ...tooltip,
        formatter: (p: unknown) => {
          const val = (p as { value?: [number, number, number, number] })?.value;
          if (!val) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(res.y)}: ${esc(yCats[val[1]])} × ${esc(res.x)}: ${esc(xCats[val[0]])}</div>`,
            `<div>${esc(d.metric_label)}: <b>${fmtSmart(val[2], isPct)}</b></div>`,
            `<div style="opacity:.75">Rows: ${Number(val[3]).toLocaleString()}</div>`,
          ].join("");
        },
      },
      grid: { top: 20, right: 24, bottom: 48, left: 20, containLabel: true },
      xAxis: {
        type: "category",
        data: xCats,
        axisLabel: { color: tokens.axisLabel, fontSize: 11, rotate: xCats.length > 8 ? 25 : 0 },
      },
      yAxis: {
        type: "category",
        data: yCats,
        axisLabel: { color: tokens.text, fontSize: 11 },
      },
      visualMap: {
        min: minV,
        max: maxV,
        orient: "horizontal",
        right: 16,
        bottom: 2,
        itemWidth: 10,
        itemHeight: 90,
        textStyle: { color: tokens.subtext, fontSize: 10.5 },
        inRange: { color: tokens.heatmapRamp },
      },
      series: [
        {
          type: "heatmap",
          data: cells.map((c) => [Number(c.xi), Number(c.yi), c.value === null ? 0 : Number(c.value), Number(c.n)]),
          label: {
            show: xCats.length <= 10 && yCats.length <= 10,
            formatter: (p: unknown) => {
              const v = (p as { value?: number[] })?.value?.[2] ?? 0;
              return fmtSmart(v, isPct);
            },
            fontSize: 10.5,
            color: tokens.text,
          },
          itemStyle: { borderColor: tokens.isDark ? "#0B0F17" : "#FFFFFF", borderWidth: 2, borderRadius: 3 },
        },
      ],
    };

    return {
      option,
      drillColumn: res.x ?? undefined,
      drillExtraColumn: res.y ?? undefined,
      extractDrill: (p: unknown) => {
        const val = (p as { value?: number[] })?.value;
        if (!val || !res.x || !res.y) return null;
        return { column: res.x, value: xCats[val[0]], extraColumn: res.y, extraValue: yCats[val[1]] };
      },
    };
  }

  // Group / Boxplot / Lollipop / Split Bar
  const categories = ((d.categories as string[]) ?? []);
  const splitSeries = ((d.series as { name: string; points: Record<string, Obj> }[]) ?? []);
  const rows = ((d.rows as Obj[]) ?? []);
  const isPct = Boolean(d.is_percent);
  const metricLabel = String(d.metric_label ?? "Value");

  if (splitSeries.length) {
    const option: EChartsOption = {
      animationDuration: 400,
      tooltip: { ...tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 4, right: 12, textStyle: { color: tokens.subtext, fontSize: 11.5 } },
      grid: { top: 36, right: 24, bottom: 32, left: 20, containLabel: true },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: tokens.text, fontSize: 11, rotate: categories.length > 8 ? 22 : 0 },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      yAxis: {
        type: "value",
        name: metricLabel,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: {
          color: tokens.axisLabel,
          fontSize: 11,
          formatter: (v: number) => (isPct ? `${Math.round(v * 100)}%` : fmtSmart(v)),
        },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      series: splitSeries.map((s, idx) => ({
        type: "bar",
        name: s.name,
        barMaxWidth: 26,
        itemStyle: { color: tokens.palette[idx % tokens.palette.length], borderRadius: [4, 4, 0, 0] },
        data: categories.map((cat) => {
          const pt = s.points[cat];
          return pt?.value !== undefined && pt?.value !== null ? Number(pt.value) : 0;
        }),
      })),
    };
    return {
      option,
      drillColumn: res.x ?? undefined,
      drillExtraColumn: res.group ?? undefined,
      extractDrill: (p: unknown) => {
        const item = p as { dataIndex?: number; seriesName?: string };
        if (typeof item.dataIndex === "number" && res.x && categories[item.dataIndex]) {
          return {
            column: res.x,
            value: categories[item.dataIndex],
            extraColumn: res.group ?? undefined,
            extraValue: item.seriesName,
          };
        }
        return null;
      },
    };
  }

  if ((visualStyle === "boxplot" || res.mode === "boxplot") && Boolean(d.has_box)) {
    const rev = [...rows].reverse();
    const option: EChartsOption = {
      animationDuration: 420,
      tooltip: {
        ...tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
          const r = rev[idx];
          if (!r) return "";
          return [
            `<div style="font-weight:600;margin-bottom:4px">${esc(r.category)} (n = ${Number(r.n).toLocaleString()})</div>`,
            `<div>Median: <b>${fmtSmart(r.median)}</b> · Mean: <b>${fmtSmart(r.mean)}</b></div>`,
            `<div>IQR: [${fmtSmart(r.q1)}, ${fmtSmart(r.q3)}]</div>`,
            `<div>Range: [${fmtSmart(r.min)}, ${fmtSmart(r.max)}]</div>`,
          ].join("");
        },
      },
      grid: { top: 20, right: 24, bottom: 32, left: 20, containLabel: true },
      xAxis: {
        type: "value",
        scale: true,
        name: res.y ?? metricLabel,
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
        axisLabel: { color: tokens.axisLabel, fontSize: 11 },
        splitLine: { lineStyle: { color: tokens.splitLine } },
      },
      yAxis: {
        type: "category",
        data: rev.map((r) => String(r.category)),
        axisLabel: { color: tokens.text, fontSize: 11.5, width: 140, overflow: "truncate" },
        axisLine: { lineStyle: { color: tokens.axisLine } },
      },
      series: [
        {
          type: "boxplot",
          itemStyle: { color: tokens.iqrFill, borderColor: tokens.primary, borderWidth: 1.8 },
          data: rev.map((r) => [Number(r.min ?? 0), Number(r.q1 ?? 0), Number(r.median ?? 0), Number(r.q3 ?? 0), Number(r.max ?? 0)]),
        },
        {
          type: "scatter",
          name: "Mean",
          symbol: "diamond",
          symbolSize: 8,
          itemStyle: { color: tokens.warning },
          data: rev.map((r) => Number(r.mean ?? 0)),
          z: 4,
        },
      ],
    };
    return {
      option,
      drillColumn: res.x ?? undefined,
      extractDrill: (p: unknown) => {
        const idx = (p as { dataIndex?: number })?.dataIndex;
        return typeof idx === "number" && rev[idx] && res.x ? { column: res.x, value: String(rev[idx].category) } : null;
      },
    };
  }

  // Default Group Bar or Lollipop (horizontal for clean label readability)
  const rev = [...rows].reverse();
  const overall = typeof d.overall === "number" ? d.overall : null;
  const isLollipop = visualStyle === "lollipop";

  const option: EChartsOption = {
    animationDuration: 400,
    animationEasing: "cubicOut",
    tooltip: {
      ...tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: unknown) => {
        const arr = Array.isArray(params) ? params : [params];
        const idx = (arr[0] as { dataIndex?: number })?.dataIndex ?? 0;
        const r = rev[idx];
        if (!r) return "";
        const ciTxt =
          typeof r.ci_low === "number" && typeof r.ci_high === "number"
            ? ` <span style="opacity:.75">[${fmtSmart(r.ci_low, isPct)}, ${fmtSmart(r.ci_high, isPct)}]</span>`
            : "";
        return [
          `<div style="font-weight:600;margin-bottom:4px">${esc(r.category)}</div>`,
          `<div>${esc(metricLabel)}: <b>${fmtSmart(r.value, isPct)}</b>${ciTxt}</div>`,
          `<div style="opacity:.75">Rows: ${Number(r.n ?? 0).toLocaleString()} (${fmtSmart(r.share, true)})</div>`,
        ].join("");
      },
    },
    grid: { top: 20, right: 30, bottom: 32, left: 20, containLabel: true },
    xAxis: {
      type: "value",
      name: metricLabel,
      nameLocation: "middle",
      nameGap: 25,
      nameTextStyle: { color: tokens.subtext, fontSize: 11.5 },
      axisLabel: {
        color: tokens.axisLabel,
        fontSize: 11,
        formatter: (v: number) => (isPct ? `${Math.round(v * 100)}%` : fmtSmart(v)),
      },
      splitLine: { lineStyle: { color: tokens.splitLine } },
    },
    yAxis: {
      type: "category",
      data: rev.map((r) => String(r.category)),
      axisLabel: { color: tokens.text, fontSize: 11.5, width: 150, overflow: "truncate" },
      axisLine: { lineStyle: { color: tokens.axisLine } },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: isLollipop ? 3 : 22,
        itemStyle: {
          color: isLollipop ? tokens.axisLine : tokens.primary,
          opacity: isLollipop ? 1 : 0.86,
          borderRadius: [0, 4, 4, 0],
        },
        emphasis: { itemStyle: { opacity: 1, color: tokens.secondary } },
        data: rev.map((r) => Number(r.value ?? 0)),
        markLine:
          overall !== null
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: tokens.warning, type: "dashed", width: 1.6 },
                label: { formatter: `Overall: ${fmtSmart(overall, isPct)}`, color: tokens.warning, fontSize: 10.5 },
                data: [{ xAxis: overall }],
              }
            : undefined,
      },
      ...(isLollipop
        ? [
            {
              type: "scatter" as const,
              symbolSize: 11,
              itemStyle: { color: tokens.primary, borderColor: tokens.tooltipBg, borderWidth: 2 },
              data: rev.map((r) => Number(r.value ?? 0)),
              z: 4,
            },
          ]
        : []),
      ...(rev.some((r) => typeof r.ci_low === "number" && typeof r.ci_high === "number")
        ? [
            {
              type: "custom" as const,
              name: "95% CI",
              renderItem: (params: unknown, api: { value: (i: number) => number; coord: (v: [number, number]) => [number, number] }) => {
                const idx = (params as { dataIndex: number }).dataIndex;
                const lo = api.coord([api.value(1), idx]);
                const hi = api.coord([api.value(2), idx]);
                return {
                  type: "group",
                  children: [
                    { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: tokens.text, lineWidth: 1.6, opacity: 0.75 } },
                    { type: "line", shape: { x1: lo[0], y1: lo[1] - 3.5, x2: lo[0], y2: lo[1] + 3.5 }, style: { stroke: tokens.text, lineWidth: 1.4, opacity: 0.75 } },
                    { type: "line", shape: { x1: hi[0], y1: hi[1] - 3.5, x2: hi[0], y2: hi[1] + 3.5 }, style: { stroke: tokens.text, lineWidth: 1.4, opacity: 0.75 } },
                  ],
                };
              },
              data: rev.map((r, i) => [i, Number(r.ci_low ?? r.value ?? 0), Number(r.ci_high ?? r.value ?? 0)]),
              z: 5,
            } as never,
          ]
        : []),
    ],
  };

  return {
    option,
    drillColumn: res.x ?? undefined,
    extractDrill: (p: unknown) => {
      const idx = (p as { dataIndex?: number })?.dataIndex;
      return typeof idx === "number" && rev[idx] && res.x ? { column: res.x, value: String(rev[idx].category) } : null;
    },
  };
}
