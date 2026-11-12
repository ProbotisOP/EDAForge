import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { DataTable } from "../components/DataTable";
import { UploadZone, useUploader } from "../components/UploadZone";
import { Badge, Empty, ErrorBox, FileIcon, HealthDot, Modal, Notice, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { fmtBytes, fmtInt, fmtPct, plural, ROLE_LABEL } from "../lib/format";
import type { ColumnInfo, Dataset, ParseIssue, Project, Role, Upload } from "../lib/types";
import { ROLES } from "../lib/types";
import { useProject } from "./ProjectLayout";
import { QualityPanel, ColumnProfiles } from "../components/Profile";
import { CleanPanel } from "../components/CleanPanel";

type Tab = "preview" | "columns" | "quality" | "clean" | "log";

export function DataPage() {
  const { project, setProject } = useProject();
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("quality");
  const [removing, setRemoving] = useState<Upload | null>(null);
  const [error, setError] = useState<unknown>(null);

  const onUploaded = useCallback((p: Project) => setProject(p), [setProject]);
  const uploader = useUploader(project.id, onUploaded);
  const datasets = project.datasets;
  const selected = datasets.find((d) => d.id === datasetId) ?? datasets[0];

  useEffect(() => {
    if (!datasetId && selected) navigate(`/p/${project.id}/data/${selected.id}`, { replace: true });
  }, [datasetId, selected, navigate, project.id]);

  const uploads = [...project.uploads].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  const combined = datasets.filter((d) => d.kind !== "file");

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Data</h1>
          <div className="sub">Upload files, check how they were read, and inspect each table's quality.</div>
        </div>
        {datasets.filter((d) => d.kind === "file").length >= 2 ? (
          <button className="btn btn-primary" onClick={() => navigate(`/p/${project.id}/connect`)}>
            Next: connect files →
          </button>
        ) : datasets.length === 1 ? (
          <button className="btn" onClick={() => navigate(`/p/${project.id}/discover`)}>
            Analyze this file →
          </button>
        ) : null}
      </div>
      <div className="content">
        {error ? <ErrorBox error={error} /> : null}
        {datasets.length === 0 && project.uploads.length === 0 ? (
          <div className="card card-pad" style={{ maxWidth: 760 }}>
            <h2 style={{ marginBottom: 6 }}>Upload your files</h2>
            <p className="muted">
              Add one file to profile it, or several related files (for example customers and orders) to see how they
              connect. Nothing is uploaded to the internet.
            </p>
            <UploadZone uploader={uploader} />
          </div>
        ) : (
          <div className="data-layout">
            <div className="stack">
              <UploadZone uploader={uploader} compact />
              <div className="card">
                <div className="card-head">
                  <h3>Files</h3>
                  <span className="muted small">{plural(project.uploads.length, "upload")}</span>
                </div>
                <div className="file-list" style={{ padding: 6 }}>
                  {uploads.map((u) => (
                    <UploadEntry
                      key={u.id}
                      upload={u}
                      datasets={datasets.filter((d) => d.upload_id === u.id)}
                      selectedId={selected?.id}
                      onSelect={(id) => navigate(`/p/${project.id}/data/${id}`)}
                      onRemove={() => setRemoving(u)}
                    />
                  ))}
                </div>
              </div>
              {combined.length ? (
                <div className="card">
                  <div className="card-head">
                    <h3>Combined &amp; cleaned tables</h3>
                  </div>
                  <div className="file-list" style={{ padding: 6 }}>
                    {combined.map((d) => (
                      <div
                        key={d.id}
                        className={selected?.id === d.id ? "file active" : "file"}
                        onClick={() => navigate(`/p/${project.id}/data/${d.id}`)}
                      >
                        <FileIcon format={d.kind === "cleaned" ? "clean" : "combined"} />
                        <div className="grow">
                          <div className="row" style={{ gap: 7 }}>
                            <HealthDot health={d.health} />
                            <span style={{ fontWeight: 600, wordBreak: "break-word" }}>{d.name}</span>
                          </div>
                          <div className="muted small">
                            {fmtInt(d.n_rows)} rows · {d.n_cols} columns
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
            <div className="card card-pad" style={{ minWidth: 0 }}>
              {selected ? (
                <DatasetView dataset={selected} tab={tab} setTab={setTab} />
              ) : (
                <Empty icon="📄" title="No readable tables yet">
                  The uploaded files could not be read. Their errors are listed on the left.
                </Empty>
              )}
            </div>
          </div>
        )}
      </div>
      {removing ? (
        <Modal
          title={`Remove ${removing.filename}?`}
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
                    setProject(await api.deleteUpload(project.id, removing.id));
                    setRemoving(null);
                    navigate(`/p/${project.id}/data`);
                  } catch (e) {
                    setError(e);
                  }
                }}
              >
                Remove
              </button>
            </>
          }
        >
          <p>
            The workspace's copy of this file is deleted, together with combined tables and links built from it. Analysis
            runs already completed keep their results.
          </p>
        </Modal>
      ) : null}
    </>
  );
}

function UploadEntry({
  upload,
  datasets,
  selectedId,
  onSelect,
  onRemove,
}: {
  upload: Upload;
  datasets: Dataset[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onRemove: () => void;
}) {
  if (upload.status === "failed") {
    return (
      <div className="file" style={{ cursor: "default", alignItems: "flex-start" }}>
        <FileIcon format={upload.format} />
        <div className="grow">
          <div className="row">
            <strong style={{ wordBreak: "break-all" }}>{upload.filename}</strong>
            <Badge tone="bad">Failed</Badge>
          </div>
          <div className="small" style={{ color: "var(--bad)" }}>
            {upload.error}
          </div>
          <button className="link-btn small" onClick={onRemove}>
            Remove
          </button>
        </div>
      </div>
    );
  }
  return (
    <>
      {datasets.map((d) => (
        <div key={d.id} className={selectedId === d.id ? "file active" : "file"} onClick={() => onSelect(d.id)}>
          <FileIcon format={upload.format} />
          <div className="grow">
            <div className="row" style={{ gap: 7 }}>
              <HealthDot health={d.health} />
              <span style={{ fontWeight: 600, wordBreak: "break-word" }}>{d.name}</span>
            </div>
            <div className="muted small">
              {fmtInt(d.n_rows)} rows · {d.n_cols} columns · {fmtBytes(upload.size_bytes)}
            </div>
          </div>
          {d.issues.some((i) => i.level === "warning") ? (
            <Badge tone="warn" title="Read with warnings">
              !
            </Badge>
          ) : null}
        </div>
      ))}
      {datasets.length ? (
        <div style={{ padding: "0 12px 6px 52px" }}>
          <button className="link-btn tiny" onClick={onRemove}>
            Remove {upload.filename}
          </button>
        </div>
      ) : null}
    </>
  );
}

function DatasetView({ dataset, tab, setTab }: { dataset: Dataset; tab: Tab; setTab: (t: Tab) => void }) {
  const { project } = useProject();
  const upload = project.uploads.find((u) => u.id === dataset.upload_id);
  const warnings = dataset.issues.filter((i) => i.level !== "info").length;
  const sources = dataset.sources.map((id) => project.datasets.find((d) => d.id === id)?.name ?? id);
  return (
    <div>
      <div className="spread" style={{ marginBottom: 12, alignItems: "flex-start" }}>
        <div className="grow">
          <div className="row-wrap">
            <HealthDot health={dataset.health} size={16} />
            <h2 style={{ wordBreak: "break-word" }}>{dataset.name}</h2>
            <Badge tone={dataset.kind === "file" ? "gray" : "brand"}>
              {dataset.kind === "combined" ? "Combined table" : dataset.kind === "cleaned" ? "Cleaned table" : upload?.format?.toUpperCase() ?? "File"}
            </Badge>
          </div>
          <div className="muted small" style={{ marginTop: 4 }}>
            {fmtInt(dataset.n_rows)} rows · {dataset.n_cols} columns
            {dataset.kind === "combined" ? ` · built from ${sources.join(" + ")}` : dataset.kind === "cleaned" ? ` · cleaned from ${sources.join("")}` : ""} · fingerprint{" "}
            <span className="mono">{dataset.fingerprint.slice(0, 12)}</span>
          </div>
          {dataset.health ? (
            <div className={`health-line hl-${dataset.health.status}`}>{dataset.health.reasons.join(" · ")}</div>
          ) : null}
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={[
          { id: "quality", label: "Overview & quality" },
          { id: "columns", label: `Columns (${dataset.n_cols})` },
          { id: "preview", label: "Preview rows" },
          { id: "clean", label: "Clean & export ✦" },
          { id: "log", label: `How it was read${warnings ? ` (${warnings})` : ""}` },
        ]}
      />
      {tab === "preview" ? <DataTable projectId={project.id} datasetId={dataset.id} /> : null}
      {tab === "columns" ? <ColumnsTab dataset={dataset} /> : null}
      {tab === "quality" ? <QualityPanel projectId={project.id} dataset={dataset} /> : null}
      {tab === "clean" ? <CleanPanel dataset={dataset} /> : null}
      {tab === "log" ? <ParseLog issues={dataset.issues} uploadIssues={upload?.issues ?? []} /> : null}
    </div>
  );
}

function ColumnsTab({ dataset }: { dataset: Dataset }) {
  const { project, setProject } = useProject();
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const change = async (column: ColumnInfo, role: Role | null) => {
    setSaving(column.name);
    setError(null);
    try {
      const updated = await api.setRole(project.id, dataset.id, column.name, role);
      setProject({ ...project, datasets: project.datasets.map((d) => (d.id === updated.id ? updated : d)) });
    } catch (e) {
      setError(e);
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="stack">
      <Notice tone="info">
        The <b>role</b> decides how discovery uses a column. Identifiers, codes and dates are never analyzed as numbers.
        If a role is wrong (for example a numeric product code read as a number), change it here.
      </Notice>
      {error ? <ErrorBox error={error} /> : null}
      <ColumnProfiles projectId={project.id} dataset={dataset} onRoleChange={change} saving={saving} />
    </div>
  );
}

export function RoleSelect({
  column,
  onChange,
  disabled,
}: {
  column: ColumnInfo;
  onChange: (role: Role | null) => void;
  disabled?: boolean;
}) {
  return (
    <div className="row">
      <select
        value={column.role}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as Role)}
        aria-label={`Role of ${column.name}`}
        style={{ height: 28, fontSize: 12 }}
      >
        {[...ROLES, ...(ROLES.includes(column.role) ? [] : [column.role])].map((r) => (
          <option key={r} value={r}>
            {ROLE_LABEL[r] ?? r}
          </option>
        ))}
      </select>
      {column.role_source === "user" ? (
        <button className="link-btn tiny" onClick={() => onChange(null)} disabled={disabled}>
          reset
        </button>
      ) : null}
    </div>
  );
}

export function missingShare(column: ColumnInfo, n: number): string {
  return fmtPct(n ? column.n_missing / n : 0);
}

function ParseLog({ issues, uploadIssues }: { issues: ParseIssue[]; uploadIssues: ParseIssue[] }) {
  const all = [...uploadIssues, ...issues];
  if (!all.length) {
    return (
      <Notice tone="ok">
        The file was read without any changes: no renamed columns, no unreadable values, no placeholders.
      </Notice>
    );
  }
  return (
    <div className="stack">
      <div className="muted">
        Everything EDAForge changed or noticed while reading this table. The original file is never modified.
      </div>
      <table className="plain">
        <thead>
          <tr>
            <th>Level</th>
            <th>Column</th>
            <th>What happened</th>
          </tr>
        </thead>
        <tbody>
          {all.map((issue, i) => (
            <tr key={i}>
              <td>
                <Badge tone={issue.level === "error" ? "bad" : issue.level === "warning" ? "warn" : "info"}>
                  {issue.level}
                </Badge>
              </td>
              <td className="mono">{issue.column ?? "—"}</td>
              <td>
                {issue.message}
                {issue.examples.length ? (
                  <div className="examples">
                    {issue.examples.map((e, j) => (
                      <code key={j}>{e}</code>
                    ))}
                  </div>
                ) : null}
                {issue.rows.length ? (
                  <div className="muted small">
                    Rows: {issue.rows.join(", ")}
                    {issue.count && issue.count > issue.rows.length ? ", …" : ""}
                  </div>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
