import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import type { Project } from "../lib/types";

interface ProjectContextValue {
  project: Project;
  setProject: (p: Project) => void;
  refresh: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) throw new Error("useProject outside ProjectLayout");
  return value;
}

export const SECTIONS: { to: string; label: string; step: number }[] = [
  { to: "data", label: "Data", step: 1 },
  { to: "connect", label: "Connect", step: 2 },
  { to: "discover", label: "Discover", step: 3 },
  { to: "report", label: "Report", step: 4 },
];

export function ProjectLayout({ sections }: { sections: string[] }) {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<unknown>(null);

  const refresh = useCallback(async () => {
    try {
      setProject(await api.getProject(projectId));
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [projectId]);

  useEffect(() => {
    setProject(null);
    void refresh();
  }, [refresh]);

  const counts: Record<string, number | undefined> = project
    ? {
        data: project.datasets.filter((d) => d.kind === "file").length,
        connect: project.links.filter((l) => l.status === "confirmed").length,
        discover: project.runs.length,
      }
    : {};

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="brand" style={{ textDecoration: "none" }}>
          <img className="brand-logo" src="/appicon.png" alt="EDAForge icon" />
          <span>
            EDAForge
            <small>of statistics</small>
          </span>
        </Link>
        {project ? (
          <div className="side-project">
            <div className="name">{project.name}</div>
            <div className="meta">
              <Link to="/" style={{ color: "#a5a9d6" }}>
                ← All workspaces
              </Link>
            </div>
          </div>
        ) : null}
        <div className="side-section">Workflow</div>
        <nav className="nav">
          {SECTIONS.filter((s) => sections.includes(s.to)).map((s) => (
            <NavLink key={s.to} to={`/p/${projectId}/${s.to}`} className={({ isActive }) => (isActive ? "active" : "")}>
              <span>
                <span className="step">{s.step}</span>
                {s.label}
              </span>
              {counts[s.to] ? <span className="count">{counts[s.to]}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="foot">Local-first: data never leaves this computer.</div>
      </aside>
      <main className="main">
        {error ? (
          <div className="content" style={{ paddingTop: 24 }}>
            <ErrorBox error={error} onRetry={() => void refresh()} />
          </div>
        ) : !project ? (
          <Loading label="Opening workspace…" />
        ) : (
          <ProjectContext.Provider value={{ project, setProject, refresh }}>
            <Outlet />
          </ProjectContext.Provider>
        )}
      </main>
    </div>
  );
}
