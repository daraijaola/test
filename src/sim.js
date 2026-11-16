'use strict';
/*
 * sim.js — the soft body: a tetrahedral, position-based (XPBD) simulation of
 * the gummy slice, advanced in small fixed substeps with one constraint pass
 * per substep.
 *
 * What happens in a substep, in this order:
 *
 *   grabbing     every pointer holds the surface point it picked. The pull is
 *                applied as a smooth bump of displacement over the particles
 *                within grabRadius of that point (in the home pose), through a
 *                stiff spring with a force cap, towards a target that follows
 *                the pointer critically damped, speed limited and on a leash.
 *                Deformation therefore starts at the finger and spreads through
 *                the material; the slice can pivot freely about the grab.
 *   elasticity   per tetrahedron and mesh independent: a deviatoric constraint
 *                on the Green strain, g(|E|) with compliance 1 / (2 mu V)
 *                (g softens the quadratic energy to a linear one at large
 *                strain, so the flesh stretches far instead of locking up),
 *                and a hydrostatic constraint det F - 1 with compliance
 *                1 / (lambda V). Both are zero at rest and are solved together
 *                as one 2x2 block per tet. mu and lambda depend on the zone:
 *                flesh soft, pith in between, rind 5.5 times stiffer.
 *   volume       the hydrostatic term, plus one global constraint on the total
 *                volume: stretched flesh has to neck, a squashed slice bulges.
 *   ground       y >= 0 with Coulomb friction on the elastic motion.
 *   limits       unilateral limits on every edge (max stretch 2.4 flesh,
 *                1.8 pith, 1.45 rind; min 0.4) with a progressive spring
 *                before the hard stop, and a floor on every tet volume. The
 *                hard stop is warm started like a rope in a rigid-body solver,
 *                so it also holds a sustained pull. They come last: no input
 *                can stretch the mesh into spikes or leave it inside out.
 *   sticky base  the particles of the cut face are tied to an "anchor frame"
 *                by saturating springs. Normally the frame is the home pose:
 *                jelly stuck to a plate, something to pull against, the far
 *                side stays put. Pull hard enough and the base peels off, the
 *                tether fades and the slice hangs from the finger under gravity
 *                alone. Let go and it falls, lands, squashes and wobbles as a
 *                free body; then the frame is fitted to where it came to rest
 *                and glides home, speed and acceleration limited, carrying the
 *                slice by its base.
 *   damping      on velocities: (1) linear damping of the motion relative to
 *                the reference frame (the plate while stuck, the best-fit
 *                rigid motion while free, so flying and swinging are not
 *                damped); (2) strain-rate damping along edges, which kills
 *                ripples before wobbles; (3) a cap on how fast the shape may
 *                come back: the kinetic energy of the returning motion is
 *                bounded (scaled down as a whole, so the wobble that follows
 *                keeps its shape) and no particle snaps back faster than the
 *                cap. Stretching is not resisted, only the recoil: a released
 *                stretch returns like gummy, not like a rubber band, and then
 *                overshoots and jiggles freely.
 *
 * The stress-free shape of the tets is pre-distorted so that the pose the slice
 * sags into under gravity is exactly mesh.rest ("sag-free" rest shape, found by
 * relaxing the real solver once and refined while the slice sits still).
 *
 * `pos` is what the renderer draws: the state interpolated between the last two
 * substeps, so motion stays even when a frame holds a fractional number of
 * substeps (1/4 speed, 144 Hz). `x` / `v` are the exact Float64 state.
 *
 * Units: slice radius 1, +y up, ground y = 0, density 1, seconds.
 * Nothing is allocated while stepping.
 */

// Resolution of the simulation mesh (passed to buildSliceMesh by main.js).
const SIM_MESH_OPTIONS = { h: 0.16, layers: 3 };

const MODE_STUCK = 0;    // base held to the home pose
const MODE_FREE = 1;     // no tether at all: gravity, ground, grabs
const MODE_HOMING = 2;   // tether fading in while the anchor frame glides home

const MAX_GRABS = 8;
const HOME_CENTRE = [0, 0.45, 0];

const DEFAULT_PARAMS = {
  substepDt: 1 / 600,
  maxBacklog: 0.05,            // seconds of simulation per advance() at most

  gravity: 11,
  density: 1,
  massEvenness: 0.6,           // 0 = lumped masses, 1 = all particles equally heavy

  // --- elasticity (at firmness 0.5) ---
  mu: 70,                      // flesh shear modulus
  zoneMu: [1, 2.2, 5.5],       // flesh / pith / rind multipliers
  strainSoften: 1.2,           // c0: the strain energy turns from quadratic to linear around |E| ~ c0 (0 = never)
  lambdaRatio: 12,             // lambda = ratio * mu_flesh * zoneLambda
  zoneLambda: [1, 1.6, 2.6],
  firmnessRange: 3.2,          // stiffness scale = range^(2 f - 1)
  globalVolume: 1,             // 0 disables the global volume constraint
  globalVolumeStiffness: 0.5,  // fraction of the volume error removed per substep

  // --- limits ---
  zoneMaxStretch: [2.4, 1.8, 1.45],
  minStretch: 0.4,
  limitWarm: 0.9,              // fraction of a loaded limit's pull that is re-applied up front in the next substep
  softLimitStart: 0.55,        // progressive stiffening starts at 1 + f * (max - 1)
  softLimitGain: 3,            // extra stiffness relative to the edge's own
  minTetVolume: 0.18,          // inversion guard: det F never stays below this

  // --- ground ---
  friction: 0.75,

  // --- sticky base / homing ---
  anchorOmega: 300,            // rad/s of a base particle on its anchor spring
  anchorHold: 230,             // total force the stuck base can hold before it starts to give
  anchorDamp: 50,              // 1/s dashpot between base particle and frame
  breakD1: 0.05, breakD2: 0.22,// mean base displacement where the tether starts / finishes fading
  tauBreak: 0.05, tauRecover: 0.35,
  homeDelay: 0.25,             // s after release before homing may start
  homeContact: 0.22,           // s of ground contact required before homing
  homeTimeout: 3.0,
  homeRamp: 0.35,              // s for the tether to fade in
  homeOmega: 7,                // rad/s of the critically damped glide
  homeSpeed: 2.2, homeSpin: 4.0,
  homeAccel: 7, homeSpinAccel: 12,
  homeFar: 2.5,                // beyond this distance the glide speeds up in proportion

  // --- grabbing ---
  grabRadius: 0.27,
  grabDepth: 0.45,             // distances through the thickness count this much: the patch is an ellipsoid ~0.6 deep
  grabStiffness: 4000,
  grabMaxForce: 150,
  forceScaling: 0.5,           // grab and anchor forces scale with stiffnessScale^this
  grabFollow: 45,              // rad/s of the critically damped target filter
  grabMaxSpeed: 8,
  leash: 2.6,

  // --- damping (functions of the Internal damping slider d) ---
  rigidFloor: 0.85,            // 1/s, always there: nothing may wobble for ever
  rigidDamp: [0.1, 1.4, 14],   // 1/s at d = 0, 0.5, 1 (times sqrt(stiffness scale): constant damping ratio)
  edgeDamp: [0.0008, 0.004, 0.03], // s, stiffness-proportional
  returnSpeed: [3.2, 2.6, 2.0],// cap on the speed of the elastic return, u/s
  returnRms: 0.42,             // the cap applies to the rms speed of the returning motion (x this factor) ...
  returnLocal: 1.2,            // ... and, a little looser, to every single particle
  returnHeldFactor: 2.5,       // looser while a finger is holding on (direct manipulation must not lag)
  globalDrag: 0.12,            // 1/s
  maxSpeed: 18,
  maxFlightSpeed: 7,           // a free slice never travels faster than this as a whole (it must stay on stage)
  maxSpin: 9,                  // rad/s
  righting: 30,                // rad/s^2 per unit sin(tilt): a let-go slice turns its cut face down
  rightingDamp: 2.5,           // 1/s on the tumbling part of its spin

  allowSleep: true,            // stop stepping while the slice sits perfectly still at home
  sagAdapt: 0.5,               // gain of the slow sag correction (per averaging window)

  // --- reset / nudge ---
  dropHeight: 0.32,
  nudgeHop: 3.4,
  nudgeTwist: 1.7,
  nudgeTilt: 1.1,
};

function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
function smoothstep(a, b, v) { const t = clamp01((v - a) / (b - a)); return t * t * (3 - 2 * t); }
// value at slider d from [at 0, at 0.5, at 1], geometric interpolation
function tri(arr, d) {
  d = clamp01(d);
  return d <= 0.5 ? arr[0] * Math.pow(arr[1] / arr[0], d * 2) : arr[1] * Math.pow(arr[2] / arr[1], d * 2 - 1);
}

class JellySim {
  constructor(mesh, opts) {
    const P = this.params = Object.assign({}, DEFAULT_PARAMS, opts || {});
    this.mesh = mesh;
    const n = this.n = mesh.numParticles;
    const m = this.numTets = mesh.numTets;
    this.substepDt = P.substepDt;
    this.gravity = P.gravity;
    this.firmness = 0.5;
    this.damping = 0.5;
    this.time = 0;
    this.steps = 0;

    // ---- state -------------------------------------------------------------
    this.pos = new Float32Array(n * 3);      // presented positions (renderer reads these)
    this.vel = new Float32Array(n * 3);
    this.x = new Float64Array(n * 3);        // exact state after the last substep
    this.xp = new Float64Array(n * 3);       // state before the last substep
    this.v = new Float64Array(n * 3);
    this.rest = new Float64Array(n * 3);     // home pose
    this.ref = new Float64Array(n * 3);      // stress-free shape (home pose minus sag)
    this.sagA = new Float64Array(n * 3);     // sag (rest - ref) = sagA / scale + sagB
    this.sagB = new Float64Array(n * 3);
    for (let i = 0; i < n * 3; i++) this.rest[i] = mesh.rest[i];

    // ---- topology ------------------------------------------------------------
    this.tets = new Int32Array(m * 4);
    for (let i = 0; i < m * 4; i++) this.tets[i] = mesh.tets[i];
    this.tetZone = mesh.tetZone;
    this.tetB = new Float64Array(m * 9);     // inverse rest matrix, row major
    this.tetAD = new Float64Array(m);        // compliance / dt^2, deviatoric
    this.tetAH = new Float64Array(m);        // compliance / dt^2, hydrostatic
    this.tetDB = new Float64Array(m);        // 1 / det(rest matrix)
    this.tetVolHome = new Float64Array(m);
    this.surfTris = mesh.surfTris;
    this.numSurfTris = mesh.surfTris.length / 3;

    // ---- masses (lumped from the home pose) ---------------------------------
    this.mass = new Float64Array(n);
    this.w = new Float64Array(n);
    let totalVol = 0;
    for (let t = 0; t < m; t++) {
      const vol = tetVolume(this.rest, this.tets[t * 4], this.tets[t * 4 + 1], this.tets[t * 4 + 2], this.tets[t * 4 + 3]);
      this.tetVolHome[t] = vol;
      totalVol += vol;
      for (let k = 0; k < 4; k++) this.mass[this.tets[t * 4 + k]] += P.density * vol * 0.25;
    }
    // Lumped masses differ by a factor of ~45 between an interior particle and
    // a rim corner; with one constraint pass per substep the light ones would be
    // shoved around by everything they touch. Blend towards the mean mass (the
    // total stays the same).
    {
      const mean = P.density * totalVol / n, a = P.massEvenness;
      for (let i = 0; i < n; i++) this.mass[i] = (1 - a) * this.mass[i] + a * mean;
    }
    this.totalMass = 0;
    for (let i = 0; i < n; i++) { this.w[i] = 1 / this.mass[i]; this.totalMass += this.mass[i]; }
    this.homeVolume = totalVol;
    this.homeCom = new Float64Array(3);
    for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) this.homeCom[k] += this.mass[i] * this.rest[i * 3 + k] / this.totalMass;

    // ---- edges ---------------------------------------------------------------
    const ne = this.numEdges = mesh.edges.length / 2;
    this.edges = new Int32Array(ne * 2);
    for (let i = 0; i < ne * 2; i++) this.edges[i] = mesh.edges[i];
    this.edgeL0 = new Float64Array(ne);      // home length
    this.edgeMax = new Float64Array(ne);     // absolute max length
    this.edgeMax2 = new Float64Array(ne);
    this.edgeMin = new Float64Array(ne);
    this.edgeMin2 = new Float64Array(ne);
    this.edgeSoft = new Float64Array(ne);    // length where progressive stiffening starts
    this.edgeSoft2 = new Float64Array(ne);
    this.edgeSoftA = new Float64Array(ne);   // its compliance / dt^2
    this.edgeLimit = new Float64Array(ne);   // max stretch ratio
    this.edgeK0 = new Float64Array(ne);      // elastic stiffness of the edge at scale 1
    this.edgeF = new Float64Array(ne);       // damping fraction per substep
    this.edgeLam = new Float64Array(ne);     // pull a loaded hard limit needed in the last substep
    this.limActive = new Int32Array(ne);     // the edges with edgeLam > 0
    this.limActiveCount = 0;
    this.edgeWA = new Float64Array(ne);      // wa / (wa + wb)
    {
      // zone limit and Van Gelder stiffness from the adjacent tets
      const key = new Map();
      for (let e = 0; e < ne; e++) { key.set(this.edges[e * 2] * n + this.edges[e * 2 + 1], e); this.edgeLimit[e] = Infinity; }
      const TE = [0, 1, 0, 2, 0, 3, 1, 2, 1, 3, 2, 3];
      for (let t = 0; t < m; t++) {
        const z = this.tetZone[t];
        for (let k = 0; k < 6; k++) {
          const a = this.tets[t * 4 + TE[k * 2]], b = this.tets[t * 4 + TE[k * 2 + 1]];
          const e = key.get(Math.min(a, b) * n + Math.max(a, b));
          if (P.zoneMaxStretch[z] < this.edgeLimit[e]) this.edgeLimit[e] = P.zoneMaxStretch[z];
          this.edgeK0[e] += 3 * P.mu * P.zoneMu[z] * this.tetVolHome[t];
        }
      }
      for (let e = 0; e < ne; e++) {
        const a = this.edges[e * 2], b = this.edges[e * 2 + 1];
        const L = Math.hypot(this.rest[a * 3] - this.rest[b * 3], this.rest[a * 3 + 1] - this.rest[b * 3 + 1], this.rest[a * 3 + 2] - this.rest[b * 3 + 2]);
        this.edgeL0[e] = L;
        this.edgeK0[e] /= L * L;
        this.edgeMax[e] = L * this.edgeLimit[e];
        this.edgeMax2[e] = this.edgeMax[e] * this.edgeMax[e];
        this.edgeMin[e] = L * P.minStretch;
        this.edgeMin2[e] = this.edgeMin[e] * this.edgeMin[e];
        this.edgeSoft[e] = L * (1 + P.softLimitStart * (this.edgeLimit[e] - 1));
        this.edgeSoft2[e] = this.edgeSoft[e] * this.edgeSoft[e];
        this.edgeWA[e] = this.w[a] / (this.w[a] + this.w[b]);
      }
    }

    // ---- sticky base ---------------------------------------------------------
    const base = [];
    for (let i = 0; i < n; i++) if (this.rest[i * 3 + 1] < 1e-6) base.push(i);
    const nb = this.numBase = base.length;
    this.baseIdx = new Int32Array(base);
    this.anchorPos = new Float64Array(nb * 3);
    this.anchorVel = new Float64Array(nb * 3);
    this.baseCentre = new Float64Array(3);
    this.baseMassTotal = 0;
    for (let k = 0; k < nb; k++) {
      const i = base[k];
      this.baseMassTotal += this.mass[i];
      for (let c = 0; c < 3; c++) this.baseCentre[c] += this.mass[i] * this.rest[i * 3 + c];
    }
    for (let c = 0; c < 3; c++) this.baseCentre[c] /= this.baseMassTotal;
    this.fric = new Float64Array(n).fill(1);  // per-particle friction scale

    this.mode = MODE_STUCK;
    this.stick = 1;          // stiction factor (drops when the base is dragged away)
    this.ramp = 1;           // fade-in while homing
    this.tether = 1;         // stick * ramp, what the anchors actually use
    this.anchorD = 0;        // mass-weighted mean distance of base particles from their anchors
    this.contactCount = 0;
    this.tRelease = 0;
    this.tContact = 0;
    this.homingT = 0;
    this.homeU = 0; this.homeUVel = 0;
    this.homeFrom = new Float64Array(3);     // base centre where homing started
    this.homeAxis = new Float64Array([0, 1, 0]);
    this.homeAngle = 0;
    this.homeVMax = 1; this.homeAMax = 1;

    // ---- grabs -----------------------------------------------------------------
    this.grabs = [];
    const maxPatch = Math.min(n, 400);
    for (let g = 0; g < MAX_GRABS; g++) {
      this.grabs.push({
        active: false, id: -1, count: 0,
        idx: new Int32Array(maxPatch), wt: new Float64Array(maxPatch),
        mass: 0, ta: 0, tb: 0, tc: 0, b0: 0, b1: 0, b2: 0,
        raw: new Float64Array(3), tgt: new Float64Array(3), tv: new Float64Array(3),
        force: 0,
      });
    }
    this.grabCount = 0;

    // ---- scratch -----------------------------------------------------------------
    this._acc = 0;
    this._alpha = 1;
    this._rng = 0x2545f491;
    this._nudgeSign = 1;
    this._calibrating = false;
    this._spinScale = 1;
    this._lowTets = 0;
    this._sagTick = 0; this._sagCount = -1; this._sagDone = false; this._calm = 0;
    this.sleeping = false;                   // true while the slice sits perfectly still: advance() then costs nothing
    this._sagAcc = new Float64Array(n * 3);
    this._sagEvery = Math.max(1, Math.round(1 / 60 / this.substepDt));     // sample at ~60 Hz
    this._sagWindow = 72;                                                // ~1.2 s per correction
    this._quat = new Float64Array(4);
    this._fitQuat = new Float64Array([0, 0, 0, 1]);   // best-fit rotation home -> current (warm start)
    this._fitMat = new Float64Array(9);
    this._mat = new Float64Array(9);
    this._volGrad = new Float64Array(n * 3);
    this._dev = new Float64Array(n * 3);
    this._gate = new Float64Array(n);
    this._stats = { finite: true, kinetic: 0, maxStretch: 1, minStretch: 1, minVolRatio: 1, com: [0, 0, 0], minY: 0, maxY: 0, maxSpeed: 0, restDeviation: 0 };

    this._refresh();
    if (P.calibrate !== false) this._calibrateSag();
    this.time = 0; this.steps = 0;           // the clock starts now, not with the calibration
    this.reset({ drop: P.drop === true });
  }

  // ======================================================================
  // public controls
  // ======================================================================

  setFirmness(v) { this.firmness = clamp01(+v || 0); this._refresh(); this.wake(); }
  setDamping(v) { this.damping = clamp01(+v || 0); this._refreshCoefficients(); }

  /** Resume stepping (called by everything that can disturb the slice; call it yourself after editing x / v directly). */
  wake() { this.sleeping = false; this._calm = 0; this._sagDone = false; }

  /** Accumulate real time (scaled) and run whole fixed substeps. Returns the number of substeps run. */
  advance(realSeconds, timeScale) {
    const dt = this.substepDt;
    const ts = timeScale === undefined ? 1 : +timeScale;
    let add = +realSeconds * ts;
    if (!(add > 0)) add = 0;
    if (this.sleeping) { this._acc = 0; return 0; }      // at rest: nothing to do until it is touched
    this._acc += add;
    let k = Math.floor(this._acc / dt + 1e-7);
    const maxK = Math.ceil(this.params.maxBacklog / dt);
    if (k > maxK) { k = maxK; this._acc = 0; } else this._acc -= k * dt;   // a stall is dropped, not replayed
    if (this._acc < 0) this._acc = 0;
    for (let i = 0; i < k; i++) this._substep();
    this._present(this._acc / dt);
    return k;
  }

  /** Run exactly k fixed substeps (tests). */
  stepSubsteps(k) {
    this.sleeping = false;
    for (let i = 0; i < k; i++) this._substep();
    this._present(1);
  }

  /** Back to the home pose. Default: lifted a little so it drops, squashes and settles. */
  reset(opts) {
    const o = opts || {};
    const drop = o.drop !== false;
    const P = this.params, n = this.n, x = this.x, xp = this.xp, v = this.v;
    for (const g of this.grabs) { g.active = false; g.id = -1; }
    this.grabCount = 0;
    this.wake();
    const lift = drop ? (o.height !== undefined ? +o.height : P.dropHeight) : 0;
    const src = drop ? this.ref : this.rest;     // dropped: start stress-free
    for (let i = 0; i < n * 3; i++) { x[i] = src[i]; v[i] = 0; }
    if (drop) {
      // put the lowest point of the stress-free shape at `lift`
      let lo = Infinity;
      for (let i = 0; i < n; i++) if (x[i * 3 + 1] < lo) lo = x[i * 3 + 1];
      for (let i = 0; i < n; i++) x[i * 3 + 1] += lift - lo;
    }
    for (let i = 0; i < n * 3; i++) xp[i] = x[i];
    this._fitQuat[0] = this._fitQuat[1] = this._fitQuat[2] = 0; this._fitQuat[3] = 1;
    this._clearLimits();
    this._setFrameHome();
    if (drop) {
      this.mode = MODE_FREE; this.stick = 1; this.ramp = 0; this.tether = 0;
    } else {
      this.mode = MODE_STUCK; this.stick = 1; this.ramp = 1; this.tether = 1;
    }
    this.tRelease = 0; this.tContact = 0; this.homingT = 0; this.anchorD = 0;
    this.contactCount = 0;
    this._acc = 0;
    this._syncFriction();
    this._present(1);
  }

  /** Playful impulse: a hop with a twist. Safe at any time, also while grabbed. */
  nudge(strength) {
    const P = this.params, n = this.n, x = this.x, v = this.v;
    let s = strength === undefined ? 1 : +strength;
    if (!(s > 0)) return;
    if (s > 2.5) s = 2.5;
    this.wake();
    const sign = this._nudgeSign; this._nudgeSign = -sign;
    const r1 = this._rand() - 0.5, r2 = this._rand() - 0.5;
    // centre of mass
    let cx = 0, cy = 0, cz = 0;
    for (let i = 0; i < n; i++) { const mi = this.mass[i]; cx += mi * x[i * 3]; cy += mi * x[i * 3 + 1]; cz += mi * x[i * 3 + 2]; }
    cx /= this.totalMass; cy /= this.totalMass; cz /= this.totalMass;
    const hop = P.nudgeHop * Math.sqrt(s);
    const twist = P.nudgeTwist * s * sign;
    const tilt = P.nudgeTilt * s * (sign * 0.7 + r1 * 0.6);
    const lean = 0.5 * s * r2;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3;
      const rx = x[i3] - cx, ry = x[i3 + 1] - cy, rz = x[i3 + 2] - cz;
      const h = clamp01(this.rest[i3 + 1]);                 // material height
      const wy = twist * (0.35 + 2.2 * (h - 0.42));         // a little spin, mostly wringing: top and base turn opposite ways
      // v += hop + wy * (y x r) + tilt * (z x r) + lean * (x x r)
      v[i3] += wy * rz - tilt * ry;
      v[i3 + 1] += hop * (0.85 + 0.3 * h) + tilt * rx - lean * rz;
      v[i3 + 2] += -wy * rx + lean * ry;
    }
    this._clampSpeeds(P.maxSpeed * 0.5);
    // let go of the ground
    this.mode = MODE_FREE; this.stick = 1; this.ramp = 0; this.tether = 0;
    this.tRelease = 0; this.tContact = 0;
    this._syncFriction();
    for (let i = 0; i < n * 3; i++) this.vel[i] = v[i];
  }

  /** Nearest intersection of a ray with the current (presented) surface. */
  raycast(origin, dir) {
    const p = this.pos, tris = this.surfTris;
    const ox = +origin[0], oy = +origin[1], oz = +origin[2];
    const dx = +dir[0], dy = +dir[1], dz = +dir[2];
    let best = Infinity, bi = -1, bu = 0, bv = 0;
    for (let t = 0, nt = this.numSurfTris; t < nt; t++) {
      const a = tris[t * 3] * 3, b = tris[t * 3 + 1] * 3, c = tris[t * 3 + 2] * 3;
      const ax = p[a], ay = p[a + 1], az = p[a + 2];
      const e1x = p[b] - ax, e1y = p[b + 1] - ay, e1z = p[b + 2] - az;
      const e2x = p[c] - ax, e2y = p[c + 1] - ay, e2z = p[c + 2] - az;
      const px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
      const det = e1x * px + e1y * py + e1z * pz;
      if (det > -1e-14 && det < 1e-14) continue;
      const inv = 1 / det;
      const tx = ox - ax, ty = oy - ay, tz = oz - az;
      const u = (tx * px + ty * py + tz * pz) * inv;
      if (u < 0 || u > 1) continue;
      const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
      const vv = (dx * qx + dy * qy + dz * qz) * inv;
      if (vv < 0 || u + vv > 1) continue;
      const tt = (e2x * qx + e2y * qy + e2z * qz) * inv;
      if (tt > 1e-7 && tt < best) { best = tt; bi = t; bu = u; bv = vv; }
    }
    if (bi < 0) return null;
    return { t: best, point: [ox + dx * best, oy + dy * best, oz + dz * best], tri: bi, bary: [1 - bu - bv, bu, bv] };
  }

  /** Attach a soft patch around `hit` (from raycast) to the pointer `id`. */
  startGrab(id, hit, target) {
    if (!hit || !(hit.tri >= 0) || hit.tri >= this.numSurfTris || !hit.bary) return false;
    let g = null;
    for (const s of this.grabs) if (s.active && s.id === id) { g = s; break; }
    if (!g) for (const s of this.grabs) if (!s.active) { g = s; break; }
    if (!g) return false;
    const P = this.params, n = this.n, rest = this.rest, x = this.x;
    const tris = this.surfTris;
    const ta = tris[hit.tri * 3], tb = tris[hit.tri * 3 + 1], tc = tris[hit.tri * 3 + 2];
    let b0 = +hit.bary[0], b1 = +hit.bary[1], b2 = +hit.bary[2];
    if (!(b0 === b0 && b1 === b1 && b2 === b2)) return false;
    const bs = b0 + b1 + b2 || 1; b0 /= bs; b1 /= bs; b2 /= bs;
    // the picked point in the home pose and in the current pose
    const hx = b0 * rest[ta * 3] + b1 * rest[tb * 3] + b2 * rest[tc * 3];
    const hy = b0 * rest[ta * 3 + 1] + b1 * rest[tb * 3 + 1] + b2 * rest[tc * 3 + 1];
    const hz = b0 * rest[ta * 3 + 2] + b1 * rest[tb * 3 + 2] + b2 * rest[tc * 3 + 2];
    const px = b0 * x[ta * 3] + b1 * x[tb * 3] + b2 * x[tc * 3];
    const py = b0 * x[ta * 3 + 1] + b1 * x[tb * 3 + 1] + b2 * x[tc * 3 + 1];
    const pz = b0 * x[ta * 3 + 2] + b1 * x[tb * 3 + 2] + b2 * x[tc * 3 + 2];
    // patch: particles within grabRadius of the picked point, measured in the home pose.
    // The pull is applied as a smooth bump of displacement, largest at the
    // picked point and fading to nothing at the patch radius.
    // The patch reaches deeper through the thickness than it is wide: a finger on
    // the face takes hold of the slice, not just of its skin.
    const R = P.grabRadius, R2 = R * R, zs = P.grabDepth;
    let count = 0;
    const cap = g.idx.length;
    for (let i = 0; i < n && count < cap; i++) {
      const ddx = rest[i * 3] - hx, ddy = rest[i * 3 + 1] - hy, ddz = (rest[i * 3 + 2] - hz) * zs;
      const d2 = ddx * ddx + ddy * ddy + ddz * ddz;
      if (d2 >= R2) continue;
      const q = 1 - d2 / R2;
      g.idx[count] = i; g.wt[count] = q * q; count++;
    }
    if (count === 0) return this._dropGrab(g);
    // scale the bump so that the picked surface point moves exactly with it
    let atPick = 0;
    for (let k = 0; k < count; k++) {
      const i = g.idx[k];
      if (i === ta) atPick += b0 * g.wt[k]; else if (i === tb) atPick += b1 * g.wt[k]; else if (i === tc) atPick += b2 * g.wt[k];
    }
    if (!(atPick > 0.05)) return this._dropGrab(g);
    let gm = 0;
    for (let k = 0; k < count; k++) { g.wt[k] /= atPick; gm += this.mass[g.idx[k]] * g.wt[k] * g.wt[k]; }
    g.count = count; g.mass = gm;                 // generalised mass of the bump
    g.ta = ta; g.tb = tb; g.tc = tc; g.b0 = b0; g.b1 = b1; g.b2 = b2;
    g.tgt[0] = px; g.tgt[1] = py; g.tgt[2] = pz;
    g.tv[0] = g.tv[1] = g.tv[2] = 0;
    g.force = 0;
    if (!g.active) { g.active = true; this.grabCount++; }
    g.id = id;
    this.wake();
    if (target && target.length >= 3) this._setRawTarget(g, target); else { g.raw[0] = px; g.raw[1] = py; g.raw[2] = pz; this._leash(g.raw); }
    return true;
  }

  _dropGrab(g) {
    if (g.active) { g.active = false; g.id = -1; this.grabCount--; }
    return false;
  }

  moveGrab(id, target) {
    if (!target) return;
    for (const g of this.grabs) if (g.active && g.id === id) { this._setRawTarget(g, target); return; }
  }

  endGrab(id) {
    for (const g of this.grabs) {
      if (g.active && g.id === id) {
        g.active = false; g.id = -1; this.grabCount--;
        if (this.grabCount === 0) { this.tRelease = 0; this.tContact = 0; }
      }
    }
  }

  /** Per particle: 0 relaxed .. 1 at the stretch limit. */
  computeTension(out) {
    const n = this.n, x = this.x;
    const o = out && out.length >= n ? out : new Float32Array(n);
    for (let i = 0; i < n; i++) o[i] = 0;
    const ed = this.edges, L0 = this.edgeL0, lim = this.edgeLimit;
    for (let e = 0, ne = this.numEdges; e < ne; e++) {
      const a = ed[e * 2], b = ed[e * 2 + 1], a3 = a * 3, b3 = b * 3;
      const dx = x[b3] - x[a3], dy = x[b3 + 1] - x[a3 + 1], dz = x[b3 + 2] - x[a3 + 2];
      let t = (Math.sqrt(dx * dx + dy * dy + dz * dz) / L0[e] - 1) / (lim[e] - 1);
      if (t > 1) t = 1;
      if (t > o[a]) o[a] = t;
      if (t > o[b]) o[b] = t;
    }
    return o;
  }

  /** Diagnostics. Returns the same object on every call (no allocation): copy it to keep it. */
  metrics() {
    const n = this.n, x = this.x, v = this.v, rest = this.rest, s = this._stats;
    let finite = true, kin = 0, minY = Infinity, maxY = -Infinity, maxSp2 = 0, dev2 = 0, devSum = 0;
    let cx = 0, cy = 0, cz = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, mi = this.mass[i];
      const px = x[i3], py = x[i3 + 1], pz = x[i3 + 2];
      const vx = v[i3], vy = v[i3 + 1], vz = v[i3 + 2];
      if (!(isFinite(px) && isFinite(py) && isFinite(pz) && isFinite(vx) && isFinite(vy) && isFinite(vz))) finite = false;
      const sp2 = vx * vx + vy * vy + vz * vz;
      kin += 0.5 * mi * sp2;
      if (sp2 > maxSp2) maxSp2 = sp2;
      if (py < minY) minY = py;
      if (py > maxY) maxY = py;
      cx += mi * px; cy += mi * py; cz += mi * pz;
      const ddx = px - rest[i3], ddy = py - rest[i3 + 1], ddz = pz - rest[i3 + 2];
      const d2 = ddx * ddx + ddy * ddy + ddz * ddz;
      if (d2 > dev2) dev2 = d2;
      devSum += d2;
    }
    let maxS = 0, minS = Infinity;
    const ed = this.edges, L0 = this.edgeL0;
    let maxRel = 0;
    for (let e = 0, ne = this.numEdges; e < ne; e++) {
      const a3 = ed[e * 2] * 3, b3 = ed[e * 2 + 1] * 3;
      const st = Math.hypot(x[b3] - x[a3], x[b3 + 1] - x[a3 + 1], x[b3 + 2] - x[a3 + 2]) / L0[e];
      if (st > maxS) maxS = st;
      if (st < minS) minS = st;
      const rel = st / this.edgeLimit[e];
      if (rel > maxRel) maxRel = rel;
    }
    let minVol = Infinity, vol = 0;
    for (let t = 0, m = this.numTets; t < m; t++) {
      const tv = tetVolume(x, this.tets[t * 4], this.tets[t * 4 + 1], this.tets[t * 4 + 2], this.tets[t * 4 + 3]);
      vol += tv;
      const r = tv / this.tetVolHome[t];
      if (r < minVol) minVol = r;
    }
    s.finite = finite && isFinite(kin);
    s.kinetic = kin;
    s.maxStretch = maxS; s.minStretch = minS; s.minVolRatio = minVol;
    s.com[0] = cx / this.totalMass; s.com[1] = cy / this.totalMass; s.com[2] = cz / this.totalMass;
    s.minY = minY; s.maxY = maxY;
    s.maxSpeed = Math.sqrt(maxSp2);
    s.restDeviation = Math.sqrt(dev2);
    // extras (beyond the contract)
    s.restDeviationRms = Math.sqrt(devSum / n);
    s.maxStretchRel = maxRel;            // worst edge stretch relative to its own limit (<= 1 means inside the limit)
    s.volumeRatio = vol / this.homeVolume;
    s.tether = this.tether;
    s.mode = this.mode === MODE_STUCK ? 'stuck' : this.mode === MODE_FREE ? 'free' : 'homing';
    s.grabs = this.grabCount;
    s.sleeping = this.sleeping;
    s.time = this.time;
    return s;
  }

  // ======================================================================
  // coefficients
  // ======================================================================

  get stiffnessScale() { return Math.pow(this.params.firmnessRange, 2 * this.firmness - 1); }

  /** Recompute everything that depends on the sliders or the stress-free shape. */
  _refresh() {
    this._rebuildRest();
    this._refreshCoefficients();
  }

  /** Stress-free shape (home pose minus sag) -> per-tet rest matrices and compliances. */
  _rebuildRest() {
    const P = this.params, n = this.n, m = this.numTets, dt = this.substepDt;
    const scale = this.stiffnessScale;
    const ref = this.ref, rest = this.rest, sagA = this.sagA, sagB = this.sagB, inv = 1 / scale;
    // the sag under gravity is (to first order) inversely proportional to the stiffness
    for (let i = 0; i < n * 3; i++) ref[i] = rest[i] - (sagA[i] * inv + sagB[i]);
    const idt2 = 1 / (dt * dt);
    const tets = this.tets, B = this.tetB;
    const muS = P.mu * scale, lamS = P.mu * P.lambdaRatio * scale;
    for (let t = 0; t < m; t++) {
      const a = tets[t * 4] * 3, b = tets[t * 4 + 1] * 3, c = tets[t * 4 + 2] * 3, d = tets[t * 4 + 3] * 3;
      const e1x = ref[b] - ref[a], e1y = ref[b + 1] - ref[a + 1], e1z = ref[b + 2] - ref[a + 2];
      const e2x = ref[c] - ref[a], e2y = ref[c + 1] - ref[a + 1], e2z = ref[c + 2] - ref[a + 2];
      const e3x = ref[d] - ref[a], e3y = ref[d + 1] - ref[a + 1], e3z = ref[d + 2] - ref[a + 2];
      // rows of the inverse of [e1 e2 e3]
      const c1x = e2y * e3z - e2z * e3y, c1y = e2z * e3x - e2x * e3z, c1z = e2x * e3y - e2y * e3x;
      const c2x = e3y * e1z - e3z * e1y, c2y = e3z * e1x - e3x * e1z, c2z = e3x * e1y - e3y * e1x;
      const c3x = e1y * e2z - e1z * e2y, c3y = e1z * e2x - e1x * e2z, c3z = e1x * e2y - e1y * e2x;
      const det = e1x * c1x + e1y * c1y + e1z * c1z;
      const id = 1 / det, t9 = t * 9;
      B[t9] = c1x * id; B[t9 + 1] = c1y * id; B[t9 + 2] = c1z * id;
      B[t9 + 3] = c2x * id; B[t9 + 4] = c2y * id; B[t9 + 5] = c2z * id;
      B[t9 + 6] = c3x * id; B[t9 + 7] = c3y * id; B[t9 + 8] = c3z * id;
      const vol = det / 6, z = this.tetZone[t];
      this.tetDB[t] = id;
      this.tetAD[t] = idt2 / (2 * muS * P.zoneMu[z] * vol);
      this.tetAH[t] = idt2 / (lamS * P.zoneLambda[z] * vol);
    }
  }

  _refreshCoefficients() {
    const P = this.params, dt = this.substepDt;
    const scale = this.stiffnessScale, idt2 = 1 / (dt * dt);
    // damping: slider -> rates. Ratios stay roughly constant across firmness.
    const d = this.damping, rs = Math.sqrt(scale);
    this.rigidDampK = 1 - Math.exp(-(P.rigidFloor + rs * tri(P.rigidDamp, d)) * dt);
    const beta = tri(P.edgeDamp, d) / rs;
    this.returnSpeed = tri(P.returnSpeed, d) * Math.pow(scale, 0.15);
    const ed = this.edges;
    for (let e = 0, ne = this.numEdges; e < ne; e++) {
      const a = ed[e * 2], b = ed[e * 2 + 1];
      const k = this.edgeK0[e] * scale, wsum = this.w[a] + this.w[b];
      let f = beta * k * wsum * dt * 2;                 // each edge is visited every other substep
      if (f > 0.5) f = 0.5;
      this.edgeF[e] = f;
      this.edgeSoftA[e] = idt2 / (P.softLimitGain * k);
    }
    this.anchorPhi = (P.anchorOmega * P.anchorOmega * dt * dt) / (1 + P.anchorOmega * P.anchorOmega * dt * dt);
    // what the base can hold and what a finger can pull grow with the firmness,
    // but slower than the stiffness: a soft slice stretches all the way to its
    // limits before it lets go of the plate, a firm one pops off sooner
    const fs = Math.pow(scale, P.forceScaling);
    this.anchorMaxStep = P.anchorHold / this.baseMassTotal * fs * dt * dt;
    this.grabAlpha = 1 / (P.grabStiffness * fs * dt * dt);
    this.grabMaxF = P.grabMaxForce * fs;
    this.anchorDampK = 1 - Math.exp(-P.anchorDamp * dt);
  }

  _syncFriction() {
    const f = this._calibrating ? 0 : 1 - this.tether;
    const fr = this.fric, bi = this.baseIdx;
    for (let k = 0, nb = this.numBase; k < nb; k++) fr[bi[k]] = f;
  }

  _setFrameHome() {
    const ap = this.anchorPos, av = this.anchorVel, bi = this.baseIdx, rest = this.rest;
    for (let k = 0, nb = this.numBase; k < nb; k++) {
      const i3 = bi[k] * 3, k3 = k * 3;
      ap[k3] = rest[i3]; ap[k3 + 1] = rest[i3 + 1]; ap[k3 + 2] = rest[i3 + 2];
      av[k3] = av[k3 + 1] = av[k3 + 2] = 0;
    }
    this.homeU = 0; this.homeUVel = 0;
  }

  _rand() {
    let s = this._rng | 0;
    s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
    this._rng = s;
    return (s >>> 0) / 4294967296;
  }

  _leash(t) {
    const P = this.params;
    if (!(t[0] === t[0] && t[1] === t[1] && t[2] === t[2])) { t[0] = HOME_CENTRE[0]; t[1] = HOME_CENTRE[1]; t[2] = HOME_CENTRE[2]; }
    let dx = t[0] - HOME_CENTRE[0], dy = t[1] - HOME_CENTRE[1], dz = t[2] - HOME_CENTRE[2];
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (!(d < 1e30)) { dx = dy = dz = 0; t[0] = HOME_CENTRE[0]; t[1] = HOME_CENTRE[1]; t[2] = HOME_CENTRE[2]; }
    else if (d > P.leash) {
      const k = P.leash / d;
      t[0] = HOME_CENTRE[0] + dx * k; t[1] = HOME_CENTRE[1] + dy * k; t[2] = HOME_CENTRE[2] + dz * k;
    }
    if (t[1] < 0.1) t[1] = 0.1;
  }

  _setRawTarget(g, target) {
    g.raw[0] = +target[0]; g.raw[1] = +target[1]; g.raw[2] = +target[2];
    this._leash(g.raw);
  }

  _present(alpha) {
    const n3 = this.n * 3, x = this.x, xp = this.xp, v = this.v, pos = this.pos, vel = this.vel;
    if (alpha >= 1) { for (let i = 0; i < n3; i++) { pos[i] = x[i]; vel[i] = v[i]; } }
    else {
      if (alpha < 0) alpha = 0;
      for (let i = 0; i < n3; i++) { pos[i] = xp[i] + (x[i] - xp[i]) * alpha; vel[i] = v[i]; }
    }
    this._alpha = alpha;
  }

  _clampSpeeds(vmax) {
    const v = this.v, n = this.n, m2 = vmax * vmax;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, s2 = v[i3] * v[i3] + v[i3 + 1] * v[i3 + 1] + v[i3 + 2] * v[i3 + 2];
      if (s2 > m2) { const k = vmax / Math.sqrt(s2); v[i3] *= k; v[i3 + 1] *= k; v[i3 + 2] *= k; }
      else if (!(s2 === s2)) { v[i3] = v[i3 + 1] = v[i3 + 2] = 0; }
    }
  }

  // ======================================================================
  // one fixed substep
  // ======================================================================

  _substep() {
    const dt = this.substepDt, n = this.n, P = this.params;
    const x = this.x, xp = this.xp, v = this.v;

    if (this.grabCount > 0) this._updateGrabTargets(dt);
    this._updateTether(dt);

    // integrate
    const gdt = -this.gravity * dt;
    const drag = this._calibrating ? Math.exp(-this._calibDrag * dt) : 1 - P.globalDrag * dt;
    const vmax2 = P.maxSpeed * P.maxSpeed;
    for (let i = 0, n3 = n * 3; i < n3; i += 3) {
      const vx = v[i] * drag, vy = v[i + 1] * drag + gdt, vz = v[i + 2] * drag;
      xp[i] = x[i]; xp[i + 1] = x[i + 1]; xp[i + 2] = x[i + 2];
      x[i] += vx * dt; x[i + 1] += vy * dt; x[i + 2] += vz * dt;
    }

    // constraints, one pass
    if (this.grabCount > 0) this._solveGrabs();
    this._solveTets();
    if (P.globalVolume) this._solveVolume();
    this._solveGround();                 // contact and friction act on the elastic motion ...
    if (this.limActiveCount > 0) this._warmLimits();
    const hard = this._solveLimits(false);
    if (this.mode !== MODE_FREE) this._solveAnchors();
    // extra sweeps only in the substeps that need them
    if (hard > 0) this._solveLimits(true);
    if (this._lowTets > 0) this._guardTets();
    // ... but friction never undoes a limit: a particle that sticks to the
    // ground must not let its neighbours be pushed through it. Nothing ends a
    // step below the ground.
    for (let i = 1, n3 = n * 3; i < n3; i += 3) if (x[i] < 0) x[i] = 0;

    // velocities
    const idt = 1 / dt;
    for (let i = 0, n3 = n * 3; i < n3; i += 3) {
      let vx = (x[i] - xp[i]) * idt, vy = (x[i + 1] - xp[i + 1]) * idt, vz = (x[i + 2] - xp[i + 2]) * idt;
      const s2 = vx * vx + vy * vy + vz * vz;
      if (s2 > vmax2) { const k = P.maxSpeed / Math.sqrt(s2); vx *= k; vy *= k; vz *= k; }   // a violent correction must not become a fling
      v[i] = vx; v[i + 1] = vy; v[i + 2] = vz;
    }

    // damping
    if (!this._calibrating) {
      this._dampRigid();
      this._dampEdges();
    }
    if (this.tether > 0 && this.mode !== MODE_FREE) this._dampAnchors();
    if (!this._calibrating) this._adaptSag();

    this.time += dt;
    this.steps++;
  }

  // ---- elasticity -------------------------------------------------------

  _solveTets() {
    const x = this.x, w = this.w, tets = this.tets, B = this.tetB;
    const AD = this.tetAD, AH = this.tetAH, DB = this.tetDB;
    const jmin = this.params.minTetVolume, ic0 = this.params.strainSoften > 0 ? 1 / this.params.strainSoften : 0;
    const jwatch = jmin + 0.1, jspan = 1 / (0.6 - jmin);
    let low = 0;
    for (let t = 0, m = this.numTets; t < m; t++) {
      const t4 = t * 4, t9 = t * 9;
      const pa = tets[t4], pb = tets[t4 + 1], pc = tets[t4 + 2], pd = tets[t4 + 3];
      const ia = pa * 3, ib = pb * 3, ic = pc * 3, id = pd * 3;
      const ax = x[ia], ay = x[ia + 1], az = x[ia + 2];
      const e1x = x[ib] - ax, e1y = x[ib + 1] - ay, e1z = x[ib + 2] - az;
      const e2x = x[ic] - ax, e2y = x[ic + 1] - ay, e2z = x[ic + 2] - az;
      const e3x = x[id] - ax, e3y = x[id + 1] - ay, e3z = x[id + 2] - az;
      const b11 = B[t9], b12 = B[t9 + 1], b13 = B[t9 + 2];
      const b21 = B[t9 + 3], b22 = B[t9 + 4], b23 = B[t9 + 5];
      const b31 = B[t9 + 6], b32 = B[t9 + 7], b33 = B[t9 + 8];
      // deformation gradient, by columns
      const f1x = e1x * b11 + e2x * b21 + e3x * b31, f1y = e1y * b11 + e2y * b21 + e3y * b31, f1z = e1z * b11 + e2z * b21 + e3z * b31;
      const f2x = e1x * b12 + e2x * b22 + e3x * b32, f2y = e1y * b12 + e2y * b22 + e3y * b32, f2z = e1z * b12 + e2z * b22 + e3z * b32;
      const f3x = e1x * b13 + e2x * b23 + e3x * b33, f3y = e1y * b13 + e2y * b23 + e3y * b33, f3z = e1z * b13 + e2z * b23 + e3z * b33;
      // volume ratio J = det(Ds) / det(Dm) and its gradients (nodes b, c, d; a is minus their sum)
      const db = DB[t];
      const h1x = (e2y * e3z - e2z * e3y) * db, h1y = (e2z * e3x - e2x * e3z) * db, h1z = (e2x * e3y - e2y * e3x) * db;
      const h2x = (e3y * e1z - e3z * e1y) * db, h2y = (e3z * e1x - e3x * e1z) * db, h2z = (e3x * e1y - e3y * e1x) * db;
      const h3x = (e1y * e2z - e1z * e2y) * db, h3y = (e1z * e2x - e1x * e2z) * db, h3z = (e1x * e2y - e1y * e2x) * db;
      const J = e1x * h1x + e1y * h1y + e1z * h1z;
      const h0x = -(h1x + h2x + h3x), h0y = -(h1y + h2y + h3y), h0z = -(h1z + h2z + h3z);
      const wa = w[pa], wb = w[pb], wc = w[pc], wd = w[pd];
      const hh = wa * (h0x * h0x + h0y * h0y + h0z * h0z) + wb * (h1x * h1x + h1y * h1y + h1z * h1z) +
        wc * (h2x * h2x + h2y * h2y + h2z * h2z) + wd * (h3x * h3x + h3y * h3y + h3z * h3z);

      if (J < jwatch) low++;
      if (J < jmin) {
        // crushed or inverted: no strain solve, just push the volume back up
        // (bounded step; _guardTets() follows with ground-aware weights)
        if (hh > 1e-30) {
          let l = (jmin - J) / hh;
          const m2 = Math.max(wa * wa * (h0x * h0x + h0y * h0y + h0z * h0z), wb * wb * (h1x * h1x + h1y * h1y + h1z * h1z),
            wc * wc * (h2x * h2x + h2y * h2y + h2z * h2z), wd * wd * (h3x * h3x + h3y * h3y + h3z * h3z));
          if (l * l * m2 > 2.25e-4) l = 0.015 / Math.sqrt(m2);
          x[ia] += wa * l * h0x; x[ia + 1] += wa * l * h0y; x[ia + 2] += wa * l * h0z;
          x[ib] += wb * l * h1x; x[ib + 1] += wb * l * h1y; x[ib + 2] += wb * l * h1z;
          x[ic] += wc * l * h2x; x[ic + 1] += wc * l * h2y; x[ic + 2] += wc * l * h2z;
          x[id] += wd * l * h3x; x[id + 1] += wd * l * h3y; x[id + 2] += wd * l * h3z;
        }
        continue;
      }

      // Green strain E = (F^T F - I) / 2 and the deviatoric constraint C = g(|E|)
      const E11 = 0.5 * (f1x * f1x + f1y * f1y + f1z * f1z - 1);
      const E22 = 0.5 * (f2x * f2x + f2y * f2y + f2z * f2z - 1);
      const E33 = 0.5 * (f3x * f3x + f3y * f3y + f3z * f3z - 1);
      const E12 = 0.5 * (f1x * f2x + f1y * f2y + f1z * f2z);
      const E13 = 0.5 * (f1x * f3x + f1y * f3y + f1z * f3z);
      const E23 = 0.5 * (f2x * f3x + f2y * f3y + f2z * f3z);
      const c2 = E11 * E11 + E22 * E22 + E33 * E33 + 2 * (E12 * E12 + E13 * E13 + E23 * E23);
      if (c2 < 1e-20) {
        // no shear strain: only the volume term acts
        const lH = (1 - J) / (hh + AH[t]);
        x[ia] += wa * lH * h0x; x[ia + 1] += wa * lH * h0y; x[ia + 2] += wa * lH * h0z;
        x[ib] += wb * lH * h1x; x[ib + 1] += wb * lH * h1y; x[ib + 2] += wb * lH * h1z;
        x[ic] += wc * lH * h2x; x[ic + 1] += wc * lH * h2y; x[ic + 2] += wc * lH * h2z;
        x[id] += wd * lH * h3x; x[id + 1] += wd * lH * h3y; x[id + 2] += wd * lH * h3z;
        continue;
      }
      const cE = Math.sqrt(c2), qs = 1 + cE * ic0, sq = Math.sqrt(qs);
      const CD = cE / sq;                                   // softened: quadratic near rest, linear far out
      const kk = (1 + 0.5 * cE * ic0) / (qs * sq * cE);     // dC/d|E| / |E|
      // P = kk * F E, by columns
      const p1x = (f1x * E11 + f2x * E12 + f3x * E13) * kk, p1y = (f1y * E11 + f2y * E12 + f3y * E13) * kk, p1z = (f1z * E11 + f2z * E12 + f3z * E13) * kk;
      const p2x = (f1x * E12 + f2x * E22 + f3x * E23) * kk, p2y = (f1y * E12 + f2y * E22 + f3y * E23) * kk, p2z = (f1z * E12 + f2z * E22 + f3z * E23) * kk;
      const p3x = (f1x * E13 + f2x * E23 + f3x * E33) * kk, p3y = (f1y * E13 + f2y * E23 + f3y * E33) * kk, p3z = (f1z * E13 + f2z * E23 + f3z * E33) * kk;
      // deviatoric gradients
      const d1x = p1x * b11 + p2x * b12 + p3x * b13, d1y = p1y * b11 + p2y * b12 + p3y * b13, d1z = p1z * b11 + p2z * b12 + p3z * b13;
      const d2x = p1x * b21 + p2x * b22 + p3x * b23, d2y = p1y * b21 + p2y * b22 + p3y * b23, d2z = p1z * b21 + p2z * b22 + p3z * b23;
      const d3x = p1x * b31 + p2x * b32 + p3x * b33, d3y = p1y * b31 + p2y * b32 + p3y * b33, d3z = p1z * b31 + p2z * b32 + p3z * b33;
      const d0x = -(d1x + d2x + d3x), d0y = -(d1y + d2y + d3y), d0z = -(d1z + d2z + d3z);

      const dd = wa * (d0x * d0x + d0y * d0y + d0z * d0z) + wb * (d1x * d1x + d1y * d1y + d1z * d1z) +
        wc * (d2x * d2x + d2y * d2y + d2z * d2z) + wd * (d3x * d3x + d3y * d3y + d3z * d3z);
      const dh = wa * (d0x * h0x + d0y * h0y + d0z * h0z) + wb * (d1x * h1x + d1y * h1y + d1z * h1z) +
        wc * (d2x * h2x + d2y * h2y + d2z * h2z) + wd * (d3x * h3x + d3y * h3y + d3z * h3z);

      // 2x2 block solve for (deviatoric, hydrostatic). A tet that is being
      // crushed resists progressively harder, long before the floor.
      let aH = AH[t];
      if (J < 0.6) { const q = (J - jmin) * jspan; aH *= q > 0.1 ? q * q : 0.01; }
      const a11 = dd + AD[t], a22 = hh + aH;
      const rh1 = -CD, rh2 = 1 - J;
      const idet = 1 / (a11 * a22 - dh * dh);
      const lD = (rh1 * a22 - rh2 * dh) * idet;
      const lH = (a11 * rh2 - dh * rh1) * idet;

      x[ia] += wa * (lD * d0x + lH * h0x); x[ia + 1] += wa * (lD * d0y + lH * h0y); x[ia + 2] += wa * (lD * d0z + lH * h0z);
      x[ib] += wb * (lD * d1x + lH * h1x); x[ib + 1] += wb * (lD * d1y + lH * h1y); x[ib + 2] += wb * (lD * d1z + lH * h1z);
      x[ic] += wc * (lD * d2x + lH * h2x); x[ic + 1] += wc * (lD * d2y + lH * h2y); x[ic + 2] += wc * (lD * d2z + lH * h2z);
      x[id] += wd * (lD * d3x + lH * h3x); x[id + 1] += wd * (lD * d3y + lH * h3y); x[id + 2] += wd * (lD * d3z + lH * h3z);
    }
    this._lowTets = low;
  }

  /**
   * Second line of defence against crushed or inverted tets (hard landings on
   * a corner, a patch dragged into the ground): only runs in substeps where the
   * elastic pass saw a tet close to the floor.
   */
  _guardTets() {
    const x = this.x, w = this.w, tets = this.tets, DB = this.tetDB;
    const jmin = this.params.minTetVolume;
    for (let t = 0, m = this.numTets; t < m; t++) {
      const t4 = t * 4;
      const pa = tets[t4], pb = tets[t4 + 1], pc = tets[t4 + 2], pd = tets[t4 + 3];
      const ia = pa * 3, ib = pb * 3, ic = pc * 3, id = pd * 3;
      const ax = x[ia], ay = x[ia + 1], az = x[ia + 2];
      const e1x = x[ib] - ax, e1y = x[ib + 1] - ay, e1z = x[ib + 2] - az;
      const e2x = x[ic] - ax, e2y = x[ic + 1] - ay, e2z = x[ic + 2] - az;
      const e3x = x[id] - ax, e3y = x[id + 1] - ay, e3z = x[id + 2] - az;
      const db = DB[t];
      const h1x = (e2y * e3z - e2z * e3y) * db, h1y = (e2z * e3x - e2x * e3z) * db, h1z = (e2x * e3y - e2y * e3x) * db;
      const J = e1x * h1x + e1y * h1y + e1z * h1z;
      if (J >= jmin) continue;
      const h2x = (e3y * e1z - e3z * e1y) * db, h2y = (e3z * e1x - e3x * e1z) * db, h2z = (e3x * e1y - e3y * e1x) * db;
      const h3x = (e1y * e2z - e1z * e2y) * db, h3y = (e1z * e2x - e1x * e2z) * db, h3z = (e1x * e2y - e1y * e2x) * db;
      const h0x = -(h1x + h2x + h3x), h0y = -(h1y + h2y + h3y), h0z = -(h1z + h2z + h3z);
      // particles lying on the ground cannot give way downwards: let the others do the moving
      const wa = ay <= 0 && h0y < 0 ? 0 : w[pa], wb = x[ib + 1] <= 0 && h1y < 0 ? 0 : w[pb];
      const wc = x[ic + 1] <= 0 && h2y < 0 ? 0 : w[pc], wd = x[id + 1] <= 0 && h3y < 0 ? 0 : w[pd];
      const hh = wa * (h0x * h0x + h0y * h0y + h0z * h0z) + wb * (h1x * h1x + h1y * h1y + h1z * h1z) +
        wc * (h2x * h2x + h2y * h2y + h2z * h2z) + wd * (h3x * h3x + h3y * h3y + h3z * h3z);
      if (!(hh > 1e-30)) continue;
      let l = (jmin - J) / hh;
      // never move a particle more than a fraction of an element per substep
      const m2 = Math.max(wa * wa * (h0x * h0x + h0y * h0y + h0z * h0z), wb * wb * (h1x * h1x + h1y * h1y + h1z * h1z),
        wc * wc * (h2x * h2x + h2y * h2y + h2z * h2z), wd * wd * (h3x * h3x + h3y * h3y + h3z * h3z));
      if (l * l * m2 > 2.25e-4) l = 0.015 / Math.sqrt(m2);
      x[ia] += wa * l * h0x; x[ia + 1] += wa * l * h0y; x[ia + 2] += wa * l * h0z;
      x[ib] += wb * l * h1x; x[ib + 1] += wb * l * h1y; x[ib + 2] += wb * l * h1z;
      x[ic] += wc * l * h2x; x[ic + 1] += wc * l * h2y; x[ic + 2] += wc * l * h2z;
      x[id] += wd * l * h3x; x[id + 1] += wd * l * h3y; x[id + 2] += wd * l * h3z;
    }
  }

  /** One global constraint: total volume = home volume (gradient from the surface). */
  _solveVolume() {
    const x = this.x, tris = this.surfTris, g = this._volGrad, w = this.w, n = this.n;
    for (let i = 0, n3 = n * 3; i < n3; i++) g[i] = 0;
    let vol6 = 0;
    for (let t = 0, nt = this.numSurfTris; t < nt; t++) {
      const a = tris[t * 3] * 3, b = tris[t * 3 + 1] * 3, c = tris[t * 3 + 2] * 3;
      const ax = x[a], ay = x[a + 1], az = x[a + 2];
      const bx = x[b], by = x[b + 1], bz = x[b + 2];
      const cx = x[c], cy = x[c + 1], cz = x[c + 2];
      // b x c, c x a, a x b
      const n1x = by * cz - bz * cy, n1y = bz * cx - bx * cz, n1z = bx * cy - by * cx;
      const n2x = cy * az - cz * ay, n2y = cz * ax - cx * az, n2z = cx * ay - cy * ax;
      const n3x = ay * bz - az * by, n3y = az * bx - ax * bz, n3z = ax * by - ay * bx;
      vol6 += ax * n1x + ay * n1y + az * n1z;
      g[a] += n1x; g[a + 1] += n1y; g[a + 2] += n1z;
      g[b] += n2x; g[b + 1] += n2y; g[b + 2] += n2z;
      g[c] += n3x; g[c + 1] += n3y; g[c + 2] += n3z;
    }
    // C = vol6 - 6 V0 (everything scaled by 6)
    const C = vol6 - 6 * this.homeVolume;
    let den = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3;
      den += w[i] * (g[i3] * g[i3] + g[i3 + 1] * g[i3 + 1] + g[i3 + 2] * g[i3 + 2]);
    }
    if (!(den > 1e-30)) return;
    const l = -this.params.globalVolumeStiffness * C / den;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, k = w[i] * l;
      x[i3] += k * g[i3]; x[i3 + 1] += k * g[i3 + 1]; x[i3 + 2] += k * g[i3 + 2];
    }
  }

  // ---- limits ---------------------------------------------------------------

  /**
   * Edge limits. The hard maximum is solved the way a rigid-body solver treats
   * a rope: every edge that is at its limit remembers how much it had to pull
   * (edgeLam) and starts the next substep by pulling that much again
   * (_warmLimits), so a sustained load is carried with almost no overshoot
   * instead of the limit sagging like a spring.
   */
  _solveLimits(reverse) {
    const x = this.x, ed = this.edges, wA = this.edgeWA, lam = this.edgeLam, act = this.limActive;
    const max2 = this.edgeMax2, min2 = this.edgeMin2, soft2 = this.edgeSoft2;
    const maxL = this.edgeMax, minL = this.edgeMin, softL = this.edgeSoft, softA = this.edgeSoftA, w = this.w;
    const ne = this.numEdges;
    let hard = 0, na = this.limActiveCount;
    for (let q = 0; q < ne; q++) {
      const e = reverse ? ne - 1 - q : q;
      const a = ed[e * 2], b = ed[e * 2 + 1], a3 = a * 3, b3 = b * 3;
      const dx = x[b3] - x[a3], dy = x[b3 + 1] - x[a3 + 1], dz = x[b3 + 2] - x[a3 + 2];
      const l2 = dx * dx + dy * dy + dz * dz;
      const acc = lam[e];
      if (acc === 0 && l2 <= soft2[e]) {
        if (l2 >= min2[e]) continue;
        // too short: push apart
        hard++;
        const l = Math.sqrt(l2);
        if (l < 1e-9) continue;
        const k = (l - minL[e]) / l, ka = k * wA[e], kb = k - ka;
        x[a3] += ka * dx; x[a3 + 1] += ka * dy; x[a3 + 2] += ka * dz;
        x[b3] -= kb * dx; x[b3 + 1] -= kb * dy; x[b3 + 2] -= kb * dz;
        continue;
      }
      const l = Math.sqrt(l2);
      if (l < 1e-9) continue;
      let corr;
      if (acc > 0 || l2 > max2[e]) {
        // hard limit with memory: the remembered pull may be given back, never more
        corr = l - maxL[e];
        if (corr < -acc) corr = -acc;
        let total = acc + corr;
        const cap = maxL[e] * 3;                      // (never needed in practice; keeps a bad state bounded)
        if (total > cap) { corr -= total - cap; total = cap; }
        if (acc === 0 && total > 0) act[na++] = e;
        lam[e] = total;
        hard++;
      } else { const ws = w[a] + w[b]; corr = (l - softL[e]) * ws / (ws + softA[e]); }  // progressive stiffening
      const k = corr / l, ka = k * wA[e], kb = k - ka;
      x[a3] += ka * dx; x[a3 + 1] += ka * dy; x[a3 + 2] += ka * dz;
      x[b3] -= kb * dx; x[b3 + 1] -= kb * dy; x[b3 + 2] -= kb * dz;
    }
    this.limActiveCount = na;
    return hard;
  }

  /** Start the substep with (most of) the pull each loaded limit needed last time. */
  _warmLimits() {
    const x = this.x, ed = this.edges, wA = this.edgeWA, lam = this.edgeLam, act = this.limActive;
    const keep = this.params.limitWarm;
    let na = 0;
    for (let q = 0, n0 = this.limActiveCount; q < n0; q++) {
      const e = act[q];
      const c = lam[e] * keep;
      if (c < 1e-7) { lam[e] = 0; continue; }       // slack again: forget it
      lam[e] = c; act[na++] = e;
      const a3 = ed[e * 2] * 3, b3 = ed[e * 2 + 1] * 3;
      const dx = x[b3] - x[a3], dy = x[b3 + 1] - x[a3 + 1], dz = x[b3 + 2] - x[a3 + 2];
      const l = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (l < 1e-9) continue;
      const k = c / l, ka = k * wA[e], kb = k - ka;
      x[a3] += ka * dx; x[a3 + 1] += ka * dy; x[a3 + 2] += ka * dz;
      x[b3] -= kb * dx; x[b3 + 1] -= kb * dy; x[b3 + 2] -= kb * dz;
    }
    this.limActiveCount = na;
  }

  _clearLimits() {
    this.edgeLam.fill(0);
    this.limActiveCount = 0;
  }

  // ---- ground -------------------------------------------------------------------

  _solveGround() {
    const x = this.x, xp = this.xp, fr = this.fric, n = this.n;
    const mu = this.params.friction;
    let contacts = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, y = x[i3 + 1];
      if (y >= 0) continue;
      contacts++;
      x[i3 + 1] = 0;
      const lim = -y * mu * fr[i];
      if (lim <= 0) continue;
      const dx = x[i3] - xp[i3], dz = x[i3 + 2] - xp[i3 + 2];
      const d2 = dx * dx + dz * dz;
      if (d2 <= lim * lim) { x[i3] = xp[i3]; x[i3 + 2] = xp[i3 + 2]; }
      else { const k = lim / Math.sqrt(d2); x[i3] -= dx * k; x[i3 + 2] -= dz * k; }
    }
    this.contactCount = contacts;
  }

  // ---- sticky base ---------------------------------------------------------------

  _solveAnchors() {
    const x = this.x, ap = this.anchorPos, bi = this.baseIdx, mass = this.mass;
    const calib = this._calibrating;
    const s = calib ? 1 : this.tether;
    const phi = (calib ? this._calibPhi : this.anchorPhi) * s;
    const maxStep = calib ? Infinity : this.anchorMaxStep * s;
    let sum = 0;
    for (let k = 0, nb = this.numBase; k < nb; k++) {
      const i = bi[k], i3 = i * 3, k3 = k * 3;
      const dx = x[i3] - ap[k3], dy = x[i3 + 1] - ap[k3 + 1], dz = x[i3 + 2] - ap[k3 + 2];
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
      sum += mass[i] * d;
      if (d < 1e-12 || phi <= 0) continue;
      let c = phi * d;
      if (c > maxStep) c = maxStep;
      const f = c / d;
      x[i3] -= dx * f; x[i3 + 1] -= dy * f; x[i3 + 2] -= dz * f;
    }
    this.anchorD = sum / this.baseMassTotal;
  }

  _dampAnchors() {
    const v = this.v, av = this.anchorVel, bi = this.baseIdx;
    const k = this.anchorDampK * this.tether;
    for (let j = 0, nb = this.numBase; j < nb; j++) {
      const i3 = bi[j] * 3, j3 = j * 3;
      v[i3] += (av[j3] - v[i3]) * k; v[i3 + 1] += (av[j3 + 1] - v[i3 + 1]) * k; v[i3 + 2] += (av[j3 + 2] - v[i3 + 2]) * k;
    }
  }

  _updateTether(dt) {
    if (this._calibrating) return;
    const P = this.params, grabbed = this.grabCount > 0;
    const before = this.tether;
    if (this.mode === MODE_FREE) {
      this.tether = 0; this.ramp = 0; this.stick = 1;
      if (grabbed) { this.tRelease = 0; this.tContact = 0; }
      else {
        this.tRelease += dt;
        if (this.contactCount > 0) this.tContact += dt;
        if ((this.tRelease > P.homeDelay && this.tContact > P.homeContact) || this.tRelease > P.homeTimeout) this._beginHoming();
      }
    } else {
      // stiction: the tether lets go when the base has been dragged away from its anchors
      let goal = 1;
      if (grabbed) goal = 1 - smoothstep(P.breakD1, P.breakD2, this.anchorD);
      const tau = goal < this.stick ? P.tauBreak : P.tauRecover;
      this.stick += (goal - this.stick) * Math.min(1, dt / tau);
      if (this.mode === MODE_HOMING) {
        this.homingT += dt;
        this.ramp = smoothstep(0, P.homeRamp, this.homingT);
        this._advanceHoming(dt);
      } else this.ramp = 1;
      this.tether = this.stick * this.ramp;
      if (this.stick < 0.08 || (!grabbed && this.stick < 0.5 && this.mode === MODE_STUCK)) {
        this.mode = MODE_FREE; this.tether = 0; this.ramp = 0; this.stick = 1;
        this.tRelease = 0; this.tContact = 0;
        this._setFrameHome();
      }
    }
    if (this.tether !== before) this._syncFriction();
  }

  /** Fit a rigid frame to where the body is now and start gliding it home. */
  _beginHoming() {
    const P = this.params, n = this.n, x = this.x, rest = this.rest, mass = this.mass;
    let cx = 0, cy = 0, cz = 0;
    for (let i = 0; i < n; i++) { const mi = mass[i]; cx += mi * x[i * 3]; cy += mi * x[i * 3 + 1]; cz += mi * x[i * 3 + 2]; }
    cx /= this.totalMass; cy /= this.totalMass; cz /= this.totalMass;
    const hc = this.homeCom;
    // A = sum m (x - c)(rest - c0)^T
    let a00 = 0, a01 = 0, a02 = 0, a10 = 0, a11 = 0, a12 = 0, a20 = 0, a21 = 0, a22 = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, mi = mass[i];
      const px = x[i3] - cx, py = x[i3 + 1] - cy, pz = x[i3 + 2] - cz;
      const qx = rest[i3] - hc[0], qy = rest[i3 + 1] - hc[1], qz = rest[i3 + 2] - hc[2];
      a00 += mi * px * qx; a01 += mi * px * qy; a02 += mi * px * qz;
      a10 += mi * py * qx; a11 += mi * py * qy; a12 += mi * py * qz;
      a20 += mi * pz * qx; a21 += mi * pz * qy; a22 += mi * pz * qz;
    }
    // rotation part; the damping pass keeps a warm estimate, polish it here
    const q = this._quat, R = this._mat, fq = this._fitQuat;
    q[0] = fq[0]; q[1] = fq[1]; q[2] = fq[2]; q[3] = fq[3];
    polarIterate(q, R, a00, a01, a02, a10, a11, a12, a20, a21, a22, 40);
    if (q[3] < 0) { q[0] = -q[0]; q[1] = -q[1]; q[2] = -q[2]; q[3] = -q[3]; }
    const sl = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2]);
    let angle = 2 * Math.atan2(sl, q[3]);
    if (!(angle === angle)) angle = 0;
    if (sl > 1e-9) { this.homeAxis[0] = q[0] / sl; this.homeAxis[1] = q[1] / sl; this.homeAxis[2] = q[2] / sl; }
    else { this.homeAxis[0] = 0; this.homeAxis[1] = 1; this.homeAxis[2] = 0; angle = 0; }
    this.homeAngle = angle;
    // where the base centre of that rigid pose is
    quatToMat(q, R);
    const bc = this.baseCentre;
    const ox = bc[0] - hc[0], oy = bc[1] - hc[1], oz = bc[2] - hc[2];
    this.homeFrom[0] = cx + R[0] * ox + R[1] * oy + R[2] * oz;
    this.homeFrom[1] = cy + R[3] * ox + R[4] * oy + R[5] * oz;
    this.homeFrom[2] = cz + R[6] * ox + R[7] * oy + R[8] * oz;
    const dist = Math.hypot(this.homeFrom[0] - bc[0], this.homeFrom[1] - bc[1], this.homeFrom[2] - bc[2]);
    // limits on the progress parameter u (1 -> 0) so neither speed limit is exceeded
    // (from far away the glide is faster, so coming home never takes much longer than ~2 s)
    const far = Math.max(1, dist / P.homeFar);
    this.homeVMax = Math.min(P.homeSpeed * far / Math.max(dist, 1e-3), P.homeSpin / Math.max(angle, 1e-3));
    this.homeAMax = Math.min(P.homeAccel * far / Math.max(dist, 1e-3), P.homeSpinAccel / Math.max(angle, 1e-3));
    this.homeU = 1; this.homeUVel = 0;
    this.homingT = 0; this.ramp = 0; this.stick = 1; this.tether = 0;
    this.mode = MODE_HOMING;
    this._placeFrame(0);
    const av = this.anchorVel;
    for (let k = 0, nb3 = this.numBase * 3; k < nb3; k++) av[k] = 0;
  }

  _advanceHoming(dt) {
    const P = this.params, om = P.homeOmega;
    let acc = -2 * om * this.homeUVel - om * om * this.homeU;
    if (acc > this.homeAMax) acc = this.homeAMax; else if (acc < -this.homeAMax) acc = -this.homeAMax;
    this.homeUVel += acc * dt;
    if (this.homeUVel < -this.homeVMax) this.homeUVel = -this.homeVMax;
    if (this.homeUVel > 0) this.homeUVel = 0;
    this.homeU += this.homeUVel * dt;
    const span = Math.max(Math.hypot(this.homeFrom[0] - this.baseCentre[0], this.homeFrom[1] - this.baseCentre[1], this.homeFrom[2] - this.baseCentre[2]), this.homeAngle);
    if (this.homeU * span < 2e-4 && this.ramp >= 1) {
      // arrived
      this._setFrameHome();
      this.mode = MODE_STUCK;
      return;
    }
    if (this.homeU < 0) this.homeU = 0;
    this._placeFrame(dt);
  }

  /** Put the anchors at the frame pose for the current homeU (and record their velocity). */
  _placeFrame(dt) {
    const u = this.homeU, R = this._mat, q = this._quat;
    const half = 0.5 * u * this.homeAngle, sn = Math.sin(half);
    q[0] = this.homeAxis[0] * sn; q[1] = this.homeAxis[1] * sn; q[2] = this.homeAxis[2] * sn; q[3] = Math.cos(half);
    quatToMat(q, R);
    const bc = this.baseCentre, rest = this.rest, n = this.n;
    const tx = bc[0] + u * (this.homeFrom[0] - bc[0]);
    let ty = bc[1] + u * (this.homeFrom[1] - bc[1]);
    const tz = bc[2] + u * (this.homeFrom[2] - bc[2]);
    // never carry the rigid ghost of the slice through the ground
    let lo = Infinity;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3;
      const y = R[3] * (rest[i3] - bc[0]) + R[4] * (rest[i3 + 1] - bc[1]) + R[5] * (rest[i3 + 2] - bc[2]);
      if (y < lo) lo = y;
    }
    if (ty + lo < 0) ty = -lo;
    const ap = this.anchorPos, av = this.anchorVel, bi = this.baseIdx;
    const idt = dt > 0 ? 1 / dt : 0;
    for (let k = 0, nb = this.numBase; k < nb; k++) {
      const i3 = bi[k] * 3, k3 = k * 3;
      const rx = rest[i3] - bc[0], ry = rest[i3 + 1] - bc[1], rz = rest[i3 + 2] - bc[2];
      const nx = tx + R[0] * rx + R[1] * ry + R[2] * rz;
      const ny = ty + R[3] * rx + R[4] * ry + R[5] * rz;
      const nz = tz + R[6] * rx + R[7] * ry + R[8] * rz;
      av[k3] = (nx - ap[k3]) * idt; av[k3 + 1] = (ny - ap[k3 + 1]) * idt; av[k3 + 2] = (nz - ap[k3 + 2]) * idt;
      ap[k3] = nx; ap[k3 + 1] = ny; ap[k3 + 2] = nz;
    }
  }

  // ---- grabs -------------------------------------------------------------------

  _updateGrabTargets(dt) {
    const P = this.params, om = P.grabFollow, vmax = P.grabMaxSpeed;
    for (let gi = 0; gi < MAX_GRABS; gi++) {
      const g = this.grabs[gi];
      if (!g.active) continue;
      const t = g.tgt, tv = g.tv, raw = g.raw;
      // critically damped follow, semi-implicit
      for (let k = 0; k < 3; k++) tv[k] += (om * om * (raw[k] - t[k]) - 2 * om * tv[k]) * dt;
      const s2 = tv[0] * tv[0] + tv[1] * tv[1] + tv[2] * tv[2];
      if (s2 > vmax * vmax) { const k = vmax / Math.sqrt(s2); tv[0] *= k; tv[1] *= k; tv[2] *= k; }
      t[0] += tv[0] * dt; t[1] += tv[1] * dt; t[2] += tv[2] * dt;
    }
  }

  _solveGrabs() {
    const x = this.x, dt = this.substepDt;
    const alpha = this.grabAlpha, maxF = this.grabMaxF;
    for (let gi = 0; gi < MAX_GRABS; gi++) {
      const g = this.grabs[gi];
      if (!g.active) continue;
      // the picked surface point, where it is now
      const a = g.ta * 3, b = g.tb * 3, c = g.tc * 3;
      const px = g.b0 * x[a] + g.b1 * x[b] + g.b2 * x[c];
      const py = g.b0 * x[a + 1] + g.b1 * x[b + 1] + g.b2 * x[c + 1];
      const pz = g.b0 * x[a + 2] + g.b1 * x[b + 2] + g.b2 * x[c + 2];
      // compliant attachment to the target, in the one coordinate "how far the bump is pushed"
      const k = -1 / (1 + alpha * g.mass);
      let lx = (px - g.tgt[0]) * k, ly = (py - g.tgt[1]) * k, lz = (pz - g.tgt[2]) * k;
      const ll = Math.sqrt(lx * lx + ly * ly + lz * lz);
      const maxL = maxF * dt * dt / g.mass;         // force cap
      if (ll > maxL) { const sc = maxL / ll; lx *= sc; ly *= sc; lz *= sc; }
      g.force = Math.min(ll, maxL) * g.mass / (dt * dt);
      const idx = g.idx, wt = g.wt;
      for (let q = 0, cnt = g.count; q < cnt; q++) {
        const i3 = idx[q] * 3, f = wt[q];
        x[i3] += f * lx; x[i3 + 1] += f * ly; x[i3 + 2] += f * lz;
      }
    }
  }

  // ---- damping -------------------------------------------------------------------

  /**
   * Shape-aware damping. With c, v_c, omega the best-fit rigid motion and R the
   * best-fit rotation of the home pose onto the current pose:
   *   - the deviation of each particle's velocity from the rigid motion is damped
   *     (rigid motion itself is left alone),
   *   - the speed at which a particle may travel back towards its place in the
   *     undeformed shape is capped. Stretching is not resisted, only the recoil
   *     is: a released stretch comes back at a gentle, bounded speed and then
   *     overshoots and wobbles freely at small amplitude.
   */
  _dampRigid() {
    const kd = this.rigidDampK;
    const n = this.n, x = this.x, v = this.v, mass = this.mass, M = this.totalMass, rest = this.rest;
    let cx = 0, cy = 0, cz = 0, px = 0, py = 0, pz = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, mi = mass[i];
      cx += mi * x[i3]; cy += mi * x[i3 + 1]; cz += mi * x[i3 + 2];
      px += mi * v[i3]; py += mi * v[i3 + 1]; pz += mi * v[i3 + 2];
    }
    cx /= M; cy /= M; cz /= M; px /= M; py /= M; pz /= M;
    const hc = this.homeCom, hx = hc[0], hy = hc[1], hz = hc[2];
    let Lx = 0, Ly = 0, Lz = 0, ixx = 0, iyy = 0, izz = 0, ixy = 0, ixz = 0, iyz = 0;
    let a00 = 0, a01 = 0, a02 = 0, a10 = 0, a11 = 0, a12 = 0, a20 = 0, a21 = 0, a22 = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, mi = mass[i];
      const rx = x[i3] - cx, ry = x[i3 + 1] - cy, rz = x[i3 + 2] - cz;
      const ux = v[i3], uy = v[i3 + 1], uz = v[i3 + 2];
      Lx += mi * (ry * uz - rz * uy); Ly += mi * (rz * ux - rx * uz); Lz += mi * (rx * uy - ry * ux);
      ixx += mi * (ry * ry + rz * rz); iyy += mi * (rx * rx + rz * rz); izz += mi * (rx * rx + ry * ry);
      ixy -= mi * rx * ry; ixz -= mi * rx * rz; iyz -= mi * ry * rz;
      const qx = mi * (rest[i3] - hx), qy = mi * (rest[i3 + 1] - hy), qz = mi * (rest[i3 + 2] - hz);
      a00 += rx * qx; a01 += rx * qy; a02 += rx * qz;
      a10 += ry * qx; a11 += ry * qy; a12 += ry * qz;
      a20 += rz * qx; a21 += rz * qy; a22 += rz * qz;
    }
    // omega = I^-1 L (symmetric 3x3)
    const c00 = iyy * izz - iyz * iyz, c01 = ixz * iyz - ixy * izz, c02 = ixy * iyz - ixz * iyy;
    const det = ixx * c00 + ixy * c01 + ixz * c02;
    if (!(det > 1e-30)) return;
    const id = 1 / det;
    const c11 = ixx * izz - ixz * ixz, c12 = ixy * ixz - ixx * iyz, c22 = ixx * iyy - ixy * ixy;
    const wx = (c00 * Lx + c01 * Ly + c02 * Lz) * id;
    const wy = (c01 * Lx + c11 * Ly + c12 * Lz) * id;
    const wz = (c02 * Lx + c12 * Ly + c22 * Lz) * id;
    // a free body must not fly or spin off stage: bound its rigid motion
    if (this.mode !== MODE_STUCK) {
      const P0 = this.params;
      const sp2 = px * px + py * py + pz * pz, w2 = wx * wx + wy * wy + wz * wz;
      let kv = 0, kw = 0;
      if (this.grabCount === 0 && sp2 > P0.maxFlightSpeed * P0.maxFlightSpeed) kv = 1 - P0.maxFlightSpeed / Math.sqrt(sp2);
      if (w2 > P0.maxSpin * P0.maxSpin) kw = 1 - P0.maxSpin / Math.sqrt(w2);
      if (kv > 0 || kw > 0) {
        const ax = kv * px, ay = kv * py, az = kv * pz, bx = kw * wx, by = kw * wy, bz = kw * wz;
        for (let i = 0; i < n; i++) {
          const i3 = i * 3;
          const rx = x[i3] - cx, ry = x[i3 + 1] - cy, rz = x[i3 + 2] - cz;
          v[i3] -= ax + by * rz - bz * ry; v[i3 + 1] -= ay + bz * rx - bx * rz; v[i3 + 2] -= az + bx * ry - by * rx;
        }
        px -= ax; py -= ay; pz -= az;
      }
      if (kw > 0) { this._spinScale = 1 - kw; } else this._spinScale = 1;
    } else this._spinScale = 1;
    const wsc = this._spinScale;
    const wxs = wx * wsc, wys = wy * wsc, wzs = wz * wsc;
    // best-fit rotation, warm started from the previous substep
    const q = this._fitQuat, R = this._fitMat;
    polarIterate(q, R, a00, a01, a02, a10, a11, a12, a20, a21, a22, 2);
    const r00 = R[0], r01 = R[1], r02 = R[2], r10 = R[3], r11 = R[4], r12 = R[5], r20 = R[6], r21 = R[7], r22 = R[8];
    // Reference frame: while the base is stuck it is the plate (world frame,
    // home pose); for a free body it is the rigidly fitted shape moving with the
    // body. There both ends close in on each other, so each gets half the speed.
    const P = this.params;
    const b = this.mode === MODE_STUCK ? this.stick : 0, nb = 1 - b, stuck = b > 0.5;
    const vret = this.returnSpeed * (0.5 + 0.5 * b) * (this.grabCount > 0 ? P.returnHeldFactor : 1);
    const dt = this.substepDt, keep = 1 - kd;
    const D = this._dev, G = this._gate;
    let ke = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3;
      const rx = x[i3] - cx, ry = x[i3 + 1] - cy, rz = x[i3 + 2] - cz;
      // velocity relative to the reference frame
      const dx = v[i3] - nb * (px + wys * rz - wzs * ry), dy = v[i3 + 1] - nb * (py + wzs * rx - wxs * rz), dz = v[i3 + 2] - nb * (pz + wxs * ry - wys * rx);
      D[i3] = dx; D[i3 + 1] = dy; D[i3 + 2] = dz;
      // displacement from this particle's place in the undeformed shape
      const qx = rest[i3] - hx, qy = rest[i3 + 1] - hy, qz = rest[i3 + 2] - hz;
      const ux = b * (x[i3] - rest[i3]) + nb * (rx - (r00 * qx + r01 * qy + r02 * qz));
      const uy = b * (x[i3 + 1] - rest[i3 + 1]) + nb * (ry - (r10 * qx + r11 * qy + r12 * qz));
      const uz = b * (x[i3 + 2] - rest[i3 + 2]) + nb * (rz - (r20 * qx + r21 * qy + r22 * qz));
      const ul2 = ux * ux + uy * uy + uz * uz;
      // which motion counts as "the shape coming back": stuck, any motion away
      // from the rest shape; free, only motion heading back (a landing has to be
      // able to squash at the speed it arrives with)
      let g = 0;
      if (ul2 > 4e-4 && (stuck || dx * ux + dy * uy + dz * uz < 0)) g = ul2 < 0.0064 ? (Math.sqrt(ul2) - 0.02) / 0.06 : 1;
      G[i] = g;
      if (g > 0) ke += g * mass[i] * (dx * dx + dy * dy + dz * dz);
    }
    // (1) the kinetic energy of the returning motion is bounded: all of it is
    //     scaled down together, so the shape of the motion (and with it the
    //     wobble that follows) survives; (2) no single particle snaps back much
    //     faster than that.
    ke *= 0.5 * keep * keep;
    const vr = vret * P.returnRms, keMax = 0.5 * M * vr * vr;
    const sg = ke > keMax ? Math.sqrt(keMax / ke) : 1;
    const vloc = vret * P.returnLocal, vloc2 = vloc * vloc;
    let dpx = 0, dpy = 0, dpz = 0;
    for (let i = 0; i < n; i++) {
      const i3 = i * 3, g = G[i];
      const dx = D[i3], dy = D[i3 + 1], dz = D[i3 + 2];
      let ex = dx * keep, ey = dy * keep, ez = dz * keep;          // linear damping
      if (g > 0) {
        let k = 1 - g * (1 - sg);
        const sp2 = (ex * ex + ey * ey + ez * ez) * k * k;
        if (sp2 > vloc2) k *= 1 - g * (1 - vloc / Math.sqrt(sp2));
        if (k < 1) {
          const cxx = (k - 1) * ex, cyy = (k - 1) * ey, czz = (k - 1) * ez, m = mass[i];
          ex += cxx; ey += cyy; ez += czz;
          dpx += m * cxx; dpy += m * cyy; dpz += m * czz;
          // take the excess out of this substep's motion as well, so the cap
          // holds no matter how hard the stretched material pulls
          x[i3] += cxx * dt; x[i3 + 2] += czz * dt;
          const ny = x[i3 + 1] + cyy * dt;
          x[i3 + 1] = ny < 0 ? 0 : ny;
        }
      }
      v[i3] += ex - dx; v[i3 + 1] += ey - dy; v[i3 + 2] += ez - dz;
    }
    // for a free body the cap must not push the body as a whole
    if (nb > 0 && (dpx !== 0 || dpy !== 0 || dpz !== 0)) {
      dpx *= nb / M; dpy *= nb / M; dpz *= nb / M;
      for (let i3 = 0, n3 = n * 3; i3 < n3; i3 += 3) { v[i3] -= dpx; v[i3 + 1] -= dpy; v[i3 + 2] -= dpz; }
    }
    // Bottom-heavy: a slice that has been let go rights itself a little, in the
    // air and on the ground, so it tends to land on its cut face and rock
    // upright instead of falling flat. (r01, r11, r21) is its current "up".
    if (this.mode === MODE_FREE && this.grabCount === 0 && P.righting > 0) {
      let tx = -r21, tz = r01;                                   // up x world-up, |.| = sin(tilt)
      if (r11 < 0) { const l = Math.sqrt(tx * tx + tz * tz); if (l > 1e-6) { tx /= l; tz /= l; } else { tx = 1; tz = 0; } }   // past horizontal: full strength
      const ax = (P.righting * tx - P.rightingDamp * wxs) * dt, az = (P.righting * tz - P.rightingDamp * wzs) * dt;
      for (let i = 0; i < n; i++) {
        const i3 = i * 3;
        const rx = x[i3] - cx, ry = x[i3 + 1] - cy, rz = x[i3 + 2] - cz;
        // v += alpha x r, alpha = (ax, 0, az)
        v[i3] += -az * ry; v[i3 + 1] += az * rx - ax * rz; v[i3 + 2] += ax * ry;
      }
    }
  }

  /** Strain-rate damping along edges (stiffness proportional: fast ripples die first). */
  _dampEdges() {
    const x = this.x, v = this.v, ed = this.edges;
    const F = this.edgeF, wA = this.edgeWA;
    // every other edge per substep (the coefficients are for two substeps)
    for (let e = this.steps & 1, ne = this.numEdges; e < ne; e += 2) {
      const a3 = ed[e * 2] * 3, b3 = ed[e * 2 + 1] * 3;
      const dx = x[b3] - x[a3], dy = x[b3 + 1] - x[a3 + 1], dz = x[b3 + 2] - x[a3 + 2];
      const l2 = dx * dx + dy * dy + dz * dz;
      if (l2 < 1e-18) continue;
      const dot = (v[b3] - v[a3]) * dx + (v[b3 + 1] - v[a3 + 1]) * dy + (v[b3 + 2] - v[a3 + 2]) * dz;
      const k = -F[e] * dot / l2, ka = k * wA[e], kb = k - ka;
      v[a3] -= ka * dx; v[a3 + 1] -= ka * dy; v[a3 + 2] -= ka * dz;
      v[b3] += kb * dx; v[b3 + 1] += kb * dy; v[b3 + 2] += kb * dz;
    }
  }

  // ======================================================================
  // sag-free rest shape
  // ======================================================================

  /**
   * Find the stress-free shape whose equilibrium under gravity is the home
   * pose: relax the real solver from the home pose and subtract what it sagged
   * (one step of a fixed-point iteration, second-order accurate). The slow
   * correction in _adaptSag() removes what is left while the slice sits still.
   */
  _calibrateSag() {
    const P = this.params, n3 = this.n * 3, sagA = this.sagA, scale = this.stiffnessScale;
    this._calibrating = true;
    this._calibPhi = Math.pow(12 * this.substepDt, 2);
    this._syncFriction();
    sagA.fill(0); this.sagB.fill(0);
    const iters = P.calibrateIters || 2;
    for (let it = 0; it < iters; it++) {
      this._rebuildRest();
      this._relax(it === 0 ? (P.calibrateSeconds || 0.7) : 0.5);
      for (let i = 0; i < n3; i++) sagA[i] += (this.x[i] - this.rest[i]) * scale;
    }
    this._calibrating = false;
    this._refresh();
    this._syncFriction();
  }

  /** Relax from the home pose towards static equilibrium (calibration only). */
  _relax(seconds) {
    const n3 = this.n * 3, x = this.x, v = this.v, xp = this.xp, rest = this.rest;
    for (let i = 0; i < n3; i++) { x[i] = rest[i]; xp[i] = rest[i]; v[i] = 0; }
    this._clearLimits();
    this._setFrameHome();
    this.mode = MODE_STUCK; this.tether = 1; this.stick = 1; this.ramp = 1;
    // roughly critical damping of the slowest mode
    this._calibDrag = 2 * 2 * Math.PI * (this.params.calibrateHz || 1.4) * Math.sqrt(this.stiffnessScale);
    const steps = Math.ceil(seconds / this.substepDt);
    for (let s = 0; s < steps; s++) this._substep();
  }

  /**
   * Integral correction of the stress-free shape: while the slice sits stuck,
   * untouched and quiet, whatever small offset from the home pose remains is
   * slowly folded into the sag, so "at rest" always means exactly mesh.rest,
   * at every firmness.
   */
  _adaptSag() {
    if (this.mode !== MODE_STUCK || this.grabCount > 0 || this.stick < 0.999) { this._sagCount = -1; this._sagTick = 0; this._calm = 0; this._sagDone = false; return; }
    if (++this._sagTick < this._sagEvery) return;
    this._sagTick = 0;
    const n3 = this.n * 3, v = this.v, x = this.x, rest = this.rest, acc = this._sagAcc;
    // average the offset from home over a window that spans the slowest wobble
    let m2 = 0, d2 = 0;
    for (let i = 0; i < n3; i += 3) {
      const s2 = v[i] * v[i] + v[i + 1] * v[i + 1] + v[i + 2] * v[i + 2];
      if (s2 > m2) m2 = s2;
      const dx = x[i] - rest[i], dy = x[i + 1] - rest[i + 1], dz = x[i + 2] - rest[i + 2];
      const q = dx * dx + dy * dy + dz * dz;
      if (q > d2) d2 = q;
    }
    if (m2 > 1.44e-4 || d2 > 0.0025) { this._sagCount = -1; this._calm = 0; return; }  // still wobbling (> 0.012 u/s) or far from home (> 0.05)
    // completely still and nothing left to correct: stop simulating until something happens
    if (m2 < 1e-6 && this._sagDone) { if (++this._calm > 20 && this.params.allowSleep) this.sleeping = true; } else this._calm = 0;
    if (this._sagCount < 0) { this._sagCount = 0; for (let i = 0; i < n3; i++) acc[i] = 0; return; }   // one sample of settling first
    for (let i = 0; i < n3; i++) acc[i] += x[i] - rest[i];
    if (++this._sagCount < this._sagWindow) return;
    const eta = this.params.sagAdapt / this._sagCount, sagA = this.sagA, sagB = this.sagB;
    let big = 0;
    for (let i = 0; i < n3; i++) { const q = acc[i] * eta; if (q > big) big = q; else if (-q > big) big = -q; }
    this._sagCount = -1;
    this._sagDone = big < 5e-5;
    if (big < 2e-6) return;                                           // converged
    // smallest change of (sagA, sagB) that applies the whole correction at this firmness
    const inv = 1 / this.stiffnessScale, ka = inv / (inv * inv + 1), kb = 1 / (inv * inv + 1);
    for (let i = 0; i < n3; i++) {
      const q = acc[i] * eta;
      let a = sagA[i] + q * ka, b = sagB[i] + q * kb;
      if (a > 0.2) a = 0.2; else if (a < -0.2) a = -0.2;
      if (b > 0.1) b = 0.1; else if (b < -0.1) b = -0.1;
      sagA[i] = a; sagB[i] = b;
    }
    this._rebuildRest();
  }
}

function tetVolume(p, a, b, c, d) {
  const a3 = a * 3, b3 = b * 3, c3 = c * 3, d3 = d * 3;
  const ax = p[a3], ay = p[a3 + 1], az = p[a3 + 2];
  const bx = p[b3] - ax, by = p[b3 + 1] - ay, bz = p[b3 + 2] - az;
  const cx = p[c3] - ax, cy = p[c3 + 1] - ay, cz = p[c3 + 2] - az;
  const dx = p[d3] - ax, dy = p[d3 + 1] - ay, dz = p[d3 + 2] - az;
  return (bx * (cy * dz - cz * dy) - by * (cx * dz - cz * dx) + bz * (cx * dy - cy * dx)) / 6;
}

/**
 * Rotation part of A (row-major entries a00..a22) by the iteration of
 * Mueller et al. 2016, starting from quaternion q; leaves the matrix in R.
 */
function polarIterate(q, R, a00, a01, a02, a10, a11, a12, a20, a21, a22, iters) {
  for (let it = 0; it < iters; it++) {
    quatToMat(q, R);
    const ox = (R[3] * a20 - R[6] * a10) + (R[4] * a21 - R[7] * a11) + (R[5] * a22 - R[8] * a12);
    const oy = (R[6] * a00 - R[0] * a20) + (R[7] * a01 - R[1] * a21) + (R[8] * a02 - R[2] * a22);
    const oz = (R[0] * a10 - R[3] * a00) + (R[1] * a11 - R[4] * a01) + (R[2] * a12 - R[5] * a02);
    const den = Math.abs(R[0] * a00 + R[3] * a10 + R[6] * a20 + R[1] * a01 + R[4] * a11 + R[7] * a21 + R[2] * a02 + R[5] * a12 + R[8] * a22) + 1e-9;
    let wx = ox / den, wy = oy / den, wz = oz / den;
    let wl = Math.sqrt(wx * wx + wy * wy + wz * wz);
    if (it === 0 && wl < 1e-7 && (R[0] * a00 + R[3] * a10 + R[6] * a20 + R[1] * a01 + R[4] * a11 + R[7] * a21 + R[2] * a02 + R[5] * a12 + R[8] * a22) < 0) { wx = 0.3; wy = 0.9; wz = 0.2; wl = Math.hypot(wx, wy, wz); }  // exactly opposite: step off the saddle
    if (!(wl > 1e-10)) break;
    const half = wl * 0.5, sn = Math.sin(half) / wl, cs = Math.cos(half);
    const rx = wx * sn, ry = wy * sn, rz = wz * sn;
    const nx = cs * q[0] + rx * q[3] + ry * q[2] - rz * q[1];
    const ny = cs * q[1] + ry * q[3] + rz * q[0] - rx * q[2];
    const nz = cs * q[2] + rz * q[3] + rx * q[1] - ry * q[0];
    const nw = cs * q[3] - rx * q[0] - ry * q[1] - rz * q[2];
    const nl = 1 / Math.sqrt(nx * nx + ny * ny + nz * nz + nw * nw);
    q[0] = nx * nl; q[1] = ny * nl; q[2] = nz * nl; q[3] = nw * nl;
  }
  quatToMat(q, R);
  return R;
}

// quaternion (x, y, z, w) -> row-major 3x3
function quatToMat(q, R) {
  const x = q[0], y = q[1], z = q[2], w = q[3];
  R[0] = 1 - 2 * (y * y + z * z); R[1] = 2 * (x * y - z * w); R[2] = 2 * (x * z + y * w);
  R[3] = 2 * (x * y + z * w); R[4] = 1 - 2 * (x * x + z * z); R[5] = 2 * (y * z - x * w);
  R[6] = 2 * (x * z - y * w); R[7] = 2 * (y * z + x * w); R[8] = 1 - 2 * (x * x + y * y);
  return R;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { JellySim, SIM_MESH_OPTIONS, DEFAULT_PARAMS };
}
