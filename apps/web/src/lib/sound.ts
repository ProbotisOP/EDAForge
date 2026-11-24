// Optional local audio feedback using Web Audio API impulses (off by default).
// Zero external assets, 100% local & CSP-safe.

const STORAGE_KEY = "edaforge-tactile-sound";

let ctx: AudioContext | null = null;
let enabled = (() => {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
})();

export function isSoundEnabled(): boolean {
  return enabled;
}

export function setSoundEnabled(next: boolean): void {
  enabled = next;
  try {
    localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function context(): AudioContext | null {
  if (!enabled || typeof window === "undefined") return null;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return null;
  try {
    const AudioCtor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtor) return null;
    ctx ??= new AudioCtor();
    if (ctx.state === "suspended") void ctx.resume().catch(() => {});
    return ctx;
  } catch {
    return null;
  }
}

export function playTick(pitch = 1): void {
  const c = context();
  if (!c || c.state !== "running") return;
  try {
    const t = c.currentTime;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(1150 * pitch, t);
    osc.frequency.exponentialRampToValueAtTime(240 * pitch, t + 0.016);
    gain.gain.setValueAtTime(0.024, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.018);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(t);
    osc.stop(t + 0.02);
  } catch {
    /* ignore */
  }
}

export function playDetent(): void {
  playTick(1.2);
}

export function playConfirm(): void {
  const c = context();
  if (!c || c.state !== "running") return;
  try {
    const t = c.currentTime;
    [587.33, 880].forEach((freq, idx) => {
      const osc = c.createOscillator();
      const gain = c.createGain();
      osc.type = "sine";
      const start = t + idx * 0.055;
      osc.frequency.setValueAtTime(freq, start);
      gain.gain.setValueAtTime(0.022, start);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.12);
      osc.connect(gain);
      gain.connect(c.destination);
      osc.start(start);
      osc.stop(start + 0.13);
    });
  } catch {
    /* ignore */
  }
}
