import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, Modal } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, plural } from "../lib/format";
import type { ProjectSummary } from "../lib/types";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null);
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [newName, setNewName] = useState("");
  const navigate = useNavigate();

  const load = useCallback(() => {
    setError(null);
    api.listProjects().then(setProjects).catch(setError);
  }, []);
  useEffect(load, [load]);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const project = await api.createProject(name.trim());
      navigate(`/p/${project.id}/data`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page-narrow">
      <div className="hero">
        <div className="row" style={{ gap: 12, alignItems: "center" }}>
          <img className="hero-logo" src="/appicon.png" alt="EDAForge icon" />
          <h1>EDAForge</h1>
        </div>
        <p>
          Upload your files. EDAForge shows how they relate, what looks wrong, what patterns may be hidden, and how strong
          the evidence is — and it never pretends that correlation proves causation.
        </p>
        <div className="journey">
          {["Upload", "Profile", "Connect", "Discover", "Validate", "Explain", "Export"].map((s, i) => (
            <span key={s}>
              {i + 1}. {s}
            </span>
          ))}
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <h2 style={{ marginBottom: 10 }}>Start a workspace</h2>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <input
            type="text"
            placeholder="Workspace name, e.g. Q3 churn review"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: 1 }}
            aria-label="Workspace name"
            maxLength={120}
          />
          <button className="btn btn-primary" disabled={!name.trim() || busy} type="submit">
            Create workspace
          </button>
        </form>
        <div className="muted small mt">Everything stays on this computer: uploads, results and reports are stored locally.</div>
      </div>

      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      {projects === null && !error ? <Loading label="Loading workspaces…" /> : null}
      {projects && projects.length === 0 ? (
        <div className="card">
          <Empty icon="🗂" title="No workspaces yet">
            Create one above, then upload two or more related files to see how they connect.
          </Empty>
        </div>
      ) : null}
      {projects && projects.length > 0 ? (
        <>
          <h2 style={{ margin: "6px 0 12px" }}>Your workspaces</h2>
          <div className="project-grid">
            {projects.map((p) => (
              <div key={p.id} className="card project-card">
                <div className="spread">
                  <Link to={`/p/${p.id}/data`}>
                    <h3>{p.name}</h3>
                  </Link>
                  {p.latest_run ? (
                    <Badge tone={p.latest_run.status === "completed" ? "ok" : "gray"}>
                      {p.latest_run.status === "completed"
                        ? `${p.latest_run.n_findings ?? 0} findings`
                        : `run ${p.latest_run.status}`}
                    </Badge>
                  ) : null}
                </div>
                <div className="muted small">
                  {plural(p.n_uploads, "file")} · {plural(p.n_datasets, "table")}
                  {p.n_failed_uploads ? ` · ${p.n_failed_uploads} failed` : ""}
                </div>
                <div className="faint small">Updated {fmtDate(p.updated_at)}</div>
                <div className="row" style={{ marginTop: 4 }}>
                  <button className="btn btn-sm btn-primary" onClick={() => navigate(`/p/${p.id}/data`)}>
                    Open
                  </button>
                  <button
                    className="btn btn-sm"
                    onClick={() => {
                      setRenaming(p);
                      setNewName(p.name);
                    }}
                  >
                    Rename
                  </button>
                  <button className="btn btn-sm btn-danger" onClick={() => setDeleting(p)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}

      {renaming ? (
        <Modal
          title="Rename workspace"
          onClose={() => setRenaming(null)}
          actions={
            <>
              <button className="btn" onClick={() => setRenaming(null)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={!newName.trim()}
                onClick={async () => {
                  try {
                    await api.renameProject(renaming.id, newName.trim());
                    setRenaming(null);
                    load();
                  } catch (e) {
                    setError(e);
                  }
                }}
              >
                Save
              </button>
            </>
          }
        >
          <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: "100%" }} aria-label="New name" />
        </Modal>
      ) : null}
      {deleting ? (
        <Modal
          title={`Delete “${deleting.name}”?`}
          onClose={() => setDeleting(null)}
          actions={
            <>
              <button className="btn" onClick={() => setDeleting(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={async () => {
                  try {
                    await api.deleteProject(deleting.id);
                    setDeleting(null);
                    load();
                  } catch (e) {
                    setError(e);
                  }
                }}
              >
                Delete workspace
              </button>
            </>
          }
        >
          <p>
            This removes the workspace's stored copies of {plural(deleting.n_uploads, "uploaded file")}, every combined
            table and every analysis run from this computer. Your original files elsewhere are not touched.
          </p>
        </Modal>
      ) : null}
    </div>
  );
}
