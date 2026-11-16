'use strict';
/*
 * main.js — boots the scene and wires the pieces together:
 *   mesh (geometry) → sim (soft body) → renderer (WebGPU) ← ui (page chrome)
 * plus the frame loop, pointer picking / dragging and layout-aware camera.
 */
const { buildSliceMesh } = require('./mesh.js');
const { Camera } = require('./camera.js');
const { JellySim, SIM_MESH_OPTIONS } = require('./sim.js');
const { JellyRenderer } = require('./render.js');
const { initUI } = require('./ui.js');

const DEFAULT_YAW = 0.42;
const DEFAULT_PITCH = 0.24;
const MAX_DPR = 2;
const MAX_PIXELS = 3.6e6;            // cap the backing store on very large / dense displays
const SLOW_MO = 0.25;

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

async function boot() {
  const state = { paused: false, slowMo: false, showMesh: false, running: false, manual: false };
  const mesh = buildSliceMesh(SIM_MESH_OPTIONS);
  const sim = new JellySim(mesh);
  const camera = new Camera();
  camera.yaw = DEFAULT_YAW;
  camera.pitch = DEFAULT_PITCH;

  const grabs = new Map();           // pointerId -> { px, py, pz, nx, ny, nz }
  let orbit = null;                  // { id, x, y, yaw, pitch }
  let renderer = null;
  let rafId = 0;
  let lastTime = 0;
  let needsLayout = true;
  let hoverX = -1, hoverY = -1, hoverDirty = false, cursor = '';
  const ray = { origin: new Float32Array(3), dir: new Float32Array(3) };
  const target = new Float32Array(3);
  const tension = new Float32Array(mesh.numParticles);

  const app = {
    state, frames: 0, frameMs: 0, simMs: 0, resolutionScale: 1,
    setPaused(p) { setPaused(Boolean(p)); ui.setPaused(state.paused); },
    /** Deterministic stepping for tests: n frames of 1/60 s, then one render. */
    stepFrames(n) { for (let i = 0; i < n; i++) sim.advance(1 / 60, 1); return app.renderOnce(); },
    renderOnce() {
      return new Promise((resolve) => requestAnimationFrame(() => { draw(performance.now(), 0); requestAnimationFrame(() => resolve()); }));
    },
    layout: () => { needsLayout = true; },
  };
  const handle = { ready: false, mesh, sim, camera, renderer: null, ui: null, app };
  window.__citrus = handle;

  function releaseAllGrabs() {
    for (const id of grabs.keys()) {
      sim.endGrab(id);
      try { ui.canvas.releasePointerCapture(id); } catch (e) { /* already released */ }
    }
    grabs.clear();
    ui.setGrabbing(false);
  }

  function setPaused(p) {
    state.paused = p;
    if (p) releaseAllGrabs();
  }

  const ui = initUI({
    onFirmness: (v) => sim.setFirmness(v),
    onDamping: (v) => sim.setDamping(v),
    onNudge: () => {
      if (state.paused) { setPaused(false); ui.setPaused(false); }
      sim.nudge(1);
    },
    onReset: () => {
      releaseAllGrabs();
      sim.reset();
      camera.yaw = DEFAULT_YAW;
      camera.pitch = DEFAULT_PITCH;
      needsLayout = true;
    },
    onPause: (p) => setPaused(Boolean(p)),
    onShowMesh: (on) => { state.showMesh = Boolean(on); if (renderer) renderer.setShowMesh(state.showMesh); },
    onSlowMo: (on) => { state.slowMo = Boolean(on); },
    onPreset: (id) => { if (renderer) renderer.setPalette(id); },
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

  try {
    renderer = await JellyRenderer.create(canvas, mesh, {
      background: cssColor('--paper', [0xF6 / 255, 0xF0 / 255, 0xE4 / 255]),
      palette: v.preset || 'orange',
    });
  } catch (err) {
    const unsupported = err && typeof err.code === 'string' && err.code.indexOf('no-') === 0;
    ui.showFallback(unsupported ? 'unsupported' : 'error', err && err.message ? err.message : String(err));
    if (!unsupported) console.error(err);
    handle.fallback = unsupported ? 'unsupported' : 'error';
    handle.ready = true;
    return;
  }
  handle.renderer = renderer;
  renderer.setShowMesh(state.showMesh);
  renderer.onDeviceLost = (info) => {
    state.running = false;
    cancelAnimationFrame(rafId);
    releaseAllGrabs();
    handle.fallback = 'lost';
    ui.showFallback('lost', info && info.message ? info.message : '');
  };

  // ── layout: canvas resolution + camera framing ──────────────────────────
  function layout() {
    needsLayout = false;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (w < 2 || h < 2) return;
    let dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    dpr = Math.min(dpr, Math.sqrt(MAX_PIXELS / (w * h)));
    dpr = Math.max(Math.min(1, window.devicePixelRatio || 1), dpr * app.resolutionScale);
    renderer.resize(w, h, dpr);

    let free = null;
    try { free = ui.getFreeRect(); } catch (e) { free = null; }
    if (!free || !(free.width > 40) || !(free.height > 40)) free = { x: 0, y: 0, width: w, height: h };
    // Centre the slice in the free area and make it fit there with room to stretch.
    camera.shiftX = ((free.x + free.width * 0.5) / w) * 2 - 1;
    camera.shiftY = 1 - ((free.y + free.height * 0.5) / h) * 2;
    const halfW = 1.42 * (w / free.width);
    const halfH = 1.08 * (h / free.height);
    camera.fit(w / h, halfW, halfH);
    camera.distance = Math.min(Math.max(camera.distance, 3.2), 16);
    camera.update();
  }

  // ── pointer input ───────────────────────────────────────────────────────
  function setRayFromEvent(e) {
    const r = canvas.getBoundingClientRect();
    const nx = ((e.clientX - r.left) / r.width) * 2 - 1;
    const ny = 1 - ((e.clientY - r.top) / r.height) * 2;
    camera.rayFromNdc(nx, ny, ray);
  }

  function setCursor(c) {
    if (c !== cursor) { cursor = c; canvas.style.cursor = c; }
  }

  function onPointerDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (!state.running) return;
    setRayFromEvent(e);
    const hit = state.paused ? null : sim.raycast(ray.origin, ray.dir);
    if (hit) {
      const f = camera.forward;
      grabs.set(e.pointerId, { px: hit.point[0], py: hit.point[1], pz: hit.point[2], nx: f[0], ny: f[1], nz: f[2] });
      sim.startGrab(e.pointerId, hit, hit.point);
      ui.setGrabbing(true);
      ui.noteInteraction();
      setCursor('grabbing');
    } else if (!orbit && grabs.size === 0 && e.isPrimary !== false) {
      orbit = { id: e.pointerId, x: e.clientX, y: e.clientY, yaw: camera.yaw, pitch: camera.pitch };
    } else {
      return;
    }
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* not capturable */ }
    e.preventDefault();
  }

  function onPointerMove(e) {
    const g = grabs.get(e.pointerId);
    if (g) {
      // Drag in the plane through the original hit point, parallel to the screen.
      setRayFromEvent(e);
      const d = ray.dir, o = ray.origin;
      const denom = d[0] * g.nx + d[1] * g.ny + d[2] * g.nz;
      if (Math.abs(denom) > 1e-5) {
        const t = ((g.px - o[0]) * g.nx + (g.py - o[1]) * g.ny + (g.pz - o[2]) * g.nz) / denom;
        if (t > 0) {
          target[0] = o[0] + d[0] * t; target[1] = o[1] + d[1] * t; target[2] = o[2] + d[2] * t;
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
      if (e.pointerType !== 'mouse') setCursor('');
    }
    if (orbit && orbit.id === e.pointerId) orbit = null;
    try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
  }

  function updateHoverCursor() {
    if (!hoverDirty || grabs.size > 0 || orbit) return;
    hoverDirty = false;
    if (state.paused) { setCursor(''); return; }
    const r = canvas.getBoundingClientRect();
    camera.rayFromNdc(((hoverX - r.left) / r.width) * 2 - 1, 1 - ((hoverY - r.top) / r.height) * 2, ray);
    setCursor(sim.raycast(ray.origin, ray.dir) ? 'grab' : '');
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  canvas.addEventListener('lostpointercapture', onPointerUp);
  canvas.addEventListener('pointerleave', () => { if (grabs.size === 0) setCursor(''); });
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('dragstart', (e) => e.preventDefault());
  window.addEventListener('blur', () => { releaseAllGrabs(); orbit = null; });

  window.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || !state.running) return;
    const el = e.target;
    const tag = el && el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'button' || tag === 'select' || tag === 'textarea' || tag === 'a') return;
    if (e.key === ' ') { app.setPaused(!state.paused); e.preventDefault(); }
    else if (e.key === 'r' || e.key === 'R') { releaseAllGrabs(); sim.reset(); }
    else if (e.key === 'n' || e.key === 'N') { if (state.paused) app.setPaused(false); sim.nudge(1); }
  });

  if (typeof ResizeObserver === 'function') new ResizeObserver(() => { needsLayout = true; }).observe(canvas);
  window.addEventListener('resize', () => { needsLayout = true; });
  window.addEventListener('orientationchange', () => { needsLayout = true; });
  document.addEventListener('visibilitychange', () => { lastTime = 0; });

  // ── frame loop ──────────────────────────────────────────────────────────
  let slowFrames = 0, fastFrames = 0;

  function draw(now, dt) {
    if (needsLayout) layout();
    updateHoverCursor();
    renderer.render({
      positions: sim.pos,
      camera,
      time: now / 1000,
      dt,
      tension: state.showMesh ? sim.computeTension(tension) : null,
    });
  }

  function frame(now) {
    if (!state.running) return;
    rafId = requestAnimationFrame(frame);
    let dt = lastTime ? (now - lastTime) / 1000 : 1 / 60;
    lastTime = now;
    if (dt > 0.1) dt = 0.1;
    if (dt < 0) dt = 0;

    const t0 = performance.now();
    // state.manual hands time stepping to tests (app.stepFrames) while grabs stay live.
    if (!state.paused && !state.manual) sim.advance(dt, state.slowMo ? SLOW_MO : 1);
    const t1 = performance.now();
    draw(now, dt);
    app.simMs += (t1 - t0 - app.simMs) * 0.1;
    app.frameMs += (dt * 1000 - app.frameMs) * 0.1;
    app.frames++;

    // Adaptive resolution: if the device cannot hold ~45 fps, render fewer pixels.
    if (app.frames > 30 && (window.devicePixelRatio || 1) > 1) {
      if (dt > 1 / 42) { slowFrames++; fastFrames = 0; } else { fastFrames++; if (fastFrames > 20) slowFrames = 0; }
      if (slowFrames > 45 && app.resolutionScale > 0.55) {
        app.resolutionScale = Math.max(0.55, app.resolutionScale * 0.82);
        slowFrames = 0;
        needsLayout = true;
      }
    }
    if (!handle.ready) handle.ready = true;
  }

  const reduceMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  sim.reset(reduceMotion ? { drop: false } : undefined);
  state.running = true;
  layout();
  rafId = requestAnimationFrame(frame);
}

function start() {
  boot().catch((err) => { console.error('Citrus Jelly failed to start:', err); });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
else start();
