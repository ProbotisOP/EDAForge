import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, Modal, Notice, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtCell, fmtInt, fmtPct } from "../lib/format";
import type { Dataset, LinkPreview, LinkSpec, LinkSuggestion } from "../lib/types";
import { useProject } from "./ProjectLayout";

const KIND_LABEL: Record<string, string> = {
  join: "Join",
  append: "Append (stack rows)",
  time_aligned: "Time-aligned join",
  unrelated: "No relationship found",
};
const CARD_LABEL: Record<string, string> = {
  "1:1": "one-to-one",
  "m:1": "many-to-one",
  "1:m": "one-to-many",
  "m:m": "many-to-many",
};

export function ConnectPage() {
  const { project, setProject } = useProject();
  const navigate = useNavigate();
  const [suggestions, setSuggestions] = useState<LinkSuggestion[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<LinkSpec | null>(null);
  const [created, setCreated] = useState<Dataset | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const names = useMemo(() => new Map(project.datasets.map((d) => [d.id, d.name])), [project.datasets]);
  const load = () => {
    setError(null);
    setSuggestions(null);
    api.suggestions(project.id).then(setSuggestions).catch(setError);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [project.id, project.datasets.length, project.links.length]);

  const choose = (s: LinkSuggestion) => {
    setSelected(s.id);
    setCreated(null);
    setDraft(s.spec ? { ...s.spec, keys: s.spec.keys.map((k) => ({ ...k })) } : null);
  };

  const confirmed = project.links.filter((l) => l.status === "confirmed");
  const visible = (suggestions ?? []).filter((s) => s.status !== "confirmed");

  if (project.datasets.length < 2) {
    return (
      <>
        <Header />
        <div className="content">
          <div className="card">
            <Empty icon="🔗" title="Connecting needs at least two tables">
              Upload another related file on the <Link to={`/p/${project.id}/data`}>Data</Link> page — for example orders
              and customers — or go straight to <Link to={`/p/${project.id}/discover`}>Discover</Link> to analyze one file.
            </Empty>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        action={
          <button
            className="btn"
            onClick={() => {
              setSelected("custom");
              setCreated(null);
              const [a, b] = project.datasets;
              setDraft({ kind: "join", left: a.id, right: b.id, keys: [{ left: "", right: "" }], how: "left", right_mode: "lookup", name: null });
            }}
          >
            + Define a link yourself
          </button>
        }
      />
      <div className="content">
        {error ? <ErrorBox error={error} onRetry={load} /> : null}
        {created ? (
          <Notice tone="ok">
            Created <b>{created.name}</b> with {fmtInt(created.n_rows)} rows and {created.n_cols} columns. Every row keeps
            the row numbers of its source records.{" "}
            <Link to={`/p/${project.id}/data/${created.id}`}>Inspect it</Link> ·{" "}
            <Link to={`/p/${project.id}/discover?dataset=${created.id}`}>Find patterns in it →</Link>
          </Notice>
        ) : null}
        <div className="grid-2 mt" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.15fr)", alignItems: "start" }}>
          <div>
            <h3 style={{ marginBottom: 10 }}>Suggested relationships</h3>
            {suggestions === null && !error ? <Loading label="Comparing columns across tables…" /> : null}
            {suggestions && visible.length === 0 ? (
              <div className="card">
                <Empty icon="✓" title="Nothing left to review">
                  Every suggestion was confirmed or rejected. Define a link yourself if something is missing.
                </Empty>
              </div>
            ) : null}
            {visible.map((s) => (
              <SuggestionCard
                key={s.id}
                s={s}
                names={names}
                selected={selected === s.id}
                onReview={() => choose(s)}
                onReject={async () => {
                  if (!s.spec) return;
                  try {
                    setProject(await api.rejectLink(project.id, s.spec));
                  } catch (e) {
                    setError(e);
                  }
                }}
                onUndo={async () => {
                  if (!s.link_id) return;
                  try {
                    setProject(await api.deleteLink(project.id, s.link_id));
                  } catch (e) {
                    setError(e);
                  }
                }}
              />
            ))}
            {confirmed.length ? (
              <div className="card mt-lg">
                <div className="card-head">
                  <h3>Confirmed links</h3>
                </div>
                <table className="plain">
                  <tbody>
                    {confirmed.map((l) => {
                      const ds = project.datasets.find((d) => d.id === l.result_dataset_id);
                      return (
                        <tr key={l.id}>
                          <td>
                            <div style={{ fontWeight: 600 }}>{ds?.name ?? "(removed)"}</div>
                            <div className="muted small">
                              {KIND_LABEL[l.kind]} · {l.spec.keys.map((k) => `${k.left} = ${k.right}`).join(", ") || "same columns"}
                              {ds ? ` · ${fmtInt(ds.n_rows)} rows` : ""}
                            </div>
                          </td>
                          <td className="right nowrap">
                            {ds ? (
                              <button className="btn btn-sm" onClick={() => navigate(`/p/${project.id}/data/${ds.id}`)}>
                                Inspect
                              </button>
                            ) : null}{" "}
                            <button className="btn btn-sm btn-danger" onClick={() => setRemoving(l.id)}>
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
          <div style={{ position: "sticky", top: 12 }}>
            {draft ? (
              <LinkEditor
                key={selected ?? "none"}
                initial={draft}
                datasets={project.datasets}
                onCreated={(ds) => {
                  setCreated(ds);
                  setDraft(null);
                  setSelected(null);
                }}
              />
            ) : (
              <div className="card">
                <Empty icon="👈" title="Review a suggestion">
                  Pick a suggested relationship to see exactly what the combined table would contain before you confirm
                  it. Nothing is joined until you do.
                </Empty>
              </div>
            )}
          </div>
        </div>
      </div>
      {removing ? (
        <Modal
          title="Remove this link?"
          onClose={() => setRemoving(null)}
          actions={
            <>
              <button className="btn" onClick={() => setRemoving(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={async () => {
                  try {
                    setProject(await api.deleteLink(project.id, removing));
                    setRemoving(null);
                  } catch (e) {
                    setError(e);
                  }
                }}
              >
                Remove link
              </button>
            </>
          }
        >
          <p>The combined table built by this link, and any table built on top of it, is deleted. Source files stay.</p>
        </Modal>
      ) : null}
    </>
  );
}

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="topbar">
      <div>
        <h1>Connect files</h1>
        <div className="sub">
          EDAForge checks which columns can link your tables. Nothing is combined until you review and confirm it.
        </div>
      </div>
      {action}
    </div>
  );
}

function SuggestionCard({
  s,
  names,
  selected,
  onReview,
  onReject,
  onUndo,
}: {
  s: LinkSuggestion;
  names: Map<string, string>;
  selected: boolean;
  onReview: () => void;
  onReject: () => void;
  onUndo: () => void;
}) {
  const rejected = s.status === "rejected";
  return (
    <div className={selected ? "suggestion selected" : "suggestion"} style={rejected ? { opacity: 0.6 } : undefined}>
      <div className="card-pad">
        <div className="spread" style={{ alignItems: "flex-start" }}>
          <div className="row-wrap">
            <Badge tone={s.kind === "unrelated" ? "gray" : s.kind === "append" ? "info" : "brand"}>{KIND_LABEL[s.kind]}</Badge>
            {s.cardinality ? <Badge tone={s.cardinality === "m:m" ? "bad" : "outline"}>{CARD_LABEL[s.cardinality]}</Badge> : null}
            {rejected ? <Badge tone="gray">rejected</Badge> : null}
          </div>
          {s.kind !== "unrelated" ? (
            <span className="confidence small muted" title="How strongly the evidence below supports the link">
              confidence
              <span className="meter">
                <span style={{ width: `${Math.round(100 * s.confidence)}%` }} />
              </span>
              {Math.round(100 * s.confidence)}%
            </span>
          ) : null}
        </div>
        <div className="link-diagram mt">
          <span className="link-node">{names.get(s.left) ?? s.left}</span>
          <span className="link-arrow">{s.kind === "append" ? "＋" : s.kind === "unrelated" ? "≠" : "⟶"}</span>
          <span className="link-node">{names.get(s.right) ?? s.right}</span>
        </div>
        {s.keys.length ? (
          <div className="small mt">
            on{" "}
            {s.keys.map((k, i) => (
              <span key={i}>
                {i ? " and " : ""}
                <code>{k.left}</code> = <code>{k.right}</code>
              </span>
            ))}
          </div>
        ) : null}
        <ul className="small" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {s.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
          {s.warnings.map((w, i) => (
            <li key={`w${i}`} style={{ color: "var(--warn)" }}>
              {w}
            </li>
          ))}
        </ul>
        {s.kind !== "unrelated" ? (
          <div className="row mt">
            {rejected ? (
              <button className="btn btn-sm" onClick={onUndo}>
                Undo rejection
              </button>
            ) : (
              <>
                <button className="btn btn-sm btn-primary" onClick={onReview}>
                  Review & preview
                </button>
                <button className="btn btn-sm" onClick={onReject}>
                  Reject
                </button>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function LinkEditor({
  initial,
  datasets,
  onCreated,
}: {
  initial: LinkSpec;
  datasets: Dataset[];
  onCreated: (d: Dataset) => void;
}) {
  const { project, setProject } = useProject();
  const [spec, setSpec] = useState<LinkSpec>(initial);
  const [preview, setPreview] = useState<LinkPreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const left = datasets.find((d) => d.id === spec.left);
  const right = datasets.find((d) => d.id === spec.right);
  const ready = spec.left !== spec.right && (spec.kind === "append" || (spec.keys.length > 0 && spec.keys.every((k) => k.left && k.right)));

  useEffect(() => {
    setAck(false);
    if (!ready) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    const timer = setTimeout(() => {
      api
        .previewLink(project.id, spec)
        .then((p) => !cancelled && setPreview(p))
        .catch((e) => !cancelled && (setError(e), setPreview(null)))
        .finally(() => !cancelled && setBusy(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [project.id, spec, ready]);

  const set = (patch: Partial<LinkSpec>) => setSpec((s) => ({ ...s, ...patch }));
  const swap = () =>
    setSpec((s) => ({ ...s, left: s.right, right: s.left, keys: s.keys.map((k) => ({ left: k.right, right: k.left })) }));
  const userCols = (d?: Dataset) => (d ? d.columns.map((c) => c.name) : []);

  const confirm = async () => {
    setConfirming(true);
    setError(null);
    try {
      const { project: updated, dataset } = await api.confirmLink(project.id, { ...spec, name: spec.name || null }, ack);
      setProject(updated);
      onCreated(dataset);
    } catch (e) {
      setError(e);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <h3>Review link</h3>
        {busy ? <Spinner label="Computing preview…" /> : null}
      </div>
      <div className="card-pad stack">
        <div className="grid-2">
          <label className="field">
            Base table <span className="hint">keeps one row per record</span>
            <select value={spec.left} onChange={(e) => set({ left: e.target.value })}>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Other table
            <select value={spec.right} onChange={(e) => set({ right: e.target.value })}>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="row-wrap">
          <div className="seg">
            {(["join", "append"] as const).map((k) => (
              <button
                key={k}
                className={(k === "join" ? spec.kind !== "append" : spec.kind === "append") ? "active" : ""}
                onClick={() => set({ kind: k === "join" ? (spec.kind === "time_aligned" ? "time_aligned" : "join") : "append" })}
              >
                {k === "join" ? "Join on keys" : "Append rows"}
              </button>
            ))}
          </div>
          <button className="btn btn-sm" onClick={swap} title="Swap base and other table">
            ⇄ Swap
          </button>
        </div>
        {spec.kind !== "append" ? (
          <>
            <div>
              <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>
                Key columns
              </div>
              {spec.keys.map((k, i) => (
                <div key={i} className="row" style={{ marginBottom: 6 }}>
                  <select value={k.left} onChange={(e) => set({ keys: spec.keys.map((x, j) => (j === i ? { ...x, left: e.target.value } : x)) })} aria-label="base key">
                    <option value="">— column in {left?.name ?? "base"} —</option>
                    {userCols(left).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                  <span className="muted">=</span>
                  <select value={k.right} onChange={(e) => set({ keys: spec.keys.map((x, j) => (j === i ? { ...x, right: e.target.value } : x)) })} aria-label="other key">
                    <option value="">— column in {right?.name ?? "other"} —</option>
                    {userCols(right).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                  {spec.keys.length > 1 ? (
                    <button className="btn btn-sm btn-ghost" onClick={() => set({ keys: spec.keys.filter((_, j) => j !== i) })} aria-label="remove key">
                      ✕
                    </button>
                  ) : null}
                </div>
              ))}
              <button className="link-btn small" onClick={() => set({ keys: [...spec.keys, { left: "", right: "" }] })}>
                + add another key column
              </button>
            </div>
            <div className="grid-2">
              <label className="field">
                Use of the other table
                <select value={spec.right_mode} onChange={(e) => set({ right_mode: e.target.value as LinkSpec["right_mode"] })}>
                  <option value="lookup">Look up one matching row (adds its columns)</option>
                  <option value="aggregate">Summarize per key (counts, means, sums)</option>
                  <option value="expand">Repeat base rows for every match (may inflate)</option>
                </select>
              </label>
              <label className="field">
                Base rows without a match
                <select value={spec.how} onChange={(e) => set({ how: e.target.value as LinkSpec["how"] })}>
                  <option value="left">Keep them (other columns missing)</option>
                  <option value="inner">Drop them</option>
                </select>
              </label>
            </div>
          </>
        ) : null}
        <label className="field">
          Name of the combined table <span className="hint">optional</span>
          <input type="text" value={spec.name ?? ""} placeholder={`${left?.name ?? ""} + ${right?.name ?? ""}`} onChange={(e) => set({ name: e.target.value })} maxLength={160} />
        </label>
        {spec.left === spec.right ? <Notice tone="warn">Choose two different tables.</Notice> : null}
        {error ? <ErrorBox error={error} /> : null}
        {preview ? <PreviewPanel preview={preview} leftName={left?.name ?? ""} rightName={right?.name ?? ""} /> : null}
        {preview?.requires_ack ? (
          <label className="row small" style={{ alignItems: "flex-start", gap: 8 }}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 3 }} />
            <span>
              I understand that this link repeats rows (or keys repeat on both sides), so counts, sums and averages over the
              repeated rows will be inflated. Summarizing per key avoids this.
            </span>
          </label>
        ) : null}
        <div className="row">
          <button className="btn btn-ok" disabled={!preview || busy || confirming || (preview.requires_ack && !ack)} onClick={confirm}>
            {confirming ? "Creating…" : "Confirm link"}
          </button>
          <span className="muted small">Creates a new combined table; the source files are not changed.</span>
        </div>
      </div>
    </div>
  );
}

function PreviewPanel({ preview, leftName, rightName }: { preview: LinkPreview; leftName: string; rightName: string }) {
  const p = preview;
  const append = p.kind === "append";
  const order = { critical: 0, warning: 1, info: 2 } as const;
  const warnings = [...p.warnings].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <div className="stack">
      <div className="grid-3">
        <div className="stat">
          <div className="v">{fmtInt(p.n_left)}</div>
          <div className="l">rows in {leftName}</div>
        </div>
        <div className="stat">
          <div className="v">{fmtInt(p.n_right)}</div>
          <div className="l">rows in {rightName}</div>
        </div>
        <div className="stat" style={p.row_multiplication > 1.0001 ? { borderColor: "#f5c2c2", background: "var(--bad-soft)" } : undefined}>
          <div className="v">{fmtInt(p.n_result)}</div>
          <div className="l">
            rows in the result
            {!append ? ` · ${p.row_multiplication.toFixed(2)}× base` : ""}
          </div>
        </div>
      </div>
      {!append ? (
        <table className="plain">
          <tbody>
            <tr>
              <td>Base rows with a match</td>
              <td className="num">
                {fmtInt(p.matched_left)} ({fmtPct(p.matched_left / Math.max(p.n_left, 1))})
              </td>
              <td>Unmatched base rows</td>
              <td className="num">{fmtInt(p.unmatched_left)}</td>
            </tr>
            <tr>
              <td>Other-table rows used</td>
              <td className="num">{fmtInt(p.matched_right)}</td>
              <td>Other-table rows not used</td>
              <td className="num">{fmtInt(p.unmatched_right)}</td>
            </tr>
            <tr>
              <td>Relationship in the data</td>
              <td className="num">{CARD_LABEL[p.cardinality] ?? p.cardinality}</td>
              <td>Most matches for one key</td>
              <td className="num">{fmtInt(p.max_right_per_key)}</td>
            </tr>
          </tbody>
        </table>
      ) : null}
      {warnings.length ? (
        <div className="stack" style={{ gap: 6 }}>
          {warnings.map((w, i) => (
            <Notice key={i} tone={w.severity === "critical" ? "bad" : w.severity === "warning" ? "warn" : "info"}>
              {w.message}
            </Notice>
          ))}
        </div>
      ) : (
        <Notice tone="ok">No row multiplication, no unmatched records and no conflicting values were found.</Notice>
      )}
      {p.overlap_columns.length ? (
        <div>
          <h4 style={{ marginBottom: 6 }}>Columns found in both tables</h4>
          <table className="plain">
            <thead>
              <tr>
                <th>Column</th>
                <th className="num">Rows compared</th>
                <th className="num">Agree</th>
                <th>Examples of disagreement (key: base vs other)</th>
              </tr>
            </thead>
            <tbody>
              {p.overlap_columns.map((o) => (
                <tr key={o.column}>
                  <td className="mono">{o.column}</td>
                  <td className="num">{fmtInt(o.compared)}</td>
                  <td className="num">{fmtPct(o.agree_share)}</td>
                  <td className="small">{o.examples.map((e) => `${e[0]}: ${e[1]} vs ${e[2]}`).join(" · ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div>
        <h4 style={{ marginBottom: 6 }}>Preview of the combined table</h4>
        <div className="table-wrap" style={{ maxHeight: 280 }}>
          <table className="data">
            <thead>
              <tr>
                {p.columns.map((c) => (
                  <th key={c}>{c === "__source__" ? "source file" : c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {p.sample.map((row, i) => (
                <tr key={i}>
                  {row.map((v, j) => (
                    <td key={j}>{v === null || v === undefined ? <span className="null">missing</span> : fmtCell(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
