import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import {
  ArrowUpLeft,
  BarChart3,
  ChevronRight,
  Crosshair,
  Download,
  FilterX,
  GitBranch,
  Grid,
  Layers,
  LineChart,
  ScatterChart,
  Table2,
} from "lucide-react";
import { api } from "../lib/api";
import {
  buildExploreOption,
  type DrillTarget,
  type ExploreVisualStyle,
} from "../lib/echartsAdapter";
import { fmtCell, fmtInt, fmtPct, ROLE_LABEL } from "../lib/format";
import { useTheme } from "../lib/theme";
import type {
  AggKind,
  Dataset,
  DrillFilter,
  ExploreMode,
  ExploreResponse,
  TimeGrain,
} from "../lib/types";
import { EChartsSurface } from "./Chart";
import { SpringSegmented } from "./kit";
import { Badge, ErrorBox, Spinner } from "./ui";

interface HistoryFrame {
  label: string;
  mode: ExploreMode;
  x: string;
  y: string;
  group: string;
  agg: AggKind;
  timeGrain: TimeGrain;
  filters: DrillFilter[];
}

export interface ExploreStudioProps {
  projectId: string;
  dataset: Dataset;
  initialX?: string;
  initialY?: string;
  initialGroup?: string;
  initialMode?: ExploreMode;
  initialFilter?: DrillFilter | null;
  compactHeader?: boolean;
}

const MODE_OPTIONS: { id: ExploreMode; label: string; icon: typeof BarChart3 }[] = [
  { id: "auto", label: "Smart Auto", icon: GitBranch },
  { id: "group", label: "Group & CI", icon: BarChart3 },
  { id: "boxplot", label: "Boxplot", icon: Layers },
  { id: "hierarchy", label: "Sunburst / Tree", icon: Layers },
  { id: "time", label: "Time Series", icon: LineChart },
  { id: "histogram", label: "Histogram", icon: BarChart3 },
  { id: "scatter", label: "Scatter + Fit", icon: ScatterChart },
  { id: "heatmap", label: "Matrix", icon: Grid },
];

const GRAINS: TimeGrain[] = ["auto", "year", "quarter", "month", "week", "day"];

export function ExploreStudio({
  projectId,
  dataset,
  initialX,
  initialY,
  initialGroup,
  initialMode = "auto",
  initialFilter = null,
  compactHeader = false,
}: ExploreStudioProps) {
  const { tokens } = useTheme();
  const usable = useMemo(() => dataset.columns.filter((c) => !c.pii), [dataset.columns]);
  const numericCols = useMemo(() => usable.filter((c) => c.role === "numeric"), [usable]);
  const catCols = useMemo(
    () => usable.filter((c) => c.role === "categorical" || c.role === "boolean"),
    [usable],
  );
  const dateCols = useMemo(() => usable.filter((c) => c.role === "datetime"), [usable]);

  const defaultX = useMemo(() => {
    if (initialX && usable.some((c) => c.name === initialX)) return initialX;
    return catCols[0]?.name ?? dateCols[0]?.name ?? numericCols[0]?.name ?? usable[0]?.name ?? "";
  }, [initialX, usable, catCols, dateCols, numericCols]);

  const defaultY = useMemo(() => {
    if (initialY && usable.some((c) => c.name === initialY)) return initialY;
    const firstNum = numericCols.find((c) => c.name !== defaultX);
    return firstNum?.name ?? "";
  }, [initialY, usable, numericCols, defaultX]);

  const [mode, setMode] = useState<ExploreMode>(initialMode);
  const [x, setX] = useState<string>(defaultX);
  const [y, setY] = useState<string>(defaultY);
  const [group, setGroup] = useState<string>(initialGroup ?? "");
  const [thirdDim, setThirdDim] = useState<string>("");
  const [agg, setAgg] = useState<AggKind>(defaultY ? "mean" : "count");
  const [timeGrain, setTimeGrain] = useState<TimeGrain>("auto");
  const [bins, setBins] = useState<number>(28);
  const [visualStyle, setVisualStyle] = useState<ExploreVisualStyle>("bar");
  const [filters, setFilters] = useState<DrillFilter[]>(() => (initialFilter ? [initialFilter] : []));
  const [history, setHistory] = useState<HistoryFrame[]>([]);
  const [drillNextCol, setDrillNextCol] = useState<string>("");

  const [res, setRes] = useState<ExploreResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<unknown>(null);
  const [brushActive, setBrushActive] = useState<boolean>(false);
  const [brushedRange, setBrushedRange] = useState<{
    count: number;
    xMin: number;
    xMax: number;
    yMin: number;
    yMax: number;
    r: number | null;
  } | null>(null);
  const [showSample, setShowSample] = useState<boolean>(false);
  const [resetTick, setResetTick] = useState<number>(0);
  const chartInst = useRef<echarts.ECharts | null>(null);

  // Sync external initialFilter changes (e.g. clicking a bar on FindingPage)
  useEffect(() => {
    if (initialFilter) {
      setFilters([initialFilter]);
    }
  }, [initialFilter]);

  useEffect(() => {
    if (initialX && usable.some((c) => c.name === initialX)) setX(initialX);
  }, [initialX, usable]);

  useEffect(() => {
    if (initialY !== undefined) setY(initialY);
  }, [initialY]);

  const dimensions = useMemo(() => {
    if (mode !== "hierarchy") return [];
    return [x, group, thirdDim].filter(Boolean);
  }, [mode, x, group, thirdDim]);

  const fetchExplore = useCallback(() => {
    if (!x) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const timer = setTimeout(() => {
      api
        .explore(projectId, dataset.id, {
          mode,
          x: x || null,
          y: y || null,
          group: group || null,
          dimensions,
          agg,
          time_grain: timeGrain,
          bins,
          filters,
        })
        .then((r) => {
          if (cancelled) return;
          setRes(r);
          if (!drillNextCol || drillNextCol === r.x) {
            setDrillNextCol(r.next_dimensions[0] ?? "");
          }
        })
        .catch((e) => {
          if (!cancelled) setError(e);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 80);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [projectId, dataset.id, mode, x, y, group, dimensions, agg, timeGrain, bins, filters, drillNextCol]);

  useEffect(fetchExplore, [fetchExplore]);

  const pushState = (label: string) => {
    setHistory((prev) => [
      ...prev,
      { label, mode, x, y, group, agg, timeGrain, filters: [...filters] },
    ]);
  };

  const drillUp = () => {
    if (history.length > 0) {
      const prev = history[history.length - 1];
      setHistory((h) => h.slice(0, -1));
      setMode(prev.mode);
      setX(prev.x);
      setY(prev.y);
      setGroup(prev.group);
      setAgg(prev.agg);
      setTimeGrain(prev.timeGrain);
      setFilters(prev.filters);
      setBrushedRange(null);
      return;
    }
    if (res?.mode === "time" && res.prev_grain) {
      setTimeGrain(res.prev_grain as TimeGrain);
      return;
    }
    if (filters.length > 0) {
      setFilters((f) => f.slice(0, -1));
    }
  };

  const jumpToHistory = (index: number) => {
    if (index < 0) {
      if (history.length > 0) {
        const root = history[0];
        setMode(root.mode);
        setX(root.x);
        setY(root.y);
        setGroup(root.group);
        setAgg(root.agg);
        setTimeGrain(root.timeGrain);
      }
      setHistory([]);
      setFilters([]);
      setBrushedRange(null);
      return;
    }
    const target = history[index];
    if (!target) return;
    setHistory((h) => h.slice(0, index));
    setMode(target.mode);
    setX(target.x);
    setY(target.y);
    setGroup(target.group);
    setAgg(target.agg);
    setTimeGrain(target.timeGrain);
    setFilters(target.filters);
    setBrushedRange(null);
  };

  const handleDrillTarget = (t: DrillTarget) => {
    if (!res) return;

    // 1. Temporal drill-down: e.g. year -> quarter -> month -> week -> day
    if (t.period && t.periodEnd && t.column) {
      const nextG = (res.next_grain as TimeGrain | null) ?? null;
      pushState(`${t.column}: ${t.period}`);
      setFilters((prev) => [
        ...prev,
        {
          column: t.column!,
          op: "date_range",
          low: t.period!,
          high: t.periodEnd!,
          label: `${t.column} in ${t.period}`,
        },
      ]);
      if (nextG) {
        setMode("time");
        setTimeGrain(nextG);
      } else if (drillNextCol) {
        setMode("group");
        setX(drillNextCol);
      }
      return;
    }

    // 2. Numeric bin / range drill-down
    if (typeof t.low === "number" && typeof t.high === "number") {
      const col = t.column ?? x;
      if (!col) return;
      const lbl = `${col} [${t.low.toPrecision(3)}, ${t.high.toPrecision(3)}]`;
      pushState(lbl);
      setFilters((prev) => [
        ...prev,
        { column: col, op: "range", low: t.low, high: t.high, label: lbl },
      ]);
      return;
    }

    // 3. Categorical / Matrix cell drill-down
    if (t.column && t.value !== undefined) {
      const newFilters: DrillFilter[] = [
        ...filters,
        { column: t.column, op: "eq", value: t.value, label: `${t.column} = ${t.value}` },
      ];
      if (t.extraColumn && t.extraValue !== undefined) {
        newFilters.push({
          column: t.extraColumn,
          op: "eq",
          value: t.extraValue,
          label: `${t.extraColumn} = ${t.extraValue}`,
        });
      }
      const stepLabel = t.extraColumn
        ? `${t.column}=${t.value}, ${t.extraColumn}=${t.extraValue}`
        : `${t.column} = ${t.value}`;
      pushState(stepLabel);
      setFilters(newFilters);

      const candidateNext =
        drillNextCol && drillNextCol !== t.column && drillNextCol !== t.extraColumn
          ? drillNextCol
          : res.next_dimensions.find((d) => d !== t.column && d !== t.extraColumn);
      if (candidateNext) {
        const nextColInfo = usable.find((c) => c.name === candidateNext);
        setX(candidateNext);
        if (nextColInfo?.role === "datetime") {
          setMode("time");
        } else if (mode === "heatmap") {
          setMode("group");
        }
      }
    }
  };

  const drillIntoBrush = () => {
    if (!brushedRange || !x || !y) return;
    const lbl = `Cluster (${brushedRange.count} pts)`;
    pushState(lbl);
    setFilters((prev) => [
      ...prev,
      {
        column: x,
        op: "range",
        low: brushedRange.xMin,
        high: brushedRange.xMax,
        label: `${x} [${brushedRange.xMin.toPrecision(3)}, ${brushedRange.xMax.toPrecision(3)}]`,
      },
      {
        column: y,
        op: "range",
        low: brushedRange.yMin,
        high: brushedRange.yMax,
        label: `${y} [${brushedRange.yMin.toPrecision(3)}, ${brushedRange.yMax.toPrecision(3)}]`,
      },
    ]);
    setBrushActive(false);
    setBrushedRange(null);
  };

  const adapted = useMemo(
    () => (res ? buildExploreOption(res, tokens, visualStyle) : null),
    [res, tokens, visualStyle],
  );

  const exportPng = () => {
    const inst = chartInst.current;
    if (!inst) return;
    const url = inst.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: tokens.isDark ? "#0F172A" : "#FFFFFF",
    });
    const a = document.createElement("a");
    a.href = url;
    a.download = `${dataset.name}-explore.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const canDrillUp = history.length > 0 || filters.length > 0 || Boolean(res?.mode === "time" && res?.prev_grain);

  return (
    <div className="explore-studio stack">
      {/* Mode & Controls Strip */}
      <div className="explore-controls card-surface">
        {!compactHeader ? (
          <div className="mode-pills" role="tablist" aria-label="Chart mode">
            {MODE_OPTIONS.map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.id}
                  type="button"
                  role="tab"
                  aria-selected={mode === m.id}
                  className={`mode-pill${mode === m.id ? " active" : ""}`}
                  onClick={() => {
                    setMode(m.id);
                    if (m.id === "time" && dateCols[0] && usable.find((c) => c.name === x)?.role !== "datetime") {
                      setX(dateCols[0].name);
                    } else if (m.id === "scatter") {
                      if (numericCols[0] && usable.find((c) => c.name === x)?.role !== "numeric") setX(numericCols[0].name);
                      if (numericCols[1] && (!y || usable.find((c) => c.name === y)?.role !== "numeric")) {
                        setY(numericCols.find((c) => c.name !== x)?.name ?? numericCols[0].name);
                      }
                    } else if (m.id === "histogram" && numericCols[0] && usable.find((c) => c.name === x)?.role !== "numeric") {
                      setX(numericCols[0].name);
                    } else if (m.id === "hierarchy") {
                      if (!catCols.some((c) => c.name === x) && catCols[0]) setX(catCols[0].name);
                      if (!group && catCols[1]) setGroup(catCols[1].name);
                      if (!thirdDim && catCols[2]) setThirdDim(catCols[2].name);
                      setVisualStyle("sunburst");
                    } else if (m.id === "boxplot") {
                      setVisualStyle("boxplot");
                    }
                  }}
                >
                  <Icon size={14} />
                  <span>{m.label}</span>
                </button>
              );
            })}
          </div>
        ) : null}

        <div className="explore-fields">
          <label className="field">
            <span>{mode === "hierarchy" ? "Level 1" : mode === "scatter" || mode === "histogram" ? "X Axis" : "Dimension (X)"}</span>
            <select value={x} onChange={(e) => setX(e.target.value)} aria-label="Primary X column">
              {usable.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} ({ROLE_LABEL[c.role] ?? c.role})
                </option>
              ))}
            </select>
          </label>

          {mode !== "histogram" ? (
            <label className="field">
              <span>{mode === "scatter" ? "Y Axis" : mode === "heatmap" ? "Row Category (Y)" : "Metric (Y)"}</span>
              <select value={y} onChange={(e) => setY(e.target.value)} aria-label="Metric Y column">
                {mode !== "scatter" && mode !== "heatmap" ? <option value="">Row Count</option> : null}
                {(mode === "scatter" ? numericCols : mode === "heatmap" ? catCols : usable).map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({ROLE_LABEL[c.role] ?? c.role})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="field">
              <span>Bins ({bins})</span>
              <input
                type="range"
                min={8}
                max={60}
                value={bins}
                onChange={(e) => setBins(Number(e.target.value))}
                style={{ height: 34 }}
              />
            </label>
          )}

          {mode !== "scatter" && mode !== "histogram" ? (
            <label className="field">
              <span>Statistic</span>
              <select value={agg} onChange={(e) => setAgg(e.target.value as AggKind)} aria-label="Statistic aggregation">
                <option value="mean">Mean (+ 95% CI)</option>
                <option value="median">Median</option>
                <option value="sum">Sum</option>
                <option value="count">Count</option>
                <option value="share">Share (%)</option>
              </select>
            </label>
          ) : null}

          <label className="field">
            <span>{mode === "hierarchy" ? "Level 2" : mode === "heatmap" ? "Cell Metric (optional)" : "Split / Color by"}</span>
            <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Group or color column">
              <option value="">— none —</option>
              {(mode === "heatmap" ? numericCols : catCols).map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          {mode === "hierarchy" ? (
            <label className="field">
              <span>Level 3</span>
              <select value={thirdDim} onChange={(e) => setThirdDim(e.target.value)} aria-label="Hierarchy level 3">
                <option value="">— optional —</option>
                {catCols.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (res?.mode === "group" || res?.mode === "boxplot" || res?.mode === "time") && res.next_dimensions.length > 0 ? (
            <label className="field">
              <span>Drill-down target</span>
              <select
                value={drillNextCol}
                onChange={(e) => setDrillNextCol(e.target.value)}
                aria-label="Next drill-down dimension"
              >
                {res.next_dimensions.map((dName) => (
                  <option key={dName} value={dName}>
                    → {dName}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {(mode === "time" || res?.mode === "time") ? (
            <label className="field">
              <span>Time Grain</span>
              <select value={timeGrain} onChange={(e) => setTimeGrain(e.target.value as TimeGrain)} aria-label="Time grain">
                {GRAINS.map((g) => (
                  <option key={g} value={g}>
                    {g === "auto" ? `Auto (${res?.grain_used ?? "smart"})` : g[0].toUpperCase() + g.slice(1)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </div>

      {/* Sticky Drill-Down / Breadcrumb Bar */}
      <div className="drill-bar">
        <div className="drill-crumbs" aria-label="Drill-down path">
          <button
            type="button"
            className="btn btn-sm drill-up-btn"
            disabled={!canDrillUp}
            onClick={drillUp}
            title="Step up one drill level"
          >
            <ArrowUpLeft size={14} />
            <span>Drill Up</span>
          </button>

          <button
            type="button"
            className={`crumb-chip${filters.length === 0 ? " current" : ""}`}
            onClick={() => jumpToHistory(-1)}
          >
            All ({fmtInt(res?.total_rows ?? dataset.n_rows)})
          </button>

          {filters.map((f, idx) => (
            <span key={idx} className="crumb-item">
              <ChevronRight size={13} className="faint" />
              <span className="crumb-chip active">
                {f.label ?? `${f.column} = ${String(f.value ?? "")}`}
                <button
                  type="button"
                  className="crumb-remove"
                  aria-label="Remove filter"
                  onClick={() => setFilters((cur) => cur.filter((_, j) => j !== idx))}
                >
                  ×
                </button>
              </span>
            </span>
          ))}

          {filters.length > 0 ? (
            <button
              type="button"
              className="link-btn small"
              style={{ marginLeft: 6 }}
              onClick={() => jumpToHistory(-1)}
            >
              <FilterX size={13} style={{ verticalAlign: "-2px" }} /> Reset
            </button>
          ) : null}
        </div>

        <div className="row-wrap" style={{ gap: 8 }}>
          {res ? (
            <Badge tone={res.matched_rows < res.total_rows ? "brand" : "outline"}>
              {fmtInt(res.matched_rows)} rows ({fmtPct(res.matched_rows / Math.max(res.total_rows, 1), 0)})
            </Badge>
          ) : null}

          {res?.mode === "group" || res?.mode === "boxplot" ? (
            <SpringSegmented<ExploreVisualStyle>
              size="xs"
              role="group"
              ariaLabel="Visual style"
              value={visualStyle === "lollipop" || visualStyle === "boxplot" ? visualStyle : "bar"}
              onChange={setVisualStyle}
              items={[
                { id: "bar", label: "Bars" },
                { id: "lollipop", label: "Lollipop" },
                ...(Boolean(res.data.has_box) ? [{ id: "boxplot" as const, label: "Boxplot" }] : []),
              ]}
            />
          ) : null}

          {res?.mode === "hierarchy" ? (
            <SpringSegmented<ExploreVisualStyle>
              size="xs"
              role="group"
              ariaLabel="Hierarchy style"
              value={visualStyle === "treemap" ? "treemap" : "sunburst"}
              onChange={setVisualStyle}
              items={[
                { id: "sunburst", label: "Sunburst" },
                { id: "treemap", label: "Treemap" },
              ]}
            />
          ) : null}

          {res?.mode === "time" ? (
            <SpringSegmented<ExploreVisualStyle>
              size="xs"
              role="group"
              ariaLabel="Time chart style"
              value={visualStyle === "bar" || visualStyle === "line" ? visualStyle : "area"}
              onChange={setVisualStyle}
              items={[
                { id: "area", label: "Area" },
                { id: "line", label: "Line" },
                { id: "bar", label: "Bars" },
              ]}
            />
          ) : null}

          {adapted?.canBrush ? (
            <button
              type="button"
              className={`btn btn-sm${brushActive ? " btn-primary" : ""}`}
              onClick={() => {
                setBrushActive((b) => !b);
                setBrushedRange(null);
              }}
            >
              <Crosshair size={13} /> Brush
            </button>
          ) : null}

          <button type="button" className="btn btn-sm" onClick={exportPng} title="Download PNG">
            <Download size={13} /> PNG
          </button>
        </div>
      </div>

      {error ? <ErrorBox error={error} onRetry={fetchExplore} /> : null}

      {brushedRange ? (
        <div className="brush-banner">
          <div className="row-wrap" style={{ gap: 12 }}>
            <Badge tone="brand">{brushedRange.count.toLocaleString()} brushed points</Badge>
            <span className="mono small">
              {x}: [{brushedRange.xMin.toPrecision(3)}, {brushedRange.xMax.toPrecision(3)}]
            </span>
            <span className="mono small">
              {y}: [{brushedRange.yMin.toPrecision(3)}, {brushedRange.yMax.toPrecision(3)}]
            </span>
            {brushedRange.r !== null ? (
              <span className="mono small">
                r = <b>{brushedRange.r >= 0 ? "+" : ""}{brushedRange.r.toFixed(3)}</b>
              </span>
            ) : null}
          </div>
          <button type="button" className="btn btn-sm btn-primary" onClick={drillIntoBrush}>
            Filter &amp; Drill into Cluster →
          </button>
        </div>
      ) : null}

      {/* Main Fluid Chart Canvas */}
      <div className="explore-canvas-card">
        <div className="spread" style={{ marginBottom: 6 }}>
          <div>
            <h3 style={{ margin: 0 }}>{res?.title ?? "Interactive Visual Explorer"}</h3>
            <div className="small muted">{res?.subtitle ?? "Select columns above to explore"}</div>
          </div>
          {loading ? <Spinner label="Updating…" /> : null}
        </div>

        {adapted ? (
          <EChartsSurface
            adapted={adapted}
            height={380}
            brushActive={brushActive}
            resetTick={resetTick}
            chartRef={chartInst}
            onBrushStats={(st) =>
              setBrushedRange(
                st
                  ? {
                      count: st.count,
                      xMin: st.xMin,
                      xMax: st.xMax,
                      yMin: st.yMin,
                      yMax: st.yMax,
                      r: st.r,
                    }
                  : null,
              )
            }
            onDrillTarget={handleDrillTarget}
          />
        ) : !loading ? (
          <div className="empty">Select a column to visualize.</div>
        ) : (
          <div style={{ height: 380, display: "grid", placeItems: "center" }}>
            <Spinner large label="Computing view…" />
          </div>
        )}

        {/* Quick Next-Dimension Chips + Underlying Rows Toggle */}
        {res ? (
          <div className="explore-footer spread">
            <div className="row-wrap" style={{ gap: 6 }}>
              {res.next_dimensions.length > 0 ? (
                <>
                  <span className="tiny muted">Switch X to:</span>
                  {res.next_dimensions.slice(0, 5).map((dim) => (
                    <button
                      key={dim}
                      type="button"
                      className="chip"
                      onClick={() => {
                        pushState(`View by ${dim}`);
                        setX(dim);
                        setResetTick((t) => t + 1);
                      }}
                    >
                      {dim}
                    </button>
                  ))}
                </>
              ) : null}
            </div>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setShowSample((s) => !s)}
            >
              <Table2 size={13} />
              <span>{showSample ? "Hide" : "Inspect"} slice rows ({fmtInt(res.matched_rows)})</span>
            </button>
          </div>
        ) : null}
      </div>

      {/* Live Underlying Slice Records */}
      {showSample && res && res.sample_columns.length > 0 ? (
        <div className="card">
          <div className="card-head">
            <h4>
              Underlying records in current slice (showing {res.sample_rows.length} of {fmtInt(res.matched_rows)})
            </h4>
          </div>
          <div className="table-wrap" style={{ maxHeight: 260, border: "none" }}>
            <table className="data">
              <thead>
                <tr>
                  {res.sample_columns.map((col) => (
                    <th key={col}>{col === "__row__" ? "#" : col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {res.sample_rows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((val, cIdx) => (
                      <td key={cIdx} className={res.sample_columns[cIdx] === "__row__" ? "rownum num" : ""}>
                        {val === null || val === undefined ? <span className="null">missing</span> : fmtCell(val)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
