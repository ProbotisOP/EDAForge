import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, ROLE_LABEL } from "../lib/format";
import type { ColumnInfo, ColumnProfile, Dataset, DatasetProfile, HistogramBin, QualityIssue, Role } from "../lib/types";
import { RoleSelect } from "../pages/DataPage";
import { HealthGauge } from "./kit";
import { Badge, ErrorBox, Loading } from "./ui";

export function useProfile(projectId: string, dataset: Dataset) {
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
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

function healthStroke(score: number): string {
  if (score >= 85) return "var(--ok)";
  if (score >= 60) return "var(--warn)";
  return "var(--bad)";
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
          <rect key={i} x={i * w + 0.5} y={height - h} width={Math.max(1, w - 1)} height={h} rx={1.5} fill="var(--brand)">
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
    <div style={{ display: "grid", gap: 3 }}>
      {shown.map((v) => (
        <div key={v.value} className="row small" style={{ gap: 6 }}>
          <span className="bar" style={{ width: 54 }}>
            <span style={{ width: `${(100 * v.count) / Math.max(n, 1)}%`, background: "var(--brand)" }} />
          </span>
          <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v.value}>
            {v.value}
          </span>
          <span className="faint tabular-nums">{fmtPct(v.count / Math.max(n, 1), 0)}</span>
        </div>
      ))}
    </div>
  );
}

const SEVERITY_TONE = { critical: "bad", warning: "warn", info: "info" } as const;

export function IssueItem({ issue }: { issue: QualityIssue }) {
  return (
    <details className={`issue issue-${issue.severity}`}>
      <summary>
        <span className={`sev-dot sev-${issue.severity}`} />
        <div className="grow">
          <div className="row-wrap" style={{ gap: 6 }}>
            <strong>{issue.title}</strong>
            <Badge tone={SEVERITY_TONE[issue.severity]}>{issue.severity}</Badge>
            <span className="muted small">{issue.category}</span>
          </div>
          <div className="muted small" style={{ marginTop: 2 }}>{issue.detail}</div>
        </div>
        {issue.count ? <span className="muted small nowrap tabular-nums">{fmtInt(issue.count)}</span> : null}
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
  const stroke = healthStroke(profile.health.score);
  const missingCells = profile.columns.reduce((s, c) => s + c.n_missing, 0);
  const missingPct = (100 * missingCells) / Math.max(1, profile.n_rows * profile.n_cols);
  const counts = { critical: 0, warning: 0, info: 0 };
  for (const i of profile.issues) counts[i.severity] += 1;

  const healthTileTone =
    profile.health.score >= 85 ? "bento-sage" : profile.health.score >= 60 ? "bento-sand" : "bento-coral";

  return (
    <div className="stack" style={{ gap: 16 }}>
      {/* Multi-Tonal Bento KPI Grid (RefUI #4 & #5 signature modular tiles!) */}
      <div className="bento-kpi-row">
        <div className={`bento-tile bento-kpi-wide ${healthTileTone}`}>
          <div className="row" style={{ gap: 14 }}>
            <HealthGauge score={profile.health.score} color={stroke} />
            <div>
              <div style={{ fontWeight: 700, fontSize: 15.5, fontFamily: "var(--display)" }}>
                Data health: {profile.health.label}
              </div>
              <div className="small tabular-nums" style={{ marginTop: 2, opacity: 0.85 }}>
                {counts.critical} critical · {counts.warning} warnings · {counts.info} notes
              </div>
              <button
                type="button"
                className="bento-inline-link"
                style={{ marginTop: 5 }}
                onClick={() => setShowMethod((v) => !v)}
              >
                {showMethod ? "Hide scoring formula" : "How is this calculated?"}
              </button>
            </div>
          </div>
        </div>

        <div className="bento-tile bento-kpi-card bento-sky">
          <div className="bento-kpi-num tabular-nums">{fmtInt(profile.n_rows)}</div>
          <div className="bento-kpi-lbl">Rows</div>
        </div>

        <div
          className="bento-tile bento-kpi-card bento-alabaster-contrast"
          title={Object.entries(profile.roles)
            .map(([r, n]) => `${n} ${(ROLE_LABEL[r] ?? r).toLowerCase()}`)
            .join(", ")}
        >
          <div className="bento-kpi-num tabular-nums">{fmtInt(profile.n_cols)}</div>
          <div className="bento-kpi-lbl">Columns</div>
        </div>

        <div className="bento-tile bento-kpi-card bento-coral">
          <div className="bento-kpi-num tabular-nums">{missingPct.toFixed(1)}%</div>
          <div className="bento-kpi-lbl">Cells missing</div>
        </div>

        <div className="bento-tile bento-kpi-card bento-surface-card">
          <div className="bento-kpi-num tabular-nums">{fmtInt(profile.n_duplicate_rows)}</div>
          <div className="bento-kpi-lbl">Duplicate rows</div>
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

      <div className="card">
        <div className="card-head">
          <h2>Quality &amp; schema checks</h2>
          <span className="muted small tabular-nums">{profile.issues.length} flagged</span>
        </div>
        {profile.issues.length === 0 ? (
          <div className="card-pad">
            <div className="notice ok">No issues were found by the checks listed under “How is this calculated?”.</div>
          </div>
        ) : (
          <div className="issue-list">
            {profile.issues.map((issue) => (
              <IssueItem key={issue.id} issue={issue} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function summary(p: ColumnProfile) {
  if (p.dtype === "integer" || p.dtype === "float") {
    if (p.role === "identifier") {
      return (
        <span className="muted small mono">
          IDs {fmtNum(p.min as number)} – {fmtNum(p.max as number)}
        </span>
      );
    }
    return (
      <div className="small mono" style={{ lineHeight: 1.4 }}>
        <div>
          med <b>{fmtNum(p.median)}</b> · μ {fmtNum(p.mean)}
        </div>
        <div className="muted">
          [{fmtNum(p.min as number)}, {fmtNum(p.max as number)}] · σ {fmtNum(p.std)}
        </div>
      </div>
    );
  }
  if (p.dtype === "date" || p.dtype === "datetime") {
    return (
      <div className="small mono">
        {String(p.min).slice(0, 10)} → {String(p.max).slice(0, 10)}
      </div>
    );
  }
  if (p.role === "identifier" && p.distinct_share > 0.95) {
    return (
      <span className="muted small tabular-nums">
        {fmtInt(p.n_distinct)} distinct ({fmtPct(p.distinct_share, 0)})
      </span>
    );
  }
  return <TopBars values={p.top_values} n={p.n - p.n_missing} />;
}

export function ColumnProfiles({
  projectId,
  dataset,
  onRoleChange,
  saving,
  onExploreColumn,
}: {
  projectId: string;
  dataset: Dataset;
  onRoleChange: (column: ColumnInfo, role: Role | null) => void;
  saving: string | null;
  onExploreColumn?: (col: string) => void;
}) {
  const { profile, error, reload } = useProfile(projectId, dataset);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!profile) return <Loading label="Profiling columns…" />;
  const byName = new Map(profile.columns.map((c) => [c.name, c]));
  return (
    <div className="table-wrap" style={{ border: "none", borderRadius: 0 }}>
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
                  <div className="row-wrap" style={{ gap: 6, justifyContent: "space-between" }}>
                    <span style={{ fontWeight: 600 }}>{c.name}</span>
                    {onExploreColumn && !c.pii ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ height: 24, padding: "0 8px", fontSize: 12 }}
                        onClick={() => onExploreColumn(c.name)}
                        title={`Explore and drill into ${c.name}`}
                      >
                        Drill →
                      </button>
                    ) : null}
                  </div>
                  <div className="faint tiny mono">
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
                  <span className="small tabular-nums">{fmtPct(p?.missing_share ?? 0)}</span>
                </td>
                <td className="num">{p ? fmtInt(p.n_distinct) : "—"}</td>
                <td>{p ? summary(p) : null}</td>
                <td>
                  {p && p.histogram.length ? (
                    <div
                      onClick={() => !c.pii && onExploreColumn?.(c.name)}
                      style={{ cursor: !c.pii && onExploreColumn ? "pointer" : "default" }}
                      title={!c.pii && onExploreColumn ? `Click to open ${c.name} in Explore` : undefined}
                    >
                      <Sparkline bins={p.histogram} />
                    </div>
                  ) : (
                    <span className="faint small">—</span>
                  )}
                </td>
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
