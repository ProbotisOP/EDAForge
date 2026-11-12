import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Chart } from "../components/Chart";
import { ALL_SIGNS, KIND_LABEL, type Lens, SIGN_LABEL, type SignFilter, signOf, UniverseView, visible } from "../components/Universe";
import { ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import type { FindingDetail, Universe, UniverseEdge, UniverseNode, UniverseStats } from "../lib/types";
import { useProject } from "./ProjectLayout";

const LENSES: { id: Lens; label: string; hint: string }[] = [
  { id: "all", label: "All signals", hint: "Every finding; brightness = evidence grade, pulse speed = effect size" },
  { id: "truth", label: "Truth", hint: "Only grade A–B findings confirmed on data the search never saw" },
  { id: "skeptic", label: "Skeptic", hint: "Lights up what is weak: unconfirmed, exploratory or grade D–E" },
];

function fmt(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return v.toExponential(2);
  if (a >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
}

/** The column's distribution as a tiny bar chart (counts from the stored data). */
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
        <div className="u-spark-axis">
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
            <b>{t.count.toLocaleString()}</b>
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
      <i style={{ width: `${Math.max(6, v * 100)}%` }} />
    </span>
  );
}

function LinkList({ title, edges, node, onPick }: { title: string; edges: UniverseEdge[]; node: string; onPick: (e: UniverseEdge) => void }) {
  if (!edges.length) return null;
  return (
    <>
      <div className="u-kicker" style={{ marginTop: 12 }}>
        {title}
      </div>
      <ul className="u-list">
        {edges.map((e) => {
          const other = e.source === node ? e.target : e.source;
          return (
            <li key={e.id}>
              <button onClick={() => onPick(e)} title={e.headline}>
                <span className="grow">{e.via ? `${other} (via ${e.via})` : other}</span>
                <StrengthBar e={e} />
                <span className="u-num">{e.estimate !== null ? `${e.estimate >= 0 ? "+" : ""}${e.estimate.toFixed(2)}` : ""}</span>
                <span className="u-grade">{e.grade ?? "ƒ"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function NodePanel({ node, edges, base, onPick, onFormula }: { node: UniverseNode; edges: UniverseEdge[]; base: string; onPick: (e: UniverseEdge) => void; onFormula: () => void }) {
  const navigate = useNavigate();
  const byStrength = (a: UniverseEdge, b: UniverseEdge) => Math.abs(b.estimate ?? b.strength) - Math.abs(a.estimate ?? a.strength);
  const ups = edges.filter((e) => signOf(e) === "up").sort(byStrength);
  const downs = edges.filter((e) => signOf(e) === "down").sort(byStrength);
  const groups = edges.filter((e) => signOf(e) === "groups").sort((a, b) => b.score - a.score);
  const s = node.stats;
  return (
    <>
      <div className="u-kicker">{node.is_target ? "Outcome" : node.derived ? "Calculated column" : node.role}</div>
      <h3>{node.id}</h3>
      <p className="u-story">{node.story}</p>
      {node.derived ? (
        <button className="u-formula" onClick={onFormula}>
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
            <div><span>Rows</span><b>{s.n.toLocaleString()}</b></div>
            <div><span>Missing</span><b className={s.missing ? "warn" : ""}>{s.n ? `${((100 * s.missing) / s.n).toFixed(1)}%` : "–"}</b></div>
            <div><span>Distinct</span><b>{s.distinct.toLocaleString()}</b></div>
            {s.kind === "numeric" ? <div><span>Mean ± sd</span><b>{fmt(s.mean)} ± {fmt(s.std)}</b></div> : null}
            {s.kind === "numeric" ? <div><span>Middle half</span><b>{fmt(s.q1)} – {fmt(s.q3)}</b></div> : null}
          </div>
        </div>
      ) : null}
      <LinkList title="↑ Rises with it" edges={ups} node={node.id} onPick={onPick} />
      <LinkList title="↓ Falls as it rises" edges={downs} node={node.id} onPick={onPick} />
      <LinkList title="◆ Differs between groups" edges={groups} node={node.id} onPick={onPick} />
      {!ups.length && !downs.length && !groups.length ? <div className="u-faint" style={{ marginTop: 10 }}>No relationship under the current lens and filters.</div> : null}
      {node.alerts.length ? (
        <>
          <div className="u-kicker" style={{ marginTop: 12 }}>Data-quality alerts</div>
          <ul className="u-list">
            {node.alerts.map((a) => (
              <li key={a.finding}>
                <button onClick={() => navigate(`${base}/${a.finding}`)}>
                  <span className="u-swatch k-alert" />
                  <span className="grow">{a.headline}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

function EdgePanel({ edge, projectId, runId, base, onNode }: { edge: UniverseEdge; projectId: string; runId: string; base: string; onNode: (id: string) => void }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    setDetail(null);
    setError(null);
    api.finding(projectId, runId, edge.finding).then(setDetail).catch(setError);
  }, [projectId, runId, edge.finding]);
  const sign = signOf(edge);
  const meaning =
    sign === "formula"
      ? `${edge.target} is calculated from ${edge.source}: a fact checked on every row.`
      : sign === "up"
        ? `When ${edge.source} is higher, ${edge.target} tends to be higher too.`
        : sign === "down"
          ? `When ${edge.source} is higher, ${edge.target} tends to be lower.`
          : `${edge.target} differs between groups of ${edge.source}.`;
  return (
    <>
      <div className="u-kicker">{edge.family_label}</div>
      <h3>{edge.headline}</h3>
      <div className={`u-sign ${sign}`}>{SIGN_LABEL[sign]}</div>
      <p className="u-story">{meaning}</p>
      {edge.estimate !== null && edge.effect_label ? (
        <div className="u-gauge" title="Effect on a −1 to +1 scale">
          <div className="u-gauge-track">
            <i className="zero" />
            <i className={`dot ${sign}`} style={{ left: `${50 + 50 * Math.max(-1, Math.min(1, edge.estimate))}%` }} />
          </div>
          <div className="u-spark-axis">
            <span>−1</span>
            <span>
              {edge.effect_label} {edge.estimate >= 0 ? "+" : ""}
              {edge.estimate.toFixed(2)}
            </span>
            <span>+1</span>
          </div>
        </div>
      ) : null}
      <div className="u-facts">
        {edge.effect_text ? <div><span>Effect</span><b>{edge.effect_text}</b></div> : null}
        <div><span>Evidence</span><b>{edge.grade ? `Grade ${edge.grade}` : "Fact (exact)"}</b></div>
        <div><span>Check</span><b>{edge.kind === "formula" ? "holds on every row" : edge.confirmed ? "confirmed on held-out data" : edge.exploratory ? "exploratory" : "not confirmed"}</b></div>
        {edge.via ? <div><span>Through</span><b>{edge.via}</b></div> : null}
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {detail ? (
        <>
          {detail.charts[0] ? (
            <div className="u-chart">
              <Chart chart={detail.charts[0]} height={190} />
            </div>
          ) : null}
          {/* The HTML comes from the server's escaping Markdown converter: data cannot inject markup. */}
          <div className="lens u-lens" dangerouslySetInnerHTML={{ __html: detail.lenses.plain.html }} />
        </>
      ) : !error ? (
        <div className="u-faint">Loading the evidence…</div>
      ) : null}
      {edge.kind !== "formula" ? <p className="u-faint">An association in this data, not proof that one column causes the other.</p> : null}
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <button className="u-btn" onClick={() => onNode(edge.source)}>◎ {edge.source}</button>
        <button className="u-btn" onClick={() => onNode(edge.target)}>◎ {edge.target}</button>
        <button className="u-btn u-primary" onClick={() => navigate(`${base}/${edge.finding}`)}>
          Full evidence →
        </button>
      </div>
    </>
  );
}

export function UniversePage() {
  const { project } = useProject();
  const { runId = "" } = useParams();
  const [universe, setUniverse] = useState<Universe | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lens, setLens] = useState<Lens>("all");
  const [signs, setSigns] = useState<SignFilter[]>(ALL_SIGNS);
  const [node, setNode] = useState<string | null>(null);
  const [edge, setEdge] = useState<string | null>(null);

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
  const shown = useMemo(() => (universe ? universe.edges.filter((e) => visible(e, lens, signs)) : []), [universe, lens, signs]);
  if (error) return <div className="content" style={{ paddingTop: 24 }}><ErrorBox error={error} /></div>;
  if (!universe) return <Loading label="Charting the data universe…" />;

  const selEdge = universe.edges.find((e) => e.id === edge) ?? null;
  const selNode = universe.nodes.find((n) => n.id === node) ?? null;
  // A finding with two conditions draws two beams; list each finding once.
  const nodeEdges = selNode
    ? shown.filter((e, i, all) => (e.source === selNode.id || e.target === selNode.id || e.via === selNode.id) && all.findIndex((x) => x.finding === e.finding && (x.source === selNode.id || x.target === selNode.id || x.via === selNode.id)) === i)
    : [];
  const confirmed = shown.filter((e) => e.confirmed && e.kind !== "formula").length;
  const counts = Object.fromEntries(ALL_SIGNS.map((s) => [s, universe.edges.filter((e) => signOf(e) === s && visible(e, lens)).length])) as Record<SignFilter, number>;
  const kinds = [...new Set(universe.edges.map((e) => e.kind))].filter((k) => k !== "pair" && k !== "formula");
  const hub = [...universe.nodes].sort((a, b) => b.degree - a.degree)[0];
  const toggle = (s: SignFilter) => setSigns((cur) => (cur.includes(s) ? (cur.length > 1 ? cur.filter((x) => x !== s) : cur) : [...cur, s]));

  return (
    <div className="universe">
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
      <div className="u-hud u-top">
        <div>
          <div className="u-title">DATA UNIVERSE</div>
          <div className="u-sub">
            {universe.dataset ?? "run"} · {universe.nodes.length} columns · {shown.length} signals · {confirmed} confirmed
            {universe.target ? ` · outcome ${universe.target}` : ""}
          </div>
        </div>
        <div className="u-lenses" role="tablist" aria-label="Lens">
          {LENSES.map((l) => (
            <button key={l.id} role="tab" aria-selected={lens === l.id} className={lens === l.id ? "on" : ""} title={l.hint} onClick={() => setLens(l.id)}>
              {l.label}
            </button>
          ))}
        </div>
        <Link className="u-btn" to={base}>
          Insight Feed →
        </Link>
      </div>

      <div className="u-hud u-legend">
        <div className="u-chips" role="group" aria-label="Show relationships">
          {ALL_SIGNS.filter((s) => counts[s] > 0).map((s) => (
            <button key={s} className={`u-chip ${s} ${signs.includes(s) ? "on" : ""}`} aria-pressed={signs.includes(s)} onClick={() => toggle(s)}>
              {SIGN_LABEL[s]} <b>{counts[s]}</b>
            </button>
          ))}
        </div>
        {kinds.map((k) => (
          <div key={k}>
            <span className={`u-swatch k-${k}`} /> {KIND_LABEL[k] ?? k}
          </div>
        ))}
        <div className="u-faint">Pulses flow along ↑ beams and against ↓ beams · faster = stronger · solid = confirmed, dashed = not · red ring = data alert · ƒ = calculated column</div>
        <div className="u-faint">Drag to orbit · scroll to zoom · hover a star for its numbers · click it to explore · Esc to reset</div>
      </div>

      {!selEdge && !selNode && hub && shown.length ? (
        <button className="u-hud u-hint" onClick={() => setNode(hub.id)}>
          ✦ Start with <b>{hub.id}</b>: the most connected star ({hub.degree} links)
        </button>
      ) : null}

      {selEdge || selNode ? (
        <aside className="u-hud u-panel" aria-label="Selection">
          <button className="u-close" onClick={() => (setNode(null), setEdge(null))} aria-label="Close">
            ✕
          </button>
          {selEdge ? (
            <EdgePanel edge={selEdge} projectId={project.id} runId={runId} base={base} onNode={(id) => (setNode(id), setEdge(null))} />
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
        </aside>
      ) : null}
      {shown.length === 0 ? (
        <div className="u-hud u-empty">No signals under this lens. Nothing here passed the checks it requires; that is a result too.</div>
      ) : null}
    </div>
  );
}
