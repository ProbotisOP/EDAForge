import { useCallback, useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SparkLineChart } from "@mui/x-charts/SparkLineChart";
import {
  ArrowUpRight,
  Database,
  FlaskConical,
  FolderOpen,
  Keyboard,
  Moon,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Sun,
  Trash2,
  Volume2,
  VolumeX,
} from "lucide-react";
import { CommandPalette } from "../components/CommandPalette";
import { PeekingCompanion, ScrollVernier, useStudioExtras } from "../components/EasterEggs";
import { HomeShowcase } from "../components/HomeShowcase";
import { BrandMark, KBD_SHORTCUT, Tip } from "../components/kit";
import { Badge, Empty, ErrorBox, Loading, Modal } from "../components/ui";
import { api } from "../lib/api";
import { createDemoWorkspace } from "../lib/demoData";
import { fmtDate, fmtInt, plural } from "../lib/format";
import { isSoundEnabled, playConfirm, playDetent, playTick, setSoundEnabled } from "../lib/sound";
import { useTheme } from "../lib/theme";
import type { ProjectSummary } from "../lib/types";

const WORKSPACE_TONES = ["bento-surface-card", "bento-sage-soft", "bento-sky-soft", "bento-sand-soft"] as const;

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [demoStep, setDemoStep] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null);
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null);
  const [newName, setNewName] = useState("");
  const [cmdOpen, setCmdOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [soundOn, setSoundOn] = useState(isSoundEnabled);
  const { theme, toggleTheme } = useTheme();
  const { openAnscombe, openShortcuts } = useStudioExtras();
  const navigate = useNavigate();
  const heroSparkGradId = useId().replace(/:/g, "");

  const load = useCallback(() => {
    setError(null);
    api.listProjects().then(setProjects).catch(setError);
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 18);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const create = async () => {
    const finalName = name.trim() || `Workspace ${(projects?.length ?? 0) + 1}`;
    setBusy(true);
    playTick();
    try {
      const project = await api.createProject(finalName);
      playConfirm();
      navigate(`/p/${project.id}/data`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const launchDemo = async () => {
    if (demoStep) return;
    setError(null);
    playTick();
    try {
      const id = await createDemoWorkspace((step) => setDemoStep(step));
      playConfirm();
      navigate(`/p/${id}/data`);
    } catch (e) {
      setError(e);
      setDemoStep(null);
    }
  };

  const totalTables = (projects ?? []).reduce((s, p) => s + p.n_datasets, 0);
  const totalFindings = (projects ?? []).reduce(
    (s, p) => s + (p.latest_run?.status === "completed" ? (p.latest_run.n_findings ?? 0) : 0),
    0,
  );
  const latestWithRun = (projects ?? []).find((p) => p.latest_run?.status === "completed");
  const sparkColor = theme === "dark" ? "#156570" : "#5EEAD4";
  const sparkSeries =
    projects && projects.length >= 3
      ? projects
          .slice(0, 8)
          .reverse()
          .map((p, i) => Math.max(2, p.n_datasets * 3 + (p.latest_run?.n_findings ?? i + 1)))
      : [4, 7, 6, 11, 14, 13, 19, 24];

  return (
    <div className="frame-outer home-frame">
      <CommandPalette open={cmdOpen} onOpenChange={setCmdOpen} />

      <div className="home-stage-window">
        <ScrollVernier />
        <PeekingCompanion onOpenAnscombe={openAnscombe} />

        <header className={`home-bar${scrolled ? " is-scrolled" : ""}`}>
          <div className="brand">
            <BrandMark size={30} />
            <span>EDAForge</span>
          </div>

          <div className="row-wrap" style={{ gap: 8 }}>
            <button
              type="button"
              className="search-pill-btn"
              onClick={() => {
                playDetent();
                setCmdOpen(true);
              }}
            >
              <Search size={14} />
              <span>Search workspaces &amp; labs…</span>
              <kbd className="cmdk-kbd">{KBD_SHORTCUT}</kbd>
            </button>

            <Tip content="Keyboard shortcuts (?)">
              <button
                type="button"
                className="icon-circle-btn"
                onClick={() => {
                  playTick();
                  openShortcuts();
                }}
                aria-label="Keyboard shortcuts"
              >
                <Keyboard size={15} />
              </button>
            </Tip>

            <Tip content={soundOn ? "Mute tactile UI clicks" : "Enable tactile UI clicks"}>
              <button
                type="button"
                className={`icon-circle-btn${soundOn ? " active" : ""}`}
                onClick={() => {
                  const next = !soundOn;
                  setSoundEnabled(next);
                  setSoundOn(next);
                  if (next) playTick(1.2);
                }}
                aria-label="Toggle UI sound"
                aria-pressed={soundOn}
              >
                {soundOn ? <Volume2 size={15} /> : <VolumeX size={15} />}
              </button>
            </Tip>

            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                playTick();
                toggleTheme();
              }}
              aria-label="Toggle color theme"
            >
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
              <span>{theme === "dark" ? "Light" : "Dark"}</span>
            </button>
          </div>
        </header>

        <div className="home-body">
          {/* FIRST VIEWPORT: ASYMMETRIC BENTO LAUNCHPAD */}
          <section className="hero-bento-grid" aria-label="Start a workspace">
            <div className="bento-tile hero-launch-tile bento-surface-card">
              <h1>Audit, join, and verify your data locally</h1>
              <p className="hero-copy">
                Drop in CSV, Excel, Parquet, SQLite, or DuckDB files to profile column health, preview foreign-key
                joins before rows multiply, and confirm patterns on held-out splits. Nothing leaves this computer.
              </p>

              <form
                className="create-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void create();
                }}
              >
                <input
                  type="text"
                  placeholder="Workspace name, e.g. Q4 churn & orders audit"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  aria-label="Workspace name"
                  maxLength={120}
                />
                <button className="btn btn-primary btn-hero" disabled={busy} type="submit">
                  <Plus size={16} />
                  <span>{busy ? "Creating…" : "Create workspace"}</span>
                </button>
              </form>

              <div className="hero-quick-row">
                <button
                  type="button"
                  className="demo-pill-btn"
                  disabled={demoStep !== null}
                  onClick={() => void launchDemo()}
                >
                  <Sparkles size={14} />
                  <span>{demoStep ?? "Load 3-table demo dataset (US + EU + Orders)"}</span>
                </button>
                <span className="small muted">Stored read-only in ~/.edaforge</span>
              </div>
            </div>

            <div className="hero-side-stack">
              {/* Interactive MUI X SparkLineChart Telemetry Bento Card */}
              <div className="bento-tile hero-telemetry-tile bento-alabaster-contrast">
                <div className="spread">
                  <span className="bento-tile-title">Local studio index</span>
                  <span className="bento-icon-circle on-tinted">
                    <Database size={15} />
                  </span>
                </div>

                <div className="telemetry-stats-row">
                  <div>
                    <div className="bento-big-num tabular-nums">{projects ? fmtInt(projects.length) : "—"}</div>
                    <div className="bento-tile-sub">Workspaces</div>
                  </div>
                  <div>
                    <div className="bento-mid-num tabular-nums">{projects ? fmtInt(totalTables) : "—"}</div>
                    <div className="bento-tile-sub">Tables</div>
                  </div>
                  <div>
                    <div className="bento-mid-num tabular-nums">{projects ? fmtInt(totalFindings) : "—"}</div>
                    <div className="bento-tile-sub">Verified findings</div>
                  </div>
                </div>

                <div className="telemetry-wave-host">
                  <SparkLineChart
                    plotType="line"
                    area
                    curve="natural"
                    height={68}
                    margin={{ top: 6, bottom: 0, left: 0, right: 0 }}
                    data={sparkSeries}
                    color={sparkColor}
                    showTooltip
                    showHighlight
                    valueFormatter={(v) => (v === null ? "" : `Activity index: ${v}`)}
                    sx={{
                      "& .MuiAreaElement-root": {
                        fill: `url(#hero-spark-${heroSparkGradId})`,
                      },
                      "& .MuiLineElement-root": {
                        strokeWidth: 2.4,
                      },
                    }}
                  >
                    <defs>
                      <linearGradient id={`hero-spark-${heroSparkGradId}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={sparkColor} stopOpacity={0.38} />
                        <stop offset="100%" stopColor={sparkColor} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                  </SparkLineChart>
                </div>
              </div>

              <div className="hero-mini-duo">
                {latestWithRun && latestWithRun.latest_run ? (
                  <button
                    type="button"
                    className="bento-tile bento-sage bento-action-tile"
                    onClick={() => {
                      playTick();
                      navigate(`/p/${latestWithRun.id}/discover/runs/${latestWithRun.latest_run!.id}`);
                    }}
                  >
                    <div className="spread">
                      <span className="bento-action-name">{latestWithRun.name}</span>
                      <ArrowUpRight size={15} />
                    </div>
                    <div className="small tabular-nums" style={{ opacity: 0.86 }}>
                      Latest run · {latestWithRun.latest_run.n_findings ?? 0} graded findings →
                    </div>
                  </button>
                ) : (
                  <div className="bento-tile bento-sage bento-action-tile" style={{ cursor: "default" }}>
                    <div className="bento-action-name">FDR + Holdout</div>
                    <div className="small" style={{ opacity: 0.86 }}>Grades A–E · 0 p-hacking</div>
                  </div>
                )}

                <button
                  type="button"
                  className="bento-tile bento-sky bento-action-tile"
                  onClick={() => {
                    playDetent();
                    openAnscombe();
                  }}
                >
                  <div className="spread">
                    <span className="bento-action-name">Anscombe’s Quartet</span>
                    <FlaskConical size={15} />
                  </div>
                  <div className="small" style={{ opacity: 0.86 }}>Same stats, 5 wild plots →</div>
                </button>
              </div>
            </div>
          </section>

          {error ? <ErrorBox error={error} onRetry={load} /> : null}
          {projects === null && !error ? <Loading label="Loading workspaces…" /> : null}

          {projects && projects.length === 0 ? (
            <div className="bento-tile bento-surface-card">
              <Empty icon={<FolderOpen size={22} />} title="No workspaces on this machine yet">
                Name a new workspace above, or click <b>Load 3-table demo dataset</b> to explore planted unit
                mismatches, foreign-key joins, and Simpson’s paradox right away.
              </Empty>
            </div>
          ) : null}

          {projects && projects.length > 0 ? (
            <section className="workspaces-section" aria-labelledby="workspaces-heading">
              <div className="spread" style={{ marginBottom: 14 }}>
                <h2 id="workspaces-heading">Your workspaces ({projects.length})</h2>
                <span className="small muted">Click any tile to open its workbench</span>
              </div>

              <div className="workspaces-bento-grid">
                {projects.map((p, idx) => {
                  const findingsCount = p.latest_run?.status === "completed" ? (p.latest_run.n_findings ?? 0) : null;
                  const toneClass = WORKSPACE_TONES[idx % WORKSPACE_TONES.length];
                  return (
                    <article
                      key={p.id}
                      className={`bento-tile workspace-bento-card bento-hit ${toneClass}`}
                      onClick={() => {
                        playTick();
                        navigate(`/p/${p.id}/data`);
                      }}
                    >
                      <div className="bento-inner">
                        <div className="spread" style={{ alignItems: "flex-start", gap: 10 }}>
                          <Link
                            to={`/p/${p.id}/data`}
                            className="workspace-title"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {p.name}
                          </Link>
                          {p.latest_run ? (
                            <Badge tone={p.latest_run.status === "completed" ? "ok" : "info"}>
                              {p.latest_run.status === "completed"
                                ? `${findingsCount} ${findingsCount === 1 ? "finding" : "findings"}`
                                : `Run ${p.latest_run.status}`}
                            </Badge>
                          ) : null}
                        </div>

                        <div className="workspace-stat-pills tabular-nums">
                          <span>{plural(p.n_uploads, "file")}</span>
                          <span>·</span>
                          <span>{plural(p.n_datasets, "table")}</span>
                          {p.n_failed_uploads ? (
                            <>
                              <span>·</span>
                              <span style={{ color: "var(--bad)" }}>{p.n_failed_uploads} failed</span>
                            </>
                          ) : null}
                        </div>

                        <div className="workspace-card-foot" onClick={(e) => e.stopPropagation()}>
                          <span className="tiny muted tabular-nums">Updated {fmtDate(p.updated_at)}</span>
                          <div className="row" style={{ gap: 4 }}>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => {
                                playTick();
                                navigate(`/p/${p.id}/data`);
                              }}
                            >
                              Open
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() => {
                                setRenaming(p);
                                setNewName(p.name);
                              }}
                              title="Rename workspace"
                              aria-label={`Rename ${p.name}`}
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost danger-hover"
                              onClick={() => setDeleting(p)}
                              title="Delete workspace"
                              aria-label={`Delete ${p.name}`}
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}

          {/* SCROLL-CHOREOGRAPHED INTERACTIVE BENTO SHOWCASE */}
          <HomeShowcase onTryDemo={() => void launchDemo()} demoBusy={demoStep !== null} />
        </div>

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
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              style={{ width: "100%" }}
              aria-label="New name"
            />
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
              This removes the workspace’s stored copies of {plural(deleting.n_uploads, "uploaded file")}, every
              combined table, and every analysis run from this computer. Your original files elsewhere are not touched.
            </p>
          </Modal>
        ) : null}
      </div>
    </div>
  );
}
