import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Box, CircleDot, Grid, Network, Search, X } from "lucide-react";
import { Chart } from "../components/Chart";
import { SpringSegmented } from "../components/kit";
import { AssociationMatrixView, NetworkGraph2D } from "../components/RelationsMatrix";
import {
  ALL_SIGNS,
  KIND_LABEL,
  type Lens,
  SIGN_LABEL,
  type SignFilter,
  signOf,
  UniverseView,
  visible,
} from "../components/Universe";
import { Badge, ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import { playTick } from "../lib/sound";
import type { FindingDetail, Universe, UniverseEdge, UniverseNode, UniverseStats } from "../lib/types";
import { useProject } from "./ProjectLayout";

type GraphViewMode = "network" | "circular" | "matrix" | "3d";

const LENSES: { id: Lens; label: string; title: string }[] = [
  { id: "all", label: "All signals", title: "Every finding (Grades A–D & formulas)" },
  { id: "truth", label: "Confirmed (A–B)", title: "Only grade A–B findings confirmed on held-out data" },
  { id: "skeptic", label: "Skeptic", title: "Highlights weak, exploratory, or unconfirmed signals" },
];

function fmt(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return v.toExponential(2);
  if (a >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
}

function Spark({ stats }: { stats: UniverseStats }) {
  if (stats.kind === "numeric" && stats.hist?.length) {
    const max = Math.max(...stats.hist, 1);
    const w = 100 / stats.hist.length;
    return (
      <div className="u-spark">
        <svg viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
          {stats.hist.map((c, i) => (
            <rect key={i} x={i * w + 0.5} width={w - 1} y={34 - (32 * c) / max} height={(32 * c) / max} rx={0.8} />
          ))}
        </svg>
        <div className="u-spark-axis mono">
          <span>{fmt(stats.min)}</span>
          <span>median {fmt(stats.median)}</span>
          <span>{fmt(stats.max)}</span>
        </div>
      </div>
    );
  }
  if (stats.top?.length) {
    const max = Math.max(...stats.top.map((t) => t.count), 1);
    return (
      <div className="u-labels-bars">
        {stats.top.map((t) => (
          <div key={t.label}>
            <span className="grow">{t.label}</span>
            <i style={{ width: `${(70 * t.count) / max}%` }} />
            <b className="mono">{t.count.toLocaleString()}</b>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

function StrengthBar({ e }: { e: UniverseEdge }) {
  const v = e.estimate !== null ? Math.min(1, Math.abs(e.estimate)) : e.strength;
  return (
    <span className={`u-bar ${signOf(e)}`} title={e.effect_text ?? ""}>
      <i style={{ width: `${Math.max(8, v * 100)}%` }} />
    </span>
  );
}

function LinkList({
  title,
  edges,
  node,
  onPick,
}: {
  title: string;
  edges: UniverseEdge[];
  node: string;
  onPick: (e: UniverseEdge) => void;
}) {
  if (!edges.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <h4 className="filter-heading" style={{ marginBottom: 6 }}>
        {title}
      </h4>
      <ul className="u-list">
        {edges.map((e) => {
          const other = e.source === node ? e.target : e.source;
          return (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => {
                  playTick();
                  onPick(e);
                }}
                title={e.headline}
              >
                <span className="grow" style={{ fontWeight: 550 }}>
                  {e.via ? `${other} (via ${e.via})` : other}
                </span>
                <StrengthBar e={e} />
                <span className="u-num">
                  {e.estimate !== null ? `${e.estimate >= 0 ? "+" : ""}${e.estimate.toFixed(2)}` : ""}
                </span>
                <span className="u-grade">{e.grade ?? "ƒ"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function NodePanel({
  node,
  edges,
  base,
  onPick,
  onFormula,
}: {
  node: UniverseNode;
  edges: UniverseEdge[];
  base: string;
  onPick: (e: UniverseEdge) => void;
  onFormula: () => void;
}) {
  const navigate = useNavigate();
  const byStrength = (a: UniverseEdge, b: UniverseEdge) =>
    Math.abs(b.estimate ?? b.strength) - Math.abs(a.estimate ?? a.strength);
  const ups = edges.filter((e) => signOf(e) === "up").sort(byStrength);
  const downs = edges.filter((e) => signOf(e) === "down").sort(byStrength);
  const groups = edges.filter((e) => signOf(e) === "groups").sort((a, b) => b.score - a.score);
  const s = node.stats;

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row-wrap" style={{ gap: 8 }}>
        <h2 style={{ fontSize: 17 }}>{node.id}</h2>
        <Badge tone={node.is_target ? "brand" : "outline"}>
          {node.is_target ? "Target outcome" : node.derived ? "Calculated column" : node.role}
        </Badge>
      </div>
      <p className="small muted" style={{ lineHeight: 1.55, margin: 0 }}>
        {node.story}
      </p>
      {node.derived ? (
        <button type="button" className="u-formula" onClick={onFormula}>
          <span>ƒ</span>
          <code>
            {node.id} = {node.derived.formula_text}
          </code>
        </button>
      ) : null}
      {s ? (
        <div className="u-stats">
          <Spark stats={s} />
          <div className="u-facts u-facts-grid">
            <div>
              <span>Rows</span>
              <b className="mono">{s.n.toLocaleString()}</b>
            </div>
            <div>
              <span>Missing</span>
              <b className={`mono ${s.missing ? "warn" : ""}`}>
                {s.n ? `${((100 * s.missing) / s.n).toFixed(1)}%` : "–"}
              </b>
            </div>
            <div>
              <span>Distinct</span>
              <b className="mono">{s.distinct.toLocaleString()}</b>
            </div>
            {s.kind === "numeric" ? (
              <div>
                <span>Mean ± SD</span>
                <b className="mono">
                  {fmt(s.mean)} ± {fmt(s.std)}
                </b>
              </div>
            ) : null}
            {s.kind === "numeric" ? (
              <div>
                <span>IQR</span>
                <b className="mono">
                  {fmt(s.q1)} – {fmt(s.q3)}
                </b>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      <LinkList title="↑ Positive associations" edges={ups} node={node.id} onPick={onPick} />
      <LinkList title="↓ Inverse associations" edges={downs} node={node.id} onPick={onPick} />
      <LinkList title="◆ Group & segment differences" edges={groups} node={node.id} onPick={onPick} />
      {!ups.length && !downs.length && !groups.length ? (
        <div className="muted small">No relationships match the active lens and sign filters.</div>
      ) : null}
      {node.alerts.length ? (
        <div style={{ marginTop: 8 }}>
          <h4 className="filter-heading" style={{ marginBottom: 6 }}>
            Data-quality alerts
          </h4>
          <ul className="u-list">
            {node.alerts.map((a) => (
              <li key={a.finding}>
                <button type="button" onClick={() => navigate(`${base}/${a.finding}`)}>
                  <span className="u-swatch k-alert" />
                  <span className="grow">{a.headline}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function EdgePanel({
  edge,
  projectId,
  runId,
  base,
  onNode,
}: {
  edge: UniverseEdge;
  projectId: string;
  runId: string;
  base: string;
  onNode: (id: string) => void;
}) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    api.finding(projectId, runId, edge.finding).then(setDetail).catch(setError);
  }, [projectId, runId, edge.finding]);

  const sign = signOf(edge);
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div>
        <h2 style={{ fontSize: 15.5, lineHeight: 1.35 }}>{edge.headline}</h2>
      </div>

      <div className="row-wrap" style={{ gap: 6 }}>
        <Badge tone="outline">{edge.family_label}</Badge>
        <Badge tone={sign === "up" ? "info" : sign === "down" ? "bad" : sign === "formula" ? "warn" : "brand"}>
          {SIGN_LABEL[sign]}
        </Badge>
        <Badge tone={edge.grade === "A" || edge.grade === "B" ? "ok" : "outline"}>
          {edge.grade ? `Grade ${edge.grade}` : "Exact Formula"}
        </Badge>
      </div>

      <div className="u-facts">
        {edge.effect_text ? (
          <div>
            <span>Effect</span>
            <b className="mono">{edge.effect_text}</b>
          </div>
        ) : null}
        <div>
          <span>Validation</span>
          <b>
            {edge.kind === "formula"
              ? "holds on every row"
              : edge.confirmed
                ? "confirmed on held-out data"
                : edge.exploratory
                  ? "exploratory"
                  : "not confirmed"}
          </b>
        </div>
        {edge.via ? (
          <div>
            <span>Conditioned on</span>
            <b className="mono">{edge.via}</b>
          </div>
        ) : null}
      </div>

      {error ? <ErrorBox error={error} /> : null}
      {detail ? (
        <>
          {detail.charts[0] ? (
            <div className="u-chart">
              <Chart chart={detail.charts[0]} height={210} compact />
            </div>
          ) : null}
          <div className="lens small" dangerouslySetInnerHTML={{ __html: detail.lenses.plain.html }} />
        </>
      ) : !error ? (
        <div className="muted small">Loading chart &amp; synthesis…</div>
      ) : null}

      <div className="row-wrap" style={{ gap: 6, marginTop: 4 }}>
        <button type="button" className="btn btn-sm" onClick={() => onNode(edge.source)}>
          {edge.source}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => onNode(edge.target)}>
          {edge.target}
        </button>
        <button type="button" className="btn btn-sm btn-primary" onClick={() => navigate(`${base}/${edge.finding}`)}>
          Full finding &amp; drill →
        </button>
      </div>
    </div>
  );
}

export function UniversePage() {
  const { project } = useProject();
  const { runId = "" } = useParams();
  const [universe, setUniverse] = useState<Universe | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [viewMode, setViewMode] = useState<GraphViewMode>("network");
  const [lens, setLens] = useState<Lens>("all");
  const [signs, setSigns] = useState<SignFilter[]>(ALL_SIGNS);
  const [node, setNode] = useState<string | null>(null);
  const [edge, setEdge] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.universe(project.id, runId).then(setUniverse).catch(setError);
  }, [project.id, runId]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        setNode(null);
        setEdge(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const base = `/p/${project.id}/discover/runs/${runId}`;
  const shown = useMemo(
    () => (universe ? universe.edges.filter((e) => visible(e, lens, signs)) : []),
    [universe, lens, signs],
  );

  if (error)
    return (
      <div className="content" style={{ paddingTop: 24 }}>
        <ErrorBox error={error} />
      </div>
    );
  if (!universe) return <Loading label="Mapping variable relationship network…" />;

  const selEdge = universe.edges.find((e) => e.id === edge) ?? null;
  const selNode = universe.nodes.find((n) => n.id === node) ?? null;
  const nodeEdges = selNode
    ? shown.filter(
        (e, i, all) =>
          (e.source === selNode.id || e.target === selNode.id || e.via === selNode.id) &&
          all.findIndex(
            (x) =>
              x.finding === e.finding &&
              (x.source === selNode.id || x.target === selNode.id || x.via === selNode.id),
          ) === i,
      )
    : [];
  const confirmed = shown.filter((e) => e.confirmed && e.kind !== "formula").length;
  const counts = Object.fromEntries(
    ALL_SIGNS.map((s) => [s, universe.edges.filter((e) => signOf(e) === s && visible(e, lens)).length]),
  ) as Record<SignFilter, number>;
  const kinds = [...new Set(universe.edges.map((e) => e.kind))].filter((k) => k !== "pair" && k !== "formula");
  const toggleSign = (s: SignFilter) => {
    playTick();
    setSigns((cur) => (cur.includes(s) ? (cur.length > 1 ? cur.filter((x) => x !== s) : cur) : [...cur, s]));
  };

  const rankedNodes = [...universe.nodes]
    .filter((n) => !search || n.id.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (a.is_target !== b.is_target ? (a.is_target ? -1 : 1) : b.degree - a.degree));

  return (
    <div className="relations-studio">
      <header className="relations-header">
        <div className="row" style={{ gap: 14 }}>
          <Link className="btn btn-sm" to={base}>
            <ArrowLeft size={14} />
            <span>Insight Feed</span>
          </Link>
          <div>
            <div className="row" style={{ gap: 8 }}>
              <span className="u-title">Data Universe</span>
              <Badge tone="outline">{universe.dataset ?? "Analysis Run"}</Badge>
            </div>
            <div className="muted tiny tabular-nums" style={{ marginTop: 2 }}>
              {universe.nodes.length} columns · {shown.length} active links · {confirmed} confirmed on holdout
              {universe.target ? ` · outcome: ${universe.target}` : ""}
            </div>
          </div>
        </div>

        <div className="row-wrap" style={{ gap: 10 }}>
          <SpringSegmented<GraphViewMode>
            size="xs"
            ariaLabel="Visualization mode"
            role="tablist"
            value={viewMode}
            onChange={setViewMode}
            items={[
              {
                id: "network",
                label: (
                  <>
                    <Network size={13} /> 2D Network
                  </>
                ),
              },
              {
                id: "circular",
                label: (
                  <>
                    <CircleDot size={13} /> Chord Ring
                  </>
                ),
              },
              {
                id: "matrix",
                label: (
                  <>
                    <Grid size={13} /> Matrix
                  </>
                ),
              },
              {
                id: "3d",
                label: (
                  <>
                    <Box size={13} /> 3D View
                  </>
                ),
              },
            ]}
          />

          <SpringSegmented<Lens>
            size="xs"
            ariaLabel="Lens"
            role="tablist"
            value={lens}
            onChange={setLens}
            items={LENSES}
          />
        </div>
      </header>

      <div className="relations-body">
        <div className="relations-stage">
          <div className="relations-filter-bar">
            <div className="row-wrap" style={{ gap: 6 }} role="group" aria-label="Show relationships">
              {ALL_SIGNS.filter((s) => counts[s] > 0).map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`u-chip ${s} ${signs.includes(s) ? "on" : ""}`}
                  aria-pressed={signs.includes(s)}
                  onClick={() => toggleSign(s)}
                >
                  {SIGN_LABEL[s]} <b className="mono">{counts[s]}</b>
                </button>
              ))}
            </div>
            <div className="row-wrap tiny muted" style={{ gap: 10 }}>
              <span>Solid = Holdout Confirmed</span>
              <span>Dashed = Unconfirmed</span>
              {kinds.slice(0, 3).map((k) => (
                <span key={k}>
                  <i className={`u-swatch k-${k}`} /> {KIND_LABEL[k] ?? k}
                </span>
              ))}
            </div>
          </div>

          <div className="relations-canvas-wrap">
            {viewMode === "network" || viewMode === "circular" ? (
              <NetworkGraph2D
                universe={universe}
                lens={lens}
                signs={signs}
                layoutMode={viewMode === "circular" ? "circular" : "force"}
                selectedNode={node}
                selectedEdge={edge}
                onSelectNode={(id) => {
                  setNode(id);
                  setEdge(null);
                }}
                onSelectEdge={(id) => {
                  setEdge(id);
                }}
              />
            ) : viewMode === "matrix" ? (
              <AssociationMatrixView
                universe={universe}
                lens={lens}
                signs={signs}
                selectedEdge={edge}
                onSelectNode={(id) => {
                  setNode(id);
                  setEdge(null);
                }}
                onSelectEdge={(id) => setEdge(id)}
              />
            ) : (
              <div className="universe-3d-box">
                <UniverseView
                  universe={universe}
                  lens={lens}
                  signs={signs}
                  selectedNode={node}
                  selectedEdge={edge}
                  onSelectNode={(id) => {
                    setNode(id);
                    setEdge(null);
                  }}
                  onSelectEdge={setEdge}
                />
              </div>
            )}

            {shown.length === 0 ? (
              <div className="relations-empty-overlay card card-pad">
                No relationships pass the selected lens &amp; filters.
              </div>
            ) : null}
          </div>
        </div>

        <aside className="relations-inspector" aria-label="Relationship inspector">
          {selEdge || selNode ? (
            <div>
              <div className="spread" style={{ marginBottom: 10 }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setNode(null);
                    setEdge(null);
                  }}
                >
                  <ArrowLeft size={13} /> All columns
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => {
                    setNode(null);
                    setEdge(null);
                  }}
                  aria-label="Close"
                >
                  <X size={14} />
                </button>
              </div>
              {selEdge ? (
                <EdgePanel
                  edge={selEdge}
                  projectId={project.id}
                  runId={runId}
                  base={base}
                  onNode={(id) => {
                    setNode(id);
                    setEdge(null);
                  }}
                />
              ) : selNode ? (
                <NodePanel
                  node={selNode}
                  edges={nodeEdges}
                  base={base}
                  onPick={(e) => setEdge(e.id)}
                  onFormula={() => {
                    const f = universe.edges.find((e) => e.kind === "formula" && e.target === selNode.id);
                    if (f) setEdge(f.id);
                  }}
                />
              ) : null}
            </div>
          ) : (
            <div className="stack" style={{ gap: 10 }}>
              <div>
                <h2 className="panel-title">Columns by connectivity</h2>
                <div className="muted tiny" style={{ marginTop: 2 }}>Click any column or graph link to inspect its statistical evidence.</div>
              </div>

              <div className="search-field">
                <Search size={13} className="search-icon" />
                <input
                  type="search"
                  placeholder="Filter columns…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  style={{ width: "100%", paddingLeft: 28, height: 30, fontSize: 12.5 }}
                  aria-label="Filter columns"
                />
              </div>

              <ul className="u-list">
                {rankedNodes.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => {
                        playTick();
                        setNode(n.id);
                        setEdge(null);
                      }}
                    >
                      <span className="grow" style={{ fontWeight: n.is_target ? 700 : 550 }}>
                        {n.derived ? `ƒ ${n.id}` : n.id}
                        {n.is_target ? " (outcome)" : ""}
                      </span>
                      <span className="tiny muted">{n.role}</span>
                      <Badge tone={n.degree > 0 ? "brand" : "gray"}>{n.degree}</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
