#!/usr/bin/env node
'use strict';
/*
 * sim.test.cjs — physics tests for src/sim.js. Plain Node, no dependencies:
 *
 *   node tests/sim.test.cjs            run everything
 *   node tests/sim.test.cjs release    run only the sections whose name contains "release"
 *
 * Every criterion prints the measured numbers next to PASS / FAIL; the exit
 * code is non-zero if anything failed.
 */
const path = require('path');
const { buildSliceMesh } = require(path.join(__dirname, '..', 'src', 'mesh.js'));
const { Camera } = require(path.join(__dirname, '..', 'src', 'camera.js'));
const { JellySim, SIM_MESH_OPTIONS, DEFAULT_PARAMS } = require(path.join(__dirname, '..', 'src', 'sim.js'));

// --------------------------------------------------------------------------
// harness
// --------------------------------------------------------------------------
const only = process.argv.slice(2).map((s) => s.toLowerCase());
let failures = 0, checks = 0, section = '';
const rows = [];
function begin(name) {
  if (only.length && !only.some((o) => name.toLowerCase().includes(o))) return false;
  section = name;
  console.log('\n== ' + name + ' ' + '='.repeat(Math.max(0, 74 - name.length)));
  return true;
}
function check(name, pass, detail) {
  checks++;
  if (!pass) failures++;
  rows.push([section, name, pass]);
  console.log((pass ? '  PASS  ' : '  FAIL  ') + name.padEnd(46) + ' ' + (detail || ''));
}
function info(text) { console.log('        ' + text); }
const f2 = (v) => (+v).toFixed(2), f3 = (v) => (+v).toFixed(3), f4 = (v) => (+v).toFixed(4), e1 = (v) => (+v).toExponential(1);

const mesh = buildSliceMesh(SIM_MESH_OPTIONS);
const T0 = Date.now();
function makeSim(opts) { return new JellySim(mesh, opts || {}); }
const DT = DEFAULT_PARAMS.substepDt;
const steps = (seconds) => Math.round(seconds / DT);

// a camera like the one main.js uses, for picking
const camera = new Camera();
camera.fit(1.5, 1.7, 1.15);
/** Pick the surface point that the camera sees at world point `at`. */
function pickAt(sim, at) {
  const p = camera.project(at[0], at[1], at[2]);
  const ray = camera.rayFromNdc(p[0], p[1]);
  return sim.raycast(ray.origin, ray.dir);
}
/** Current / home position of a picked surface point. */
function surfacePoint(sim, hit, arr) {
  const t = sim.surfTris, a = t[hit.tri * 3], b = t[hit.tri * 3 + 1], c = t[hit.tri * 3 + 2], w = hit.bary;
  return [0, 1, 2].map((k) => w[0] * arr[a * 3 + k] + w[1] * arr[b * 3 + k] + w[2] * arr[c * 3 + k]);
}
/** Grab `hit`, move the target by `delta` over tPull seconds, hold until tHold. Steps the sim. */
function pull(sim, id, hit, delta, tPull, tHold, each) {
  const p0 = hit.point.slice();
  sim.startGrab(id, hit, p0);
  const n = steps(tHold);
  for (let s = 0; s < n; s += 2) {
    const u = Math.min(1, (s * DT) / tPull);
    sim.moveGrab(id, [p0[0] + delta[0] * u, p0[1] + delta[1] * u, p0[2] + delta[2] * u]);
    sim.stepSubsteps(2);
    if (each) each(s * DT);
  }
}
function restDistances(sim, home) {
  const d = new Float64Array(sim.n);
  for (let i = 0; i < sim.n; i++) d[i] = Math.hypot(sim.rest[i * 3] - home[0], sim.rest[i * 3 + 1] - home[1], sim.rest[i * 3 + 2] - home[2]);
  return d;
}
function displacements(sim) {
  const d = new Float64Array(sim.n);
  for (let i = 0; i < sim.n; i++) d[i] = Math.hypot(sim.x[i * 3] - sim.rest[i * 3], sim.x[i * 3 + 1] - sim.rest[i * 3 + 1], sim.x[i * 3 + 2] - sim.rest[i * 3 + 2]);
  return d;
}
/** metrics() returns one shared object: copy it when it has to outlive the next call. */
function snap(sim) { const m = sim.metrics(); return Object.assign({}, m, { com: m.com.slice() }); }
/** Mean distance between the front-face and back-face copies of the 2D mesh vertices selected by test(x, y), relative to rest. */
function thicknessRatio(sim, test) {
  const N2 = mesh.particlesPerLayer, top = mesh.layers * N2;
  let now = 0, rest = 0;
  for (let v = 0; v < N2; v++) {
    if (!test(sim.rest[v * 3], sim.rest[v * 3 + 1])) continue;
    const a = v * 3, b = (v + top) * 3;
    now += Math.hypot(sim.x[a] - sim.x[b], sim.x[a + 1] - sim.x[b + 1], sim.x[a + 2] - sim.x[b + 2]);
    rest += Math.hypot(sim.rest[a] - sim.rest[b], sim.rest[a + 1] - sim.rest[b + 1], sim.rest[a + 2] - sim.rest[b + 2]);
  }
  return now / rest;
}
function minParticleY(sim) { let m = Infinity; for (let i = 1; i < sim.n * 3; i += 3) if (sim.x[i] < m) m = sim.x[i]; return m; }

// --------------------------------------------------------------------------
// 0. contract
// --------------------------------------------------------------------------
if (begin('contract')) {
  const sim = makeSim();
  const pos = sim.pos, vel = sim.vel;
  check('pos / vel are Float32Array(3n)', pos instanceof Float32Array && vel instanceof Float32Array && pos.length === mesh.numParticles * 3 && vel.length === pos.length, `n = ${mesh.numParticles}`);
  check('fixed substep', sim.substepDt === DT && DT > 0 && DT <= 1 / 300, `substepDt = 1/${Math.round(1 / sim.substepDt)} s`);
  let same = true;
  for (let i = 0; i < pos.length; i++) if (pos[i] !== mesh.rest[i]) same = false;
  check('constructed exactly in the home pose', same);
  const k60 = sim.advance(1 / 60), k0 = sim.advance(0);
  check('advance() returns whole substeps', k60 === Math.round(1 / 60 / DT) && k0 === 0, `advance(1/60) -> ${k60}, advance(0) -> ${k0}`);
  sim.reset(); sim.nudge(1); sim.advance(0.1); sim.setFirmness(0.3); sim.setDamping(0.8);
  check('pos / vel stay the same objects', sim.pos === pos && sim.vel === vel);
  check('raycast misses return null', sim.raycast([0, 5, 9], [0, 1, 0]) === null && sim.raycast([9, 9, 9], [1, 0, 0]) === null);
  sim.reset({ drop: false });
  const hit = sim.raycast([0.2, 0.5, 5], [0, 0, -1]);
  check('raycast hits the front face', !!hit && Math.abs(hit.point[2] - 0.23) < 0.03 && Math.abs(hit.t - (5 - hit.point[2])) < 1e-6 && Math.abs(hit.bary[0] + hit.bary[1] + hit.bary[2] - 1) < 1e-9,
    hit ? `t ${f3(hit.t)} point (${hit.point.map(f3).join(', ')}) tri ${hit.tri}` : 'no hit');
  const tens = sim.computeTension();
  let tmax = 0; for (const v of tens) tmax = Math.max(tmax, v);
  check('tension is 0 at rest', tens.length === mesh.numParticles && tmax < 0.02, `max ${f3(tmax)}`);
  const m = sim.metrics();
  const keys = ['finite', 'kinetic', 'maxStretch', 'minStretch', 'minVolRatio', 'com', 'minY', 'maxY', 'maxSpeed', 'restDeviation'];
  check('metrics() has the contracted fields', keys.every((k) => k in m) && m.com.length === 3, keys.filter((k) => !(k in m)).join(',') || 'all present');
  sim.startGrab(7, hit); sim.startGrab(8, sim.raycast([-0.4, 0.3, 5], [0, 0, -1]));
  const g2 = sim.grabCount; sim.endGrab(7); sim.endGrab(99); const g1 = sim.grabCount; sim.endGrab(8);
  check('grabCount follows start / end', g2 === 2 && g1 === 1 && sim.grabCount === 0, `${g2} -> ${g1} -> ${sim.grabCount}`);
}

// --------------------------------------------------------------------------
// 1. rest stability
// --------------------------------------------------------------------------
if (begin('rest stability')) {
  const sim = makeSim();
  sim.reset({ drop: false });
  const c0 = sim.metrics().com.slice();
  let worstDev = 0, worstKin = 0, finite = true, minY = Infinity;
  for (let s = 0; s < steps(5); s += 30) {
    sim.stepSubsteps(30);
    const m = sim.metrics();
    worstDev = Math.max(worstDev, m.restDeviation); worstKin = Math.max(worstKin, m.kinetic);
    finite = finite && m.finite; minY = Math.min(minY, m.minY);
  }
  const m = sim.metrics();
  const drift = Math.hypot(m.com[0] - c0[0], m.com[1] - c0[1], m.com[2] - c0[2]);
  check('5 s untouched: stays in the home pose', worstDev < 0.003, `max restDeviation ${e1(worstDev)} (radius = 1), at the end ${e1(m.restDeviation)}`);
  check('5 s untouched: no motion', worstKin < 1e-5 && m.maxSpeed < 0.01, `max kinetic ${e1(worstKin)}, final max speed ${e1(m.maxSpeed)} u/s`);
  check('5 s untouched: no drift', drift < 5e-4 && finite && minY >= 0, `centre of mass moved ${e1(drift)}, minY ${minY}`);
  // other firmness settings: the stress-free shape is re-estimated, the rest pose stays
  for (const f of [0, 1]) {
    sim.setFirmness(f); sim.reset({ drop: false });
    let w = 0, late = 0;
    for (let s = 0; s < steps(5); s += 30) { sim.stepSubsteps(30); const d = sim.metrics().restDeviation; w = Math.max(w, d); if (s > steps(4)) late = Math.max(late, d); }
    check(`firmness ${f}: rest pose kept`, w < 0.02, `max restDeviation over 5 s ${e1(w)}, in the last second ${e1(late)} (still converging)`);
  }
}

// --------------------------------------------------------------------------
// 2. grab locations: deformation starts at the grab point and decays with distance
// --------------------------------------------------------------------------
const SPOTS = [
  { name: 'top of the rind', at: [0.0, 0.99, 0.05], delta: [0.05, 0.38, 0.05] },
  { name: 'side tip', at: [0.95, 0.12, 0.12], delta: [0.36, 0.14, 0.0] },
  { name: 'centre of the face', at: [0.05, 0.45, 0.23], delta: [0.06, 0.1, 0.36] },
  { name: 'near the base', at: [-0.3, 0.12, 0.23], delta: [-0.12, 0.2, 0.3] },
  { name: 'in the pith', at: [-0.6, 0.6, 0.23], delta: [-0.26, 0.26, 0.12] },
];
if (begin('grab locations')) {
  const sim = makeSim();
  for (const spot of SPOTS) {
    sim.reset({ drop: false });
    const hit = pickAt(sim, spot.at);
    if (!hit) { check(spot.name + ': picked', false, 'ray missed'); continue; }
    const home = surfacePoint(sim, hit, sim.rest);
    const miss = Math.hypot(home[0] - spot.at[0], home[1] - spot.at[1], home[2] - spot.at[2]);
    const rho = Math.hypot(home[0], home[1]);
    const zone = rho >= mesh.rindR ? 'rind' : rho >= mesh.pithR ? 'pith' : 'flesh';
    pull(sim, 1, hit, spot.delta, 0.6, 1.2);
    const amount = Math.hypot(...spot.delta);
    const d = displacements(sim), r = restDistances(sim, home);
    const order = Array.from(d.keys()).sort((a, b) => d[b] - d[a]);
    const topN = Math.max(8, Math.round(sim.n * 0.04));
    let topDist = 0; for (let k = 0; k < topN; k++) topDist += r[order[k]] / topN;
    const ring = (lo, hi) => { let s = 0, c = 0; for (let i = 0; i < sim.n; i++) if (r[i] >= lo && r[i] < hi) { s += d[i]; c++; } return c ? s / c : NaN; };
    const near = ring(0, 0.25), mid = ring(0.45, 0.8), far = ring(1.1, 9);
    const grabbed = surfacePoint(sim, hit, sim.x);
    const follow = Math.hypot(grabbed[0] - home[0] - spot.delta[0], grabbed[1] - home[1] - spot.delta[1], grabbed[2] - home[2] - spot.delta[2]);
    const m = sim.metrics();
    info(`${spot.name}: hit (${home.map(f2).join(', ')}) [${zone}], ${f3(miss)} from the aimed point; pulled ${f2(amount)}`);
    check(spot.name + ': grabbed point follows', follow < 0.05 && m.finite, `${f3(follow)} from the target`);
    check(spot.name + ': most displaced are at the grab', topDist < 0.42, `the ${topN} most displaced particles are on average ${f3(topDist)} from the grab point`);
    check(spot.name + ': decays with distance', near > mid * 1.3 && mid > far && near > 0.5 * amount, `mean displacement near ${f3(near)} > mid ${f3(mid)} > far ${f3(far)}`);
    check(spot.name + ': far side stays home', far < 0.25 * amount && m.mode === 'stuck', `far ${f3(far)} = ${Math.round(100 * far / amount)} % of the pull, base ${m.mode}`);
    sim.endGrab(1);
  }
}

// --------------------------------------------------------------------------
// 3. flesh stretches, the rind resists
// --------------------------------------------------------------------------
if (begin('flesh vs rind')) {
  const sim = makeSim();
  const localStrain = (spotAt, delta) => {
    sim.reset({ drop: false });
    const hit = pickAt(sim, spotAt);
    const home = surfacePoint(sim, hit, sim.rest);
    pull(sim, 1, hit, delta, 0.6, 1.2);
    const r = restDistances(sim, home);
    // strain of the edges around the grab point
    let worst = 0, sum = 0, cnt = 0;
    for (let e = 0; e < sim.numEdges; e++) {
      const a = sim.edges[e * 2], b = sim.edges[e * 2 + 1];
      if (r[a] > 0.3 || r[b] > 0.3) continue;
      const st = Math.hypot(sim.x[a * 3] - sim.x[b * 3], sim.x[a * 3 + 1] - sim.x[b * 3 + 1], sim.x[a * 3 + 2] - sim.x[b * 3 + 2]) / sim.edgeL0[e] - 1;
      if (st > worst) worst = st;
      if (st > 0) { sum += st; cnt++; }
    }
    const force = sim.grabs[0].force;
    sim.endGrab(1);
    return { worst, mean: sum / Math.max(1, cnt), force, home };
  };
  // the same 0.4 pull, straight out of the surface: flesh on the face, rind on the rim
  const flesh = localStrain([0.05, 0.45, 0.23], [0, 0, 0.4]);
  const rind = localStrain([0.0, 0.99, 0.0], [0, 0.4, 0]);
  info(`flesh grab at (${flesh.home.map(f2).join(', ')}), rind grab at (${rind.home.map(f2).join(', ')}), both pulled 0.40 outwards`);
  check('same pull: more local strain in the flesh', flesh.worst > 1.3 * rind.worst, `largest edge strain within 0.3 of the grab: flesh ${f2(flesh.worst)}, rind ${f2(rind.worst)}  (x${f2(flesh.worst / rind.worst)})`);
  check('same pull: the rind pulls back harder', rind.force > 1.15 * flesh.force, `holding force: rind ${f2(rind.force)}, flesh ${f2(flesh.force)}`);
  // zone-wise, during one pull on the rind: the rind edges stretch less than the flesh they drag along
  sim.reset({ drop: false });
  const hit = pickAt(sim, [0.0, 0.99, 0.0]);
  pull(sim, 1, hit, [0, 0.6, 0], 0.8, 1.4);
  const zmax = [0, 0, 0];
  for (let e = 0; e < sim.numEdges; e++) {
    const a = sim.edges[e * 2], b = sim.edges[e * 2 + 1];
    const st = Math.hypot(sim.x[a * 3] - sim.x[b * 3], sim.x[a * 3 + 1] - sim.x[b * 3 + 1], sim.x[a * 3 + 2] - sim.x[b * 3 + 2]) / sim.edgeL0[e];
    const lim = sim.edgeLimit[e];
    const z = lim <= sim.params.zoneMaxStretch[2] ? 2 : lim <= sim.params.zoneMaxStretch[1] ? 1 : 0;
    if (st > zmax[z]) zmax[z] = st;
  }
  sim.endGrab(1);
  check('rind grabbed and pulled 0.6: flesh stretches most', zmax[0] > zmax[2] + 0.2 && zmax[2] <= sim.params.zoneMaxStretch[2] * 1.05,
    `largest stretch: flesh x${f2(zmax[0])}, pith x${f2(zmax[1])}, rind x${f2(zmax[2])}`);
}

// --------------------------------------------------------------------------
// 4. strong stretching
// --------------------------------------------------------------------------
function bandExtent(sim, test) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (let i = 0; i < sim.n; i++) {
    if (!test(sim.rest[i * 3], sim.rest[i * 3 + 1], sim.rest[i * 3 + 2])) continue;
    x0 = Math.min(x0, sim.x[i * 3]); x1 = Math.max(x1, sim.x[i * 3]);
    y0 = Math.min(y0, sim.x[i * 3 + 1]); y1 = Math.max(y1, sim.x[i * 3 + 1]);
    z0 = Math.min(z0, sim.x[i * 3 + 2]); z1 = Math.max(z1, sim.x[i * 3 + 2]);
  }
  return [x1 - x0, y1 - y0, z1 - z0];
}
if (begin('strong stretching')) {
  const LIMIT_TOL = 1.12;      // hard limits are solved once per substep: allow 12 % while force is ramping
  // (a) one finger: the top pulled 2.2 units away and held
  {
    const sim = makeSim();
    sim.reset({ drop: false });
    const band = (x, y) => y > 0.42 && y < 0.62;
    const rest = bandExtent(sim, band);
    const hit = pickAt(sim, [0.0, 0.99, 0.05]);
    let worstRel = 0, minVol = Infinity, volLo = 1, volHi = 1, finite = true, narrow = [1, 1], peakTop = 0, letGoAt = NaN, maxStr = 0, hangStr = 0, hangRel = 0;
    pull(sim, 1, hit, [0, 2.2, 0], 1.6, 3.2, (t) => {
      const m = sim.metrics();
      worstRel = Math.max(worstRel, m.maxStretchRel); minVol = Math.min(minVol, m.minVolRatio); maxStr = Math.max(maxStr, m.maxStretch);
      volLo = Math.min(volLo, m.volumeRatio); volHi = Math.max(volHi, m.volumeRatio); finite = finite && m.finite;
      if (m.mode === 'stuck') { const b = bandExtent(sim, band); narrow[0] = Math.min(narrow[0], b[0] / rest[0]); narrow[1] = Math.min(narrow[1], thicknessRatio(sim, band)); peakTop = Math.max(peakTop, m.maxY); }
      else if (isNaN(letGoAt)) letGoAt = Math.min(2.2, 2.2 * t / 1.6);
      if (t > 2.2) { hangStr = Math.max(hangStr, m.maxStretch); hangRel = Math.max(hangRel, m.maxStretchRel); }   // the last second: hanging, bobbing
    });
    const m = sim.metrics();
    const held = surfacePoint(sim, hit, sim.x), home = surfacePoint(sim, hit, sim.rest);
    info(`one finger, top pulled up 2.2: the base holds until the pull reaches ${f2(letGoAt)} (top at y = ${f2(peakTop)}), then the slice hangs from the finger`);
    check('1 finger: grabbed point ends 2+ units away', Math.hypot(held[0] - home[0], held[1] - home[1], held[2] - home[2]) > 2.0, `${f2(Math.hypot(held[0] - home[0], held[1] - home[1], held[2] - home[2]))} from home, slice bottom at y = ${f2(m.minY)}, ${m.mode}`);
    check('1 finger: stretch stays within the limits', worstRel < LIMIT_TOL && hangRel < 1.0, `worst edge at ${f2(worstRel)} of its limit during the pull (largest stretch x${f2(maxStr)}), ${f2(hangRel)} while hanging`);
    check('1 finger: no tet inverted, all finite', minVol > 0 && finite, `smallest tet volume ratio ${f2(minVol)}`);
    check('1 finger: volume preserved', volLo > 0.97 && volHi < 1.03, `total volume between ${f4(volLo)} and ${f4(volHi)} of rest`);
    check('1 finger: the middle necks', narrow[0] < 0.9 && narrow[1] < 0.95, `mid-height band: width ${Math.round(narrow[0] * 100)} %, thickness ${Math.round(narrow[1] * 100)} % of rest at the peak`);
    check('1 finger: hangs and stretches under its weight', m.minY > 0.5 && hangStr > 1.04 && hangStr < 2, `largest stretch while hanging x${f2(hangStr)}`);
  }
  // (b) two fingers pulling the slice apart, held: a sustained stretch
  {
    const sim = makeSim();
    sim.reset({ drop: false });
    const band = (x) => Math.abs(x) < 0.22;
    const rest = bandExtent(sim, band);
    const hl = pickAt(sim, [-0.78, 0.4, 0.23]), hr = pickAt(sim, [0.78, 0.4, 0.23]);
    const pl = hl.point.slice(), pr = hr.point.slice();
    sim.startGrab(1, hl); sim.startGrab(2, hr);
    let worstRel = 0, minVol = Infinity, volLo = 1, volHi = 1, finite = true;
    const D = 1.0;
    for (let s = 0; s < steps(3); s += 2) {
      const u = Math.min(1, s * DT / 1.4);
      sim.moveGrab(1, [pl[0] - D * u, pl[1] + 0.5 * u, pl[2]]); sim.moveGrab(2, [pr[0] + D * u, pr[1] + 0.5 * u, pr[2]]);
      sim.stepSubsteps(2);
      const m = sim.metrics();
      worstRel = Math.max(worstRel, m.maxStretchRel); minVol = Math.min(minVol, m.minVolRatio);
      volLo = Math.min(volLo, m.volumeRatio); volHi = Math.max(volHi, m.volumeRatio); finite = finite && m.finite;
    }
    const m = sim.metrics();
    const b = bandExtent(sim, band);
    const a = surfacePoint(sim, hl, sim.x), c = surfacePoint(sim, hr, sim.x);
    const span = Math.hypot(a[0] - c[0], a[1] - c[1], a[2] - c[2]), span0 = Math.hypot(pl[0] - pr[0], pl[1] - pr[1], pl[2] - pr[2]);
    info(`two fingers, targets pulled apart to ${f2(span0 + 2 * D)} (from ${f2(span0)}): the grabbed points end ${f2(span)} apart (x${f2(span / span0)})`);
    check('2 fingers: held stretch within the limits', worstRel < LIMIT_TOL && m.maxStretchRel < 1.1, `worst edge at ${f2(worstRel)} of its limit on the way, ${f2(m.maxStretchRel)} held; largest stretch x${f2(m.maxStretch)}`);
    check('2 fingers: no tet inverted, all finite', minVol > 0 && finite, `smallest tet volume ratio ${f2(minVol)}`);
    check('2 fingers: volume preserved', volLo > 0.97 && volHi < 1.03, `total volume between ${f4(volLo)} and ${f4(volHi)} of rest`);
    const thick = thicknessRatio(sim, band);
    check('2 fingers: the flesh between them narrows', b[1] / rest[1] < 0.8 && b[1] / rest[1] * thick < 0.75 && span / span0 > 1.5, `middle of the slice: height ${Math.round(100 * b[1] / rest[1])} %, thickness ${Math.round(100 * thick)} %, cross-section ${Math.round(100 * b[1] / rest[1] * thick)} % of rest`);
    sim.endGrab(1); sim.endGrab(2);
    sim.stepSubsteps(steps(6));
    const end = sim.metrics();
    check('2 fingers: comes home after release', end.restDeviation < 0.01 && end.mode === 'stuck', `restDeviation ${e1(end.restDeviation)} after 6 s`);
  }
}

// --------------------------------------------------------------------------
// 5. release: gentle return, a wobble that dies out
// --------------------------------------------------------------------------
/** Pull the top of the slice by `delta`, hold, let go; analyse the displacement of the grabbed point. */
function releaseRun(sim, firmness, damping, delta, watch) {
  sim.setFirmness(firmness); sim.setDamping(damping); sim.reset({ drop: false });
  sim.stepSubsteps(steps(0.5));
  const hit = pickAt(sim, [0.0, 0.99, 0.05]);
  const home = surfacePoint(sim, hit, sim.rest);
  pull(sim, 1, hit, delta, 0.8, 1.5);
  const stuck = sim.mode === 0;
  const start = surfacePoint(sim, hit, sim.x);
  const d0 = Math.hypot(start[0] - home[0], start[1] - home[1], start[2] - home[2]);
  const axis = [0, 1, 2].map((k) => (start[k] - home[k]) / d0);
  sim.endGrab(1);
  const N = steps(watch);
  const sig = new Float64Array(N), dist = new Float64Array(N);
  let peak = 0, prev = d0;
  for (let s = 0; s < N; s++) {
    sim.stepSubsteps(1);
    const p = surfacePoint(sim, hit, sim.x);
    sig[s] = (p[0] - home[0]) * axis[0] + (p[1] - home[1]) * axis[1] + (p[2] - home[2]) * axis[2];
    dist[s] = Math.hypot(p[0] - home[0], p[1] - home[1], p[2] - home[2]);
    const sp = Math.abs(sig[s] - prev) / DT; if (sp > peak) peak = sp; prev = sig[s];
  }
  let tBack = NaN;
  for (let s = 0; s < N; s++) if (sig[s] < 0.1 * d0) { tBack = (s + 1) * DT; break; }
  // overshoots: alternating extrema after the first return, as a fraction of the initial displacement
  const over = []; let sign = 1;
  for (let s = 1; s < N - 1; s++) {
    if ((sig[s] - sig[s - 1]) * (sig[s + 1] - sig[s]) < 0 && Math.abs(sig[s]) > 0.02 * d0 && Math.sign(sig[s]) !== sign) { over.push(sig[s] / d0); sign = Math.sign(sig[s]); }
  }
  let t5 = 0;
  for (let s = N - 1; s >= 0; s--) if (dist[s] > 0.05 * d0) { t5 = (s + 1) * DT; break; }
  const m = sim.metrics();
  return { d0, stuck, tBack, peak, over, n5: over.filter((o) => Math.abs(o) > 0.05).length, n10: over.filter((o) => Math.abs(o) > 0.1).length, t5, endDev: m.restDeviation, finite: m.finite };
}
if (begin('release')) {
  const sim = makeSim();
  const zPull = [0.05, 0.12, 0.5];       // out of the plane: the slow, wide wobble
  const sidePull = [0.55, 0.25, 0.0];    // in the plane
  const fmt = (r) => `back in ${f2(r.tBack)} s, peak ${f2(r.peak)} u/s, overshoots ${r.over.slice(0, 6).map((o) => Math.round(o * 100)).join(' ') || 'none'} %, < 5 % after ${f2(r.t5)} s`;
  console.log('        the top of the slice is pulled ~0.5 off (the base stays stuck), held, released. Displacement of the grabbed');
  console.log('        point along the pull, overshoots in % of the initial displacement:');
  console.log('        firmness damping | pulled | back to 10 % | peak speed | overshoots > 5 % | below 5 % after | verdict');
  for (const f of [0, 0.5, 1]) for (const d of [0, 0.5, 1]) {
    const r = releaseRun(sim, f, d, zPull, 9);
    const notInstant = r.tBack >= 0.12 && r.peak <= 6.5;
    let ok = r.stuck && r.finite && notInstant && r.endDev < 0.03;
    let why = '';
    if (d === 0) { ok = ok && r.t5 < 7 && r.n5 >= 3; why = 'must still die out (< 7 s) but wobble freely'; }
    else if (d === 0.5) { ok = ok && r.n5 >= 2 && r.t5 < 3.6 && r.t5 > 0.5; why = 'a clear wobble that settles'; }
    else { ok = ok && r.n10 === 0 && r.n5 <= 1 && r.t5 < 2.2; why = 'almost no overshoot, no creep'; }
    console.log(`        ${f.toFixed(1).padStart(5)}    ${d.toFixed(1).padStart(4)}    |  ${f2(r.d0)}  |    ${f2(r.tBack)} s    |  ${f2(r.peak).padStart(5)} u/s |  ${String(r.n5).padStart(2)} (${r.over.slice(0, 5).map((o) => Math.round(o * 100)).join(' ') || '-'})`.padEnd(92) + ` |   ${f2(r.t5)} s`.padEnd(14) + (ok ? ' | ok' : ' | FAIL') + `  (${why})`);
    check(`firmness ${f} damping ${d}`, ok, fmt(r));
  }
  // the defaults, looked at more closely
  const rz = releaseRun(sim, 0.5, 0.5, zPull, 8);
  check('defaults: not an instant snap', rz.tBack >= 0.18 && rz.peak <= 4.0, `${f2(rz.d0)} away comes back to 10 % in ${f2(rz.tBack)} s, peak speed ${f2(rz.peak)} u/s`);
  check('defaults: 2-3+ visible overshoots', rz.n5 >= 3 && rz.n10 >= 2 && Math.abs(rz.over[0]) > 0.15 && Math.abs(rz.over[0]) < 0.7, `${rz.over.slice(0, 7).map((o) => Math.round(o * 100)).join(' ')} %`);
  check('defaults: below 5 % within 1.5-2.5 s', rz.t5 > 0.8 && rz.t5 < 2.5, `${f2(rz.t5)} s`);
  const rs = releaseRun(sim, 0.5, 0.5, sidePull, 8);
  check('defaults, in-plane pull: gentle and wobbly too', rs.stuck && rs.tBack >= 0.18 && rs.peak <= 4.0 && rs.n5 >= 2 && rs.t5 < 2.5, fmt(rs));
  // a hard pull lifts the slice off; let go from up there
  {
    sim.setFirmness(0.5); sim.setDamping(0.5); sim.reset({ drop: false });
    const hit = pickAt(sim, [0.0, 0.99, 0.05]);
    pull(sim, 1, hit, [0.9, 1.5, 0.2], 1.0, 2.0);
    const lifted = snap(sim);
    sim.endGrab(1);
    let tHome = NaN, peakCom = 0, minY = Infinity, prev = sim.metrics().com.slice(), landed = NaN;
    for (let s = 0; s < steps(8); s += 6) {
      sim.stepSubsteps(6);
      const m = sim.metrics();
      const v = Math.hypot(m.com[0] - prev[0], m.com[1] - prev[1], m.com[2] - prev[2]) / (6 * DT); prev = m.com.slice();
      if (v > peakCom) peakCom = v;
      minY = Math.min(minY, m.minY);
      if (isNaN(landed) && m.minY <= 1e-9) landed = s * DT;
      if (isNaN(tHome) && m.restDeviation < 0.05) tHome = s * DT;
    }
    const m = sim.metrics();
    check('lifted off and released: falls, then comes home', lifted.mode === 'free' && lifted.minY > 0.3 && landed > 0.15 && tHome > 0.6 && tHome < 4 && m.restDeviation < 0.01 && m.mode === 'stuck' && minY >= 0,
      `released ${f2(lifted.minY)} above the ground; lands after ${f2(landed)} s, back home (< 0.05) after ${f2(tHome)} s, fastest ${f2(peakCom)} u/s, final restDeviation ${e1(m.restDeviation)}`);
  }
}

// --------------------------------------------------------------------------
// 6. ground collisions
// --------------------------------------------------------------------------
if (begin('collisions')) {
  const sim = makeSim();
  const drop = (height, label) => {
    sim.setFirmness(0.5); sim.setDamping(0.5);
    sim.reset(height === undefined ? undefined : { height });
    const h0 = sim.metrics().minY;
    let below = 0, landed = NaN, vImpact = 0, minTop = Infinity, widest = 0, finite = true, minVol = Infinity;
    const tops = [];
    const w0 = bandExtent(sim, () => true)[0];
    for (let s = 0; s < steps(5); s++) {
      sim.stepSubsteps(1);
      const y = minParticleY(sim);
      if (y < 0) below++;
      if (isNaN(landed)) { if (y <= 0) landed = (s + 1) * DT; else if (s % 4 === 0) vImpact = sim.metrics().maxSpeed; }
      else if (s % 4 === 0) {
        const m = sim.metrics();
        finite = finite && m.finite; minVol = Math.min(minVol, m.minVolRatio);
        const t = (s + 1) * DT - landed;
        if (t < 0.5) { minTop = Math.min(minTop, m.maxY); widest = Math.max(widest, bandExtent(sim, () => true)[0]); }
        tops.push(m.maxY);
      }
    }
    // wobble: alternating extrema of the height after the impact
    let ext = 0, big = 0;
    for (let k = 1; k < tops.length - 1; k++) if ((tops[k] - tops[k - 1]) * (tops[k + 1] - tops[k]) < 0 && Math.abs(tops[k] - 1) > 0.004) { ext++; big = Math.max(big, tops[k] - 1); }
    const m = sim.metrics();
    return { label, h0, landed, vImpact, squash: 1 - minTop, bulge: widest / w0 - 1, ext, rebound: big, below, finite, minVol, end: snap(sim) };
  };
  const a = drop(undefined, 'reset()'), b = drop(1.0, 'from 1.0'), c = drop(2.0, 'from 2.0');
  for (const r of [a, b, c]) info(`${r.label.padEnd(9)}: falls ${f2(r.h0)}, hits at ${f2(r.vImpact)} u/s after ${f2(r.landed)} s; squashes ${(r.squash * 100).toFixed(1)} % of its height, bulges ${(r.bulge * 100).toFixed(1)} % wider, rebounds to +${(r.rebound * 100).toFixed(1)} %, ${r.ext} height extrema; smallest tet ${f2(r.minVol)}`);
  check('reset() drops from a small height', a.h0 > 0.15 && a.h0 < 0.6 && a.landed > 0.1 && a.landed < 0.5, `${f2(a.h0)} above the ground, lands after ${f2(a.landed)} s`);
  check('normal drop: squashes a few percent', a.squash > 0.03 && a.squash < 0.15, `${(a.squash * 100).toFixed(1)} % of its height`);
  check('hard drops squash more', b.squash > a.squash * 1.2 && c.squash > b.squash && c.squash < 0.4, `${(a.squash * 100).toFixed(1)} % -> ${(b.squash * 100).toFixed(1)} % -> ${(c.squash * 100).toFixed(1)} %`);
  check('wobbles after the impact', a.ext >= 3 && a.rebound > 0.01 && b.ext >= 3, `${a.ext} / ${b.ext} / ${c.ext} extrema of the height, first rebound +${(a.rebound * 100).toFixed(1)} %`);
  check('no particle ever below the ground', a.below + b.below + c.below === 0 && a.end.minY >= 0, `${a.below + b.below + c.below} substeps with y < 0 out of ${3 * steps(5)}`);
  check('settles at home', [a, b, c].every((r) => r.finite && r.end.mode === 'stuck' && r.end.restDeviation < 0.005 && r.end.kinetic < 1e-5 && r.minVol > 0), [a, b, c].map((r) => `${e1(r.end.restDeviation)}`).join(' / ') + ' restDeviation after 5 s');
}

// --------------------------------------------------------------------------
// 7. nudge
// --------------------------------------------------------------------------
if (begin('nudge')) {
  const sim = makeSim();
  sim.reset({ drop: false });
  sim.nudge(1);
  let apex = 0, airborne = 0, below = 0, finite = true, twist = 0, squash = 1, landedAt = NaN;
  for (let s = 0; s < steps(5); s += 2) {
    sim.stepSubsteps(2);
    const y = minParticleY(sim);
    if (y < 0) below++;
    if (y > 0.01) airborne += 2 * DT; else if (airborne > 0.1 && isNaN(landedAt)) landedAt = s * DT;
    apex = Math.max(apex, y);
    if (s % 8 === 0) {
      const m = sim.metrics(); finite = finite && m.finite;
      if (!isNaN(landedAt)) squash = Math.min(squash, m.maxY);
      // twist: angle between the top row and the base row seen from above
      let tx = 0, tz = 0, bx = 0, bz = 0;
      for (let i = 0; i < sim.n; i++) { const rx = sim.rest[i * 3], ry = sim.rest[i * 3 + 1]; if (Math.abs(rx) < 0.3) continue; const sgn = Math.sign(rx); if (ry < 0.05) { bx += sgn * sim.x[i * 3]; bz += sgn * sim.x[i * 3 + 2]; } else if (ry > 0.6) { tx += sgn * sim.x[i * 3]; tz += sgn * sim.x[i * 3 + 2]; } }
      twist = Math.max(twist, Math.abs(Math.atan2(tz, tx) - Math.atan2(bz, bx)));
    }
  }
  const m = sim.metrics();
  check('hop', apex > 0.15 && apex < 1.2 && airborne > 0.25, `clears the ground by ${f2(apex)}, airborne ${f2(airborne)} s`);
  check('twist', twist > 0.05, `top turns up to ${(twist * 180 / Math.PI).toFixed(1)} deg against the base`);
  check('lands, squashes, comes home', squash < 0.99 && below === 0 && finite && m.restDeviation < 0.01 && m.mode === 'stuck', `lowest height after landing ${f3(squash)}, restDeviation after 5 s ${e1(m.restDeviation)}`);
  // repeated nudges, and nudging a held slice
  sim.reset({ drop: false });
  let worstRel = 0, minVol = Infinity, far = 0; finite = true;
  for (let k = 0; k < 12; k++) { sim.nudge(0.6 + (k % 3)); for (let s = 0; s < 9; s++) { sim.stepSubsteps(10); const q = sim.metrics(); finite = finite && q.finite; worstRel = Math.max(worstRel, q.maxStretchRel); minVol = Math.min(minVol, q.minVolRatio); far = Math.max(far, Math.hypot(q.com[0], q.com[2])); } }
  const hit = pickAt(sim, [0.0, 0.5, 0.2]);
  if (hit) { sim.startGrab(1, hit); for (let k = 0; k < 6; k++) { sim.nudge(1.5); sim.stepSubsteps(60); const q = sim.metrics(); finite = finite && q.finite; worstRel = Math.max(worstRel, q.maxStretchRel); minVol = Math.min(minVol, q.minVolRatio); } sim.endGrab(1); }
  sim.stepSubsteps(steps(7));
  const e = sim.metrics();
  check('12 nudges in 1.8 s, 6 more while held: safe', finite && worstRel < 1.15 && minVol > 0 && far < 4 && e.restDeviation < 0.01, `worst stretch ${f2(worstRel)} of the limit, smallest tet ${f2(minVol)}, strayed ${f2(far)} at most, restDeviation after 7 s ${e1(e.restDeviation)}`);
}

// --------------------------------------------------------------------------
// 8. reset
// --------------------------------------------------------------------------
if (begin('reset')) {
  const sim = makeSim();
  let seed = 7; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  // chaos
  for (let k = 0; k < 40; k++) {
    const hit = pickAt(sim, [(rnd() - 0.5) * 1.6, rnd() * 0.9, 0.1]);
    if (hit) sim.startGrab(1 + (k % 2), hit);
    sim.moveGrab(1 + (k % 2), [(rnd() - 0.5) * 6, rnd() * 4, (rnd() - 0.5) * 4]);
    if (k % 5 === 0) sim.nudge(2 * rnd());
    sim.stepSubsteps(40);
  }
  const chaos = snap(sim);
  sim.reset();
  const grabsAfter = sim.grabCount;
  sim.moveGrab(1, [3, 3, 3]); sim.endGrab(1); sim.endGrab(2);            // stale pointer ids must be harmless
  const m0 = snap(sim);
  sim.stepSubsteps(steps(4));
  const m = sim.metrics();
  check('reset() during a 2-finger grab is safe', grabsAfter === 0 && m0.finite && sim.grabCount === 0, `before: restDeviation ${f2(chaos.restDeviation)}, ${chaos.grabs} grabs; after: ${grabsAfter} grabs`);
  check('reset() then 4 s: back at rest', m.restDeviation < 0.005 && m.kinetic < 1e-5 && m.mode === 'stuck', `restDeviation ${e1(m.restDeviation)}, kinetic ${e1(m.kinetic)}`);
  // exact rest
  sim.nudge(2); sim.stepSubsteps(100);
  sim.reset({ drop: false });
  let exact = true; for (let i = 0; i < sim.pos.length; i++) if (sim.pos[i] !== mesh.rest[i] || sim.vel[i] !== 0) exact = false;
  sim.stepSubsteps(steps(2));
  const m2 = sim.metrics();
  check('reset({ drop: false }) is exactly the rest state', exact && m2.restDeviation < 0.003 && m2.kinetic < 1e-7, `pos === mesh.rest, vel === 0; after 2 s restDeviation ${e1(m2.restDeviation)}`);
  // reset at slider extremes
  let ok = true, worst = 0;
  for (const [f, d] of [[0, 0], [1, 1], [0, 1], [1, 0]]) { sim.setFirmness(f); sim.setDamping(d); sim.reset(); sim.stepSubsteps(steps(6)); const q = sim.metrics(); worst = Math.max(worst, q.restDeviation); ok = ok && q.finite && q.restDeviation < 0.02 && q.mode === 'stuck'; }
  check('reset() settles at every slider corner', ok, `worst restDeviation after 6 s ${e1(worst)}`);
}

// --------------------------------------------------------------------------
// 9. timestep robustness
// --------------------------------------------------------------------------
if (begin('timestep robustness')) {
  // (a) a free scenario must not depend on how real time is cut into frames at all
  const N = steps(2.5);
  const runFree = (frame, scale) => {
    const sim = makeSim({ allowSleep: false });
    sim.reset(); sim.nudge(1);
    const per = Math.ceil(frame * scale / DT) + 1;
    let frames = 0;
    while (sim.steps + per < N) { sim.advance(frame, scale); frames++; }
    sim.stepSubsteps(N - sim.steps);
    return { x: Float64Array.from(sim.x), frames, m: snap(sim) };
  };
  const ref = runFree(1 / 60, 1);
  const variants = [['1/144 s frames', 1 / 144, 1], ['1/30 s frames', 1 / 30, 1], ['uneven frames', 0.0123, 1], ['1/4 speed', 1 / 60, 0.25]];
  for (const [name, frame, scale] of variants) {
    const r = runFree(frame, scale);
    let diff = 0; for (let i = 0; i < ref.x.length; i++) diff = Math.max(diff, Math.abs(r.x[i] - ref.x[i]));
    check(`${name}: identical to 1/60 s frames`, diff === 0 && r.m.finite, `${r.frames} frames vs ${ref.frames}; max difference after ${N} substeps: ${diff}`);
  }
  // (b) 1/4 speed is the same simulation played slowly
  {
    const sim = makeSim({ allowSleep: false });
    sim.reset();
    let n1 = 0; for (let k = 0; k < 240; k++) n1 += sim.advance(1 / 60, 0.25);
    check('1/4 speed: a quarter of the substeps per frame', Math.abs(n1 - steps(1)) <= 1, `${n1} substeps in 240 frames (4 s real = 1 s simulated)`);
  }
  // (c) a stalled tab: the backlog is dropped, nothing jumps
  {
    const sim = makeSim({ allowSleep: false });
    sim.reset({ drop: false });
    const hit = pickAt(sim, [0.0, 0.99, 0.05]);
    sim.startGrab(1, hit); sim.moveGrab(1, [0.4, 1.6, 0.1]);
    for (let k = 0; k < 30; k++) sim.advance(1 / 60);
    const before = sim.metrics().com.slice();
    const k1 = sim.advance(0.5), k2 = sim.advance(5), k3 = sim.advance(1 / 60);
    const m = sim.metrics();
    const jump = Math.hypot(m.com[0] - before[0], m.com[1] - before[1], m.com[2] - before[2]);
    const cap = Math.ceil(DEFAULT_PARAMS.maxBacklog / DT);
    check('0.5 s and 5 s stalls are clamped', k1 === cap && k2 === cap && k3 === Math.round(1 / 60 / DT) && m.finite && jump < 0.3, `advance(0.5) -> ${k1}, advance(5) -> ${k2} substeps (cap ${cap} = ${(cap * DT * 1000).toFixed(0)} ms), next frame -> ${k3}; centre moved ${f3(jump)}`);
    check('bad frame times are ignored', sim.advance(NaN) === 0 && sim.advance(-1) === 0 && sim.advance(1 / 60, 0) === 0 && sim.metrics().finite);
  }
  // (d) a scripted drag (the target is a function of simulated time) at different frame rates:
  //     the pointer is sampled at other instants, so the motion may differ a little, not more
  const runDrag = (frame, scale, stallAt) => {
    const sim = makeSim({ allowSleep: false });
    sim.reset({ drop: false });
    const hit = pickAt(sim, [0.3, 0.6, 0.23]);
    sim.startGrab(1, hit, hit.point);
    const p0 = hit.point.slice();
    const per = Math.ceil(frame * scale / DT) + 1;
    const script = () => {
      const t = sim.time;
      if (t < 1.6) sim.moveGrab(1, [p0[0] + 0.45 * Math.sin(2.2 * t), p0[1] + 0.3 * (1 - Math.cos(1.7 * t)), p0[2] + 0.3 * Math.sin(1.3 * t)]);
      else sim.endGrab(1);
    };
    const samples = [];
    let worstRel = 0, finite = true, real = 0, stalled = false;
    for (let cp = 1; cp <= 12; cp++) {
      const target = steps(0.25 * cp);
      while (sim.steps + per < target) {
        script();
        if (stallAt !== undefined && !stalled && real >= stallAt) { sim.advance(0.5, scale); stalled = true; } else sim.advance(frame, scale);
        real += frame;
        const m = sim.metrics(); finite = finite && m.finite; worstRel = Math.max(worstRel, m.maxStretchRel);
      }
      script();
      if (target > sim.steps) sim.stepSubsteps(target - sim.steps);
      const m = sim.metrics();
      samples.push([m.com.slice(), m.maxY, m.mode]);
    }
    return { samples, worstRel, finite };
  };
  const base = runDrag(1 / 60, 1);
  for (const [name, frame, scale, stallAt] of [['1/144 s frames', 1 / 144, 1], ['1/30 s frames', 1 / 30, 1], ['1/4 speed', 1 / 60, 0.25], ['0.5 s stall mid-drag', 1 / 60, 1, 0.7]]) {
    const r = runDrag(frame, scale, stallAt);
    let diff = 0;
    for (let k = 0; k < 12; k++) {
      const a = r.samples[k], b = base.samples[k];
      diff = Math.max(diff, Math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1], a[0][2] - b[0][2]), Math.abs(a[1] - b[1]));
    }
    check(`scripted drag, ${name}: same motion`, r.finite && diff < 0.06 && r.worstRel < 1.12, `largest difference of centre / height at 12 checkpoints (every 0.25 s of simulated time): ${f3(diff)}; worst stretch ${f2(r.worstRel)} of the limit`);
  }
}

// --------------------------------------------------------------------------
// 10. fuzz
// --------------------------------------------------------------------------
if (begin('fuzz')) {
  const PER_SEED = 16000, SEEDS = [11, 2024, 77777];
  let total = 0, samples = 0, inverted = 0, worstRel = 0, overLimit = 0, minVol = Infinity, maxSpeed = 0, finite = true, minY = Infinity, farthest = 0, volLo = 1, volHi = 1;
  const settle = [];
  const t0 = Date.now();
  for (const seed0 of SEEDS) {
    const sim = makeSim();
    let seed = seed0; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    const ids = [1, 2, 3];
    let done = 0, nextEvent = 0;
    while (done < PER_SEED && finite) {
      if (done >= nextEvent) {
        const r = rnd(), id = ids[Math.floor(rnd() * 3)];
        if (r < 0.3) {
          const o = [(rnd() - 0.5) * 6, rnd() * 3 + 0.2, 5], at = [(rnd() - 0.5) * 2.2, rnd() * 1.1, (rnd() - 0.5) * 0.4];
          const l = Math.hypot(at[0] - o[0], at[1] - o[1], at[2] - o[2]);
          const hit = sim.raycast(o, [(at[0] - o[0]) / l, (at[1] - o[1]) / l, (at[2] - o[2]) / l]);
          if (hit) sim.startGrab(id, hit);
        } else if (r < 0.65) sim.moveGrab(id, [(rnd() - 0.5) * 12, (rnd() - 0.3) * 8, (rnd() - 0.5) * 8]);   // teleporting target
        else if (r < 0.78) sim.endGrab(id);
        else if (r < 0.84) sim.nudge(rnd() * 3);
        else if (r < 0.9) sim.setFirmness(rnd() < 0.5 ? Math.round(rnd()) : rnd());
        else if (r < 0.96) sim.setDamping(rnd() < 0.5 ? Math.round(rnd()) : rnd());
        else if (r < 0.98) sim.reset(rnd() < 0.5 ? undefined : { drop: false });
        else sim.moveGrab(id, [NaN, Infinity, -Infinity]);
        nextEvent = done + Math.floor(rnd() * 200);
      }
      const k = 1 + Math.floor(rnd() * 12);
      if (rnd() < 0.5) sim.stepSubsteps(k); else sim.advance(k * DT * (0.5 + rnd()), rnd() < 0.2 ? 0.25 : 1);
      done += k;
      const m = sim.metrics();
      samples++;
      if (!m.finite) finite = false;
      worstRel = Math.max(worstRel, m.maxStretchRel); if (m.maxStretchRel > 1.1) overLimit++;
      minVol = Math.min(minVol, m.minVolRatio); if (m.minVolRatio <= 0) inverted++;
      maxSpeed = Math.max(maxSpeed, m.maxSpeed); minY = Math.min(minY, m.minY);
      volLo = Math.min(volLo, m.volumeRatio); volHi = Math.max(volHi, m.volumeRatio);
      farthest = Math.max(farthest, Math.hypot(m.com[0], m.com[1] - 0.42, m.com[2]));
    }
    total += done;
    // afterwards: let go, default sliders, settle
    for (const id of ids) sim.endGrab(id);
    sim.setFirmness(0.5); sim.setDamping(0.5);
    sim.stepSubsteps(steps(10));
    settle.push(snap(sim));
  }
  info(`${total} substeps (${(total * DT).toFixed(0)} s of random multi-touch grabs, teleporting targets, slider extremes, nudges, resets), ${samples} samples, ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  check('always finite', finite, `max particle speed ${f2(maxSpeed)} u/s, slice never farther than ${f2(farthest)} from home`);
  check('nothing below the ground', minY >= 0, `minY ${minY}`);
  check('stretch limits respected', worstRel < 1.35 && overLimit / samples < 0.01, `worst edge ever at ${f2(worstRel)} of its limit; ${(100 * overLimit / samples).toFixed(2)} % of samples above 1.10`);
  check('tets do not stay inverted', inverted / samples < 0.03 && minVol > -1, `${inverted} of ${samples} samples (${(100 * inverted / samples).toFixed(2)} %) had a tet with volume <= 0 (worst ${f2(minVol)}); total volume ${f3(volLo)}..${f3(volHi)}`);
  check('returns to rest afterwards', settle.every((m) => m.finite && m.restDeviation < 0.01 && m.mode === 'stuck' && m.minVolRatio > 0.9 && m.kinetic < 1e-4), settle.map((m) => `${e1(m.restDeviation)} (${m.mode})`).join(', ') + ' restDeviation 10 s after letting go');
}

// --------------------------------------------------------------------------
// 11. performance
// --------------------------------------------------------------------------
if (begin('performance')) {
  const sim = makeSim({ allowSleep: false });
  const time = (frames, each) => {
    for (let k = 0; k < 120; k++) { if (each) each(k); sim.advance(1 / 60); }
    const t0 = process.hrtime.bigint();
    for (let k = 0; k < frames; k++) { if (each) each(k + 120); sim.advance(1 / 60); }
    return Number(process.hrtime.bigint() - t0) / 1e6 / frames;
  };
  const ctor0 = process.hrtime.bigint(); makeSim(); const ctorMs = Number(process.hrtime.bigint() - ctor0) / 1e6;
  sim.reset({ drop: false });
  const idle = time(600);
  const hit = pickAt(sim, [0.2, 0.6, 0.23]);
  sim.startGrab(1, hit); const p0 = hit.point.slice();
  const drag = time(600, (k) => { const t = k / 60; sim.moveGrab(1, [p0[0] + 0.8 * Math.sin(2.5 * t), p0[1] + 0.5 + 0.5 * Math.sin(1.9 * t), p0[2] + 0.5 * Math.sin(1.3 * t)]); });
  sim.endGrab(1);
  sim.reset({ drop: false });
  const hl = pickAt(sim, [-0.7, 0.4, 0.23]), hr = pickAt(sim, [0.7, 0.4, 0.23]);
  sim.startGrab(1, hl); sim.startGrab(2, hr);
  const two = time(600, (k) => { const t = k / 60, u = 0.9 * (0.5 - 0.5 * Math.cos(2 * t)); sim.moveGrab(1, [hl.point[0] - u, hl.point[1] + 0.4 * u, hl.point[2]]); sim.moveGrab(2, [hr.point[0] + u, hr.point[1] + 0.4 * u, hr.point[2]]); });
  const asleep = makeSim(); asleep.reset({ drop: false });
  let frames = 0; while (!asleep.sleeping && frames < 60 * 40) { asleep.advance(1 / 60); frames++; }
  const ts = process.hrtime.bigint(); for (let k = 0; k < 600; k++) asleep.advance(1 / 60); const sleepMs = Number(process.hrtime.bigint() - ts) / 1e6 / 600;
  const per = Math.round(1 / 60 / DT);
  info(`mesh: ${mesh.numParticles} particles, ${mesh.numTets} tets, ${mesh.edges.length / 2} edges; ${per} substeps per 60 Hz frame; constructor ${ctorMs.toFixed(0)} ms`);
  info(`ms per advance(1/60): idle ${idle.toFixed(2)}, one-finger drag ${drag.toFixed(2)}, two-finger stretch ${two.toFixed(2)}, asleep ${sleepMs.toFixed(4)} (fell asleep after ${(frames / 60).toFixed(1)} s)`);
  // The budget is 2.5 ms; the hard failure line is looser because this machine is shared.
  check('one frame of simulation while dragging', drag < 4.0, `${drag.toFixed(2)} ms (target <= 2.5 ms${drag <= 2.5 ? '' : ' -- OVER TARGET, machine busy?'})`);
  check('idle frame', idle < 4.0, `${idle.toFixed(2)} ms awake, ${sleepMs.toFixed(4)} ms once asleep`);
  check('goes to sleep when left alone', asleep.sleeping && asleep.metrics().restDeviation < 0.003, `after ${(frames / 60).toFixed(1)} s, restDeviation ${e1(asleep.metrics().restDeviation)}`);
  asleep.nudge(1);
  check('wakes up when touched', !asleep.sleeping && asleep.advance(1 / 60) === per);
}

// --------------------------------------------------------------------------
console.log('\n' + '='.repeat(78));
const bySection = new Map();
for (const [sec, , pass] of rows) { const s = bySection.get(sec) || [0, 0]; s[pass ? 0 : 1]++; bySection.set(sec, s); }
for (const [sec, [p, f]] of bySection) console.log(`${f ? 'FAIL' : 'PASS'}  ${sec.padEnd(24)} ${p}/${p + f}`);
console.log(`${failures ? 'FAILED' : 'ALL PASSED'}: ${checks - failures}/${checks} checks in ${((Date.now() - T0) / 1000).toFixed(1)} s`);
process.exit(failures ? 1 : 0);
