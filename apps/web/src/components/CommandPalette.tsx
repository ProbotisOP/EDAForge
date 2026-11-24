import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import {
  BarChart3,
  Compass,
  Database,
  FileText,
  FlaskConical,
  FolderKanban,
  GitMerge,
  Keyboard,
  Moon,
  Network,
  Search,
  Sparkles,
  Sun,
  Volume2,
  VolumeX,
} from "lucide-react";
import { api } from "../lib/api";
import { createDemoWorkspace } from "../lib/demoData";
import { fmtInt } from "../lib/format";
import { isSoundEnabled, playConfirm, playDetent, playTick, setSoundEnabled } from "../lib/sound";
import { useTheme } from "../lib/theme";
import type { Project, ProjectSummary } from "../lib/types";
import { useStudioExtras } from "./EasterEggs";

export function CommandPalette({
  open,
  onOpenChange,
  currentProject,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  currentProject?: Project | null;
}) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const { openAnscombe, openShortcuts } = useStudioExtras();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [soundOn, setSoundOn] = useState(isSoundEnabled);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        playDetent();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!open) return;
    setSoundOn(isSoundEnabled());
    api
      .listProjects()
      .then(setProjects)
      .catch(() => {});
  }, [open]);

  const run = (fn: () => void) => {
    playTick();
    onOpenChange(false);
    fn();
  };

  const completedRuns = currentProject?.runs.filter((r) => r.status === "completed") ?? [];

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="cmdk-overlay" />
        <Dialog.Content className="cmdk-dialog" aria-label="Command palette">
          <Dialog.Title className="sr-only">Command Palette</Dialog.Title>
          <Command className="cmdk-root" loop>
            <div className="cmdk-input-wrap">
              <Search size={15} className="cmdk-search-icon" />
              <Command.Input
                placeholder={
                  currentProject
                    ? `Jump to tables, runs, or tools in ${currentProject.name}…`
                    : "Jump to workspaces, demo data, themes, or secret labs…"
                }
                className="cmdk-input"
              />
              <kbd className="cmdk-kbd">ESC</kbd>
            </div>

            <Command.List className="cmdk-list">
              <Command.Empty className="cmdk-empty">No matching commands, workspaces, or tables.</Command.Empty>

              {currentProject ? (
                <Command.Group heading={currentProject.name} className="cmdk-group">
                  <Command.Item
                    className="cmdk-item"
                    onSelect={() => run(() => navigate(`/p/${currentProject.id}/data`))}
                  >
                    <Database size={14} />
                    <span>Data — Upload, profile, and clean tables</span>
                  </Command.Item>
                  <Command.Item
                    className="cmdk-item"
                    onSelect={() => run(() => navigate(`/p/${currentProject.id}/connect`))}
                  >
                    <GitMerge size={14} />
                    <span>Connect — Join and stack related tables</span>
                  </Command.Item>
                  <Command.Item
                    className="cmdk-item"
                    onSelect={() => run(() => navigate(`/p/${currentProject.id}/discover`))}
                  >
                    <Compass size={14} />
                    <span>Discover — Find and verify patterns</span>
                  </Command.Item>
                  <Command.Item
                    className="cmdk-item"
                    onSelect={() => run(() => navigate(`/p/${currentProject.id}/report`))}
                  >
                    <FileText size={14} />
                    <span>Report — Export HTML, CSV, and JSON</span>
                  </Command.Item>
                </Command.Group>
              ) : null}

              {currentProject && currentProject.datasets.length > 0 ? (
                <Command.Group heading="Tables in Workspace" className="cmdk-group">
                  {currentProject.datasets.map((ds) => (
                    <Command.Item
                      key={ds.id}
                      value={`table ${ds.name} ${ds.kind}`}
                      className="cmdk-item"
                      onSelect={() => run(() => navigate(`/p/${currentProject.id}/data/${ds.id}`))}
                    >
                      <BarChart3 size={14} />
                      <span className="grow">{ds.name}</span>
                      <span className="cmdk-meta mono">{fmtInt(ds.n_rows)} rows</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ) : null}

              {currentProject && completedRuns.length > 0 ? (
                <Command.Group heading="Completed Analysis Runs" className="cmdk-group">
                  {completedRuns.slice(0, 5).map((r) => (
                    <Command.Item
                      key={r.id}
                      value={`run ${String(r.summary.dataset ?? r.id)} insight feed`}
                      className="cmdk-item"
                      onSelect={() => run(() => navigate(`/p/${currentProject.id}/discover/runs/${r.id}`))}
                    >
                      <Compass size={14} />
                      <span className="grow">Insight Feed: {String(r.summary.dataset ?? r.id)}</span>
                      <span className="cmdk-meta mono">{r.summary.n_findings ?? 0} findings</span>
                    </Command.Item>
                  ))}
                  <Command.Item
                    value="data universe network matrix 3d"
                    className="cmdk-item"
                    onSelect={() =>
                      run(() => navigate(`/p/${currentProject.id}/discover/runs/${completedRuns[0].id}/universe`))
                    }
                  >
                    <Network size={14} />
                    <span>Open Data Universe &amp; Association Matrix</span>
                  </Command.Item>
                </Command.Group>
              ) : null}

              <Command.Group heading="Workspaces & Demo" className="cmdk-group">
                <Command.Item className="cmdk-item" onSelect={() => run(() => navigate("/"))}>
                  <FolderKanban size={14} />
                  <span>All Workspaces Launchpad</span>
                </Command.Item>
                <Command.Item
                  value="create demo workspace sample dataset us eu orders"
                  className="cmdk-item"
                  onSelect={() =>
                    run(() => {
                      void createDemoWorkspace().then((id) => {
                        playConfirm();
                        navigate(`/p/${id}/data`);
                      });
                    })
                  }
                >
                  <Sparkles size={14} />
                  <span>Create 3-Table Demo Workspace (US + EU + Orders)</span>
                </Command.Item>
                {projects.slice(0, 8).map((p) => (
                  <Command.Item
                    key={p.id}
                    value={`workspace ${p.name}`}
                    className="cmdk-item"
                    onSelect={() => run(() => navigate(`/p/${p.id}/data`))}
                  >
                    <FolderKanban size={14} />
                    <span className="grow">{p.name}</span>
                    <span className="cmdk-meta mono">{p.n_datasets} tables</span>
                  </Command.Item>
                ))}
              </Command.Group>

              <Command.Group heading="Studio & Secret Labs" className="cmdk-group">
                <Command.Item
                  value="anscombe quartet paradox secret lab easter egg datasaurus"
                  className="cmdk-item"
                  onSelect={() => run(() => openAnscombe())}
                >
                  <FlaskConical size={14} />
                  <span>Open Anscombe’s Quartet &amp; Paradox Lab</span>
                  <span className="cmdk-meta mono">Shift A</span>
                </Command.Item>
                <Command.Item
                  value="keyboard shortcuts help chords"
                  className="cmdk-item"
                  onSelect={() => run(() => openShortcuts())}
                >
                  <Keyboard size={14} />
                  <span>Show Keyboard Shortcuts &amp; Chords</span>
                  <span className="cmdk-meta mono">?</span>
                </Command.Item>
                <Command.Item
                  className="cmdk-item"
                  onSelect={() => run(() => toggleTheme())}
                >
                  {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                  <span>Switch to {theme === "dark" ? "Light Mineral" : "Dark Petrol"} Bento</span>
                  <span className="cmdk-meta mono">Shift T</span>
                </Command.Item>
                <Command.Item
                  className="cmdk-item"
                  onSelect={() =>
                    run(() => {
                      const next = !soundOn;
                      setSoundEnabled(next);
                      setSoundOn(next);
                    })
                  }
                >
                  {soundOn ? <VolumeX size={14} /> : <Volume2 size={14} />}
                  <span>{soundOn ? "Mute" : "Enable"} tactile audio detents</span>
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
