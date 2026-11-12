import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { InsightFeed } from "../components/Feed";
import { Badge, Empty, ErrorBox, HealthDot, Loading, Notice, Spinner } from "../components/ui";
import { api, subscribeRun } from "../lib/api";
import { fmtDate, fmtInt, ROLE_LABEL } from "../lib/format";
import type { ColumnInfo, Dataset, Intent, PlanItem, RunEvent, RunResultView, RunSettings, ScopePlan } from "../lib/types";
import { useProject } from "./ProjectLayout";

const INTENTS: { id: Intent; title: string; text: string }[] = [
  { id: "auto", title: "Find hidden patterns", text: "Every applicable analysis, no outcome needed" },
  { id: "target", title: "Explain an outcome", text: "What goes with one column you care about" },
  { id: "compare", title: "Compare files or groups", text: "How sources or groups differ" },
  { id: "anomalies", title: "Investigate unusual records", text: "Outliers and changes over time" },
  { id: "health", title: "Check data health", text: "Quality checks and leakage only" },
];

function defaultDataset(datasets: Dataset[], wanted: string | null): Dataset | undefined {
  if (wanted) {
    const hit = datasets.find((d) => d.id === wanted);
    if (hit) return hit;
  }
  const combined = datasets.filter((d) => d.kind === "combined").sort((a, b) => b.created_at.localeCompare(a.created_at));
  return combined[0] ?? [...datasets].sort((a, b) => b.n_rows - a.n_rows)[0];
}

export function DiscoverPage() {
  const { project } = useProject();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const datasets = project.datasets;
  const [datasetId, setDatasetId] = useState<string>(() => defaultDataset(datasets, params.get("dataset"))?.id ?? "");
  const dataset = datasets.find((d) => d.id === datasetId);
  const files = datasets.filter((d) => d.kind === "file");
  const [mode, setMode] = useState<"one" | "several" | "all">("one");
  const [picked, setPicked] = useState<string[]>([]);
  const [scopePlan, setScopePlan] = useState<ScopePlan | null>(null);
  const [scopeError, setScopeError] = useState<unknown>(null);
  const [ack, setAck] = useState(false);
  const scope = mode === "all" ? files.map((d) => d.id) : mode === "several" ? picked : [];
  const scopeKey = scope.join(",");
  const [intent, setIntent] = useState<Intent>("auto");
  const [target, setTarget] = useState<string>("");
  const [timeColumn, setTimeColumn] = useState<string>("");
  const [groupColumn, setGroupColumn] = useState<string>("");
  const [minGroup, setMinGroup] = useState<number>(10);
  const [focus, setFocus] = useState<string[]>([]);
  const [exclude, setExclude] = useState<string[]>([]);
  const [showOptions, setShowOptions] = useState(false);
  const [plan, setPlan] = useState<{ plan: PlanItem[]; notes: string[] } | null>(null);
  const [planError, setPlanError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);

  useEffect(() => {
    setTarget("");
    setTimeColumn("");
    setGroupColumn("");
    setFocus([]);
    setExclude([]);
    setAck(false);
  }, [datasetId, scopeKey]);

  useEffect(() => {
    setScopePlan(null);
    setScopeError(null);
    if (scope.length < 2) return;
    let cancelled = false;
    api
      .scopePlan(project.id, scope)
      .then((p) => !cancelled && setScopePlan(p))
      .catch((e) => !cancelled && setScopeError(e));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, scopeKey]);
  const multi = scope.length >= 2;

  const settings: RunSettings = useMemo(
    () => ({
      dataset_id: multi ? "" : datasetId,
      scope: multi ? scope : [],
      acknowledged: ack,
      intent,
      target: target || null,
      time_column: timeColumn || null,
      group_column: groupColumn || null,
      min_group_size: Math.max(10, Math.round(minGroup) || 10),
      focus,
      exclude,
    }),
    [datasetId, multi, scopeKey, ack, intent, target, timeColumn, groupColumn, minGroup, focus, exclude],
  );

  useEffect(() => {
    if (!datasetId && !multi) return;
    if (mode !== "one" && !multi) {
      setPlan(null);
      return;
    }
    let cancelled = false;
    setPlanError(null);
    const t = setTimeout(() => {
      api
        .planRun(project.id, settings)
        .then((p) => !cancelled && setPlan(p))
        .catch((e) => !cancelled && (setPlan(null), setPlanError(e)));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [project.id, settings, datasetId, multi, mode]);

  if (!datasets.length) {
    return (
      <>
        <Header />
        <div className="content">
          <div className="card">
            <Empty icon="📂" title="Nothing to analyze yet">
              Upload files on the <Link to={`/p/${project.id}/data`}>Data</Link> page first.
            </Empty>
          </div>
        </div>
      </>
    );
  }

  const cols: ColumnInfo[] = multi ? ((scopePlan?.columns ?? []) as ColumnInfo[]) : dataset?.columns ?? [];
  const usable = cols.filter((c) => !c.pii && ["numeric", "categorical", "boolean"].includes(c.role));
  const dates = cols.filter((c) => c.role === "datetime");
  const groups = cols.filter((c) => ["categorical", "boolean"].includes(c.role));
  const runnable = plan && !planError && plan.plan.some((p) => p.status === "run") && (!multi || (scopePlan && (!scopePlan.requires_ack || ack)));
  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const { run_id } = await api.startRun(project.id, settings);
      navigate(`/p/${project.id}/discover/runs/${run_id}`);
    } catch (e) {
      setStartError(e);
    } finally {
      setStarting(false);
    }
  };
  const cycle = (name: string) => {
    if (focus.includes(name)) {
      setFocus(focus.filter((n) => n !== name));
      setExclude([...exclude, name]);
    } else if (exclude.includes(name)) {
      setExclude(exclude.filter((n) => n !== name));
    } else {
      setFocus([...focus, name]);
    }
  };
  const runs = [...project.runs].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <>
      <Header />
      <div className="content stack">
        <div className="card card-pad stack">
          <div className="setup">
            <div className="field" style={{ gridColumn: "span 2" }}>
              <span>Where to look</span>
              <div className="seg scope-seg" role="radiogroup" aria-label="Scope">
                {([["one", "One table"], ["several", "Several files"], ["all", `All files (${files.length})`]] as const).map(([m, label]) => (
                  <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "active" : ""} disabled={m !== "one" && files.length < 2} onClick={() => setMode(m)}>
                    {label}
                  </button>
                ))}
              </div>
              {mode === "one" ? (
                <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} aria-label="Table to analyze">
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.kind === "combined" ? "⋈ " : ""}
                      {d.name} — {fmtInt(d.n_rows)} rows
                    </option>
                  ))}
                </select>
              ) : mode === "several" ? (
                <div className="chips" aria-label="Files to connect">
                  {files.map((d) => (
                    <button key={d.id} className={picked.includes(d.id) ? "chip on" : "chip"} onClick={() => setPicked(picked.includes(d.id) ? picked.filter((x) => x !== d.id) : [...picked, d.id])}>
                      <HealthDot health={d.health} size={9} /> {d.name}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <label className="field" style={{ gridColumn: "span 2" }}>
              Outcome to explain <span className="hint">{intent === "target" ? "required" : "optional — focuses the search"}</span>
              <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Outcome column">
                <option value="">— none —</option>
                {usable.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({ROLE_LABEL[c.role]})
                  </option>
                ))}
              </select>
            </label>
          </div>
          {multi || (mode === "several" && picked.length < 2) ? (
            <ScopePanel plan={scopePlan} error={scopeError} ack={ack} setAck={setAck} needMore={mode === "several" && picked.length < 2} />
          ) : null}
          <div className="intent-grid" role="radiogroup" aria-label="Analysis intent">
            {INTENTS.map((i) => (
              <button key={i.id} className={intent === i.id ? "intent active" : "intent"} onClick={() => setIntent(i.id)} role="radio" aria-checked={intent === i.id}>
                <strong>{i.title}</strong>
                <span>{i.text}</span>
              </button>
            ))}
          </div>
          <div>
            <button className="link-btn small" onClick={() => setShowOptions(!showOptions)}>
              {showOptions ? "▾ Hide options" : "▸ Options: time column, comparison, focus and exclusions"}
            </button>
          </div>
          {showOptions ? (
            <div className="stack">
              <div className="setup">
                <label className="field">
                  Date column for time patterns
                  <select value={timeColumn} onChange={(e) => setTimeColumn(e.target.value)}>
                    <option value="">{dates.length ? "automatic (first date column)" : "— no date columns —"}</option>
                    {dates.map((c) => (
                      <option key={c.name}>{c.name}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Compare groups by
                  <select value={groupColumn} onChange={(e) => setGroupColumn(e.target.value)}>
                    <option value="">{dataset?.kind === "combined" ? "source files (if appended)" : "— none —"}</option>
                    {groups.map((c) => (
                      <option key={c.name}>{c.name}</option>
                    ))}
                  </select>
                </label>
                <label className="field" title="Labels with fewer rows are combined into '(other)'. The minimum is 10: smaller groups give effect sizes that cannot be trusted.">
                  Smallest group (rows)
                  <input type="number" min={10} max={1000} step={1} value={minGroup} aria-label="Smallest group size"
                    onChange={(e) => setMinGroup(Number(e.target.value))} onBlur={() => setMinGroup((v) => Math.min(1000, Math.max(10, Math.round(v) || 10)))} />
                </label>
              </div>
              <div>
                <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
                  Columns <span className="muted" style={{ fontWeight: 400 }}>— click to focus on a column, again to exclude it, again to reset</span>
                </div>
                <div className="chips">
                  {cols.map((c) => (
                    <button
                      key={c.name}
                      className={focus.includes(c.name) ? "chip on" : exclude.includes(c.name) ? "chip off" : "chip"}
                      onClick={() => cycle(c.name)}
                      title={c.role_reason}
                    >
                      {c.name}
                      <span className="faint tiny">{ROLE_LABEL[c.role]}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
          <div className="hr" />
          <div className="spread" style={{ alignItems: "flex-start" }}>
            <div className="grow">
              <h3 style={{ marginBottom: 6 }}>What will run</h3>
              {planError ? <Notice tone="warn">{planError instanceof Error ? planError.message : String(planError)}</Notice> : null}
              {!plan && !planError ? <Spinner label="Checking which analyses apply…" /> : null}
              {plan ? (
                <table className="plain">
                  <tbody>
                    {plan.plan.map((p) => (
                      <tr key={p.analyzer} style={p.status === "skipped" ? { color: "var(--faint)" } : undefined}>
                        <td style={{ width: 22 }}>{p.status === "run" ? "✓" : "–"}</td>
                        <td style={{ fontWeight: 600 }}>{p.label}</td>
                        <td>{p.reason}</td>
                        <td className="small muted">{p.status === "run" ? p.method : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              {plan?.notes.length ? (
                <ul className="small muted" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {plan.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className="stack" style={{ alignItems: "flex-end", minWidth: 230 }}>
              <button className="btn btn-primary btn-hero" disabled={!runnable || starting} onClick={start}>
                {starting ? "Starting…" : "Find hidden patterns"}
              </button>
              <span className="tiny muted" style={{ textAlign: "right", maxWidth: 230 }}>
                Findings are tested with false-discovery control and checked on data the search does not see.
              </span>
            </div>
          </div>
          {startError ? <ErrorBox error={startError} /> : null}
        </div>
        {runs.length ? (
          <div className="card">
            <div className="card-head">
              <h3>Previous runs</h3>
            </div>
            <table className="plain">
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate(`/p/${project.id}/discover/runs/${r.id}`)}>
                    <td style={{ fontWeight: 600 }}>{String(r.summary.dataset ?? r.dataset_id)}</td>
                    <td>{INTENTS.find((i) => i.id === r.settings.intent)?.title ?? r.settings.intent}{r.settings.target ? ` · outcome ${r.settings.target}` : ""}</td>
                    <td>
                      <Badge tone={r.status === "completed" ? "ok" : r.status === "failed" ? "bad" : "gray"}>{r.status}</Badge>
                    </td>
                    <td className="muted">{r.status === "completed" ? `${r.summary.n_findings ?? 0} findings · ${r.summary.n_facts ?? 0} facts` : ""}</td>
                    <td className="muted small">{fmtDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  );
}

function ScopePanel({ plan, error, ack, setAck, needMore }: { plan: ScopePlan | null; error: unknown; ack: boolean; setAck: (v: boolean) => void; needMore: boolean }) {
  if (needMore) return <Notice tone="info">Choose two or more files to see how they connect.</Notice>;
  if (error) return <ErrorBox error={error} />;
  if (!plan) return <Spinner label="Working out how these files connect…" />;
  return (
    <div className="scope-panel">
      <div className="spread">
        <h3>How these files connect</h3>
        <span className="muted small">{plan.steps.length ? `→ one table of ${fmtInt(plan.result_rows)} rows` : "no connection found"}</span>
      </div>
      <ol className="scope-steps">
        {plan.steps.map((s, i) => (
          <li key={i}>
            <div className="row-wrap">
              <Badge tone={s.kind === "append" ? "brand" : "info"}>{s.kind === "append" ? "Stack" : "Join"}</Badge>
              <strong>{s.left_name}</strong>
              <span className="muted">{s.kind === "append" ? "＋" : "⟶"}</span>
              <strong>{s.right_name}</strong>
              {s.kind !== "append" ? <span className="muted small">on {s.spec.keys.map((k) => `${k.left} = ${k.right}`).join(", ")}</span> : null}
            </div>
            <div className="small muted">
              {fmtInt(s.n_left)} + {fmtInt(s.n_right)} rows → {fmtInt(s.n_result)} rows
              {s.kind !== "append" ? ` (${s.row_multiplication.toFixed(2)}× the base)` : ""} · confidence {Math.round(s.confidence * 100)}%
            </div>
            {s.warnings.filter((w) => w.severity !== "info").map((w, j) => (
              <div key={j} className={`small ${w.severity === "critical" ? "txt-bad" : "txt-warn"}`}>⚠ {w.message}</div>
            ))}
          </li>
        ))}
      </ol>
      {plan.unconnected.map((u) => (
        <Notice key={u.table} tone="warn">
          <b>{u.table}</b> is left out: {u.reason}
        </Notice>
      ))}
      {plan.requires_ack ? (
        <label className="row small" style={{ alignItems: "flex-start", gap: 8 }}>
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 3 }} aria-label="Acknowledge connection warnings" />
          <span>I have reviewed this: {plan.steps.flatMap((s) => s.ack_reasons).join("; ")}.</span>
        </label>
      ) : null}
      <div className="tiny muted">The connected tables are saved on the Connect page, where you can inspect, change or remove them.</div>
    </div>
  );
}

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="topbar">
      <div>
        <h1>Discover</h1>
        <div className="sub">Search for relationships, segments, reversals, changes and mismatches — and check every one of them.</div>
      </div>
      {action}
    </div>
  );
}

interface Progress {
  label: string;
  done: number;
  total: number;
  pass: string;
}

export function RunPage() {
  const { project, refresh } = useProject();
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<RunResultView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [cancelling, setCancelling] = useState(false);
  const started = useRef(Date.now());

  const load = useCallback(() => {
    api.run(project.id, runId).then(setView).catch(setError);
  }, [project.id, runId]);
  useEffect(() => {
    setView(null);
    setEvents([]);
    setProgress({});
    started.current = Date.now();
    load();
  }, [load]);

  const running = view && (view.run.status === "queued" || view.run.status === "running");
  useEffect(() => {
    if (!running) return;
    const close = subscribeRun(
      project.id,
      runId,
      (e) => {
        setEvents((list) => [...list.slice(-199), e]);
        if (e.kind === "progress" && typeof e.data.analyzer === "string") {
          const d = e.data as { analyzer: string; label: string; done: number; total: number; pass: string };
          setProgress((p) => ({ ...p, [d.analyzer]: { label: d.label, done: d.done, total: d.total, pass: d.pass } }));
        }
      },
      () => {
        load();
        void refresh();
      },
    );
    return close;
  }, [running, project.id, runId, load, refresh]);

  if (error) return <div className="content" style={{ paddingTop: 24 }}><ErrorBox error={error} onRetry={load} /></div>;
  if (!view) return <Loading label="Loading run…" />;
  const run = view.run;

  const headerAction = (
    <div className="row">
      <button className="btn" onClick={() => navigate(`/p/${project.id}/discover`)}>
        New analysis
      </button>
      {run.status === "completed" ? (
        <button className="btn btn-universe" onClick={() => navigate(`/p/${project.id}/discover/runs/${run.id}/universe`)}>
          Enter the Data Universe ✦
        </button>
      ) : null}
      {run.status === "completed" ? (
        <button className="btn btn-primary" onClick={() => navigate(`/p/${project.id}/report/${run.id}`)}>
          Report & export →
        </button>
      ) : null}
    </div>
  );

  if (running) {
    const candidates = events.filter((e) => e.kind === "candidate").length;
    const findings = events.filter((e) => e.kind === "finding").length;
    const stage = events.some((e) => e.kind === "pipeline_finished")
      ? "Building the Insight Feed"
      : events.some((e) => e.message === "screening finished" || e.stage === "confirmation" || e.stage === "cross_fit")
        ? "Checking candidates on data the search did not see"
        : events.some((e) => e.kind === "pipeline_started")
          ? "Screening"
          : "Preparing";
    return (
      <>
        <Header action={headerAction} />
        <div className="content stack">
          <div className="card card-pad stack">
            <div className="spread">
              <div className="row">
                <Spinner large />
                <div>
                  <h2>{stage}…</h2>
                  <div className="muted small">
                    {String(view.dataset.name)} · started {fmtDate(run.created_at)} · {candidates} candidates so far{findings ? ` · ${findings} findings graded` : ""}
                  </div>
                </div>
              </div>
              <button
                className="btn btn-danger"
                disabled={cancelling}
                onClick={async () => {
                  setCancelling(true);
                  try {
                    await api.cancelRun(project.id, runId);
                  } catch (e) {
                    setError(e);
                  }
                }}
              >
                {cancelling ? "Cancelling…" : "Cancel"}
              </button>
            </div>
            <div className="stage-list">
              {view.plan.filter((p) => p.status === "run" && !p.analyzer.startsWith("describe.")).map((p) => {
                const pr = progress[p.analyzer];
                const share = pr && pr.total ? pr.done / pr.total : 0;
                return (
                  <div key={p.analyzer} className={pr ? (share >= 1 ? "stage done" : "stage active") : "stage wait"}>
                    <span className="dot">{pr ? (share >= 1 ? "✓" : "…") : "·"}</span>
                    <span style={{ width: 300 }}>{p.label}</span>
                    {pr ? (
                      <>
                        <div className="progress" style={{ width: 200 }}>
                          <div style={{ width: `${Math.round(100 * share)}%` }} />
                        </div>
                        <span className="muted small">
                          {pr.done} of {pr.total} · {pr.pass.replace("split", "half-split ").replace("/select", "")}
                        </span>
                      </>
                    ) : (
                      <span className="faint small">waiting</span>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="log" aria-live="polite">
              {events.filter((e) => e.kind !== "progress").slice(-40).map((e) => (
                <div key={e.seq} className={e.kind === "warning" ? "warn" : ""}>
                  {e.kind === "candidate" ? "candidate · " : e.kind === "finding" ? "graded · " : e.kind === "warning" ? "note · " : ""}
                  {e.message}
                </div>
              ))}
            </div>
            <div className="muted small">
              Progress counts are real: each line is reported by the engine as it finishes a test. Candidates are not results until they
              are checked again and graded.
            </div>
          </div>
        </div>
      </>
    );
  }

  if (run.status === "failed" || run.status === "cancelled") {
    return (
      <>
        <Header action={headerAction} />
        <div className="content">
          <Notice tone={run.status === "failed" ? "bad" : "info"}>
            {run.status === "failed" ? `This run failed: ${run.error ?? "unknown error"}` : "This run was cancelled before it finished; no results were kept."}
          </Notice>
        </div>
      </>
    );
  }

  const split = view.split as { mode?: string; n_exploration?: number; n_confirmation?: number; n_total?: number; strategy?: string };
  const leaders = view.feed.filter((i) => !i.merged_into);
  const inferential = leaders.filter((i) => i.evidence.basis === "inferential" && i.evidence.grade !== "E");
  const confirmed = leaders.filter((i) => i.evidence.confirmation.startsWith("confirmed"));
  const tested = view.searched.reduce((s, x) => s + x.tested, 0);
  return (
    <>
      <Header action={headerAction} />
      <div className="content stack">
        <div className="card card-pad">
          <div className="grid-4">
            <div className="stat">
              <div className="v">{inferential.length}</div>
              <div className="l">findings (grade A–D)</div>
            </div>
            <div className="stat">
              <div className="v">{confirmed.length}</div>
              <div className="l">confirmed on held-out data</div>
            </div>
            <div className="stat">
              <div className="v">{leaders.length - inferential.length - leaders.filter((i) => i.evidence.grade === "E").length}</div>
              <div className="l">data facts (quality, unusual records)</div>
            </div>
            <div className="stat">
              <div className="v">{fmtInt(tested)}</div>
              <div className="l">hypotheses tested, with false-discovery control</div>
            </div>
          </div>
          <div className="muted small mt">
            {String(view.dataset.name)} ·{" "}
            {split.mode === "holdout"
              ? `searched ${fmtInt(split.n_exploration)} rows, then re-tested every candidate on ${fmtInt(split.n_confirmation)} sealed rows`
              : split.mode === "cross_fit"
                ? `cross-fitting: candidates re-tested on random halves (${split.strategy})`
                : "small sample: no rows could be held out, so every finding is exploratory"}
            {run.settings.target ? ` · outcome: ${run.settings.target}` : ""} · {fmtDate(run.created_at)}
          </div>
        </div>
        {view.null_results.length ? (
          <Notice tone="info">
            <b>Searched without a reportable result:</b> {view.null_results.map((n) => `${n.label} (${n.message.replace("Tested ", "").replace(" hypotheses; none held up after false-discovery control.", " tested")})`).join("; ")}. Finding nothing
            does not show that nothing is there.
          </Notice>
        ) : null}
        {view.notes.length || view.warnings.length ? (
          <details className="issue">
            <summary>
              <span className="sev-dot sev-info" />
              <div className="grow">
                <strong>How the data was handled in this run</strong>
                <div className="muted small">{view.notes.length + view.warnings.length} notes: columns left out, labels combined, sampling, checks</div>
              </div>
            </summary>
            <div className="body">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {[...view.notes, ...view.warnings].map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </div>
          </details>
        ) : null}
        {view.feed.length ? (
          <InsightFeed items={view.feed} basePath={`/p/${project.id}/discover/runs/${run.id}`} />
        ) : (
          <div className="card">
            <Empty icon="∅" title="No findings">
              Nothing passed the checks. That is a result too: with this data and these settings, no pattern was strong enough to be
              reported without risking a false alarm.
            </Empty>
          </div>
        )}
      </div>
    </>
  );
}
