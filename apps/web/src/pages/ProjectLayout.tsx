import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import {
  ArrowLeft,
  Compass,
  Database,
  FileText,
  GitMerge,
  Keyboard,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Sun,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { CommandPalette } from "../components/CommandPalette";
import { PeekingCompanion, ScrollVernier, useStudioExtras } from "../components/EasterEggs";
import { BrandMark, KBD_SHORTCUT, Tip } from "../components/kit";
import { ErrorBox, Loading } from "../components/ui";
import { api } from "../lib/api";
import { plural } from "../lib/format";
import { isSoundEnabled, playDetent, playTick, setSoundEnabled } from "../lib/sound";
import { useTheme } from "../lib/theme";
import type { Project } from "../lib/types";

interface ProjectContextValue {
  project: Project;
  setProject: (p: Project) => void;
  refresh: () => Promise<void>;
  openCommandPalette: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) throw new Error("useProject outside ProjectLayout");
  return value;
}

export const SECTIONS: { to: string; label: string; icon: typeof Database }[] = [
  { to: "data", label: "Data", icon: Database },
  { to: "connect", label: "Connect", icon: GitMerge },
  { to: "discover", label: "Discover", icon: Compass },
  { to: "report", label: "Report", icon: FileText },
];

export function ProjectLayout({ sections }: { sections: string[] }) {
  const { projectId = "" } = useParams();
  const location = useLocation();
  const reduce = useReducedMotion();
  const { theme, toggleTheme } = useTheme();
  const { openAnscombe, openShortcuts } = useStudioExtras();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [dockExpanded, setDockExpanded] = useState<boolean>(() => {
    try {
      return localStorage.getItem("edaforge-dock-expanded") === "1";
    } catch {
      return false;
    }
  });
  const [scrolled, setScrolled] = useState(false);
  const [soundOn, setSoundOn] = useState(isSoundEnabled);

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

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.pathname]);

  const toggleDock = () => {
    playTick();
    setDockExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("edaforge-dock-expanded", next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const counts: Record<string, number | undefined> = project
    ? {
        data: project.datasets.filter((d) => d.kind === "file").length || undefined,
        connect: project.links.filter((l) => l.status === "confirmed").length || undefined,
        discover: project.runs.length || undefined,
        report: project.runs.filter((r) => r.status === "completed").length || undefined,
      }
    : {};

  const isUniverse = location.pathname.endsWith("/universe");
  const slim = !dockExpanded && !mobileMenuOpen;

  return (
    <div className={`frame-outer studio-shell${slim ? " is-slim" : " is-expanded"}${scrolled ? " is-scrolled" : ""}`}>
      <CommandPalette open={cmdOpen} onOpenChange={setCmdOpen} currentProject={project} />

      {/* Mobile Compact Header (< 920px) */}
      <div className="mobile-studio-bar">
        <Link to="/" className="brand" onClick={() => playTick()}>
          <BrandMark size={26} />
          <span>EDAForge</span>
        </Link>
        <div className="row" style={{ gap: 6 }}>
          <button
            type="button"
            className="icon-circle-btn"
            onClick={() => setCmdOpen(true)}
            aria-label="Open search"
          >
            <Search size={15} />
          </button>
          <button
            type="button"
            className="icon-circle-btn"
            onClick={() => setMobileMenuOpen((v) => !v)}
            aria-label={mobileMenuOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </div>

      {/* RefUI #1 & #4 Floating Slim Pill Dock + Detached Bottom Control Pod */}
      <aside className={`dock-column${mobileMenuOpen ? " is-open" : ""}`}>
        <div className="floating-dock-pill">
          <div className="dock-brand-row">
            <Tip content={slim ? "All workspaces (EDAForge)" : "Return to workspaces"}>
              <Link to="/" className="brand" onClick={() => playTick()} aria-label="EDAForge home">
                <BrandMark size={32} />
                {!slim ? <span>EDAForge</span> : null}
              </Link>
            </Tip>
          </div>

          <Tip content={`Search & jump (${KBD_SHORTCUT})`}>
            <button
              type="button"
              className="dock-cmdk-btn"
              onClick={() => {
                playDetent();
                setCmdOpen(true);
              }}
              aria-label="Search workspaces and commands"
            >
              <Search size={15} />
              {!slim ? (
                <>
                  <span className="grow">Search…</span>
                  <kbd className="cmdk-kbd">{KBD_SHORTCUT}</kbd>
                </>
              ) : null}
            </button>
          </Tip>

          {project && !slim ? (
            <div className="dock-workspace-tile">
              <div className="name">{project.name}</div>
              <div className="side-project-stats">
                {plural(project.datasets.length, "table")} · {plural(project.runs.length, "run")}
              </div>
              <Link to="/" className="back-link">
                <ArrowLeft size={12} /> All workspaces
              </Link>
            </div>
          ) : project ? (
            <Tip content={`${project.name} — All workspaces`}>
              <Link to="/" className="dock-back-pill" aria-label="All workspaces">
                <ArrowLeft size={15} />
              </Link>
            </Tip>
          ) : null}

          <nav className="dock-nav" aria-label="Workspace navigation">
            {SECTIONS.filter((s) => sections.includes(s.to)).map((s) => {
              const Icon = s.icon;
              const c = counts[s.to];
              const basePath = `/p/${projectId}/${s.to}`;
              const isActive =
                location.pathname === basePath || location.pathname.startsWith(`${basePath}/`);
              return (
                <Tip key={s.to} content={`${s.label}${c ? ` (${c})` : ""}`}>
                  <Link
                    to={basePath}
                    onClick={() => playDetent()}
                    aria-label={s.label}
                    aria-current={isActive ? "page" : undefined}
                    className={isActive ? "dock-nav-item active" : "dock-nav-item"}
                  >
                    {isActive ? (
                      <motion.span
                        layoutId="dock-active-pill"
                        className="dock-active-bg"
                        transition={
                          reduce
                            ? { duration: 0 }
                            : { type: "spring", stiffness: 420, damping: 32, mass: 0.65 }
                        }
                      />
                    ) : null}
                    <span className="nav-label">
                      <span className="dock-icon-box">
                        <Icon size={16} />
                      </span>
                      {slim ? <span className="sr-only">{s.label}</span> : <span>{s.label}</span>}
                    </span>
                    {c ? <span className="count">{c}</span> : null}
                  </Link>
                </Tip>
              );
            })}
          </nav>

          <div className="dock-expand-row">
            <Tip content={slim ? "Expand sidebar labels" : "Collapse to slim icon dock"}>
              <button
                type="button"
                className="dock-expand-btn"
                onClick={toggleDock}
                aria-label={slim ? "Expand navigation dock" : "Collapse navigation dock"}
              >
                {slim ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
                {!slim ? <span>Slim dock</span> : null}
              </button>
            </Tip>
          </div>
        </div>

        {/* Detached Bottom Squircle Control Pod (RefUI #1 & #4 signature bottom-left pod!) */}
        <div className="dock-detached-pod" role="group" aria-label="Studio preferences">
          <Tip content={`Switch to ${theme === "dark" ? "Light Mineral" : "Dark Petrol"} Bento (Shift+T)`}>
            <button
              type="button"
              className="dock-pod-btn primary-pod"
              onClick={() => {
                playTick(1.1);
                toggleTheme();
              }}
              aria-label="Toggle color theme"
            >
              {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
              {!slim ? <span>{theme === "dark" ? "Light" : "Dark"}</span> : null}
            </button>
          </Tip>

          <div className={slim ? "dock-pod-subrow" : "row"} style={{ gap: 6 }}>
            <Tip content="Keyboard shortcuts (?)">
              <button
                type="button"
                className="dock-pod-btn"
                onClick={() => {
                  playTick();
                  openShortcuts();
                }}
                aria-label="Keyboard shortcuts"
              >
                <Keyboard size={14} />
              </button>
            </Tip>

            <Tip content={soundOn ? "Mute subtle UI clicks" : "Enable subtle UI clicks"}>
              <button
                type="button"
                className={`dock-pod-btn${soundOn ? " active" : ""}`}
                onClick={() => {
                  const next = !soundOn;
                  setSoundEnabled(next);
                  setSoundOn(next);
                  if (next) playTick(1.2);
                }}
                aria-label="Toggle UI sound"
                aria-pressed={soundOn}
              >
                {soundOn ? <Volume2 size={14} /> : <VolumeX size={14} />}
              </button>
            </Tip>
          </div>
        </div>
      </aside>

      {mobileMenuOpen ? (
        <div className="mobile-dock-backdrop" onClick={() => setMobileMenuOpen(false)} aria-hidden="true" />
      ) : null}

      {/* Main Rounded Stage Window */}
      <main className={`stage-window${isUniverse ? " is-universe" : ""}`}>
        {!isUniverse ? <PeekingCompanion onOpenAnscombe={openAnscombe} /> : null}
        {!isUniverse ? <ScrollVernier /> : null}

        {error ? (
          <div className="content" style={{ paddingTop: 24 }}>
            <ErrorBox error={error} onRetry={() => void refresh()} />
          </div>
        ) : !project ? (
          <Loading label="Opening workspace…" />
        ) : (
          <ProjectContext.Provider
            value={{
              project,
              setProject,
              refresh,
              openCommandPalette: () => setCmdOpen(true),
            }}
          >
            <motion.div
              key={location.pathname.split("/").slice(0, 4).join("/")}
              initial={reduce ? false : { y: 5 }}
              animate={{ y: 0 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
              className="stage-route-inner"
            >
              <Outlet />
            </motion.div>
          </ProjectContext.Provider>
        )}
      </main>
    </div>
  );
}
