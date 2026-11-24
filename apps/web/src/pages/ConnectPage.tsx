import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  GitMerge,
  Layers,
  MousePointerClick,
  Plus,
} from "lucide-react";
import { SchemaGraph } from "../components/SchemaGraph";
import { SpringSegmented } from "../components/kit";
import { Badge, Empty, ErrorBox, Loading, Modal, Notice, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtCell, fmtInt, fmtPct } from "../lib/format";
import type { Dataset, LinkPreview, LinkSpec, LinkSuggestion, Rescale } from "../lib/types";
import { useProject } from "./ProjectLayout";

const KIND_LABEL: Record<string, string> = {
  join: "Join",
  append: "Append (stack rows)",
  time_aligned: "Time-aligned join",
  unrelated: "No relationship found",
};
const CARD_LABEL: Record<string, string> = {
  "1:1": "1-to-1",
  "m:1": "many-to-1",
  "1:m": "1-to-many",
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
  const [showOther, setShowOther] = useState(false);

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
  const unconfirmed = (suggestions ?? []).filter((s) => s.status !== "confirmed");
  const actionable = unconfirmed.filter((s) => s.kind !== "unrelated" && s.status !== "rejected");
  const secondary = unconfirmed.filter((s) => s.kind === "unrelated" || s.status === "rejected");

  if (project.datasets.length < 2) {
    return (
      <>
        <Header />
        <div className="content">
          <div className="card">
            <Empty icon={<GitMerge size={22} />} title="Connecting needs at least 2 tables">
              Upload another related file on the <Link to={`/p/${project.id}/data`}>Data</Link> page — for example orders
              and customers — or go straight to <Link to={`/p/${project.id}/discover`}>Discover</Link> to analyze 1 file.
            </Empty>
          </div>
        </div>
      </>
    );
  }

  const activePair: [string, string] | null = draft ? [draft.left, draft.right] : null;

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
              setDraft({
                kind: "join",
                left: a.id,
                right: b.id,
                keys: [{ left: "", right: "" }],
                how: "left",
                right_mode: "lookup",
                name: null,
              });
            }}
          >
            <Plus size={14} />
            <span>Define custom link</span>
          </button>
        }
      />
      <div className="content stack">
        {error ? <ErrorBox error={error} onRetry={load} /> : null}
        {created ? (
          <Notice tone="ok">
            Created <b>{created.name}</b> with <span className="tabular-nums">{fmtInt(created.n_rows)}</span> rows and{" "}
            <span className="tabular-nums">{created.n_cols}</span> columns. Every row preserves source lineage.{" "}
            <Link to={`/p/${project.id}/data/${created.id}`}>Inspect it</Link> ·{" "}
            <Link to={`/p/${project.id}/discover?dataset=${created.id}`}>Find patterns in it →</Link>
          </Notice>
        ) : null}

        {suggestions ? (
          <SchemaGraph
            datasets={project.datasets}
            suggestions={suggestions}
            confirmed={confirmed}
            selectedId={selected}
            activePair={activePair}
            onSelectSuggestion={choose}
          />
        ) : null}

        <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 0.95fr) minmax(0, 1.25fr)", alignItems: "start" }}>
          <div className="stack">
            <div className="spread">
              <h2 className="panel-title">Suggested links ({actionable.length})</h2>
            </div>

            {suggestions === null && !error ? <Loading label="Checking join keys across tables…" /> : null}

            {suggestions && actionable.length === 0 ? (
              <div className="card">
                <Empty icon={<CheckCircle2 size={22} />} title="All candidate links reviewed">
                  Every detected relationship was confirmed or dismissed. You can still define a custom join above.
                </Empty>
              </div>
            ) : null}

            {actionable.map((s) => (
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

            {secondary.length > 0 ? (
              <div>
                <button
                  type="button"
                  className="link-btn small"
                  onClick={() => setShowOther((v) => !v)}
                >
                  {showOther ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <span>
                    {showOther ? "Hide" : "Show"} {secondary.length} unrelated or dismissed pair
                    {secondary.length > 1 ? "s" : ""}
                  </span>
                </button>
                {showOther ? (
                  <div className="stack mt">
                    {secondary.map((s) => (
                      <SuggestionCard
                        key={s.id}
                        s={s}
                        names={names}
                        selected={selected === s.id}
                        onReview={() => choose(s)}
                        onReject={async () => {}}
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
                  </div>
                ) : null}
              </div>
            ) : null}

            {confirmed.length ? (
              <div className="card">
                <div className="card-head">
                  <h2>Confirmed links ({confirmed.length})</h2>
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
                              {KIND_LABEL[l.kind]} ·{" "}
                              <span className="mono">
                                {l.spec.keys.map((k) => `${k.left} = ${k.right}`).join(", ") || "aligned schema"}
                              </span>
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

          <div style={{ position: "sticky", top: 14 }}>
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
                <Empty icon={<MousePointerClick size={22} />} title="Select a relationship to preview">
                  Click any connector in the map above or click <b>Review &amp; preview</b> on a suggested link to check
                  row counts, match rates, and unit alignment before joining.
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
          Preview foreign-key cardinality, row multiplication, and unit consistency before combining tables.
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
    <div
      className={`${selected ? "suggestion selected" : "suggestion"} bento-hit`}
      style={rejected ? { opacity: 0.65 } : undefined}
    >
      <div className="card-pad bento-inner">
        <div className="spread" style={{ alignItems: "center" }}>
          <div className="row-wrap" style={{ gap: 6 }}>
            <Badge tone={s.kind === "unrelated" ? "gray" : "info"}>
              {KIND_LABEL[s.kind]}
            </Badge>
            {s.cardinality ? (
              <Badge tone={s.cardinality === "m:m" ? "bad" : "outline"}>
                {s.cardinality} ({CARD_LABEL[s.cardinality]})
              </Badge>
            ) : null}
            {rejected ? <Badge tone="gray">dismissed</Badge> : null}
          </div>
          {s.kind !== "unrelated" ? (
            <span className="confidence small muted" title="Match confidence">
              <span className="meter">
                <span style={{ width: `${Math.round(100 * s.confidence)}%` }} />
              </span>
              {Math.round(100 * s.confidence)}%
            </span>
          ) : null}
        </div>

        <div className="rel-flow-line">
          <span className="rel-table-name">{names.get(s.left) ?? s.left}</span>
          {s.keys[0]?.left ? <code>{s.keys.map((k) => k.left).join(", ")}</code> : null}
          <span className="muted" style={{ display: "inline-flex" }}>
            {s.kind === "append" ? <Layers size={14} /> : <ArrowRight size={14} />}
          </span>
          <span className="rel-table-name">{names.get(s.right) ?? s.right}</span>
          {s.keys[0]?.right ? <code>{s.keys.map((k) => k.right).join(", ")}</code> : null}
        </div>

        <ul className="rel-reasons small">
          {s.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
          {s.warnings.map((w, i) => (
            <li key={`w${i}`} className="rel-warning-item">
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
                <button className={selected ? "btn btn-sm btn-primary" : "btn btn-sm"} onClick={onReview}>
                  Review &amp; preview
                </button>
                <button className="btn btn-sm btn-ghost" onClick={onReject}>
                  Dismiss
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
  const ready =
    spec.left !== spec.right &&
    (spec.kind === "append" || (spec.keys.length > 0 && spec.keys.every((k) => k.left && k.right)));

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
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [project.id, spec, ready]);

  const set = (patch: Partial<LinkSpec>) => setSpec((s) => ({ ...s, ...patch }));
  const swap = () =>
    setSpec((s) => ({
      ...s,
      left: s.right,
      right: s.left,
      keys: s.keys.map((k) => ({ left: k.right, right: k.left })),
    }));
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
        <h2>Preview link</h2>
        {busy ? <Spinner label="Computing preview…" /> : null}
      </div>
      <div className="card-pad stack">
        <div className="grid-2">
          <label className="field">
            <span>
              Base table <span className="hint">(grain preserved)</span>
            </span>
            <select value={spec.left} onChange={(e) => set({ left: e.target.value })}>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Lookup or stacked table</span>
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
          <SpringSegmented<"join" | "append">
            role="group"
            ariaLabel="Link operation"
            value={spec.kind === "append" ? "append" : "join"}
            onChange={(k) => set({ kind: k === "join" ? (spec.kind === "time_aligned" ? "time_aligned" : "join") : "append" })}
            items={[
              { id: "join", label: "Join on keys" },
              { id: "append", label: "Append rows" },
            ]}
          />
          <button type="button" className="btn btn-sm" onClick={swap} title="Swap base and lookup table">
            <ArrowLeftRight size={13} />
            <span>Swap tables</span>
          </button>
        </div>

        {spec.kind !== "append" ? (
          <>
            <div>
              <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
                Join key pairs
              </div>
              {spec.keys.map((k, i) => (
                <div key={i} className="row" style={{ marginBottom: 6 }}>
                  <select
                    style={{ flex: 1 }}
                    value={k.left}
                    onChange={(e) => set({ keys: spec.keys.map((x, j) => (j === i ? { ...x, left: e.target.value } : x)) })}
                    aria-label="base key"
                  >
                    <option value="">— column in {left?.name ?? "base"} —</option>
                    {userCols(left).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                  <span className="muted mono">=</span>
                  <select
                    style={{ flex: 1 }}
                    value={k.right}
                    onChange={(e) => set({ keys: spec.keys.map((x, j) => (j === i ? { ...x, right: e.target.value } : x)) })}
                    aria-label="other key"
                  >
                    <option value="">— column in {right?.name ?? "other"} —</option>
                    {userCols(right).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                  {spec.keys.length > 1 ? (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => set({ keys: spec.keys.filter((_, j) => j !== i) })}
                      aria-label="remove key"
                    >
                      ×
                    </button>
                  ) : null}
                </div>
              ))}
              <button
                type="button"
                className="link-btn small"
                onClick={() => set({ keys: [...spec.keys, { left: "", right: "" }] })}
              >
                + Add composite key column
              </button>
            </div>
            <div className="grid-2">
              <label className="field">
                <span>Lookup strategy</span>
                <select value={spec.right_mode} onChange={(e) => set({ right_mode: e.target.value as LinkSpec["right_mode"] })}>
                  <option value="lookup">Lookup 1 matching row (adds columns)</option>
                  <option value="aggregate">Summarize per key (counts, means, sums)</option>
                  <option value="expand">Expand for every match (may multiply rows)</option>
                </select>
              </label>
              <label className="field">
                <span>Unmatched base rows</span>
                <select value={spec.how} onChange={(e) => set({ how: e.target.value as LinkSpec["how"] })}>
                  <option value="left">Keep all base rows (left join)</option>
                  <option value="inner">Keep matched rows only (inner join)</option>
                </select>
              </label>
            </div>
          </>
        ) : null}

        <label className="field">
          <span>
            Output table name <span className="hint">(optional)</span>
          </span>
          <input
            type="text"
            value={spec.name ?? ""}
            placeholder={`${left?.name ?? ""} + ${right?.name ?? ""}`}
            onChange={(e) => set({ name: e.target.value })}
            maxLength={160}
          />
        </label>

        {spec.left === spec.right ? <Notice tone="warn">Choose 2 different tables.</Notice> : null}
        {error ? <ErrorBox error={error} /> : null}
        {preview ? (
          <PreviewPanel
            preview={preview}
            leftName={left?.name ?? ""}
            rightName={right?.name ?? ""}
            rescale={spec.rescale ?? []}
            onChangeRescale={(next) => set({ rescale: next })}
          />
        ) : null}
        {preview?.requires_ack ? (
          <label className="row small" style={{ alignItems: "flex-start", gap: 8 }}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 3 }} />
            <span>
              I have reviewed this warning:{" "}
              {preview.ack_reasons?.length
                ? preview.ack_reasons.join("; ")
                : "this link repeats rows (or keys repeat on both sides), which can inflate counts and sums"}
              .
            </span>
          </label>
        ) : null}
        <div className="row">
          <button
            className="btn btn-primary"
            disabled={!preview || busy || confirming || (preview.requires_ack && !ack)}
            onClick={confirm}
          >
            {confirming ? "Creating…" : "Confirm link"}
          </button>
          <span className="muted small">Creates a new derived table; original uploads stay untouched.</span>
        </div>
      </div>
    </div>
  );
}

function PreviewPanel({
  preview,
  leftName,
  rightName,
  rescale,
  onChangeRescale,
}: {
  preview: LinkPreview;
  leftName: string;
  rightName: string;
  rescale: Rescale[];
  onChangeRescale: (next: Rescale[]) => void;
}) {
  const p = preview;
  const append = p.kind === "append";
  const order = { critical: 0, warning: 1, info: 2 } as const;
  const mismatchCols = new Set(p.unit_mismatches.map((u) => u.column));
  const warnings = [...p.warnings]
    .filter((w) => !(mismatchCols.size > 0 && [...mismatchCols].some((col) => w.message.startsWith(`${col}:`)) && /different units|ratio this close/i.test(w.message)))
    .sort((a, b) => order[a.severity] - order[b.severity]);
  const leftShare = Math.min(1, p.matched_left / Math.max(p.n_left, 1));
  const rightShare = Math.min(1, p.matched_right / Math.max(p.n_right, 1));

  const toggleRescale = (opt: Rescale) => {
    const exists = rescale.some((r) => r.column === opt.column && r.side === opt.side && r.factor === opt.factor);
    if (exists) {
      onChangeRescale(rescale.filter((r) => r.column !== opt.column));
    } else {
      onChangeRescale([...rescale.filter((r) => r.column !== opt.column), opt]);
    }
  };

  return (
    <div className="stack">
      <div className="bento-kpi-3">
        <div className="bento-tile bento-kpi-card bento-sky">
          <div className="bento-kpi-num tabular-nums">{fmtInt(p.n_left)}</div>
          <div className="bento-kpi-lbl">rows in {leftName}</div>
        </div>
        <div className="bento-tile bento-kpi-card bento-sand">
          <div className="bento-kpi-num tabular-nums">{fmtInt(p.n_right)}</div>
          <div className="bento-kpi-lbl">rows in {rightName}</div>
        </div>
        <div
          className={`bento-tile bento-kpi-card ${p.row_multiplication > 1.0001 ? "bento-coral" : "bento-sage"}`}
        >
          <div className="bento-kpi-num tabular-nums">{fmtInt(p.n_result)}</div>
          <div className="bento-kpi-lbl">
            rows in the result
            {!append ? ` · ${p.row_multiplication.toFixed(2)}× base` : ""}
          </div>
        </div>
      </div>

      {!append ? (
        <div className="join-coverage-rows">
          <div className="join-cov-row">
            <div className="spread small">
              <span>
                <b>{leftName}</b> key match rate
              </span>
              <span className="tabular-nums">
                {fmtInt(p.matched_left)} matched ({fmtPct(leftShare)}) · {fmtInt(p.unmatched_left)} unmatched
              </span>
            </div>
            <div className="cov-track">
              <div className="cov-fill ok" style={{ width: `${Math.round(leftShare * 100)}%` }} />
            </div>
          </div>

          <div className="join-cov-row">
            <div className="spread small">
              <span>
                <b>{rightName}</b> keys referenced
              </span>
              <span className="tabular-nums">
                {fmtInt(p.matched_right)} used ({fmtPct(rightShare)}) · {fmtInt(p.unmatched_right)} unused
              </span>
            </div>
            <div className="cov-track">
              <div className="cov-fill brand" style={{ width: `${Math.round(rightShare * 100)}%` }} />
            </div>
          </div>

          <div className="spread tiny muted">
            <span>
              Cardinality: <b>{CARD_LABEL[p.cardinality] ?? p.cardinality}</b>
            </span>
            <span className="tabular-nums">
              Max matches per key: <b>{fmtInt(p.max_right_per_key)}</b>
            </span>
          </div>
        </div>
      ) : null}

      {p.unit_mismatches.length > 0 ? (
        <div className="unit-guard-card">
          <div className="spread" style={{ marginBottom: 6 }}>
            <strong>Unit mismatch detected across tables</strong>
            <Badge tone="warn">{p.unit_mismatches.length} column{p.unit_mismatches.length > 1 ? "s" : ""}</Badge>
          </div>
          {p.unit_mismatches.map((u) => (
            <div key={u.column} className="unit-guard-item">
              <div className="small">
                <code>{u.column}</code> median is <b className="tabular-nums">{u.median_left.toLocaleString()}</b> in{" "}
                <b>{leftName}</b> vs. <b className="tabular-nums">{u.median_right.toLocaleString()}</b> in <b>{rightName}</b>{" "}
                <span className="muted">({u.hint})</span>
              </div>
              <div className="row-wrap" style={{ gap: 6, marginTop: 6 }}>
                {u.options.map((opt, idx) => {
                  const active = rescale.some(
                    (r) => r.column === opt.column && r.side === opt.side && r.factor === opt.factor,
                  );
                  const sideLabel = opt.side === "left" ? leftName : rightName;
                  return (
                    <button
                      key={idx}
                      type="button"
                      className={`btn btn-sm${active ? " btn-primary" : ""}`}
                      onClick={() => toggleRescale(opt)}
                    >
                      {active ? "✓ " : ""}Rescale {sideLabel} · {opt.column} × {opt.factor}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {warnings.length ? (
        <div className="stack" style={{ gap: 6 }}>
          {warnings.map((w, i) => (
            <Notice key={i} tone={w.severity === "critical" ? "bad" : w.severity === "warning" ? "warn" : "info"}>
              {w.message}
            </Notice>
          ))}
        </div>
      ) : p.unit_mismatches.length === 0 ? (
        <Notice tone="ok">Clean join: 0 row inflation, 0 unmatched keys, and 0 value conflicts.</Notice>
      ) : null}

      {p.overlap_columns.length ? (
        <div>
          <h4 style={{ marginBottom: 6 }}>Overlapping column agreement</h4>
          <table className="plain">
            <thead>
              <tr>
                <th>Column</th>
                <th className="num">Compared</th>
                <th className="num">Agree</th>
                <th>Sample disagreements</th>
              </tr>
            </thead>
            <tbody>
              {p.overlap_columns.map((o) => (
                <tr key={o.column}>
                  <td className="mono">{o.column}</td>
                  <td className="num">{fmtInt(o.compared)}</td>
                  <td className="num">{fmtPct(o.agree_share)}</td>
                  <td className="small mono">
                    {o.examples.map((e) => `${e[0]}: ${e[1]} ≠ ${e[2]}`).join(" · ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div>
        <h4 style={{ marginBottom: 6 }}>Combined table sample</h4>
        <div className="table-wrap" style={{ maxHeight: 260 }}>
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
