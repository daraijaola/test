'use strict';
/*
 * mesh.js — procedural tetrahedral mesh of a thick semicircular citrus slice.
 *
 * Nothing is loaded from a model file: a 2D triangulation of a half disc is
 * built from concentric rings, extruded through the thickness into prisms,
 * and every prism is split into three tetrahedra.
 *
 * Two coordinate sets are produced per particle:
 *
 *   mat  — "material" coordinates of the ideal half cylinder, radius 1:
 *            x in [-1, 1], y in [0, 1] with x² + y² <= 1, z in [-T/2, T/2].
 *          y = 0 is the flat cut face, the arc is the rind. These never change;
 *          the renderer evaluates segments, membranes, pith, rind and bubbles
 *          as functions of `mat`, so the pattern is glued to the flesh.
 *
 *   rest — the rest pose in world space (same frame, edges rounded, faces
 *          slightly domed). The slice stands on its cut face on the ground
 *          plane y = 0, the arc rising to y ≈ 1, thickness along z.
 *
 * Zones by normalised radius rho = length(mat.xy):
 *   flesh  rho <  pithR
 *   pith   pithR <= rho < rindR
 *   rind   rho >= rindR
 */

const ZONE_FLESH = 0;
const ZONE_PITH = 1;
const ZONE_RIND = 2;

function buildSliceMesh(opts) {
  const o = Object.assign({
    h: 0.14,          // target in-plane edge length (slice radius is 1)
    layers: 3,        // divisions through the thickness
    thickness: 0.44,  // T
    pithR: 0.80,      // flesh / pith boundary
    rindR: 0.905,     // pith / rind boundary
    arcSegs: 0,       // segments on the three outer rings (0 = derive from h)
    edgeRound: 0.12,  // rounding radius where the faces meet the rind / cut face
    puff: 0.07,       // faces dome outwards by this fraction of the thickness
  }, opts || {});

  const T = o.thickness;
  const NT = Math.max(1, o.layers | 0);

  // ---- 2D rings ---------------------------------------------------------
  const rowH = o.h * 0.8660254;
  const nInner = Math.max(2, Math.round(o.pithR / rowH));
  const radii = [];
  for (let j = 0; j <= nInner; j++) radii.push(o.pithR * j / nInner);
  radii.push(o.rindR, 1.0);
  const nRings = radii.length;                       // ring 0 is the centre point
  const arcSegs = o.arcSegs > 0 ? o.arcSegs | 0 : Math.max(6, Math.round(Math.PI / o.h));

  const ringStart = new Int32Array(nRings);
  const ringSegs = new Int32Array(nRings);
  const v2 = [];                                     // x, y pairs
  for (let j = 0; j < nRings; j++) {
    ringStart[j] = v2.length / 2;
    if (j === 0) { ringSegs[j] = 0; v2.push(0, 0); continue; }
    const r = radii[j];
    const segs = j >= nRings - 3 ? arcSegs : Math.max(2, Math.round(Math.PI * r / o.h));
    ringSegs[j] = segs;
    for (let i = 0; i <= segs; i++) {
      const th = Math.PI * i / segs;
      // snap the end points exactly onto the cut face
      const y = (i === 0 || i === segs) ? 0 : r * Math.sin(th);
      v2.push(r * Math.cos(th), y);
    }
  }
  const N2 = v2.length / 2;

  // ---- stitch consecutive rings into CCW triangles ------------------------
  const tri2 = [];
  for (let j = 0; j < nRings - 1; j++) {
    const a0 = ringStart[j], na = ringSegs[j];
    const b0 = ringStart[j + 1], nb = ringSegs[j + 1];
    if (na === 0) {
      for (let k = 0; k < nb; k++) tri2.push(a0, b0 + k, b0 + k + 1);
      continue;
    }
    let i = 0, k = 0;
    while (i < na || k < nb) {
      let advanceOuter;
      if (i >= na) advanceOuter = true;
      else if (k >= nb) advanceOuter = false;
      else {
        const ta = (i + 1) * nb, tb = (k + 1) * na;   // compare (i+1)/na with (k+1)/nb
        if (tb < ta) advanceOuter = true;
        else if (tb > ta) advanceOuter = false;
        else advanceOuter = ((k + j) & 1) === 0;      // alternate quad diagonals
      }
      if (advanceOuter) { tri2.push(a0 + i, b0 + k, b0 + k + 1); k++; }
      else { tri2.push(a0 + i, b0 + k, a0 + i + 1); i++; }
    }
  }
  const nTri2 = tri2.length / 3;

  // ---- particles ----------------------------------------------------------
  const n = N2 * (NT + 1);
  const mat = new Float32Array(n * 3);
  const rest = new Float32Array(n * 3);
  const rho = new Float32Array(n);
  const rr = Math.min(o.edgeRound, T * 0.5 - 1e-4);
  for (let k = 0; k <= NT; k++) {
    const z = T * (k / NT - 0.5);
    for (let v = 0; v < N2; v++) {
      const p = (v + k * N2) * 3;
      const x = v2[v * 2], y = v2[v * 2 + 1];
      const r = Math.hypot(x, y);
      mat[p] = x; mat[p + 1] = y; mat[p + 2] = z;
      rho[v + k * N2] = r;

      // rest pose: dome the faces, then round the rim corners
      const dArc = 1 - r;                   // distance to the rind arc
      const dCut = y;                       // distance to the cut face
      const dRim = Math.min(dArc, dCut);
      const dome = 1 + o.puff * smooth(0, 0.55, dRim);
      let zz = z * dome;
      let rad = r, yy = y, xx = x;
      const az = Math.abs(zz);
      const halfT = T * 0.5 * dome;
      const cz = az - (halfT - rr);         // > 0 inside the corner band (z)
      // arc corner: pull radially inwards and in z onto a quarter circle
      const ca = rr - dArc;
      if (ca > 0 && cz > 0) {
        const len = Math.hypot(ca, cz);
        if (len > rr) {
          const s = rr / len;
          rad = 1 - rr + ca * s;
          zz = Math.sign(zz) * (halfT - rr + cz * s);
        }
      }
      // cut-face corner: only tuck z in, keep the base flat on the ground
      const cc = rr * 0.6 - dCut;
      if (cc > 0 && cz > 0) {
        const len = Math.hypot(cc, cz);
        const lim = rr * 0.6 + (rr - rr * 0.6);
        if (len > lim) zz = Math.sign(zz) * (halfT - rr + cz * (lim / len));
      }
      if (r > 1e-9) { xx = x * rad / r; yy = y * rad / r; }
      rest[p] = xx; rest[p + 1] = yy; rest[p + 2] = zz;
    }
  }

  // ---- prisms -> tetrahedra ---------------------------------------------
  // Quad faces are always split from the bottom of the lower 2D index to the
  // top of the higher one, so neighbouring prisms agree on every diagonal.
  const tets = new Uint32Array(nTri2 * NT * 12);
  const tetZone = new Uint8Array(nTri2 * NT * 3);
  let tc = 0;
  const s = [0, 0, 0];
  for (let t = 0; t < nTri2; t++) {
    s[0] = tri2[t * 3]; s[1] = tri2[t * 3 + 1]; s[2] = tri2[t * 3 + 2];
    s.sort((p, q) => p - q);
    const cx = (v2[s[0] * 2] + v2[s[1] * 2] + v2[s[2] * 2]) / 3;
    const cy = (v2[s[0] * 2 + 1] + v2[s[1] * 2 + 1] + v2[s[2] * 2 + 1]) / 3;
    const cr = Math.hypot(cx, cy);
    const zone = cr >= o.rindR ? ZONE_RIND : cr >= o.pithR ? ZONE_PITH : ZONE_FLESH;
    for (let k = 0; k < NT; k++) {
      const b = k * N2, u = (k + 1) * N2;
      tc = pushTet(tets, tetZone, tc, rest, zone, s[0] + b, s[1] + b, s[2] + b, s[2] + u);
      tc = pushTet(tets, tetZone, tc, rest, zone, s[0] + b, s[1] + b, s[1] + u, s[2] + u);
      tc = pushTet(tets, tetZone, tc, rest, zone, s[0] + b, s[0] + u, s[1] + u, s[2] + u);
    }
  }
  const numTets = tc;

  // ---- unique edges ---------------------------------------------------------
  const edgeSet = new Map();
  const TE = [0, 1, 0, 2, 0, 3, 1, 2, 1, 3, 2, 3];
  for (let t = 0; t < numTets; t++) {
    for (let e = 0; e < 6; e++) {
      const a = tets[t * 4 + TE[e * 2]], b = tets[t * 4 + TE[e * 2 + 1]];
      const lo = Math.min(a, b), hi = Math.max(a, b);
      edgeSet.set(lo * n + hi, 1);
    }
  }
  const edges = new Uint32Array(edgeSet.size * 2);
  { let i = 0; for (const key of edgeSet.keys()) { edges[i++] = Math.floor(key / n); edges[i++] = key % n; } }

  // ---- boundary surface (faces used by exactly one tet), CCW seen from outside
  const faceMap = new Map();
  const TF = [1, 2, 3, 0, 0, 3, 2, 1, 0, 1, 3, 2, 0, 2, 1, 3]; // 3 face verts + opposite vert
  for (let t = 0; t < numTets; t++) {
    for (let f = 0; f < 4; f++) {
      const a = tets[t * 4 + TF[f * 4]], b = tets[t * 4 + TF[f * 4 + 1]], c = tets[t * 4 + TF[f * 4 + 2]];
      const d = tets[t * 4 + TF[f * 4 + 3]];
      const srt = [a, b, c].sort((p, q) => p - q);
      const key = srt[0] + ':' + srt[1] + ':' + srt[2];
      const prev = faceMap.get(key);
      if (prev) prev.count++;
      else faceMap.set(key, { a, b, c, d, count: 1 });
    }
  }
  const surf = [];
  for (const f of faceMap.values()) {
    if (f.count !== 1) continue;
    // flip so that the normal points away from the opposite vertex
    if (orient(rest, f.a, f.b, f.c, f.d) > 0) surf.push(f.a, f.c, f.b);
    else surf.push(f.a, f.b, f.c);
  }
  const surfTris = new Uint32Array(surf);

  const surfEdgeSet = new Map();
  for (let t = 0; t < surfTris.length; t += 3) {
    for (let e = 0; e < 3; e++) {
      const a = surfTris[t + e], b = surfTris[t + (e + 1) % 3];
      const lo = Math.min(a, b), hi = Math.max(a, b);
      surfEdgeSet.set(lo * n + hi, 1);
    }
  }
  const surfEdges = new Uint32Array(surfEdgeSet.size * 2);
  { let i = 0; for (const key of surfEdgeSet.keys()) { surfEdges[i++] = Math.floor(key / n); surfEdges[i++] = key % n; } }

  const onSurface = new Uint8Array(n);
  for (let i = 0; i < surfTris.length; i++) onSurface[surfTris[i]] = 1;

  return {
    numParticles: n,
    numTets,
    mat,                 // Float32Array(3n)  ideal material coordinates
    rest,                // Float32Array(3n)  rest pose, world space, on the ground
    rho,                 // Float32Array(n)   normalised radius of each particle
    tets: tets.subarray(0, numTets * 4),   // Uint32Array(4m)  positively oriented in the rest pose
    tetZone: tetZone.subarray(0, numTets), // Uint8Array(m)    ZONE_FLESH | ZONE_PITH | ZONE_RIND
    edges,               // Uint32Array(2e)   unique tet edges
    surfTris,            // Uint32Array(3t)   boundary triangles, CCW from outside
    surfEdges,           // Uint32Array(2s)   unique boundary edges
    onSurface,           // Uint8Array(n)
    thickness: T,
    pithR: o.pithR,
    rindR: o.rindR,
    layers: NT,
    particlesPerLayer: N2,
    options: o,
  };
}

function smooth(a, b, x) {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

// signed volume * 6 of (a, b, c, d)
function orient(p, a, b, c, d) {
  const ax = p[a * 3], ay = p[a * 3 + 1], az = p[a * 3 + 2];
  const bx = p[b * 3] - ax, by = p[b * 3 + 1] - ay, bz = p[b * 3 + 2] - az;
  const cx = p[c * 3] - ax, cy = p[c * 3 + 1] - ay, cz = p[c * 3 + 2] - az;
  const dx = p[d * 3] - ax, dy = p[d * 3 + 1] - ay, dz = p[d * 3 + 2] - az;
  return bx * (cy * dz - cz * dy) - by * (cx * dz - cz * dx) + bz * (cx * dy - cy * dx);
}

function pushTet(tets, tetZone, tc, rest, zone, a, b, c, d) {
  const vol = orient(rest, a, b, c, d);
  if (Math.abs(vol) < 1e-12) return tc;              // degenerate, skip
  if (vol < 0) { const t = c; c = d; d = t; }
  tets[tc * 4] = a; tets[tc * 4 + 1] = b; tets[tc * 4 + 2] = c; tets[tc * 4 + 3] = d;
  tetZone[tc] = zone;
  return tc + 1;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { buildSliceMesh, ZONE_FLESH, ZONE_PITH, ZONE_RIND };
}
