import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { useTheme } from "../lib/theme";
import type { Universe, UniverseEdge } from "../lib/types";
import { signOf, type Lens, type SignFilter, visible } from "./Universe";

const ROLE_PALETTE_DARK: Record<string, string> = {
  numeric: "#38BDF8",
  categorical: "#A78BFA",
  boolean: "#2DD4BF",
  datetime: "#F59E0B",
  source: "#10B981",
  other: "#94A3B8",
};

const ROLE_PALETTE_LIGHT: Record<string, string> = {
  numeric: "#0284C7",
  categorical: "#7C3AED",
  boolean: "#0D9488",
  datetime: "#D97706",
  source: "#059669",
  other: "#64748B",
};

function edgeHex(e: UniverseEdge, isDark: boolean): string {
  const s = signOf(e);
  if (s === "formula") return isDark ? "#FBBF24" : "#D97706";
  if (s === "up") return isDark ? "#22D3EE" : "#0284C7";
  if (s === "down") return isDark ? "#FB7185" : "#E11D48";
  return isDark ? "#A78BFA" : "#7C3AED";
}

export function NetworkGraph2D({
  universe,
  lens,
  signs,
  layoutMode,
  selectedNode,
  selectedEdge,
  onSelectNode,
  onSelectEdge,
}: {
  universe: Universe;
  lens: Lens;
  signs: SignFilter[];
  layoutMode: "force" | "circular";
  selectedNode: string | null;
  selectedEdge: string | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
}) {
  const { tokens } = useTheme();
  const hostRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<echarts.ECharts | null>(null);
  const handlers = useRef({ onSelectNode, onSelectEdge });
  handlers.current = { onSelectNode, onSelectEdge };

  const shownEdges = useMemo(
    () => universe.edges.filter((e) => visible(e, lens, signs)),
    [universe.edges, lens, signs],
  );

  const option = useMemo<echarts.EChartsOption>(() => {
    const roleColors = tokens.isDark ? ROLE_PALETTE_DARK : ROLE_PALETTE_LIGHT;
    const connectedSet = new Set<string>();
    if (selectedNode) {
      connectedSet.add(selectedNode);
      for (const e of shownEdges) {
        if (e.source === selectedNode) connectedSet.add(e.target);
        if (e.target === selectedNode) connectedSet.add(e.source);
        if (e.via === selectedNode) {
          connectedSet.add(e.source);
          connectedSet.add(e.target);
        }
      }
    }

    // Deduplicate multi-edges between same pair by keeping strongest edge for clean visual layout
    const bestByPair = new Map<string, UniverseEdge>();
    for (const e of shownEdges) {
      const key = [e.source, e.target].sort().join("::") + "::" + e.kind;
      const prev = bestByPair.get(key);
      if (!prev || e.score > prev.score) bestByPair.set(key, e);
    }
    const cleanEdges = [...bestByPair.values()];

    const nodes = universe.nodes.map((n) => {
      const dimmed = Boolean(selectedNode && !connectedSet.has(n.id));
      const isSel = n.id === selectedNode;
      const size = n.is_target ? 38 : Math.min(32, 14 + n.degree * 2.2);
      const baseColor = n.is_target ? "#F59E0B" : (roleColors[n.role] ?? roleColors.other);

      return {
        id: n.id,
        name: n.derived ? `ƒ ${n.id}` : n.id,
        symbolSize: size,
        value: n.degree,
        itemStyle: {
          color: baseColor,
          opacity: dimmed ? 0.22 : 1,
          borderColor: isSel ? tokens.text : n.alerts.length ? "#EF4444" : tokens.isDark ? "#17191D" : "#FFFFFF",
          borderWidth: isSel ? 3 : n.alerts.length ? 2.2 : 1.5,
          shadowBlur: 0,
        },
        label: {
          show: true,
          position: "right" as const,
          color: dimmed ? tokens.subtext : tokens.text,
          fontSize: n.is_target || isSel ? 12.5 : 11.5,
          fontWeight: n.is_target || isSel ? ("bold" as const) : ("normal" as const),
          formatter: () => (n.derived ? `ƒ ${n.id}` : n.id),
        },
      };
    });

    // Pairwise curvature when two edges connect the same nodes
    const pairCount = new Map<string, number>();
    const links = cleanEdges.map((e) => {
      const pk = [e.source, e.target].sort().join("::");
      const idx = pairCount.get(pk) ?? 0;
      pairCount.set(pk, idx + 1);
      const isSel = e.id === selectedEdge;
      const touchesSel = !selectedNode || e.source === selectedNode || e.target === selectedNode || e.via === selectedNode;
      return {
        source: e.source,
        target: e.target,
        edgeId: e.id,
        headline: e.headline,
        effectText: e.effect_text,
        grade: e.grade,
        lineStyle: {
          color: edgeHex(e, tokens.isDark),
          width: isSel ? 4 : 1.4 + e.strength * 2.8,
          type: e.confirmed ? ("solid" as const) : ("dashed" as const),
          opacity: isSel ? 1 : touchesSel ? 0.82 : 0.1,
          curveness: idx === 0 ? 0.08 : 0.24 * (idx % 2 === 1 ? 1 : -1),
        },
      };
    });

    return {
      animationDurationUpdate: 380,
      tooltip: {
        backgroundColor: tokens.tooltipBg,
        borderColor: tokens.tooltipBorder,
        borderWidth: 1,
        textStyle: { color: tokens.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          const p = params as { dataType?: string; data?: Record<string, unknown> };
          if (p.dataType === "edge" && p.data) {
            return [
              `<div style="font-weight:600;max-width:260px;white-space:normal">${String(p.data.headline ?? "")}</div>`,
              p.data.effectText ? `<div style="margin-top:3px">${String(p.data.effectText)}</div>` : "",
              `<div style="opacity:.75;margin-top:2px">${p.data.grade ? `Grade ${p.data.grade}` : "Exact formula"} · Click to inspect</div>`,
            ].join("");
          }
          if (p.dataType === "node" && p.data) {
            const nodeObj = universe.nodes.find((x) => x.id === p.data?.id);
            if (!nodeObj) return "";
            return [
              `<div style="font-weight:600">${nodeObj.id} (${nodeObj.role})</div>`,
              `<div style="opacity:.8">${nodeObj.degree} relationships${nodeObj.alerts.length ? ` · ${nodeObj.alerts.length} quality alert(s)` : ""}</div>`,
              `<div style="opacity:.65;margin-top:2px">Click to focus connections</div>`,
            ].join("");
          }
          return "";
        },
      },
      series: [
        {
          type: "graph",
          layout: layoutMode,
          roam: true,
          draggable: true,
          emphasis: {
            focus: "adjacency",
            lineStyle: { width: 3.6 },
          },
          force: {
            repulsion: 460,
            edgeLength: [95, 195],
            gravity: 0.08,
            layoutAnimation: true,
          },
          circular: { rotateLabel: false },
          data: nodes,
          links,
        },
      ],
    };
  }, [universe.nodes, shownEdges, tokens, layoutMode, selectedNode, selectedEdge]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const inst = echarts.init(el, undefined, { renderer: "canvas" });
    instRef.current = inst;

    inst.on("click", (params: unknown) => {
      const p = params as { dataType?: string; data?: { id?: string; edgeId?: string } };
      if (p.dataType === "node" && p.data?.id) {
        handlers.current.onSelectNode(p.data.id);
      } else if (p.dataType === "edge" && p.data?.edgeId) {
        handlers.current.onSelectEdge(p.data.edgeId);
      }
    });

    inst.getZr().on("click", (ev: { target?: unknown }) => {
      if (!ev.target) {
        handlers.current.onSelectNode(null);
        handlers.current.onSelectEdge(null);
      }
    });

    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      inst.dispose();
      instRef.current = null;
    };
  }, []);

  useEffect(() => {
    instRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={hostRef} className="relations-surface" data-testid="universe-canvas" />;
}

export function AssociationMatrixView({
  universe,
  lens,
  signs,
  selectedEdge,
  onSelectNode,
  onSelectEdge,
}: {
  universe: Universe;
  lens: Lens;
  signs: SignFilter[];
  selectedEdge: string | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
}) {
  const { tokens } = useTheme();
  const hostRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<echarts.ECharts | null>(null);
  const handlers = useRef({ onSelectNode, onSelectEdge });
  handlers.current = { onSelectNode, onSelectEdge };

  const { orderedCols, cells, cellEdgeMap } = useMemo(() => {
    const shown = universe.edges.filter((e) => visible(e, lens, signs));
    const activeNodes = [...universe.nodes].sort((a, b) => {
      if (a.is_target !== b.is_target) return a.is_target ? -1 : 1;
      return b.degree - a.degree || a.id.localeCompare(b.id);
    });
    const cols = activeNodes.map((n) => n.id);
    const idxMap = new Map(cols.map((c, i) => [c, i]));
    const edgeLookup = new Map<string, UniverseEdge>();

    for (const e of shown) {
      const i = idxMap.get(e.source);
      const j = idxMap.get(e.target);
      if (i === undefined || j === undefined) continue;
      for (const [r, c] of [
        [i, j],
        [j, i],
      ]) {
        const k = `${r}:${c}`;
        const prev = edgeLookup.get(k);
        if (!prev || e.score > prev.score) edgeLookup.set(k, e);
      }
    }

    const matrixCells: [number, number, number, string, string][] = [];
    for (let i = 0; i < cols.length; i++) {
      for (let j = 0; j < cols.length; j++) {
        if (i === j) continue;
        const e = edgeLookup.get(`${i}:${j}`);
        if (!e) continue;
        const signedVal =
          e.estimate !== null
            ? Math.max(-1, Math.min(1, e.estimate))
            : (e.sign === -1 ? -1 : 1) * Math.max(0.25, e.strength);
        matrixCells.push([i, j, Number(signedVal.toFixed(3)), e.grade ?? "ƒ", e.id]);
      }
    }

    return { orderedCols: cols, cells: matrixCells, cellEdgeMap: edgeLookup };
  }, [universe.nodes, universe.edges, lens, signs]);

  const option = useMemo<echarts.EChartsOption>(
    () => ({
      animationDuration: 320,
      tooltip: {
        backgroundColor: tokens.tooltipBg,
        borderColor: tokens.tooltipBorder,
        borderWidth: 1,
        textStyle: { color: tokens.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          const val = (params as { value?: [number, number, number, string, string] })?.value;
          if (!val) return "";
          const edge = cellEdgeMap.get(`${val[0]}:${val[1]}`);
          if (!edge) return "";
          return [
            `<div style="font-weight:600;max-width:260px;white-space:normal">${edge.headline}</div>`,
            edge.effect_text ? `<div style="margin-top:3px">${edge.effect_text}</div>` : "",
            `<div style="opacity:.75;margin-top:2px">${edge.grade ? `Grade ${edge.grade}` : "Formula"} · Click cell to inspect</div>`,
          ].join("");
        },
      },
      grid: { top: 24, right: 28, bottom: 84, left: 130, containLabel: false },
      xAxis: {
        type: "category",
        data: orderedCols,
        axisLabel: { color: tokens.axisLabel, fontSize: 11, rotate: 38 },
        splitArea: { show: true, areaStyle: { color: ["transparent", tokens.isDark ? "rgba(255,255,255,0.015)" : "rgba(0,0,0,0.015)"] } },
      },
      yAxis: {
        type: "category",
        data: orderedCols,
        axisLabel: { color: tokens.text, fontSize: 11, width: 118, overflow: "truncate" },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: false,
        orient: "horizontal",
        right: 24,
        bottom: 10,
        itemWidth: 12,
        itemHeight: 120,
        text: ["Positive / Strong", "Negative"],
        textStyle: { color: tokens.subtext, fontSize: 11 },
        inRange: { color: tokens.divergingRamp },
      },
      series: [
        {
          type: "heatmap",
          data: cells.map((c) => ({
            value: c,
            itemStyle:
              c[4] === selectedEdge
                ? { borderColor: tokens.warning, borderWidth: 2.5 }
                : undefined,
          })),
          label: {
            show: orderedCols.length <= 16,
            formatter: (p: unknown) => {
              const v = (p as { value?: [number, number, number, string] })?.value;
              return v ? v[3] : "";
            },
            fontSize: 10,
            fontWeight: "bold",
            color: tokens.text,
          },
          itemStyle: {
            borderColor: tokens.isDark ? "rgba(148, 163, 184, 0.28)" : "#CBD5E1",
            borderWidth: 1.5,
            borderRadius: 3,
          },
        },
      ],
    }),
    [orderedCols, cells, cellEdgeMap, tokens, selectedEdge],
  );

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const inst = echarts.init(el, undefined, { renderer: "canvas" });
    instRef.current = inst;

    inst.on("click", (params: unknown) => {
      const val = (params as { value?: [number, number, number, string, string] })?.value;
      if (val?.[4]) {
        handlers.current.onSelectEdge(val[4]);
      }
    });

    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      inst.dispose();
      instRef.current = null;
    };
  }, []);

  useEffect(() => {
    instRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={hostRef} className="relations-surface" data-testid="universe-canvas" />;
}
