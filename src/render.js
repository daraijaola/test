'use strict';
/*
 * render.js — WebGPU renderer for the gummy citrus slice (all WGSL lives here).
 *
 * The renderer owns everything drawn in the canvas: the cream backdrop, the
 * ground with its contact shadow, the translucent slice and the mesh overlay.
 *
 * Frame graph (every pass is driven by the CURRENT deformed particle positions):
 *
 *   1. shadow raster   the refined surface is projected along the key light onto
 *                      the ground (512², seen from below) keeping the lowest
 *                      occluder; its height is turned into contact / low / high
 *                      occlusion weights.
 *   2. blur chain      4 progressively smaller + wider Gaussian levels, so the
 *                      ground can mix a tight contact shadow with ever softer
 *                      penumbrae (height-dependent softness without a big kernel).
 *   3. back faces      material coordinate + distance of the exit point of every
 *                      view ray, into an rgba16float target.
 *   4. main (MSAA 4x)  backdrop + ground, then the front faces of the slice: the
 *                      fragment shader marches the straight segment between the
 *                      entry and the (slightly refracted) exit point IN MATERIAL
 *                      SPACE through a procedural field (segments, membranes,
 *                      pith, rind, vesicles) accumulating absorption and
 *                      in-scattered studio light, adds analytic bubbles, lets the
 *                      refracted ground show through and finishes with a soft
 *                      Fresnel reflection of a procedural softbox studio.
 *                      Finally the optional simulation-mesh overlay.
 *
 * Geometry: the simulation surface is coarse, so every surface triangle is
 * subdivided (K×K) once at start-up. The refined vertices only store "corner
 * particle indices + barycentrics + material coordinate"; the vertex shader
 * pulls the live particle positions / smooth normals from a storage buffer and
 * applies Phong tessellation, so per frame the CPU only uploads n particles.
 *
 * Colour: everything is shaded in linear sRGB; the fragment shaders apply the
 * sRGB transfer themselves and write to the plain preferred canvas format
 * (sRGB *view formats* of the canvas are not honoured by every backend). The
 * backdrop is exactly the page colour; only the slice goes through a soft
 * highlight shoulder.
 *
 * Per frame the CPU does: smooth normals (surface triangles), a best-fit body
 * frame, one particle upload and one uniform upload — no allocations.
 *
 * Look-dev aid: renderer.debugView = 1 scattered light, 2 transmitted backdrop,
 * 3 reflection, 4 normals, 5 thickness, 6 transmittance (0 = final image).
 */

const SHADOW_RES = 512;        // base occlusion map (texels)
const SHADOW_EXTENT = 2.6;     // half size of the world-space square it covers
const SHADOW_LEVELS = 4;       // blurred levels: 256, 128, 64, 32
const NOISE_RES = 64;
const NUM_BUBBLES = 44;
const NUM_SEGMENTS = 7;
const MSAA = 4;
const PALETTE_FADE_SECONDS = 0.5;
const MIN_STEPS = 4;           // march steps per pixel: the range renderer.steps accepts
const MAX_STEPS = 22;
const QUALITY_STEPS = { low: 9, medium: 14, high: 22 };

// ───────────────────────────── palettes ─────────────────────────────
// All colours are LINEAR rgb. "abs" = absorption per world unit (Beer–Lambert),
// density = scattering per world unit, "sca" = colour of the scattered light,
// "deep" = attenuation of the light that feeds the scattering as it travels
// into the body, "shadow" = how the ground shadow absorbs (tints) the light.
const PALETTES = {
  orange: {
    fleshAbs: [0.30, 3.2, 9.0], fleshDensity: 0.38,
    fleshSca: [1.00, 0.60, 0.10], mottle: 0.25,
    fleshAbs2: [0.42, 4.0, 9.5], vesicle: 1.0,
    memAbs: [0.06, 0.14, 0.42], memDensity: 13.0,
    memSca: [0.93, 0.79, 0.56],
    rindAbs: [0.25, 3.4, 12.0], rindDensity: 11.0,
    rindSca: [1.00, 0.34, 0.02],
    deep: [0.50, 3.2, 8.0],
    shadow: [0.02, 0.75, 2.2], shadowStrength: 1.0,
    lineHot: [1.0, 0.16, 0.30],
  },
  blood: {
    fleshAbs: [4.2, 16.0, 10.0], fleshDensity: 0.42,
    fleshSca: [0.72, 0.015, 0.05], mottle: 0.85,
    fleshAbs2: [1.1, 6.0, 8.5], vesicle: 1.0,
    memAbs: [0.07, 0.30, 0.48], memDensity: 13.0,
    memSca: [0.93, 0.70, 0.56],
    rindAbs: [0.28, 4.4, 11.0], rindDensity: 11.0,
    rindSca: [1.00, 0.20, 0.03],
    deep: [1.8, 7.0, 7.0],
    shadow: [0.16, 1.45, 1.6], shadowStrength: 1.0,
    lineHot: [1.0, 0.86, 0.25],
  },
  lemon: {
    fleshAbs: [0.24, 0.80, 6.5], fleshDensity: 0.40,
    fleshSca: [0.93, 0.86, 0.20], mottle: 0.2,
    fleshAbs2: [0.20, 0.55, 7.0], vesicle: 1.0,
    memAbs: [0.05, 0.08, 0.36], memDensity: 13.0,
    memSca: [0.90, 0.845, 0.64],
    rindAbs: [0.10, 1.0, 9.0], rindDensity: 11.0,
    rindSca: [1.00, 0.66, 0.035],
    deep: [0.25, 0.75, 5.0],
    shadow: [0.03, 0.28, 1.8], shadowStrength: 0.92,
    lineHot: [1.0, 0.18, 0.32],
  },
};
const PALETTE_FLOATS = 40;     // 10 vec4

function packPalette(p, out) {
  let o = 0;
  const v4 = (v, w) => { out[o++] = v[0]; out[o++] = v[1]; out[o++] = v[2]; out[o++] = w; };
  v4(p.fleshAbs, p.fleshDensity);
  v4(p.fleshSca, p.mottle);
  v4(p.fleshAbs2, p.vesicle);
  v4(p.memAbs, p.memDensity);
  v4(p.memSca, 0);
  v4(p.rindAbs, p.rindDensity);
  v4(p.rindSca, 0);
  v4(p.deep, 0);
  v4(p.shadow, p.shadowStrength);
  v4(p.lineHot, 0);
  return out;
}

// ───────────────────────────── studio lighting ─────────────────────────────
function norm3(v) { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
function cross3(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function lightFrame(dir) {
  const d = norm3(dir);
  const tx = norm3(cross3([0, 1, 0], d));
  const ty = cross3(d, tx);
  return { d, tx, ty };
}
// key: large softbox behind / above / left of the subject (back light makes the
// jelly glow and throws the shadow towards the viewer); fill: very large soft
// panel in front; top: overhead strip.
const KEY = lightFrame([-0.50, 0.80, -0.45]);
const FILL = lightFrame([-0.42, 0.20, 0.88]);
const TOP = lightFrame([0.12, 1.0, 0.22]);
// the ground shadow is cast along the key light, shortened for composition
const SHADOW_SHEAR = [0.36, 0.34];

const f = (x) => { const s = Number(x).toFixed(6); return s.indexOf('.') < 0 ? s + '.0' : s; };
const v3 = (v) => `vec3f(${f(v[0])}, ${f(v[1])}, ${f(v[2])})`;

// ───────────────────────────── WGSL ─────────────────────────────
function wgslGlobals() {
  return /* wgsl */`
const PI = 3.14159265358979;

struct Globals {
  viewProj: mat4x4f,
  eye: vec4f,        // xyz eye, w = reference distance (eye -> target) for the relative depth encoding
  rayF: vec4f,       // xyz: ray basis (forward incl. principal point shift), w = time
  rayR: vec4f,       // xyz: right * tan * aspect, w = viewport width  (px)
  rayU: vec4f,       // xyz: up * tan,             w = viewport height (px)
  camR: vec4f,       // xyz: camera right, w = pixels per world unit at distance 1
  camU: vec4f,       // xyz: camera up,    w = overlay line half width (px)
  bodyX: vec4f,      // world directions of the material axes (best rigid fit of the body)
  bodyY: vec4f,
  bodyZ: vec4f,
  shadow: vec4f,     // xy: centre of the shadow map (world xz), z: 1 / half extent
  shear: vec4f,      // xy: ground offset per unit height along the key light, z: debug view (0 = off), w: march steps
  bg: vec4f,         // backdrop colour (linear), w = dither amplitude
  fleshAbs: vec4f,   // rgb absorption, w scattering density
  fleshSca: vec4f,   // rgb scatter colour, w mottle amount
  fleshAbs2: vec4f,  // rgb second absorption (mottling), w vesicle strength
  memAbs: vec4f,     // membranes / pith: rgb absorption, w density
  memSca: vec4f,
  rindAbs: vec4f,
  rindSca: vec4f,
  deep: vec4f,       // attenuation of the light feeding the scattering
  shadowTint: vec4f, // rgb absorption of the ground shadow, w strength
  lineHot: vec4f,    // overlay accent colour
};
@group(0) @binding(0) var<uniform> G: Globals;
`;
}

function wgslGeometry(c) {
  return /* wgsl */`
struct Particle { pos: vec4f, nrm: vec4f };   // pos.w = tension, nrm = smooth surface normal (0 inside)
@group(0) @binding(1) var<storage, read> particles: array<Particle>;

struct SurfPoint { p: vec3f, n: vec3f };

// Phong tessellation: project the flat point onto the tangent planes of the
// three corner particles and blend — rounds the coarse simulation surface.
fn surfPoint(idx: vec3u, bary: vec2f) -> SurfPoint {
  let b = vec3f(1.0 - bary.x - bary.y, bary.x, bary.y);
  let A = particles[idx.x];
  let B = particles[idx.y];
  let C = particles[idx.z];
  let p = A.pos.xyz * b.x + B.pos.xyz * b.y + C.pos.xyz * b.z;
  let qa = p - dot(p - A.pos.xyz, A.nrm.xyz) * A.nrm.xyz;
  let qb = p - dot(p - B.pos.xyz, B.nrm.xyz) * B.nrm.xyz;
  let qc = p - dot(p - C.pos.xyz, C.nrm.xyz) * C.nrm.xyz;
  var ps = mix(p, qa * b.x + qb * b.y + qc * b.z, ${f(c.phongAlpha)});
  ps.y = max(ps.y, 0.0);                       // never bulge through the ground
  let n = A.nrm.xyz * b.x + B.nrm.xyz * b.y + C.nrm.xyz * b.z;
  var o: SurfPoint;
  o.p = ps;
  o.n = n / max(length(n), 1e-6);
  return o;
}
`;
}

function wgslShadowRaster(c) {
  return wgslGlobals() + wgslGeometry(c) + /* wgsl */`
struct ShOut { @builtin(position) clip: vec4f, @location(0) h: f32 };

@vertex
fn vs(@location(0) idx: vec3u, @location(1) bary: vec2f) -> ShOut {
  let s = surfPoint(idx, bary);
  let g = s.p.xz + G.shear.xy * s.p.y;                  // slide down the key light onto the ground
  let q = (g - G.shadow.xy) * G.shadow.z;
  var o: ShOut;
  o.clip = vec4f(q.x, q.y, clamp(s.p.y * 0.2, 0.0, 1.0), 1.0);   // depth = height: keep the lowest occluder
  o.h = s.p.y;
  return o;
}

@fragment
fn fs(in: ShOut) -> @location(0) vec4f {
  let h = max(in.h, 0.0);
  // r: touching the ground, g: close to it, b: anywhere up to slice height, a: coverage
  return vec4f(exp(-h / 0.030), exp(-h / 0.20), exp(-h / 0.95), 1.0);
}
`;
}

const WGSL_BLUR = /* wgsl */`
struct BlurU { dir: vec4f };
@group(0) @binding(0) var<uniform> U: BlurU;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var smp: sampler;

struct FsIn { @builtin(position) clip: vec4f, @location(0) uv: vec2f };

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> FsIn {
  let p = vec2f(f32((vi << 1u) & 2u), f32(vi & 2u)) * 2.0 - 1.0;
  var o: FsIn;
  o.clip = vec4f(p, 0.0, 1.0);
  o.uv = vec2f(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5);
  return o;
}

// 9-tap Gaussian folded into 5 bilinear fetches
@fragment
fn fs(in: FsIn) -> @location(0) vec4f {
  let d = U.dir.xy;
  var c = textureSampleLevel(src, smp, in.uv, 0.0) * 0.2270270270;
  c += (textureSampleLevel(src, smp, in.uv + d * 1.3846153846, 0.0)
      + textureSampleLevel(src, smp, in.uv - d * 1.3846153846, 0.0)) * 0.3162162162;
  c += (textureSampleLevel(src, smp, in.uv + d * 3.2307692308, 0.0)
      + textureSampleLevel(src, smp, in.uv - d * 3.2307692308, 0.0)) * 0.0702702703;
  return c;
}
`;

function wgslBack(c) {
  return wgslGlobals() + wgslGeometry(c) + /* wgsl */`
struct BkOut { @builtin(position) clip: vec4f, @location(0) world: vec3f, @location(1) mat: vec3f };

@vertex
fn vs(@location(0) idx: vec3u, @location(1) bary: vec2f, @location(2) mat: vec3f) -> BkOut {
  let s = surfPoint(idx, bary);
  var o: BkOut;
  o.clip = G.viewProj * vec4f(s.p, 1.0);
  o.world = s.p;
  o.mat = mat;
  return o;
}

// exit point of the view ray: material coordinate + distance from the eye
// (stored relative to the eye->target distance to stay precise in 16 bit float)
@fragment
fn fs(in: BkOut) -> @location(0) vec4f {
  return vec4f(in.mat, length(in.world - G.eye.xyz) - G.eye.w);
}
`;
}

// Shared by the backdrop and the slice: studio, ground, shadow.
function wgslScene(c) {
  return /* wgsl */`
@group(1) @binding(0) var linSmp: sampler;
@group(1) @binding(1) var noiseSmp: sampler;
@group(1) @binding(2) var noiseTex: texture_3d<f32>;
@group(1) @binding(3) var sh1: texture_2d<f32>;
@group(1) @binding(4) var sh2: texture_2d<f32>;
@group(1) @binding(5) var sh3: texture_2d<f32>;
@group(1) @binding(6) var sh4: texture_2d<f32>;

const KEY_DIR = ${v3(KEY.d)};
const KEY_TX = ${v3(KEY.tx)};
const KEY_TY = ${v3(KEY.ty)};
const FILL_DIR = ${v3(FILL.d)};
const FILL_TX = ${v3(FILL.tx)};
const FILL_TY = ${v3(FILL.ty)};
const TOP_DIR = ${v3(TOP.d)};
const TOP_TX = ${v3(TOP.tx)};
const TOP_TY = ${v3(TOP.ty)};
const KEY_COL = vec3f(1.0, 0.975, 0.93);
const FILL_COL = vec3f(0.97, 0.985, 1.0);

fn ign(p: vec2f) -> f32 {
  return fract(52.9829189 * fract(dot(p, vec2f(0.06711056, 0.00583715))));
}

// linear -> display (sRGB transfer) with a +-half-LSB dither against banding
fn toDisplay(c: vec3f, fragCoord: vec2f) -> vec4f {
  let x = clamp(c, vec3f(0.0), vec3f(1.0));
  let lo = x * 12.92;
  let hi = 1.055 * pow(x, vec3f(1.0 / 2.4)) - vec3f(0.055);
  let e = select(hi, lo, x <= vec3f(0.0031308));
  return vec4f(e + vec3f((ign(fragCoord) - 0.5) * G.bg.w), 1.0);
}

// Multiplier applied to the ground colour at world position xz.
// cloud in [0,1] blurs the lookup; through = 1 when the ground is seen through
// the jelly itself: the ground right under it is lit by the (tinted) light that
// passed through the body, so the neutral contact core is mostly lifted.
fn groundShadow(xz: vec2f, cloud: f32, through: f32) -> vec3f {
  let q = (xz - G.shadow.xy) * G.shadow.z;
  let uv = vec2f(q.x * 0.5 + 0.5, 0.5 - q.y * 0.5);
  let edge = saturate((1.0 - max(abs(q.x), abs(q.y))) * 8.0);
  let s1 = textureSampleLevel(sh1, linSmp, uv, 0.0);
  let s2 = textureSampleLevel(sh2, linSmp, uv, 0.0);
  let s3 = textureSampleLevel(sh3, linSmp, uv, 0.0);
  let s4 = textureSampleLevel(sh4, linSmp, uv, 0.0);
  let contact = mix(s1.r, s2.r, cloud);                 // tight, only where the jelly touches
  let low = mix(s2.g, s3.g, cloud);                     // soft, close to the ground
  let high = s3.b * 0.55 + s4.b * 0.45;                 // very soft, cast by the whole slice
  let pool = s4.a;                                      // faint ambient pool
  let k = edge * G.shadowTint.w;
  // light that went through the jelly comes out tinted: the soft part of the
  // shadow absorbs like the flesh, only the contact core is neutral and dark.
  let core = (contact * 1.05 + low * 0.30 + high * 0.18) * (1.0 - 0.70 * through);
  let tinted = low * 0.45 + high * 1.10 + pool * 0.10 + contact * 0.55 * through;
  return exp(-(vec3f(1.00, 1.08, 1.16) * core + G.shadowTint.rgb * tinted) * k);
}

// Two-fetch version for blurry reflections of the ground.
fn groundShadowBlurred(xz: vec2f) -> vec3f {
  let q = (xz - G.shadow.xy) * G.shadow.z;
  let uv = vec2f(q.x * 0.5 + 0.5, 0.5 - q.y * 0.5);
  let edge = saturate((1.0 - max(abs(q.x), abs(q.y))) * 8.0);
  let s2 = textureSampleLevel(sh2, linSmp, uv, 0.0);
  let s4 = textureSampleLevel(sh4, linSmp, uv, 0.0);
  let core = s2.r * 0.85 + s2.g * 0.30 + s4.b * 0.18;
  let tinted = s2.g * 0.45 + s4.b * 1.10 + s4.a * 0.10;
  return exp(-(vec3f(1.00, 1.08, 1.16) * core + G.shadowTint.rgb * tinted) * (edge * G.shadowTint.w));
}

// Radiance seen along a ray that leaves towards the studio.
fn scene(ro: vec3f, rd: vec3f, cloud: f32, through: f32) -> vec3f {
  var col = G.bg.rgb;
  if (rd.y < -1e-4) {
    let t = max(-ro.y / rd.y, 0.0);
    let p = ro + rd * t;
    col *= groundShadow(p.xz, cloud, through);
  }
  return col;
}
`;
}

function wgslBackdrop(c) {
  return wgslGlobals() + wgslScene(c) + /* wgsl */`
struct FsIn { @builtin(position) clip: vec4f, @location(0) ndc: vec2f };

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> FsIn {
  let p = vec2f(f32((vi << 1u) & 2u), f32(vi & 2u)) * 2.0 - 1.0;
  var o: FsIn;
  o.clip = vec4f(p, 1.0, 1.0);
  o.ndc = p;
  return o;
}

@fragment
fn fs(in: FsIn) -> @location(0) vec4f {
  let rd = normalize(G.rayF.xyz + G.rayR.xyz * in.ndc.x + G.rayU.xyz * in.ndc.y);
  return toDisplay(scene(G.eye.xyz, rd, 0.0, 0.0), in.clip.xy);
}
`;
}

function wgslSlice(c) {
  return wgslGlobals() + wgslGeometry(c) + wgslScene(c) + /* wgsl */`
// bubbles are sorted by their angle around the slice centre; sec[] holds the
// first bubble of each of 16 angular sectors (+ the end) so a ray only tests
// the few bubbles that lie in the sectors it crosses
struct Bubbles { b: array<vec4f, ${c.numBubbles}>, sec: array<vec4f, 5> };
@group(1) @binding(7) var<uniform> BUB: Bubbles;
@group(2) @binding(0) var backTex: texture_2d<f32>;

const MIN_STEPS = ${MIN_STEPS};
const MAX_STEPS = ${MAX_STEPS};
const NSEG = ${f(c.segments)};
const HALF_T = ${f(c.thickness * 0.5)};
const PITH_R = ${f(c.pithR)};
const RIND_R = ${f(c.rindR)};
const CORE_R = 0.085;
// per-segment random, tabulated (the values the sin-hash produced on the reference renderer):
// sin() of large arguments is not portable between GPUs
const SEG_RND = array<f32, 7>(0.270020, 0.628906, 0.507813, 0.671875, 0.078125, 0.729492, 0.286133);
const MEM_HALF = 0.0075;
const SEG_ROUND = 0.050;
const IOR = 1.36;
const REFRACT_GAIN = 0.9;      // share of the ideal slab offset that is applied (the body is cloudy, not clear)
const SHEEN_COL = vec3f(1.0, 0.94, 0.82);     // the key light as the waxy skin of the rind gives it back

struct VsOut {
  @builtin(position) clip: vec4f,
  @location(0) world: vec3f,
  @location(1) normal: vec3f,
  @location(2) mat: vec3f,
};

@vertex
fn vs(@location(0) idx: vec3u, @location(1) bary: vec2f, @location(2) mat: vec3f) -> VsOut {
  let s = surfPoint(idx, bary);
  var o: VsOut;
  o.clip = G.viewProj * vec4f(s.p, 1.0);
  o.world = s.p;
  o.normal = s.n;
  o.mat = mat;
  return o;
}

// ---------------------------------------------------------------- lighting
// Diffuse studio irradiance on a surface with normal n (soft, low contrast).
fn irradiance(n: vec3f) -> vec3f {
  var e = G.bg.rgb * mix(0.22, 0.42, n.y * 0.5 + 0.5);           // cream room: floor bounce .. ceiling
  let k = max((dot(n, KEY_DIR) + 0.40) / 1.40, 0.0);
  e += KEY_COL * (0.75 * k * k);
  let fl = max((dot(n, FILL_DIR) + 0.65) / 1.65, 0.0);
  e += FILL_COL * (0.22 * fl * fl);
  return e;
}

fn softbox(r: vec3f, d: vec3f, tx: vec3f, ty: vec3f, half: vec2f, feather: f32) -> f32 {
  let z = dot(r, d);
  let zz = max(z, 1e-3);
  let u = abs(dot(r, tx)) / zz;
  let v = abs(dot(r, ty)) / zz;
  let m = (1.0 - smoothstep(half.x - feather, half.x + feather, u))
        * (1.0 - smoothstep(half.y - feather, half.y + feather, v));
  return m * smoothstep(0.0, 0.25, z);
}

// Blurry reflection of the studio: cream room, the real ground (with its
// shadow) below the horizon and three softboxes with feathered edges.
fn envLight(r: vec3f, p: vec3f) -> vec3f {
  var e = G.bg.rgb * mix(0.55, 0.42, smoothstep(0.0, 0.9, r.y));
  let floorMix = 1.0 - smoothstep(-0.20, 0.06, r.y);
  if (floorMix > 0.0) {
    let rr = normalize(vec3f(r.x, min(r.y, -0.06), r.z));
    let hit = p + rr * (max(p.y, 0.0) / -rr.y);
    e = mix(e, G.bg.rgb * groundShadowBlurred(hit.xz) * 0.80, floorMix);
  }
  e += KEY_COL * (softbox(r, KEY_DIR, KEY_TX, KEY_TY, vec2f(0.62, 0.42), 0.34) * 3.0);
  e += FILL_COL * (softbox(r, FILL_DIR, FILL_TX, FILL_TY, vec2f(0.44, 0.17), 0.11) * 4.2
                 + softbox(r, FILL_DIR, FILL_TX, FILL_TY, vec2f(0.60, 0.30), 0.40) * 1.2);
  e += KEY_COL * (softbox(r, TOP_DIR, TOP_TX, TOP_TY, vec2f(0.90, 0.40), 0.45) * 1.0);
  return e;
}

// ---------------------------------------------------------------- material field
struct Medium {
  sa: vec3f,     // absorption
  ss: f32,       // scattering density
  col: vec3f,    // colour of the scattered light
  r: f32,
  pale: f32,     // 1 in membranes / pith
};

// Everything here is a function of the MATERIAL coordinate, so segments,
// membranes, pith, rind and vesicles are glued to the flesh and deform with it.
struct Segs {
  d: f32,        // signed distance into the nearest rounded wedge (> 0 inside the flesh)
  a: f32,        // angular coordinate, 0..NSEG
  rnd: f32,      // per-segment random
};

fn loNoise(m: vec3f) -> vec4f {
  return textureSampleLevel(noiseTex, noiseSmp, m * vec3f(0.52, 0.52, 0.22) + vec3f(0.13, 0.57, 0.31), 0.0);
}

// Radial segments: rounded wedges, gently irregular, slightly wavy through the thickness.
fn segments(m: vec3f, r: f32, lo: vec4f) -> Segs {
  let th = atan2(max(m.y, 0.0), m.x) / PI;                            // 0..1 across the half disc
  var a = th * NSEG + (lo.g - 0.5) * 0.20 * smoothstep(0.08, 0.5, r);
  a = clamp(a, 0.0005, NSEG - 0.0005);
  let seg = floor(a);
  let fr = a - seg;
  // distance to the nearest membrane; the two end segments simply run into the cut face
  let toLo = select(fr, 1.0, seg < 0.5);
  let toHi = select(1.0 - fr, 1.0, seg > NSEG - 1.5);
  let halfAng = min(min(toLo, toHi), 0.5) * (PI / NSEG);
  let dSide = r * sin(halfAng) - MEM_HALF * (0.75 + 0.6 * lo.b);
  let dOut = (PITH_R + 0.012 + (lo.a - 0.5) * 0.022) - r;
  let dIn = r - CORE_R;
  let q = max(vec3f(SEG_ROUND) - vec3f(dSide, dOut, dIn), vec3f(0.0));
  var o: Segs;
  o.d = SEG_ROUND - length(q);
  o.a = a;
  o.rnd = SEG_RND[i32(seg)];
  return o;
}

// lo = low-frequency noise at m (it varies so slowly that the march just
// interpolates it between the entry and the exit point).
fn medium(m: vec3f, soft: f32, lo: vec4f) -> Medium {
  let r = length(m.xy);
  let sg = segments(m, r, lo);
  let a = sg.a;
  let segRnd = sg.rnd;
  let flesh = smoothstep(-soft, soft, sg.d);

  // juice vesicles: faint radial streaks
  let vz = textureSampleLevel(noiseTex, noiseSmp, vec3f(a * 0.93 + segRnd * 7.0, r * 0.33 + segRnd, m.z * 1.05), 0.0);
  let ves = smoothstep(0.30, 0.72, vz.b * 0.7 + vz.a * 0.3);
  let vk = G.fleshAbs2.w;

  // mottling (blood orange) + a little variation from segment to segment
  let mot = smoothstep(0.42, 0.70, lo.r + (segRnd - 0.5) * 0.35) * G.fleshSca.w;
  let fAbs = mix(G.fleshAbs.rgb, G.fleshAbs2.rgb, mot) * mix(1.0 + 0.22 * vk, 1.0 - 0.18 * vk, ves);
  let fDen = G.fleshAbs.w * (0.92 + 0.16 * segRnd) * mix(1.0 - 0.50 * vk, 1.0 + 0.90 * vk, ves);

  // membranes are thinner / more translucent than the pith ring
  let inner = 1.0 - smoothstep(PITH_R - 0.02, PITH_R + 0.03, r);
  // (inside the body the membranes are translucent veils; where they meet the
  // two big faces they are drawn as a crisp line by the fragment shader)
  let tDen = G.memAbs.w * mix(0.50, 0.46, inner);

  let rind = smoothstep(RIND_R - 0.045, RIND_R + 0.005, r + (lo.a - 0.5) * 0.014);

  var o: Medium;
  o.sa = mix(mix(G.memAbs.rgb, fAbs, flesh), G.rindAbs.rgb, rind);
  o.ss = mix(mix(tDen, fDen, flesh), G.rindAbs.w, rind);
  // membranes take on some of the flesh colour, the pith ring stays pale
  let memCol = G.memSca.rgb * mix(vec3f(1.0), vec3f(1.04, 0.94, 0.80) * mix(vec3f(1.0), G.fleshSca.rgb, 0.15), inner);
  o.col = mix(mix(memCol, G.fleshSca.rgb, flesh), G.rindSca.rgb, rind);
  o.r = r;
  o.pale = (1.0 - flesh) * (1.0 - rind);
  return o;
}

// Very low amplitude surface relief (world units): slow waviness everywhere,
// fine pores on the rind. Evaluated in material space → sticks to the surface.
// Returns (height, segment distance at the surface point).
fn microHeight(m: vec3f, footprint: f32, lo: vec4f) -> vec2f {
  let r = length(m.xy);
  let w = textureSampleLevel(noiseTex, noiseSmp, m * 0.83 + vec3f(0.4, 0.1, 0.7), 0.0).a;
  // rind pores: small round dimples on a jittered grid over (arc length, thickness)
  let th = atan2(max(m.y, 0.0), m.x);
  let pg = vec2f(th, m.z) * 30.0;
  let cell = floor(pg);
  let hsh = fract(sin(vec2f(dot(cell, vec2f(127.1, 311.7)), dot(cell, vec2f(269.5, 183.3)))) * 43758.5453);
  let pd = length(fract(pg) - vec2f(0.5) - (hsh - vec2f(0.5)) * 0.5);
  let pores = (1.0 - smoothstep(0.10, 0.30, pd)) * step(0.25, hsh.x);
  // embossed candy: on the two big faces every segment puffs up a little,
  // leaving shallow grooves along the membranes and the pith
  let sg = segments(m, r, lo);
  let faceK = smoothstep(HALF_T - 0.07, HALF_T - 0.005, abs(m.z));
  let emboss = smoothstep(-0.012, 0.050, sg.d) * faceK;
  // (only on the outer arc, where (angle, z) is a proper parametrisation; fade before they alias)
  let poreK = smoothstep(0.972, 0.994, r) * (1.0 - smoothstep(0.005, 0.014, footprint));
  return vec2f(w * 0.0045 - pores * 0.0011 * poreK + emboss * 0.0085, sg.d);
}

fn shoulder(x: vec3f) -> vec3f {
  let a = 0.74;
  let y = max(x - vec3f(a), vec3f(0.0)) / (1.0 - a);
  return min(x, vec3f(a)) + (1.0 - a) * (1.0 - exp(-y));
}

@fragment
fn fs(in: VsOut) -> @location(0) vec4f {
  let res = vec2f(G.rayR.w, G.rayU.w);
  let pix = vec2i(in.clip.xy);
  let toEye = G.eye.xyz - in.world;
  let distA = length(toEye);
  let V = toEye / distA;
  let rd = -V;
  let mA = in.mat;

  // ---- surface normal with glued micro relief (derivatives first: uniform control flow)
  let Ng = normalize(in.normal);
  let footprint = length(dpdx(mA)) + length(dpdy(mA));
  let loA = loNoise(mA);
  let micro = microHeight(mA, footprint, loA);
  let hgt = micro.x;
  let dpx = dpdx(in.world);
  let dpy = dpdy(in.world);
  // per-pixel forward differences of the relief (screen-space derivatives of hgt are constant per 2x2 quad -> blocky)
  let dhx = microHeight(mA + dpdx(mA), footprint, loA).x - hgt;
  let dhy = microHeight(mA + dpdy(mA), footprint, loA).x - hgt;
  let r1 = cross(dpy, Ng);
  let r2 = cross(Ng, dpx);
  let det = dot(dpx, r1);
  let grad = (r1 * dhx + r2 * dhy) * sign(det);
  var N = normalize(abs(det) * Ng - grad);
  // the two big faces are shaded as if they were gently domed (pillowy candy):
  // tilt the normal away from the middle of the face, in the body's own frame
  let faceK = smoothstep(HALF_T - 0.07, HALF_T - 0.005, abs(mA.z));
  let domeDir = G.bodyX.xyz * mA.x + G.bodyY.xyz * (mA.y - 0.40);
  N = normalize(N + domeDir * (0.30 * faceK));
  N = normalize(N + V * max(0.03 - dot(N, V), 0.0));
  let NdV = saturate(dot(N, V));

  // ---- where does the ray leave the body? The back-face buffer is read where
  // the REFRACTED ray comes out. Through a slab that is beside the straight exit
  // by  chord * sin(deviation) * cos(incidence) / cos(refraction)  as seen from
  // the eye: next to nothing face-on, a good part of the thickness at a glancing
  // view. The inside therefore looks shallower than it is and slides against the
  // pattern on the surface when the camera orbits or the surface tilts and wobbles.
  let ppu = G.camR.w / distA;                                // pixels per world unit here
  let back0 = textureLoad(backTex, pix, 0);
  let valid0 = back0.a > -100.0;
  let thick0 = select(0.0, max(back0.a + G.eye.w - distA, 0.0), valid0);
  let bend = refract(rd, N, 1.0 / IOR) - rd;
  let slab = NdV / sqrt(1.0 - (1.0 - NdV * NdV) / (IOR * IOR));
  var offPx = vec2f(dot(bend, G.camR.xyz), -dot(bend, G.camU.xyz)) * (thick0 * ppu * slab * REFRACT_GAIN);
  // The relief and the dome in N may turn the offset, but not push it beyond
  // what the smooth surface gives (or 7% of a slice radius where that is less).
  let cosG = saturate(dot(Ng, V));
  let sinG = sqrt(1.0 - cosG * cosG);
  let tanT = sinG / sqrt(IOR * IOR - sinG * sinG);           // tangent of the refracted angle
  let offSmooth = thick0 * ppu * cosG * (sinG - cosG * tanT) * REFRACT_GAIN;
  let offMax = max(0.07 * G.camR.w / G.eye.w, offSmooth);
  offPx *= min(1.0, offMax / max(length(offPx), 1e-3));
  var pix1 = clamp(pix + vec2i(round(offPx)), vec2i(0), vec2i(res) - vec2i(1));
  var back = textureLoad(backTex, pix1, 0);
  var thick = back.a + G.eye.w - distA;
  if (!(back.a > -100.0) || thick <= 0.0) {                  // beside the body: come back half way first
    pix1 = clamp(pix + vec2i(round(offPx * 0.5)), vec2i(0), vec2i(res) - vec2i(1));
    back = textureLoad(backTex, pix1, 0);
    thick = back.a + G.eye.w - distA;
  }
  var pixE = vec2f(pix1) + vec2f(0.5);
  if (!(back.a > -100.0) || thick <= 0.0) {
    back = back0;
    thick = thick0;
    pixE = in.clip.xy;
  }
  var mB = back.rgb;
  if (!valid0) {
    mB = mA;
    thick = 0.0;
  }
  thick = min(thick, 3.0);

  // world-space exit point
  let ndcE = (pixE / res * 2.0 - vec2f(1.0)) * vec2f(1.0, -1.0);
  let rdE = normalize(G.rayF.xyz + G.rayR.xyz * ndcE.x + G.rayU.xyz * ndcE.y);
  let pE = G.eye.xyz + rdE * (distA + thick);

  // ---- march the straight material-space segment entry -> exit
  let nSteps = clamp(i32(G.shear.w), MIN_STEPS, MAX_STEPS);
  let fSteps = f32(nSteps);
  // one sample per step, dithered inside its step against banding. With fewer
  // (longer) steps than the default 14 the dither is narrowed towards the middle
  // of the step: the features are widened to the step anyway (soft0), and a full
  // step of dither would show its pattern as a hatch on the dense pith and rind.
  let jit = 0.5 + (ign(in.clip.xy) - 0.5) * clamp(0.15 * fSteps - 1.1, 0.25, 1.0);
  let ds = thick / fSteps;
  let dm = (mB - mA) / fSteps;
  var m = mA + dm * jit;
  // feature softness: a pixel at the surface, growing with depth (cloudy jelly)
  // and never thinner than what one march step can resolve across a membrane
  let soft0 = max(0.0045, 0.9 / ppu) + 0.62 * length(dm.xy);

  let kappa = G.deep.rgb;
  // ground proximity: less light arrives low down on faces that look at the floor
  let lowAO = mix(1.0, 0.55 + 0.45 * smoothstep(-0.02, 0.22, in.world.y), saturate(0.45 - N.y * 0.75));
  let eEntry = irradiance(N) * lowAO;
  // no light enters where the exit point rests on (or hovers just above) the ground
  let eExit = irradiance(rd) * (1.10 * mix(0.55, 1.0, smoothstep(0.0, 0.20, pE.y)));
  let cosN = max(NdV, 0.25);
  let stepEntry = exp(-kappa * (ds * cosN));
  let stepExit = exp(kappa * ds);
  var aEntry = exp(-kappa * (ds * cosN * jit));
  var aExit = exp(-kappa * max(thick - ds * jit, 0.0));

  // light entering through the faces that are neither the entry nor the exit
  // (distances measured in the ideal half cylinder; planar faces follow a
  // geometric progression along the segment)
  let dFA = HALF_T - mA.z; let dFB = HALF_T - mB.z;
  let dBA = HALF_T + mA.z; let dBB = HALF_T + mB.z;
  let rA = length(mA.xy);  let rB = length(mB.xy);
  let wF = smoothstep(0.0, 0.10, dFA) * smoothstep(0.0, 0.10, dFB);
  let wB = smoothstep(0.0, 0.10, dBA) * smoothstep(0.0, 0.10, dBB);
  let wC = smoothstep(0.0, 0.10, mA.y) * smoothstep(0.0, 0.10, mB.y);
  let wA = smoothstep(0.0, 0.10, 1.0 - rA) * smoothstep(0.0, 0.10, 1.0 - rB);
  let eF = irradiance(G.bodyZ.xyz) * wF;
  let eB = irradiance(-G.bodyZ.xyz) * wB;
  let eC = irradiance(-G.bodyY.xyz) * (wC * 0.45);
  var tF = exp(-kappa * max(dFA + dm.z * (-jit), 0.0));
  var tB = exp(-kappa * max(dBA + dm.z * jit, 0.0));
  var tC = exp(-kappa * max(mA.y + dm.y * jit, 0.0));
  let stepF = exp(kappa * dm.z);
  let stepB = exp(-kappa * dm.z);
  let stepC = exp(-kappa * dm.y);

  let lowTint = exp(-kappa * 0.30);
  let loB = loNoise(mB);
  var T = vec3f(1.0);
  var L = vec3f(0.0);
  for (var i = 0; i < nSteps; i++) {
    let s = (f32(i) + jit) * ds;
    let md = medium(m, soft0 + s * 0.035, mix(loA, loB, (f32(i) + jit) / fSteps));
    let nA = (G.bodyX.xyz * m.x + G.bodyY.xyz * m.y) / max(md.r, 1e-3);
    let eA = irradiance(nA) * (wA * exp(-kappa * max(1.0 - md.r, 0.0)));
    var lin = eEntry * aEntry + (eExit * aExit + eF * tF + eB * tB + eC * tC) * 0.5 + eA * 0.75;
    lin = mix(lin, vec3f(lin.r), md.pale * 0.45);                // pale tissue scatters the light before it reddens
    // the ground blocks the lower hemisphere: everything close to it receives less light
    // (what does arrive down there has mostly travelled through the body: it is warm)
    let lift = smoothstep(-0.03, 0.22, mix(in.world.y, pE.y, (f32(i) + jit) / fSteps));
    lin *= mix(lowTint, vec3f(1.0), max(lift, md.pale * 0.42));
    let ext = md.sa + vec3f(md.ss);
    let stepT = exp(-ext * ds);
    L += T * (vec3f(1.0) - stepT) * (md.col * (md.ss / ext)) * lin;
    T *= stepT;
    m += dm;
    aEntry *= stepEntry;
    aExit *= stepExit;
    tF *= stepF;
    tB *= stepB;
    tC *= stepC;
  }

  // ---- what is behind: the studio, bent by the jelly and dimmed by its transmittance
  var dirOut = normalize(rd + bend * (0.55 * smoothstep(0.0, 0.12, thick)));
  // an exit point resting on the ground always sees the (shadowed) ground right there, never the open backdrop
  dirOut.y = min(dirOut.y, mix(1.0, -0.25, 1.0 - smoothstep(0.0, 0.04, pE.y)));
  let behind = scene(pE, dirOut, saturate(thick * 2.5), smoothstep(0.0, 0.15, thick));
  var col = L + T * behind;

  // ---- membranes where they reach the surface of the two big faces: a crisp,
  // slightly opaque line (analytically anti-aliased, glued to the material)
  let lineSoft = max(0.004, footprint * 0.75);
  let memLine = (1.0 - smoothstep(-lineSoft, lineSoft, micro.y + 0.002))
              * faceK * (1.0 - smoothstep(PITH_R - 0.02, PITH_R + 0.03, rA));
  // (as bright as the flesh around it, only paler: it reads as a membrane, not as a drawn line)
  let memLit = G.memSca.rgb * vec3f(1.0, 0.95, 0.84) * (max(col.r, col.g) * 0.42 + 0.62);
  col = mix(col, memLit, memLine * 0.62);

  // ---- tiny bubbles: analytic spheres in material space along the straight
  // chord. Like everything else inside they are seen through a refracting
  // surface: each one appears moved against the bend by the sideways lead the
  // refracted ray has gained at the bubble's depth. The whole sphere is moved,
  // by the bend of the flat big face that looks at the eye, which keeps it
  // round (bending the ray at the real, bumpy and rounded surface would flatten
  // and wrinkle the spheres). Towards an edge-on view the shift fades out.
  let dAB = select(mB, back0.rgb, valid0) - mA;
  let dd = max(dot(dAB, dAB), 1e-8);
  let dirM = dAB / sqrt(dd);
  let side = select(-1.0, 1.0, dot(G.bodyZ.xyz, V) >= 0.0);
  let nFace = G.bodyZ.xyz * side;
  let cosF = dot(nFace, V);
  let bendF = (refract(rd, nFace, 1.0 / IOR) - rd)
            * (smoothstep(0.10, 0.45, cosF) / sqrt(1.0 - (1.0 - cosF * cosF) / (IOR * IOR)));
  // sideways lead per unit of depth below that face, in the body's frame (only the
  // part across the chord: a bubble keeps its place along it, and so its dimming)
  let leadM = vec3f(dot(bendF, G.bodyX.xyz), dot(bendF, G.bodyY.xyz), dot(bendF, G.bodyZ.xyz));
  let lead = leadM - dirM * dot(leadM, dirM);
  let logT = log(max(T, vec3f(1e-5)));
  // the body in front of a bubble dims it as along the straight chord: the shorter
  // refracted path must not make the glints brighter at oblique views
  let dimK = max(thick0 / max(thick, 1e-4), 1.0);
  // a bubble can show anywhere between the entry point and the end of the refracted ray
  let mB0 = mA + dAB;
  let mBr = mB0 + lead * clamp(HALF_T - side * mB0.z, 0.0, 2.0 * HALF_T);
  let secA = atan2(max(mA.y, 0.0), mA.x) * (16.0 / PI);
  let secB = atan2(max(mBr.y, 0.0), mBr.x) * (16.0 / PI);
  let sLo = clamp(i32(floor(min(secA, secB))) - 1, 0, 16);
  let sHi = clamp(i32(floor(max(secA, secB))) + 2, 0, 16);
  let iLo = i32(BUB.sec[sLo / 4][sLo % 4]);
  let iHi = i32(BUB.sec[sHi / 4][sHi % 4]);
  for (var i = iLo; i < iHi; i++) {
    let b = BUB.b[i];
    let c = b.xyz - lead * (HALF_T - side * b.z);              // where the bubble appears to be
    let t = dot(c - mA, dAB) / dd;
    let tc = clamp(t, 0.0, 1.0);
    let off = mA + dAB * tc - c;
    let q2 = dot(off, off) / (b.w * b.w);
    if (q2 < 1.0 && t > -0.02 && t < 1.02) {
      let e = sqrt(q2);
      let hh = sqrt(1.0 - q2);
      let nbM = off / b.w - dirM * hh;                         // sphere normal facing the viewer (material frame)
      let nb = normalize(G.bodyX.xyz * nbM.x + G.bodyY.xyz * nbM.y + G.bodyZ.xyz * nbM.z);
      let rb = reflect(rd, nb);
      let glint = pow(saturate(dot(rb, KEY_DIR)), 10.0) * 1.6 + pow(saturate(dot(rb, FILL_DIR)), 6.0) * 0.9
                + pow(saturate(rb.y), 3.0) * 0.35;
      let rim = e * e * e;
      let Tb = exp(logT * (tc * dimK));                        // transmittance in front of the bubble
      let aa = saturate((1.0 - e) * b.w * ppu * 1.5 + 0.15);
      let shade = G.bg.rgb * (0.10 + 0.62 * rim) + KEY_COL * glint;
      col = mix(col, col * (1.0 - 0.30 * rim) + Tb * shade, aa);
    }
  }

  // ---- surface: soft Fresnel sheen of the studio
  let F = 0.028 + 0.40 * pow(1.0 - NdV, 5.0);                 // waxy: grazing reflection stays moderate
  let R = reflect(rd, N);
  let env = envLight(R, in.world);
  col = col * (1.0 - F) + env * F;

  // ---- the skin of the rind is waxier than the cut faces: the three studio
  // lights leave broad, low highlights on it (half-vector lobes, broken up by
  // the pores in N). The wax lets some of the rind's own colour through, so the
  // highlight is a lighter rind colour and not a white film. It is blended in
  // instead of added: the sheen can pale the rind but never push a channel
  // past the highlight's own level.
  let skin = smoothstep(0.955, 0.99, rA) * (1.0 - faceK);
  let gloss = pow(saturate(dot(N, normalize(KEY_DIR + V))), 18.0)
            + pow(saturate(dot(N, normalize(TOP_DIR + V))), 18.0) * 0.5
            + pow(saturate(dot(N, normalize(FILL_DIR + V))), 18.0) * 0.6;
  let sheen = saturate(skin * gloss * 0.40);
  let sheenCol = SHEEN_COL * mix(vec3f(1.0), G.rindSca.rgb, 0.5);
  col = mix(col, sheenCol, sheen);

  let dbg = G.shear.z;
  if (dbg > 0.5) {
    if (dbg < 1.5) { col = L; }
    else if (dbg < 2.5) { col = T * behind; }
    else if (dbg < 3.5) { col = mix(env * F, sheenCol, sheen); }
    else if (dbg < 4.5) { col = N * 0.5 + vec3f(0.5); }
    else if (dbg < 5.5) { col = vec3f(thick); }
    else if (dbg < 6.5) { col = T; }
    else { col = vec3f(1.0, 0.0, 1.0); }
    return vec4f(pow(clamp(col, vec3f(0.0), vec3f(1.0)), vec3f(1.0 / 2.2)), 1.0);
  }

  return toDisplay(shoulder(col), in.clip.xy);
}
`;
}

function wgslLines(c) {
  return wgslGlobals() + wgslGeometry(c) + /* wgsl */`
struct LineOut {
  @builtin(position) clip: vec4f,
  @location(0) side: f32,
  @location(1) tension: f32,
};

fn edgePoint(i0: u32, i1: u32, t: f32) -> vec4f {
  let A = particles[i0];
  let B = particles[i1];
  let p = mix(A.pos.xyz, B.pos.xyz, t);
  let qa = p - dot(p - A.pos.xyz, A.nrm.xyz) * A.nrm.xyz;
  let qb = p - dot(p - B.pos.xyz, B.nrm.xyz) * B.nrm.xyz;
  var ps = mix(p, mix(qa, qb, t), ${f(c.phongAlpha)});
  ps.y = max(ps.y, 0.0);
  return vec4f(ps, mix(A.pos.w, B.pos.w, t));
}

@vertex
fn vs(@builtin(vertex_index) vi: u32, @location(0) idx: vec2u, @location(1) tt: vec2f) -> LineOut {
  let a = edgePoint(idx.x, idx.y, tt.x);
  let b = edgePoint(idx.x, idx.y, tt.y);
  // lift the line a hair towards the eye so it sits on top of the surface
  let pa = a.xyz + normalize(G.eye.xyz - a.xyz) * 0.006;
  let pb = b.xyz + normalize(G.eye.xyz - b.xyz) * 0.006;
  let ca = G.viewProj * vec4f(pa, 1.0);
  let cb = G.viewProj * vec4f(pb, 1.0);
  let res = vec2f(G.rayR.w, G.rayU.w);
  let sa = ca.xy / ca.w * res * 0.5;
  let sb = cb.xy / cb.w * res * 0.5;
  var dir = sb - sa;
  let len = length(dir);
  dir = select(vec2f(1.0, 0.0), dir / max(len, 1e-6), len > 1e-5);
  let nrm = vec2f(-dir.y, dir.x);
  let atB = vi == 1u || vi == 4u || vi == 5u;
  let side = select(-1.0, 1.0, vi == 2u || vi == 3u || vi == 5u);
  let cc = select(ca, cb, atB);
  let halfW = G.camU.w + 1.0;                                  // + 1 px for the soft edge
  let off = nrm * (side * halfW) / res * 2.0 * cc.w;
  var o: LineOut;
  o.clip = vec4f(cc.xy + off, cc.z, cc.w);
  o.side = side * halfW;
  o.tension = select(a.w, b.w, atB);
  return o;
}

fn lineColor(in: LineOut, alpha: f32, hotAlpha: f32) -> vec4f {
  let cover = saturate(G.camU.w + 0.5 - abs(in.side));
  let t = saturate(in.tension);
  let ink = vec3f(0.0242, 0.0110, 0.0052);                     // #2B1B10
  let hot = G.lineHot.rgb;
  let k = smoothstep(0.30, 0.95, t);
  let col = pow(mix(ink, hot, k), vec3f(1.0 / 2.2));           // display space (blending happens there)
  return vec4f(col, cover * mix(alpha, hotAlpha, k));
}

@fragment
fn fsCrisp(in: LineOut) -> @location(0) vec4f { return lineColor(in, 0.60, 0.95); }

@fragment
fn fsFaint(in: LineOut) -> @location(0) vec4f { return lineColor(in, 0.075, 0.16); }
`;
}

// ───────────────────────────── CPU-side builders ─────────────────────────────
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function srgbToLinear(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }

/** Tileable smooth value noise, 4 channels: r 4 cells, g 8 cells, b 16 cells, a fbm. */
function buildNoiseVolume(res) {
  const rnd = mulberry32(0xC17205);
  const lattice = (cells) => { const a = new Float32Array(cells * cells * cells); for (let i = 0; i < a.length; i++) a[i] = rnd(); return a; };
  // smoothstep-interpolated upsampling of a periodic lattice, one axis at a time
  const upsample = (lat, cells) => {
    const i0 = new Int32Array(res), i1 = new Int32Array(res), w = new Float32Array(res);
    for (let x = 0; x < res; x++) {
      const fx = x * cells / res, x0 = Math.floor(fx), t = fx - x0;
      i0[x] = x0; i1[x] = (x0 + 1) % cells; w[x] = t * t * (3 - 2 * t);
    }
    const ax = new Float32Array(cells * cells * res);            // [k][j][x]
    for (let k = 0; k < cells; k++) for (let j = 0; j < cells; j++) {
      const src = (k * cells + j) * cells, dst = (k * cells + j) * res;
      for (let x = 0; x < res; x++) { const a = lat[src + i0[x]]; ax[dst + x] = a + (lat[src + i1[x]] - a) * w[x]; }
    }
    const ay = new Float32Array(cells * res * res);              // [k][y][x]
    for (let k = 0; k < cells; k++) for (let y = 0; y < res; y++) {
      const s0 = (k * cells + i0[y]) * res, s1 = (k * cells + i1[y]) * res, dst = (k * res + y) * res, wy = w[y];
      for (let x = 0; x < res; x++) { const a = ax[s0 + x]; ay[dst + x] = a + (ax[s1 + x] - a) * wy; }
    }
    const out = new Float32Array(res * res * res);               // [z][y][x]
    const plane = res * res;
    for (let z = 0; z < res; z++) {
      const s0 = i0[z] * plane, s1 = i1[z] * plane, dst = z * plane, wz = w[z];
      for (let i = 0; i < plane; i++) { const a = ay[s0 + i]; out[dst + i] = a + (ay[s1 + i] - a) * wz; }
    }
    return out;
  };
  const r = upsample(lattice(4), 4), g = upsample(lattice(8), 8), b = upsample(lattice(16), 16);
  const f4 = upsample(lattice(4), 4), f8 = upsample(lattice(8), 8), f16 = upsample(lattice(16), 16);
  const total = res * res * res;
  const data = new Uint8Array(total * 4);
  const q = (v) => Math.max(0, Math.min(255, Math.round(v * 255)));
  for (let i = 0; i < total; i++) {
    data[i * 4] = q(r[i]);
    data[i * 4 + 1] = q(g[i]);
    data[i * 4 + 2] = q(b[i]);
    data[i * 4 + 3] = q(f4[i] * 0.5 + f8[i] * 0.3 + f16[i] * 0.2);
  }
  return data;
}

/** Sparse tiny bubbles suspended in the flesh (material coordinates + radius). */
function buildBubbles(count, thickness, pithR) {
  const rnd = mulberry32(0xB0BB1E5);
  const out = new Float32Array(count * 4 + 20);
  const pts = [];
  let guard = 0;
  while (pts.length < count && guard++ < 20000) {
    const big = rnd() < 0.16;
    const rad = big ? 0.017 + rnd() * 0.010 : 0.0065 + rnd() * 0.0075;
    const r = Math.sqrt(0.03 + rnd() * 0.97) * (pithR - 0.07);
    const th = Math.PI * (0.03 + 0.94 * rnd());
    const x = r * Math.cos(th), y = r * Math.sin(th);
    if (y < 0.05 || r < 0.14) continue;
    const zLim = thickness * 0.5 - rad - 0.022;
    const z = (rnd() * 2 - 1) * zLim;
    let ok = true;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (Math.hypot(p[0] - x, p[1] - y) < 0.085 + p[3] + rad) { ok = false; break; }
    }
    if (!ok) continue;
    pts.push([x, y, z, rad]);
  }
  while (pts.length < count) pts.push([-1e3, 1e-3, 0, 1e-3]);      // (never happens) parked far outside
  // sort by angle and index 16 angular sectors
  const ang = (p) => Math.atan2(Math.max(p[1], 0), p[0]);
  pts.sort((p, q) => ang(p) - ang(q));
  for (let i = 0; i < count; i++) {
    const p = pts[i];
    out[i * 4] = p[0]; out[i * 4 + 1] = p[1]; out[i * 4 + 2] = p[2]; out[i * 4 + 3] = p[3];
  }
  for (let sct = 0; sct <= 16; sct++) {
    let first = count;
    for (let i = 0; i < count; i++) { if (ang(pts[i]) * 16 / Math.PI >= sct) { first = i; break; } }
    out[count * 4 + sct] = first;
  }
  return out;
}

/**
 * Subdivide every surface triangle K×K. A refined vertex stores its three
 * corner particles, two barycentrics and the (linearly interpolated) material
 * coordinate — positions are resolved in the vertex shader.
 */
function buildRenderSurface(mesh, K) {
  const tris = mesh.surfTris, mat = mesh.mat, n = mesh.numParticles;
  const nTri = tris.length / 3;
  const map = new Map();
  const vIdx = [], vBary = [], vMat = [];
  const indices = [];
  const addVertex = (a, b, c, i, j) => {
    // i steps towards b, j steps towards c
    const k = K - i - j;
    let key;
    if (k === K) key = 'v' + a;
    else if (i === K) key = 'v' + b;
    else if (j === K) key = 'v' + c;
    else if (j === 0) key = a < b ? `e${a}_${b}_${i}` : `e${b}_${a}_${K - i}`;
    else if (i === 0) key = a < c ? `e${a}_${c}_${j}` : `e${c}_${a}_${K - j}`;
    else if (k === 0) key = b < c ? `e${b}_${c}_${j}` : `e${c}_${b}_${K - j}`;
    else key = null;
    if (key !== null) { const hit = map.get(key); if (hit !== undefined) return hit; }
    const id = vIdx.length / 3;
    const u = i / K, v = j / K, w = 1 - u - v;
    vIdx.push(a, b, c);
    vBary.push(u, v);
    vMat.push(
      mat[a * 3] * w + mat[b * 3] * u + mat[c * 3] * v,
      mat[a * 3 + 1] * w + mat[b * 3 + 1] * u + mat[c * 3 + 1] * v,
      mat[a * 3 + 2] * w + mat[b * 3 + 2] * u + mat[c * 3 + 2] * v);
    if (key !== null) map.set(key, id);
    return id;
  };
  const row = [];
  for (let t = 0; t < nTri; t++) {
    const a = tris[t * 3], b = tris[t * 3 + 1], c = tris[t * 3 + 2];
    for (let j = 0; j <= K; j++) {
      row[j] = [];
      for (let i = 0; i <= K - j; i++) row[j][i] = addVertex(a, b, c, i, j);
    }
    for (let j = 0; j < K; j++) {
      for (let i = 0; i < K - j; i++) {
        indices.push(row[j][i], row[j][i + 1], row[j + 1][i]);
        if (i < K - j - 1) indices.push(row[j][i + 1], row[j + 1][i + 1], row[j + 1][i]);
      }
    }
  }
  const count = vIdx.length / 3;
  const buf = new ArrayBuffer(count * 32);
  const u32 = new Uint32Array(buf), f32 = new Float32Array(buf);
  for (let i = 0; i < count; i++) {
    const o = i * 8;
    u32[o] = vIdx[i * 3]; u32[o + 1] = vIdx[i * 3 + 1]; u32[o + 2] = vIdx[i * 3 + 2];
    f32[o + 3] = vBary[i * 2]; f32[o + 4] = vBary[i * 2 + 1];
    f32[o + 5] = vMat[i * 3]; f32[o + 6] = vMat[i * 3 + 1]; f32[o + 7] = vMat[i * 3 + 2];
  }
  if (n > 0xFFFFFFFF) throw new Error('mesh too large');
  return { vertexData: buf, vertexCount: count, indexData: new Uint32Array(indices), indexCount: indices.length };
}

/** Line instances for the overlay: all tet edges (straight), then the surface edges split in K curved pieces. */
function buildLineInstances(mesh, K) {
  const all = mesh.edges, surf = mesh.surfEdges;
  const nAll = all.length / 2, nSurf = surf.length / 2;
  const count = nAll + nSurf * K;
  const buf = new ArrayBuffer(count * 16);
  const u32 = new Uint32Array(buf), f32 = new Float32Array(buf);
  let o = 0;
  for (let e = 0; e < nAll; e++) { u32[o] = all[e * 2]; u32[o + 1] = all[e * 2 + 1]; f32[o + 2] = 0; f32[o + 3] = 1; o += 4; }
  for (let e = 0; e < nSurf; e++) {
    for (let k = 0; k < K; k++) { u32[o] = surf[e * 2]; u32[o + 1] = surf[e * 2 + 1]; f32[o + 2] = k / K; f32[o + 3] = (k + 1) / K; o += 4; }
  }
  return { data: buf, allCount: nAll, surfFirst: nAll, surfCount: nSurf * K };
}

function gpuError(code, message, cause) {
  const e = new Error(message);
  e.code = code;
  if (cause) e.cause = cause;
  return e;
}

const PRIVATE = Symbol('JellyRenderer');

// ───────────────────────────── the renderer ─────────────────────────────
class JellyRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} mesh  result of buildSliceMesh()
   * @param {object} [opts] { background: [r,g,b] sRGB 0..1 (default cream #F6F0E4),
   *                          palette: 'orange'|'blood'|'lemon',
   *                          quality: 'low'|'medium'|'high'  (starts renderer.steps at 9 / 14 / 22, default 'medium'),
   *                          subdivisions: 1..5  (render-surface refinement per triangle edge, default 3),
   *                          debug: bool  (also collect the WGSL compiler's messages in debugErrors) }
   *
   * Rejects with an Error whose message is a plain sentence for the visitor and whose .code says what went wrong:
   *   'no-webgpu'         navigator.gpu is missing, or the canvas cannot give a WebGPU context
   *   'insecure-context'  navigator.gpu is missing because the page is not a secure context
   *   'no-adapter'        no adapter was offered
   *   'no-device'         the device could not be created, or was lost while the scene was starting
   *   'init-failed'       a shader, a pipeline or a resource failed validation (the message ends with the
   *                       underlying error; .cause is the original error)
   */
  static async create(canvas, mesh, opts) {
    const o = opts || {};
    const gpu = typeof navigator !== 'undefined' ? navigator.gpu : undefined;
    if (!gpu) {
      if (typeof window !== 'undefined' && window.isSecureContext === false) {
        throw gpuError('insecure-context', 'WebGPU only works on secure pages. Open this page over https, from localhost or as a local file.');
      }
      throw gpuError('no-webgpu', 'This browser does not offer WebGPU.');
    }
    let adapter = null;
    // prefer the discrete GPU on dual-GPU laptops (Windows ignores the hint and only warns about it)
    const isWindows = /win/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '');
    if (!isWindows) { try { adapter = await gpu.requestAdapter({ powerPreference: 'high-performance' }); } catch (e) { adapter = null; } }
    if (!adapter) { try { adapter = await gpu.requestAdapter(); } catch (e) { adapter = null; } }
    if (!adapter) throw gpuError('no-adapter', 'No graphics adapter that supports WebGPU was found.');
    let device = null;
    try { device = await adapter.requestDevice(); } catch (e) { throw gpuError('no-device', 'The graphics device could not be started.', e); }
    if (!device) throw gpuError('no-device', 'The graphics device could not be started.');
    let context = null;
    try { context = canvas.getContext('webgpu'); } catch (e) { context = null; }
    if (!context) { device.destroy(); throw gpuError('no-webgpu', 'This page could not get a WebGPU drawing surface.'); }
    // adapter.info is the current place for the flag; the attribute on the adapter is the older one
    const info = adapter.info || {};
    const fallbackAdapter = Boolean(info.isFallbackAdapter || adapter.isFallbackAdapter);
    const r = new JellyRenderer(PRIVATE, canvas, mesh, o, device, context, gpu.getPreferredCanvasFormat(), fallbackAdapter);
    let failure = null;
    try { await r._init(); } catch (e) { failure = e; }
    // A lost device does not make initialisation fail by itself (its calls quietly do nothing), and
    // requestDevice() may even hand out a device that is already lost: ask the device before anything else.
    const lost = await Promise.race([device.lost, new Promise((resolve) => setTimeout(resolve, 0, null))]);
    if (lost || r._lost) {
      r.destroy();
      throw gpuError('no-device', 'The graphics device was lost while the scene was starting.', failure || undefined);
    }
    if (failure) {
      r.destroy();
      const detail = failure && failure.message ? failure.message : String(failure);
      throw gpuError('init-failed', 'The scene could not be set up on this graphics device: ' + detail, failure);
    }
    return r;
  }

  constructor(token, canvas, mesh, opts, device, context, format, fallbackAdapter) {
    if (token !== PRIVATE) throw new Error('Use JellyRenderer.create()');
    this.canvas = canvas;
    this.mesh = mesh;
    this.device = device;
    this.context = context;
    this.format = format;
    this._onDeviceLost = null;
    this._lostInfo = null;
    this._lostTold = false;
    this._onError = null;
    this._failure = null;        // the Error that stopped the renderer, once there is one
    this._failureTold = false;
    this.debug = Boolean(opts.debug);
    this.debugErrors = [];
    this._steps = QUALITY_STEPS[opts.quality] || QUALITY_STEPS.medium;
    this.gpuMs = 0;              // smoothed submit -> GPU-finished latency (ms), 0 until measured
    this._probing = false;       // a latency probe is in flight
    this._checkFrames = 0;       // frames still to be drawn inside a validation scope
    this.isFallbackAdapter = Boolean(fallbackAdapter);   // software rasteriser: expect seconds per frame, not frames per second
    this.subdivisions = Math.max(1, Math.min(5, (opts.subdivisions | 0) || 3));
    this.showMesh = false;
    this.debugView = 0;          // look-dev aid, see the header comment
    this.pixelWidth = 0;
    this.pixelHeight = 0;
    this._destroyed = false;
    this._lost = false;
    this._configured = false;
    this._targetsOk = false;
    this._lastTime = -1;

    const bg = opts.background || [0xF6 / 255, 0xF0 / 255, 0xE4 / 255];
    this._bgSrgb = [bg[0], bg[1], bg[2]];
    this._bg = [srgbToLinear(bg[0]), srgbToLinear(bg[1]), srgbToLinear(bg[2])];

    // palette cross-fade state
    this._palFrom = new Float32Array(PALETTE_FLOATS);
    this._palTo = new Float32Array(PALETTE_FLOATS);
    this._palT = 1;
    this.palette = PALETTES[opts.palette] ? opts.palette : 'orange';
    packPalette(PALETTES[this.palette], this._palTo);
    this._palFrom.set(this._palTo);

    // per-frame scratch (no allocations while rendering)
    const n = mesh.numParticles;
    this._n = n;
    this._nAcc = new Float32Array(n * 3);
    this._pData = new Float32Array(n * 8);
    this._u = new Float32Array(16 + 12 * 4 + PALETTE_FLOATS);
    this._uPal = this._u.subarray(64, 64 + PALETTE_FLOATS);   // view onto the palette block
    this._matRel = new Float32Array(n * 3);
    let cx = 0, cy = 0, cz = 0;
    for (let i = 0; i < n; i++) { cx += mesh.mat[i * 3]; cy += mesh.mat[i * 3 + 1]; cz += mesh.mat[i * 3 + 2]; }
    cx /= n; cy /= n; cz /= n;
    for (let i = 0; i < n; i++) {
      this._matRel[i * 3] = mesh.mat[i * 3] - cx;
      this._matRel[i * 3 + 1] = mesh.mat[i * 3 + 1] - cy;
      this._matRel[i * 3 + 2] = mesh.mat[i * 3 + 2] - cz;
    }
    this._shadowCx = 0;
    this._shadowCz = 0;
  }

  // ------------------------------------------------------------------ init
  /** Builds everything on the device; rejects with the first validation or pipeline error. */
  async _init() {
    const device = this.device;

    device.lost.then((info) => {
      this._lost = true;
      this._lostInfo = info || null;
      this._notifyLost();
    });
    // An error nobody asked for (outside the validation scopes below) means the frames are broken.
    this._onUncaptured = (ev) => {
      const msg = ev && ev.error && ev.error.message ? ev.error.message : String(ev);
      if (this.debugErrors.length < 50) this.debugErrors.push(msg);
      if (!this._failure) console.error('[JellyRenderer] WebGPU error: ' + msg);
      this._fail(msg);
    };
    device.addEventListener('uncapturederror', this._onUncaptured);

    // The scope collects what createShaderModule and the resource calls report (a rejected
    // pipeline only says that its module is invalid; the compiler's message is in the scope).
    device.pushErrorScope('validation');
    let failure = null;
    try { await this._build(); } catch (e) { failure = e; }
    let scoped = null;
    try { scoped = await device.popErrorScope(); } catch (e) { scoped = null; }
    if (scoped) {
      this.debugErrors.push(scoped.message);
      const err = new Error(scoped.message);
      if (failure) err.cause = failure;
      throw err;
    }
    if (failure) throw failure;

    // size the targets from the canvas' current layout box
    const cw = this.canvas.clientWidth || this.canvas.width || 1;
    const ch = this.canvas.clientHeight || this.canvas.height || 1;
    this.resize(cw, ch, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
  }

  async _build() {
    const device = this.device, mesh = this.mesh;
    const dbg = this.debug;

    const cfg = {
      phongAlpha: 0.72,
      segments: NUM_SEGMENTS,
      thickness: mesh.thickness,
      pithR: mesh.pithR,
      rindR: mesh.rindR,
      numBubbles: NUM_BUBBLES,
    };

    // ---- static geometry
    const surf = buildRenderSurface(mesh, this.subdivisions);
    this._indexCount = surf.indexCount;
    this._vbuf = device.createBuffer({ label: 'slice vertices', size: surf.vertexData.byteLength, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(this._vbuf, 0, surf.vertexData);
    this._ibuf = device.createBuffer({ label: 'slice indices', size: surf.indexData.byteLength, usage: GPUBufferUsage.INDEX | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(this._ibuf, 0, surf.indexData);

    const lines = buildLineInstances(mesh, Math.max(2, this.subdivisions));
    this._lines = lines;
    this._lbuf = device.createBuffer({ label: 'overlay edges', size: lines.data.byteLength, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(this._lbuf, 0, lines.data);

    this._pbuf = device.createBuffer({ label: 'particles', size: this._pData.byteLength, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
    this._ubuf = device.createBuffer({ label: 'globals', size: this._u.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });

    const bubbles = buildBubbles(NUM_BUBBLES, mesh.thickness, mesh.pithR);
    this._bbuf = device.createBuffer({ label: 'bubbles', size: bubbles.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(this._bbuf, 0, bubbles);

    // ---- noise volume
    const noise = buildNoiseVolume(NOISE_RES);
    this._noiseTex = device.createTexture({
      label: 'noise', size: [NOISE_RES, NOISE_RES, NOISE_RES], dimension: '3d', format: 'rgba8unorm',
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
    });
    device.queue.writeTexture({ texture: this._noiseTex }, noise, { bytesPerRow: NOISE_RES * 4, rowsPerImage: NOISE_RES }, [NOISE_RES, NOISE_RES, NOISE_RES]);

    this._linSampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear', addressModeU: 'clamp-to-edge', addressModeV: 'clamp-to-edge' });
    this._noiseSampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear', addressModeU: 'repeat', addressModeV: 'repeat', addressModeW: 'repeat' });

    // ---- shadow targets
    const SH_FMT = 'rgba16float';
    const texUsage = GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.TEXTURE_BINDING;
    this._sh0 = device.createTexture({ label: 'shadow raster', size: [SHADOW_RES, SHADOW_RES], format: SH_FMT, usage: texUsage });
    this._sh0Depth = device.createTexture({ label: 'shadow depth', size: [SHADOW_RES, SHADOW_RES], format: 'depth24plus', usage: GPUTextureUsage.RENDER_ATTACHMENT });
    this._shTmp = [];
    this._shLvl = [];
    for (let l = 1; l <= SHADOW_LEVELS; l++) {
      const s = SHADOW_RES >> l;
      this._shTmp.push(device.createTexture({ label: 'shadow tmp ' + l, size: [s, s], format: SH_FMT, usage: texUsage }));
      this._shLvl.push(device.createTexture({ label: 'shadow level ' + l, size: [s, s], format: SH_FMT, usage: texUsage }));
    }

    // ---- bind group layouts
    const VS = GPUShaderStage.VERTEX, FS = GPUShaderStage.FRAGMENT;
    const geoLayout = device.createBindGroupLayout({
      label: 'geometry', entries: [
        { binding: 0, visibility: VS | FS, buffer: { type: 'uniform' } },
        { binding: 1, visibility: VS, buffer: { type: 'read-only-storage' } },
      ],
    });
    const globalsOnlyLayout = device.createBindGroupLayout({
      label: 'globals', entries: [{ binding: 0, visibility: VS | FS, buffer: { type: 'uniform' } }],
    });
    const sceneEntries = [
      { binding: 0, visibility: FS, sampler: { type: 'filtering' } },
      { binding: 1, visibility: FS, sampler: { type: 'filtering' } },
      { binding: 2, visibility: FS, texture: { sampleType: 'float', viewDimension: '3d' } },
      { binding: 3, visibility: FS, texture: { sampleType: 'float' } },
      { binding: 4, visibility: FS, texture: { sampleType: 'float' } },
      { binding: 5, visibility: FS, texture: { sampleType: 'float' } },
      { binding: 6, visibility: FS, texture: { sampleType: 'float' } },
    ];
    const sceneLayout = device.createBindGroupLayout({
      label: 'scene', entries: sceneEntries.concat([{ binding: 7, visibility: FS, buffer: { type: 'uniform' } }]),
    });
    this._backLayout = device.createBindGroupLayout({
      label: 'back faces', entries: [{ binding: 0, visibility: FS, texture: { sampleType: 'unfilterable-float' } }],
    });
    const blurLayout = device.createBindGroupLayout({
      label: 'blur', entries: [
        { binding: 0, visibility: FS, buffer: { type: 'uniform' } },
        { binding: 1, visibility: FS, texture: { sampleType: 'float' } },
        { binding: 2, visibility: FS, sampler: { type: 'filtering' } },
      ],
    });

    // ---- bind groups
    this._geoBind = device.createBindGroup({
      layout: geoLayout, entries: [
        { binding: 0, resource: { buffer: this._ubuf } },
        { binding: 1, resource: { buffer: this._pbuf } },
      ],
    });
    this._globalsBind = device.createBindGroup({ layout: globalsOnlyLayout, entries: [{ binding: 0, resource: { buffer: this._ubuf } }] });
    this._sceneBind = device.createBindGroup({
      layout: sceneLayout, entries: [
        { binding: 0, resource: this._linSampler },
        { binding: 1, resource: this._noiseSampler },
        { binding: 2, resource: this._noiseTex.createView({ dimension: '3d' }) },
        { binding: 3, resource: this._shLvl[0].createView() },
        { binding: 4, resource: this._shLvl[1].createView() },
        { binding: 5, resource: this._shLvl[2].createView() },
        { binding: 6, resource: this._shLvl[3].createView() },
        { binding: 7, resource: { buffer: this._bbuf } },
      ],
    });

    // blur chain: (src -> tmp, horizontal + downsample), (tmp -> level, vertical)
    this._blurPasses = [];
    this._blurUniforms = [];
    let srcTex = this._sh0;
    for (let l = 0; l < SHADOW_LEVELS; l++) {
      const s = SHADOW_RES >> (l + 1);
      const mk = (dx, dy, from, to) => {
        const ub = device.createBuffer({ size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
        device.queue.writeBuffer(ub, 0, new Float32Array([dx, dy, 0, 0]));
        this._blurUniforms.push(ub);
        const bind = device.createBindGroup({
          layout: blurLayout, entries: [
            { binding: 0, resource: { buffer: ub } },
            { binding: 1, resource: from.createView() },
            { binding: 2, resource: this._linSampler },
          ],
        });
        const desc = { colorAttachments: [{ view: to.createView(), loadOp: 'clear', storeOp: 'store', clearValue: { r: 0, g: 0, b: 0, a: 0 } }] };
        this._blurPasses.push({ bind, desc });
      };
      mk(1 / s, 0, srcTex, this._shTmp[l]);
      mk(0, 1 / s, this._shTmp[l], this._shLvl[l]);
      srcTex = this._shLvl[l];
    }

    // ---- shader modules
    const mkModule = async (label, code) => {
      const mod = device.createShaderModule({ label, code });
      if (dbg && mod.getCompilationInfo) {
        const info = await mod.getCompilationInfo();
        for (const m of info.messages) {
          const text = `[JellyRenderer] WGSL ${m.type} in ${label} (${m.lineNum}:${m.linePos}): ${m.message}`;
          this.debugErrors.push(text);
          if (m.type === 'error') console.error(text); else console.warn(text);
        }
      }
      return mod;
    };
    const [modShadow, modBlur, modBack, modBackdrop, modSlice, modLines] = await Promise.all([
      mkModule('shadow raster', wgslShadowRaster(cfg)),
      mkModule('blur', WGSL_BLUR),
      mkModule('back faces', wgslBack(cfg)),
      mkModule('backdrop', wgslBackdrop(cfg)),
      mkModule('slice', wgslSlice(cfg)),
      mkModule('overlay lines', wgslLines(cfg)),
    ]);

    // ---- pipelines
    const surfBuffers = [{
      arrayStride: 32, attributes: [
        { shaderLocation: 0, offset: 0, format: 'uint32x3' },
        { shaderLocation: 1, offset: 12, format: 'float32x2' },
        { shaderLocation: 2, offset: 20, format: 'float32x3' },
      ],
    }];
    const surfBuffersNoMat = [{
      arrayStride: 32, attributes: [
        { shaderLocation: 0, offset: 0, format: 'uint32x3' },
        { shaderLocation: 1, offset: 12, format: 'float32x2' },
      ],
    }];
    const lineBuffers = [{
      arrayStride: 16, stepMode: 'instance', attributes: [
        { shaderLocation: 0, offset: 0, format: 'uint32x2' },
        { shaderLocation: 1, offset: 8, format: 'float32x2' },
      ],
    }];
    const layout = (...groups) => device.createPipelineLayout({ bindGroupLayouts: groups });
    const alphaBlend = {
      color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
      alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' },
    };
    const canvasFmt = this.format;

    const pipes = await Promise.all([
      device.createRenderPipelineAsync({
        label: 'shadow raster', layout: layout(geoLayout),
        vertex: { module: modShadow, entryPoint: 'vs', buffers: surfBuffersNoMat },
        fragment: { module: modShadow, entryPoint: 'fs', targets: [{ format: SH_FMT }] },
        primitive: { topology: 'triangle-list', cullMode: 'none' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: true, depthCompare: 'less' },
      }),
      device.createRenderPipelineAsync({
        label: 'blur', layout: layout(blurLayout),
        vertex: { module: modBlur, entryPoint: 'vs' },
        fragment: { module: modBlur, entryPoint: 'fs', targets: [{ format: SH_FMT }] },
        primitive: { topology: 'triangle-list' },
      }),
      device.createRenderPipelineAsync({
        label: 'back faces', layout: layout(geoLayout),
        vertex: { module: modBack, entryPoint: 'vs', buffers: surfBuffers },
        fragment: { module: modBack, entryPoint: 'fs', targets: [{ format: 'rgba16float' }] },
        primitive: { topology: 'triangle-list', cullMode: 'front', frontFace: 'ccw' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: true, depthCompare: 'greater' },
      }),
      device.createRenderPipelineAsync({
        label: 'backdrop', layout: layout(globalsOnlyLayout, sceneLayout),
        vertex: { module: modBackdrop, entryPoint: 'vs' },
        fragment: { module: modBackdrop, entryPoint: 'fs', targets: [{ format: canvasFmt }] },
        primitive: { topology: 'triangle-list' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: false, depthCompare: 'always' },
        multisample: { count: MSAA },
      }),
      device.createRenderPipelineAsync({
        label: 'slice', layout: layout(geoLayout, sceneLayout, this._backLayout),
        vertex: { module: modSlice, entryPoint: 'vs', buffers: surfBuffers },
        fragment: { module: modSlice, entryPoint: 'fs', targets: [{ format: canvasFmt }] },
        primitive: { topology: 'triangle-list', cullMode: 'back', frontFace: 'ccw' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: true, depthCompare: 'less' },
        multisample: { count: MSAA },
      }),
      device.createRenderPipelineAsync({
        label: 'overlay faint', layout: layout(geoLayout),
        vertex: { module: modLines, entryPoint: 'vs', buffers: lineBuffers },
        fragment: { module: modLines, entryPoint: 'fsFaint', targets: [{ format: canvasFmt, blend: alphaBlend }] },
        primitive: { topology: 'triangle-list', cullMode: 'none' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: false, depthCompare: 'always' },
        multisample: { count: MSAA },
      }),
      device.createRenderPipelineAsync({
        label: 'overlay crisp', layout: layout(geoLayout),
        vertex: { module: modLines, entryPoint: 'vs', buffers: lineBuffers },
        fragment: { module: modLines, entryPoint: 'fsCrisp', targets: [{ format: canvasFmt, blend: alphaBlend }] },
        primitive: { topology: 'triangle-list', cullMode: 'none' },
        depthStencil: { format: 'depth24plus', depthWriteEnabled: false, depthCompare: 'less-equal' },
        multisample: { count: MSAA },
      }),
    ]);
    [this._pShadow, this._pBlur, this._pBack, this._pBackdrop, this._pSlice, this._pLineFaint, this._pLineCrisp] = pipes;

    // ---- reusable pass descriptors (views are patched in when targets change)
    this._shadowPass = {
      colorAttachments: [{ view: this._sh0.createView(), loadOp: 'clear', storeOp: 'store', clearValue: { r: 0, g: 0, b: 0, a: 0 } }],
      depthStencilAttachment: { view: this._sh0Depth.createView(), depthLoadOp: 'clear', depthStoreOp: 'discard', depthClearValue: 1 },
    };
    this._backPass = {
      colorAttachments: [{ view: null, loadOp: 'clear', storeOp: 'store', clearValue: { r: 0, g: 0, b: 0, a: -1000 } }],
      depthStencilAttachment: { view: null, depthLoadOp: 'clear', depthStoreOp: 'discard', depthClearValue: 0 },
    };
    const b = this._bgSrgb;
    this._mainPass = {
      colorAttachments: [{ view: null, resolveTarget: null, loadOp: 'clear', storeOp: 'discard', clearValue: { r: b[0], g: b[1], b: b[2], a: 1 } }],
      depthStencilAttachment: { view: null, depthLoadOp: 'clear', depthStoreOp: 'discard', depthClearValue: 1 },
    };

  }

  // ------------------------------------------------------------------ public API
  /**
   * (Re)configure the canvas and the size-dependent targets. Cheap when nothing changed.
   * dpr is the backing-store scale: any positive number, also below 1 (fewer pixels than the layout box).
   */
  resize(cssWidth, cssHeight, dpr) {
    if (this._destroyed || this._lost) return;
    const device = this.device;
    const ratio = dpr > 0 && dpr < Infinity ? dpr : 1;
    const maxDim = device.limits.maxTextureDimension2D;
    // a box that is laid out gets at least one pixel and never more than a texture may have
    const toPixels = (css) => (css > 0 ? Math.min(maxDim, Math.max(1, Math.round(css * ratio))) : 0);
    const w = toPixels(cssWidth), h = toPixels(cssHeight);
    if (w < 1 || h < 1) { this._targetsOk = false; return; }      // hidden / collapsed canvas: skip frames
    if (w === this.pixelWidth && h === this.pixelHeight && this._targetsOk) return;
    this.pixelWidth = w;
    this.pixelHeight = h;
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    if (!this._configured) {
      this.context.configure({ device, format: this.format, alphaMode: 'opaque' });
      this._configured = true;
    }
    this._destroyTargets();
    const RA = GPUTextureUsage.RENDER_ATTACHMENT;
    this._msaaColor = device.createTexture({ label: 'msaa colour', size: [w, h], sampleCount: MSAA, format: this.format, usage: RA });
    this._msaaDepth = device.createTexture({ label: 'msaa depth', size: [w, h], sampleCount: MSAA, format: 'depth24plus', usage: RA });
    this._backTex = device.createTexture({ label: 'back faces', size: [w, h], format: 'rgba16float', usage: RA | GPUTextureUsage.TEXTURE_BINDING });
    this._backDepth = device.createTexture({ label: 'back depth', size: [w, h], format: 'depth24plus', usage: RA });
    const backView = this._backTex.createView();
    this._backBind = device.createBindGroup({ layout: this._backLayout, entries: [{ binding: 0, resource: backView }] });
    this._backPass.colorAttachments[0].view = backView;
    this._backPass.depthStencilAttachment.view = this._backDepth.createView();
    this._mainPass.colorAttachments[0].view = this._msaaColor.createView();
    this._mainPass.depthStencilAttachment.view = this._msaaDepth.createView();
    this._targetsOk = true;
    this._checkFrames = 2;                                         // validate the next frames drawn into the new targets
  }

  /** March steps per pixel, settable at any time: a number, rounded and clamped to 4..22 (anything else is ignored). */
  get steps() { return this._steps; }
  set steps(value) {
    const n = Math.round(Number(value));
    if (Number.isFinite(n)) this._steps = Math.min(MAX_STEPS, Math.max(MIN_STEPS, n));
  }

  /** Called once with the GPUDeviceLostInfo; a loss that happened before the handler was set is delivered late. */
  get onDeviceLost() { return this._onDeviceLost; }
  set onDeviceLost(fn) { this._onDeviceLost = fn; if (this._lost) Promise.resolve().then(() => this._notifyLost()); }
  _notifyLost() {
    if (this._destroyed || this._lostTold || typeof this._onDeviceLost !== 'function') return;
    this._lostTold = true;
    try { this._onDeviceLost(this._lostInfo); } catch (e) { console.error(e); }
  }

  /**
   * Called once with an Error when a frame fails validation or the device reports an error of its own.
   * The renderer draws nothing from then on. A failure from before the handler was set is delivered late.
   */
  get onError() { return this._onError; }
  set onError(fn) { this._onError = fn; if (this._failure) Promise.resolve().then(() => this._notifyError()); }
  _notifyError() {
    if (this._destroyed || this._failureTold || !this._failure || typeof this._onError !== 'function') return;
    this._failureTold = true;
    try { this._onError(this._failure); } catch (e) { console.error(e); }
  }
  _fail(message) {
    if (this._failure || this._destroyed || this._lost) return;
    this._failure = new Error(message);
    this._notifyError();
  }

  /** true while something inside the renderer is still animating (palette cross-fade). */
  get animating() { return this._palT < 1; }

  /** 'orange' | 'blood' | 'lemon'; cross-fades over ~0.5 s unless immediate. */
  setPalette(id, immediate) {
    const p = PALETTES[id];
    if (!p) return;
    if (id === this.palette && this._palT >= 1 && !immediate) return;
    // start from whatever is on screen right now
    this._currentPalette(this._palFrom);
    packPalette(p, this._palTo);
    this.palette = id;
    this._palT = immediate ? 1 : 0;
    this._lastTime = -1;          // the fade starts now, however long ago the last frame was drawn
  }

  setShowMesh(on) { this.showMesh = Boolean(on); }

  /**
   * Draw one frame.
   * @param {{positions: Float32Array, camera: object, time?: number, dt?: number, tension?: Float32Array}} frame
   */
  render(frame) {
    if (this._destroyed || this._lost || this._failure || !this._targetsOk || !frame || !frame.positions || !frame.camera) return;
    const device = this.device, cam = frame.camera;
    const time = frame.time || 0;
    // the palette cross-fade follows the clock of `time` (so it also runs while
    // the simulation is paused); `dt` is only the fallback when time stands still
    let adv = this._lastTime >= 0 ? time - this._lastTime : 0;
    if (!(adv > 0)) adv = frame.dt > 0 ? frame.dt : 0;
    this._lastTime = time;
    adv = Math.min(adv, 0.25);
    if (this._palT < 1) this._palT = Math.min(1, this._palT + adv / PALETTE_FADE_SECONDS);

    if (!this._updateParticles(frame.positions, frame.tension)) return;   // non-finite input: keep the last good frame
    this._updateUniforms(cam, time);
    device.queue.writeBuffer(this._pbuf, 0, this._pData);
    device.queue.writeBuffer(this._ubuf, 0, this._u);

    // The first frames into new targets are drawn inside a validation scope. The scope is popped
    // whatever happens while encoding: one left open would swallow every later error.
    const check = this._checkFrames > 0;
    if (check) device.pushErrorScope('validation');
    let submitted = false;
    try {
      submitted = this._drawFrame();
    } finally {
      if (check) {
        if (submitted) this._checkFrames--;
        device.popErrorScope().then((err) => { if (err) this._fail(err.message); }, () => {});
      }
    }
    if (submitted) this._probeLatency();
  }

  /** Encodes and submits the frame graph; false when the canvas has no texture to draw into right now. */
  _drawFrame() {
    const device = this.device;
    let canvasTex;
    try { canvasTex = this.context.getCurrentTexture(); } catch (e) { return false; }
    this._mainPass.colorAttachments[0].resolveTarget = canvasTex.createView();

    const enc = device.createCommandEncoder();

    // 1. occlusion seen from the ground, along the key light
    let pass = enc.beginRenderPass(this._shadowPass);
    pass.setPipeline(this._pShadow);
    pass.setBindGroup(0, this._geoBind);
    pass.setVertexBuffer(0, this._vbuf);
    pass.setIndexBuffer(this._ibuf, 'uint32');
    pass.drawIndexed(this._indexCount);
    pass.end();

    // 2. blur chain
    const blurs = this._blurPasses;
    for (let i = 0; i < blurs.length; i++) {
      pass = enc.beginRenderPass(blurs[i].desc);
      pass.setPipeline(this._pBlur);
      pass.setBindGroup(0, blurs[i].bind);
      pass.draw(3);
      pass.end();
    }

    // 3. exit points (back faces)
    pass = enc.beginRenderPass(this._backPass);
    pass.setPipeline(this._pBack);
    pass.setBindGroup(0, this._geoBind);
    pass.setVertexBuffer(0, this._vbuf);
    pass.setIndexBuffer(this._ibuf, 'uint32');
    pass.drawIndexed(this._indexCount);
    pass.end();

    // 4. backdrop + slice + overlay, MSAA resolved straight into the canvas
    pass = enc.beginRenderPass(this._mainPass);
    pass.setPipeline(this._pBackdrop);
    pass.setBindGroup(0, this._globalsBind);
    pass.setBindGroup(1, this._sceneBind);
    pass.draw(3);
    pass.setPipeline(this._pSlice);
    pass.setBindGroup(0, this._geoBind);
    pass.setBindGroup(1, this._sceneBind);
    pass.setBindGroup(2, this._backBind);
    pass.setVertexBuffer(0, this._vbuf);
    pass.setIndexBuffer(this._ibuf, 'uint32');
    pass.drawIndexed(this._indexCount);
    if (this.showMesh) {
      const ln = this._lines;
      pass.setVertexBuffer(0, this._lbuf);
      pass.setPipeline(this._pLineFaint);
      pass.draw(6, ln.allCount, 0, 0);
      pass.setPipeline(this._pLineCrisp);
      pass.draw(6, ln.surfCount, 0, ln.surfFirst);
    }
    pass.end();

    device.queue.submit([enc.finish()]);
    return true;
  }

  /** Times how long the GPU needs to finish what was just submitted (gpuMs); one probe in flight at a time. */
  _probeLatency() {
    if (this._probing) return;
    this._probing = true;
    const t0 = performance.now();
    this.device.queue.onSubmittedWorkDone().then(() => {
      this._probing = false;
      if (this._destroyed || this._lost) return;                   // a dead device "finishes" at once: not a measurement
      const ms = performance.now() - t0;
      this.gpuMs = this.gpuMs > 0 ? this.gpuMs + (ms - this.gpuMs) * 0.15 : ms;
    }, () => { this._probing = false; });
  }

  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    try { if (this._onUncaptured) this.device.removeEventListener('uncapturederror', this._onUncaptured); } catch (e) { /* ignore */ }
    this._destroyTargets();
    const kill = (x) => { try { if (x) x.destroy(); } catch (e) { /* ignore */ } };
    [this._vbuf, this._ibuf, this._lbuf, this._pbuf, this._ubuf, this._bbuf, this._noiseTex, this._sh0, this._sh0Depth].forEach(kill);
    (this._shTmp || []).forEach(kill);
    (this._shLvl || []).forEach(kill);
    (this._blurUniforms || []).forEach(kill);
    try { if (this._configured) this.context.unconfigure(); } catch (e) { /* ignore */ }
    try { this.device.destroy(); } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------------ internals
  _destroyTargets() {
    const kill = (x) => { try { if (x) x.destroy(); } catch (e) { /* ignore */ } };
    kill(this._msaaColor); kill(this._msaaDepth); kill(this._backTex); kill(this._backDepth);
    this._msaaColor = this._msaaDepth = this._backTex = this._backDepth = null;
    this._targetsOk = false;
  }

  _currentPalette(out) {
    const a = this._palFrom, b = this._palTo;
    let t = this._palT;
    t = t * t * (3 - 2 * t);
    for (let i = 0; i < PALETTE_FLOATS; i++) out[i] = a[i] + (b[i] - a[i]) * t;
    return out;
  }

  /** Smooth normals + packing; also fits the body frame and the shadow window. Returns false on non-finite input. */
  _updateParticles(pos, tension) {
    const n = this._n, acc = this._nAcc, out = this._pData, tris = this.mesh.surfTris, rel = this._matRel;
    acc.fill(0);
    for (let t = 0, tl = tris.length; t < tl; t += 3) {
      const a = tris[t] * 3, b = tris[t + 1] * 3, c = tris[t + 2] * 3;
      const ax = pos[a], ay = pos[a + 1], az = pos[a + 2];
      const ux = pos[b] - ax, uy = pos[b + 1] - ay, uz = pos[b + 2] - az;
      const vx = pos[c] - ax, vy = pos[c + 1] - ay, vz = pos[c + 2] - az;
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      acc[a] += nx; acc[a + 1] += ny; acc[a + 2] += nz;
      acc[b] += nx; acc[b + 1] += ny; acc[b + 2] += nz;
      acc[c] += nx; acc[c + 1] += ny; acc[c + 2] += nz;
    }
    let sx = 0, sy = 0, sz = 0;
    let xx = 0, xy = 0, xz = 0, yx = 0, yy = 0, yz = 0, zx = 0, zy = 0, zz = 0;
    const hasT = Boolean(tension) && tension.length >= n;
    for (let i = 0; i < n; i++) {
      const p = i * 3, o = i * 8;
      const px = pos[p], py = pos[p + 1], pz = pos[p + 2];
      out[o] = px; out[o + 1] = py; out[o + 2] = pz;
      out[o + 3] = hasT ? tension[i] : 0;
      let nx = acc[p], ny = acc[p + 1], nz = acc[p + 2];
      const l = Math.sqrt(nx * nx + ny * ny + nz * nz);
      if (l > 1e-12) { nx /= l; ny /= l; nz /= l; } else { nx = 0; ny = 0; nz = 0; }
      out[o + 4] = nx; out[o + 5] = ny; out[o + 6] = nz; out[o + 7] = 0;
      sx += px; sy += py; sz += pz;
      const mx = rel[p], my = rel[p + 1], mz = rel[p + 2];
      xx += px * mx; xy += py * mx; xz += pz * mx;
      yx += px * my; yy += py * my; yz += pz * my;
      zx += px * mz; zy += py * mz; zz += pz * mz;
    }
    if (!(Math.abs(sx) + Math.abs(sy) + Math.abs(sz) < 1e9)) return false;   // NaN / exploded
    const u = this._u;
    // world directions of the material axes (columns of the cross-covariance)
    let l = Math.sqrt(xx * xx + xy * xy + xz * xz) || 1;
    u[40] = xx / l; u[41] = xy / l; u[42] = xz / l; u[43] = 0;
    l = Math.sqrt(yx * yx + yy * yy + yz * yz) || 1;
    u[44] = yx / l; u[45] = yy / l; u[46] = yz / l; u[47] = 0;
    l = Math.sqrt(zx * zx + zy * zy + zz * zz) || 1;
    u[48] = zx / l; u[49] = zy / l; u[50] = zz / l; u[51] = 0;
    // shadow window follows the body, snapped to the coarsest blur texel so it never swims
    const cy = sy / n;
    const snap = (SHADOW_EXTENT * 2) / (SHADOW_RES >> SHADOW_LEVELS);
    this._shadowCx = Math.round((sx / n + SHADOW_SHEAR[0] * cy * 0.6) / snap) * snap;
    this._shadowCz = Math.round((sz / n + SHADOW_SHEAR[1] * cy * 0.6) / snap) * snap;
    return true;
  }

  _updateUniforms(cam, time) {
    const u = this._u;
    u.set(cam.viewProj, 0);
    const tanH = Math.tan(cam.fovY * 0.5);
    const aspect = cam.aspect > 0 ? cam.aspect : this.pixelWidth / this.pixelHeight;   // must match cam.viewProj
    const r = cam.right, up = cam.up, fw = cam.forward;
    const tx = tanH * aspect, ty = tanH;
    const sx = (cam.shiftX || 0) * tx, sy = (cam.shiftY || 0) * ty;
    u[16] = cam.eye[0]; u[17] = cam.eye[1]; u[18] = cam.eye[2]; u[19] = cam.distance;
    u[20] = fw[0] - r[0] * sx - up[0] * sy; u[21] = fw[1] - r[1] * sx - up[1] * sy; u[22] = fw[2] - r[2] * sx - up[2] * sy; u[23] = time;
    u[24] = r[0] * tx; u[25] = r[1] * tx; u[26] = r[2] * tx; u[27] = this.pixelWidth;
    u[28] = up[0] * ty; u[29] = up[1] * ty; u[30] = up[2] * ty; u[31] = this.pixelHeight;
    const pxScale = this.pixelHeight / (2 * tanH);
    u[32] = r[0]; u[33] = r[1]; u[34] = r[2]; u[35] = pxScale;
    // overlay line half width: ~1.2 CSS px wide lines, never thinner than 1 device px
    const cssScale = this.canvas.clientHeight > 0 ? this.pixelHeight / this.canvas.clientHeight : 1;
    u[36] = up[0]; u[37] = up[1]; u[38] = up[2]; u[39] = Math.max(0.5, 0.6 * cssScale);
    // 40..51 body frame (written by _updateParticles)
    u[52] = this._shadowCx; u[53] = this._shadowCz; u[54] = 1 / SHADOW_EXTENT; u[55] = 0;
    u[56] = SHADOW_SHEAR[0]; u[57] = SHADOW_SHEAR[1]; u[58] = this.debugView || 0; u[59] = this._steps;
    u[60] = this._bg[0]; u[61] = this._bg[1]; u[62] = this._bg[2]; u[63] = 1 / 255;
    this._currentPalette(this._uPal);
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { JellyRenderer, PALETTES };
}
