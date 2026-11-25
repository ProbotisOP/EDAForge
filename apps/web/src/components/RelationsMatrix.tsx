import { useEffect, useMemo, useRef, useState } from "react";
import type { AdaptedChart } from "../lib/muiChartsAdapter";
import { useTheme } from "../lib/theme";
import type { Universe, UniverseEdge } from "../lib/types";
import { MuiChartSurface } from "./Chart";
import { signOf, type Lens, type SignFilter, visible } from "./Universe";

const ROLE_PALETTE_DARK: Record<string, string> = {
  numeric: "#4CC9F0",
  categorical: "#5EEAD4",
  boolean: "#34D399",
  datetime: "#FBBF24",
  source: "#93C5FD",
  other: "#A2B3BC",
};

const ROLE_PALETTE_LIGHT: Record<string, string> = {
  numeric: "#155861",
  categorical: "#2B59C3",
  boolean: "#0D6E66",
  datetime: "#B45309",
  source: "#19383D",
  other: "#566670",
};

function edgeHex(e: UniverseEdge, isDark: boolean): string {
  const s = signOf(e);
  if (s === "formula") return isDark ? "#FBBF24" : "#B45309";
  if (s === "up") return isDark ? "#4CC9F0" : "#155861";
  if (s === "down") return isDark ? "#FB7185" : "#C84B31";
  return isDark ? "#34D399" : "#0D6E66";
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
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 860, h: 520 });
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      if (r.width > 40 && r.height > 40) {
        setSize({ w: Math.round(r.width), h: Math.round(r.height) });
      }
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const shownEdges = useMemo(
    () => universe.edges.filter((e) => visible(e, lens, signs)),
    [universe.edges, lens, signs],
  );

  const cleanEdges = useMemo(() => {
    const bestByPair = new Map<string, UniverseEdge>();
    for (const e of shownEdges) {
      const key = [e.source, e.target].sort().join("::") + "::" + e.kind;
      const prev = bestByPair.get(key);
      if (!prev || e.score > prev.score) bestByPair.set(key, e);
    }
    return [...bestByPair.values()];
  }, [shownEdges]);

  const positions = useMemo(() => {
    const nodes = universe.nodes;
    const n = nodes.length || 1;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const rad = Math.max(90, Math.min(size.w, size.h) * 0.36);

    const pts = nodes.map((nd, idx) => {
      const angle = (2 * Math.PI * idx) / n - Math.PI / 2;
      return {
        id: nd.id,
        x: cx + rad * Math.cos(angle),
        y: cy + rad * Math.sin(angle),
        vx: 0,
        vy: 0,
      };
    });

    if (layoutMode === "circular" || nodes.length <= 2) {
      return new Map(pts.map((p) => [p.id, { x: p.x, y: p.y }]));
    }

    const idxMap = new Map(pts.map((p, i) => [p.id, i]));
    const kIdeal = Math.sqrt((size.w * size.h) / Math.max(n, 2)) * 0.58;

    for (let iter = 0; iter < 80; iter++) {
      const temp = (1 - iter / 80) * 18;
      for (const p of pts) {
        p.vx = 0;
        p.vy = 0;
      }
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x;
          const dy = pts[i].y - pts[j].y;
          const dist = Math.max(8, Math.hypot(dx, dy));
          const rep = (kIdeal * kIdeal) / dist;
          const fx = (dx / dist) * rep;
          const fy = (dy / dist) * rep;
          pts[i].vx += fx;
          pts[i].vy += fy;
          pts[j].vx -= fx;
          pts[j].vy -= fy;
        }
      }
      for (const e of cleanEdges) {
        const ia = idxMap.get(e.source);
        const ib = idxMap.get(e.target);
        if (ia === undefined || ib === undefined) continue;
        const dx = pts[ia].x - pts[ib].x;
        const dy = pts[ia].y - pts[ib].y;
        const dist = Math.max(8, Math.hypot(dx, dy));
        const att = ((dist * dist) / kIdeal) * (0.45 + e.strength * 0.4);
        const fx = (dx / dist) * att;
        const fy = (dy / dist) * att;
        pts[ia].vx -= fx;
        pts[ia].vy -= fy;
        pts[ib].vx += fx;
        pts[ib].vy += fy;
      }
      for (const p of pts) {
        p.vx += (cx - p.x) * 0.06;
        p.vy += (cy - p.y) * 0.06;
        const mag = Math.hypot(p.vx, p.vy) || 1;
        p.x += (p.vx / mag) * Math.min(mag, temp);
        p.y += (p.vy / mag) * Math.min(mag, temp);
        p.x = Math.max(76, Math.min(size.w - 110, p.x));
        p.y = Math.max(46, Math.min(size.h - 46, p.y));
      }
    }

    return new Map(pts.map((p) => [p.id, { x: p.x, y: p.y }]));
  }, [universe.nodes, cleanEdges, layoutMode, size]);

  const connectedSet = useMemo(() => {
    const set = new Set<string>();
    if (!selectedNode) return set;
    set.add(selectedNode);
    for (const e of shownEdges) {
      if (e.source === selectedNode) set.add(e.target);
      if (e.target === selectedNode) set.add(e.source);
      if (e.via === selectedNode) {
        set.add(e.source);
        set.add(e.target);
      }
    }
    return set;
  }, [selectedNode, shownEdges]);

  const roleColors = tokens.isDark ? ROLE_PALETTE_DARK : ROLE_PALETTE_LIGHT;
  const pairSeen = new Map<string, number>();

  return (
    <div
      ref={hostRef}
      className="relations-surface"
      data-testid="universe-canvas"
      style={{ position: "relative" }}
      onClick={() => {
        onSelectNode(null);
        onSelectEdge(null);
      }}
    >
      <svg
        width={size.w}
        height={size.h}
        viewBox={`0 0 ${size.w} ${size.h}`}
        style={{ width: "100%", height: "100%", display: "block" }}
      >
        {cleanEdges.map((e) => {
          const p0 = positions.get(e.source);
          const p1 = positions.get(e.target);
          if (!p0 || !p1) return null;
          const pk = [e.source, e.target].sort().join("::");
          const kIdx = pairSeen.get(pk) ?? 0;
          pairSeen.set(pk, kIdx + 1);

          const mx = (p0.x + p1.x) / 2;
          const my = (p0.y + p1.y) / 2;
          const dx = p1.x - p0.x;
          const dy = p1.y - p0.y;
          const len = Math.hypot(dx, dy) || 1;
          const bend = (kIdx === 0 ? 0.1 : 0.24 * (kIdx % 2 === 1 ? 1 : -1)) * len;
          const qx = mx - (dy / len) * bend;
          const qy = my + (dx / len) * bend;

          const isSel = e.id === selectedEdge;
          const touchesSel =
            !selectedNode ||
            e.source === selectedNode ||
            e.target === selectedNode ||
            e.via === selectedNode;

          return (
            <path
              key={e.id}
              d={`M ${p0.x} ${p0.y} Q ${qx} ${qy} ${p1.x} ${p1.y}`}
              fill="none"
              stroke={edgeHex(e, tokens.isDark)}
              strokeWidth={isSel ? 4 : 1.5 + e.strength * 2.6}
              strokeDasharray={e.confirmed ? undefined : "5 4"}
              strokeOpacity={isSel ? 1 : touchesSel ? 0.84 : 0.12}
              style={{ cursor: "pointer" }}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelectEdge(e.id);
              }}
              onMouseEnter={(ev) => {
                const box = hostRef.current?.getBoundingClientRect();
                if (!box) return;
                setTip({
                  x: ev.clientX - box.left,
                  y: ev.clientY - box.top,
                  lines: [
                    e.headline,
                    ...(e.effect_text ? [e.effect_text] : []),
                    `${e.grade ? `Grade ${e.grade}` : "Exact formula"} · Click to inspect`,
                  ],
                });
              }}
              onMouseLeave={() => setTip(null)}
            />
          );
        })}

        {universe.nodes.map((n) => {
          const pos = positions.get(n.id);
          if (!pos) return null;
          const dimmed = Boolean(selectedNode && !connectedSet.has(n.id));
          const isSel = n.id === selectedNode;
          const r = n.is_target ? 16 : Math.min(14, 7 + n.degree * 1.1);
          const fill = n.is_target
            ? tokens.warning
            : (roleColors[n.role] ?? roleColors.other);

          return (
            <g
              key={n.id}
              transform={`translate(${pos.x}, ${pos.y})`}
              style={{ cursor: "pointer", opacity: dimmed ? 0.25 : 1 }}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelectNode(n.id);
              }}
              onMouseEnter={(ev) => {
                const box = hostRef.current?.getBoundingClientRect();
                if (!box) return;
                setTip({
                  x: ev.clientX - box.left,
                  y: ev.clientY - box.top,
                  lines: [
                    `${n.id} (${n.role})`,
                    `${n.degree} relationships${n.alerts.length ? ` · ${n.alerts.length} alert(s)` : ""}`,
                    "Click to focus connections",
                  ],
                });
              }}
              onMouseLeave={() => setTip(null)}
            >
              <circle
                r={r}
                fill={fill}
                stroke={
                  isSel
                    ? tokens.text
                    : n.alerts.length
                      ? tokens.negative
                      : tokens.tooltipBg
                }
                strokeWidth={isSel ? 3 : 2}
              />
              <text
                x={r + 6}
                y={4}
                fill={tokens.text}
                fontSize={12}
                fontWeight={n.is_target || isSel ? 700 : 500}
                fontFamily="var(--sans)"
              >
                {n.derived ? `ƒ ${n.id}` : n.id}
              </text>
            </g>
          );
        })}
      </svg>

      {tip ? (
        <div
          className="mui-bento-float-tip"
          style={{ left: Math.max(8, tip.x + 14), top: Math.max(8, tip.y - 12) }}
        >
          {tip.lines.map((line, i) => (
            <div key={i} className={i === 0 ? "tip-head" : "tip-row"}>
              {line}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function AssociationMatrixView({
  universe,
  lens,
  signs,
  selectedEdge,
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
  const [height, setHeight] = useState(480);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      if (r.height > 120) setHeight(Math.round(r.height));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const adapted = useMemo<AdaptedChart>(() => {
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

    const cells = [];
    for (let yi = 0; yi < cols.length; yi++) {
      for (let xi = 0; xi < cols.length; xi++) {
        if (xi === yi) continue;
        const e = edgeLookup.get(`${xi}:${yi}`);
        if (!e) continue;
        const signedVal =
          e.estimate !== null
            ? Math.max(-1, Math.min(1, e.estimate))
            : (e.sign === -1 ? -1 : 1) * Math.max(0.25, e.strength);
        cells.push({
          xi,
          yi,
          value: Number(signedVal.toFixed(3)),
          badge: e.grade ?? "ƒ",
          selected: e.id === selectedEdge,
          tooltipLines: [
            e.headline,
            ...(e.effect_text ? [e.effect_text] : []),
            `${e.grade ? `Grade ${e.grade}` : "Formula"} · Click cell to inspect`,
          ],
          drill: { column: "__edge__", value: e.id },
        });
      }
    }

    return {
      drillColumn: "__edge__",
      model: {
        kind: "heatmap",
        xCategories: cols,
        yCategories: cols,
        min: -1,
        max: 1,
        ramp: tokens.divergingRamp,
        diverging: true,
        cells,
      },
    };
  }, [universe.nodes, universe.edges, lens, signs, tokens.divergingRamp, selectedEdge]);

  return (
    <div ref={hostRef} className="relations-surface" data-testid="universe-canvas">
      <MuiChartSurface
        adapted={adapted}
        height={height}
        onDrillTarget={(t) => {
          if (t.column === "__edge__" && t.value) onSelectEdge(t.value);
        }}
      />
    </div>
  );
}
