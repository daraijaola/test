#!/usr/bin/env node
'use strict';
/*
 * build.cjs — bundles src/ into ONE self-contained HTML file (no external
 * requests at runtime). Plain concatenation with a tiny CommonJS shim, so the
 * same source files also load unchanged in Node for the physics tests.
 *
 *   node tools/build.cjs                  -> index.html
 *   node tools/build.cjs --out x.html     -> custom output path
 *   node tools/build.cjs --ui-stub        -> ui-stub.html: page + styles + ui.js
 *                                            driven by tools/ui-stub.js
 *   node tools/build.cjs --entry tools/x.js [--page p.html] [--styles s.css]
 *                                         -> x.html: dev preview with a custom
 *                                            entry; missing src modules are
 *                                            skipped, default page is a bare
 *                                            full-viewport <canvas id="stage">
 *   node tools/build.cjs --fragment x.html-> also write a body-fragment variant
 *                                            (no doctype/html/head/body tags)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 && args[i + 1] ? args[i + 1] : dflt; };

const TITLE = 'Citrus Jelly';
const DESCRIPTION = 'A soft, stretchable gummy orange slice simulated and rendered live with WebGPU.';

// --ui-stub is shorthand for a custom entry that boots only the page chrome.
const uiStub = flag('--ui-stub');
const entryArg = opt('--entry', uiStub ? 'tools/ui-stub.js' : '');
const customEntry = Boolean(entryArg);
const entryFile = customEntry ? path.resolve(ROOT, entryArg) : path.join(SRC, 'main.js');
const pageArg = opt('--page', uiStub ? 'src/page.html' : '');
const stylesArg = opt('--styles', uiStub ? 'src/styles.css' : '');

const read = (p) => fs.readFileSync(p, 'utf8');
const readOptional = (p) => (fs.existsSync(p) ? read(p) : '');

// Library modules, in dependency order. With a custom entry (dev previews),
// modules that do not exist yet are simply left out.
const modules = [];
for (const f of ['mesh.js', 'camera.js', 'sim.js', 'render.js', 'ui.js']) {
  const file = path.join(SRC, f);
  if (fs.existsSync(file)) modules.push([f, file]);
  else if (!customEntry) { console.error(`build: missing src/${f}`); process.exit(1); }
}
if (!fs.existsSync(entryFile)) { console.error(`build: missing entry ${path.relative(ROOT, entryFile)}`); process.exit(1); }
modules.push(['main.js', entryFile]);

let bundle = `(() => {\n'use strict';\nconst __defs = Object.create(null), __cache = Object.create(null);\n` +
  `function __require(name) {\n  name = String(name).replace(/^(\\.\\.?\\/)+(src\\/)?/, '');\n  if (!(name in __cache)) {\n` +
  `    if (!(name in __defs)) throw new Error('Unknown module ' + name);\n` +
  `    const module = { exports: {} };\n    __cache[name] = module.exports;\n` +
  `    __defs[name](module, module.exports, __require);\n    __cache[name] = module.exports;\n  }\n  return __cache[name];\n}\n`;
for (const [name, file] of modules) {
  bundle += `\n// ───────────────────────── ${name} ─────────────────────────\n` +
    `__defs[${JSON.stringify(name)}] = function (module, exports, require) {\n${read(file)}\n};\n`;
}
bundle += `\n__require('main.js');\n})();\n`;
bundle = bundle.replace(/<\/script/gi, '<\\/script');

const MIN_PAGE = '<canvas id="stage"></canvas>';
const MIN_CSS = 'html,body{height:100%;margin:0;background:#F6F0E4}#stage{position:fixed;inset:0;width:100%;height:100%;display:block;touch-action:none}';
let css, page;
if (customEntry) {
  page = pageArg ? read(path.resolve(ROOT, pageArg)).trim() : MIN_PAGE;
  css = stylesArg ? [readOptional(path.join(SRC, 'fonts.css')), read(path.resolve(ROOT, stylesArg))].filter(Boolean).join('\n') : MIN_CSS;
} else {
  page = read(path.join(SRC, 'page.html')).trim();
  css = [readOptional(path.join(SRC, 'fonts.css')), read(path.join(SRC, 'styles.css'))].filter(Boolean).join('\n');
}

const head = `<title>${TITLE}</title>\n<meta name="description" content="${DESCRIPTION}">`;
const body = `${page}\n<script>\n${bundle}</script>`;

const full = `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n` +
  `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n` +
  `${head}\n<style>\n${css}\n</style>\n</head>\n<body>\n${body}\n</body>\n</html>\n`;

const out = path.resolve(ROOT, opt('--out', uiStub ? 'ui-stub.html' : customEntry ? path.basename(entryArg).replace(/\.js$/, '') + '.html' : 'index.html'));
fs.writeFileSync(out, full);
console.log(`build: wrote ${path.relative(ROOT, out)} (${(full.length / 1024).toFixed(1)} KB)`);

const fragPath = opt('--fragment', '');
if (fragPath) {
  const frag = `${head}\n<meta name="claude:viewport-fit-sides" content="cover">\n<style>\n${css}\n</style>\n${body}\n`;
  fs.writeFileSync(path.resolve(fragPath), frag);
  console.log(`build: wrote fragment ${fragPath} (${(frag.length / 1024).toFixed(1)} KB)`);
}
