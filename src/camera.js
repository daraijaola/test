'use strict';
/*
 * camera.js — a small orbit camera shared by the renderer (matrices) and the
 * pointer code (picking rays), so both always agree on the projection.
 *
 * Conventions: right-handed world, +y up, column-major 4x4 matrices in
 * Float32Array(16), WebGPU clip space (x, y in [-1, 1], z in [0, 1]).
 * `shiftX / shiftY` move the principal point in NDC so the subject can sit in
 * the middle of the free area between the heading and the control panel.
 */
class Camera {
  constructor() {
    this.target = new Float32Array([0, 0.47, 0]);
    this.yaw = 0.42;            // radians around +y, 0 looks down -z from +z
    this.pitch = 0.24;          // radians above the horizon
    this.distance = 6.0;
    this.fovY = 30 * Math.PI / 180;
    this.near = 0.1;
    this.far = 60;
    this.aspect = 1;
    this.shiftX = 0;
    this.shiftY = 0;

    this.eye = new Float32Array(3);
    this.right = new Float32Array(3);
    this.up = new Float32Array(3);
    this.forward = new Float32Array(3);   // from eye towards target
    this.view = new Float32Array(16);
    this.proj = new Float32Array(16);
    this.viewProj = new Float32Array(16);
    this.invViewProj = new Float32Array(16);
    this.update();
  }

  /** Choose the distance so a box of half extents (halfW, halfH) around the target fits. */
  fit(aspect, halfW, halfH) {
    this.aspect = aspect;
    const t = Math.tan(this.fovY * 0.5);
    this.distance = Math.max(halfH / t, halfW / (t * aspect));
    this.update();
  }

  update() {
    const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    const e = this.eye, t = this.target, f = this.forward, r = this.right, u = this.up;
    e[0] = t[0] + this.distance * cp * sy;
    e[1] = t[1] + this.distance * sp;
    e[2] = t[2] + this.distance * cp * cy;
    f[0] = -cp * sy; f[1] = -sp; f[2] = -cp * cy;
    r[0] = cy; r[1] = 0; r[2] = -sy;                       // normalize(cross(f, +y))
    u[0] = r[1] * f[2] - r[2] * f[1];                      // cross(r, f)
    u[1] = r[2] * f[0] - r[0] * f[2];
    u[2] = r[0] * f[1] - r[1] * f[0];

    const v = this.view;
    v[0] = r[0]; v[4] = r[1]; v[8] = r[2];   v[12] = -(r[0] * e[0] + r[1] * e[1] + r[2] * e[2]);
    v[1] = u[0]; v[5] = u[1]; v[9] = u[2];   v[13] = -(u[0] * e[0] + u[1] * e[1] + u[2] * e[2]);
    v[2] = -f[0]; v[6] = -f[1]; v[10] = -f[2]; v[14] = (f[0] * e[0] + f[1] * e[1] + f[2] * e[2]);
    v[3] = 0; v[7] = 0; v[11] = 0; v[15] = 1;

    const p = this.proj;
    const g = 1 / Math.tan(this.fovY * 0.5);
    const n = this.near, fa = this.far;
    p.fill(0);
    p[0] = g / this.aspect;
    p[5] = g;
    p[8] = -this.shiftX;          // clip.x += shiftX * clip.w  (clip.w = -view.z)
    p[9] = -this.shiftY;
    p[10] = fa / (n - fa);
    p[11] = -1;
    p[14] = n * fa / (n - fa);

    Camera.mul(this.viewProj, p, v);
    Camera.invert(this.invViewProj, this.viewProj);
    return this;
  }

  /** World-space ray through NDC (nx, ny), both in [-1, 1], y up. */
  rayFromNdc(nx, ny, out) {
    const o = out || { origin: new Float32Array(3), dir: new Float32Array(3) };
    const t = Math.tan(this.fovY * 0.5);
    const vx = (nx - this.shiftX) * t * this.aspect;
    const vy = (ny - this.shiftY) * t;
    const r = this.right, u = this.up, f = this.forward;
    let dx = f[0] + r[0] * vx + u[0] * vy;
    let dy = f[1] + r[1] * vx + u[1] * vy;
    let dz = f[2] + r[2] * vx + u[2] * vy;
    const l = 1 / Math.hypot(dx, dy, dz);
    o.origin[0] = this.eye[0]; o.origin[1] = this.eye[1]; o.origin[2] = this.eye[2];
    o.dir[0] = dx * l; o.dir[1] = dy * l; o.dir[2] = dz * l;
    return o;
  }

  /** World point -> [ndcX, ndcY, depth01, viewDepth]. */
  project(x, y, z, out) {
    const m = this.viewProj, o = out || new Float32Array(4);
    const cx = m[0] * x + m[4] * y + m[8] * z + m[12];
    const cy = m[1] * x + m[5] * y + m[9] * z + m[13];
    const cz = m[2] * x + m[6] * y + m[10] * z + m[14];
    const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    o[0] = cx / cw; o[1] = cy / cw; o[2] = cz / cw; o[3] = cw;
    return o;
  }

  static mul(out, a, b) {
    for (let c = 0; c < 4; c++) {
      const b0 = b[c * 4], b1 = b[c * 4 + 1], b2 = b[c * 4 + 2], b3 = b[c * 4 + 3];
      out[c * 4] = a[0] * b0 + a[4] * b1 + a[8] * b2 + a[12] * b3;
      out[c * 4 + 1] = a[1] * b0 + a[5] * b1 + a[9] * b2 + a[13] * b3;
      out[c * 4 + 2] = a[2] * b0 + a[6] * b1 + a[10] * b2 + a[14] * b3;
      out[c * 4 + 3] = a[3] * b0 + a[7] * b1 + a[11] * b2 + a[15] * b3;
    }
    return out;
  }

  static invert(out, m) {
    const a00 = m[0], a01 = m[1], a02 = m[2], a03 = m[3];
    const a10 = m[4], a11 = m[5], a12 = m[6], a13 = m[7];
    const a20 = m[8], a21 = m[9], a22 = m[10], a23 = m[11];
    const a30 = m[12], a31 = m[13], a32 = m[14], a33 = m[15];
    const b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10;
    const b02 = a00 * a13 - a03 * a10, b03 = a01 * a12 - a02 * a11;
    const b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12;
    const b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30;
    const b08 = a20 * a33 - a23 * a30, b09 = a21 * a32 - a22 * a31;
    const b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
    let det = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
    det = det ? 1 / det : 0;
    out[0] = (a11 * b11 - a12 * b10 + a13 * b09) * det;
    out[1] = (a02 * b10 - a01 * b11 - a03 * b09) * det;
    out[2] = (a31 * b05 - a32 * b04 + a33 * b03) * det;
    out[3] = (a22 * b04 - a21 * b05 - a23 * b03) * det;
    out[4] = (a12 * b08 - a10 * b11 - a13 * b07) * det;
    out[5] = (a00 * b11 - a02 * b08 + a03 * b07) * det;
    out[6] = (a32 * b02 - a30 * b05 - a33 * b01) * det;
    out[7] = (a20 * b05 - a22 * b02 + a23 * b01) * det;
    out[8] = (a10 * b10 - a11 * b08 + a13 * b06) * det;
    out[9] = (a01 * b08 - a00 * b10 - a03 * b06) * det;
    out[10] = (a30 * b04 - a31 * b02 + a33 * b00) * det;
    out[11] = (a21 * b02 - a20 * b04 - a23 * b00) * det;
    out[12] = (a11 * b07 - a10 * b09 - a12 * b06) * det;
    out[13] = (a00 * b09 - a01 * b07 + a02 * b06) * det;
    out[14] = (a31 * b01 - a30 * b03 - a32 * b00) * det;
    out[15] = (a20 * b03 - a21 * b01 + a22 * b00) * det;
    return out;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { Camera };
}
