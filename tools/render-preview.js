'use strict';
/*
 * render-preview.js — look-dev entry for the renderer alone.
 *
 *   node tools/build.cjs --entry tools/render-preview.js --out render-preview.html
 *
 * Builds the mesh, a Camera and the JellyRenderer on the bare <canvas id="stage">
 * and applies FAKE analytic deformations to mesh.rest, so the look can be judged
 * without the simulation.
 *
 *   ?pose=rest|stretch|squash|twist|lift|bend|flat   (lift = 0.4 above the ground)
 *   ?palette=orange|blood|lemon      ?mesh=1 (overlay, with fake tension)
 *   ?yaw=0.42&pitch=0.24             ?zoom=1 (bigger = closer)
 *   ?anim=1 (breathing deformation + palette cycling with ?cycle=1)
 *   ?quality=low|medium|high         ?sub=3 (surface subdivision)
 *   ?dpr=1                           ?h=0.14&layers=3 (mesh resolution override)
 *
 * window.__citrus = { ready, renderer, camera, mesh, positions, setPose(), frame() }
 */
const { buildSliceMesh } = require('../src/mesh.js');
const { Camera } = require('../src/camera.js');
const { JellyRenderer } = require('../src/render.js');

const qs = new URLSearchParams(location.search);
const num = (k, d) => (qs.has(k) && isFinite(parseFloat(qs.get(k))) ? parseFloat(qs.get(k)) : d);

function meshOptions() {
  let o = {};
  try { o = Object.assign({}, require('../src/sim.js').SIM_MESH_OPTIONS || {}); } catch (e) { /* sim.js not there yet */ }
  if (qs.has('h')) o.h = num('h', 0.14);
  if (qs.has('layers')) o.layers = num('layers', 3) | 0;
  return o;
}

/** Fake analytic deformations of the rest pose; amount in [0,1]. Writes tension as well. */
function applyPose(mesh, pose, amount, out, tension) {
  const n = mesh.numParticles, r = mesh.rest;
  const s = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
  for (let i = 0; i < n; i++) {
    let x = r[i * 3], y = r[i * 3 + 1], z = r[i * 3 + 2];
    let ten = 0;
    if (pose === 'stretch') {
      // a point high on the right is pulled up and out: the flesh necks towards it
      const gx = 0.62, gy = 0.70;
      const d2 = (x - gx) * (x - gx) + (y - gy) * (y - gy);
      const w = Math.exp(-d2 / 0.20) * amount;
      const wide = Math.exp(-d2 / 0.9) * amount;
      const nx = 0.72, ny = 0.69;                      // pull direction
      const along = (x - gx) * nx + (y - gy) * ny;
      x += nx * (0.55 * w + 0.12 * wide) + nx * along * 0.5 * w;
      y += ny * (0.55 * w + 0.12 * wide) + ny * along * 0.5 * w;
      // narrow across the pull and through the thickness (volume preservation)
      const across = (x - gx) * -ny + (y - gy) * nx;
      x -= -ny * across * 0.0 * w;
      z *= 1 - 0.42 * w;
      y -= 0.10 * wide * (1 - s(0, 0.5, y)) * 0;
      ten = Math.min(1, w * 1.25);
    } else if (pose === 'squash') {
      const k = 1 - 0.30 * amount;
      const bulge = 1 / Math.sqrt(k);
      const prof = 1 + (bulge - 1) * (0.6 + 0.8 * Math.sin(Math.min(1, y) * Math.PI));
      x *= prof; z *= prof; y *= k;
      ten = Math.min(1, 0.55 * amount * Math.sin(Math.min(1, y) * Math.PI));
    } else if (pose === 'twist') {
      const a = 1.25 * amount * y;
      const c = Math.cos(a), sn = Math.sin(a);
      const X = x * c + z * sn, Z = -x * sn + z * c;
      x = X; z = Z;
      x += 0.12 * amount * y * y;
      ten = Math.min(1, Math.abs(a) * Math.hypot(x, z) * 0.6);
    } else if (pose === 'bend') {
      // lean back and curl over like a soft slice flopping
      const a = 0.9 * amount * y;
      const c = Math.cos(a), sn = Math.sin(a);
      const Y = y * c - z * sn * 0 - (1 - c) * 0, Zb = z + 0;
      const rr = 1 / Math.max(0.35, 0.9 * amount);
      y = Math.sin(a) * (rr - z);
      z = rr - Math.cos(a) * (rr - z) - 0 * (Y + Zb);
      ten = Math.min(1, Math.abs(a) * 0.5);
    } else if (pose === 'lift') {
      y += 0.4 * amount;
    } else if (pose === 'flat') {
      // lying on its face on the ground
      const Y = z + mesh.thickness * 0.5 + 0.012, Z = -y + 0.5;
      y = Math.max(0, Y); z = Z;
    }
    out[i * 3] = x; out[i * 3 + 1] = Math.max(0, y); out[i * 3 + 2] = z;
    if (tension) tension[i] = ten;
  }
}

async function boot() {
  const canvas = document.getElementById('stage');
  const mesh = buildSliceMesh(meshOptions());
  const camera = new Camera();
  camera.yaw = num('yaw', 0.42);
  camera.pitch = num('pitch', 0.24);
  camera.target[0] = num('tx', camera.target[0]);
  camera.target[1] = num('ty', camera.target[1]);
  camera.target[2] = num('tz', camera.target[2]);
  camera.shiftX = num('shiftx', 0);
  camera.shiftY = num('shifty', 0);
  const zoom = num('zoom', 1);

  const positions = new Float32Array(mesh.numParticles * 3);
  const tension = new Float32Array(mesh.numParticles);
  let pose = qs.get('pose') || 'rest';
  const anim = qs.get('anim') === '1';
  applyPose(mesh, pose, 1, positions, tension);

  const handle = { ready: false, error: null, renderer: null, camera, mesh, positions, tension, frames: 0 };
  window.__citrus = handle;

  let renderer;
  try {
    renderer = await JellyRenderer.create(canvas, mesh, {
      palette: qs.get('palette') || 'orange',
      quality: qs.get('quality') || 'medium',
      subdivisions: num('sub', 0) | 0,
      debug: qs.get('debug') !== '0',
    });
  } catch (e) {
    handle.error = { code: e.code || 'error', message: String(e && e.message || e) };
    console.error('renderer failed: ' + handle.error.code + ' — ' + handle.error.message);
    document.body.insertAdjacentHTML('beforeend',
      `<p style="position:fixed;left:24px;top:24px;font:16px/1.4 Georgia,serif;color:#2B1B10">WebGPU unavailable (${handle.error.code}).</p>`);
    handle.ready = 'failed';
    return;
  }
  handle.renderer = renderer;
  renderer.setShowMesh(qs.get('mesh') === '1');
  renderer.debugView = num('view', 0);
  renderer.onDeviceLost = (info) => console.error('device lost: ' + (info && info.message));

  const layout = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const dpr = num('dpr', Math.min(2, window.devicePixelRatio || 1));
    renderer.resize(w, h, dpr);
    if (w > 0 && h > 0) camera.fit(w / h, 1.55 / zoom, 0.95 / zoom);
  };
  layout();
  window.addEventListener('resize', layout);

  const t0 = performance.now();
  let last = t0;
  const cycle = ['orange', 'blood', 'lemon'];
  let cycleAt = 0;
  handle.setPose = (p, amount) => { pose = p; applyPose(mesh, pose, amount === undefined ? 1 : amount, positions, tension); };
  handle.frame = (timeSeconds) => {
    camera.update();
    renderer.render({ positions, camera, time: timeSeconds || 0, dt: 1 / 60, tension });
  };

  const tick = (now) => {
    const time = (now - t0) / 1000;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (anim) {
      const a = pose === 'rest' ? 0 : 0.5 + 0.5 * Math.sin(time * 2.2);
      applyPose(mesh, pose, a, positions, tension);
      camera.yaw = num('yaw', 0.42) + 0.25 * Math.sin(time * 0.5);
      if (qs.get('cycle') === '1' && time - cycleAt > 2.5) {
        cycleAt = time;
        renderer.setPalette(cycle[(cycle.indexOf(renderer.palette) + 1) % 3]);
      }
    }
    camera.update();
    renderer.render({ positions, camera, time, dt, tension });
    handle.frames++;
    if (handle.frames === 2 && handle.ready !== true) {
      // the first frame has been submitted; wait for the GPU to finish it before reporting ready
      renderer.device.queue.onSubmittedWorkDone().then(() => { handle.ready = true; handle.gpuErrors = renderer.debugErrors.slice(); });
    }
    if (anim || handle.frames < 4 || qs.get('loop') === '1') requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

boot();
