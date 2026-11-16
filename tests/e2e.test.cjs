'use strict';
/*
 * e2e.test.cjs — drives the built index.html in headless Chromium with software
 * WebGPU and checks the things a person would check by hand:
 *
 *   boot · labels · grab at several locations · strong stretch · release decay
 *   ground contact · reset · pause / ¼ speed / mesh / presets · touch · fallback
 *
 *   node tools/build.cjs && node tests/e2e.test.cjs [--shots dir]
 *
 * Physics is stepped deterministically (app.state.manual + app.stepFrames) so
 * results do not depend on how slowly the software rasteriser draws.
 */
const fs = require('fs');
const path = require('path');
const { launch } = require('./harness.cjs');

const argShots = process.argv.indexOf('--shots');
const SHOTS = argShots > 0 ? path.resolve(process.argv[argShots + 1]) : path.join(__dirname, 'out');
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail === undefined ? '' : '  — ' + detail}`);
}
const f3 = (x) => (typeof x === 'number' ? x.toFixed(3) : String(x));

// Grab locations in material coordinates (x, y) on the camera-facing face.
const SPOTS = [
  { name: 'flesh centre', x: 0.0, y: 0.45, pull: [0, -150] },
  { name: 'rind top', x: 0.0, y: 0.98, pull: [0, -150] },
  { name: 'left tip', x: -0.9, y: 0.14, pull: [-150, -40] },
  { name: 'right flesh', x: 0.5, y: 0.3, pull: [140, -80] },
  { name: 'pith', x: 0.56, y: 0.62, pull: [110, -110] },
  { name: 'near base', x: 0.12, y: 0.08, pull: [0, -150] },
];

async function main() {
  // ───────────────────────── desktop, WebGPU ─────────────────────────
  const h = await launch({ width: 1100, height: 700 });
  await h.ready();
  const page = h.page;
  check('boots with WebGPU (no fallback)', await page.evaluate(() => !window.__citrus.fallback && !!window.__citrus.renderer));

  // let the intro drop play out, checking the ground the whole way
  await page.evaluate(() => { window.__citrus.app.state.manual = true; });
  const drop = await page.evaluate(() => {
    const { sim } = window.__citrus;
    sim.reset();
    let minY = Infinity, topMin = Infinity, topRest = -Infinity, peakSpeed = 0;
    const rest = window.__citrus.mesh.rest;
    for (let i = 1; i < rest.length; i += 3) topRest = Math.max(topRest, rest[i]);
    const tops = [];
    for (let f = 0; f < 240; f++) {
      sim.advance(1 / 60, 1);
      const m = sim.metrics();
      minY = Math.min(minY, m.minY);
      peakSpeed = Math.max(peakSpeed, m.maxSpeed);
      tops.push(m.maxY);
      topMin = Math.min(topMin, m.maxY);
    }
    const end = sim.metrics();
    return { minY, topMin, topRest, peakSpeed, tops, finite: end.finite, restDeviation: end.restDeviation, startTop: tops[0] };
  });
  check('intro drop: nothing goes through the ground', drop.minY > -1e-3, `minY ${f3(drop.minY)}`);
  check('intro drop: falls from above its rest height', drop.startTop > drop.topRest + 0.02, `start top ${f3(drop.startTop)} vs rest ${f3(drop.topRest)}`);
  check('intro drop: squashes on impact', drop.topMin < drop.topRest - 0.005, `lowest top ${f3(drop.topMin)} vs rest ${f3(drop.topRest)} (squash ${f3(drop.topRest - drop.topMin)})`);
  check('intro drop: settles back to rest', drop.finite && drop.restDeviation < 0.03, `restDeviation ${f3(drop.restDeviation)}`);
  await page.evaluate(() => window.__citrus.app.renderOnce());
  await h.shot(path.join(SHOTS, 'desktop-rest.png'));

  // labels
  const text = await page.evaluate(() => document.body.innerText);
  for (const label of ['Citrus Jelly.', 'Firmness', 'Internal damping', 'Give it a nudge', 'Reset', 'Pause', 'Show mesh', '¼ speed', 'Orange', 'Blood Orange', 'Lemon', 'Grab. Stretch. Let go.']) {
    check(`label present: ${label}`, text.toLowerCase().includes(label.toLowerCase()));
  }

  // helper evaluated in the page: screen position of the surface particle nearest a material point
  const spotScreen = (spot) => page.evaluate((s) => {
    const { mesh, sim, camera, ui } = window.__citrus;
    const front = mesh.thickness * 0.5;
    let best = -1, bd = Infinity;
    for (let i = 0; i < mesh.numParticles; i++) {
      if (!mesh.onSurface[i] || Math.abs(mesh.mat[i * 3 + 2] - front) > 1e-4) continue;
      const d = Math.hypot(mesh.mat[i * 3] - s.x, mesh.mat[i * 3 + 1] - s.y);
      if (d < bd) { bd = d; best = i; }
    }
    const p = sim.pos;
    const n = camera.project(p[best * 3], p[best * 3 + 1], p[best * 3 + 2]);
    const r = ui.canvas.getBoundingClientRect();
    return { i: best, x: r.left + (n[0] * 0.5 + 0.5) * r.width, y: r.top + (1 - (n[1] * 0.5 + 0.5)) * r.height };
  }, spot);

  const displacement = (grabIndex) => page.evaluate((gi) => {
    const { mesh, sim } = window.__citrus;
    const n = mesh.numParticles, rest = mesh.rest, pos = sim.pos;
    let maxD = 0, maxI = -1;
    const rows = [];
    for (let i = 0; i < n; i++) {
      const d = Math.hypot(pos[i * 3] - rest[i * 3], pos[i * 3 + 1] - rest[i * 3 + 1], pos[i * 3 + 2] - rest[i * 3 + 2]);
      const r = Math.hypot(rest[i * 3] - rest[gi * 3], rest[i * 3 + 1] - rest[gi * 3 + 1], rest[i * 3 + 2] - rest[gi * 3 + 2]);
      rows.push([r, d]);
      if (d > maxD) { maxD = d; maxI = i; }
    }
    rows.sort((a, b) => a[0] - b[0]);
    const q = Math.floor(n / 4);
    const mean = (a) => a.reduce((s, v) => s + v[1], 0) / a.length;
    const distOfMax = Math.hypot(rest[maxI * 3] - rest[gi * 3], rest[maxI * 3 + 1] - rest[gi * 3 + 1], rest[maxI * 3 + 2] - rest[gi * 3 + 2]);
    return { maxD, distOfMax, near: mean(rows.slice(0, q)), far: mean(rows.slice(n - q)), metrics: sim.metrics() };
  }, grabIndex);

  for (const spot of SPOTS) {
    await page.evaluate(() => { window.__citrus.sim.reset({ drop: false }); });
    await page.evaluate(() => window.__citrus.app.renderOnce());
    const s = await spotScreen(spot);
    await page.mouse.move(s.x, s.y);
    await page.mouse.down();
    const grabbed = await page.evaluate(() => window.__citrus.sim.grabCount);
    check(`[${spot.name}] pointer down grabs the slice`, grabbed === 1, `grabCount ${grabbed}`);
    for (let k = 1; k <= 6; k++) {
      await page.mouse.move(s.x + spot.pull[0] * k / 6, s.y + spot.pull[1] * k / 6);
      await page.evaluate(() => { window.__citrus.sim.advance(1 / 60, 1); window.__citrus.sim.advance(1 / 60, 1); });
    }
    await page.evaluate(() => window.__citrus.app.stepFrames(40));
    const d = await displacement(s.i);
    check(`[${spot.name}] deformation originates at the grab point`, d.distOfMax < 0.4, `most-moved particle is ${f3(d.distOfMax)} from the grab (moved ${f3(d.maxD)})`);
    check(`[${spot.name}] deformation falls off with distance`, d.far < d.near * 0.75 && d.maxD > 0.1, `near quartile ${f3(d.near)} vs far quartile ${f3(d.far)}`);
    check(`[${spot.name}] stays finite and un-inverted`, d.metrics.finite && d.metrics.minVolRatio > 0, `maxStretch ${f3(d.metrics.maxStretch)} minVol ${f3(d.metrics.minVolRatio)}`);
    await h.shot(path.join(SHOTS, `grab-${spot.name.replace(/\s+/g, '-')}.png`));
    await page.mouse.up();
    check(`[${spot.name}] pointer up releases`, (await page.evaluate(() => window.__citrus.sim.grabCount)) === 0);
  }

  // ── strong stretch, hold, release, decay ──
  await page.evaluate(() => { window.__citrus.sim.reset({ drop: false }); });
  await page.evaluate(() => window.__citrus.app.renderOnce());
  const top = await spotScreen({ x: 0.0, y: 0.7 });
  await page.mouse.move(top.x, top.y);
  await page.mouse.down();
  for (let k = 1; k <= 12; k++) {
    await page.mouse.move(top.x + 30 * k / 12, top.y - 330 * k / 12);
    await page.evaluate(() => { for (let i = 0; i < 3; i++) window.__citrus.sim.advance(1 / 60, 1); });
  }
  await page.evaluate(() => window.__citrus.app.stepFrames(90));
  const strong = await page.evaluate(() => window.__citrus.sim.metrics());
  check('strong stretch: finite, limited, no inverted elements', strong.finite && strong.maxStretch < 3.2 && strong.minVolRatio > 0,
    `maxStretch ${f3(strong.maxStretch)} minVolRatio ${f3(strong.minVolRatio)} restDeviation ${f3(strong.restDeviation)}`);
  check('strong stretch: the slice really is stretched', strong.maxStretch > 1.25, `maxStretch ${f3(strong.maxStretch)}`);
  await h.shot(path.join(SHOTS, 'strong-stretch.png'));
  await page.evaluate(() => { window.__citrus.renderer.setShowMesh(true); window.__citrus.app.state.showMesh = true; });
  await page.evaluate(() => window.__citrus.app.renderOnce());
  await h.shot(path.join(SHOTS, 'strong-stretch-mesh.png'));
  await page.evaluate(() => { window.__citrus.renderer.setShowMesh(false); window.__citrus.app.state.showMesh = false; });

  await page.mouse.up();
  const decay = await page.evaluate(() => {
    const { sim } = window.__citrus;
    const series = [];
    const d0 = sim.metrics().restDeviation;
    for (let f = 0; f < 360; f++) {
      sim.advance(1 / 60, 1);
      if (f % 3 === 2) { const m = sim.metrics(); series.push([+(f / 60).toFixed(2), m.restDeviation, m.kinetic, m.minY]); }
    }
    return { d0, series, end: sim.metrics() };
  });
  const at = (t) => decay.series.find((r) => r[0] >= t) || decay.series[decay.series.length - 1];
  check('release: not an instant snap back', at(0.1)[1] > decay.d0 * 0.25, `restDeviation ${f3(decay.d0)} → ${f3(at(0.1)[1])} after 0.1 s`);
  check('release: oscillation dies out', decay.end.restDeviation < 0.03 && decay.end.kinetic < 1e-3, `after 6 s restDeviation ${f3(decay.end.restDeviation)} kinetic ${decay.end.kinetic.toExponential(2)}`);
  check('release: never below the ground', Math.min(...decay.series.map((r) => r[3])) > -1e-3);
  console.log('      decay (t, restDeviation): ' + decay.series.filter((_, i) => i % 5 === 0).map((r) => `${r[0]}:${r[1].toFixed(3)}`).join('  '));
  await page.evaluate(() => window.__citrus.app.renderOnce());
  await h.shot(path.join(SHOTS, 'after-release.png'));

  // ── controls ──
  await page.evaluate(() => { window.__citrus.app.state.manual = false; });
  await page.getByRole('button', { name: /give it a nudge/i }).click();
  const nudged = await page.evaluate(() => { const { sim } = window.__citrus; for (let i = 0; i < 6; i++) sim.advance(1 / 60, 1); return sim.metrics(); });
  check('nudge: sets the slice in motion', nudged.kinetic > 1e-4 && nudged.finite, `kinetic ${nudged.kinetic.toExponential(2)}`);
  await page.getByRole('button', { name: /^reset$/i }).click();
  const afterReset = await page.evaluate(() => { const { sim } = window.__citrus; for (let i = 0; i < 300; i++) sim.advance(1 / 60, 1); return sim.metrics(); });
  check('reset: returns to the rest pose', afterReset.finite && afterReset.restDeviation < 0.02, `restDeviation ${f3(afterReset.restDeviation)}`);

  await page.getByRole('button', { name: /^pause$/i }).click();
  check('pause: app is paused and button reads Resume', await page.evaluate(() => window.__citrus.app.state.paused) && (await page.getByRole('button', { name: /^resume$/i }).count()) === 1);
  await page.getByRole('button', { name: /^resume$/i }).click();
  check('resume: app runs again', !(await page.evaluate(() => window.__citrus.app.state.paused)));

  await page.getByLabel(/show mesh/i).click({ force: true });
  check('show mesh toggle reaches the app', await page.evaluate(() => window.__citrus.app.state.showMesh === true));
  await page.waitForTimeout(600);
  await h.shot(path.join(SHOTS, 'desktop-mesh.png'));
  await page.getByLabel(/show mesh/i).click({ force: true });
  await page.getByLabel(/¼ speed/i).click({ force: true });
  check('¼ speed toggle reaches the app', await page.evaluate(() => window.__citrus.app.state.slowMo === true));
  await page.getByLabel(/¼ speed/i).click({ force: true });

  for (const [label, id] of [['Blood Orange', 'blood'], ['Lemon', 'lemon'], ['Orange', 'orange']]) {
    await page.getByLabel(new RegExp('^' + label + '$', 'i')).click({ force: true });
    check(`preset ${label} selected`, await page.evaluate((x) => window.__citrus.ui.values.preset === x, id));
    await page.waitForTimeout(1500);
    await h.shot(path.join(SHOTS, `preset-${id}.png`));
  }

  // sliders drive the simulation
  await page.getByLabel(/firmness/i).fill('1');
  await page.getByLabel(/internal damping/i).fill('0');
  const slid = await page.evaluate(() => ({ ...window.__citrus.ui.values }));
  check('sliders report normalised values', slid.firmness >= 0 && slid.firmness <= 1 && slid.damping >= 0 && slid.damping <= 1, JSON.stringify(slid));

  check('no console errors on desktop', h.errors().length === 0, h.errors().map((e) => e.text).join(' | ').slice(0, 400));
  await h.close();

  // ───────────────────────── phone, touch ─────────────────────────
  const m = await launch({ width: 390, height: 844, dpr: 2, mobile: true });
  await m.ready();
  await m.page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); });
  await m.page.evaluate(() => window.__citrus.app.renderOnce());
  await m.shot(path.join(SHOTS, 'phone-rest.png'));
  const overflow = await m.page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, sh: document.documentElement.scrollHeight, ch: document.documentElement.clientHeight }));
  check('phone: no horizontal overflow', overflow.sw <= overflow.cw + 1, JSON.stringify(overflow));
  const mc = await m.page.evaluate(() => {
    const { sim, camera, ui, mesh } = window.__citrus;
    let best = 0, bd = Infinity;
    for (let i = 0; i < mesh.numParticles; i++) {
      if (!mesh.onSurface[i] || mesh.mat[i * 3 + 2] < mesh.thickness * 0.49) continue;
      const d = Math.hypot(mesh.mat[i * 3], mesh.mat[i * 3 + 1] - 0.5);
      if (d < bd) { bd = d; best = i; }
    }
    const n = camera.project(sim.pos[best * 3], sim.pos[best * 3 + 1], sim.pos[best * 3 + 2]);
    const r = ui.canvas.getBoundingClientRect();
    return { x: r.left + (n[0] * 0.5 + 0.5) * r.width, y: r.top + (1 - (n[1] * 0.5 + 0.5)) * r.height };
  });
  const cdp = await m.touchDrag([mc.x, mc.y], [mc.x + 20, mc.y - 120], { steps: 8, release: false });
  const touchGrab = await m.page.evaluate(() => { const c = window.__citrus; const g = c.sim.grabCount; for (let i = 0; i < 40; i++) c.sim.advance(1 / 60, 1); return { g, m: c.sim.metrics() }; });
  check('phone: a finger grabs and stretches the slice', touchGrab.g === 1 && touchGrab.m.restDeviation > 0.02 && touchGrab.m.finite, `grabCount ${touchGrab.g} restDeviation ${f3(touchGrab.m.restDeviation)}`);
  await m.page.evaluate(() => window.__citrus.app.renderOnce());
  await m.shot(path.join(SHOTS, 'phone-stretch.png'));
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  check('phone: lifting the finger releases', (await m.page.evaluate(() => window.__citrus.sim.grabCount)) === 0);
  check('no console errors on phone', m.errors().length === 0, m.errors().map((e) => e.text).join(' | ').slice(0, 400));
  await m.close();

  // ───────────────────────── fallback ─────────────────────────
  for (const [name, opts] of [['no adapter', { webgpu: false }], ['no navigator.gpu', { webgpu: false, removeGpu: true }]]) {
    const fb = await launch({ width: 1100, height: 700, ...opts });
    await fb.ready(20000);
    const t = await fb.page.evaluate(() => document.body.innerText);
    check(`fallback (${name}): clear WebGPU message`, /webgpu/i.test(t) && (await fb.page.evaluate(() => window.__citrus.fallback === 'unsupported')));
    check(`fallback (${name}): no uncaught errors`, fb.errors().length === 0, fb.errors().map((e) => e.text).join(' | ').slice(0, 300));
    await fb.shot(path.join(SHOTS, `fallback-${name.replace(/[^a-z]+/g, '-')}.png`));
    await fb.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) { for (const r of failed) console.log('  FAILED: ' + r.name + (r.detail ? ' — ' + r.detail : '')); process.exit(1); }
}

main().catch((err) => { console.error(err); process.exit(1); });
