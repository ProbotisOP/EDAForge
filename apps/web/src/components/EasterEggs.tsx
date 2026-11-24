import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { motion, useReducedMotion, useScroll, useSpring } from "motion/react";
import { Eye, EyeOff, FlaskConical, Keyboard, Sparkles, X } from "lucide-react";
import { playConfirm, playDetent, playTick } from "../lib/sound";
import { useTheme } from "../lib/theme";

interface StudioExtrasValue {
  openAnscombe: () => void;
  openShortcuts: () => void;
  registerBrandClick: () => void;
}

const StudioExtrasContext = createContext<StudioExtrasValue>({
  openAnscombe: () => {},
  openShortcuts: () => {},
  registerBrandClick: () => {},
});

export function useStudioExtras(): StudioExtrasValue {
  return useContext(StudioExtrasContext);
}

export function StudioExtrasProvider({ children }: { children: ReactNode }) {
  const [anscombeOpen, setAnscombeOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const { toggleTheme } = useTheme();
  const location = useLocation();
  const clickTimes = useRef<number[]>([]);

  const projectMatch = /^\/p\/([^/]+)/.exec(location.pathname);
  const currentProjectId = projectMatch ? decodeURIComponent(projectMatch[1]) : undefined;

  const registerBrandClick = () => {
    const now = Date.now();
    clickTimes.current = [...clickTimes.current.filter((t) => now - t < 2400), now];
    if (clickTimes.current.length >= 5) {
      clickTimes.current = [];
      playConfirm();
      setAnscombeOpen(true);
    }
  };

  return (
    <StudioExtrasContext.Provider
      value={{
        openAnscombe: () => setAnscombeOpen(true),
        openShortcuts: () => setShortcutsOpen(true),
        registerBrandClick,
      }}
    >
      {children}
      <AnscombeModal open={anscombeOpen} onClose={() => setAnscombeOpen(false)} />
      <ShortcutsController
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
        onToggleTheme={toggleTheme}
        onOpenAnscombe={() => setAnscombeOpen(true)}
        projectId={currentProjectId}
      />
    </StudioExtrasContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// 1. Live Scroll-Vernier Progress Rail
// ---------------------------------------------------------------------------
export function ScrollVernier() {
  const { scrollYProgress } = useScroll();
  const reduce = useReducedMotion();
  const [visible, setVisible] = useState(false);
  const smooth = useSpring(scrollYProgress, {
    stiffness: 260,
    damping: 32,
    restDelta: 0.001,
  });

  useEffect(() => {
    const update = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setVisible(max > 24 && window.scrollY > 6);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <div className="scroll-vernier-track" style={{ opacity: visible ? 1 : 0 }} aria-hidden="true">
      <motion.div
        className="scroll-vernier-bar"
        style={{ scaleX: reduce ? scrollYProgress : smooth }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Anscombe's Quartet & Paradox Secret Lab (Easter Egg #1)
// ---------------------------------------------------------------------------
type DatasetId = "I" | "II" | "III" | "IV" | "RING";

const QUARTET: Record<
  DatasetId,
  {
    name: string;
    subtitle: string;
    lesson: string;
    points: [number, number][];
  }
> = {
  I: {
    name: "Set I · Clean Linear",
    subtitle: "Well-behaved noisy linear trend",
    lesson: "Here OLS regression (y = 3.00 + 0.50x) genuinely describes the underlying relationship.",
    points: [
      [10, 8.04],
      [8, 6.95],
      [13, 7.58],
      [9, 8.81],
      [11, 8.33],
      [14, 9.96],
      [6, 7.24],
      [4, 4.26],
      [12, 10.84],
      [7, 4.82],
      [5, 5.68],
    ],
  },
  II: {
    name: "Set II · Exact Parabola",
    subtitle: "Deterministic non-linear curve",
    lesson: "Identical r = 0.816 and mean, yet a linear model misses the 100% deterministic curvature.",
    points: [
      [10, 9.14],
      [8, 8.14],
      [13, 8.74],
      [9, 8.77],
      [11, 9.26],
      [14, 8.1],
      [6, 6.13],
      [4, 3.1],
      [12, 9.13],
      [7, 7.26],
      [5, 4.74],
    ],
  },
  III: {
    name: "Set III · Single Outlier",
    subtitle: "Tight line dragged by 1 bad record",
    lesson: "1 corrupted export row (x = 13, y = 12.74) warps both the slope and standard error.",
    points: [
      [10, 7.46],
      [8, 6.77],
      [13, 12.74],
      [9, 7.11],
      [11, 7.81],
      [14, 8.84],
      [6, 6.08],
      [4, 5.39],
      [12, 8.15],
      [7, 6.42],
      [5, 5.73],
    ],
  },
  IV: {
    name: "Set IV · High Leverage",
    subtitle: "Zero variance except 1 extreme x",
    lesson: "10 rows sit at x = 8 with no slope at all; 1 leverage point fabricates r = 0.816 out of thin air.",
    points: [
      [8, 6.58],
      [8, 5.76],
      [8, 7.71],
      [8, 8.84],
      [8, 8.47],
      [8, 7.04],
      [8, 5.25],
      [19, 12.5],
      [8, 5.56],
      [8, 7.91],
      [8, 6.89],
    ],
  },
  RING: {
    name: "Set V · Tilted Ellipse",
    subtitle: "Same summary stats, hollow center",
    lesson: "Summary tables are blind to topology. Always inspect distributions, residuals, and holdout splits.",
    points: [
      [5.1, 4.9],
      [6.2, 6.9],
      [7.6, 8.4],
      [9.4, 9.4],
      [11.3, 9.9],
      [13.4, 9.6],
      [12.7, 7.5],
      [11.1, 6.1],
      [9.2, 5.3],
      [7.1, 4.8],
      [5.9, 9.7],
    ],
  },
};

export function AnscombeModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [active, setActive] = useState<DatasetId>("I");
  const [autoCycle, setAutoCycle] = useState(false);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!open || !autoCycle) return;
    const keys: DatasetId[] = ["I", "II", "III", "IV", "RING"];
    const timer = window.setInterval(() => {
      setActive((cur) => keys[(keys.indexOf(cur) + 1) % keys.length]);
    }, 1900);
    return () => window.clearInterval(timer);
  }, [open, autoCycle]);

  const current = QUARTET[active];
  const mapX = (x: number) => 42 + ((x - 3) / 17) * 356;
  const mapY = (y: number) => 206 - ((y - 2) / 12) * 176;

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-back" />
        <Dialog.Content className="modal modal-fixed anscombe-modal" aria-describedby={undefined}>
          <div className="spread" style={{ marginBottom: 12 }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="bento-icon-circle tone-petrol">
                <FlaskConical size={16} />
              </span>
              <div>
                <Dialog.Title asChild>
                  <h2 style={{ margin: 0 }}>Anscombe’s Secret Lab</h2>
                </Dialog.Title>
                <div className="small muted">Why EDAForge never trusts a summary table without a plot</div>
              </div>
            </div>
            <button type="button" className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close secret lab">
              <X size={15} />
            </button>
          </div>

          <div className="anscombe-stats-bar">
            <div>
              <span>Mean X</span>
              <b className="mono">9.00</b>
            </div>
            <div>
              <span>Mean Y</span>
              <b className="mono">7.50</b>
            </div>
            <div>
              <span>SD (X / Y)</span>
              <b className="mono">3.32 / 2.03</b>
            </div>
            <div>
              <span>Pearson r</span>
              <b className="mono">+0.816</b>
            </div>
            <div>
              <span>Linear Fit</span>
              <b className="mono">y = 3.00 + 0.50x</b>
            </div>
          </div>

          <div className="anscombe-tabs" role="tablist" aria-label="Anscombe datasets">
            {(Object.keys(QUARTET) as DatasetId[]).map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={active === k}
                className={`anscombe-tab${active === k ? " active" : ""}`}
                onClick={() => {
                  playDetent();
                  setAutoCycle(false);
                  setActive(k);
                }}
              >
                {QUARTET[k].name.split(" · ")[0]}
              </button>
            ))}
            <button
              type="button"
              className={`anscombe-tab morph-btn${autoCycle ? " active" : ""}`}
              onClick={() => {
                playTick();
                setAutoCycle((v) => !v);
              }}
            >
              <Sparkles size={12} /> {autoCycle ? "Pause morph" : "Auto-morph"}
            </button>
          </div>

          <div className="anscombe-stage">
            <svg viewBox="0 0 420 232" className="anscombe-svg" role="img" aria-label={current.name}>
              {[4, 8, 12, 16, 20].map((gx) => (
                <g key={`gx-${gx}`}>
                  <line x1={mapX(gx)} y1={24} x2={mapX(gx)} y2={206} stroke="var(--line)" strokeDasharray="3 3" />
                  <text x={mapX(gx)} y={224} textAnchor="middle" fill="var(--muted)" fontSize="12">
                    {gx}
                  </text>
                </g>
              ))}
              {[4, 8, 12].map((gy) => (
                <g key={`gy-${gy}`}>
                  <line x1={42} y1={mapY(gy)} x2={402} y2={mapY(gy)} stroke="var(--line)" strokeDasharray="3 3" />
                  <text x={32} y={mapY(gy) + 4} textAnchor="end" fill="var(--muted)" fontSize="12">
                    {gy}
                  </text>
                </g>
              ))}
              {/* Identical OLS regression line across all sets: y = 3 + 0.5x */}
              <line
                x1={mapX(3.5)}
                y1={mapY(3 + 0.5 * 3.5)}
                x2={mapX(19.5)}
                y2={mapY(3 + 0.5 * 19.5)}
                stroke="var(--brand)"
                strokeWidth="2"
                strokeDasharray="6 4"
                opacity="0.7"
              />
              {current.points.map(([px, py], idx) => (
                <motion.circle
                  key={idx}
                  initial={false}
                  animate={{ cx: mapX(px), cy: mapY(py) }}
                  transition={
                    reduce
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 220, damping: 24, mass: 0.7 }
                  }
                  r={6.2}
                  fill="var(--coral-accent)"
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ))}
            </svg>
          </div>

          <div className="anscombe-caption">
            <strong>{current.name}:</strong> {current.lesson}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ---------------------------------------------------------------------------
// 3. Peeking Studio Companion "Loupe" (RefUI #1 Nod + Konami Code!)
// ---------------------------------------------------------------------------
const QUIPS = [
  "0 bytes leave 127.0.0.1. Your CSVs stay strictly between us.",
  "p = 0.049 without holdout confirmation is just wishful thinking.",
  "Tip: Press ? anytime to open keyboard navigation chords.",
  "Watch out for mixed cents and dollars when stacking regional exports!",
  "Simpson’s paradox: when every subgroup disagrees with the aggregate.",
  "Psst… click the EDAForge bar-mark 5 times to unlock Anscombe’s Lab.",
];

const KONAMI = [
  "ArrowUp",
  "ArrowUp",
  "ArrowDown",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "ArrowLeft",
  "ArrowRight",
  "b",
  "a",
];

export function PeekingCompanion({
  onOpenAnscombe,
}: {
  onOpenAnscombe: () => void;
}) {
  const [hidden, setHidden] = useState<boolean>(() => {
    try {
      return localStorage.getItem("edaforge-companion-hidden") === "1";
    } catch {
      return false;
    }
  });
  const [quipIdx, setQuipIdx] = useState(0);
  const [bubbleOpen, setBubbleOpen] = useState(false);
  const [konamiUnlocked, setKonamiUnlocked] = useState(false);
  const [pupil, setPupil] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement>(null);
  const seqRef = useRef<number>(0);
  const reduce = useReducedMotion();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const wanted = KONAMI[seqRef.current];
      if (e.key === wanted || e.key.toLowerCase() === wanted) {
        seqRef.current += 1;
        if (seqRef.current === KONAMI.length) {
          seqRef.current = 0;
          setKonamiUnlocked(true);
          setBubbleOpen(true);
          playConfirm();
          onOpenAnscombe();
        }
      } else {
        seqRef.current = e.key === KONAMI[0] ? 1 : 0;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpenAnscombe]);

  useEffect(() => {
    if (hidden || reduce) return;
    const onMove = (e: PointerEvent) => {
      const el = svgRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const dx = e.clientX - (rect.left + rect.width / 2);
      const dy = e.clientY - (rect.top + rect.height / 2);
      const dist = Math.hypot(dx, dy) || 1;
      const mag = Math.min(2.1, dist / 90);
      setPupil({ x: (dx / dist) * mag, y: (dy / dist) * mag });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [hidden, reduce]);

  if (hidden) {
    return (
      <button
        type="button"
        className="peeker-restore-pill"
        onClick={() => {
          playTick();
          setHidden(false);
          try {
            localStorage.setItem("edaforge-companion-hidden", "0");
          } catch {
            /* ignore */
          }
        }}
        title="Bring back Loupe the statistical inspector"
        aria-label="Show studio mascot"
      >
        <Eye size={13} aria-hidden="true" />
      </button>
    );
  }

  return (
    <div
      className="peeker-wrap"
      onMouseEnter={() => setBubbleOpen(true)}
      onMouseLeave={() => setBubbleOpen(false)}
    >
      {bubbleOpen ? (
        <div className="peeker-bubble" role="status">
          <span>
            {konamiUnlocked
              ? "Konami Fellow unlocked! Every p-value bows to your holdout split."
              : QUIPS[quipIdx]}
          </span>
          <button
            type="button"
            className="peeker-hide-btn"
            onClick={(e) => {
              e.stopPropagation();
              setHidden(true);
              setBubbleOpen(false);
              try {
                localStorage.setItem("edaforge-companion-hidden", "1");
              } catch {
                /* ignore */
              }
            }}
            title="Tuck Loupe away"
            aria-label="Hide studio mascot"
          >
            <EyeOff size={11} />
          </button>
        </div>
      ) : null}

      <button
        type="button"
        className="peeker-btn"
        onClick={() => {
          playTick(1.15);
          setBubbleOpen(true);
          setQuipIdx((i) => (i + 1) % QUIPS.length);
        }}
        aria-label="Loupe, statistical studio companion — click for a statistical note"
      >
        <svg ref={svgRef} width="46" height="36" viewBox="0 0 46 36" fill="none" aria-hidden="true">
          {/* Beanie / Inspector Cap (RefUI 1 nod!) */}
          <path
            d="M11 16C11 8.8 16.4 4 23 4C29.6 4 35 8.8 35 16H11Z"
            fill={konamiUnlocked ? "#D97706" : "#C84B31"}
          />
          <rect x="9.5" y="13.5" width="27" height="4.5" rx="2.25" fill={konamiUnlocked ? "#F59E0B" : "#A63820"} />
          {/* Head */}
          <rect x="11" y="16" width="24" height="17" rx="8.5" fill="#F2DEC9" stroke="var(--stage-border-strong)" strokeWidth="1.2" />
          {/* Spectacles */}
          <circle cx="18.2" cy="23.5" r="4.6" fill="#FFFFFF" stroke="#1E293B" strokeWidth="1.6" />
          <circle cx="27.8" cy="23.5" r="4.6" fill="#FFFFFF" stroke="#1E293B" strokeWidth="1.6" />
          <line x1="22.8" y1="23.5" x2="23.2" y2="23.5" stroke="#1E293B" strokeWidth="1.6" />
          {/* Pupils */}
          <circle cx={18.2 + pupil.x} cy={23.5 + pupil.y} r="1.8" fill="#12191D" />
          <circle cx={27.8 + pupil.x} cy={23.5 + pupil.y} r="1.8" fill="#12191D" />
          {/* Paws gripping the stage edge */}
          <rect x="7" y="30" width="6.5" height="4.5" rx="2.2" fill="#E6CBB0" stroke="var(--stage-border-strong)" strokeWidth="1" />
          <rect x="32.5" y="30" width="6.5" height="4.5" rx="2.2" fill="#E6CBB0" stroke="var(--stage-border-strong)" strokeWidth="1" />
        </svg>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. Global Keyboard Chords + Bento Shortcuts HUD ('?')
// ---------------------------------------------------------------------------
export function ShortcutsController({
  open,
  onOpenChange,
  onToggleTheme,
  onOpenAnscombe,
  projectId,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  onToggleTheme: () => void;
  onOpenAnscombe: () => void;
  projectId?: string;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const gPressedAt = useRef<number>(0);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "?" || (e.shiftKey && e.key === "/")) {
        e.preventDefault();
        playDetent();
        onOpenChange(!open);
        return;
      }
      if (e.shiftKey && e.key.toLowerCase() === "t") {
        e.preventDefault();
        playTick();
        onToggleTheme();
        return;
      }
      if (e.shiftKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        playConfirm();
        onOpenAnscombe();
        return;
      }

      const now = Date.now();
      if (!e.shiftKey && e.key.toLowerCase() === "g") {
        gPressedAt.current = now;
        return;
      }
      if (now - gPressedAt.current < 900) {
        const k = e.key.toLowerCase();
        gPressedAt.current = 0;
        if (k === "h") {
          e.preventDefault();
          playTick();
          navigate("/");
        } else if (projectId && k === "d") {
          e.preventDefault();
          playTick();
          navigate(`/p/${projectId}/data`);
        } else if (projectId && k === "c") {
          e.preventDefault();
          playTick();
          navigate(`/p/${projectId}/connect`);
        } else if (projectId && k === "f") {
          e.preventDefault();
          playTick();
          navigate(`/p/${projectId}/discover`);
        } else if (projectId && k === "r") {
          e.preventDefault();
          playTick();
          navigate(`/p/${projectId}/report`);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange, onToggleTheme, onOpenAnscombe, navigate, projectId, location.pathname]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-back" />
        <Dialog.Content className="modal modal-fixed shortcuts-modal" aria-describedby={undefined}>
          <div className="spread" style={{ marginBottom: 14 }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="bento-icon-circle tone-sky">
                <Keyboard size={16} />
              </span>
              <div>
                <Dialog.Title asChild>
                  <h2 style={{ margin: 0 }}>Studio Keyboard Shortcuts</h2>
                </Dialog.Title>
                <div className="small muted">Navigate pipelines, findings, and labs without leaving the keyboard</div>
              </div>
            </div>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => onOpenChange(false)} aria-label="Close shortcuts">
              <X size={15} />
            </button>
          </div>

          <div className="shortcuts-grid">
            <div className="shortcut-group">
              <h3>Global</h3>
              <div className="shortcut-row">
                <span>Command palette</span>
                <span><kbd>Ctrl</kbd> <kbd>K</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Shortcut sheet</span>
                <span><kbd>?</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Flip Light / Dark Bento</span>
                <span><kbd>Shift</kbd> <kbd>T</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Anscombe’s Secret Lab</span>
                <span><kbd>Shift</kbd> <kbd>A</kbd></span>
              </div>
            </div>

            <div className="shortcut-group">
              <h3>Navigation Chords</h3>
              <div className="shortcut-row">
                <span>All workspaces home</span>
                <span><kbd>G</kbd> then <kbd>H</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Data workbench</span>
                <span><kbd>G</kbd> then <kbd>D</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Connect &amp; join preview</span>
                <span><kbd>G</kbd> then <kbd>C</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Discover &amp; runs</span>
                <span><kbd>G</kbd> then <kbd>F</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Report &amp; exports</span>
                <span><kbd>G</kbd> then <kbd>R</kbd></span>
              </div>
              <div className="shortcut-row">
                <span>Prev / Next finding</span>
                <span><kbd>[</kbd> / <kbd>]</kbd></span>
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
