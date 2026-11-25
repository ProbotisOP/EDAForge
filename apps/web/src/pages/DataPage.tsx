import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { FileWarning, Sparkles, Trash2 } from "lucide-react";
import { CleanPanel } from "../components/CleanPanel";
import { DataTable } from "../components/DataTable";
import { ExploreStudio } from "../components/ExploreStudio";
import { ColumnProfiles, QualityPanel } from "../components/Profile";
import { UploadZone, useUploader } from "../components/UploadZone";
import { Badge, Empty, ErrorBox, FileIcon, HealthDot, Modal, Notice, Tabs } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { buildDemoFiles } from "../lib/demoData";
import { fmtBytes, fmtInt, fmtPct, plural, ROLE_LABEL } from "../lib/format";
import { playConfirm, playTick } from "../lib/sound";
import type { ColumnInfo, Dataset, ParseIssue, Project, Role, Upload } from "../lib/types";
import { ROLES } from "../lib/types";
import { useProject } from "./ProjectLayout";

type Tab = "quality" | "explore" | "columns" | "preview" | "clean" | "log";
const VALID_TABS: Tab[] = ["quality", "explore", "columns", "preview", "clean", "log"];

export function DataPage() {
  const { project, setProject } = useProject();
  const { datasetId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const rawTab = searchParams.get("tab") as Tab | null;
  const tab: Tab = rawTab && VALID_TABS.includes(rawTab) ? rawTab : "quality";

  const setTab = useCallback(
    (next: Tab) => {
      const nextParams = new URLSearchParams(searchParams);
      if (next === "quality") nextParams.delete("tab");
      else nextParams.set("tab", next);
      setSearchParams(nextParams, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const [exploreCol, setExploreCol] = useState<string | undefined>(undefined);
  const [removing, setRemoving] = useState<Upload | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const onUploaded = useCallback((p: Project) => setProject(p), [setProject]);
  const uploader = useUploader(project.id, onUploaded);
  const datasets = project.datasets;
  const selected = datasets.find((d) => d.id === datasetId) ?? datasets[0];

  useEffect(() => {
    if (!datasetId && selected) navigate(`/p/${project.id}/data/${selected.id}`, { replace: true });
  }, [datasetId, selected, navigate, project.id]);

  const populateDemoHere = async () => {
    setDemoLoading(true);
    setError(null);
    playTick();
    try {
      const files = buildDemoFiles();
      let latestProject = project;
      for (const f of files) {
        const res = await uploadFile(project.id, f, () => {});
        latestProject = res.project;
      }
      playConfirm();
      setProject(latestProject);
    } catch (e) {
      setError(e);
    } finally {
      setDemoLoading(false);
    }
  };

  const uploads = [...project.uploads].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  const fileDatasets = datasets.filter((d) => d.kind === "file");
  const combined = datasets.filter((d) => d.kind !== "file");
  const confirmedLinks = project.links.filter((l) => l.status === "confirmed");

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Data</h1>
          <div className="sub">Upload tables, audit column distributions and quality, and clean issues before analysis.</div>
        </div>

        <div className="row-wrap" style={{ gap: 8 }}>
          {fileDatasets.length >= 2 && confirmedLinks.length > 0 ? (
            <>
              <button className="btn" onClick={() => navigate(`/p/${project.id}/connect`)}>
                Connect files ({confirmedLinks.length})
              </button>
              <button className="btn btn-primary" onClick={() => navigate(`/p/${project.id}/discover`)}>
                Discover patterns →
              </button>
            </>
          ) : fileDatasets.length >= 2 ? (
            <button className="btn btn-primary" onClick={() => navigate(`/p/${project.id}/connect`)}>
              Next: connect files →
            </button>
          ) : datasets.length === 1 ? (
            <button className="btn btn-primary" onClick={() => navigate(`/p/${project.id}/discover`)}>
              Analyze this file →
            </button>
          ) : null}
        </div>
      </div>

      <div className="content">
        {error ? <ErrorBox error={error} /> : null}
        {datasets.length === 0 && project.uploads.length === 0 ? (
          <div className="empty-upload-bento">
            <div className="bento-tile bento-surface-card" style={{ padding: 24 }}>
              <h2 style={{ marginBottom: 6 }}>Upload your first table</h2>
              <p className="muted" style={{ maxWidth: "64ch", marginBottom: 16 }}>
                Drop in 1 table to inspect distributions and anomalies, or upload 2 or more related exports (such as
                customers and orders) to map foreign-key joins automatically. Original files are read locally and never
                modified.
              </p>
              <UploadZone uploader={uploader} />

              <div className="hr" style={{ margin: "18px 0 14px" }} />
              <div className="spread" style={{ flexWrap: "wrap" }}>
                <span className="small muted">Want to test unit alignment, join previews, and Simpson’s paradox right now?</span>
                <button
                  type="button"
                  className="demo-pill-btn"
                  disabled={demoLoading}
                  onClick={() => void populateDemoHere()}
                >
                  <Sparkles size={14} />
                  <span>{demoLoading ? "Loading 3 demo tables…" : "Populate with 3 demo tables"}</span>
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="data-layout">
            <div className="stack">
              <UploadZone uploader={uploader} compact />

              <div className="card">
                <div className="card-head">
                  <h2>Source files</h2>
                  <span className="muted small tabular-nums">{plural(project.uploads.length, "upload")}</span>
                </div>
                <div className="file-list">
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
                    <h2>Derived tables</h2>
                    <span className="muted small tabular-nums">{combined.length}</span>
                  </div>
                  <div className="file-list">
                    {combined.map((d) => (
                      <div
                        key={d.id}
                        role="button"
                        tabIndex={0}
                        className={selected?.id === d.id ? "file active" : "file"}
                        onClick={() => navigate(`/p/${project.id}/data/${d.id}`)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            navigate(`/p/${project.id}/data/${d.id}`);
                          }
                        }}
                      >
                        <FileIcon format={d.kind === "cleaned" ? "clean" : "combined"} />
                        <div className="grow">
                          <div className="row" style={{ gap: 7 }}>
                            <HealthDot health={d.health} />
                            <span style={{ fontWeight: 600, wordBreak: "break-word" }}>{d.name}</span>
                          </div>
                          <div className="muted small tabular-nums">
                            {fmtInt(d.n_rows)} rows · {d.n_cols} cols
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>

            <div style={{ minWidth: 0 }}>
              {selected ? (
                <DatasetView
                  dataset={selected}
                  tab={tab}
                  setTab={setTab}
                  exploreCol={exploreCol}
                  onExploreColumn={(colName) => {
                    setExploreCol(colName);
                    setTab("explore");
                  }}
                />
              ) : (
                <div className="card">
                  <Empty icon={<FileWarning size={20} />} title="No readable tables yet">
                    The uploaded files could not be read. Their errors are listed on the left.
                  </Empty>
                </div>
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
            The workspace’s copy of this file is deleted, together with combined tables and links built from it. Analysis
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
        </div>
        <button
          type="button"
          className="file-remove-btn"
          onClick={onRemove}
          title={`Remove ${upload.filename}`}
          aria-label={`Remove ${upload.filename}`}
        >
          <Trash2 size={13} />
        </button>
      </div>
    );
  }
  return (
    <>
      {datasets.map((d, idx) => (
        <div
          key={d.id}
          role="button"
          tabIndex={0}
          className={selectedId === d.id ? "file active" : "file"}
          onClick={() => onSelect(d.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(d.id);
            }
          }}
        >
          <FileIcon format={upload.format} />
          <div className="grow">
            <div className="row" style={{ gap: 7 }}>
              <HealthDot health={d.health} />
              <span style={{ fontWeight: 600, wordBreak: "break-word" }}>{d.name}</span>
            </div>
            <div className="muted small tabular-nums">
              {fmtInt(d.n_rows)} rows · {d.n_cols} cols · {fmtBytes(upload.size_bytes)}
            </div>
          </div>
          {d.issues.some((i) => i.level === "warning") ? (
            <Badge tone="warn" title="Read with warnings">
              Warning
            </Badge>
          ) : null}
          {idx === 0 ? (
            <button
              type="button"
              className="file-remove-btn"
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              title={`Remove ${upload.filename}`}
              aria-label={`Remove ${upload.filename}`}
            >
              <Trash2 size={13} />
            </button>
          ) : null}
        </div>
      ))}
    </>
  );
}

function DatasetView({
  dataset,
  tab,
  setTab,
  exploreCol,
  onExploreColumn,
}: {
  dataset: Dataset;
  tab: Tab;
  setTab: (t: Tab) => void;
  exploreCol?: string;
  onExploreColumn: (col: string) => void;
}) {
  const { project } = useProject();
  const upload = project.uploads.find((u) => u.id === dataset.upload_id);
  const warnings = dataset.issues.filter((i) => i.level !== "info").length;
  const sources = dataset.sources.map((id) => project.datasets.find((d) => d.id === id)?.name ?? id);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="dataset-header bento-tile bento-surface-card" style={{ padding: "16px 20px 14px" }}>
        <div className="row-wrap" style={{ gap: 8 }}>
          <HealthDot health={dataset.health} size={10} />
          <h2 className="dataset-title">{dataset.name}</h2>
          <Badge tone={dataset.kind === "file" ? "outline" : "info"}>
            {dataset.kind === "combined"
              ? "Combined table"
              : dataset.kind === "cleaned"
                ? "Cleaned table"
                : (upload?.format?.toUpperCase() ?? "File")}
          </Badge>
        </div>

        <div className="muted small tabular-nums" style={{ marginTop: 4 }}>
          <b>{fmtInt(dataset.n_rows)}</b> rows · <b>{dataset.n_cols}</b> columns
          {dataset.kind === "combined"
            ? ` · joined from ${sources.join(" + ")}`
            : dataset.kind === "cleaned"
              ? ` · cleaned from ${sources.join("")}`
              : ""}
          {dataset.health?.reasons.length ? ` · ${dataset.health.reasons.join(" · ")}` : ""}
        </div>

        <div style={{ marginTop: 12 }}>
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            items={[
              { id: "quality", label: "Overview & quality" },
              { id: "explore", label: "Explore & drill" },
              { id: "columns", label: `Columns (${dataset.n_cols})` },
              { id: "preview", label: "Preview rows" },
              { id: "clean", label: "Clean & export" },
              { id: "log", label: `How it was read${warnings ? ` (${warnings})` : ""}` },
            ]}
          />
        </div>
      </div>

      {tab === "quality" ? (
        <QualityPanel
          projectId={project.id}
          dataset={dataset}
          onExploreColumn={onExploreColumn}
        />
      ) : null}
      {tab === "explore" ? (
        <ExploreStudio key={`${dataset.id}:${exploreCol ?? ""}`} projectId={project.id} dataset={dataset} initialX={exploreCol} />
      ) : null}
      {tab === "columns" ? <ColumnsTab dataset={dataset} onExploreColumn={onExploreColumn} /> : null}
      {tab === "preview" ? (
        <div className="card card-pad">
          <DataTable projectId={project.id} datasetId={dataset.id} />
        </div>
      ) : null}
      {tab === "clean" ? <CleanPanel dataset={dataset} /> : null}
      {tab === "log" ? (
        <div className="card card-pad">
          <ParseLog issues={dataset.issues} uploadIssues={upload?.issues ?? []} />
        </div>
      ) : null}
    </div>
  );
}

function ColumnsTab({
  dataset,
  onExploreColumn,
}: {
  dataset: Dataset;
  onExploreColumn: (col: string) => void;
}) {
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
        Column <b>roles</b> govern statistical tests: identifiers, codes, and dates are never analyzed as continuous
        numbers. Click <b>Drill</b> on any column to inspect its distribution and subgroups.
      </Notice>
      {error ? <ErrorBox error={error} /> : null}
      <div className="card" style={{ overflow: "hidden" }}>
        <ColumnProfiles
          projectId={project.id}
          dataset={dataset}
          onRoleChange={change}
          saving={saving}
          onExploreColumn={onExploreColumn}
        />
      </div>
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
        The file was read without any changes: no renamed columns, no unreadable values, no placeholders.{" "}
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
