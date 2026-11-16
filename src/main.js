'use strict';
/*
 * main.js — boots the scene and wires the pieces together:
 *   mesh (geometry) → sim (soft body) → renderer (WebGPU) ← ui (page chrome)
 * plus the frame loop, pointer picking / dragging, the layout-aware camera, and
 * the policies around them: draw only when something changed, keep the frame
 * rate on slow CPUs and GPUs, survive a lost graphics device, fail visibly.
 */
const { buildSliceMesh } = require('./mesh.js');
const { Camera } = require('./camera.js');
const { JellySim, SIM_MESH_OPTIONS } = require('./sim.js');
const { JellyRenderer } = require('./render.js');
const { initUI } = require('./ui.js');

const DEFAULT_YAW = 0.42;
const DEFAULT_PITCH = 0.24;
const MAX_DPR = 2;
const MAX_PIXELS = 3.6e6;            // cap on the backing store, whatever the screen density
const MIN_DPR = 0.6;                 // the quality governor never goes below this many device pixels per CSS pixel
const SLOW_MO = 0.25;
const SIM_BUDGET_MS = 11;            // physics time one frame may cost before the jelly is slowed instead
const PICK_SLOP = { mouse: 5, pen: 6, touch: 14 };   // CSS px of forgiveness around the silhouette
const FEEL_DELAY_MS = 180;           // a slider has "stopped" after this long without a change
const NUDGE_GAP_MS = 120;
const PAPER = [0xF6 / 255, 0xF0 / 255, 0xE4 / 255];
const SOFTWARE_NOTICE = 'Software rendering: motion will be slow. Turn on hardware acceleration in your browser for the full effect.';

// What the governor may trade for frame rate, best first: march steps, then pixels.
const QUALITY_LEVELS = [
  { steps: 14, scale: 1 },
  { steps: 9, scale: 0.85 },
  { steps: 9, scale: 0.7 },
  { steps: 9, scale: 0.6 },
];

// How a failed JellyRenderer.create() is explained to the visitor.
const FALLBACK_FOR_CODE = {
  'no-webgpu': 'unsupported',
  'no-adapter': 'unsupported',
  'no-device': 'unsupported',
  'insecure-context': 'insecure',
};

function cssColor(name, fallback) {
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const m = /^#([0-9a-f]{6})$/i.exec(raw);
    if (m) {
      const v = parseInt(m[1], 16);
      return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
    }
  } catch (e) { /* fall through */ }
  return fallback;
}

/** ?quality=full | low | auto overrides how the picture quality is chosen (the tests pin it). */
function qualityOverride() {
  const m = /[?&]quality=(full|low|auto)(?:&|$)/.exec(typeof location !== 'undefined' ? location.search : '');
  return m ? m[1] : '';
}

function messageOf(err) {
  if (err == null) return '';
  if (typeof err === 'string') return err;
  return typeof err.message === 'string' ? err.message : String(err);
}

async function boot() {
  const state = { paused: false, slowMo: false, showMesh: false, running: false, manual: false };
  const mesh = buildSliceMesh(SIM_MESH_OPTIONS);
  const sim = new JellySim(mesh);
  const camera = new Camera();
  camera.yaw = DEFAULT_YAW;
  camera.pitch = DEFAULT_PITCH;

  const grabs = new Map();           // pointerId -> { px, py, pz (current target), dx, dy (pick offset, CSS px) }
  let orbit = null;                  // { id, x, y, yaw, pitch }
  let renderer = null;
  let rafId = 0;
  let lastTime = 0;
  let needsLayout = true;
  let dirty = 3;                     // frames still to draw although nothing in the scene moves
  let hoverX = -1, hoverY = -1, hoverDirty = false, cursor = '';
  let canvasRect = null, titleRect = null;
  let baseDpr = 1, minScale = 1;     // backing-store scale at full quality, and the lowest the governor may ask for
  const ray = { origin: new Float32Array(3), dir: new Float32Array(3) };
  const target = new Float32Array(3);
  const projected = new Float32Array(4);
  const tension = new Float32Array(mesh.numParticles);

  const invalidate = (frames) => { const n = frames || 2; if (dirty < n) dirty = n; };

  const app = {
    state, frames: 0, drawn: 0, frameMs: 0, simMs: 0, subMs: 0.3, resolutionScale: 1, quality: null,
    setPaused(p) { setPaused(Boolean(p)); ui.setPaused(state.paused); },
    /** Deterministic stepping for tests: n frames of 1/60 s, then one render. */
    stepFrames(n) { for (let i = 0; i < n; i++) sim.advance(1 / 60, 1); return app.renderOnce(); },
    renderOnce() {
      return new Promise((resolve) => requestAnimationFrame(() => { draw(performance.now(), 0); requestAnimationFrame(() => resolve()); }));
    },
    layout: () => { needsLayout = true; },
    invalidate,
  };
  const handle = { ready: false, mesh, sim, camera, renderer: null, ui: null, app };
  window.__citrus = handle;

  // ── picture quality governor ────────────────────────────────────────────
  // Frame timing alone cannot tell a slow GPU from a 30 Hz display, a power-saving
  // browser or slow JavaScript, so every change is an experiment: one level down when
  // frames are late and the GPU looks like the cause, kept only if frames really got
  // faster; one level back up when the GPU has had plenty of slack for a while, kept
  // only if frames stay as fast. A change that does not pay is undone and not tried
  // again for a growing while.
  const quality = {
    mode: 'auto',                    // 'auto' | 'full' (pinned at the top level) | 'low' (pinned at the bottom)
    level: 0,
    n: 0, sum: 0, cpu: 0, skip: 60,
    trial: null,                     // { from, before, gpuBefore, up } while an experiment is being measured
    failedDown: 0, holdDown: 0, failedUp: 0, holdUp: 0, changedAt: 0,
    WINDOW: 40,

    apply(level) {
      this.level = level;
      const q = QUALITY_LEVELS[level];
      if (renderer) renderer.steps = q.steps;
      if (app.resolutionScale !== q.scale) { app.resolutionScale = q.scale; needsLayout = true; }
      invalidate();
    },
    /** Forget the samples so far; an experiment that was being measured is undone. */
    restart(skip) {
      this.n = 0; this.sum = 0; this.cpu = 0; this.skip = skip || 20;
      if (this.trial) { const from = this.trial.from; this.trial = null; this.apply(from); }
    },
    /** Back to the starting level with a clean record (Reset, a new renderer). */
    restore() {
      this.trial = null;
      this.failedDown = 0; this.holdDown = 0; this.failedUp = 0; this.holdUp = 0;
      this.apply(this.mode === 'low' ? QUALITY_LEVELS.length - 1 : 0);
      this.restart(30);
    },
    /** True when the next level down would actually render fewer steps or pixels. */
    canLower() {
      if (this.level >= QUALITY_LEVELS.length - 1) return false;
      const a = QUALITY_LEVELS[this.level], b = QUALITY_LEVELS[this.level + 1];
      return b.steps < a.steps || Math.max(b.scale, minScale) < Math.max(a.scale, minScale) - 1e-3;
    },
    /** One drawn frame: its real interval (s), the JavaScript time it cost (ms), the clock (ms). */
    sample(dt, cpuMs, now) {
      if (this.mode !== 'auto' || !renderer) return;
      if (this.skip > 0) { this.skip--; return; }
      this.n++; this.sum += dt; this.cpu += cpuMs;
      if (this.n < this.WINDOW) return;
      const avg = this.sum / this.n, cpuShare = this.cpu / (this.sum * 1000);
      const gpuMs = renderer.gpuMs > 0 ? renderer.gpuMs : 0;
      const gpuShare = gpuMs / (avg * 1000);
      this.n = 0; this.sum = 0; this.cpu = 0;

      if (this.trial) {
        const t = this.trial;
        this.trial = null;
        const gpuKnown = gpuMs > 0 && t.gpuBefore > 0;
        if (t.up) {
          if (avg > t.before * 1.1 || avg > 1 / 50) {            // it cost frame rate: back down, ask again much later
            this.apply(t.from); this.skip = 12;
            this.failedUp++; this.holdUp = now + 60000 * this.failedUp;
          } else { this.failedUp = 0; this.changedAt = now; }
        } else if (avg < t.before * 0.9 || (gpuKnown && gpuMs < t.gpuBefore * 0.85 && avg <= t.before * 1.02)) {
          this.failedDown = 0; this.changedAt = now;             // it helped: keep it
        } else {
          this.apply(t.from); this.skip = 12;                    // it did not: the pixels come back
          this.failedDown++; this.holdDown = now + 15000 * this.failedDown * this.failedDown;
        }
        return;
      }

      const slow = avg > 1 / 50;
      if (slow && cpuShare < 0.5 && (gpuMs === 0 || gpuShare > 0.4) && now >= this.holdDown && this.failedDown < 3 && this.canLower()) {
        this.trial = { from: this.level, before: avg, gpuBefore: gpuMs, up: false };
        this.apply(this.level + 1); this.skip = 12;
      } else if (!slow && this.level > 0 && gpuMs > 0 && gpuShare < 0.3 && now - this.changedAt > 20000 && now >= this.holdUp) {
        this.trial = { from: this.level, before: avg, gpuBefore: gpuMs, up: true };
        this.apply(this.level - 1); this.skip = 12;
      }
    },
  };
  app.quality = quality;

  // ── scene actions (shared by the panel and the keyboard) ────────────────
  function setCursor(c) {
    if (c !== cursor) { cursor = c; ui.canvas.style.cursor = c; }
  }

  function releaseAllGrabs() {
    for (const id of grabs.keys()) {
      sim.endGrab(id);
      try { ui.canvas.releasePointerCapture(id); } catch (e) { /* already released */ }
    }
    grabs.clear();
    ui.setGrabbing(false);
    if (cursor === 'grabbing') { setCursor(''); hoverDirty = hoverX >= 0; }
    invalidate();
  }

  function setPaused(p) {
    state.paused = p;
    if (p) releaseAllGrabs();
    lastTime = 0;
    invalidate();
  }

  function resetScene() {
    releaseAllGrabs();
    orbit = null;
    // Paused: straight to the rest pose. The usual little drop would hang in mid-air until Resume.
    sim.reset(state.paused ? { drop: false } : undefined);
    camera.yaw = DEFAULT_YAW;
    camera.pitch = DEFAULT_PITCH;
    quality.restore();
    needsLayout = true;
    invalidate(3);
  }

  let lastNudge = -1e9;
  function nudgeScene() {
    const now = performance.now();
    if (now - lastNudge < NUDGE_GAP_MS) return;
    lastNudge = now;
    if (state.paused) { setPaused(false); ui.setPaused(false); }
    sim.nudge(1);
  }

  // A resting slice looks the same at every slider setting, so once a slider has stopped
  // moving the slice is given a small sway that shows the new feel.
  let feelTimer = 0;
  function showFeel() {
    clearTimeout(feelTimer);
    feelTimer = setTimeout(() => {
      if (state.running && !state.paused && !state.manual && grabs.size === 0) sim.jiggle(1);
    }, FEEL_DELAY_MS);
  }

  const ui = initUI({
    onFirmness: (v) => { sim.setFirmness(v); showFeel(); },
    onDamping: (v) => { sim.setDamping(v); showFeel(); },
    onNudge: nudgeScene,
    onReset: resetScene,
    onPause: (p) => setPaused(Boolean(p)),
    onShowMesh: (on) => { state.showMesh = Boolean(on); if (renderer) renderer.setShowMesh(state.showMesh); invalidate(); },
    onSlowMo: (on) => { state.slowMo = Boolean(on); },
    onPreset: (id) => { if (renderer) renderer.setPalette(id); invalidate(); },
    onLayout: () => { needsLayout = true; },
  });
  handle.ui = ui;
  const canvas = ui.canvas;

  // Apply whatever the controls currently show.
  const v = ui.values || {};
  if (typeof v.firmness === 'number') sim.setFirmness(v.firmness);
  if (typeof v.damping === 'number') sim.setDamping(v.damping);
  state.paused = Boolean(v.paused);
  state.slowMo = Boolean(v.slowMo);
  state.showMesh = Boolean(v.showMesh);

  // ── renderer lifecycle ──────────────────────────────────────────────────
  const rendererOptions = () => ({ background: cssColor('--paper', PAPER), palette: ui.values.preset || 'orange' });

  /** Stops the scene behind a message; nothing draws or reacts afterwards. */
  function fail(kind, detail) {
    state.running = false;
    cancelAnimationFrame(rafId);
    clearTimeout(feelTimer);
    releaseAllGrabs();
    orbit = null;
    handle.fallback = kind;
    ui.showFallback(kind, detail || '');
  }

  let recoveries = 0, lastLoss = -1e9;

  function adopt(r) {
    renderer = r;
    handle.renderer = r;
    r.setShowMesh(state.showMesh);
    // The panel is live while the shaders compile: honour a preset picked in the meantime.
    if (ui.values.preset && ui.values.preset !== r.palette) r.setPalette(ui.values.preset, true);
    r.steps = QUALITY_LEVELS[quality.level].steps;
    r.onError = (err) => { console.error(err); fail('crashed', messageOf(err)); };
    r.onDeviceLost = (info) => recover(messageOf(info));
  }

  // The simulation, the camera and the controls live in JavaScript, so a lost device
  // costs nothing but the GPU objects: build them again in place. Losses that keep
  // coming end in the message instead.
  function recover(detail) {
    const now = performance.now();
    if (now - lastLoss > 30000) recoveries = 0;
    lastLoss = now;
    if (recoveries >= 2 || handle.fallback) { fail('lost', detail); return; }
    recoveries++;
    state.running = false;
    cancelAnimationFrame(rafId);
    releaseAllGrabs();
    orbit = null;
    const old = renderer;
    try { old.destroy(); } catch (e) { /* the device is gone anyway */ }      // frees the canvas for the next device
    setTimeout(() => {
      JellyRenderer.create(canvas, mesh, rendererOptions()).then((fresh) => {
        adopt(fresh);
        quality.restart(30);
        needsLayout = true;
        lastTime = 0;
        invalidate(3);
        state.running = true;
        rafId = requestAnimationFrame(frame);
      }, (err) => fail('lost', detail || messageOf(err)));
    }, 300 * recoveries);
  }

  let first;
  try {
    first = await JellyRenderer.create(canvas, mesh, rendererOptions());
  } catch (err) {
    const kind = (err && FALLBACK_FOR_CODE[err.code]) || 'error';
    if (kind === 'error') console.error(err);
    ui.showFallback(kind, messageOf(err));
    handle.fallback = kind;
    handle.ready = true;
    return;
  }
  // A software rasteriser draws a few frames per second at best: start at the lowest
  // settings and say so. Everything else starts at full quality and adapts.
  const override = qualityOverride();
  quality.mode = override || (first.isFallbackAdapter ? 'low' : 'auto');
  quality.level = quality.mode === 'low' ? QUALITY_LEVELS.length - 1 : 0;
  app.resolutionScale = QUALITY_LEVELS[quality.level].scale;
  adopt(first);
  if (first.isFallbackAdapter && quality.mode === 'low') ui.setNotice(SOFTWARE_NOTICE);

  // ── layout: canvas resolution + camera framing ──────────────────────────
  function layout() {
    needsLayout = false;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (w < 2 || h < 2) return;
    const device = window.devicePixelRatio || 1;
    baseDpr = Math.min(device, MAX_DPR, Math.sqrt(MAX_PIXELS / (w * h)));
    const floor = Math.min(MIN_DPR * Math.min(1, device), baseDpr);
    minScale = floor / baseDpr;
    renderer.resize(w, h, Math.max(floor, baseDpr * app.resolutionScale));
    invalidate();

    canvasRect = canvas.getBoundingClientRect();
    titleRect = ui.getTitleRect();
    let free = null;
    try { free = ui.getFreeRect(); } catch (e) { free = null; }
    if (!free || !(free.width > 40) || !(free.height > 8)) free = { x: 0, y: 0, width: w, height: h, mode: '' };
    // Nothing can be pulled below the ground, so where the free area is much taller than
    // the slice needs (a phone held upright) the slice sits a little below the middle.
    const tall = free.mode === 'dock' ? Math.min(1, Math.max(0, (free.height / free.width - 0.9) / 0.5)) : 0;
    camera.shiftX = ((free.x + free.width * 0.5) / w) * 2 - 1;
    camera.shiftY = 1 - ((free.y + free.height * (0.5 + 0.07 * tall)) / h) * 2;
    // Generous air around the slice when there is room, less when the free area is small:
    // the slice can always be stretched across the chrome, but it must not start out tiny.
    const room = Math.min(free.width / 2.84, free.height / 2.16);          // px per world unit at the roomy margins
    const tight = Math.min(1, Math.max(0, (150 - room) / 90));
    const halfW = (1.42 - 0.24 * tight - 0.12 * tall * (1 - tight)) * (w / free.width);
    const halfH = (1.08 - 0.36 * tight) * (h / free.height);
    camera.fit(w / h, halfW, halfH);
    camera.distance = Math.min(Math.max(camera.distance, 3.2), 16);
    camera.update();
  }

  // ── pointer input ───────────────────────────────────────────────────────
  function castAt(x, y) {
    const r = canvasRect || canvas.getBoundingClientRect();
    camera.rayFromNdc(((x - r.left) / r.width) * 2 - 1, 1 - ((y - r.top) / r.height) * 2, ray);
    return sim.raycast(ray.origin, ray.dir);
  }

  /**
   * The surface point under the pointer, or the nearest one a few pixels away: the
   * drawn outline bulges slightly past the simulation surface, and a finger is blunt.
   * Returns { hit, dx, dy } with the pixel offset at which the hit was found.
   */
  function pick(x, y, type) {
    let hit = castAt(x, y);
    if (hit) return { hit, dx: 0, dy: 0 };
    const slop = PICK_SLOP[type] || PICK_SLOP.pen;
    for (let ring = 1; ring <= 2; ring++) {
      const rad = slop * ring / 2;
      let best = null, bestT = Infinity;
      for (let a = 0; a < 8; a++) {
        const dx = Math.cos(a * Math.PI / 4) * rad, dy = Math.sin(a * Math.PI / 4) * rad;
        hit = castAt(x + dx, y + dy);
        if (hit && hit.t < bestT) { bestT = hit.t; best = { hit, dx, dy }; }
      }
      if (best) return best;
    }
    return null;
  }

  function onPointerDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (!state.running) return;
    canvasRect = canvas.getBoundingClientRect();
    const picked = state.paused ? null : pick(e.clientX, e.clientY, e.pointerType);
    if (picked && sim.startGrab(e.pointerId, picked.hit, picked.hit.point)) {
      const p = picked.hit.point;
      grabs.set(e.pointerId, { px: p[0], py: p[1], pz: p[2], dx: picked.dx, dy: picked.dy });
      ui.setGrabbing(true);
      ui.noteInteraction();
      setCursor('grabbing');
    } else if (!orbit && grabs.size === 0 && e.isPrimary !== false) {
      orbit = { id: e.pointerId, x: e.clientX, y: e.clientY, yaw: camera.yaw, pitch: camera.pitch };
    } else {
      return;
    }
    // preventDefault below also cancels the usual "pressing elsewhere clears the focus":
    // do that by hand, so that Space after playing means Pause and not "press the last button again".
    const focused = document.activeElement;
    if (focused && focused !== document.body && focused !== canvas && typeof focused.blur === 'function') focused.blur();
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* not capturable */ }
    invalidate();
    e.preventDefault();
  }

  function onPointerMove(e) {
    const g = grabs.get(e.pointerId);
    if (g) {
      // Drag in the plane through the held point that faces the camera as it is NOW
      // (another finger may have turned the view since the grab began).
      const r = canvasRect || canvas.getBoundingClientRect();
      camera.rayFromNdc(((e.clientX + g.dx - r.left) / r.width) * 2 - 1, 1 - ((e.clientY + g.dy - r.top) / r.height) * 2, ray);
      const d = ray.dir, o = ray.origin, f = camera.forward;
      const denom = d[0] * f[0] + d[1] * f[1] + d[2] * f[2];
      if (Math.abs(denom) > 1e-5) {
        const t = ((g.px - o[0]) * f[0] + (g.py - o[1]) * f[1] + (g.pz - o[2]) * f[2]) / denom;
        if (t > 0) {
          target[0] = o[0] + d[0] * t; target[1] = o[1] + d[1] * t; target[2] = o[2] + d[2] * t;
          g.px = target[0]; g.py = target[1]; g.pz = target[2];
          sim.moveGrab(e.pointerId, target);
        }
      }
      e.preventDefault();
      return;
    }
    if (orbit && orbit.id === e.pointerId) {
      camera.yaw = Math.min(1.25, Math.max(-1.25, orbit.yaw - (e.clientX - orbit.x) * 0.006));
      camera.pitch = Math.min(0.85, Math.max(0.05, orbit.pitch + (e.clientY - orbit.y) * 0.005));
      camera.update();
      invalidate();
      e.preventDefault();
      return;
    }
    if (e.pointerType === 'mouse') { hoverX = e.clientX; hoverY = e.clientY; hoverDirty = true; }
  }

  function onPointerUp(e) {
    if (grabs.has(e.pointerId)) {
      sim.endGrab(e.pointerId);
      grabs.delete(e.pointerId);
      if (grabs.size === 0) ui.setGrabbing(false);
      hoverX = e.clientX; hoverY = e.clientY; hoverDirty = e.pointerType === 'mouse';
      if (e.pointerType !== 'mouse' && grabs.size === 0) setCursor('');
      invalidate();
    }
    if (orbit && orbit.id === e.pointerId) orbit = null;
    try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
  }

  function updateHoverCursor() {
    if (!hoverDirty || grabs.size > 0 || orbit) return;
    hoverDirty = false;
    if (state.paused || !state.running) { setCursor(''); return; }
    setCursor(pick(hoverX, hoverY, 'mouse') ? 'grab' : '');
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  canvas.addEventListener('lostpointercapture', onPointerUp);
  canvas.addEventListener('pointerleave', () => { if (grabs.size === 0) { hoverDirty = false; setCursor(''); } });
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('dragstart', (e) => e.preventDefault());
  window.addEventListener('blur', () => { releaseAllGrabs(); orbit = null; });

  // ── keyboard: Space pauses, R resets, N nudges ──────────────────────────
  window.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || !state.running) return;
    const el = e.target;
    const tag = el && el.tagName ? el.tagName.toLowerCase() : '';
    const type = el && el.type ? String(el.type).toLowerCase() : '';
    const typing = tag === 'textarea' || tag === 'select' || Boolean(el && el.isContentEditable) ||
      (tag === 'input' && type !== 'range' && type !== 'checkbox' && type !== 'radio' && type !== 'button');
    if (typing) return;
    if (e.key === ' ') {
      if (tag === 'input' || tag === 'button' || tag === 'a') return;       // Space belongs to the focused control
      if (!e.repeat) app.setPaused(!state.paused);
      e.preventDefault();
    } else if (e.key === 'r' || e.key === 'R') {
      if (!e.repeat) resetScene();
    } else if (e.key === 'n' || e.key === 'N') {
      if (!e.repeat) nudgeScene();
    }
  });

  // ── things that change the picture from outside the scene ───────────────
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => { needsLayout = true; }).observe(canvas);
  window.addEventListener('resize', () => { needsLayout = true; });
  window.addEventListener('orientationchange', () => { needsLayout = true; });
  const resumed = () => { lastTime = 0; quality.restart(30); invalidate(3); };
  document.addEventListener('visibilitychange', resumed);
  window.addEventListener('pageshow', resumed);
  // The window can move to a screen with another pixel density without changing its CSS size.
  (function watchDensity() {
    if (typeof matchMedia !== 'function') return;
    const mq = matchMedia('(resolution: ' + (window.devicePixelRatio || 1) + 'dppx)');
    if (mq.addEventListener) mq.addEventListener('change', () => { needsLayout = true; watchDensity(); }, { once: true });
  })();

  // ── frame loop ──────────────────────────────────────────────────────────
  /** The heading steps back while any part of the slice is behind its lettering. */
  function updateUnderTitle() {
    let under = false;
    if (titleRect && canvasRect) {
      const p = sim.pos, r = canvasRect, t = titleRect, pad = 8;
      const x0 = t.x + pad, x1 = t.x + t.width - pad, y0 = t.y + pad, y1 = t.y + t.height - pad;
      for (let i = 0, n = mesh.numParticles; i < n && !under; i++) {
        if (!mesh.onSurface[i]) continue;
        camera.project(p[i * 3], p[i * 3 + 1], p[i * 3 + 2], projected);
        const x = r.left + (projected[0] * 0.5 + 0.5) * r.width, y = r.top + (1 - (projected[1] * 0.5 + 0.5)) * r.height;
        under = x > x0 && x < x1 && y > y0 && y < y1;
      }
    }
    ui.setUnderTitle(under);
  }

  function draw(now, dt) {
    if (!renderer) return;
    if (needsLayout) layout();
    updateHoverCursor();
    updateUnderTitle();
    renderer.render({
      positions: sim.pos,
      camera,
      time: now / 1000,
      dt,
      tension: state.showMesh ? sim.computeTension(tension) : null,
    });
    app.drawn++;
  }

  function finiteState() {
    const p = sim.pos;
    let s = 0;
    for (let i = 0, n = p.length; i < n; i++) s += p[i];
    return s - s === 0;
  }

  function step(now) {
    const interval = lastTime ? (now - lastTime) / 1000 : 1 / 60;       // the real time since the last frame
    lastTime = now;
    const dt = Math.min(Math.max(interval, 0), 0.1);

    const t0 = performance.now();
    let moving = false;
    // state.manual hands time stepping to tests (app.stepFrames) while grabs stay live.
    if (!state.paused && !state.manual) {
      // A CPU that cannot run the fixed substeps in real time gets a slightly slower
      // jelly instead of a slide show: the substeps of one frame are capped by what
      // they have been costing on this machine.
      const scale = state.slowMo ? SLOW_MO : 1;
      const maxSub = Math.max(3, Math.floor(SIM_BUDGET_MS / app.subMs));
      const k = sim.advance(Math.min(dt, maxSub * sim.substepDt / scale), scale);
      if (k > 0) app.subMs += (Math.min((performance.now() - t0) / k, 4) - app.subMs) * 0.1;
      moving = !sim.sleeping;
      if (moving && !finiteState()) {
        console.error('Citrus Jelly: the simulation state was not finite; resetting the slice.');
        releaseAllGrabs();
        sim.reset({ drop: false });
      }
    }
    const t1 = performance.now();

    // Nothing on screen changes while the slice sleeps or the scene is paused, so
    // nothing is drawn then either: the last frame stays up and the GPU rests.
    const mustDraw = moving || needsLayout || dirty > 0 || grabs.size > 0 || orbit !== null || renderer.animating || !handle.ready;
    if (mustDraw) { if (dirty > 0) dirty--; draw(now, dt); } else updateHoverCursor();

    app.simMs += (t1 - t0 - app.simMs) * 0.1;
    app.frameMs += (dt * 1000 - app.frameMs) * 0.1;
    app.frames++;
    if (mustDraw && !state.manual) quality.sample(Math.min(interval, 0.5), performance.now() - t0, now);
    if (!handle.ready) handle.ready = true;
  }

  let frameErrors = 0;
  function frame(now) {
    if (!state.running) return;
    rafId = requestAnimationFrame(frame);
    try {
      step(now);
      frameErrors = 0;
    } catch (err) {
      // One bad frame is skipped. A frame that keeps failing stops the scene with a
      // message instead of a frozen picture and an endless stream of console errors.
      if (++frameErrors === 1) console.error(err);
      if (frameErrors >= 3) fail('crashed', messageOf(err));
    }
  }

  const reduceMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  sim.reset(reduceMotion ? { drop: false } : undefined);
  state.running = true;
  layout();
  rafId = requestAnimationFrame(frame);
}

function start() {
  let started = false;
  const go = () => {
    if (started) return;
    started = true;
    boot().catch((err) => {
      console.error('Citrus Jelly failed to start:', err);
      const handle = window.__citrus || (window.__citrus = {});
      try { (handle.ui || initUI({})).showFallback('error', messageOf(err)); } catch (e) { /* nothing left to show it with */ }
      handle.fallback = 'error';
      handle.ready = true;
    });
  };
  // Let the page paint its heading first; building the simulation blocks for a moment.
  // (A hidden tab gets no animation frames, hence the timer.)
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => requestAnimationFrame(go));
  setTimeout(go, 400);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
else start();
