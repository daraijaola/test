'use strict';
/*
 * ui-stub.js — entry point for `node tools/build.cjs --ui-stub`.
 * Boots only the page chrome (ui.js) with logging handlers, so the layout can
 * be developed and screenshotted before the simulation and renderer exist.
 * Add ?fallback to the URL to preview the "WebGPU unavailable" state.
 */
const { initUI } = require('./ui.js');

const ui = initUI({
  onFirmness: (v) => console.log('firmness', v),
  onDamping: (v) => console.log('damping', v),
  onNudge: () => console.log('nudge'),
  onReset: () => console.log('reset'),
  onPause: (paused) => console.log('pause', paused),
  onShowMesh: (on) => console.log('showMesh', on),
  onSlowMo: (on) => console.log('slowMo', on),
  onPreset: (name) => console.log('preset', name),
});

if (/[?&]fallback/.test(location.search)) {
  ui.showFallback('unsupported');
}
window.__citrus = { ui, ready: true };
