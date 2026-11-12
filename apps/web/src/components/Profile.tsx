import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, ROLE_LABEL } from "../lib/format";
import type { ColumnInfo, ColumnProfile, Dataset, DatasetProfile, HistogramBin, QualityIssue, Role } from "../lib/types";
import { RoleSelect } from "../pages/DataPage";
import { Badge, ErrorBox, Loading } from "./ui";

/** Fetches the engine-computed profile of a dataset (cached server-side). */
export function useProfile(projectId: string, dataset: Dataset) {
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  // Role changes invalidate the profile on the server; refetch when the column metadata changes.
  const key = dataset.id + dataset.columns.map((c) => c.role).join(",");
  const load = useCallback(() => {
    setError(null);
    setProfile(null);
    api.profile(projectId, dataset.id).then(setProfile).catch(setError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, key]);
  useEffect(load, [load]);
  return { profile, error, reload: load };
}

function healthColor(score: number): { bg: string; fg: string } {
  if (score >= 90) return { bg: "var(--ok-soft)", fg: "var(--ok)" };
  if (score >= 75) return { bg: "#eef7e8", fg: "#3f6212" };
  if (score >= 50) return { bg: "var(--warn-soft)", fg: "var(--warn)" };
  return { bg: "var(--bad-soft)", fg: "var(--bad)" };
}

export function Sparkline({ bins, width = 120, height = 28 }: { bins: HistogramBin[]; width?: number; height?: number }) {
  if (!bins.length) return null;
  const max = Math.max(...bins.map((b) => b.count), 1);
  const w = width / bins.length;
  return (
    <svg className="spark" width={width} height={height} role="img" aria-label="distribution">
      {bins.map((b, i) => {
        const h = b.count ? Math.max(1.5, (b.count / max) * (height - 2)) : 0;
        return (
          <rect key={i} x={i * w + 0.5} y={height - h} width={Math.max(1, w - 1)} height={h} fill="#818cf8">
            <title>{`${typeof b.x0 === "number" ? fmtNum(b.x0) : String(b.x0).slice(0, 10)} – ${
              typeof b.x1 === "number" ? fmtNum(b.x1) : String(b.x1).slice(0, 10)
            }: ${fmtInt(b.count)}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function TopBars({ values, n }: { values: { value: string; count: number }[]; n: number }) {
  const shown = values.slice(0, 4);
  return (
    <div style={{ display: "grid", gap: 2 }}>
      {shown.map((v) => (
        <div key={v.value} className="row small" style={{ gap: 6 }}>
          <span className="bar" style={{ width: 54 }}>
            <span style={{ width: `${(100 * v.count) / Math.max(n, 1)}%`, background: "#818cf8" }} />
          </span>
          <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v.value}>
            {v.value}
          </span>
          <span className="faint">{fmtPct(v.count / Math.max(n, 1), 0)}</span>
        </div>
      ))}
    </div>
  );
}

const SEVERITY_TONE = { critical: "bad", warning: "warn", info: "info" } as const;

export function IssueItem({ issue }: { issue: QualityIssue }) {
  return (
    <details className="issue">
      <summary>
        <span className={`sev-dot sev-${issue.severity}`} />
        <div className="grow">
          <div className="row-wrap" style={{ gap: 6 }}>
            <strong>{issue.title}</strong>
            <Badge tone={SEVERITY_TONE[issue.severity]}>{issue.severity}</Badge>
            <Badge tone="outline">{issue.category}</Badge>
          </div>
          <div className="muted small">{issue.detail}</div>
        </div>
        {issue.count ? <span className="muted small nowrap">{fmtInt(issue.count)}</span> : null}
      </summary>
      <div className="body">
        <div>
          <b>Rule:</b> {issue.method}
        </div>
        {issue.share !== null && issue.share !== undefined ? (
          <div>
            <b>Affected:</b> {fmtInt(issue.count ?? 0)} ({fmtPct(issue.share)})
          </div>
        ) : null}
        {issue.examples.length ? (
          <div>
            <b>Examples:</b>
            <div className="examples">
              {issue.examples.map((e, i) => (
                <code key={i}>{e}</code>
              ))}
            </div>
          </div>
        ) : null}
        {issue.rows.length ? (
          <div className="muted small" style={{ marginTop: 4 }}>
            Row numbers in the file: {issue.rows.join(", ")}
            {issue.count && issue.count > issue.rows.length ? ", …" : ""}
          </div>
        ) : null}
      </div>
    </details>
  );
}

export function QualityPanel({ projectId, dataset }: { projectId: string; dataset: Dataset }) {
  const { profile, error, reload } = useProfile(projectId, dataset);
  const [showMethod, setShowMethod] = useState(false);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!profile) return <Loading label="Profiling columns…" />;
  const color = healthColor(profile.health.score);
  const missingCells = profile.columns.reduce((s, c) => s + c.n_missing, 0);
  const counts = { critical: 0, warning: 0, info: 0 };
  for (const i of profile.issues) counts[i.severity] += 1;
  return (
    <div className="stack">
      <div className="row" style={{ gap: 16, alignItems: "stretch", flexWrap: "wrap" }}>
        <div className="stat row" style={{ gap: 14, minWidth: 300, flex: "1 1 300px" }}>
          <div className="health-ring" style={{ background: color.bg, color: color.fg }} aria-label="health score">
            {Number.isInteger(profile.health.score) ? profile.health.score : profile.health.score.toFixed(1)}
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Data health: {profile.health.label}</div>
            <div className="muted small">
              {counts.critical} critical · {counts.warning} warnings · {counts.info} notes
            </div>
            <button className="link-btn small" onClick={() => setShowMethod((v) => !v)}>
              {showMethod ? "Hide" : "How is this calculated?"}
            </button>
          </div>
        </div>
        <div className="grid-4" style={{ flex: "2 1 420px" }}>
          <div className="stat">
            <div className="v">{fmtInt(profile.n_rows)}</div>
            <div className="l">rows</div>
          </div>
          <div className="stat" title={Object.entries(profile.roles).map(([r, n]) => `${n} ${(ROLE_LABEL[r] ?? r).toLowerCase()}`).join(", ")}>
            <div className="v">{profile.n_cols}</div>
            <div className="l">columns</div>
            <div className="faint tiny" style={{ lineHeight: 1.3, marginTop: 2 }}>
              {Object.entries(profile.roles)
                .map(([r, n]) => `${n} ${(ROLE_LABEL[r] ?? r).toLowerCase()}`)
                .join(" · ")}
            </div>
          </div>
          <div className="stat">
            <div className="v">{fmtPct(missingCells / Math.max(1, profile.n_rows * profile.n_cols))}</div>
            <div className="l">cells missing</div>
          </div>
          <div className="stat">
            <div className="v">{fmtInt(profile.n_duplicate_rows)}</div>
            <div className="l">duplicate rows</div>
          </div>
        </div>
      </div>
      {showMethod ? (
        <div className="card card-pad">
          <p className="muted">{profile.health.method}</p>
          <table className="plain">
            <thead>
              <tr>
                <th>Category</th>
                <th>Rule</th>
                <th className="num">Issues</th>
                <th className="num">Penalty</th>
              </tr>
            </thead>
            <tbody>
              {profile.health.components.map((c) => (
                <tr key={c.category}>
                  <td>{c.category}</td>
                  <td className="muted">{c.explanation}</td>
                  <td className="num">{c.issues}</td>
                  <td className="num">
                    {c.penalty ? `−${c.penalty}` : "0"} <span className="faint">/ {c.cap}</span>
                  </td>
                </tr>
              ))}
              <tr>
                <td colSpan={3}>
                  <b>Score</b>
                </td>
                <td className="num">
                  <b>{profile.health.score}</b>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}
      <div>
        <h3 style={{ margin: "6px 0 8px" }}>Issues found ({profile.issues.length})</h3>
        {profile.issues.length === 0 ? (
          <div className="notice ok">No issues were found by the checks listed under “How is this calculated?”.</div>
        ) : (
          profile.issues.map((issue) => <IssueItem key={issue.id} issue={issue} />)
        )}
      </div>
    </div>
  );
}

function summary(p: ColumnProfile) {
  if (p.dtype === "integer" || p.dtype === "float") {
    if (p.role === "identifier") return <span className="muted small">IDs {fmtNum(p.min as number)} – {fmtNum(p.max as number)}</span>;
    return (
      <div className="small" style={{ lineHeight: 1.35 }}>
        <div>
          median <b>{fmtNum(p.median)}</b> · mean {fmtNum(p.mean)}
        </div>
        <div className="muted">
          {fmtNum(p.min as number)} – {fmtNum(p.max as number)} · sd {fmtNum(p.std)}
        </div>
      </div>
    );
  }
  if (p.dtype === "date" || p.dtype === "datetime") {
    return (
      <div className="small">
        {String(p.min).slice(0, 10)} → {String(p.max).slice(0, 10)}
      </div>
    );
  }
  if (p.role === "identifier" && p.distinct_share > 0.95) {
    return <span className="muted small">{fmtInt(p.n_distinct)} distinct values ({fmtPct(p.distinct_share, 0)} unique)</span>;
  }
  return <TopBars values={p.top_values} n={p.n - p.n_missing} />;
}

export function ColumnProfiles({
  projectId,
  dataset,
  onRoleChange,
  saving,
}: {
  projectId: string;
  dataset: Dataset;
  onRoleChange: (column: ColumnInfo, role: Role | null) => void;
  saving: string | null;
}) {
  const { profile, error, reload } = useProfile(projectId, dataset);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!profile) return <Loading label="Profiling columns…" />;
  const byName = new Map(profile.columns.map((c) => [c.name, c]));
  return (
    <div className="table-wrap">
      <table className="plain columns-table">
        <thead>
          <tr>
            <th>Column</th>
            <th>Role</th>
            <th>Missing</th>
            <th className="num">Distinct</th>
            <th>Summary</th>
            <th>Distribution</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {dataset.columns.map((c) => {
            const p = byName.get(c.name);
            return (
              <tr key={c.name}>
                <td>
                  <div style={{ fontWeight: 650, wordBreak: "break-word" }}>{c.name}</div>
                  <div className="faint tiny">
                    {c.dtype}
                    {c.original_name !== c.name ? ` · was “${c.original_name}”` : ""}
                  </div>
                </td>
                <td>
                  <RoleSelect column={c} onChange={(role) => onRoleChange(c, role)} disabled={saving === c.name} />
                  <div className="faint tiny" style={{ maxWidth: 190 }}>
                    {c.role_reason}
                  </div>
                </td>
                <td className="nowrap">
                  <span className="bar">
                    <span style={{ width: `${100 * (p?.missing_share ?? 0)}%` }} />
                  </span>{" "}
                  <span className="small">{fmtPct(p?.missing_share ?? 0)}</span>
                </td>
                <td className="num">{p ? fmtInt(p.n_distinct) : "—"}</td>
                <td>{p ? summary(p) : null}</td>
                <td>{p && p.histogram.length ? <Sparkline bins={p.histogram} /> : <span className="faint small">—</span>}</td>
                <td className="small">
                  <div className="row-wrap" style={{ gap: 4 }}>
                    {c.pii ? <Badge tone="bad">personal data: {c.pii.replace("_", " ")}</Badge> : null}
                    {c.n_invalid ? <Badge tone="warn">{fmtInt(c.n_invalid)} unreadable</Badge> : null}
                    {p?.n_outliers ? <Badge tone="info">{fmtInt(p.n_outliers)} unusual</Badge> : null}
                    {p?.flags.includes("constant") ? <Badge>single value</Badge> : null}
                  </div>
                  {c.parse_note ? <div className="faint tiny">{c.parse_note}</div> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
