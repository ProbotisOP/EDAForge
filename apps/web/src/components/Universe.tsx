import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import type { Universe, UniverseEdge, UniverseNode } from "../lib/types";

// The Data Universe: every analyzed column is a star, every stored finding a beam between the
// columns it involves. Nothing is computed here: colour is the finding's direction (up together,
// one up while the other goes down, or a difference between groups), the pulse speed its ranking
// effect component, brightness its evidence grade, solid or dashed its confirmation status.

export type Lens = "all" | "truth" | "skeptic";
export type SignFilter = "up" | "down" | "groups" | "formula";
export const ALL_SIGNS: SignFilter[] = ["up", "down", "groups", "formula"];

export function signOf(e: UniverseEdge): SignFilter {
  if (e.kind === "formula") return "formula";
  return e.sign > 0 ? "up" : e.sign < 0 ? "down" : "groups";
}
const SIGN_COLOR: Record<SignFilter, number> = { up: 0x22d3ee, down: 0xfb7185, groups: 0xa78bfa, formula: 0xfbbf24 };
export const SIGN_LABEL: Record<SignFilter, string> = {
  up: "↑ Rise together",
  down: "↓ One rises, other falls",
  groups: "◆ Differs between groups",
  formula: "ƒ Exact formula",
};

const ROLE_COLOR: Record<string, number> = {
  numeric: 0x38bdf8,
  categorical: 0xa78bfa,
  boolean: 0xc084fc,
  datetime: 0xfbbf24,
  source: 0x34d399,
  other: 0x94a3b8,
};
const KIND_COLOR: Record<string, number> = {
  pair: 0x7dd3fc,
  reversal: 0xf43f5e,
  explained_away: 0xf59e0b,
  subgroup: 0xe879f9,
  interaction: 0xfacc15,
  synergy: 0xfacc15,
  cross_file: 0x34d399,
};
const GRADE_ALPHA: Record<string, number> = { A: 1, B: 0.85, C: 0.6, D: 0.38, E: 0.14 };

export const KIND_LABEL: Record<string, string> = {
  pair: "Relationship",
  reversal: "Reversal (flips within groups)",
  explained_away: "Explained away by a third column",
  subgroup: "Segment that drives the outcome",
  interaction: "Combination that matters together",
  synergy: "Partners in a combination",
  cross_file: "Differs between files",
};

function kindColor(e: UniverseEdge): number {
  if (e.kind === "pair" && e.family === "cross_file") return KIND_COLOR.cross_file;
  if (e.kind === "pair" || e.kind === "formula") return SIGN_COLOR[signOf(e)];
  return KIND_COLOR[e.kind] ?? KIND_COLOR.pair;
}

export function visible(e: UniverseEdge, lens: Lens, signs: SignFilter[] = ALL_SIGNS): boolean {
  if (!signs.includes(signOf(e))) return false;
  if (e.kind === "formula") return true; // a fact checked on every row, not a graded inference
  if (lens === "truth") return e.confirmed && (e.grade === "A" || e.grade === "B");
  // Results that did not hold up (grade E) only appear under the Skeptic lens, as in the feed.
  if (lens === "all") return e.grade !== "E";
  return true;
}

/** Deterministic 3D force layout (seeded positions, fixed iterations). */
function layout(nodes: UniverseNode[], edges: UniverseEdge[], target: string | null): Map<string, THREE.Vector3> {
  const pos = new Map<string, THREE.Vector3>();
  const n = nodes.length;
  nodes.forEach((node, i) => {
    // Golden-spiral seeds: reproducible, evenly spread.
    const y = 1 - (2 * (i + 0.5)) / Math.max(n, 1);
    const r = Math.sqrt(1 - y * y);
    const theta = Math.PI * (3 - Math.sqrt(5)) * i;
    pos.set(node.id, node.id === target ? new THREE.Vector3() : new THREE.Vector3(Math.cos(theta) * r * 40, y * 40, Math.sin(theta) * r * 40));
  });
  const vel = new Map(nodes.map((node) => [node.id, new THREE.Vector3()]));
  const tmp = new THREE.Vector3();
  for (let it = 0; it < 400; it++) {
    const cool = 1 - it / 400;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = pos.get(nodes[i].id)!;
        const b = pos.get(nodes[j].id)!;
        tmp.subVectors(a, b);
        const d2 = Math.max(tmp.lengthSq(), 1);
        tmp.multiplyScalar(900 / d2 / Math.sqrt(d2));
        vel.get(nodes[i].id)!.add(tmp);
        vel.get(nodes[j].id)!.sub(tmp);
      }
    }
    for (const e of edges) {
      const a = pos.get(e.source);
      const b = pos.get(e.target);
      if (!a || !b) continue;
      tmp.subVectors(b, a);
      const d = Math.max(tmp.length(), 0.01);
      const rest = 34 - 18 * e.strength;
      tmp.multiplyScalar(((d - rest) / d) * 0.02 * (0.4 + e.strength));
      vel.get(e.source)!.add(tmp);
      vel.get(e.target)!.sub(tmp);
    }
    for (const node of nodes) {
      const p = pos.get(node.id)!;
      const v = vel.get(node.id)!;
      v.addScaledVector(p, -0.004);
      if (node.id === target) v.set(0, 0, 0);
      p.addScaledVector(v, cool);
      v.multiplyScalar(0.6);
    }
  }
  return pos;
}

interface Props {
  universe: Universe;
  lens: Lens;
  signs: SignFilter[];
  selectedNode: string | null;
  selectedEdge: string | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
}

function fmt(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  return a >= 1e5 ? v.toExponential(2) : a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
}

function hoverText(node: UniverseNode): string {
  const s = node.stats;
  if (!s) return node.id;
  const miss = s.n ? `${((100 * s.missing) / s.n).toFixed(0)}% missing` : "";
  if (s.kind === "numeric") return `median ${fmt(s.median)} · range ${fmt(s.min)}–${fmt(s.max)} · ${miss}`;
  return `${s.distinct} labels · top ${s.top?.[0]?.label ?? "–"} · ${miss}`;
}

export function UniverseView({ universe, lens, signs, selectedNode, selectedEdge, onSelectNode, onSelectEdge }: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const state = useRef<{
    focus: (id: string) => void;
    apply: (lens: Lens, signs: SignFilter[], node: string | null, edge: string | null) => void;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const positions = useMemo(() => layout(universe.nodes, universe.edges, universe.target), [universe]);
  const handlers = useRef({ onSelectNode, onSelectEdge });
  handlers.current = { onSelectNode, onSelectEdge };
  const selected = useRef<string | null>(selectedNode);
  selected.current = selectedNode;

  useEffect(() => {
    const host = mount.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
    } catch {
      setError("This browser cannot draw 3D graphics (WebGL is unavailable). The Insight Feed shows the same findings.");
      return;
    }
    const width = () => host.clientWidth || 800;
    const height = () => host.clientHeight || 600;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width(), height());
    renderer.setClearColor(0x05060f);
    host.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.setSize(width(), height());
    labels.domElement.className = "universe-labels";
    host.appendChild(labels.domElement);

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(55, width() / height(), 0.1, 2000);
    const dists = [...positions.values()].map((v) => v.length()).sort((a, b) => a - b);
    const radius = Math.max(20, dists[Math.floor(dists.length * 0.8)] ?? 20);
    camera.position.set(0, radius * 0.35, radius * 2.1);
    const controls = new OrbitControls(camera, labels.domElement);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.35;
    controls.addEventListener("start", () => (controls.autoRotate = false));

    // Background stars (decoration only; fixed seed so the sky never changes between visits).
    let seed = 7;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(1800 * 3);
    for (let i = 0; i < starPos.length; i++) starPos[i] = (rand() - 0.5) * 900;
    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x3b4470, size: 0.9 })));
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    scene.fog = new THREE.Fog(0x05060f, radius * 2.5, radius * 7);

    const glowTex = (() => {
      const c = document.createElement("canvas");
      c.width = c.height = 64;
      const g = c.getContext("2d")!;
      const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      grad.addColorStop(0, "rgba(255,255,255,1)");
      grad.addColorStop(0.25, "rgba(255,255,255,0.55)");
      grad.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = grad;
      g.fillRect(0, 0, 64, 64);
      return new THREE.CanvasTexture(c);
    })();

    const nodeObjs = new Map<string, { mesh: THREE.Mesh; glow: THREE.Sprite; label: CSS2DObject; base: number; badge: HTMLSpanElement }>();
    for (const node of universe.nodes) {
      const p = positions.get(node.id)!;
      const color = node.is_target ? 0xffd166 : ROLE_COLOR[node.role] ?? ROLE_COLOR.other;
      const r = node.is_target ? 3.4 : 1.1 + Math.min(node.degree, 10) * 0.18;
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 16), new THREE.MeshBasicMaterial({ color }));
      mesh.position.copy(p);
      mesh.userData = { node: node.id };
      scene.add(mesh);
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
      glow.scale.setScalar(r * (node.is_target ? 9 : 6));
      glow.position.copy(p);
      scene.add(glow);
      if (node.alerts.some((a) => a.severity === "warning" || a.severity === "critical")) {
        const ring = new THREE.Mesh(new THREE.RingGeometry(r * 1.6, r * 1.8, 32), new THREE.MeshBasicMaterial({ color: 0xff6b6b, side: THREE.DoubleSide, transparent: true, opacity: 0.4 }));
        ring.position.copy(p);
        ring.userData = { spin: true };
        scene.add(ring);
      }
      const div = document.createElement("div");
      div.className = node.is_target ? "u-label u-target" : "u-label";
      div.dataset.node = node.id;
      const name = document.createElement("span");
      name.textContent = node.derived ? `ƒ ${node.id}` : node.id;
      name.dataset.node = node.id;
      const badge = document.createElement("span");
      badge.className = "u-badge";
      badge.dataset.node = node.id;
      div.append(name, badge);
      const label = new CSS2DObject(div);
      label.position.set(0, r + 1.6, 0);
      mesh.add(label);
      nodeObjs.set(node.id, { mesh, glow, label, base: r, badge });
    }

    interface Beam {
      edge: UniverseEdge;
      line: THREE.Line;
      extra: THREE.Line[];
      pulses: THREE.Sprite[];
      curve: THREE.QuadraticBezierCurve3;
      phase: number;
      alpha: number;
      boost: number;
    }
    const beams: Beam[] = [];
    universe.edges.forEach((edge, k) => {
      const a = positions.get(edge.source);
      const b = positions.get(edge.target);
      if (!a || !b) return;
      const mid = a.clone().add(b).multiplyScalar(0.5);
      // Parallel findings between the same pair bow apart so each beam is selectable.
      const twin = universe.edges.filter((e) => (e.source === edge.source && e.target === edge.target) || (e.source === edge.target && e.target === edge.source));
      const idx = twin.indexOf(edge);
      const normal = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3(0, 1, 0)).normalize();
      mid.addScaledVector(normal, (idx - (twin.length - 1) / 2) * 4);
      mid.y += 2;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(40));
      const color = kindColor(edge);
      const material = edge.confirmed
        ? new THREE.LineBasicMaterial({ color, transparent: true, opacity: 1 })
        : new THREE.LineDashedMaterial({ color, transparent: true, opacity: 1, dashSize: 1.2, gapSize: 1 });
      const line = new THREE.Line(geo, material);
      if (!edge.confirmed) line.computeLineDistances();
      line.userData = { edge: edge.id };
      scene.add(line);
      const extra: THREE.Line[] = [];
      if (edge.via && positions.get(edge.via)) {
        const v = positions.get(edge.via)!;
        for (const end of [a, b]) {
          const l = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([end, v]),
            new THREE.LineDashedMaterial({ color, transparent: true, opacity: 0.5, dashSize: 0.6, gapSize: 0.8 }),
          );
          l.computeLineDistances();
          l.userData = { edge: edge.id };
          scene.add(l);
          extra.push(l);
        }
      }
      // Live pulses: more and faster for stronger effects; dimmer when not confirmed.
      const pulses: THREE.Sprite[] = [];
      const count = 1 + Math.round(2 * edge.strength);
      for (let i = 0; i < count; i++) {
        const p = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: edge.confirmed ? 1 : 0.55 }));
        p.scale.setScalar(1.1 + 2.0 * edge.strength);
        scene.add(p);
        pulses.push(p);
      }
      beams.push({ edge, line, extra, pulses, curve, phase: (k * 0.137) % 1, alpha: 1, boost: 1 });
    });

    const other = (e: UniverseEdge, id: string) => (e.source === id ? e.target : e.source);
    const apply = (lensNow: Lens, signsNow: SignFilter[], node: string | null, edgeSel: string | null) => {
      for (const beam of beams) {
        const e = beam.edge;
        const show = visible(e, lensNow, signsNow);
        const touches = !node || e.source === node || e.target === node || e.via === node;
        let alpha = (GRADE_ALPHA[e.grade ?? "E"] ?? 0.2) * (0.35 + 0.65 * e.strength);
        if (lensNow === "skeptic") alpha = !e.confirmed || e.exploratory || e.grade === "D" || e.grade === "E" ? 1 : 0.08;
        if (node && touches) alpha = Math.max(alpha, 0.9); // the selected star's beams flare
        if (!touches) alpha *= 0.08;
        if (edgeSel) alpha = e.id === edgeSel ? 1 : alpha * 0.25;
        beam.alpha = alpha;
        beam.boost = (node && touches) || e.id === edgeSel ? 2.2 : 1;
        for (const l of [beam.line, ...beam.extra]) l.visible = show;
        for (const p of beam.pulses) p.visible = show && alpha > 0.15;
      }
      const badges = new Map<string, string>();
      if (node) {
        for (const b of beams) {
          const e = b.edge;
          if (!visible(e, lensNow, signsNow) || (e.source !== node && e.target !== node)) continue;
          const o = other(e, node);
          const mark = e.kind === "formula" ? "ƒ" : e.sign > 0 ? "↑" : e.sign < 0 ? "↓" : "◆";
          const text = e.estimate !== null ? `${mark} ${e.estimate >= 0 ? "+" : ""}${e.estimate.toFixed(2)}` : mark;
          const prev = badges.get(o);
          if (!prev || (e.estimate !== null && !/\d/.test(prev))) badges.set(o, text);
        }
      }
      for (const [id, obj] of nodeObjs) {
        const t = badges.get(id) ?? "";
        obj.badge.textContent = t;
        obj.badge.className = `u-badge ${t.startsWith("↑") ? "up" : t.startsWith("↓") ? "down" : t.startsWith("ƒ") ? "formula" : "groups"}`;
        const linked = !node || id === node || badges.has(id) || beams.some((b) => visible(b.edge, lensNow, signsNow) && b.edge.via === node && (b.edge.source === id || b.edge.target === id));
        (obj.glow.material as THREE.SpriteMaterial).opacity = linked ? 0.8 : 0.1;
        (obj.mesh.material as THREE.MeshBasicMaterial).transparent = true;
        (obj.mesh.material as THREE.MeshBasicMaterial).opacity = linked ? 1 : 0.25;
        obj.label.element.style.opacity = linked ? "1" : "0.3";
        obj.label.element.classList.toggle("u-selected", id === node);
      }
    };

    const ringTex = (() => {
      const c = document.createElement("canvas");
      c.width = c.height = 128;
      const g = c.getContext("2d")!;
      g.strokeStyle = "rgba(255,255,255,1)";
      g.lineWidth = 6;
      g.shadowColor = "white";
      g.shadowBlur = 12;
      g.beginPath();
      g.arc(64, 64, 52, 0, Math.PI * 2);
      g.stroke();
      return new THREE.CanvasTexture(c);
    })();
    const waves: { sprite: THREE.Sprite; t: number; size: number }[] = [];
    const shock = (id: string) => {
      const p = positions.get(id);
      const obj = nodeObjs.get(id);
      if (!p || !obj) return;
      const color = (obj.mesh.material as THREE.MeshBasicMaterial).color;
      for (let i = 0; i < 3; i++) {
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTex, color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
        sprite.position.copy(p);
        scene.add(sprite);
        waves.push({ sprite, t: -i * 0.22, size: obj.base * 26 });
      }
    };
    let flight: { from: THREE.Vector3; to: THREE.Vector3; look0: THREE.Vector3; look1: THREE.Vector3; t: number } | null = null;
    const focus = (id: string) => {
      const p = positions.get(id);
      if (!p) return;
      shock(id);
      controls.autoRotate = false;
      // Frame the star together with its neighbours, so that their badges are in view.
      const group = [p.clone()];
      for (const b of beams) {
        if (!b.line.visible || (b.edge.source !== id && b.edge.target !== id)) continue;
        const q = positions.get(b.edge.source === id ? b.edge.target : b.edge.source);
        if (q) group.push(q.clone());
      }
      const center = group.reduce((acc, v) => acc.add(v), new THREE.Vector3()).multiplyScalar(1 / group.length);
      const spread = Math.max(12, ...group.map((v) => v.distanceTo(center)));
      const fov = (camera.fov * Math.PI) / 180;
      const dist = Math.max(28, (spread * 1.35) / Math.tan(fov / 2));
      const dir = camera.position.clone().sub(controls.target).normalize();
      // The insight panel covers the right of the screen: aim a little right of the group so that
      // the group sits in the visible part.
      const right = new THREE.Vector3().crossVectors(camera.up, dir).normalize();
      const aim = center.clone().addScaledVector(right, spread * 0.45);
      flight = { from: camera.position.clone(), to: aim.clone().addScaledVector(dir, dist), look0: controls.target.clone(), look1: aim, t: 0 };
    };
    state.current = { focus, apply };

    const tip = document.createElement("div");
    tip.className = "u-tip";
    host.appendChild(tip);
    const raycaster = new THREE.Raycaster();
    raycaster.params.Line = { threshold: 0.8 };
    const pointer = new THREE.Vector2();
    let downAt: [number, number] | null = null;
    // OrbitControls captures the pointer, so pointerup never reports the label: decide on pointerdown.
    const onDown = (ev: PointerEvent) => {
      tip.style.display = "none";
      const el = ev.target as HTMLElement;
      if (el.closest?.(".u-label") && el.dataset.node) {
        downAt = null;
        handlers.current.onSelectNode(el.dataset.node);
        return;
      }
      downAt = [ev.clientX, ev.clientY];
    };
    const onUp = (ev: PointerEvent) => {
      if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hitNode = raycaster.intersectObjects([...nodeObjs.values()].map((o) => o.mesh))[0];
      if (hitNode) {
        handlers.current.onSelectNode(hitNode.object.userData.node as string);
        return;
      }
      const hitEdge = raycaster.intersectObjects(beams.filter((b) => b.line.visible).map((b) => b.line))[0];
      if (hitEdge) handlers.current.onSelectEdge(hitEdge.object.userData.edge as string);
      else {
        handlers.current.onSelectNode(null);
        handlers.current.onSelectEdge(null);
      }
    };
    const byId = new Map(universe.nodes.map((n) => [n.id, n]));
    let hovered: string | null = null;
    const onMove = (ev: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      const el = ev.target as HTMLElement;
      let id: string | null = el.dataset?.node ?? null;
      if (!id) {
        pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects([...nodeObjs.values()].map((o) => o.mesh))[0];
        id = hit ? (hit.object.userData.node as string) : null;
      }
      hovered = id;
      labels.domElement.style.cursor = id ? "pointer" : "grab";
      const node = id ? byId.get(id) : undefined;
      if (!node) {
        tip.style.display = "none";
        return;
      }
      tip.style.display = "block";
      tip.style.left = `${ev.clientX - rect.left + 14}px`;
      tip.style.top = `${ev.clientY - rect.top + 12}px`;
      tip.replaceChildren();
      const b = document.createElement("b");
      b.textContent = node.id;
      const line = document.createElement("div");
      line.textContent = hoverText(node);
      const hint = document.createElement("div");
      hint.className = "u-faint";
      hint.textContent = node.derived ? `calculated: ${node.derived.formula_text}` : "click to see what moves with it";
      tip.append(b, line, hint);
    };
    labels.domElement.addEventListener("pointermove", onMove);
    labels.domElement.addEventListener("pointerdown", onDown);
    labels.domElement.addEventListener("pointerup", onUp);

    const resize = () => {
      camera.aspect = width() / height();
      camera.updateProjectionMatrix();
      renderer.setSize(width(), height());
      labels.setSize(width(), height());
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);

    const clock = new THREE.Clock();
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const dt = clock.getDelta();
      const t = clock.elapsedTime;
      for (const beam of beams) {
        const e = beam.edge;
        // Breathing: the beam's brightness pulses at a rate set by the effect size.
        const breath = 0.72 + 0.28 * Math.sin(t * (1.2 + 2.6 * e.strength) * beam.boost + beam.phase * 6.28);
        for (const l of [beam.line, ...beam.extra]) {
          (l.material as THREE.LineBasicMaterial).opacity = (l === beam.line ? beam.alpha : beam.alpha * 0.55) * breath;
        }
        beam.phase = (beam.phase + dt * (0.08 + 0.3 * e.strength) * beam.boost) % 1;
        beam.pulses.forEach((p, i) => {
          if (!p.visible) return;
          let u = (beam.phase + i / beam.pulses.length) % 1;
          if (e.sign < 0) u = 1 - u; // against the grain: one rises while the other falls
          p.position.copy(beam.curve.getPoint(u));
          (p.material as THREE.SpriteMaterial).opacity = Math.min(1, beam.alpha * 1.4) * (e.confirmed ? 1 : 0.55) * Math.sin(Math.PI * u) ** 0.5;
        });
        if (beam.edge.kind === "reversal") {
          // A reversal alternates between the overall direction and the within-group one.
          const mat = beam.line.material as THREE.LineBasicMaterial;
          mat.color.setHex(Math.sin(t * 2.4) > 0 ? 0xf43f5e : 0x60a5fa);
        }
      }
      for (let i = waves.length - 1; i >= 0; i--) {
        const w = waves[i];
        w.t += dt * 0.9;
        if (w.t < 0) {
          w.sprite.visible = false;
          continue;
        }
        w.sprite.visible = true;
        w.sprite.scale.setScalar(2 + w.size * w.t);
        (w.sprite.material as THREE.SpriteMaterial).opacity = Math.max(0, 1 - w.t) * 0.9;
        if (w.t >= 1) {
          scene.remove(w.sprite);
          w.sprite.material.dispose();
          waves.splice(i, 1);
        }
      }
      for (const [id, obj] of nodeObjs) {
        const target = id === hovered ? 1.35 : id === selected.current ? 1.2 + 0.08 * Math.sin(t * 4) : 1;
        obj.mesh.scale.setScalar(obj.mesh.scale.x + (target - obj.mesh.scale.x) * Math.min(1, dt * 10));
      }
      scene.traverse((o) => {
        if (o.userData.spin) o.rotation.z += dt * 0.8;
        if (o instanceof THREE.Mesh && o.userData.spin) o.lookAt(camera.position);
      });
      if (flight) {
        flight.t = Math.min(1, flight.t + dt * 1.2);
        const s = flight.t * flight.t * (3 - 2 * flight.t);
        camera.position.lerpVectors(flight.from, flight.to, s);
        controls.target.lerpVectors(flight.look0, flight.look1, s);
        if (flight.t >= 1) flight = null;
      }
      controls.update();
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      labels.domElement.removeEventListener("pointermove", onMove);
      labels.domElement.removeEventListener("pointerdown", onDown);
      labels.domElement.removeEventListener("pointerup", onUp);
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Line || o instanceof THREE.Points || o instanceof THREE.Sprite) {
          o.geometry?.dispose();
          const m = o.material as THREE.Material | THREE.Material[];
          (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
        }
      });
      glowTex.dispose();
      ringTex.dispose();
      renderer.dispose();
      host.innerHTML = "";
      state.current = null;
    };
  }, [universe, positions]);

  useEffect(() => {
    state.current?.apply(lens, signs, selectedNode, selectedEdge);
  }, [lens, signs, selectedNode, selectedEdge, universe]);

  useEffect(() => {
    if (selectedNode) state.current?.focus(selectedNode);
  }, [selectedNode]);

  if (error) return <div className="universe-fallback">{error}</div>;
  return <div ref={mount} className="universe-canvas" data-testid="universe-canvas" />;
}
