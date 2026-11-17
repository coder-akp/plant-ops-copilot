// 3D line view. Built into app/static/scene.js with `npm run build` (see frontend/README.md).
// Procedural geometry only: no model files, no textures to download.
import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Mesh, MeshLambertMaterial, MeshBasicMaterial,
  BoxGeometry, CylinderGeometry, LatheGeometry, RingGeometry, PlaneGeometry, TorusGeometry, OctahedronGeometry,
  HemisphereLight, DirectionalLight, InstancedMesh, Object3D, Vector2, Vector3, Raycaster, GridHelper,
  EdgesGeometry, LineSegments, LineBasicMaterial, AdditiveBlending, CanvasTexture, RepeatWrapping, Sprite,
  SpriteMaterial, SRGBColorSpace, Color, MathUtils,
} from "three";

const COLORS = { ok: 0x3fd6a4, watch: 0xf5b544, alert: 0xff6b73, accent: 0x4c9bff, steel: 0x34445c, trim: 0x44566f, dark: 0x1a2332 };
const LINE_LEN = 19.4;
const BELT_Y = 1.0;
const MACHINES = [
  { id: "FILLER-01", role: "Filler", x: -6.3, top: 2.9 },
  { id: "CAPPER-01", role: "Capper", x: -2.1, top: 2.9 },
  { id: "LABELER-01", role: "Labeler", x: 2.1, top: 2.6 },
  { id: "PACKER-01", role: "Packer", x: 6.3, top: 2.4 },
];

const mat = (color, extra = {}) => new MeshLambertMaterial({ color, ...extra });
const box = (w, h, d, m, x, y, z) => { const o = new Mesh(new BoxGeometry(w, h, d), m); o.position.set(x, y, z); return o; };
const cyl = (rt, rb, h, m, x, y, z, seg = 24) => { const o = new Mesh(new CylinderGeometry(rt, rb, h, seg), m); o.position.set(x, y, z); return o; };

function haloTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,0.95)");
  r.addColorStop(0.35, "rgba(255,255,255,0.35)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 64, 64);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

function beltTexture() {
  const c = document.createElement("canvas");
  c.width = 128; c.height = 16;
  const g = c.getContext("2d");
  g.fillStyle = "#1d2735"; g.fillRect(0, 0, 128, 16);
  g.fillStyle = "#2a374a";
  for (let i = 0; i < 128; i += 16) g.fillRect(i, 0, 7, 16);
  const t = new CanvasTexture(c);
  t.wrapS = t.wrapT = RepeatWrapping;
  t.repeat.set(LINE_LEN / 1.6, 1);
  t.colorSpace = SRGBColorSpace;
  return t;
}

export function webglSupported(force) {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2", { failIfMajorPerformanceCaveat: !force }) || c.getContext("webgl", { failIfMajorPerformanceCaveat: !force });
    return !!gl;
  } catch { return false; }
}

export function createScene(container, opts = {}) {
  const lowPower = !!opts.lowPower;
  const reduceMotion = !!opts.reduceMotion;
  const touch = !!opts.touch;

  const renderer = new WebGLRenderer({ antialias: !lowPower, alpha: true, powerPreference: lowPower ? "low-power" : "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowPower ? 1.5 : 2));
  renderer.outputColorSpace = SRGBColorSpace;
  const canvas = renderer.domElement;
  canvas.className = "m3d-canvas";
  canvas.setAttribute("aria-hidden", "true");
  canvas.style.touchAction = touch ? "pan-y" : "none";
  container.appendChild(canvas);

  const scene = new Scene();
  const camera = new PerspectiveCamera(32, 16 / 9, 0.5, 120);
  scene.add(new HemisphereLight(0xd8e6ff, 0x182232, 2.0));
  const sun = new DirectionalLight(0xffffff, 1.6);
  sun.position.set(-6, 12, 9);
  scene.add(sun);

  /* Floor and conveyor */
  const floor = new Mesh(new PlaneGeometry(30, 12), new MeshBasicMaterial({ color: 0x0c131d, transparent: true, opacity: 0.85 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(0, -0.01, -0.8);
  scene.add(floor);
  const grid = new GridHelper(30, 30, 0x22324a, 0x162234);
  grid.position.set(0, 0, -0.8);
  grid.scale.z = 0.4;
  scene.add(grid);

  const steel = mat(COLORS.steel), trim = mat(COLORS.trim), dark = mat(COLORS.dark), accent = mat(COLORS.accent);
  scene.add(box(LINE_LEN, 0.16, 1.2, dark, 0, BELT_Y - 0.1, 0));
  const belt = beltTexture();
  const beltMesh = new Mesh(new PlaneGeometry(LINE_LEN - 0.1, 0.96), new MeshBasicMaterial({ map: belt }));
  beltMesh.rotation.x = -Math.PI / 2;
  beltMesh.position.set(0, BELT_Y, 0);
  scene.add(beltMesh);
  [-0.62, 0.62].forEach((z) => scene.add(box(LINE_LEN, 0.14, 0.06, trim, 0, BELT_Y + 0.05, z)));
  for (let i = 0; i < 8; i++) {
    const x = -LINE_LEN / 2 + 1 + i * ((LINE_LEN - 2) / 7);
    [-0.5, 0.5].forEach((z) => scene.add(box(0.1, BELT_Y - 0.15, 0.1, trim, x, (BELT_Y - 0.15) / 2, z)));
  }

  /* Machines */
  const halo = haloTexture();
  const machines = {};
  const spin = [];
  const hitMeshes = [];

  function baseMachine(def) {
    const g = new Group();
    g.position.set(def.x, 0, 0);
    g.add(box(2.9, 0.14, 2.3, dark, 0, 0.07, -1.7));
    return g;
  }

  function build(def) {
    const g = baseMachine(def);
    const bodyMats = [];
    const m1 = mat(COLORS.steel); bodyMats.push(m1);
    const m2 = mat(COLORS.trim); bodyMats.push(m2);
    const arm = (len, y) => { const a = box(0.55, 0.34, len, m2, 0, y, -len / 2 + 0.2); g.add(a); };
    if (def.id.startsWith("FILLER")) {
      g.add(cyl(1.15, 1.25, 2.5, m1, 0, 1.35, -1.8, 40));
      const ring = new Mesh(new TorusGeometry(1.2, 0.07, 10, 48), accent);
      ring.rotation.x = Math.PI / 2; ring.position.set(0, 1.9, -1.8); g.add(ring);
      g.add(cyl(0.5, 0.65, 0.35, m2, 0, 2.7, -1.8));
      arm(1.9, 2.15);
      [-0.28, 0, 0.28].forEach((dx) => g.add(cyl(0.05, 0.05, 0.55, accent, dx, 1.85, -0.1, 10)));
      const lid = cyl(0.3, 0.3, 0.12, accent, 0, 2.95, -1.8); g.add(lid); spin.push([lid, 0.9]);
    } else if (def.id.startsWith("CAPPER")) {
      g.add(box(2.2, 2.5, 1.6, m1, 0, 1.4, -1.9));
      g.add(box(2.4, 0.18, 1.8, m2, 0, 2.75, -1.9));
      arm(1.9, 2.25);
      g.add(cyl(0.12, 0.12, 0.8, m2, 0, 1.75, -0.1, 12));
      const head = cyl(0.34, 0.34, 0.24, accent, 0, 1.45, -0.1, 20); g.add(head); spin.push([head, 5]);
    } else if (def.id.startsWith("LABELER")) {
      g.add(box(2.5, 2.2, 1.7, m1, 0, 1.2, -1.9));
      g.add(box(2.7, 0.16, 1.9, m2, 0, 2.4, -1.9));
      const drum = cyl(0.55, 0.55, 0.9, mat(0xdfe7f2), 0, 1.75, -0.85, 28);
      drum.rotation.x = Math.PI / 2; g.add(drum); spin.push([drum, 1.4, "y"]);
      g.add(box(0.3, 1.0, 0.3, m2, 0, 1.75, -1.3));
      g.add(cyl(0.3, 0.3, 0.12, accent, 0.9, 2.2, -1.9)); 
    } else {
      g.add(box(3.0, 1.9, 1.9, m1, 0, 1.05, -1.8));
      g.add(box(3.1, 0.14, 2.0, m2, 0, 2.1, -1.8));
      const frame = box(0.12, 1.5, 0.12, m2, -1.3, 1.9, 0.5); g.add(frame);
      g.add(box(0.12, 1.5, 0.12, m2, 1.3, 1.9, 0.5));
      g.add(box(2.7, 0.12, 0.12, m2, 0, 2.65, 0.5));
      const pivot = new Group(); pivot.position.set(0, 2.6, 0.5);
      pivot.add(box(0.14, 1.1, 0.14, accent, 0, -0.55, 0)); pivot.add(box(0.5, 0.1, 0.5, accent, 0, -1.1, 0));
      g.add(pivot); spin.push([pivot, 0.9, "sway"]);
    }
    /* Status light bar, halo, floor ring */
    const lightMat = new MeshBasicMaterial({ color: COLORS.ok });
    const bar = box(2.0, 0.12, 0.12, lightMat, 0, def.top + 0.12, -1.0); g.add(bar);
    const glow = new Sprite(new SpriteMaterial({ map: halo, color: COLORS.ok, transparent: true, opacity: 0.55, blending: AdditiveBlending, depthWrite: false }));
    glow.scale.set(4.2, 2.2, 1); glow.position.set(0, def.top + 0.3, -1.0); g.add(glow);
    const ringMat = new MeshBasicMaterial({ color: COLORS.ok, transparent: true, opacity: 0.42, depthWrite: false });
    const ring = new Mesh(new RingGeometry(2.0, 2.12, 56), ringMat);
    ring.rotation.x = -Math.PI / 2; ring.position.set(0, 0.03, -0.9); ring.scale.set(1, 0.72, 1); g.add(ring);
    const pulseMat = new MeshBasicMaterial({ color: COLORS.accent, transparent: true, opacity: 0, depthWrite: false });
    const pulse = new Mesh(new RingGeometry(1.9, 2.1, 56), pulseMat);
    pulse.rotation.x = -Math.PI / 2; pulse.position.set(0, 0.05, -0.9); pulse.scale.set(1, 0.72, 1); g.add(pulse);
    const flag = new Mesh(new OctahedronGeometry(0.26), new MeshBasicMaterial({ color: COLORS.watch }));
    flag.position.set(0, def.top + 1.0, -1.0); flag.visible = false; g.add(flag);
    const outline = new LineSegments(new EdgesGeometry(new BoxGeometry(3.1, def.top + 0.5, 3.4)), new LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0 }));
    outline.position.set(0, (def.top + 0.5) / 2, -1.1); g.add(outline);
    const hit = new Mesh(new BoxGeometry(3.2, def.top + 0.6, 3.5), new MeshBasicMaterial({ visible: false }));
    hit.position.copy(outline.position); hit.userData.id = def.id; g.add(hit); hitMeshes.push(hit);
    scene.add(g);
    return { def, group: g, bodyMats, lightMat, glow, ring, ringMat, pulse, pulseMat, flag, outline, sev: 0, kind: "ok", vib: 0, pulseT: -1, baseX: def.x };
  }
  MACHINES.forEach((d) => { machines[d.id] = build(d); });

  /* Bottles: glass, liquid, cap and label are separate instanced meshes (4 draw calls) */
  const N = lowPower ? 18 : 25;
  const spacing = LINE_LEN / N;
  const profile = [[0, 0], [0.2, 0], [0.22, 0.04], [0.22, 0.46], [0.15, 0.62], [0.085, 0.72], [0.085, 0.86], [0.1, 0.88], [0.1, 0.92], [0, 0.92]].map((p) => new Vector2(p[0], p[1]));
  const glass = new InstancedMesh(new LatheGeometry(profile, 14), mat(0xb9d0e6, { transparent: true, opacity: 0.9 }), N);
  const liquid = new InstancedMesh(new CylinderGeometry(0.18, 0.18, 0.4, 12), mat(COLORS.accent), N);
  const caps = new InstancedMesh(new CylinderGeometry(0.105, 0.105, 0.07, 10), mat(0xe7edf7), N);
  const labels = new InstancedMesh(new CylinderGeometry(0.228, 0.228, 0.2, 14, 1, true), mat(0xf4f6fa, { side: 2 }), N);
  [glass, liquid, caps, labels].forEach((m) => { m.frustumCulled = false; scene.add(m); });
  const tmp = new Object3D();
  let flow = 1, belt0 = 0;

  function placeBottles(dt) {
    belt0 = (belt0 + dt * 1.15 * flow) % LINE_LEN;
    for (let i = 0; i < N; i++) {
      const x = ((i * spacing + belt0) % LINE_LEN) - LINE_LEN / 2;
      const edge = Math.min(1, (x + LINE_LEN / 2) / 0.6, Math.max(0, (8.1 - x) / 1.1));
      const s = Math.max(0.001, edge);
      tmp.position.set(x, BELT_Y + 0.01, 0); tmp.scale.set(s, s, s); tmp.rotation.set(0, 0, 0); tmp.updateMatrix();
      glass.setMatrixAt(i, tmp.matrix);
      const filled = x > MACHINES[0].x + 0.4;
      tmp.position.set(x, BELT_Y + 0.05 + 0.2 * s, 0); tmp.scale.set(filled ? s : 0.001, filled ? s : 0.001, filled ? s : 0.001); tmp.updateMatrix();
      liquid.setMatrixAt(i, tmp.matrix);
      const capped = x > MACHINES[1].x + 0.4;
      tmp.position.set(x, BELT_Y + 0.93 * s, 0); const cs = capped ? s : 0.001; tmp.scale.set(cs, cs, cs); tmp.updateMatrix();
      caps.setMatrixAt(i, tmp.matrix);
      const labeled = x > MACHINES[2].x + 0.4;
      tmp.position.set(x, BELT_Y + 0.28 * s, 0); const ls = labeled ? s : 0.001; tmp.scale.set(ls, ls, ls); tmp.updateMatrix();
      labels.setMatrixAt(i, tmp.matrix);
    }
    [glass, liquid, caps, labels].forEach((m) => { m.instanceMatrix.needsUpdate = true; });
  }

  /* Labels (HTML buttons: keyboard and touch friendly) */
  const labelEls = {};
  MACHINES.forEach((d) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "m3d-label ok";
    b.dataset.id = d.id;
    b.innerHTML = `<i class="dot"></i><b>${d.id}</b><small>${d.role}</small>`;
    b.addEventListener("click", () => opts.onSelect && opts.onSelect(d.id));
    b.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") hover(d.id, e); });
    b.addEventListener("pointerleave", () => hover(null));
    container.appendChild(b);
    labelEls[d.id] = b;
  });

  /* Camera: custom orbit. The wheel is never captured, so the page keeps scrolling. */
  const view = { az: 0, pol: 1.12, radius: 22, tx: 0, ty: 1.35, tz: -0.7, dAz: 0, dPol: 1.12, dRadius: 22, dTx: 0, focus: null, zoomed: null, focusSelected: null, userUntil: 0, narrow: false };
  let width = 1, height = 1, aspect = 1.6;

  function fitRadius() {
    const viewW = aspect >= 1.55 ? 18.4 : aspect >= 1.1 ? 14 : 10.5;
    view.narrow = aspect < 1.55;
    const vf = (camera.fov * Math.PI) / 180;
    const r = viewW / 2 / (Math.tan(vf / 2) * aspect);
    return MathUtils.clamp(r, 12, 36);
  }
  function applyFocus() {
    const base = fitRadius();
    const f = view.focus && machines[view.focus];
    view.dRadius = f ? base * (view.narrow ? 0.98 : 0.86) : base;
    view.dTx = f ? (view.narrow ? f.baseX : f.baseX * 0.45) : 0;
    dirty = true;
  }

  function resize() {
    const r = container.getBoundingClientRect();
    width = Math.max(1, Math.round(r.width)); height = Math.max(1, Math.round(r.height));
    aspect = width / height;
    renderer.setSize(width, height, false);
    camera.aspect = aspect; camera.updateProjectionMatrix();
    const wasR = view.radius;
    applyFocus();
    if (wasR === 22) view.radius = view.dRadius;
    dirty = true;
  }

  /* Pointer input */
  const ray = new Raycaster();
  const ndc = new Vector2();
  let hoverId = null, down = null, pendingMove = null;
  function pick(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(hitMeshes, false)[0];
    return hit ? hit.object.userData.id : null;
  }
  function hover(id, e) {
    if (id !== hoverId) { hoverId = id; dirty = true; }
    if (opts.onHover) {
      const r = container.getBoundingClientRect();
      opts.onHover(id ? { id, x: e ? e.clientX - r.left : 0, y: e ? e.clientY - r.top : 0, w: r.width, h: r.height } : null);
    }
  }
  canvas.addEventListener("pointermove", (e) => {
    if (down) {
      const dx = e.clientX - down.x, dy = e.clientY - down.y;
      if (Math.abs(dx) + Math.abs(dy) > 5) down.moved = true;
      if (down.moved) {
        if (e.pointerType === "touch" && !orbitOn) {
          view.dTx = MathUtils.clamp(down.tx - (dx / width) * (view.radius * 0.95), -6.3, 6.3);
        } else {
          view.dAz = MathUtils.clamp(down.az - dx * 0.006, -0.9, 0.9);
          view.dPol = MathUtils.clamp(down.pol - dy * 0.005, 0.8, 1.38);
        }
        view.userUntil = performance.now() + 4000; dirty = true;
      }
      return;
    }
    if (e.pointerType !== "mouse") return;
    const first = !pendingMove;
    pendingMove = e;
    if (first) requestAnimationFrame(() => {
      const ev = pendingMove; pendingMove = null;
      if (ev) hover(pick(ev.clientX, ev.clientY), ev);
    });
  });
  canvas.addEventListener("pointerdown", (e) => {
    down = { x: e.clientX, y: e.clientY, az: view.dAz, pol: view.dPol, tx: view.dTx, moved: false, type: e.pointerType };
    if (e.pointerType === "mouse" || orbitOn) canvas.setPointerCapture(e.pointerId);
    canvas.style.cursor = "grabbing";
  });
  function endPointer(e) {
    const d = down; down = null; canvas.style.cursor = "";
    if (d && !d.moved && e.type === "pointerup") {
      const id = pick(e.clientX, e.clientY);
      if (id && opts.onSelect) opts.onSelect(id);
    }
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("pointerleave", () => { if (!down) hover(null); });
  let orbitOn = false;

  /* Animation loop: runs only while the scene is visible */
  let raf = 0, last = 0, visible = true, dirty = true, running = false;
  const minDt = lowPower ? 1000 / 30 : 1000 / 60;
  const tmpV = new Vector3();
  const clock0 = performance.now();

  function update(now, dt) {
    const t = (now - clock0) / 1000;
    const calm = reduceMotion;
    /* camera */
    if (!calm && now > view.userUntil) view.dAz = Math.sin(t * 0.12) * 0.07;
    const k = calm ? 1 : 1 - Math.pow(0.0015, dt);
    view.az += (view.dAz - view.az) * k; view.pol += (view.dPol - view.pol) * k;
    view.radius += (view.dRadius - view.radius) * k; view.tx += (view.dTx - view.tx) * k;
    const sp = Math.sin(view.pol);
    camera.position.set(view.tx + view.radius * sp * Math.sin(view.az), view.ty + view.radius * Math.cos(view.pol), view.tz + view.radius * sp * Math.cos(view.az));
    camera.lookAt(view.tx, view.ty, view.tz);
    camera.updateMatrixWorld();
    /* machines */
    for (const id in machines) {
      const m = machines[id];
      const col = COLORS[m.kind];
      m.lightMat.color.setHex(col); m.glow.material.color.setHex(col); m.ringMat.color.setHex(col);
      const attention = m.kind === "ok" ? 0 : m.kind === "watch" ? 0.5 : 1;
      const beat = attention ? 0.5 + 0.5 * Math.sin(t * (2.2 + attention * 2.4)) : 0;
      m.glow.material.opacity = calm ? 0.55 : 0.4 + 0.25 * attention * beat + (attention ? 0 : 0.08);
      m.ringMat.opacity = calm ? 0.45 : 0.3 + 0.35 * beat * attention + (attention ? 0 : 0.08);
      const shake = calm ? 0 : m.vib;
      m.group.position.x = m.baseX + (shake ? Math.sin(t * 58 + m.baseX) * shake : 0);
      m.group.position.y = shake ? Math.abs(Math.sin(t * 47 + m.baseX)) * shake * 0.7 : 0;
      const hot = hoverId === id, sel = view.focusSelected === id;
      const em = hot ? 0.16 : sel ? 0.09 : 0;
      m.bodyMats.forEach((b) => b.emissive.setRGB(em * 0.3, em * 0.6, em));
      m.outline.material.opacity = sel ? 0.95 : hot ? 0.55 : 0;
      m.outline.material.color.setHex(sel ? COLORS.accent : 0xffffff);
      m.flag.rotation.y = t * 1.6; m.flag.position.y = m.def.top + 1.0 + (calm ? 0 : Math.sin(t * 2.4) * 0.08);
      if (m.pulseT >= 0) {
        m.pulseT += dt / 0.9;
        if (m.pulseT >= 1) { m.pulseT = -1; m.pulseMat.opacity = 0; }
        else { const s = 1 + m.pulseT * 0.7; m.pulse.scale.set(s, 0.72 * s, 1); m.pulseMat.opacity = 0.85 * (1 - m.pulseT); }
      }
    }
    spin.forEach(([o, rate, mode]) => {
      if (calm) return;
      if (mode === "sway") o.rotation.z = Math.sin(t * rate * 1.6) * 0.45;
      else if (mode === "y") o.rotation.y += dt * rate;
      else o.rotation.y += dt * rate;
    });
    if (!calm) { belt.offset.x = (belt.offset.x - dt * 0.72 * flow) % 1; placeBottles(dt); }
    /* label positions */
    for (const id in labelEls) {
      const m = machines[id];
      tmpV.set(m.baseX, m.def.top + 0.55, -1.0).project(camera);
      const x = (tmpV.x * 0.5 + 0.5) * width, y = (-tmpV.y * 0.5 + 0.5) * height;
      labelEls[id].style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
    }
  }

  function frame(now) {
    raf = 0;
    if (!running) return;
    const dtMs = now - last;
    if (dtMs >= minDt - 2) {
      const dt = Math.min(dtMs, 100) / 1000;
      last = now;
      update(now, dt);
      renderer.render(scene, camera);
      dirty = false;
    }
    if (!reduceMotion || dirty || pulsing()) raf = requestAnimationFrame(frame);
  }
  function pulsing() { return Object.values(machines).some((m) => m.pulseT >= 0); }
  function kick() { if (running && !raf) { last = performance.now() - minDt; raf = requestAnimationFrame(frame); } }
  function start() { if (running) return; running = true; kick(); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; }
  const invalidate = () => { dirty = true; kick(); };

  const io = new IntersectionObserver((es) => { visible = es[0].isIntersecting; (visible && !document.hidden) ? start() : stop(); }, { threshold: 0.05 });
  io.observe(container);
  const onVis = () => { (visible && !document.hidden) ? start() : stop(); };
  document.addEventListener("visibilitychange", onVis);
  const ro = new ResizeObserver(() => { resize(); invalidate(); });
  ro.observe(container);
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); stop(); if (opts.onLost) opts.onLost(); });
  resize();
  view.radius = view.dRadius;
  start();

  /* Public API */
  const KIND_LABEL = { ok: "Normal", watch: "Watch", alert: "Alert" };
  return {
    setData(map) {
      let maxSev = 0;
      for (const id in machines) {
        const d = map[id] || {};
        const m = machines[id];
        m.sev = d.sev || 0; m.kind = !m.sev ? "ok" : m.sev >= 60 ? "alert" : "watch";
        m.vib = d.vibration ? 0.006 + 0.02 * (m.sev / 100) : 0;
        maxSev = Math.max(maxSev, m.sev);
        const el = labelEls[id];
        el.className = "m3d-label " + m.kind + (m.flag.visible ? " wo" : "");
        el.querySelector("small").textContent = m.sev ? `${KIND_LABEL[m.kind]} · ${m.sev}` : (d.role || "Normal");
      }
      flow = 1 - 0.45 * (maxSev / 100);
      invalidate();
    },
    select(id, zoom = true) { view.focusSelected = id || null; view.zoomed = zoom ? id || null : null; view.focus = view.zoomed; applyFocus(); invalidate(); },
    follow(id) { view.focus = id || view.zoomed || null; applyFocus(); invalidate(); },
    pulse(id) { const ids = id ? [id] : Object.keys(machines); ids.forEach((i, n) => setTimeout(() => { if (machines[i]) { machines[i].pulseT = 0; invalidate(); } }, id ? 0 : n * 140)); },
    flag(id, on) { if (machines[id]) { machines[id].flag.visible = !!on; labelEls[id].classList.toggle("wo", !!on); invalidate(); } },
    clearFlags() { Object.keys(machines).forEach((i) => { machines[i].flag.visible = false; labelEls[i].classList.remove("wo"); }); invalidate(); },
    resetView() { view.focus = null; view.zoomed = null; view.dAz = 0; view.dPol = 1.12; view.userUntil = 0; applyFocus(); invalidate(); },
    setOrbit(on) { orbitOn = !!on; canvas.style.touchAction = on ? "none" : (touch ? "pan-y" : "none"); },
    invalidate,
    dispose() { stop(); io.disconnect(); ro.disconnect(); document.removeEventListener("visibilitychange", onVis); renderer.dispose(); canvas.remove(); Object.values(labelEls).forEach((el) => el.remove()); },
  };
}
