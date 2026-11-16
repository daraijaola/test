'use strict';
/*
 * filmstrip.cjs — renders a scripted interaction frame by frame into one contact
 * sheet, so motion can be judged from real WebGPU frames even where the browser
 * only has a (slow) software rasteriser.
 *
 *   node tools/build.cjs && node tests/filmstrip.cjs <scenario|all> [options]
 *
 *   --out dir         where the sheets go (default tests/out)
 *   --w 1100 --h 700  viewport; frames are cropped to the stage area (--full keeps the whole page)
 *   --scale 0.5       size of each frame in the sheet
 *   --cols 6          frames per row in the sheet
 *   --every 3         capture every n-th simulated 1/60 s frame
 *   --palette blood   orange | blood | lemon
 *   --firmness 0.5 --damping 0.5
 *   --mesh            draw the simulation mesh overlay
 *   --file x.html     page to load (default index.html), --root dir to serve from
 *   --list            print the scenario names
 *
 * Time is stepped deterministically (app.state.manual), pointer input is real.
 * A scenario is a list of steps:
 *   ['grab', matX, matY]            press on the camera-facing face (material coords)
 *   ['drag', dxUnits, dyUnits, n]   move the pointer by that many world units over n frames (+y is up)
 *   ['hold', n]  ['release']  ['run', n]  ['nudge']  ['reset']
 */
const fs = require('fs');
const path = require('path');
const { launch } = require('./harness.cjs');

const SCENARIOS = {
  'top-pull': [['grab', 0, 0.86], ['drag', 0.1, 0.8, 18], ['hold', 12], ['release'], ['run', 96]],
  'top-pop': [['grab', 0, 0.9], ['drag', 0.2, 1.7, 40], ['hold', 20], ['release'], ['run', 130]],
  'side-pull': [['grab', 0.62, 0.42], ['drag', 1.0, 0.25, 22], ['hold', 10], ['release'], ['run', 96]],
  'tip-pull': [['grab', -0.9, 0.14], ['drag', -0.8, 0.3, 20], ['hold', 10], ['release'], ['run', 96]],
  'flesh-poke': [['grab', -0.25, 0.4], ['drag', -0.2, -0.3, 12], ['hold', 8], ['release'], ['run', 80]],
  'squash': [['grab', 0, 0.95], ['drag', 0, -0.5, 14], ['hold', 10], ['release'], ['run', 84]],
  'shake': [['grab', 0.3, 0.7], ['drag', 0.5, 0.2, 6], ['drag', -1.0, 0, 8], ['drag', 1.0, 0, 8], ['drag', -1.0, 0.2, 8], ['release'], ['run', 90]],
  'nudge': [['run', 4], ['nudge'], ['run', 140]],
  'drop': [['reset'], ['run', 120]],
};

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : dflt; };
const flag = (name) => args.includes(name);

async function film(name, steps, o) {
  const h = await launch({ width: o.w, height: o.h, file: o.file, root: o.root });
  await h.ready();
  const page = h.page;
  await page.evaluate((cfg) => {
    const c = window.__citrus;
    c.app.state.manual = true;
    c.sim.setFirmness(cfg.firmness);
    c.sim.setDamping(cfg.damping);
    c.sim.reset({ drop: false });
    c.renderer.setPalette(cfg.palette, true);
    if (cfg.mesh) { c.renderer.setShowMesh(true); c.app.state.showMesh = true; }
    const root = document.getElementById('citrus-jelly');
    if (root && cfg.bare) for (const el of root.querySelectorAll('.cj-ui')) el.style.visibility = 'hidden';
  }, o);
  await page.evaluate(() => window.__citrus.app.renderOnce());
  // frame the shots on the area the slice lives in, with room to stretch
  const clip = o.full ? null : await page.evaluate(() => {
    const f = window.__citrus.ui.getFreeRect(), W = innerWidth, H = innerHeight;
    const x0 = Math.max(0, Math.floor(f.x - f.width * 0.18)), x1 = Math.min(W, Math.ceil(f.x + f.width * 1.18));
    const y0 = Math.max(0, Math.floor(f.y - f.height * 0.45)), y1 = Math.min(H, Math.ceil(f.y + f.height * 1.12));
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  });
  const cell = clip || { width: o.w, height: o.h };

  const toScreen = (x, y) => page.evaluate(([mx, my]) => {
    const { mesh, sim, camera, ui } = window.__citrus;
    const front = mesh.thickness * 0.5;
    let best = -1, bd = Infinity;
    for (let i = 0; i < mesh.numParticles; i++) {
      if (!mesh.onSurface[i] || Math.abs(mesh.mat[i * 3 + 2] - front) > 1e-4) continue;
      const d = Math.hypot(mesh.mat[i * 3] - mx, mesh.mat[i * 3 + 1] - my);
      if (d < bd) { bd = d; best = i; }
    }
    const p = sim.pos, r = ui.canvas.getBoundingClientRect();
    const px = (wx, wy, wz) => { const n = camera.project(wx, wy, wz); return [r.left + (n[0] * 0.5 + 0.5) * r.width, r.top + (1 - (n[1] * 0.5 + 0.5)) * r.height]; };
    const a = px(p[best * 3], p[best * 3 + 1], p[best * 3 + 2]);
    // pixels per world unit along the screen axes, measured at the slice centre
    const c0 = px(0, 0.5, 0), cx = px(camera.right[0], 0.5 + camera.right[1], camera.right[2]), cy = px(camera.up[0], 0.5 + camera.up[1], camera.up[2]);
    return { x: a[0], y: a[1], ppuX: Math.hypot(cx[0] - c0[0], cx[1] - c0[1]), ppuY: Math.hypot(cy[0] - c0[0], cy[1] - c0[1]) };
  }, [x, y]);

  const frames = [];
  const log = [];
  let simFrame = 0, sinceShot = 0, cursor = null, ppu = null;
  const shoot = async (label) => {
    await page.evaluate(() => window.__citrus.app.renderOnce());
    const buf = await page.screenshot(clip ? { type: 'png', clip } : { type: 'png' });
    const m = await page.evaluate(() => { const x = window.__citrus.sim.metrics(); return { s: x.maxStretch, d: x.restDeviation, k: x.kinetic, y: x.minY, mode: x.mode, v: x.minVolRatio }; });
    frames.push({ buf, label: `${(simFrame / 60).toFixed(2)}s ${label}` });
    log.push({ t: +(simFrame / 60).toFixed(3), label, ...m });
  };
  const advance = async (n, label, perFrame) => {
    for (let i = 0; i < n; i++) {
      if (perFrame) await perFrame(i);
      await page.evaluate(() => window.__citrus.sim.advance(1 / 60, 1));
      simFrame++; sinceShot++;
      if (sinceShot >= o.every) { sinceShot = 0; await shoot(label); }
    }
  };

  await shoot('rest');
  for (const step of steps) {
    const [kind, a, b, c] = step;
    if (kind === 'grab') {
      const s = await toScreen(a, b);
      cursor = { x: s.x, y: s.y }; ppu = s;
      await page.mouse.move(cursor.x, cursor.y);
      await page.mouse.down();
    } else if (kind === 'drag') {
      const from = { ...cursor }, to = { x: cursor.x + a * ppu.ppuX, y: cursor.y - b * ppu.ppuY };
      await advance(c, 'drag', async (i) => {
        const k = (i + 1) / c;
        cursor = { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k };
        await page.mouse.move(cursor.x, cursor.y);
      });
    } else if (kind === 'hold') {
      await advance(a, 'hold');
    } else if (kind === 'release') {
      await page.mouse.up();
    } else if (kind === 'run') {
      await advance(a, 'free');
    } else if (kind === 'nudge') {
      await page.evaluate(() => window.__citrus.sim.nudge(1));
    } else if (kind === 'reset') {
      await page.evaluate(() => window.__citrus.sim.reset());
    }
  }
  const errors = h.errors().map((e) => e.text);

  // compose the contact sheet in the same browser
  const sheet = await h.context.newPage();
  const cols = o.cols, cellW = Math.round(cell.width * o.scale), cellH = Math.round(cell.height * o.scale);
  const rows = Math.ceil(frames.length / cols);
  await sheet.setViewportSize({ width: cols * cellW, height: rows * (cellH + 16) });
  const html = `<body style="margin:0;background:#222;font:11px/16px monospace;color:#ddd">` +
    `<div style="display:grid;grid-template-columns:repeat(${cols},${cellW}px)">` +
    frames.map((f) => `<div><img width="${cellW}" height="${cellH}" style="display:block" src="data:image/png;base64,${f.buf.toString('base64')}"><div style="height:16px;padding-left:4px">${f.label}</div></div>`).join('') +
    `</div></body>`;
  await sheet.setContent(html);
  await sheet.waitForTimeout(200);
  const file = path.join(o.out, `film-${name}${o.suffix}.png`);
  await sheet.screenshot({ path: file });
  fs.writeFileSync(path.join(o.out, `film-${name}${o.suffix}.json`), JSON.stringify({ name, options: { ...o, out: undefined }, log, errors }, null, 1));
  await h.close();
  console.log(`${name}: ${frames.length} frames -> ${file}${errors.length ? '  (console errors: ' + errors.length + ')' : ''}`);
  return file;
}

async function main() {
  if (flag('--list') || !args.length) { console.log(Object.keys(SCENARIOS).join('\n')); return; }
  const which = args[0] === 'all' ? Object.keys(SCENARIOS) : args[0].split(',');
  const o = {
    out: path.resolve(opt('--out', path.join(__dirname, 'out'))),
    w: +opt('--w', 1100), h: +opt('--h', 700), cols: +opt('--cols', 6), every: +opt('--every', 3), scale: +opt('--scale', 0.5), full: flag('--full'),
    palette: opt('--palette', 'orange'), firmness: +opt('--firmness', 0.5), damping: +opt('--damping', 0.5),
    mesh: flag('--mesh'), bare: !flag('--chrome'), file: opt('--file', 'index.html'), root: opt('--root', undefined), suffix: opt('--suffix', ''),
  };
  fs.mkdirSync(o.out, { recursive: true });
  for (const name of which) {
    if (!SCENARIOS[name]) { console.error(`unknown scenario ${name}`); process.exitCode = 1; continue; }
    await film(name, SCENARIOS[name], o);
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
