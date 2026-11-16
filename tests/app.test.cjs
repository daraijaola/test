'use strict';
/*
 * app.test.cjs — what the integration layer (src/main.js) promises, checked in
 * headless Chromium with software WebGPU: the picture really is drawn (pixels),
 * controls reach the simulation and the renderer, picking is forgiving, the
 * keyboard works, nothing is redrawn while nothing moves, picture quality adapts
 * sensibly, a lost device is recovered, and failures end in a message.
 *
 *   node tools/build.cjs && node tests/app.test.cjs [--shots dir]
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
const rgb = (c) => `rgb(${c.map((v) => Math.round(v)).join(',')})`;
const errorTexts = (h) => h.errors().map((e) => e.text).join(' | ').slice(0, 300);

// ───────────────────────────── helpers evaluated in the page ─────────────────────────────
/** Screen-space facts about the slice: bounding box, a flesh point, the top of the pickable outline. */
const sliceInfo = (page) => page.evaluate(() => {
  const { mesh, sim, camera, ui } = window.__citrus;
  const r = ui.canvas.getBoundingClientRect(), p = sim.pos;
  const px = (x, y, z) => { const n = camera.project(x, y, z); return [r.left + (n[0] * 0.5 + 0.5) * r.width, r.top + (1 - (n[1] * 0.5 + 0.5)) * r.height]; };
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  const front = mesh.thickness * 0.5;
  let flesh = -1, bd = 1e9;
  for (let i = 0; i < mesh.numParticles; i++) {
    if (!mesh.onSurface[i]) continue;
    const s = px(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]);
    x0 = Math.min(x0, s[0]); x1 = Math.max(x1, s[0]); y0 = Math.min(y0, s[1]); y1 = Math.max(y1, s[1]);
    if (Math.abs(mesh.mat[i * 3 + 2] - front) < 1e-4) {
      const d = Math.hypot(mesh.mat[i * 3] - 0.3, mesh.mat[i * 3 + 1] - 0.45);
      if (d < bd) { bd = d; flesh = i; }
    }
  }
  const f = px(p[flesh * 3], p[flesh * 3 + 1], p[flesh * 3 + 2]);
  // walk up from the flesh point until the ray misses: the last pickable pixel row
  const ray = { origin: new Float32Array(3), dir: new Float32Array(3) };
  const hits = (x, y) => { camera.rayFromNdc(((x - r.left) / r.width) * 2 - 1, 1 - ((y - r.top) / r.height) * 2, ray); return Boolean(sim.raycast(ray.origin, ray.dir)); };
  let edgeY = f[1];
  while (edgeY > 0 && hits(f[0], edgeY - 1)) edgeY -= 1;
  return { x0, x1, y0, y1, flesh: f, edge: [f[0], edgeY], width: innerWidth, height: innerHeight };
});

/** Decodes a PNG screenshot in the page (no image library needed) and returns statistics of some regions. */
async function regions(page, rects) {
  const b64 = (await page.screenshot({ type: 'png' })).toString('base64');
  return page.evaluate(async ({ b64, rects }) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = new OffscreenCanvas(img.width, img.height), g = c.getContext('2d');
    g.drawImage(img, 0, 0);
    const k = img.width / innerWidth;
    return rects.map((q) => {
      const x = Math.max(0, Math.round(q.x * k)), y = Math.max(0, Math.round(q.y * k));
      const w = Math.max(1, Math.min(img.width - x, Math.round(q.w * k))), h = Math.max(1, Math.min(img.height - y, Math.round(q.h * k)));
      const d = g.getImageData(x, y, w, h).data;
      let r = 0, gg = 0, b = 0, sat = 0, white = 0;
      const n = d.length / 4;
      for (let i = 0; i < d.length; i += 4) {
        r += d[i]; gg += d[i + 1]; b += d[i + 2];
        const mx = Math.max(d[i], d[i + 1], d[i + 2]), mn = Math.min(d[i], d[i + 1], d[i + 2]);
        if (mx > 0 && (mx - mn) / mx > 0.35) sat++;
        if (mn >= 250) white++;
      }
      return { mean: [r / n, gg / n, b / n], luma: (0.2126 * r + 0.7152 * gg + 0.0722 * b) / n, saturated: sat / n, white: white / n, data: q.keep ? Array.from(d) : null };
    });
  }, { b64, rects });
}
const around = (pt, half) => ({ x: pt[0] - half, y: pt[1] - half, w: half * 2, h: half * 2 });
const draw = (page) => page.evaluate(() => window.__citrus.app.renderOnce());

// ───────────────────────────── the main desktop session ─────────────────────────────
async function desktop() {
  const h = await launch({ width: 900, height: 600 });
  await h.ready();
  const page = h.page;
  const rest = () => page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); c.camera.yaw = 0.42; c.camera.pitch = 0.24; c.camera.update(); });
  await rest();
  await draw(page);

  // ── the picture ──
  let s = await sliceInfo(page);
  const box = { x: s.x0, y: s.y0, w: s.x1 - s.x0, h: s.y1 - s.y0 };
  const inner = { x: s.x0 + box.w * 0.25, y: s.y0 + box.h * 0.35, w: box.w * 0.5, h: box.h * 0.5 };
  const corner = { x: 4, y: s.height - 24, w: 20, h: 20 };
  const under = { x: s.x0 + box.w * 0.3, y: s.y1 + 6, w: box.w * 0.4, h: 10 };
  let px = await regions(page, [corner, inner, around(s.flesh, 5), under, box]);
  check('pixels: the backdrop is the paper colour', px[0].mean.every((v, i) => Math.abs(v - [246, 240, 228][i]) <= 3), rgb(px[0].mean));
  check('pixels: the slice is drawn, saturated orange', px[1].saturated > 0.8 && px[1].mean[0] > 190 && px[1].mean[0] > px[1].mean[1] + 50 && px[1].mean[1] > px[1].mean[2] + 20,
    `${rgb(px[1].mean)}, ${(px[1].saturated * 100).toFixed(0)} % saturated`);
  check('pixels: no blown-out white in the slice', px[4].white < 0.01, `${(px[4].white * 100).toFixed(2)} % of the slice box`);
  check('pixels: a contact shadow lies under the slice', px[3].luma < px[0].luma - 6, `luma ${px[3].luma.toFixed(1)} under the base vs ${px[0].luma.toFixed(1)} paper`);
  await h.shot(path.join(SHOTS, 'app-rest.png'));

  const before = (await regions(page, [{ ...box, keep: true }]))[0].data;
  await page.getByLabel(/show mesh/i).click({ force: true });
  await draw(page);
  const after = (await regions(page, [{ ...box, keep: true }]))[0].data;
  let diff = 0;
  for (let i = 0; i < before.length; i++) diff += Math.abs(before[i] - after[i]);
  check('pixels: Show mesh draws the mesh over the slice', diff / before.length > 3, `mean change ${(diff / before.length).toFixed(1)} levels`);
  await page.getByLabel(/show mesh/i).click({ force: true });

  for (const [label, id, test] of [
    ['Lemon', 'lemon', (c) => c[0] > 200 && c[1] > 170 && c[2] < 140],
    ['Blood Orange', 'blood', (c) => c[0] > 130 && c[1] < 110 && c[0] > c[1] * 1.7],
    ['Orange', 'orange', (c) => c[0] > 200 && c[1] > 80 && c[1] < 170 && c[2] < 110],
  ]) {
    await page.getByLabel(new RegExp('^' + label + '$', 'i')).click({ force: true });
    await page.waitForFunction((x) => { const r = window.__citrus.renderer; return r.palette === x && !r.animating; }, id, { timeout: 30000 });
    await draw(page);
    const c = (await regions(page, [around(s.flesh, 5)]))[0].mean;
    check(`pixels: ${label} reaches the renderer and the screen`, test(c), `flesh ${rgb(c)}`);
  }

  // ── a pull colours the area above the resting outline, and the heading steps back ──
  const above = { x: s.edge[0] - 12, y: Math.max(0, s.y0 - 70), w: 24, h: 40 };
  const emptyAbove = (await regions(page, [above]))[0].saturated;
  await page.mouse.move(s.edge[0], s.edge[1] + 25);
  await page.mouse.down();
  for (let k = 1; k <= 8; k++) {
    await page.mouse.move(s.edge[0], s.edge[1] + 25 - 160 * k / 8);
    await page.evaluate(() => { for (let i = 0; i < 3; i++) window.__citrus.sim.advance(1 / 60, 1); });
  }
  await page.evaluate(() => window.__citrus.app.stepFrames(20));
  const pulled = (await regions(page, [above]))[0].saturated;
  check('pixels: a pulled slice is drawn where it was pulled to', emptyAbove < 0.05 && pulled > 0.5, `saturated share above the rest outline ${f3(emptyAbove)} → ${f3(pulled)}`);
  const underTitle = await page.evaluate(() => {
    const { ui, sim, camera, mesh } = window.__citrus;
    const t = ui.getTitleRect(), r = ui.canvas.getBoundingClientRect(), p = sim.pos;
    let inside = false;
    for (let i = 0; i < mesh.numParticles && !inside; i++) {
      if (!mesh.onSurface[i]) continue;
      const n = camera.project(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]);
      const x = r.left + (n[0] * 0.5 + 0.5) * r.width, y = r.top + (1 - (n[1] * 0.5 + 0.5)) * r.height;
      inside = x > t.x + 8 && x < t.x + t.width - 8 && y > t.y + 8 && y < t.y + t.height - 8;
    }
    return { inside, flag: ui.root.hasAttribute('data-under-title') };
  });
  check('heading: steps back exactly while the slice is behind it', underTitle.flag === underTitle.inside, JSON.stringify(underTitle));

  // ── a grab survives a resize ──
  await page.setViewportSize({ width: 820, height: 600 });
  await draw(page);
  check('resize while holding: the grab is kept', (await page.evaluate(() => window.__citrus.sim.grabCount)) === 1);
  await page.mouse.up();
  await page.setViewportSize({ width: 900, height: 600 });
  await page.evaluate(() => window.__citrus.app.stepFrames(200));
  check('heading: comes back when the slice has gone home', !(await page.evaluate(() => window.__citrus.ui.root.hasAttribute('data-under-title'))));

  // ── forgiving picking ──
  await rest();
  await draw(page);
  s = await sliceInfo(page);
  const tryPress = async (x, y) => {
    await page.mouse.move(x, y);
    await page.mouse.down();
    const g = await page.evaluate(() => window.__citrus.sim.grabCount);
    await page.mouse.move(x + 40, y);
    const yaw = await page.evaluate(() => window.__citrus.camera.yaw);
    await page.mouse.up();
    await rest();
    return { g, yaw };
  };
  const near = await tryPress(s.edge[0], s.edge[1] - 3);
  check('picking: a press 3 px outside the pickable outline still grabs', near.g === 1 && Math.abs(near.yaw - 0.42) < 1e-6, JSON.stringify(near));
  const far = await tryPress(s.edge[0], s.edge[1] - 40);
  check('picking: a press well away from the slice orbits the camera', far.g === 0 && Math.abs(far.yaw - 0.42) > 0.05, JSON.stringify(far));
  await page.mouse.move(s.edge[0], s.edge[1] - 40);
  await page.mouse.down(); await page.mouse.move(s.edge[0] + 60, s.edge[1] - 20); await page.mouse.up();
  await page.getByRole('button', { name: /^reset$/i }).click();
  const cam = await page.evaluate(() => [window.__citrus.camera.yaw, window.__citrus.camera.pitch]);
  check('reset: restores the camera after an orbit', Math.abs(cam[0] - 0.42) < 1e-6 && Math.abs(cam[1] - 0.24) < 1e-6, cam.map(f3).join(', '));
  await page.mouse.move(s.flesh[0], s.flesh[1], { button: 'right' });
  await page.mouse.down({ button: 'right' });
  check('picking: the right button does not grab', (await page.evaluate(() => window.__citrus.sim.grabCount)) === 0);
  await page.mouse.up({ button: 'right' });

  // ── sliders reach the simulation and show their effect ──
  await page.evaluate(() => { const c = window.__citrus; c.app.state.manual = false; c.sim.reset({ drop: false }); });
  await page.getByLabel(/firmness/i).fill('0.9');
  await page.getByLabel(/internal damping/i).fill('0.2');
  const set = await page.evaluate(() => ({ f: window.__citrus.sim.firmness, d: window.__citrus.sim.damping }));
  check('sliders: Firmness and Internal damping reach the simulation', Math.abs(set.f - 0.9) < 1e-6 && Math.abs(set.d - 0.2) < 1e-6, JSON.stringify(set));
  await page.waitForTimeout(450);
  const swayed = await page.evaluate(() => { const { sim } = window.__citrus; let peak = 0; for (let i = 0; i < 40; i++) { sim.advance(1 / 60, 1); peak = Math.max(peak, sim.metrics().restDeviation); } return { peak, mode: sim.metrics().mode, minY: sim.metrics().minY }; });
  check('sliders: a change gives the resting slice a small sway on the spot', swayed.peak > 0.02 && swayed.peak < 0.3 && swayed.mode === 'stuck' && swayed.minY < 0.01, JSON.stringify(swayed));
  await page.getByLabel(/firmness/i).fill('0.5');
  await page.getByLabel(/internal damping/i).fill('0.5');

  // ── keyboard ──
  await page.getByRole('button', { name: /give it a nudge/i }).click();
  await page.getByRole('button', { name: /^reset$/i }).click();
  await page.evaluate(() => { const c = window.__citrus; c.sim.reset({ drop: false }); c.app.state.manual = true; });
  await draw(page);
  s = await sliceInfo(page);
  await page.mouse.move(s.flesh[0], s.flesh[1]);
  await page.mouse.down();
  const focusAfterPress = await page.evaluate(() => document.activeElement === document.body || document.activeElement === null);
  check('keyboard: pressing the stage takes focus back from the panel', focusAfterPress);
  await page.keyboard.press(' ');
  let st = await page.evaluate(() => ({ paused: window.__citrus.app.state.paused, grabs: window.__citrus.sim.grabCount }));
  check('keyboard: Space pauses (and lets go of the slice) instead of pressing the last button', st.paused === true && st.grabs === 0, JSON.stringify(st));
  await page.mouse.up();
  await page.keyboard.down(' ');
  for (let i = 0; i < 8; i++) await page.keyboard.down(' ');        // auto-repeat
  await page.keyboard.up(' ');
  check('keyboard: a held Space toggles once', (await page.evaluate(() => window.__citrus.app.state.paused)) === false);

  await page.evaluate(() => { const c = window.__citrus; c.camera.yaw = 1.0; c.camera.update(); });
  await page.getByLabel(/firmness/i).focus();
  await page.keyboard.press('r');
  check('keyboard: R resets like the button, also while a slider has focus', Math.abs((await page.evaluate(() => window.__citrus.camera.yaw)) - 0.42) < 1e-6);
  await page.evaluate(() => { const c = window.__citrus; c.sim.reset({ drop: false }); });
  await page.keyboard.down('n');
  let hop = 0;
  for (let i = 0; i < 20; i++) {                                    // auto-repeat for 80 simulated frames
    await page.keyboard.down('n');
    hop = Math.max(hop, await page.evaluate(() => { const { sim } = window.__citrus; let top = 0; for (let k = 0; k < 4; k++) { sim.advance(1 / 60, 1); top = Math.max(top, sim.metrics().minY); } return top; }));
  }
  await page.keyboard.up('n');
  check('keyboard: a held N nudges once and the slice stays in view', hop > 0.05 && hop < 1.2, `highest slice bottom ${f3(hop)}`);
  await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());

  // ── pause and reset ──
  await page.evaluate(() => { window.__citrus.app.state.manual = false; });
  await page.getByRole('button', { name: /^pause$/i }).click();
  await page.getByRole('button', { name: /^reset$/i }).click();
  await page.waitForTimeout(300);
  const pr = await page.evaluate(() => { const m = window.__citrus.sim.metrics(); return { minY: m.minY, mode: m.mode, paused: window.__citrus.app.state.paused }; });
  check('reset while paused: the slice is on the ground, not hanging in mid-air', pr.paused && pr.minY < 0.01 && pr.mode === 'stuck', JSON.stringify(pr));

  // ── the simulation clock: paused, quarter speed, normal ──
  const clock = async (frames) => page.evaluate((n) => new Promise((resolve) => {
    const c = window.__citrus, f0 = c.app.frames, t0 = c.sim.time;
    const tick = () => { if (c.app.frames - f0 >= n) resolve((c.sim.time - t0) / (c.app.frames - f0)); else requestAnimationFrame(tick); };
    c.sim.wake(); tick();
  }), frames);
  // (drawing is switched off for this: the software rasteriser would stretch every frame past the
  // longest step the loop accepts, and the two speeds could not be told apart)
  await page.evaluate(() => { const r = window.__citrus.renderer; r.realRender = r.render; r.render = () => {}; });
  const pausedRate = await clock(10);
  await page.getByRole('button', { name: /^resume$/i }).click();
  await page.evaluate(() => window.__citrus.sim.nudge(1));
  await clock(6);
  const normalRate = await clock(20);
  await page.getByLabel(/¼ speed/i).click({ force: true });
  await page.evaluate(() => window.__citrus.sim.nudge(1));
  await clock(6);
  const slowRate = await clock(20);
  await page.getByLabel(/¼ speed/i).click({ force: true });
  await page.evaluate(() => { const r = window.__citrus.renderer; r.render = r.realRender; delete r.realRender; window.__citrus.app.invalidate(3); });
  check('clock: paused 0, ¼ speed a quarter of normal', pausedRate === 0 && normalRate > 0 && Math.abs(slowRate / normalRate - 0.25) < 0.06,
    `sim seconds per frame: paused ${f3(pausedRate)}, normal ${f3(normalRate)}, ¼ speed ${f3(slowRate)}`);

  // ── nothing is redrawn while nothing moves ──
  await page.evaluate(() => { const c = window.__citrus; c.sim.reset({ drop: false }); });
  await page.waitForFunction(() => window.__citrus.sim.sleeping, null, { timeout: 60000 });
  await page.waitForTimeout(1200);
  const idle = await page.evaluate(() => new Promise((resolve) => { const a = window.__citrus.app, d0 = a.drawn, f0 = a.frames; setTimeout(() => resolve({ drawn: a.drawn - d0, frames: a.frames - f0 }), 1500); }));
  check('idle: no frames are drawn while the slice sleeps', idle.drawn === 0 && idle.frames > 3, JSON.stringify(idle));
  const d1 = await page.evaluate(() => window.__citrus.app.drawn);
  await page.getByLabel(/^lemon$/i).click({ force: true });
  await page.waitForFunction(() => { const r = window.__citrus.renderer; return r.palette === 'lemon' && !r.animating; }, null, { timeout: 30000 });
  await page.waitForTimeout(600);
  const c2 = (await regions(page, [around(s.flesh, 5)]))[0].mean;
  check('idle: a preset change is still drawn to the end of its fade', (await page.evaluate(() => window.__citrus.app.drawn)) > d1 && c2[1] > 170 && c2[2] < 140, `flesh ${rgb(c2)}`);
  await page.getByLabel(/^orange$/i).click({ force: true });
  await page.getByRole('button', { name: /^pause$/i }).click();
  await page.waitForTimeout(800);
  const pausedDraws = await page.evaluate(() => new Promise((resolve) => { const a = window.__citrus.app, d0 = a.drawn; setTimeout(() => resolve(a.drawn - d0), 1200); }));
  check('idle: no frames are drawn while paused', pausedDraws === 0, `${pausedDraws} draws`);
  await page.getByRole('button', { name: /^resume$/i }).click();

  // ── window blur lets go ──
  await page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); });
  await draw(page);
  s = await sliceInfo(page);
  await page.mouse.move(s.flesh[0], s.flesh[1]);
  await page.mouse.down();
  const held = await page.evaluate(() => window.__citrus.sim.grabCount);
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  check('blur: a held slice is released when the window loses focus', held === 1 && (await page.evaluate(() => window.__citrus.sim.grabCount)) === 0);
  await page.mouse.up();

  check('no console errors in the desktop session', h.errors().length === 0, errorTexts(h));
  await h.close();
}

// ───────────────────────────── picture quality governor (policy, synthetic frames) ─────────────────────────────
async function governor() {
  const h = await launch({ width: 640, height: 420, quality: 'auto' });
  await h.ready();
  // The policy is fed synthetic frame times; each model says how long a frame takes at a quality level.
  const run = (model) => h.page.evaluate((model) => {
    const c = window.__citrus, q = c.app.quality;
    c.app.state.manual = true;
    q.mode = 'auto'; q.restore(); q.skip = 0;
    const cost = [1, 0.55, 0.38, 0.28];                      // relative GPU work per level (steps and pixels)
    let gpu = 0;
    Object.defineProperty(c.renderer, 'gpuMs', { configurable: true, get: () => gpu });
    let now = 1000, lowest = 0, changes = 0, last = q.level, reduced = 0, total = 0;
    const seq = [];
    for (let i = 0; i < model.frames; i++) {
      const lvl = q.level;
      let dt, cpu = 2;
      if (model.kind === 'gpu') { const ms = model.fullMs * cost[lvl]; dt = Math.ceil(ms / 16.667) * 16.667; gpu = model.blind ? 0 : ms; }
      else if (model.kind === 'cap30') { dt = 33.333; gpu = model.blind ? 0 : 4; }
      else if (model.kind === 'hiccup') { dt = i % 15 === 0 ? 30 : 14.5; gpu = 5; }
      else if (model.kind === 'cpu') { dt = 33.333; cpu = 26; gpu = 5; }
      else if (model.kind === 'relief') { const ms = (i < model.until ? model.fullMs : 3) * cost[lvl]; dt = Math.max(16.667, Math.ceil(ms / 16.667) * 16.667); gpu = ms; }
      now += dt;
      q.sample(dt / 1000, cpu, now);
      if (q.level !== last) { changes++; last = q.level; seq.push(q.level); }
      lowest = Math.max(lowest, q.level);
      total++; if (lvl > 0) reduced++;
    }
    const out = { level: q.level, lowest, changes, reducedShare: reduced / total, steps: c.renderer.steps, scale: c.app.resolutionScale, seq: seq.slice(0, 12) };
    delete c.renderer.gpuMs;
    return out;
  }, model);

  let r = await run({ kind: 'cap30', frames: 3000 });
  check('quality: a 30 Hz display with an idle GPU keeps full quality', r.level === 0 && r.changes === 0, JSON.stringify(r));
  r = await run({ kind: 'cap30', blind: true, frames: 6000 });
  check('quality: with no GPU timing, a 30 Hz cap costs only brief experiments', r.level === 0 && r.changes <= 6 && r.reducedShare < 0.05, JSON.stringify(r));
  r = await run({ kind: 'hiccup', frames: 3000 });
  check('quality: an occasional late frame changes nothing', r.level === 0 && r.changes === 0, JSON.stringify(r));
  r = await run({ kind: 'cpu', frames: 3000 });
  check('quality: slow JavaScript is not answered with fewer pixels', r.level === 0 && r.changes === 0, JSON.stringify(r));
  r = await run({ kind: 'gpu', fullMs: 30, frames: 1500 });
  check('quality: a GPU that needs 30 ms a frame is relieved until it holds 60 fps', r.level >= 1 && r.level <= 2 && r.steps === 9 && r.changes <= 3, JSON.stringify(r));
  r = await run({ kind: 'gpu', fullMs: 30, blind: true, frames: 1500 });
  check('quality: the same without GPU timing', r.level >= 1 && r.level <= 2 && r.changes <= 3, JSON.stringify(r));
  r = await run({ kind: 'gpu', fullMs: 120, frames: 3000 });
  check('quality: a very slow GPU goes to the lowest level and stays there', r.level === 3 && r.scale === 0.6 && r.changes <= 4, JSON.stringify(r));
  r = await run({ kind: 'relief', fullMs: 40, until: 1500, frames: 9000 });
  check('quality: full quality comes back when the load has gone', r.lowest >= 1 && r.level === 0, JSON.stringify(r));

  const reset = await h.page.evaluate(() => {
    const c = window.__citrus, q = c.app.quality;
    q.apply(3);
    document.getElementById('cj-reset').click();
    return { level: q.level, steps: c.renderer.steps, scale: c.app.resolutionScale };
  });
  check('quality: Reset restores full quality', reset.level === 0 && reset.steps === 14 && reset.scale === 1, JSON.stringify(reset));
  await h.close();
}

// ───────────────────────────── slow CPU ─────────────────────────────
async function slowCpu() {
  const h = await launch({ width: 480, height: 320 });
  await h.ready();
  const cdp = await h.context.newCDPSession(h.page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 6 });
  const m = await h.page.evaluate(() => new Promise((resolve) => {
    const c = window.__citrus;
    c.sim.nudge(1);
    let n = 0, worst = 0, last = c.sim.steps;
    const tick = () => {
      c.sim.wake();
      const k = c.sim.steps - last; last = c.sim.steps;
      if (n > 12) worst = Math.max(worst, k);
      if (++n > 40) resolve({ subMs: c.app.subMs, simMs: c.app.simMs, worstSubsteps: worst }); else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }));
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
  check('slow CPU: physics per frame is capped by its measured cost', m.worstSubsteps < 30 && m.worstSubsteps * m.subMs < 24, JSON.stringify(m));
  await h.close();
}

// ───────────────────────────── device loss ─────────────────────────────
async function deviceLoss() {
  const h = await launch({ width: 640, height: 420 });
  await h.ready();
  const page = h.page;
  await page.evaluate(() => { const c = window.__citrus; c.sim.reset({ drop: false }); c.app.state.manual = true; });
  await draw(page);
  const s = await sliceInfo(page);
  await page.mouse.move(s.flesh[0], s.flesh[1]);
  await page.mouse.down();
  await page.mouse.move(s.flesh[0] + 60, s.flesh[1] - 60);
  await page.evaluate(() => window.__citrus.app.stepFrames(20));
  await page.mouse.up();
  await page.getByLabel(/^lemon$/i).click({ force: true });
  const lose = async () => {
    const pose = await page.evaluate(() => { const c = window.__citrus; window.__old = c.renderer; const d = c.sim.metrics().restDeviation; c.renderer.device.destroy(); return d; });
    return pose;
  };
  const recovered = async () => {
    await page.waitForFunction(() => { const c = window.__citrus; return c.fallback || (c.renderer !== window.__old && c.app.state.running); }, null, { timeout: 60000 });
    return page.evaluate(() => { const c = window.__citrus; return { fallback: c.fallback || null, pose: c.sim.metrics().restDeviation, palette: c.renderer.palette, running: c.app.state.running }; });
  };
  const pose = await lose();
  let r = await recovered();
  check('device loss: the renderer is rebuilt in place', !r.fallback && r.running && r.palette === 'lemon' && Math.abs(r.pose - pose) < 1e-9 && pose > 0.05, JSON.stringify(r));
  await draw(page);
  await page.waitForTimeout(300);
  const c = (await regions(page, [around(s.flesh, 30)]))[0];
  check('device loss: the scene is drawn again afterwards', c.saturated > 0.3, `${(c.saturated * 100).toFixed(0)} % saturated around the slice`);
  await h.shot(path.join(SHOTS, 'app-after-device-loss.png'));
  await lose(); r = await recovered();
  check('device loss: a second loss is recovered too', !r.fallback && r.running, JSON.stringify(r));
  await lose(); r = await recovered();
  const text = await page.evaluate(() => document.body.innerText);
  check('device loss: losses that keep coming end in a message with Reload', r.fallback === 'lost' && /graphics device/i.test(text) && (await page.getByRole('button', { name: /reload/i }).count()) === 1, JSON.stringify(r));
  await h.close();
}

// ───────────────────────────── failures end in a message ─────────────────────────────
async function failures() {
  let h = await launch({ width: 640, height: 420 });
  await h.ready();
  await h.page.evaluate(() => { window.__citrus.renderer.render = () => { throw new Error('boom'); }; window.__citrus.sim.nudge(1); });
  await h.page.waitForFunction(() => window.__citrus.fallback, null, { timeout: 60000 });
  let t = await h.page.evaluate(() => ({ kind: window.__citrus.fallback, text: document.body.innerText, running: window.__citrus.app.state.running }));
  check('failure: a frame that keeps throwing stops behind a message', t.kind === 'crashed' && !t.running && /stopped unexpectedly/i.test(t.text) && /boom/.test(t.text), t.kind);
  check('failure: it is reported once, not once per frame', h.errors().length <= 2, `${h.errors().length} console errors`);
  await h.shot(path.join(SHOTS, 'app-crashed.png'));
  await h.close();

  h = await launch({ width: 640, height: 420, initScript: () => { if (window.GPUDevice) GPUDevice.prototype.createRenderPipelineAsync = () => Promise.reject(new Error('no pipelines today')); } });
  await h.ready(60000);
  t = await h.page.evaluate(() => ({ kind: window.__citrus.fallback, text: document.body.innerText }));
  check('failure: a start-up failure says the scene could not start (not "no WebGPU")', t.kind === 'error' && /could not start/i.test(t.text) && /no pipelines today/.test(t.text), t.kind);
  await h.close();

  h = await launch({ width: 640, height: 420, webgpu: false, removeGpu: true, initScript: () => { Object.defineProperty(window, 'isSecureContext', { get: () => false, configurable: true }); } });
  await h.ready(30000);
  t = await h.page.evaluate(() => ({ kind: window.__citrus.fallback, text: document.body.innerText }));
  check('failure: an insecure page is told to use https, localhost or a local file', t.kind === 'insecure' && /https/.test(t.text) && /localhost/.test(t.text) && !/hardware acceleration/i.test(t.text), t.kind);
  check('failure: no uncaught errors on the insecure page', h.errors().length === 0, errorTexts(h));
  await h.shot(path.join(SHOTS, 'app-insecure.png'));
  await h.close();
}

// ───────────────────────────── software rendering, reduced motion ─────────────────────────────
async function modes() {
  let h = await launch({ width: 900, height: 600, quality: '' });
  await h.ready();
  let t = await h.page.evaluate(() => { const c = window.__citrus; const n = document.getElementById('cj-notice'); return { soft: c.renderer.isFallbackAdapter, steps: c.renderer.steps, scale: c.app.resolutionScale, notice: n && !n.hidden ? n.textContent : '', w: c.renderer.pixelWidth }; });
  check('software rendering: lowest settings and a quiet notice', t.soft && t.steps === 9 && t.scale === 0.6 && /software rendering/i.test(t.notice) && t.w === 540, JSON.stringify(t));
  await h.page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); });
  await draw(h.page);
  const sb = await sliceInfo(h.page);
  const nb = await h.page.evaluate(() => { const r = document.getElementById('cj-notice').getBoundingClientRect(); return { x0: r.left, x1: r.right, y0: r.top, y1: r.bottom }; });
  check('software rendering: the notice is clear of the slice', nb.x1 < sb.x0 || nb.x0 > sb.x1 || nb.y1 < sb.y0 || nb.y0 > sb.y1,
    `notice ends at y ${Math.round(nb.y1)}, slice starts at y ${Math.round(sb.y0)}`);
  await h.shot(path.join(SHOTS, 'app-software.png'));
  await h.close();

  h = await launch({ width: 640, height: 420, reducedMotion: true });
  await h.ready();
  t = await h.page.evaluate(() => { const m = window.__citrus.sim.metrics(); return { mode: m.mode, minY: m.minY, dev: m.restDeviation }; });
  check('reduced motion: the slice starts at rest, without the drop', t.mode === 'stuck' && t.minY < 1e-6 && t.dev < 0.01, JSON.stringify(t));
  await h.close();
}

// ───────────────────────────── layout sweep ─────────────────────────────
async function layouts() {
  const h = await launch({ width: 1440, height: 900 });
  await h.ready();
  const page = h.page;
  await page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); });
  for (const [w, hgt, minShare] of [[1440, 900, 0.3], [1100, 700, 0.3], [844, 390, 0.25], [390, 844, 0.55], [375, 553, 0.5], [512, 384, 0.3], [480, 320, 0.22]]) {
    await page.setViewportSize({ width: w, height: hgt });
    await page.waitForTimeout(150);
    await draw(page); await draw(page);
    const s = await sliceInfo(page);
    const g = await page.evaluate(() => {
      const box = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? { x: r.left, y: r.top, w: r.width, h: r.height } : null; };
      return { title: box('.cj-title'), hint: box('#cj-hint'), panel: box('#cj-panel'), free: window.__citrus.ui.getFreeRect(), over: document.documentElement.scrollWidth > innerWidth + 1 || document.documentElement.scrollHeight > innerHeight + 1 };
    });
    const hit = (b) => b && !(s.x1 < b.x + 2 || s.x0 > b.x + b.w - 2 || s.y1 < b.y + 2 || s.y0 > b.y + b.h - 2);
    const inView = s.x0 >= -1 && s.y0 >= -1 && s.x1 <= w + 1 && s.y1 <= hgt + 1;
    const panelIn = g.panel && g.panel.x >= -1 && g.panel.y >= -1 && g.panel.x + g.panel.w <= w + 1 && g.panel.y + g.panel.h <= hgt + 1;
    const share = (s.x1 - s.x0) / w;
    // In the wide layout the low tips of the dome are meant to tuck under the heading's longer first line.
    const titleClear = g.free.mode === 'wide' || !hit(g.title);
    check(`layout ${w}x${hgt} (${g.free.mode}): slice in view, clear of the chrome, panel on screen`,
      inView && titleClear && !hit(g.hint) && !hit(g.panel) && panelIn && !g.over && share >= minShare,
      `slice ${Math.round(s.x1 - s.x0)}x${Math.round(s.y1 - s.y0)} px (${(share * 100).toFixed(0)} % of the width)${hit(g.title) ? ', touches title' : ''}${hit(g.hint) ? ', touches hint' : ''}${hit(g.panel) ? ', touches panel' : ''}${panelIn ? '' : ', panel off screen'}${g.over ? ', page overflows' : ''}`);
    if (w === 375 || w === 512 || w === 1440) await h.shot(path.join(SHOTS, `app-layout-${w}x${hgt}.png`));
  }
  check('no console errors during the layout sweep', h.errors().length === 0, errorTexts(h));
  await h.close();
}

// ───────────────────────────── touch ─────────────────────────────
async function touch() {
  const h = await launch({ width: 390, height: 844, dpr: 2, mobile: true });
  await h.ready();
  const page = h.page;
  await page.evaluate(() => { const c = window.__citrus; c.app.state.manual = true; c.sim.reset({ drop: false }); });
  await draw(page);
  const s = await sliceInfo(page);
  const cdp = await h.context.newCDPSession(page);
  const pt = (x, y, id) => ({ x, y, id, radiusX: 8, radiusY: 8, force: 1 });
  const send = (type, pts) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: pts });

  await send('touchStart', [pt(s.edge[0], s.edge[1] - 10, 1)]);
  const g1 = await page.evaluate(() => ({ g: window.__citrus.sim.grabCount, yaw: window.__citrus.camera.yaw }));
  await send('touchMove', [pt(s.edge[0] + 30, s.edge[1] - 10, 1)]);
  const yaw1 = await page.evaluate(() => window.__citrus.camera.yaw);
  await send('touchEnd', []);
  check('touch: a finger 10 px off the slice grabs it instead of turning the camera', g1.g === 1 && Math.abs(yaw1 - 0.42) < 1e-6, JSON.stringify({ ...g1, yaw1 }));

  // two fingers pull the slice apart
  await page.evaluate(() => window.__citrus.sim.reset({ drop: false }));
  const left = [s.flesh[0] - (s.x1 - s.x0) * 0.35, s.flesh[1]], right = [s.flesh[0] + (s.x1 - s.x0) * 0.1, s.flesh[1]];
  await send('touchStart', [pt(left[0], left[1], 1)]);
  await send('touchStart', [pt(left[0], left[1], 1), pt(right[0], right[1], 2)]);
  for (let k = 1; k <= 8; k++) {
    await send('touchMove', [pt(left[0] - 5 * k, left[1] - 4 * k, 1), pt(right[0] + 6 * k, right[1] - 6 * k, 2)]);
    await page.evaluate(() => { for (let i = 0; i < 3; i++) window.__citrus.sim.advance(1 / 60, 1); });
  }
  await page.evaluate(() => window.__citrus.app.stepFrames(20));
  const two = await page.evaluate(() => { const m = window.__citrus.sim.metrics(); return { grabs: window.__citrus.sim.grabCount, stretch: m.maxStretch, finite: m.finite, minVol: m.minVolRatio }; });
  check('touch: two fingers stretch the slice between them', two.grabs === 2 && two.stretch > 1.25 && two.finite && two.minVol > 0, JSON.stringify(two));
  await h.shot(path.join(SHOTS, 'app-two-fingers.png'));

  // a second finger presses Pause while the first still holds the slice
  // (CDP: touchStart and touchMove list every finger that is down, touchEnd the ones being lifted)
  const first = pt(left[0] - 40, left[1] - 32, 1);
  await send('touchEnd', [pt(right[0] + 48, right[1] - 48, 2)]);
  const one = await page.evaluate(() => window.__citrus.sim.grabCount);
  const pause = await page.evaluate(() => { const r = document.getElementById('cj-pause').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; });
  await send('touchStart', [first, pt(pause[0], pause[1], 3)]);
  await send('touchEnd', [pt(pause[0], pause[1], 3)]);
  const p2 = await page.evaluate(() => ({ paused: window.__citrus.app.state.paused, grabs: window.__citrus.sim.grabCount }));
  check('touch: a second finger can press Pause while the first holds the slice', one === 1 && p2.paused === true && p2.grabs === 0, JSON.stringify({ heldBefore: one, ...p2 }));
  await send('touchEnd', [first]);
  check('no console errors in the touch session', h.errors().length === 0, errorTexts(h));
  await h.close();
}

async function main() {
  const only = process.argv.slice(2).filter((a) => !a.startsWith('--') && a !== SHOTS && process.argv[process.argv.indexOf(a) - 1] !== '--shots');
  const sections = { desktop, governor, slowCpu, deviceLoss, failures, modes, layouts, touch };
  for (const [name, fn] of Object.entries(sections)) {
    if (only.length && !only.includes(name)) continue;
    console.log(`\n── ${name} ──`);
    await fn();
  }
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) { for (const r of failed) console.log('  FAILED: ' + r.name + (r.detail ? ' — ' + r.detail : '')); process.exit(1); }
}

main().catch((err) => { console.error(err); process.exit(1); });
