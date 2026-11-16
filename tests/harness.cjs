'use strict';
/*
 * harness.cjs — launches headless Chromium with software WebGPU (SwiftShader)
 * and serves the repo over http://127.0.0.1 so pages get a secure context.
 *
 * The flag set below is the one that both creates a WebGPU device AND presents
 * the canvas in this headless environment (other combinations lose the device
 * on the first present). SwiftShader is a CPU rasteriser: expect roughly one
 * frame every 0.1–2 s, so keep test viewports small and never infer real-world
 * frame rate from it.
 *
 *   const { launch } = require('./harness.cjs');
 *   const h = await launch({ width: 960, height: 640 });
 *   await h.ready();                 // waits for window.__citrus.ready
 *   await h.drag([480, 300], [480, 120], { steps: 10, release: false });
 *   await h.shot('out.png');
 *   console.log(h.errors());
 *   await h.close();
 */
const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const GPU_ARGS = [
  '--enable-unsafe-webgpu',
  '--use-gl=angle',
  '--use-angle=swiftshader',
  '--enable-features=Vulkan',
  '--use-vulkan=swiftshader',
  '--ignore-gpu-blocklist',
];
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.cjs': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json', '.woff2': 'font/woff2' };

function serve(root) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
      const file = path.resolve(root, rel);
      if (!file.startsWith(path.resolve(root)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; res.end('not found'); return; }
      res.setHeader('content-type', MIME[path.extname(file)] || 'application/octet-stream');
      res.setHeader('cache-control', 'no-store');
      res.end(fs.readFileSync(file));
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

async function launch(opts = {}) {
  const {
    width = 960, height = 640, dpr = 1,
    webgpu = true,          // false: no GPU flags, requestAdapter() resolves null
    removeGpu = false,      // true: navigator.gpu is undefined (older browsers)
    mobile = false,         // touch-capable mobile emulation
    file = 'index.html', query = '', root = ROOT,
    reducedMotion = false,
    // The page lowers its picture quality on a software rasteriser, which is what the tests
    // run on. 'full' pins it at full quality (what a real GPU starts with); '' leaves the
    // page to decide; 'auto' and 'low' are the page's other ?quality= settings.
    quality = 'full',
  } = opts;
  const search = [query, quality ? 'quality=' + quality : ''].filter(Boolean).join('&');
  const server = await serve(root);
  const browser = await chromium.launch({ headless: true, args: webgpu ? GPU_ARGS : [] });
  const context = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: dpr, hasTouch: mobile, isMobile: mobile,
    reducedMotion: reducedMotion ? 'reduce' : 'no-preference',
  });
  const page = await context.newPage();
  if (removeGpu) await page.addInitScript(() => { Object.defineProperty(Navigator.prototype, 'gpu', { get() { return undefined; }, configurable: true }); });
  const logs = [];
  page.on('console', (m) => logs.push({ type: m.type(), text: m.text() }));
  page.on('pageerror', (e) => logs.push({ type: 'pageerror', text: String(e && e.stack || e) }));
  const url = `http://127.0.0.1:${server.address().port}/${file}${search ? '?' + search : ''}`;
  await page.goto(url, { waitUntil: 'load' });

  const h = {
    browser, context, page, logs, url,
    /** Wait until the app reports it has rendered its first frame. */
    async ready(timeout = 90000) {
      await page.waitForFunction(() => window.__citrus && window.__citrus.ready === true, null, { timeout });
      return h;
    },
    errors() { return logs.filter((l) => l.type === 'error' || l.type === 'pageerror'); },
    warnings() { return logs.filter((l) => l.type === 'warning'); },
    async shot(file, o = {}) { return page.screenshot({ path: file, ...o }); },
    async wait(ms) { await page.waitForTimeout(ms); },
    /** Mouse drag in CSS pixels. release:false leaves the button down. */
    async drag(from, to, { steps = 12, stepDelay = 30, holdMs = 0, release = true } = {}) {
      await page.mouse.move(from[0], from[1]);
      await page.mouse.down();
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        await page.mouse.move(from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t);
        if (stepDelay) await page.waitForTimeout(stepDelay);
      }
      if (holdMs) await page.waitForTimeout(holdMs);
      if (release) await page.mouse.up();
    },
    async release() { await page.mouse.up(); },
    /** Single-finger touch drag through CDP (needs launch({ mobile: true })). */
    async touchDrag(from, to, { steps = 12, stepDelay = 30, holdMs = 0, release = true } = {}) {
      const cdp = await context.newCDPSession(page);
      const pt = (p) => [{ x: p[0], y: p[1], id: 1, radiusX: 8, radiusY: 8, force: 1 }];
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pt(from) });
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pt([from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t]) });
        if (stepDelay) await page.waitForTimeout(stepDelay);
      }
      if (holdMs) await page.waitForTimeout(holdMs);
      if (release) await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      return cdp;
    },
    async close() { await browser.close(); await new Promise((r) => server.close(r)); },
  };
  return h;
}

module.exports = { launch, GPU_ARGS, ROOT };
