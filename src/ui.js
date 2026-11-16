'use strict';
/*
 * ui.js — the page chrome around the WebGPU canvas (markup: page.html,
 * styles: styles.css, fonts: fonts.css).
 *
 *   const ui = initUI({ onFirmness(v01), onDamping(v01), onNudge(), onReset(),
 *                       onPause(paused), onShowMesh(on), onSlowMo(on), onPreset(id) });
 *
 *   ui.canvas                    the <canvas id="stage">
 *   ui.values                    { firmness, damping, paused, showMesh, slowMo, preset } (live)
 *   ui.setPaused(b)              reflect a pause state decided elsewhere
 *   ui.setPreset(id)             'orange' | 'blood' | 'lemon'; also moves --accent
 *   ui.setGrabbing(b)            the slice is in hand: the hint steps aside
 *   ui.noteInteraction()         first grab happened: the hint steps back for good
 *   ui.showFallback(kind, detail)  'unsupported' | 'lost' | 'error'
 *   ui.getFreeRect()             { x, y, width, height } in CSS px: where to centre the slice
 *                                (plus .mode: 'wide' | 'top' | 'dock' | 'short', the current layout)
 *
 * When the chrome reflows without a window resize (fonts arriving, text zoom) a
 * window "resize" event is dispatched so the frame loop re-reads getFreeRect();
 * pass handlers.onLayout to be called directly instead. handlers.onReload, if
 * given, replaces location.reload() for the fallback's Reload button.
 *
 * Like DOM setters, the programmatic setters do NOT call the handlers; pass
 * `true` as the last argument (setPaused(b, true), setPreset(id, true),
 * setFirmness(v, true) …) to notify as if the user had done it.
 */

const PRESET_IDS = ['orange', 'blood', 'lemon'];
const PRESET_LABELS = { orange: 'Orange', blood: 'Blood Orange', lemon: 'Lemon' };

const FALLBACK_COPY = {
  unsupported: {
    kicker: 'WebGPU unavailable',
    title: 'This scene needs WebGPU, and this browser or device does not provide it.',
    body: 'The slice is simulated and drawn live on your graphics hardware, so without WebGPU there is nothing to stretch. Two things usually fix it:',
    steps: [
      'Open this page in a current version of Chrome, Edge or Safari.',
      'Make sure hardware acceleration is switched on in the browser’s settings.',
    ],
    reload: false,
  },
  lost: {
    kicker: 'Graphics device lost',
    title: 'The browser lost its graphics device, so the scene has stopped.',
    body: 'This can happen when the computer wakes from sleep, a graphics driver restarts, or the tab has been in the background for a long while. Reloading the page brings the slice back.',
    steps: [],
    reload: true,
  },
  error: {
    kicker: 'Something went wrong',
    title: 'The scene could not start.',
    body: 'Setting up the WebGPU scene failed on this device. Reloading often helps. If it keeps happening, try a current version of Chrome, Edge or Safari, and make sure hardware acceleration is switched on.',
    steps: [],
    reload: true,
  },
};

function clamp01(x) {
  x = Number(x);
  if (!(x > 0)) return 0;          // also catches NaN
  return x > 1 ? 1 : x;
}

function initUI(handlers) {
  const h = handlers || {};
  const doc = document;
  const byId = (id) => doc.getElementById(id);
  const call = (name, arg) => { if (typeof h[name] === 'function') h[name](arg); };

  const root = byId('citrus-jelly') || doc.body;
  let canvas = byId('stage');
  if (!canvas) {                    // page.html missing (custom entry): still hand back a canvas
    canvas = doc.createElement('canvas');
    canvas.id = 'stage';
    canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;display:block;touch-action:none';
    root.insertBefore(canvas, root.firstChild);
  }

  const q = (selector) => root.querySelector(selector);
  const el = {
    overlay: q('.cj-ui'),
    mast: q('.cj-mast'),
    title: q('.cj-title'),
    hintText: q('.cj-hint__text'),
    panel: byId('cj-panel'),
    firmness: byId('cj-firmness'),
    firmnessValue: byId('cj-firmness-value'),
    damping: byId('cj-damping'),
    dampingValue: byId('cj-damping-value'),
    nudge: byId('cj-nudge'),
    reset: byId('cj-reset'),
    pause: byId('cj-pause'),
    mesh: byId('cj-mesh'),
    slowMo: byId('cj-slowmo'),
    status: byId('cj-status'),
    fallback: byId('cj-fallback'),
  };
  const radios = {};
  for (const id of PRESET_IDS) radios[id] = byId('cj-preset-' + id);

  const values = { firmness: 0.5, damping: 0.5, paused: false, showMesh: false, slowMo: false, preset: 'orange' };
  const hintCopy = el.hintText ? el.hintText.textContent : '';
  let fallbackKind = null;

  function say(text) { if (el.status) el.status.textContent = text; }

  // ── sliders ────────────────────────────────────────────────────────────
  function bindRange(input, out, key, handlerName) {
    const span = () => {
      const min = parseFloat(input.min), max = parseFloat(input.max);
      const lo = isFinite(min) ? min : 0;
      const hi = isFinite(max) && max > lo ? max : lo + 1;
      return [lo, hi];
    };
    const read = () => { const [lo, hi] = span(); return clamp01((parseFloat(input.value) - lo) / (hi - lo)); };
    const paint = (v) => {
      input.style.setProperty('--p', v.toFixed(4));
      input.setAttribute('aria-valuetext', Math.round(v * 100) + ' percent');
      if (out) out.textContent = v.toFixed(2);
    };
    const sync = (notify) => {
      const v = read();
      paint(v);
      if (v === values[key]) return;
      values[key] = v;
      if (notify) call(handlerName, v);
    };
    const set = (v, notify) => {
      const [lo, hi] = span();
      input.value = String(lo + clamp01(v) * (hi - lo));
      sync(Boolean(notify));
    };
    if (!input) return (v, notify) => { values[key] = clamp01(v); if (notify) call(handlerName, values[key]); };
    input.addEventListener('input', () => sync(true));
    input.addEventListener('change', () => sync(true));

    // Fingers: the whole row is the handle. Touching the track moves the bead there
    // and keeps dragging; touching the bead itself drags it without a jump. Not every
    // browser's native range input does this on touch, so touches are driven here
    // (and kept away from the native handling). Mouse, pen and keyboard stay native.
    let touchId = null, grabDx = 0;
    const thumbSize = () => parseFloat(getComputedStyle(input).getPropertyValue('--cj-thumb')) || 24;
    const drive = (clientX) => {
      const [lo, hi] = span();
      const r = input.getBoundingClientRect(), t = thumbSize();
      const f = clamp01((clientX - grabDx - r.left - t / 2) / Math.max(1, r.width - t));
      const step = parseFloat(input.step) > 0 ? parseFloat(input.step) : 0.01;
      const snapped = lo + Math.round((f * (hi - lo)) / step) * step;
      const next = String(+Math.min(hi, Math.max(lo, snapped)).toFixed(6));
      if (next === input.value) return;
      input.value = next;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const touchOf = (e) => {
      for (let i = 0; i < e.changedTouches.length; i++) if (e.changedTouches[i].identifier === touchId) return e.changedTouches[i];
      return null;
    };
    input.addEventListener('touchstart', (e) => {
      if (input.disabled || touchId !== null || !e.changedTouches.length) return;
      const touch = e.changedTouches[0];
      const r = input.getBoundingClientRect(), t = thumbSize();
      const beadX = r.left + t / 2 + (r.width - t) * read();
      grabDx = Math.abs(touch.clientX - beadX) <= t * 0.75 ? touch.clientX - beadX : 0;
      touchId = touch.identifier;
      if (e.cancelable) e.preventDefault();
      drive(touch.clientX);
    }, { passive: false });
    input.addEventListener('touchmove', (e) => {
      const touch = touchId === null ? null : touchOf(e);
      if (!touch) return;
      if (e.cancelable) e.preventDefault();
      drive(touch.clientX);
    }, { passive: false });
    const endTouch = (e) => {
      if (touchId === null || !touchOf(e)) return;
      touchId = null;
      if (e.cancelable) e.preventDefault();
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };
    input.addEventListener('touchend', endTouch);
    input.addEventListener('touchcancel', endTouch);

    values[key] = read();
    paint(values[key]);
    return set;
  }
  const setFirmness = bindRange(el.firmness, el.firmnessValue, 'firmness', 'onFirmness');
  const setDamping = bindRange(el.damping, el.dampingValue, 'damping', 'onDamping');

  // ── buttons ────────────────────────────────────────────────────────────
  function setPaused(paused, notify) {
    paused = Boolean(paused);
    const changed = paused !== values.paused;
    values.paused = paused;
    if (el.pause) el.pause.textContent = paused ? 'Resume' : 'Pause';
    if (el.hintText && hintCopy) el.hintText.textContent = paused ? 'Paused.' : hintCopy;
    root.toggleAttribute('data-paused', paused);
    if (changed) say(paused ? 'Paused' : 'Running');
    if (notify) call('onPause', paused);
  }
  if (el.nudge) el.nudge.addEventListener('click', () => call('onNudge'));
  if (el.reset) el.reset.addEventListener('click', () => call('onReset'));
  if (el.pause) el.pause.addEventListener('click', () => setPaused(!values.paused, true));

  // A second finger on a button, switch or swatch while the first one holds the slice:
  // browsers only turn a lone finger's tap into a click, so do it for them.
  if (el.panel) {
    el.panel.addEventListener('touchend', (e) => {
      if (!e.touches || e.touches.length === 0 || fallbackKind) return;   // lone finger: the browser clicks
      const from = e.target && e.target.closest ? e.target.closest('button, label, input[type="checkbox"], input[type="radio"]') : null;
      if (!from || from.disabled) return;
      const t = e.changedTouches[0];
      const under = doc.elementFromPoint(t.clientX, t.clientY);
      if (!under || !(from === under || from.contains(under))) return;    // slid off: not a tap
      if (e.cancelable) e.preventDefault();
      from.click();
    });
  }

  // ── switches ───────────────────────────────────────────────────────────
  function bindSwitch(input, key, handlerName) {
    const set = (on, notify) => {
      values[key] = Boolean(on);
      if (input) input.checked = values[key];
      if (notify) call(handlerName, values[key]);
    };
    if (input) {
      values[key] = Boolean(input.checked);
      input.addEventListener('change', () => { values[key] = Boolean(input.checked); call(handlerName, values[key]); });
    }
    return set;
  }
  const setShowMesh = bindSwitch(el.mesh, 'showMesh', 'onShowMesh');
  const setSlowMo = bindSwitch(el.slowMo, 'slowMo', 'onSlowMo');

  // ── colour presets ─────────────────────────────────────────────────────
  function setPreset(id, notify) {
    if (PRESET_IDS.indexOf(id) < 0) return false;
    values.preset = id;
    if (radios[id]) radios[id].checked = true;
    root.setAttribute('data-preset', id);
    // The accent follows the preset. The colours themselves live in styles.css (:root).
    const rootStyle = doc.documentElement.style;
    rootStyle.setProperty('--accent', 'var(--' + id + ')');
    rootStyle.setProperty('--accent-ink', 'var(--' + id + '-ink)');
    if (notify) call('onPreset', id);
    return true;
  }
  for (const id of PRESET_IDS) {
    const radio = radios[id];
    if (!radio) continue;
    if (radio.checked) values.preset = id;
    radio.addEventListener('change', () => { if (radio.checked) setPreset(id, true); });
  }
  setPreset(values.preset, false);

  // ── transient states ───────────────────────────────────────────────────
  function setGrabbing(on) { root.toggleAttribute('data-grabbing', Boolean(on)); }
  function noteInteraction() { root.setAttribute('data-touched', ''); }

  // ── fallback ───────────────────────────────────────────────────────────
  function showFallback(kind, detail) {
    const copy = FALLBACK_COPY[kind] || FALLBACK_COPY.error;
    fallbackKind = FALLBACK_COPY[kind] ? kind : 'error';
    const hadFocusInPanel = Boolean(el.panel && doc.activeElement && el.panel.contains(doc.activeElement));

    root.setAttribute('data-fallback', fallbackKind);
    root.removeAttribute('data-grabbing');
    canvas.setAttribute('aria-hidden', 'true');
    if (el.panel) {
      el.panel.hidden = true;
      const controls = el.panel.querySelectorAll('input, button');
      for (let i = 0; i < controls.length; i++) controls[i].disabled = true;
    }

    let box = el.fallback;
    if (!box) {                     // page.html missing: build a bare message
      box = el.fallback = doc.createElement('section');
      box.id = 'cj-fallback';
      box.className = 'cj-fallback';
      box.setAttribute('role', 'alert');
      box.tabIndex = -1;
      box.innerHTML = '<p id="cj-fallback-kicker"></p><h2 id="cj-fallback-title"></h2><p id="cj-fallback-body"></p>' +
        '<ul id="cj-fallback-steps"></ul><button type="button" id="cj-reload" hidden>Reload</button><p id="cj-fallback-detail" hidden></p>';
      box.style.cssText = 'position:fixed;left:24px;right:24px;top:24px;font:15px/1.5 system-ui,sans-serif';
      (el.overlay || root).appendChild(box);
    }
    const part = (name) => box.querySelector('#cj-fallback-' + name);
    part('kicker').textContent = copy.kicker;
    part('title').textContent = copy.title;
    part('body').textContent = copy.body;
    const steps = part('steps');
    steps.textContent = '';
    for (const text of copy.steps) {
      const li = doc.createElement('li');
      const span = doc.createElement('span');
      span.textContent = text;
      li.appendChild(span);
      steps.appendChild(li);
    }
    const reload = box.querySelector('#cj-reload');
    if (reload) {
      reload.hidden = !copy.reload;
      reload.disabled = !copy.reload;
      reload.onclick = () => { if (typeof h.onReload === 'function') h.onReload(); else location.reload(); };
    }
    const detailEl = part('detail');
    const detailText = detail == null ? '' : String(detail && detail.message ? detail.message : detail).trim();
    if (detailEl) {
      detailEl.hidden = !detailText;
      detailEl.textContent = detailText ? 'Technical detail: ' + detailText.slice(0, 400) : '';
    }
    box.hidden = false;
    // Keyboard users were inside the panel that just went away: hand focus on.
    if (hadFocusInPanel) {
      const target = reload && copy.reload ? reload : box;
      try { target.focus({ preventScroll: true }); } catch (e) { /* not focusable */ }
    }
  }

  // ── layout query ───────────────────────────────────────────────────────
  function layoutMode() {
    try {
      const m = getComputedStyle(root).getPropertyValue('--cj-mode').trim();
      if (m) return m;
    } catch (e) { /* fall through */ }
    return '';
  }

  /**
   * The rectangle (CSS px, viewport coordinates) the slice should be centred in:
   * what is left of the stage once the heading and the panel are accounted for.
   */
  function getFreeRect() {
    const stage = canvas.getBoundingClientRect();
    let W = stage.width, H = stage.height, X = stage.left, Y = stage.top;
    if (!(W > 0) || !(H > 0)) { W = window.innerWidth || 0; H = window.innerHeight || 0; X = 0; Y = 0; }
    const mode = layoutMode();
    const full = { x: X, y: Y, width: W, height: H, mode };
    if (!el.overlay || fallbackKind) return full;

    const visible = (node) => {
      if (!node) return null;
      const r = node.getBoundingClientRect();
      return r.width > 0 && r.height > 0 ? r : null;
    };
    const cs = getComputedStyle(el.overlay);
    const pad = {
      l: parseFloat(cs.paddingLeft) || 0, r: parseFloat(cs.paddingRight) || 0,
      t: parseFloat(cs.paddingTop) || 0, b: parseFloat(cs.paddingBottom) || 0,
    };
    const mast = visible(el.mast);
    const title = visible(el.title) || mast;
    const panel = visible(el.panel);

    let left = X, right = X + W, top = Y, bottom = Y + H;
    if (mode === 'dock') {
      // heading above, panel below; the slice may use the full width
      if (mast) top = mast.bottom + 4;
      if (panel) bottom = panel.top - 4;
    } else if (mode === 'wide') {
      // heading | slice | panel, full height. The slice is a dome standing on its flat
      // side: its low tips can tuck a little under the heading's right edge (whose long
      // first line sits higher up), so the rectangle reaches slightly past that edge.
      const tuck = Math.max(16, Math.min(56, W * 0.03));
      if (title) left = title.right - tuck;
      if (panel) right = panel.left;
      top = Y + Math.min(pad.t, 24);
      bottom = Y + H - Math.min(pad.b, 24);
    } else {
      // 'top' and 'short': heading in the top left corner, panel in a column on the right
      left = X + Math.min(pad.l, 24);
      if (panel) right = panel.left - 12;
      if (title) top = title.bottom + (mode === 'short' ? 0 : 6);
      bottom = Y + H - Math.min(pad.b, mode === 'short' ? 6 : 20);
    }
    const rect = { x: left, y: top, width: right - left, height: bottom - top, mode };
    if (!(rect.width >= 80) || !(rect.height >= 80)) return full;
    return rect;
  }

  // The free rectangle also moves when the chrome itself reflows without the window
  // changing size (the embedded fonts arriving, text zoom). Whoever positions the
  // slice listens to window "resize", so say it that way; handlers.onLayout, if
  // given, is called instead.
  if (typeof ResizeObserver === 'function') {
    let primed = false, queued = false;
    const announce = () => {
      queued = false;
      if (typeof h.onLayout === 'function') h.onLayout();
      else window.dispatchEvent(new Event('resize'));
    };
    const watcher = new ResizeObserver(() => {
      if (!primed) { primed = true; return; }             // the initial report is not a change
      if (queued) return;
      queued = true;
      requestAnimationFrame(announce);
    });
    for (const node of [el.mast, el.title, el.panel]) if (node) watcher.observe(node);
  }

  const ui = {
    canvas,
    root,
    values,
    setPaused,
    setPreset,
    setGrabbing,
    noteInteraction,
    showFallback,
    getFreeRect,
    // extras (not in the original contract)
    setFirmness,
    setDamping,
    setShowMesh,
    setSlowMo,
    presets: PRESET_IDS.slice(),
    presetLabels: Object.assign({}, PRESET_LABELS),
    get fallback() { return fallbackKind; },
    get layout() { return layoutMode(); },
  };
  return ui;
}

if (typeof module !== 'undefined' && module.exports) module.exports = { initUI, PRESET_IDS, PRESET_LABELS };
