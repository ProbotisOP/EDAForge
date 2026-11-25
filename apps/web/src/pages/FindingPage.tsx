import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { radarClasses, RadarChart } from "@mui/x-charts";
import { ChevronLeft, ChevronRight, GitBranch, X } from "lucide-react";
import { Chart } from "../components/Chart";
import { ExploreStudio } from "../components/ExploreStudio";
import { EvidenceBadge } from "../components/Feed";
import { SpringSegmented } from "../components/kit";
import { Badge, ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import type { DrillTarget } from "../lib/muiChartsAdapter";
import { fmtNum, fmtPct } from "../lib/format";
import { playTick } from "../lib/sound";
import { useTheme } from "../lib/theme";
import type { DrillFilter, ExploreMode, FeedItem, FindingDetail } from "../lib/types";
import { useProject } from "./ProjectLayout";

type Lens = "plain" | "analyst" | "scientist";
const LENS_LABEL: Record<Lens, string> = { plain: "Plain", analyst: "Analyst", scientist: "Scientist" };

function p(value: unknown): string {
  if (typeof value !== "number") return "—";
  if (value < 1e-4) return value.toExponential(1);
  return fmtNum(value, 2);
}

export function FindingPage() {
  const { project } = useProject();
  const { tokens } = useTheme();
  const { runId = "", findingId = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [siblings, setSiblings] = useState<FeedItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [lens, setLens] = useState<Lens>("plain");
  const [showMethod, setShowMethod] = useState(false);
  const [drillOpen, setDrillOpen] = useState(false);
  const [drillSeed, setDrillSeed] = useState<DrillFilter | null>(null);

  const load = useCallback(() => {
    setError(null);
    setDetail(null);
    setDrillOpen(false);
    setDrillSeed(null);
    api.finding(project.id, runId, findingId).then(setDetail).catch(setError);
  }, [project.id, runId, findingId]);
  useEffect(load, [load]);

  useEffect(() => {
    api
      .run(project.id, runId)
      .then((rv) => setSiblings(rv.feed.filter((f) => !f.merged_into && f.evidence.grade !== "E")))
      .catch(() => {});
  }, [project.id, runId]);

  const runMeta = useMemo(() => project.runs.find((r) => r.id === runId), [project.runs, runId]);
  const dataset = useMemo(() => {
    const dsId = detail?.dataset_id ?? runMeta?.dataset_id;
    return dsId ? project.datasets.find((d) => d.id === dsId) : undefined;
  }, [detail?.dataset_id, runMeta?.dataset_id, project.datasets]);

  const back = `/p/${project.id}/discover/runs/${runId}`;
  const curIdx = siblings.findIndex((s) => s.id === findingId);
  const prevFinding = curIdx > 0 ? siblings[curIdx - 1] : null;
  const nextFinding = curIdx >= 0 && curIdx < siblings.length - 1 ? siblings[curIdx + 1] : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "[" && prevFinding) {
        e.preventDefault();
        playTick();
        navigate(`${back}/${prevFinding.id}`);
      } else if (e.key === "]" && nextFinding) {
        e.preventDefault();
        playTick();
        navigate(`${back}/${nextFinding.id}`);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prevFinding, nextFinding, back, navigate]);

  if (error)
    return (
      <div className="content" style={{ paddingTop: 24 }}>
        <ErrorBox error={error} onRetry={load} />
      </div>
    );
  if (!detail) return <Loading label="Loading finding…" />;
  const m = detail.method;
  const conf = m.confirmation as {
    status?: string;
    method?: string;
    p_value?: number;
    q_value?: number;
    n?: number;
    aggregation?: string;
  };
  const descriptive = detail.evidence.basis === "descriptive";

  const findCol = (name?: string) => dataset?.columns.find((c) => c.name === name);
  const v0 = detail.variables[0];
  const v1 = detail.variables[1];
  const v2 = detail.variables[2];
  const c0 = findCol(v0);
  const c1 = findCol(v1);

  let exploreX = v0;
  let exploreY = v1 ?? "";
  let exploreMode: ExploreMode = "auto";
  if (c0?.role === "numeric" && c1 && (c1.role === "categorical" || c1.role === "boolean")) {
    exploreX = v1;
    exploreY = v0;
    exploreMode = "group";
  } else if (c0?.role === "numeric" && c1?.role === "numeric") {
    exploreX = v0;
    exploreY = v1;
    exploreMode = "scatter";
  } else if (detail.family === "time") {
    const dtCol = dataset?.columns.find((c) => c.role === "datetime")?.name;
    if (dtCol) {
      exploreX = dtCol;
      exploreY = c0?.role === "numeric" ? v0 : "";
      exploreMode = "time";
    }
  }

  const handleChartDrill = (target: DrillTarget) => {
    if (!dataset) return;
    playTick(1.1);
    if (typeof target.low === "number" && typeof target.high === "number") {
      const col = target.column && dataset.columns.some((c) => c.name === target.column) ? target.column : exploreX;
      setDrillSeed({
        column: col,
        op: "range",
        low: target.low,
        high: target.high,
        label: `${col} [${target.low.toPrecision(3)}, ${target.high.toPrecision(3)}]`,
      });
    } else if (target.column && target.value !== undefined && dataset.columns.some((c) => c.name === target.column)) {
      setDrillSeed({
        column: target.column,
        op: "eq",
        value: target.value,
        label: `${target.column} = ${target.value}`,
      });
    }
    setDrillOpen(true);
  };

  const scoreEntries = Object.entries(detail.score_components);

  return (
    <>
      <div className="topbar" style={{ alignItems: "flex-start" }}>
        <div className="grow">
          <div className="spread" style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <Link to={back} className="small" style={{ fontWeight: 500 }}>
              ← Insight Feed
            </Link>
            {siblings.length > 1 ? (
              <div className="row" style={{ gap: 4 }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!prevFinding}
                  onClick={() => prevFinding && navigate(`${back}/${prevFinding.id}`)}
                  title={prevFinding ? `Previous: ${prevFinding.headline}` : "First finding"}
                  aria-label="Previous finding"
                >
                  <ChevronLeft size={13} /> Prev
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!nextFinding}
                  onClick={() => nextFinding && navigate(`${back}/${nextFinding.id}`)}
                  title={nextFinding ? `Next: ${nextFinding.headline}` : "Last finding"}
                  aria-label="Next finding"
                >
                  Next <ChevronRight size={13} />
                </button>
              </div>
            ) : null}
          </div>

          <h1 style={{ maxWidth: 920 }}>{detail.headline}</h1>

          <div className="row-wrap small muted" style={{ gap: 8, marginTop: 8 }}>
            <span className="rank">#{detail.rank}</span>
            <span>·</span>
            <span>{detail.family_label}</span>
            <span>·</span>
            <EvidenceBadge item={detail} />
            {detail.records_label ? (
              <>
                <span>·</span>
                <span className="tabular-nums">{detail.records_label}</span>
              </>
            ) : null}
            <span>·</span>
            <span>Columns: {detail.variables.map((v) => (v === "__source__" ? "source file" : v)).join(" · ")}</span>
          </div>
        </div>
      </div>

      <div className="content">
        <div className="detail-layout">
          <div className="stack">
            <div className="card card-pad">
              <div className="spread" style={{ marginBottom: 14, flexWrap: "wrap" }}>
                <SpringSegmented<Lens>
                  ariaLabel="Explanation level"
                  role="tablist"
                  value={lens}
                  onChange={setLens}
                  items={(["plain", "analyst", "scientist"] as Lens[]).map((l) => ({
                    id: l,
                    label: LENS_LABEL[l],
                  }))}
                />
                <span className="muted small">
                  {lens === "plain"
                    ? "Plain-English summary"
                    : lens === "analyst"
                      ? "Effect sizes, CIs, and subgroups"
                      : "Statistical test, ledger, and assumptions"}
                </span>
              </div>
              <div className="lens" dangerouslySetInnerHTML={{ __html: detail.lenses[lens].html }} />
              <div className="tiny faint mt">
                Deterministic template: every figure is read directly from the stored statistical ledger.
              </div>
            </div>

            {detail.charts.map((c, i) => (
              <div key={i} className="card card-pad">
                <Chart
                  chart={c}
                  onDrillTarget={dataset ? handleChartDrill : undefined}
                  onOpenExplorer={
                    dataset
                      ? () => {
                          playTick();
                          setDrillOpen((v) => !v);
                        }
                      : undefined
                  }
                />
                <div className="tiny muted mt">{c.alt_text}</div>
              </div>
            ))}

            {drillOpen && dataset ? (
              <div className="card card-pad">
                <div className="spread" style={{ marginBottom: 10 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <GitBranch size={15} style={{ color: "var(--brand)" }} />
                    <div>
                      <h2 className="panel-title" style={{ margin: 0 }}>Subgroup &amp; drill explorer</h2>
                      <div className="small muted">
                        Slice <b>{dataset.name}</b> across dimensions and time grains to check how this pattern behaves in subgroups.
                      </div>
                    </div>
                  </div>
                  <button type="button" className="btn btn-sm" onClick={() => setDrillOpen(false)} aria-label="Close drill explorer">
                    <X size={14} />
                  </button>
                </div>
                <ExploreStudio
                  projectId={project.id}
                  dataset={dataset}
                  initialX={exploreX}
                  initialY={exploreY}
                  initialGroup={v2}
                  initialMode={exploreMode}
                  initialFilter={drillSeed}
                />
              </div>
            ) : null}

            <div className="card">
              <div className="card-head">
                <h2>Statistical ledger &amp; methodology</h2>
                <button className="btn btn-sm" onClick={() => setShowMethod(!showMethod)} aria-expanded={showMethod}>
                  {showMethod ? "Hide" : "Show method & evidence"}
                </button>
              </div>
              {showMethod ? (
                <div className="card-pad method stack">
                  {descriptive ? (
                    <div>
                      <h3 className="filter-heading">Rule</h3>
                      <p>{m.rule ?? detail.summary}</p>
                      <p className="muted small">
                        Descriptive check computed exactly on every row: no hypothesis test, no p-value, no evidence grade.
                      </p>
                    </div>
                  ) : (
                    <>
                      <table className="plain">
                        <tbody>
                          <tr>
                            <td>Finding ID</td>
                            <td className="mono">{detail.id}</td>
                          </tr>
                          <tr>
                            <td>Analysis</td>
                            <td className="mono">
                              {m.analyzer} v{m.analyzer_version}
                            </td>
                          </tr>
                          <tr>
                            <td>Test</td>
                            <td className="mono">{m.test}</td>
                          </tr>
                          <tr>
                            <td>Statistic (search data)</td>
                            <td className="mono">{fmtNum(m.statistic ?? null, 4)}</td>
                          </tr>
                          <tr>
                            <td>p-value (search data)</td>
                            <td className="mono">{p(m.p_value)}</td>
                          </tr>
                          <tr>
                            <td>q-value (false-discovery adjusted, search data)</td>
                            <td className="mono">{p(m.q_value)}</td>
                          </tr>
                          <tr>
                            <td>Confirmation</td>
                            <td>
                              {conf.method}
                              {conf.aggregation ? ` — ${conf.aggregation}` : ""}: p = <span className="mono">{p(conf.p_value)}</span>, q ={" "}
                              <span className="mono">{p(conf.q_value)}</span>, n = <span className="mono">{conf.n ?? "—"}</span> →{" "}
                              <b>{conf.status}</b>
                            </td>
                          </tr>
                          {m.effect ? (
                            <tr>
                              <td>Effect</td>
                              <td className="mono">
                                {m.effect.measure} = {fmtNum(m.effect.estimate)} [{fmtNum(m.effect.ci_low ?? null)},{" "}
                                {fmtNum(m.effect.ci_high ?? null)}] ({Math.round(100 * m.effect.ci_level)}%,{" "}
                                {m.effect.ci_method ?? "—"}; {m.effect.split ?? "—"} split)
                              </td>
                            </tr>
                          ) : null}
                          {m.secondary_effects.map((e, i) => (
                            <tr key={i}>
                              <td>Also</td>
                              <td className="mono">
                                {e.measure} = {fmtNum(e.estimate)} [{fmtNum(e.ci_low ?? null)}, {fmtNum(e.ci_high ?? null)}] ({e.ci_method})
                              </td>
                            </tr>
                          ))}
                          <tr>
                            <td>Rows used</td>
                            <td className="mono">{m.n.toLocaleString()}</td>
                          </tr>
                          <tr>
                            <td>Robustness</td>
                            <td>
                              stability {m.stability !== undefined && m.stability !== null ? fmtPct(m.stability, 0) : "not measured"};{" "}
                              {m.specs_total ? `${m.specs_consistent ?? 0} of ${m.specs_total} specifications agree` : "specification curve not run"}
                            </td>
                          </tr>
                          <tr>
                            <td>Causal rung</td>
                            <td>
                              {m.rung} — {m.rung === "R1" ? "an association, not a causal claim" : m.rung}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <div>
                        <h3 className="filter-heading" style={{ marginBottom: 6 }}>Assumptions</h3>
                        {m.assumptions.length ? (
                          m.assumptions.map((a, i) => (
                            <div key={i} className="assume">
                              <Badge
                                tone={a.status === "pass" ? "ok" : a.status === "fail" ? "bad" : a.status === "warn" ? "warn" : "gray"}
                              >
                                {a.status}
                              </Badge>
                              <div>
                                <b>{a.name}</b>: {a.description} <span className="muted">{a.detail}</span>
                              </div>
                            </div>
                          ))
                        ) : (
                          <p className="muted">None declared.</p>
                        )}
                      </div>
                      <div>
                        <h3 className="filter-heading" style={{ marginBottom: 6 }}>Hypothesis ledger entries</h3>
                        <div className="table-wrap">
                          <table className="data">
                            <thead>
                              <tr>
                                <th>ID</th>
                                <th>Hypothesis</th>
                                <th>Test</th>
                                <th>Split</th>
                                <th className="num">Statistic</th>
                                <th className="num">p</th>
                                <th className="num">n</th>
                                <th className="num">Resamples</th>
                                <th className="num">Seed</th>
                              </tr>
                            </thead>
                            <tbody>
                              {m.ledger.map((e, i) => (
                                <tr key={i}>
                                  <td className="mono">{String(e.hypothesis_id)}</td>
                                  <td title={String(e.hypothesis)}>{String(e.hypothesis)}</td>
                                  <td className="mono">{String(e.test)}</td>
                                  <td>{String(e.split)}</td>
                                  <td className="num">{fmtNum((e.statistic as number) ?? null, 4)}</td>
                                  <td className="num">{p(e.p_value)}</td>
                                  <td className="num">{e.n === null || e.n === undefined ? "—" : String(e.n)}</td>
                                  <td className="num">
                                    {e.n_resamples === null || e.n_resamples === undefined ? "—" : String(e.n_resamples)}
                                  </td>
                                  <td className="num mono">{e.seed === null || e.seed === undefined ? "—" : String(e.seed)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                      <div>
                        <h3 className="filter-heading" style={{ marginBottom: 6 }}>Parameters</h3>
                        <pre>{JSON.stringify(m.params, null, 2)}</pre>
                      </div>
                      <div>
                        <h3 className="filter-heading" style={{ marginBottom: 6 }}>Reproducibility</h3>
                        <pre>{JSON.stringify(detail.provenance, null, 2)}</pre>
                        <p className="muted small">
                          Running the same settings on files with the same fingerprints reproduces this result: the seed fixes every
                          split, permutation, and bootstrap.
                        </p>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </div>

          <aside className="inspector-panel">
            <div className="inspector-section">
              <div className="row" style={{ gap: 12, marginBottom: 8 }}>
                <div className={`grade g-${descriptive ? "F" : detail.evidence.grade}`}>
                  {descriptive ? "fact" : detail.evidence.grade}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14.5 }}>
                    {descriptive
                      ? "Exact data check"
                      : `${detail.evidence.label[0].toUpperCase()}${detail.evidence.label.slice(1)} evidence`}
                  </div>
                  <div className="muted small">{detail.evidence.wording}</div>
                </div>
              </div>
              <div className="small muted">{detail.evidence.confirmation}</div>
              {!descriptive && m.grade_reasons.length ? (
                <details style={{ marginTop: 8 }}>
                  <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>
                    Why not a higher grade?
                  </summary>
                  <ul className="small" style={{ paddingLeft: 18 }}>
                    {m.grade_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>

            {detail.effect_text ? (
              <div className="inspector-section">
                <h2 className="filter-heading" style={{ marginBottom: 4 }}>Effect size</h2>
                <div className="mono" style={{ fontWeight: 600, fontSize: 13.5 }}>
                  {detail.effect_label}: {detail.effect_text}
                </div>
                {detail.records_label ? <div className="muted small" style={{ marginTop: 4 }}>{detail.records_label}</div> : null}
              </div>
            ) : null}

            <div className="inspector-section">
              <h2 className="filter-heading" style={{ marginBottom: 6 }}>Caveats</h2>
              {detail.caveats.length ? (
                <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                  {detail.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              ) : (
                <div className="small muted">No specific caveats were recorded; general scope notes are in Plain view.</div>
              )}
              <div className="small mt" style={{ color: "var(--warn)" }}>
                {descriptive
                  ? "A data check describes the data; it does not explain it."
                  : "Observational association does not establish causation."}
              </div>
            </div>

            <div className="inspector-section">
              <div className="spread" style={{ marginBottom: 4 }}>
                <h2 className="filter-heading" style={{ margin: 0 }}>Ranking breakdown (#{detail.rank})</h2>
                <span className="mono small" style={{ fontWeight: 700, color: "var(--brand)" }}>
                  {fmtNum(detail.score, 3)}
                </span>
              </div>

              {scoreEntries.length >= 3 ? (
                <div style={{ margin: "4px -10px 6px" }}>
                  <RadarChart
                    height={196}
                    shape="circular"
                    divisions={4}
                    stripeColor={(idx) =>
                      idx % 2 === 1
                        ? tokens.isDark
                          ? "rgba(56, 189, 248, 0.05)"
                          : "rgba(21, 101, 112, 0.045)"
                        : "none"
                    }
                    hideLegend
                    margin={{ top: 18, right: 48, bottom: 18, left: 48 }}
                    radar={{
                      max: 1,
                      labelGap: 7,
                      metrics: scoreEntries.map(([k]) => ({
                        name: k[0].toUpperCase() + k.slice(1),
                        min: 0,
                        max: 1,
                      })),
                    }}
                    series={[
                      {
                        id: "rank-radar",
                        label: "Score component",
                        data: scoreEntries.map(([, v]) => Math.max(0, Math.min(1, Number(v)))),
                        color: tokens.primary,
                        fillArea: true,
                        valueFormatter: (v) => fmtNum(v, 2),
                      },
                    ]}
                    sx={{
                      [`& .${radarClasses.axisLabel}`]: {
                        fill: tokens.text,
                        fontSize: 12,
                        fontWeight: 600,
                      },
                      [`& .${radarClasses.gridDivider}, & .${radarClasses.gridRadial}`]: {
                        stroke: tokens.splitLine,
                      },
                      [`& .${radarClasses.seriesArea}`]: {
                        fillOpacity: 0.28,
                        strokeWidth: 2.3,
                      },
                    }}
                  />
                </div>
              ) : null}

              <table className="plain">
                <tbody>
                  {scoreEntries.map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ paddingLeft: 0 }}>{k}</td>
                      <td className="num" style={{ paddingRight: 0 }}>
                        <span className="bar" style={{ width: 44, marginRight: 8 }}>
                          <span style={{ width: `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%`, background: "var(--brand-2)" }} />
                        </span>
                        {fmtNum(v, 2)}
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td style={{ paddingLeft: 0 }}>
                      <b>Composite score</b>
                    </td>
                    <td className="num" style={{ paddingRight: 0 }}>
                      <b>{fmtNum(detail.score, 3)}</b>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div className="tiny muted mt">
                {Object.entries(
                  detail.score_weights ?? { evidence: 0.35, effect: 0.25, coverage: 0.15, robustness: 0.15, relevance: 0.1 },
                )
                  .map(([k, w]) => `${w.toFixed(2)}·${k}`)
                  .join(" + ")}
                ; p-values never enter ranking.
              </div>
            </div>

            {detail.related.length ? (
              <div className="inspector-section">
                <h2 className="filter-heading" style={{ marginBottom: 6 }}>Related findings</h2>
                <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                  {detail.related.map((r) => (
                    <li key={r.id} style={{ marginBottom: 4 }}>
                      <button className="link-btn" onClick={() => navigate(`${back}/${r.id}`)} style={{ textAlign: "left" }}>
                        {r.headline}
                      </button>{" "}
                      <span className="faint">({r.type})</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </aside>
        </div>
      </div>
    </>
  );
}
