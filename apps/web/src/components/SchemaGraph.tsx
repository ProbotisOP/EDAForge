import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  getSmoothStepPath,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { CheckCircle2, Database, KeyRound, Layers } from "lucide-react";
import { fmtInt } from "../lib/format";
import { useTheme } from "../lib/theme";
import type { Dataset, LinkMeta, LinkSuggestion } from "../lib/types";
import { HealthDot } from "./ui";

interface TableNodeData extends Record<string, unknown> {
  dataset: Dataset;
  keyCols: Set<string>;
  highlighted: boolean;
}

function TableSchemaNode({ data }: NodeProps<Node<TableNodeData>>) {
  const { dataset, keyCols, highlighted } = data;
  const shownCols = useMemo(() => {
    const keys = dataset.columns.filter((c) => keyCols.has(c.name));
    const others = dataset.columns.filter((c) => !keyCols.has(c.name)).slice(0, Math.max(0, 5 - keys.length));
    return [...keys, ...others].slice(0, 6);
  }, [dataset.columns, keyCols]);
  const hiddenCount = Math.max(0, dataset.columns.length - shownCols.length);

  return (
    <div className={`er-node${highlighted ? " active" : ""}`}>
      <Handle type="target" position={Position.Left} className="er-handle" />
      <div className="er-node-head">
        <div className="row" style={{ gap: 7, minWidth: 0 }}>
          {dataset.kind === "combined" ? <Layers size={14} className="er-icon" /> : <Database size={14} className="er-icon" />}
          <HealthDot health={dataset.health} size={8} />
          <span className="er-title" title={dataset.name}>
            {dataset.name}
          </span>
        </div>
        <span className="er-meta">{fmtInt(dataset.n_rows)}r</span>
      </div>
      <div className="er-cols">
        {shownCols.map((col) => {
          const isKey = keyCols.has(col.name);
          return (
            <div key={col.name} className={`er-col${isKey ? " is-key" : ""}`}>
              <span className="row" style={{ gap: 5, minWidth: 0 }}>
                {isKey ? <KeyRound size={11} className="er-key-icon" /> : <span className="er-dot" />}
                <span className="er-col-name">{col.name}</span>
              </span>
              <span className="er-col-type">{col.dtype}</span>
            </div>
          );
        })}
        {hiddenCount > 0 ? <div className="er-more">+{hiddenCount} more columns</div> : null}
      </div>
      <Handle type="source" position={Position.Right} className="er-handle" />
    </div>
  );
}

interface RelEdgeData extends Record<string, unknown> {
  label: string;
  sublabel: string;
  status: "confirmed" | "selected" | "suggested";
  kind: string;
  onSelect?: () => void;
}

function RelationshipEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<Edge<RelEdgeData>>) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 12,
  });

  const st = data?.status ?? "suggested";
  const stroke =
    st === "confirmed" ? "var(--ok)" : st === "selected" ? "var(--brand)" : "var(--faint)";

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke,
          strokeWidth: st === "selected" ? 2.2 : st === "confirmed" ? 2 : 1.5,
          strokeDasharray: st === "suggested" ? "5 4" : undefined,
        }}
      />
      <EdgeLabelRenderer>
        <button
          type="button"
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: "all",
          }}
          className={`er-edge-pill ${st}`}
          onClick={(e) => {
            e.stopPropagation();
            data?.onSelect?.();
          }}
        >
          {st === "confirmed" ? <CheckCircle2 size={11} /> : null}
          <span>{data?.label}</span>
          {data?.sublabel ? <small>{data.sublabel}</small> : null}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

const NODE_TYPES = { tableNode: TableSchemaNode };
const EDGE_TYPES = { relEdge: RelationshipEdge };

export function SchemaGraph({
  datasets,
  suggestions,
  confirmed,
  selectedId,
  activePair,
  onSelectSuggestion,
}: {
  datasets: Dataset[];
  suggestions: LinkSuggestion[];
  confirmed: LinkMeta[];
  selectedId: string | null;
  activePair: [string, string] | null;
  onSelectSuggestion: (s: LinkSuggestion) => void;
}) {
  const { tokens } = useTheme();
  const baseTables = useMemo(() => datasets.filter((d) => d.kind === "file"), [datasets]);

  const { nodes, edges } = useMemo(() => {
    const keyMap = new Map<string, Set<string>>();
    for (const d of baseTables) keyMap.set(d.id, new Set());

    const validSuggestions = suggestions.filter(
      (s) => s.kind !== "unrelated" && s.status !== "rejected" && s.status !== "confirmed",
    );

    for (const s of validSuggestions) {
      for (const k of s.keys) {
        keyMap.get(s.left)?.add(k.left);
        keyMap.get(s.right)?.add(k.right);
      }
    }
    for (const c of confirmed) {
      for (const k of c.spec.keys) {
        keyMap.get(c.spec.left)?.add(k.left);
        keyMap.get(c.spec.right)?.add(k.right);
      }
    }

    const cols = baseTables.length <= 4 ? 2 : 3;
    const builtNodes: Node<TableNodeData>[] = baseTables.map((ds, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const isHighlighted = Boolean(activePair && (activePair[0] === ds.id || activePair[1] === ds.id));
      return {
        id: ds.id,
        type: "tableNode",
        position: { x: 40 + col * 395, y: 24 + row * 285 },
        data: {
          dataset: ds,
          keyCols: keyMap.get(ds.id) ?? new Set(),
          highlighted: isHighlighted,
        },
      };
    });

    const builtEdges: Edge<RelEdgeData>[] = [];

    for (const c of confirmed) {
      if (!keyMap.has(c.spec.left) || !keyMap.has(c.spec.right)) continue;
      const keyStr = c.spec.keys.map((k) => `${k.left}=${k.right}`).join(", ");
      builtEdges.push({
        id: `conf-${c.id}`,
        source: c.spec.left,
        target: c.spec.right,
        type: "relEdge",
        animated: false,
        data: {
          label: c.kind === "append" ? "Stacked" : "Joined",
          sublabel: keyStr || "columns aligned",
          status: "confirmed",
          kind: c.kind,
        },
      });
    }

    for (const s of validSuggestions) {
      if (!keyMap.has(s.left) || !keyMap.has(s.right)) continue;
      const isSel = selectedId === s.id;
      const keyStr = s.keys.map((k) => (k.left === k.right ? k.left : `${k.left}=${k.right}`)).join(", ");
      builtEdges.push({
        id: `sug-${s.id}`,
        source: s.left,
        target: s.right,
        type: "relEdge",
        animated: false,
        data: {
          label:
            s.kind === "append"
              ? `Append · ${Math.round(s.confidence * 100)}%`
              : `Join ${s.cardinality ?? ""} · ${Math.round(s.confidence * 100)}%`,
          sublabel: keyStr,
          status: isSel ? "selected" : "suggested",
          kind: s.kind,
          onSelect: () => onSelectSuggestion(s),
        },
      });
    }

    return { nodes: builtNodes, edges: builtEdges };
  }, [baseTables, suggestions, confirmed, selectedId, activePair, onSelectSuggestion]);

  const canvasHeight = baseTables.length > 2 ? 465 : 275;

  return (
    <div className="er-canvas-card card">
      <div className="er-canvas-bar spread">
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <h2 className="panel-title">Schema map</h2>
          <span className="muted small tabular-nums">
            {baseTables.length} source tables · {confirmed.length} confirmed ·{" "}
            {suggestions.filter((s) => s.kind !== "unrelated" && s.status !== "confirmed" && s.status !== "rejected").length} suggested
          </span>
        </div>
        <div className="er-legend small muted">
          <span><i className="er-swatch confirmed" /> Confirmed</span>
          <span><i className="er-swatch selected" /> Reviewing</span>
          <span><i className="er-swatch suggested" /> Suggested</span>
        </div>
      </div>
      <div style={{ width: "100%", height: canvasHeight }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          minZoom={0.4}
          maxZoom={1.6}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color={tokens.isDark ? "#2E333D" : "#D4D6D0"}
          />
          <Controls showInteractive={false} className="er-flow-controls" />
        </ReactFlow>
      </div>
    </div>
  );
}
