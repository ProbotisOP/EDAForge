import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Chart } from "../components/Chart";
import { EvidenceBadge } from "../components/Feed";
import { Badge, ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import { fmtNum, fmtPct } from "../lib/format";
import type { FindingDetail } from "../lib/types";
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
  const { runId = "", findingId = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lens, setLens] = useState<Lens>("plain");
  const [showMethod, setShowMethod] = useState(false);

  const load = useCallback(() => {
    setError(null);
    setDetail(null);
    api.finding(project.id, runId, findingId).then(setDetail).catch(setError);
  }, [project.id, runId, findingId]);
  useEffect(load, [load]);

  const back = `/p/${project.id}/discover/runs/${runId}`;
  if (error) return <div className="content" style={{ paddingTop: 24 }}><ErrorBox error={error} onRetry={load} /></div>;
  if (!detail) return <Loading label="Loading finding…" />;
  const m = detail.method;
  const conf = m.confirmation as { status?: string; method?: string; p_value?: number; q_value?: number; n?: number; aggregation?: string };
  const descriptive = detail.evidence.basis === "descriptive";

  return (
    <>
      <div className="topbar" style={{ alignItems: "flex-start" }}>
        <div className="grow">
          <Link to={back} className="small">
            ← Insight Feed
          </Link>
          <div className="row-wrap" style={{ gap: 6, margin: "8px 0 6px" }}>
            <span className="rank">#{detail.rank}</span>
            <Badge tone="brand">{detail.family_label}</Badge>
            <EvidenceBadge item={detail} />
            {detail.records_label ? <Badge tone="outline">{detail.records_label}</Badge> : null}
            <span className="faint small mono">{detail.id}</span>
          </div>
          <h1 style={{ maxWidth: 980 }}>{detail.headline}</h1>
          <div className="muted" style={{ marginTop: 4 }}>
            {detail.variables.join(" · ")}
          </div>
        </div>
      </div>
      <div className="content">
        <div className="detail-layout">
          <div className="stack">
            <div className="card card-pad">
              <div className="spread" style={{ marginBottom: 12 }}>
                <div className="seg" role="tablist" aria-label="Explanation level">
                  {(["plain", "analyst", "scientist"] as Lens[]).map((l) => (
                    <button key={l} role="tab" aria-selected={lens === l} className={lens === l ? "active" : ""} onClick={() => setLens(l)}>
                      {LENS_LABEL[l]}
                    </button>
                  ))}
                </div>
                <span className="muted small">
                  {lens === "plain" ? "What it means" : lens === "analyst" ? "Effect sizes, intervals, groups" : "Method, assumptions, evidence"}
                </span>
              </div>
              {/* The HTML comes from the server's escaping Markdown converter: data cannot inject markup. */}
              <div className="lens" dangerouslySetInnerHTML={{ __html: detail.lenses[lens].html }} />
              <div className="tiny faint mt">
                Text produced from templates; every number in it is taken from the stored result of this run.
              </div>
            </div>
            {detail.charts.map((c, i) => (
              <div key={i} className="card card-pad">
                <Chart chart={c} />
                <div className="tiny muted mt">{c.alt_text}</div>
              </div>
            ))}
            <div className="card">
              <div className="card-head">
                <h3>Show the calculation</h3>
                <button className="btn btn-sm" onClick={() => setShowMethod(!showMethod)} aria-expanded={showMethod}>
                  {showMethod ? "Hide" : "Show method & evidence"}
                </button>
              </div>
              {showMethod ? (
                <div className="card-pad method stack">
                  {descriptive ? (
                    <div>
                      <h4>Rule</h4>
                      <p>{m.rule ?? detail.summary}</p>
                      <p className="muted small">Descriptive check computed exactly on every row: no hypothesis test, no p-value, no evidence grade.</p>
                    </div>
                  ) : (
                    <>
                      <table className="plain">
                        <tbody>
                          <tr><td>Analysis</td><td className="mono">{m.analyzer} v{m.analyzer_version}</td></tr>
                          <tr><td>Test</td><td className="mono">{m.test}</td></tr>
                          <tr><td>Statistic (search data)</td><td>{fmtNum(m.statistic ?? null, 4)}</td></tr>
                          <tr><td>p-value (search data)</td><td>{p(m.p_value)}</td></tr>
                          <tr><td>q-value (false-discovery adjusted, search data)</td><td>{p(m.q_value)}</td></tr>
                          <tr><td>Confirmation</td><td>{conf.method}{conf.aggregation ? ` — ${conf.aggregation}` : ""}: p = {p(conf.p_value)}, q = {p(conf.q_value)}, n = {conf.n ?? "—"} → <b>{conf.status}</b></td></tr>
                          {m.effect ? (
                            <tr><td>Effect</td><td>{m.effect.measure} = {fmtNum(m.effect.estimate)} [{fmtNum(m.effect.ci_low ?? null)}, {fmtNum(m.effect.ci_high ?? null)}] ({Math.round(100 * m.effect.ci_level)}%, {m.effect.ci_method ?? "—"}; computed on {m.effect.split ?? "—"} data)</td></tr>
                          ) : null}
                          {m.secondary_effects.map((e, i) => (
                            <tr key={i}><td>Also</td><td>{e.measure} = {fmtNum(e.estimate)} [{fmtNum(e.ci_low ?? null)}, {fmtNum(e.ci_high ?? null)}] ({e.ci_method})</td></tr>
                          ))}
                          <tr><td>Rows used</td><td>{m.n.toLocaleString()}</td></tr>
                          <tr><td>Robustness</td><td>stability {m.stability !== undefined && m.stability !== null ? fmtPct(m.stability, 0) : "not measured"}; {m.specs_total ? `${m.specs_consistent ?? 0} of ${m.specs_total} specifications agree` : "specification curve not run"}</td></tr>
                          <tr><td>Causal rung</td><td>{m.rung} — {m.rung === "R1" ? "an association, not a causal claim" : m.rung}</td></tr>
                        </tbody>
                      </table>
                      <div>
                        <h4>Assumptions</h4>
                        {m.assumptions.length ? (
                          m.assumptions.map((a, i) => (
                            <div key={i} className="assume">
                              <Badge tone={a.status === "pass" ? "ok" : a.status === "fail" ? "bad" : a.status === "warn" ? "warn" : "gray"}>{a.status}</Badge>
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
                        <h4>Hypothesis ledger entries</h4>
                        <div className="table-wrap">
                          <table className="data">
                            <thead>
                              <tr><th>ID</th><th>Hypothesis</th><th>Test</th><th>Split</th><th className="num">Statistic</th><th className="num">p</th><th className="num">n</th><th className="num">Resamples</th><th className="num">Seed</th></tr>
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
                                  <td className="num">{e.n_resamples === null || e.n_resamples === undefined ? "—" : String(e.n_resamples)}</td>
                                  <td className="num mono">{e.seed === null || e.seed === undefined ? "—" : String(e.seed)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                      <div>
                        <h4>Parameters</h4>
                        <pre>{JSON.stringify(m.params, null, 2)}</pre>
                      </div>
                      <div>
                        <h4>Reproducibility</h4>
                        <pre>{JSON.stringify(detail.provenance, null, 2)}</pre>
                        <p className="muted small">
                          Running the same settings on files with the same fingerprints reproduces this result: the seed fixes every
                          split, permutation and bootstrap.
                        </p>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </div>
          <div className="stack">
            <div className="card card-pad">
              <div className="row" style={{ gap: 12, marginBottom: 8 }}>
                <div className={`grade g-${descriptive ? "F" : detail.evidence.grade}`}>{descriptive ? "fact" : detail.evidence.grade}</div>
                <div>
                  <div style={{ fontWeight: 700 }}>{descriptive ? "Exact data check" : `${detail.evidence.label[0].toUpperCase()}${detail.evidence.label.slice(1)} evidence`}</div>
                  <div className="muted small">{detail.evidence.wording}</div>
                </div>
              </div>
              <div className="small">{detail.evidence.confirmation}</div>
              {!descriptive && m.grade_reasons.length ? (
                <details style={{ marginTop: 8 }}>
                  <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>Why not a higher grade?</summary>
                  <ul className="small" style={{ paddingLeft: 18 }}>
                    {m.grade_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
            {detail.effect_text ? (
              <div className="card card-pad">
                <h4 style={{ marginBottom: 6 }}>Size of the effect</h4>
                <div style={{ fontWeight: 650 }}>
                  {detail.effect_label}: {detail.effect_text}
                </div>
                {detail.records_label ? <div className="muted small">{detail.records_label}</div> : null}
              </div>
            ) : null}
            <div className="card card-pad">
              <h4 style={{ marginBottom: 6 }}>Caveats</h4>
              {detail.caveats.length ? (
                <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                  {detail.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              ) : (
                <div className="small muted">No specific caveats were recorded; the general ones are in the Plain view.</div>
              )}
              <div className="small mt" style={{ color: "var(--warn)" }}>
                {descriptive ? "A data check describes the data; it does not explain it." : "An association in data does not show that one thing is the reason for another."}
              </div>
            </div>
            <div className="card card-pad">
              <h4 style={{ marginBottom: 6 }}>Why it is ranked #{detail.rank}</h4>
              <table className="plain">
                <tbody>
                  {Object.entries(detail.score_components).map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="num">{fmtNum(v, 2)}</td></tr>
                  ))}
                  <tr><td><b>score</b></td><td className="num"><b>{fmtNum(detail.score, 3)}</b></td></tr>
                </tbody>
              </table>
              <div className="tiny muted">
                {Object.entries(detail.score_weights ?? { evidence: 0.35, effect: 0.25, coverage: 0.15, robustness: 0.15, relevance: 0.1 })
                  .map(([k, w]) => `${w.toFixed(2)}·${k}`)
                  .join(" + ")}
                ; p-values are not used for ranking.
              </div>
            </div>
            {detail.related.length ? (
              <div className="card card-pad">
                <h4 style={{ marginBottom: 6 }}>Related findings</h4>
                <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                  {detail.related.map((r) => (
                    <li key={r.id}>
                      <button className="link-btn" onClick={() => navigate(`${back}/${r.id}`)} style={{ textAlign: "left" }}>
                        {r.headline}
                      </button>{" "}
                      <span className="faint">({r.type})</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}
