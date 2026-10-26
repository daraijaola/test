# "Notebook page" sketch for FOURTH QUARTER -- everything procedural.
# Run: /opt/ml/bin/python -I sketch.py
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, zoom
from matplotlib.path import Path
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, 'fonts')
# open-licence (OFL) Google Fonts, fetched into ./fonts on first run
_FONTS = {'ReenieBeanie.ttf': 'reeniebeanie', 'WaitingfortheSunrise.ttf': 'waitingforthesunrise',
          'CoveredByYourGrace.ttf': 'coveredbyyourgrace', 'BebasNeue-Regular.ttf': 'bebasneue', 'Kalam-Bold.ttf': 'kalam'}
os.makedirs(FD, exist_ok=True)
for _f, _fam in _FONTS.items():
    if not os.path.exists(os.path.join(FD, _f)):
        import urllib.request
        urllib.request.urlretrieve(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{_fam}/{_f}', os.path.join(FD, _f))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'sketch_notebook.jpg')

W = H = 2000
SS = 4                       # per-stroke supersampling
rng = np.random.default_rng(1918)

F_LYRIC = os.path.join(FD, 'ReenieBeanie.ttf')
F_NOTE = os.path.join(FD, 'WaitingfortheSunrise.ttf')
F_CAPS = os.path.join(FD, 'CoveredByYourGrace.ttf')
F_BLOCK = os.path.join(FD, 'BebasNeue-Regular.ttf')
F_KALAM = os.path.join(FD, 'Kalam-Bold.ttf')

# ----------------------------------------------------------------------------- noise helpers
def lowres_noise(shape, scale, seed=None):
    r = np.random.default_rng(seed) if seed is not None else rng
    h, w = shape
    gh, gw = max(2, int(h / scale) + 3), max(2, int(w / scale) + 3)
    g = r.standard_normal((gh, gw)).astype(np.float32)
    z = zoom(g, (scale, scale), order=3)[:h, :w]
    z = z[:h, :w]
    if z.shape != (h, w):
        z = np.pad(z, ((0, h - z.shape[0]), (0, w - z.shape[1])), mode='edge')
    return (z - z.mean()) / (z.std() + 1e-6)


def noise1d(t, waves, r=None):
    r = r or rng
    out = np.zeros_like(t)
    for lam, a in waves:
        out += a * np.sin(2 * np.pi * t / lam + r.uniform(0, 2 * np.pi))
    return out


# ----------------------------------------------------------------------------- geometry helpers
def resample(pts, step):
    pts = np.asarray(pts, float)
    d = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(d)])
    L = s[-1]
    n = max(2, int(L / step) + 1)
    t = np.linspace(0, L, n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], 1), t, L


def bez(p0, p1, p2, p3, n=40):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def catmull(pts, n=16, closed=False):
    P = np.asarray(pts, float)
    if closed:
        P = np.vstack([P[-1], P, P[0], P[1]])
    else:
        P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2][None])
    return np.vstack(out)


def ellipse_pts(cx, cy, rx, ry, a0=0, a1=2 * np.pi, n=120, rot=0.0):
    a = np.linspace(a0, a1, n)
    x, y = rx * np.cos(a), ry * np.sin(a)
    c, s = math.cos(rot), math.sin(rot)
    return np.stack([cx + c * x - s * y, cy + s * x + c * y], 1)


def xform(pts, dx=0, dy=0, rot=0.0, sc=1.0):
    P = np.asarray(pts, float) * sc
    c, s = math.cos(rot), math.sin(rot)
    return np.stack([P[:, 0] * c - P[:, 1] * s + dx, P[:, 0] * s + P[:, 1] * c + dy], 1)


# ----------------------------------------------------------------------------- media layers
class Layer:
    def __init__(self, color, name=''):
        self.a = np.zeros((H, W), np.float32)
        self.color = np.array(color, np.float32)
        self.name = name

    def add(self, x0, y0, patch):
        h, w = patch.shape
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(W, x0 + w), min(H, y0 + h)
        if xb <= xa or yb <= ya:
            return
        p = patch[ya - y0:yb - y0, xa - x0:xb - x0]
        reg = self.a[ya:yb, xa:xb]
        self.a[ya:yb, xa:xb] = 1 - (1 - reg) * (1 - p)


PEN = Layer((0.15, 0.19, 0.42), 'pen')
PENCIL = Layer((0.27, 0.27, 0.30), 'pencil')
RED = Layer((0.80, 0.17, 0.19), 'red')
HILITE = Layer((1.0, 0.82, 0.30), 'hilite')
HILITE2 = Layer((1.0, 0.56, 0.20), 'hilite_orange')
COFFEE = Layer((0.60, 0.40, 0.22), 'coffee')


def draw_stroke(layer, pts, width=2.2, pressure=0.9, kind='pen', amp=0.7, occ=None,
                taper=True, skips=True, step=0.5, resample_in=True):
    """Hand stroke: wobble, pressure, ink skips / pencil taper; rendered with 4x AA."""
    P, t, L = resample(pts, step)
    if L < 0.5:
        return
    d = np.gradient(P, axis=0)
    nrm = np.stack([-d[:, 1], d[:, 0]], 1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9
    if amp > 0:
        a_eff = amp * min(1.0, 0.35 + L / 260)
        off = noise1d(t, [(260, 1.0), (95, 0.55), (37, 0.28)]) * a_eff / 1.3
        P = P + nrm * off[:, None]
    p = pressure * (1 + noise1d(t, [(140, 0.07), (45, 0.05), (13, 0.035)]))
    wv = np.full(len(t), width)
    if kind == 'pen':
        p *= 1 + 0.22 * np.exp(-t / 2.5)            # little blob where the ball lands
        if skips and L > 30:
            for _ in range(rng.poisson(L / 170)):
                c = rng.uniform(0, L)
                p *= 1 - 0.42 * np.exp(-((t - c) / rng.uniform(1.2, 3.2)) ** 2)
        if taper:
            p *= np.clip(0.55 + 0.45 * (L - t) / 4.0, 0.55, 1)
    elif kind == 'pencil':
        if taper:
            ramp = np.clip(t / min(14, L / 3 + 1e-3), 0, 1) * np.clip((L - t) / min(22, L / 3 + 1e-3), 0, 1)
            p *= 0.25 + 0.75 * ramp ** 0.7
            wv *= 0.65 + 0.35 * ramp
    elif kind == 'marker':
        pass
    if occ is not None:
        inside = np.zeros(len(P), bool)
        for o in occ:
            inside |= o.contains_points(P)
        p = np.where(inside, 0, p)
    p = np.clip(p, 0, 1)
    pad = width + 3
    x0 = int(math.floor(P[:, 0].min() - pad)); y0 = int(math.floor(P[:, 1].min() - pad))
    x1 = int(math.ceil(P[:, 0].max() + pad)); y1 = int(math.ceil(P[:, 1].max() + pad))
    if x1 < 0 or y1 < 0 or x0 > W or y0 > H:
        return
    w, h = x1 - x0, y1 - y0
    img = Image.new('L', (w * SS, h * SS), 0)
    dr = ImageDraw.Draw(img)
    Q = (P - [x0, y0]) * SS
    for (x, y), pp, ww in zip(Q, p, wv):
        if pp <= 0.003:
            continue
        r = ww * SS / 2
        dr.ellipse([x - r, y - r, x + r, y + r], fill=int(255 * pp))
    patch = np.asarray(img, np.float32).reshape(h, SS, w, SS).mean((1, 3)) / 255.0
    layer.add(x0, y0, patch)


def poly_path(pts):
    return Path(np.asarray(pts, float))


def shape_mask(polys, x0, y0, w, h, sc=2):
    """even-odd fill of polygons into a boolean mask (sc x final res) for region x0,y0,w,h."""
    acc = np.zeros((h * sc, w * sc), bool)
    for poly in polys:
        im = Image.new('1', (w * sc, h * sc), 0)
        q = ((np.asarray(poly) - [x0, y0]) * sc).ravel().tolist()
        if len(q) >= 6:
            ImageDraw.Draw(im).polygon(q, fill=1)
        acc ^= np.asarray(im, bool)
    return acc


def hatch_segments(mask, x0, y0, sc, angle, spacing, jit=0.15, overshoot=1.5, min_len=3,
                   phase=None):
    """Parallel hatch lines clipped to mask; returns list of [p,q] in final coords."""
    h, w = mask.shape
    ca, sa = math.cos(angle), math.sin(angle)
    # direction (ca,sa), normal (-sa,ca)
    cx, cy = w / sc / 2, h / sc / 2
    R = math.hypot(w / sc, h / sc) / 2 + 2
    segs = []
    k = -R + (phase if phase is not None else rng.uniform(0, spacing))
    while k < R:
        ang = angle + rng.normal(0, 0.025)
        c2, s2 = math.cos(ang), math.sin(ang)
        ts = np.arange(-R, R, 0.5)
        xs = cx + -sa * k + c2 * ts
        ys = cy + ca * k + s2 * ts
        xi = np.round(xs * sc).astype(int); yi = np.round(ys * sc).astype(int)
        ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        ins = np.zeros(len(ts), bool)
        ins[ok] = mask[yi[ok], xi[ok]]
        # runs
        dif = np.diff(np.concatenate([[0], ins.astype(int), [0]]))
        starts = np.where(dif == 1)[0]; ends = np.where(dif == -1)[0] - 1
        for a, b in zip(starts, ends):
            if (b - a) * 0.5 < min_len:
                continue
            ea = rng.normal(0, overshoot); eb = rng.normal(0, overshoot)
            ta, tb = ts[a] - ea, ts[b] + eb
            segs.append([[x0 + cx - sa * k + c2 * ta, y0 + cy + ca * k + s2 * ta],
                         [x0 + cx - sa * k + c2 * tb, y0 + cy + ca * k + s2 * tb]])
        k += spacing * (1 + rng.normal(0, jit))
    return segs


def hatch_fill(layer, polys, angle, spacing, width=1.6, pressure=0.75, kind='pen', amp=0.25,
               overshoot=1.5, zig=False, extra_mask=None):
    P = np.vstack(polys)
    x0 = int(P[:, 0].min()) - 4; y0 = int(P[:, 1].min()) - 4
    w = int(P[:, 0].max()) - x0 + 8; h = int(P[:, 1].max()) - y0 + 8
    m = shape_mask(polys, x0, y0, w, h)
    if extra_mask is not None:
        m &= extra_mask(x0, y0, w, h)
    segs = hatch_segments(m, x0, y0, 2, angle, spacing, overshoot=overshoot)
    if zig and segs:
        # chain alternate segments into back-and-forth scribble strokes
        i = 0
        lim = 2.6 * spacing + 5
        while i < len(segs):
            chain = []
            for j in range(rng.integers(3, 8)):
                if i >= len(segs):
                    break
                a, b = segs[i]
                nxt = [a, b] if j % 2 == 0 else [b, a]
                if chain and math.dist(chain[-1], nxt[0]) > lim:
                    break
                chain += nxt
                i += 1
            if len(chain) >= 2:
                draw_stroke(layer, chain, width, pressure * rng.uniform(0.85, 1.05), kind, amp=amp, skips=False)
    else:
        for a, b in segs:
            draw_stroke(layer, [a, b], width, pressure * rng.uniform(0.8, 1.05), kind, amp=amp, skips=False)


# ----------------------------------------------------------------------------- handwriting
_font_cache = {}


def get_font(path, px):
    key = (path, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, px)
    return _font_cache[key]


def write(layer, text, x, y, font_path, size, pressure=0.92, slope=0.0, rot_jit=2.0,
          size_jit=0.035, drift=2.5, track=0.0, grain=0.18, upright=0.0):
    """Hand-write `text` with baseline starting at (x, y). Returns word boxes (x0,x1,ytop,ybase)."""
    base_px = int(size * SS)
    font = get_font(font_path, base_px)
    asc, desc = font.getmetrics()
    total = font.getlength(text) + len(text) * track * SS
    pad = int(size * SS * 0.8)
    cw = int(total * 1.1 + 2 * pad)
    slope_px = abs(math.tan(slope)) * total
    ch_ = int(asc + desc + 2 * pad + slope_px + drift * SS * 2)
    by = pad + asc + (int(slope_px) if slope < 0 else 0)
    canvas = np.zeros((ch_, cw), np.float32)
    cx = float(pad)
    words, cur = [], None
    phase = rng.uniform(0, 6.28)
    for i, chh in enumerate(text):
        adv = font.getlength(text[:i + 1]) - font.getlength(text[:i]) + track * SS
        dy = drift * SS * math.sin(phase + cx / (SS * 260)) + rng.normal(0, 0.5) * SS + math.tan(slope) * (cx - pad)
        if chh != ' ':
            s = 1 + rng.normal(0, size_jit)
            f = get_font(font_path, int(round(base_px * s / 4)) * 4)
            l, t, r, b = f.getbbox(chh, anchor='ls')
            gp = int(size * SS * 0.25)
            gw, gh = r - l + 2 * gp, b - t + 2 * gp
            g = Image.new('L', (gw, gh), 0)
            ImageDraw.Draw(g).text((gp - l, gp - t), chh, font=f, fill=255, anchor='ls')
            g = g.rotate(rng.normal(upright, rot_jit), resample=Image.BICUBIC,
                         center=(gp - l, gp - t))
            ga = np.asarray(g, np.float32) / 255
            gx = int(cx + l - gp + rng.normal(0, 0.4) * SS)
            gy = int(by + dy + t - gp)
            ya, xa = max(0, gy), max(0, gx)
            yb, xb = min(ch_, gy + gh), min(cw, gx + gw)
            canvas[ya:yb, xa:xb] = np.maximum(canvas[ya:yb, xa:xb], ga[ya - gy:yb - gy, xa - gx:xb - gx])
            if cur is None:
                cur = [cx, cx + adv, dy]
            else:
                cur[1] = cx + adv
        else:
            if cur is not None:
                words.append(cur); cur = None
        cx += adv * (1 + rng.normal(0, 0.03))
    if cur is not None:
        words.append(cur)
    # downsample
    hh, ww = canvas.shape[0] // SS, canvas.shape[1] // SS
    patch = canvas[:hh * SS, :ww * SS].reshape(hh, SS, ww, SS).mean((1, 3))
    ox = int(round(x - pad / SS)); oy = int(round(y - by / SS))
    # ink pressure variation
    pn = lowres_noise(patch.shape, 22) * 0.08 + lowres_noise(patch.shape, 6) * 0.05
    patch = np.clip(patch * pressure * (1 + pn), 0, 1)
    layer.add(ox, oy, patch)
    out = []
    for a, b, dy in words:
        out.append((x + (a - pad) / SS, x + (b - pad) / SS, y + dy / SS - size * 0.42, y + dy / SS))
    return out


def strike(layer, box, passes=1, kind='pen', width=2.3, pressure=0.9, scribble=False):
    x0, x1, ytop, yb = box
    ym = (ytop + yb) / 2 + 2
    if scribble:
        pts = []
        n = int((x1 - x0) / 9) + 3
        for i in range(n):
            xx = x0 - 4 + (x1 - x0 + 8) * i / (n - 1)
            pts.append([xx + rng.normal(0, 2), ym + (14 if i % 2 else -14) + rng.normal(0, 3)])
        draw_stroke(layer, catmull(pts, 6), width, pressure, kind, amp=0.6)
        return
    for k in range(passes):
        yy = ym + rng.normal(0, 2.0) + k * 5
        draw_stroke(layer, [[x0 - 6 + rng.normal(0, 2), yy + rng.normal(0, 2)],
                            [(x0 + x1) / 2, yy + rng.normal(0, 1.5)],
                            [x1 + 6 + rng.normal(0, 2), yy - 2 + rng.normal(0, 2)]], width, pressure, kind, amp=0.9)


def underline(layer, x0, x1, y, kind='pen', width=2.3, pressure=0.9, n=1, gap=7):
    for k in range(n):
        yy = y + k * gap
        pts = catmull([[x0 + rng.normal(0, 3), yy + rng.normal(0, 1.5)],
                       [(2 * x0 + x1) / 3, yy + 1 + rng.normal(0, 1.5)],
                       [(x0 + 2 * x1) / 3, yy + rng.normal(0, 1.5)],
                       [x1 + rng.normal(0, 4), yy - 3 + rng.normal(0, 2)]], 12)
        draw_stroke(layer, pts, width, pressure, kind, amp=0.8)


def loop_circle(layer, cx, cy, rx, ry, kind='pen', width=2.3, pressure=0.9, turns=1.15, rot=0.0):
    a0 = rng.uniform(0, 6.28)
    n = int(140 * turns)
    a = np.linspace(a0, a0 + 2 * np.pi * turns, n)
    grow = 1 + np.linspace(0, 0.07, n)
    x = cx + rx * grow * np.cos(a); y = cy + ry * grow * np.sin(a)
    P = xform(np.stack([x - cx, y - cy], 1), cx, cy, rot)
    draw_stroke(layer, P, width, pressure, kind, amp=1.2)


def arrow(layer, pts, kind='pencil', width=2.0, pressure=0.7, head=16):
    P = catmull(pts, 14)
    draw_stroke(layer, P, width, pressure, kind, amp=0.8)
    d = P[-1] - P[-6]
    d /= np.linalg.norm(d)
    for sgn in (1, -1):
        a = math.atan2(d[1], d[0]) + math.pi + sgn * 0.45
        q = P[-1] + head * np.array([math.cos(a), math.sin(a)])
        draw_stroke(layer, [P[-1] + d * 1.0, q], width, pressure, kind, amp=0.3)


# ============================================================================= PAPER
def make_paper():
    base = np.array([0.968, 0.950, 0.898], np.float32)
    lum = (1 + 0.012 * lowres_noise((H, W), 320) + 0.008 * lowres_noise((H, W), 60)
           + 0.006 * lowres_noise((H, W), 9))
    fine = gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 0.7)
    fine /= fine.std()
    lum += 0.016 * fine
    # fibres
    fib = Image.new('L', (W, H), 128)
    d = ImageDraw.Draw(fib)
    for _ in range(2600):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        L = rng.uniform(6, 30); a = rng.uniform(0, np.pi)
        pts = [(x + L * k / 4 * math.cos(a + 0.2 * math.sin(k)), y + L * k / 4 * math.sin(a + 0.2 * math.sin(k))) for k in range(5)]
        d.line(pts, fill=int(128 + rng.choice([-1, 1]) * rng.uniform(4, 10)), width=1)
    fib = gaussian_filter(np.asarray(fib, np.float32), 0.6) - 128
    lum += fib / 255 * 0.9
    paper = base[None, None, :] * lum[..., None]
    # tooth (for graphite)
    tooth = gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 0.85)
    tooth = 0.5 + 0.5 * np.tanh(tooth / tooth.std() * 1.1 + 0.25 * fine)
    return paper.astype(np.float32), tooth.astype(np.float32)


RULE0, RULE_DY = 200, 66
MARGIN_X = 300
HOLES = [(96, 330), (96, 1000), (96, 1670)]


def rule_y(i):
    return RULE0 + RULE_DY * i


def print_rules(paper):
    """Printed (crisp) blue rules, red double margin."""
    im = np.zeros((H, W), np.float32)
    yy = np.arange(H)[:, None].astype(np.float32)
    for i in range(0, 30):
        y = rule_y(i) + 0.3 * math.sin(i * 1.7)
        if y > H + 2:
            break
        prof = np.clip(1.15 - np.abs(yy - y) / 1.25, 0, 1)
        im = np.maximum(im, prof * np.ones((1, W), np.float32))
    dens = 0.58 * (1 + 0.06 * lowres_noise((H, W), 40))
    blue = np.array([0.60, 0.74, 0.88], np.float32)
    a = im * dens
    paper *= (1 - a[..., None] * (1 - blue))
    xx = np.arange(W)[None, :].astype(np.float32)
    m = np.zeros((1, W), np.float32)
    for x in (MARGIN_X, MARGIN_X + 7):
        m = np.maximum(m, np.clip(1.2 - np.abs(xx - x) / 1.2, 0, 1))
    red = np.array([0.90, 0.50, 0.53], np.float32)
    a = (m * np.ones((H, 1), np.float32)) * 0.62 * (1 + 0.05 * lowres_noise((H, W), 50))
    paper *= (1 - a[..., None] * (1 - red))
    return paper


def punch_holes(img):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for hx, hy in HOLES:
        r = 29
        d = np.hypot(xx - hx, yy - hy)
        inside = np.clip(r + 0.5 - d, 0, 1)
        # sheet underneath (same cream, a touch darker) seen through the hole
        under = np.array([0.86, 0.84, 0.78], np.float32)
        # crescent shadow cast by the hole's upper-right rim onto the sheet below
        d2 = np.hypot(xx - (hx - 7), yy - (hy + 7))
        cres = np.clip(d2 - r + 0.5, 0, 1)
        cres = gaussian_filter(cres, 2.0)
        col = under[None, None, :] * (1 - 0.32 * cres[..., None])
        img[:] = img * (1 - inside[..., None]) + col * inside[..., None]
        rim = np.exp(-((d - r) / 1.0) ** 2)
        img *= (1 - 0.22 * rim)[..., None]
    return img


# ============================================================================= TITLE
def title_polys(text, x, y_base, height, track=6.0, seed_rot=0.022):
    """Outline polygons of block letters, per-letter jittered (hand lettering)."""
    fp = FontProperties(fname=F_BLOCK)
    letters = []
    tp_full = TextPath((0, 0), 'H', size=100, prop=fp)
    cap = tp_full.get_extents().height
    sc = height / cap
    cx = x
    for ch in text:
        if ch == ' ':
            cx += 32 * sc + track
            continue
        tp = TextPath((0, 0), ch, size=100, prop=fp)
        ext = tp.get_extents()
        polys = [np.array(p) for p in tp.to_polygons(closed_only=True)]
        rot = rng.normal(0, seed_rot)
        s = 1 + rng.normal(0, 0.025)
        w_ch = ext.width * sc * s
        ox = cx - ext.x0 * sc * s
        out = []
        for p in polys:
            q = np.stack([p[:, 0] * sc * s, -p[:, 1] * sc * s], 1)
            # rotate about letter bottom-center
            q = xform(q - [w_ch / 2, 0], ox + w_ch / 2, y_base + rng.normal(0, 1.5), rot)
            out.append(q)
        # gentle hand-warp of each letter
        warp_a = rng.uniform(0, 6.28)
        for k, q in enumerate(out):
            q[:, 0] += 1.6 * np.sin(q[:, 1] / 37 + warp_a)
            q[:, 1] += 1.3 * np.sin(q[:, 0] / 41 + warp_a * 1.7)
        letters.append((ch, out, (cx, cx + w_ch)))
        cx += w_ch + track
    return letters, cx


TITLE_BASE, TITLE_H = 384, 205


def draw_title():
    letters, x_end = title_polys('FOURTH QUARTER', 338, TITLE_BASE, TITLE_H, track=13)
    allp = [q for _, ps, _ in letters for q in ps]
    off = np.array([10, 9])

    def not_in_letters(x0, y0, w, h):
        return ~shape_mask(allp, x0, y0, w, h)

    # drop shadow: dense, dark, two directions
    for ch, ps, _ in letters:
        sp = [q + off for q in ps]
        hatch_fill(PEN, sp, 0.78, 3.0, width=1.8, pressure=0.9, amp=0.3, overshoot=0.6,
                   extra_mask=not_in_letters, zig=True)
        hatch_fill(PEN, sp, -0.5, 4.2, width=1.6, pressure=0.7, amp=0.3, overshoot=0.6,
                   extra_mask=not_in_letters)
    # interior: diagonal hatching (mid tone)
    for ch, ps, _ in letters:
        hatch_fill(PEN, ps, -0.62, 5.6, width=1.6, pressure=0.7, amp=0.25, overshoot=1.6)
    # outlines, traced twice
    for ch, ps, _ in letters:
        for q in ps:
            qq = np.vstack([q, q[:2]])
            draw_stroke(PEN, qq, 3.0, 0.97, 'pen', amp=0.9)
            draw_stroke(PEN, qq + rng.normal(0, 0.9, 2), 2.2, 0.75, 'pen', amp=1.4)
    return letters


def draw_crown(cx, cy, sc=1.0, rot=-0.22):
    def T(p):
        return xform(p, cx, cy, rot, sc)
    body = [(-92, 24), (-104, -46), (-60, -4), (-46, -64), (-20, -8), (0, -92), (20, -8), (46, -64),
            (60, -4), (104, -46), (92, 24)]
    body = np.array(body, float)
    # slightly curved strokes between vertices
    seg = []
    for i in range(len(body) - 1):
        a, b = body[i], body[i + 1]
        m = (a + b) / 2 + rng.normal(0, 1.5, 2)
        seg.append(catmull([a, m, b], 8)[:-1])
    seg.append(body[-1:])
    outline = np.vstack(seg)
    band_top = np.array([[x, 24 + 9 * (1 - (x / 92) ** 2)] for x in np.linspace(-92, 92, 30)])
    band_bot = np.array([[x, 62 + 11 * (1 - (x / 90) ** 2)] for x in np.linspace(-90, 90, 30)])
    crown_poly = np.vstack([outline, band_bot[::-1]])
    # shading on the right half of the points region
    reg = np.vstack([outline, band_top[::-1]])
    hatch_fill(PEN, [T(reg)], 1.15 + rot, 5.5, width=1.5, pressure=0.6, amp=0.3, overshoot=1.0,
               extra_mask=lambda x0, y0, w, h: _halfmask(x0, y0, w, h, T, 10))
    band = np.vstack([band_top, band_bot[::-1]])
    hatch_fill(PEN, [T(band)], 1.45 + rot, 3.6, width=1.5, pressure=0.8, amp=0.2, overshoot=0.8,
               extra_mask=lambda x0, y0, w, h: ~_jewel_mask(x0, y0, w, h, T))
    for k in range(2):
        j = rng.normal(0, 0.8, 2) * k
        draw_stroke(PEN, T(outline) + j, 2.6 - 0.6 * k, 0.95 - 0.2 * k, 'pen', amp=1.0)
        draw_stroke(PEN, T(band_top) + j, 2.4 - 0.5 * k, 0.9 - 0.2 * k, 'pen', amp=1.0)
        draw_stroke(PEN, T(band_bot) + j, 2.6 - 0.6 * k, 0.95 - 0.2 * k, 'pen', amp=1.0)
        draw_stroke(PEN, T([[-92, 24], [-90, 62]]) + j, 2.4, 0.9, 'pen', amp=0.6)
        draw_stroke(PEN, T([[92, 24], [90, 62]]) + j, 2.4, 0.9, 'pen', amp=0.6)
    for tx, ty in [(-104, -46), (-46, -64), (0, -92), (46, -64), (104, -46)]:
        draw_stroke(PEN, T(ellipse_pts(tx, ty - 9, 8.5, 8.5, n=50, a0=1.3, a1=1.3 + 6.6)), 2.3, 0.92, amp=0.4)
    # jewels on band
    draw_stroke(PEN, T(np.array([[0, 30], [13, 46], [0, 63], [-13, 46], [0, 30], [13, 46]])), 2.3, 0.9, amp=0.4)
    for jx in (-50, 50):
        draw_stroke(PEN, T(ellipse_pts(jx, 45 + 4 * (1 - (jx / 90) ** 2), 8, 8, n=50, a0=0, a1=6.8)), 2.2, 0.9, amp=0.3)
    return T(crown_poly)


def _halfmask(x0, y0, w, h, T, xsplit):
    yy, xx = np.mgrid[0:h * 2, 0:w * 2] / 2.0
    # back-transform to crown-local coordinates approx: use T on two points to get frame
    o = T(np.array([[0.0, 0.0]]))[0]; ex = T(np.array([[1.0, 0.0]]))[0] - o
    ux = ex / np.linalg.norm(ex)
    lx = (xx + x0 - o[0]) * ux[0] + (yy + y0 - o[1]) * ux[1]
    return lx / np.linalg.norm(ex) > xsplit


def _jewel_mask(x0, y0, w, h, T):
    polys = [T(np.array([[0, 27], [16, 46], [0, 66], [-16, 46]]))]
    polys += [T(ellipse_pts(jx, 45 + 4 * (1 - (jx / 90) ** 2), 11, 11, n=30)) for jx in (-50, 50)]
    m = np.zeros((h * 2, w * 2), bool)
    for p in polys:
        m |= shape_mask([p], x0, y0, w, h)
    return m


# ============================================================================= SCOREBOARD
SEG = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd',
       '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abcfgd'}


def seg_poly(name, x, y, w, h, t):
    # returns hexagon polygon for segment, digit box top-left x,y
    hh = h / 2
    def horiz(yc):
        return np.array([[x + t * 0.6, yc], [x + t * 1.1, yc - t / 2], [x + w - t * 1.1, yc - t / 2],
                         [x + w - t * 0.6, yc], [x + w - t * 1.1, yc + t / 2], [x + t * 1.1, yc + t / 2]])
    def vert(xc, ya, yb):
        return np.array([[xc, ya + t * 0.6], [xc + t / 2, ya + t * 1.1], [xc + t / 2, yb - t * 1.1],
                         [xc, yb - t * 0.6], [xc - t / 2, yb - t * 1.1], [xc - t / 2, ya + t * 1.1]])
    return {'a': horiz(y + t / 2), 'g': horiz(y + hh), 'd': horiz(y + h - t / 2),
            'f': vert(x + t / 2, y, y + hh), 'b': vert(x + w - t / 2, y, y + hh),
            'e': vert(x + t / 2, y + hh, y + h), 'c': vert(x + w - t / 2, y + hh, y + h)}[name]


def draw_scoreboard(x, y, rot=0.03):
    W_, H_ = 430, 196
    c = np.array([x + W_ / 2, y + H_ / 2])

    def T(p):
        p = np.asarray(p, float)
        return xform(p - c, c[0], c[1], rot)
    # hanging cables
    for hx in (x + 70, x + W_ - 70):
        draw_stroke(PENCIL, T([[hx, y - 62], [hx + 1, y]]), 2.0, 0.75, 'pencil', amp=0.5)
        draw_stroke(PENCIL, T([[hx + 5, y - 62], [hx + 6, y]]), 1.6, 0.45, 'pencil', amp=0.5)
    # body (rounded rect), double outline
    def rrect(x0, y0, x1, y1, r):
        pts = []
        for (ccx, ccy, a0) in [(x1 - r, y0 + r, -np.pi / 2), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, np.pi / 2), (x0 + r, y0 + r, np.pi)]:
            a = np.linspace(a0, a0 + np.pi / 2, 10)
            pts.append(np.stack([ccx + r * np.cos(a), ccy + r * np.sin(a)], 1))
        P = np.vstack(pts)
        return np.vstack([P, P[:1]])
    outer = rrect(x, y, x + W_, y + H_, 18)
    inner = rrect(x + 11, y + 11, x + W_ - 11, y + H_ - 11, 10)
    # dark frame fill between outer & inner
    hatch_fill(PEN, [T(outer[:-1]), T(inner[:-1])], 0.9, 3.0, width=1.6, pressure=0.85, amp=0.2, overshoot=0.5, zig=True)
    draw_stroke(PEN, T(outer), 2.6, 0.95, amp=1.0)
    draw_stroke(PEN, T(inner), 2.2, 0.9, amp=0.8)
    # divider
    draw_stroke(PEN, T([[x + 128, y + 22], [x + 128, y + H_ - 22]]), 2.2, 0.85, amp=0.6)
    # digits 0:21  (lit = hatched, unlit = faint pencil ghost)
    dw, dh, th = 56, 120, 15
    dx0 = x + 152
    dy0 = y + (H_ - dh) / 2
    for dig, xx in [('0', dx0), ('2', dx0 + 100), ('1', dx0 + 176)]:
        for sname in 'abcdefg':
            poly = T(seg_poly(sname, xx, dy0, dw, dh, th))
            if sname in SEG[dig]:
                hatch_fill(PEN, [poly], 1.2, 2.0, width=1.7, pressure=0.95, amp=0.12, overshoot=0.3, zig=True)
                draw_stroke(PEN, np.vstack([poly, poly[:1]]), 2.0, 0.95, amp=0.3)
            else:
                draw_stroke(PENCIL, np.vstack([poly, poly[:1]]), 1.4, 0.16, 'pencil', amp=0.4)
    # colon
    for cy_ in (dy0 + dh * 0.33, dy0 + dh * 0.67):
        p = T(ellipse_pts(dx0 + 78, cy_, 6, 6, n=30))
        hatch_fill(PEN, [p], 0.5, 2.0, width=1.6, pressure=0.95, amp=0.1, overshoot=0.3)
        draw_stroke(PEN, p, 1.8, 0.9, amp=0.2)
    # Q4 in left panel
    qx, qy = T([[x + 26, y + 134]])[0]
    write(PEN, 'Q4', qx, qy, F_KALAM, 80, pressure=0.97, rot_jit=1.5, slope=rot, track=-4)
    return T(outer)


# ============================================================================= BASKETBALL
def draw_ball(cx, cy, r, layer=PEN):
    circ = ellipse_pts(cx, cy, r, r, a0=0.3, a1=0.3 + 2 * np.pi * 1.04, n=160)
    # shading crescent lower-right
    shade = np.vstack([ellipse_pts(cx, cy, r, r, a0=-0.6, a1=2.2, n=60),
                       ellipse_pts(cx - r * 0.25, cy - r * 0.2, r * 0.95, r * 0.95, a0=2.2, a1=-0.6, n=60)])
    hatch_fill(layer, [shade], 0.9, 3.4, width=1.4, pressure=0.7, amp=0.2, overshoot=0.5)
    draw_stroke(layer, circ, 2.4, 0.93, amp=0.8)
    # seams
    draw_stroke(layer, catmull([[cx - r * 0.98, cy + r * 0.08], [cx, cy - r * 0.06], [cx + r * 0.98, cy + r * 0.1]], 20), 2.0, 0.88, amp=0.4)
    draw_stroke(layer, catmull([[cx + r * 0.1, cy - r * 0.99], [cx - r * 0.06, cy], [cx + r * 0.12, cy + r * 0.99]], 20), 2.0, 0.88, amp=0.4)
    draw_stroke(layer, catmull([[cx - r * 0.62, cy - r * 0.78], [cx - r * 0.38, cy], [cx - r * 0.66, cy + r * 0.74]], 20), 2.0, 0.85, amp=0.4)
    draw_stroke(layer, catmull([[cx + r * 0.66, cy - r * 0.74], [cx + r * 0.42, cy], [cx + r * 0.62, cy + r * 0.78]], 20), 2.0, 0.85, amp=0.4)


# ============================================================================= MICROPHONE (pencil)
def superellipse(cx, cy, a, b, n=2.6, N=200):
    t = np.linspace(0, 2 * np.pi, N)
    x = a * np.sign(np.cos(t)) * np.abs(np.cos(t)) ** (2 / n)
    y = b * np.sign(np.sin(t)) * np.abs(np.sin(t)) ** (2 / n)
    return np.stack([cx + x, cy + y], 1)


def draw_mic(cx, top):
    hx, hy, a, b = cx, top + 135, 84, 128
    head = superellipse(hx, hy, a, b, 2.5)
    head_path = Path(head)
    # construction lines (light, partly erased)
    draw_stroke(PENCIL, [[cx + 2, top - 30], [cx - 3, top + 620]], 1.6, 0.16, 'pencil', amp=1.5)
    draw_stroke(PENCIL, ellipse_pts(hx + 3, hy - 4, a + 8, b + 6, n=160), 1.5, 0.15, 'pencil', amp=2.0)
    draw_stroke(PENCIL, ellipse_pts(cx, top + 560, 128, 26, n=120), 1.5, 0.14, 'pencil', amp=1.5)
    # head shading: right side & bottom
    def right_side(x0, y0, w, h):
        yy, xx = np.mgrid[0:h * 2, 0:w * 2] / 2.0
        X = (xx + x0 - hx) / a; Y = (yy + y0 - hy) / b
        return (X * 0.8 + Y * 0.35) > 0.15
    hatch_fill(PENCIL, [head], 1.05, 4.2, width=2.0, pressure=0.55, kind='pencil', amp=0.4, overshoot=1.0,
               extra_mask=right_side)
    def right_side2(x0, y0, w, h):
        yy, xx = np.mgrid[0:h * 2, 0:w * 2] / 2.0
        X = (xx + x0 - hx) / a; Y = (yy + y0 - hy) / b
        return (X * 0.8 + Y * 0.35) > 0.55
    hatch_fill(PENCIL, [head], 0.35, 4.6, width=2.0, pressure=0.5, kind='pencil', amp=0.4, overshoot=1.0,
               extra_mask=right_side2)
    # grille ribs: curved horizontal bars
    for k in range(-5, 6):
        y0 = hy + k * 21.5
        xs = np.linspace(-a * 1.05, a * 1.05, 60)
        ys = y0 + 7 * (1 - (xs / a) ** 2) * (1 if k >= 0 else 0.6)
        P = np.stack([hx + xs, ys], 1)
        ins = head_path.contains_points(P)
        if ins.sum() < 4:
            continue
        P = P[ins]
        draw_stroke(PENCIL, P, 2.2, 0.85, 'pencil', amp=0.5)
        draw_stroke(PENCIL, P + [0, 4.5], 1.6, 0.45, 'pencil', amp=0.5)
    # centre spine
    for sx in (-9, 9):
        draw_stroke(PENCIL, [[hx + sx, hy - b + 6], [hx + sx * 1.1, hy + b - 6]], 2.2, 0.9, 'pencil', amp=0.6)
    hatch_fill(PENCIL, [np.array([[hx + 1, hy - b + 8], [hx + 9, hy - b + 8], [hx + 10, hy + b - 8], [hx + 1, hy + b - 8]])],
               1.57, 3.0, width=1.8, pressure=0.7, kind='pencil', amp=0.2)
    # head outline (two passes)
    draw_stroke(PENCIL, np.vstack([head, head[:3]]), 2.6, 0.95, 'pencil', amp=1.0)
    draw_stroke(PENCIL, np.vstack([head, head[:3]]) + [1.2, 0.8], 2.0, 0.6, 'pencil', amp=1.6)
    # yoke (U bracket) from head sides
    yk_top = hy + 10
    outer_u = ellipse_pts(hx, yk_top, a + 26, b + 34, a0=0, a1=np.pi, n=90)
    inner_u = ellipse_pts(hx, yk_top, a + 12, b + 20, a0=0, a1=np.pi, n=90)
    occ = [head_path]
    draw_stroke(PENCIL, outer_u, 2.5, 0.9, 'pencil', amp=0.8, occ=occ)
    draw_stroke(PENCIL, inner_u, 2.2, 0.8, 'pencil', amp=0.8, occ=occ)
    yoke_poly = np.vstack([outer_u, inner_u[::-1]])
    hatch_fill(PENCIL, [yoke_poly], 0.2, 3.6, width=1.8, pressure=0.6, kind='pencil', amp=0.3,
               extra_mask=lambda x0, y0, w, h: ~shape_mask([head], x0, y0, w, h))
    # pivot knobs
    for sx in (-1, 1):
        k = ellipse_pts(hx + sx * (a + 19), yk_top, 13, 13, n=60)
        draw_stroke(PENCIL, np.vstack([k, k[:3]]), 2.3, 0.9, 'pencil', amp=0.3)
        hatch_fill(PENCIL, [k], 0.8, 3.0, width=1.6, pressure=0.6, kind='pencil', amp=0.2)
    # stem + stand
    sb = yk_top + b + 34
    draw_stroke(PENCIL, [[hx - 12, sb - 2], [hx - 12, sb + 26]], 2.3, 0.9, 'pencil', amp=0.4)
    draw_stroke(PENCIL, [[hx + 12, sb - 2], [hx + 12, sb + 26]], 2.3, 0.9, 'pencil', amp=0.4)
    draw_stroke(PENCIL, ellipse_pts(hx, sb + 26, 22, 7, n=60), 2.2, 0.85, 'pencil', amp=0.3)
    pole_top, pole_bot = sb + 30, top + 548
    draw_stroke(PENCIL, [[hx - 8, pole_top], [hx - 8, pole_bot]], 2.3, 0.9, 'pencil', amp=0.8)
    draw_stroke(PENCIL, [[hx + 8, pole_top], [hx + 8, pole_bot]], 2.3, 0.9, 'pencil', amp=0.8)
    hatch_fill(PENCIL, [np.array([[hx + 1, pole_top], [hx + 8, pole_top], [hx + 8, pole_bot], [hx + 1, pole_bot]])],
               1.3, 3.2, width=1.6, pressure=0.6, kind='pencil', amp=0.2)
    # base: elliptical puck
    by = top + 562
    top_e = ellipse_pts(hx, by, 120, 24, n=140)
    draw_stroke(PENCIL, np.vstack([top_e, top_e[:3]]), 2.5, 0.92, 'pencil', amp=1.0)
    bot = ellipse_pts(hx, by + 22, 120, 24, a0=0, a1=np.pi, n=80)
    draw_stroke(PENCIL, bot, 2.5, 0.9, 'pencil', amp=1.0)
    draw_stroke(PENCIL, [[hx - 120, by], [hx - 120, by + 22]], 2.2, 0.85, 'pencil', amp=0.3)
    draw_stroke(PENCIL, [[hx + 120, by], [hx + 120, by + 22]], 2.2, 0.85, 'pencil', amp=0.3)
    rim = np.vstack([ellipse_pts(hx, by, 120, 24, a0=0, a1=np.pi, n=60), ellipse_pts(hx, by + 22, 120, 24, a0=np.pi, a1=0, n=60)])
    hatch_fill(PENCIL, [rim], 1.2, 3.4, width=1.8, pressure=0.7, kind='pencil', amp=0.3)
    # cast shadow
    sh = ellipse_pts(hx + 70, by + 40, 150, 22, n=100)
    hatch_fill(PENCIL, [sh], 0.05, 4.5, width=2.2, pressure=0.32, kind='pencil', amp=0.6,
               extra_mask=lambda x0, y0, w, h: ~shape_mask([np.vstack([top_e, bot[::-1]])], x0, y0, w, h))
    return head


# ============================================================================= CAMPFIRE
def draw_log(p0, p1, r, occ=None, layer=PEN, kind='pen'):
    p0, p1 = np.array(p0, float), np.array(p1, float)
    d = p1 - p0; L = np.linalg.norm(d); u = d / L; n = np.array([-u[1], u[0]])
    ang = math.atan2(u[1], u[0])
    sideA = [p0 + n * r, p1 + n * r]
    sideB = [p0 - n * r, p1 - n * r]
    cap = ellipse_pts(p1[0], p1[1], r * 0.45, r, n=80, rot=ang)
    back = ellipse_pts(p0[0], p0[1], r * 0.45, r, a0=np.pi / 2, a1=3 * np.pi / 2, n=50, rot=ang)
    poly = np.vstack([back, ellipse_pts(p1[0], p1[1], r * 0.45, r, a0=-np.pi / 2, a1=np.pi / 2, n=50, rot=ang)])
    pr = Path(poly)
    w = 2.4 if kind == 'pen' else 2.3
    # shading: lower half of log (bark) hatch
    lower = np.vstack([p0 - n * r * 0.05, p1 - n * r * 0.05, p1 - n * r, p0 - n * r])
    if n[1] < 0:
        lower = np.vstack([p0 + n * r * 0.05, p1 + n * r * 0.05, p1 + n * r, p0 + n * r])
    hatch_fill(layer, [lower], ang + 1.2, 4.0, width=1.5, pressure=0.62, kind=kind, amp=0.3, overshoot=0.8,
               extra_mask=(lambda x0, y0, w_, h_: ~_occ_mask(occ, x0, y0, w_, h_)) if occ else None)
    for s in (sideA, sideB):
        draw_stroke(layer, s, w, 0.93, kind, amp=1.2, occ=occ)
    draw_stroke(layer, back, w, 0.9, kind, amp=0.6, occ=occ)
    draw_stroke(layer, np.vstack([cap, cap[:4]]), w, 0.95, kind, amp=0.6, occ=occ)
    # growth rings
    for k, f in enumerate((0.62, 0.32)):
        draw_stroke(layer, ellipse_pts(p1[0], p1[1], r * 0.45 * f, r * f, n=60, rot=ang, a0=0.4, a1=0.4 + 6.0), 1.6, 0.7, kind, amp=0.3, occ=occ)
    # bark ticks
    for _ in range(int(L / 26)):
        tpos = rng.uniform(0.12, 0.88)
        side = rng.choice([-1, 1]) * rng.uniform(0.15, 0.75)
        a = p0 + d * tpos + n * r * side
        draw_stroke(layer, [a, a + u * rng.uniform(14, 30) + n * rng.normal(0, 1.5)], 1.6, 0.75, kind, amp=0.3, occ=occ)
    return poly


def _occ_mask(occ, x0, y0, w, h):
    m = np.zeros((h * 2, w * 2), bool)
    yy, xx = np.mgrid[0:h * 2, 0:w * 2] / 2.0
    pts = np.stack([xx.ravel() + x0, yy.ravel() + y0], 1)
    for o in occ:
        m |= o.contains_points(pts).reshape(m.shape)
    return m


def flame_outline(cx, by, s=1.0):
    # hand-placed control points (y up negative), three tongues
    P = np.array([[-118, 0], [-128, -60], [-112, -120], [-92, -168], [-96, -214], [-78, -180], [-56, -150], [-46, -200],
                  [-30, -262], [-4, -318], [4, -366], [18, -312], [34, -258], [48, -214], [62, -182], [84, -228], [102, -266],
                  [104, -212], [118, -150], [128, -86], [120, -30], [112, 0]], float)
    return P * s + [cx, by]


def draw_campfire(cx, by):
    # flames first (behind logs)
    outer = flame_outline(cx, by, 1.0)
    sp = []
    # build with catmull but keep tips pointy: split at tips
    tips = [4, 10, 16]
    pieces = []
    idx = [0] + tips + [len(outer) - 1]
    for i in range(len(idx) - 1):
        seg = outer[idx[i]:idx[i + 1] + 1]
        pieces.append(catmull(seg, 10)[:-1])
    pieces.append(outer[-1:])
    fl = np.vstack(pieces)
    inner = np.array([[-62, 0], [-70, -50], [-52, -96], [-36, -132], [-34, -100], [-18, -128], [-6, -178], [4, -230],
                      [14, -180], [26, -132], [40, -110], [50, -150], [60, -104], [66, -52], [58, 0]], float) + [cx, by]
    ip = []
    tips_i = [3, 7, 11]
    idx = [0] + tips_i + [len(inner) - 1]
    for i in range(len(idx) - 1):
        ip.append(catmull(inner[idx[i]:idx[i + 1] + 1], 10)[:-1])
    ip.append(inner[-1:])
    inner_c = np.vstack(ip)
    # logs (front) define occluders
    logA = (np.array([cx - 205, by - 4]), np.array([cx + 190, by + 84]))
    logB = (np.array([cx + 212, by + 0]), np.array([cx - 186, by + 90]))
    def log_poly(p0, p1, r):
        u = (p1 - p0) / np.linalg.norm(p1 - p0); ang = math.atan2(u[1], u[0])
        return np.vstack([ellipse_pts(p0[0], p0[1], r * 0.45, r, a0=np.pi / 2, a1=3 * np.pi / 2, n=50, rot=ang),
                          ellipse_pts(p1[0], p1[1], r * 0.45, r, a0=-np.pi / 2, a1=np.pi / 2, n=50, rot=ang)])
    pa = log_poly(*logA, 37); pb = log_poly(*logB, 38)
    occ_logs = [Path(pa), Path(pb)]
    # highlighter wash over flames (orange marker, quick scribble fill)
    marker_fill(np.vstack([fl, fl[:1]]), occ=occ_logs)
    marker_fill(np.vstack([inner_c, inner_c[:1]]), layer=HILITE2, angle=0.5, spacing=15, width=20, pressure=0.55)
    # flame shading: hatch between outer and inner on the right side
    hatch_fill(PEN, [fl, inner_c], 1.0, 5.0, width=1.5, pressure=0.55, amp=0.3, overshoot=1.0,
               extra_mask=lambda x0, y0, w, h: _right_of(x0, y0, w, h, cx - 10) & ~_occ_mask(occ_logs, x0, y0, w, h))
    draw_stroke(PEN, fl, 2.6, 0.95, amp=1.0, occ=occ_logs)
    draw_stroke(PEN, fl + [1.0, -0.8], 1.9, 0.6, amp=1.5, occ=occ_logs)
    draw_stroke(PEN, inner_c, 2.2, 0.85, amp=0.9, occ=occ_logs)
    # back log then front log
    draw_log(*logB, 38, occ=[Path(pa)])
    draw_log(*logA, 37)
    # embers: three sparks drifting up (quiet 999)
    embers = [(cx + 62, by - 400, 7.5), (cx + 112, by - 462, 6.5), (cx + 86, by - 528, 5.5)]
    for (ex, ey, er) in embers:
        p = ellipse_pts(ex, ey, er, er * 1.15, n=40, a0=0, a1=6.6, rot=rng.uniform(0, 3))
        marker_stroke(HILITE2, [[ex - 5, ey + 3], [ex + 5, ey - 3], [ex - 3, ey - 4], [ex + 4, ey + 5]], er * 2.6, 0.7)
        hatch_fill(RED, [p], 0.6, 1.8, width=1.7, pressure=0.95, amp=0.1, overshoot=0.2)
        draw_stroke(RED, p, 2.0, 0.95, amp=0.2)
    # motion ticks below each ember (rising)
    for (ex, ey, er) in embers:
        for k, (ddx, l) in enumerate([(-6, 12), (5, 9)]):
            y0_ = ey + er + 9 + k * 4
            draw_stroke(PENCIL, [[ex + ddx - 2, y0_], [ex + ddx - 5, y0_ + l]], 1.7, 0.55, 'pencil', amp=0.2)
    # ground shadow under the logs
    sh = ellipse_pts(cx + 10, by + 112, 270, 26, n=120)
    hatch_fill(PENCIL, [sh], 0.08, 4.4, width=2.2, pressure=0.38, kind='pencil', amp=0.6,
               extra_mask=lambda x0, y0, w, h: ~_occ_mask(occ_logs, x0, y0, w, h))
    return fl


def _right_of(x0, y0, w, h, xs):
    yy, xx = np.mgrid[0:h * 2, 0:w * 2] / 2.0
    return (xx + x0) > xs


def marker_fill(poly, occ=None, layer=None, angle=-0.55, spacing=19, width=24, pressure=0.62):
    layer = layer or HILITE
    P = poly
    x0 = int(P[:, 0].min()) - 4; y0 = int(P[:, 1].min()) - 4
    w = int(P[:, 0].max()) - x0 + 8; h = int(P[:, 1].max()) - y0 + 8
    m = shape_mask([poly], x0, y0, w, h)
    # shrink a bit so marker stays mostly inside but sloppy
    segs = hatch_segments(m, x0, y0, 2, angle, spacing, jit=0.2, overshoot=6)
    chain = []
    for i, (a, b) in enumerate(segs):
        chain += [a, b] if i % 2 == 0 else [b, a]
    if chain:
        marker_stroke(layer, chain, width, pressure)


def marker_stroke(layer, pts, width, pressure):
    """Felt-tip highlighter: flat even tone, streaky, darker where it doubles back."""
    P, t, L = resample(pts, 1.0)
    pad = width + 4
    x0 = int(P[:, 0].min() - pad); y0 = int(P[:, 1].min() - pad)
    x1 = int(P[:, 0].max() + pad); y1 = int(P[:, 1].max() + pad)
    w, h = x1 - x0, y1 - y0
    acc = np.zeros((h, w), np.float32)
    # draw as separate sub-strokes so overlaps build up (marker is translucent)
    nseg = max(1, int(L / 140))
    bounds = np.linspace(0, len(P) - 1, nseg + 1).astype(int)
    for i in range(nseg):
        Q = P[bounds[i]:bounds[i + 1] + 1]
        img = Image.new('L', (w * 2, h * 2), 0)
        q = ((Q - [x0, y0]) * 2).ravel().tolist()
        if len(Q) >= 2:
            ImageDraw.Draw(img).line(q, fill=255, width=int(width * 2), joint='curve')
        a = np.asarray(img, np.float32).reshape(h, 2, w, 2).mean((1, 3)) / 255
        acc = 1 - (1 - acc) * (1 - a * pressure)
    streak = 1 + 0.10 * lowres_noise((h, w), 3) + 0.05 * lowres_noise((h, w), 30)
    layer.add(x0, y0, np.clip(acc * streak, 0, 1))


def highlight_line(x0, x1, y, h=40, pressure=0.6, slope=-0.004):
    """Highlighter swipe across a line of text (chisel tip: square ends)."""
    L = x1 - x0
    pad = 10
    w_, h_ = int(L + 2 * pad + 20), int(h + 2 * pad + 20)
    ox, oy = int(x0 - pad), int(y - h / 2 - pad - 10)
    yy, xx = np.mgrid[0:h_, 0:w_].astype(np.float32)
    X = xx + ox; Y = yy + oy
    centre = y + slope * (X - x0) + 3 * np.sin((X - x0) / 160)
    edge_top = centre - h / 2 + 1.5 * np.sin(X / 23)
    edge_bot = centre + h / 2 + 1.5 * np.sin(X / 31 + 1)
    a = np.clip(Y - edge_top + 0.5, 0, 1) * np.clip(edge_bot - Y + 0.5, 0, 1)
    a *= np.clip(X - x0 + 0.5, 0, 1) * np.clip(x1 - X + 0.5, 0, 1)
    # stroke start/end pooled ink, streaks along direction
    a *= 1 + 0.25 * np.exp(-(X - x0) / 10) + 0.18 * np.exp(-(x1 - X) / 8)
    streak = gaussian_filter(rng.standard_normal((h_, w_)).astype(np.float32), (0.8, 40))
    streak /= streak.std() + 1e-6
    a *= (1 + 0.07 * streak) * pressure
    # second partial pass
    HILITE.add(ox, oy, np.clip(a, 0, 1))


# ============================================================================= NIGHT: moon, stars, Eiffel
def draw_star(cx, cy, r, layer=PENCIL, kind='pencil', pressure=0.8, rot=0.0):
    pts = []
    for i in range(11):
        a = rot - np.pi / 2 + i * np.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append([cx + rr * math.cos(a), cy + rr * math.sin(a)])
    draw_stroke(layer, np.array(pts), 2.0, pressure, kind, amp=0.4)


def draw_twinkle(cx, cy, r, layer=PENCIL, kind='pencil', pressure=0.75):
    draw_stroke(layer, [[cx, cy - r], [cx, cy + r]], 1.8, pressure, kind, amp=0.2)
    draw_stroke(layer, [[cx - r * 0.8, cy], [cx + r * 0.8, cy]], 1.8, pressure, kind, amp=0.2)


def draw_moon(cx, cy, r):
    outer = ellipse_pts(cx, cy, r, r, a0=0.9, a1=0.9 + 2 * np.pi * 0.62, n=120)
    # crescent: outer arc from a0..a1 then inner arc back
    a0, a1 = np.pi * 0.45, np.pi * 1.85
    oa = ellipse_pts(cx, cy, r, r, a0=a0, a1=a1, n=100)
    ia = ellipse_pts(cx + r * 0.42, cy - r * 0.22, r * 0.86, r * 0.86, a0=a1 - 0.25, a1=a0 + 0.3, n=100)
    poly = np.vstack([oa, ia[::-1][::-1]])
    cres = np.vstack([oa, ia])
    hatch_fill(PENCIL, [cres], 0.9, 3.6, width=1.9, pressure=0.55, kind='pencil', amp=0.3, overshoot=0.8)
    draw_stroke(PENCIL, np.vstack([oa, ia, oa[:2]]), 2.4, 0.9, 'pencil', amp=0.6)


def draw_eiffel(cx, by, Ht=250, layer=PENCIL, kind='pencil'):
    def f(h):  # half width of outer leg at height h
        return 64 * (1 - h / Ht) ** 2.4 + 3.0

    hs = np.linspace(0, Ht - 18, 60)
    for sgn in (-1, 1):
        outer = np.stack([cx + sgn * f(hs), by - hs], 1)
        draw_stroke(layer, outer, 2.2, 0.88, kind, amp=0.5)
    # inner edges of the legs below 1st platform
    h1, h2 = 64, 130
    hl = np.linspace(0, h1, 20)
    for sgn in (-1, 1):
        inner = np.stack([cx + sgn * (f(hl) - 15 * (1 - hl / h1) - 8), by - hl], 1)
        draw_stroke(layer, inner, 1.9, 0.75, kind, amp=0.3)
    # arch
    draw_stroke(layer, ellipse_pts(cx, by, f(0) - 22, 44, a0=np.pi, a1=2 * np.pi, n=50), 1.9, 0.8, kind, amp=0.4)
    # platforms
    for h, ext, th in ((h1, 9, 8), (h2, 6, 6)):
        w = f(h) + ext
        for dy in (0, th):
            draw_stroke(layer, [[cx - w, by - h + dy], [cx + w, by - h + dy - 1]], 2.0, 0.85, kind, amp=0.3)
        draw_stroke(layer, [[cx - w, by - h], [cx - w, by - h + th]], 1.8, 0.8, kind, amp=0.1)
        draw_stroke(layer, [[cx + w, by - h - 1], [cx + w, by - h + th]], 1.8, 0.8, kind, amp=0.1)
    # lattice X's
    for (ha, hb) in ((h1 + 8, h2), (h2 + 6, Ht - 30)):
        n = 3 if ha < h2 else 4
        edges = np.linspace(ha, hb, n + 1)
        for i in range(n):
            ya, yb = edges[i], edges[i + 1]
            draw_stroke(layer, [[cx - f(ya) + 2, by - ya], [cx + f(yb) - 2, by - yb]], 1.4, 0.55, kind, amp=0.2)
            draw_stroke(layer, [[cx + f(ya) - 2, by - ya], [cx - f(yb) + 2, by - yb]], 1.4, 0.55, kind, amp=0.2)
    for sgn in (-1, 1):
        for i in range(3):
            ya, yb = i * h1 / 3, (i + 1) * h1 / 3
            xo_a, xo_b = f(ya), f(yb)
            xi_a, xi_b = f(ya) - 15 * (1 - ya / h1) - 8, f(yb) - 15 * (1 - yb / h1) - 8
            draw_stroke(layer, [[cx + sgn * xo_a, by - ya], [cx + sgn * xi_b, by - yb]], 1.3, 0.5, kind, amp=0.1)
            draw_stroke(layer, [[cx + sgn * xi_a, by - ya], [cx + sgn * xo_b, by - yb]], 1.3, 0.5, kind, amp=0.1)
    # top + spire
    draw_stroke(layer, [[cx - 6, by - Ht + 18], [cx + 6, by - Ht + 18]], 1.8, 0.8, kind, amp=0.1)
    draw_stroke(layer, [[cx, by - Ht + 18], [cx, by - Ht - 14]], 1.8, 0.85, kind, amp=0.1)
    # shading on right leg
    right = np.vstack([np.stack([cx + f(hs) - 1, by - hs], 1),
                       np.stack([cx + f(hs[::-1]) * 0.45, by - hs[::-1]], 1)])
    hatch_fill(layer, [right], 1.2, 4.0, width=1.5, pressure=0.45, kind=kind, amp=0.2, overshoot=0.4)


# ============================================================================= PIANO
def draw_keys(x0, y0, n_white=17, kw=58, kh=232, rot=-0.035):
    c = np.array([x0, y0])

    def T(p):
        return xform(np.asarray(p, float) - c, c[0], c[1], rot)
    total = n_white * kw
    # fade the right end (unfinished sketch) -> pressure falloff
    def pf(x):
        return float(np.clip(1.15 - (x - x0) / total * 0.55, 0.45, 1.0))
    # top & bottom long lines
    draw_stroke(PENCIL, T([[x0 - 4, y0], [x0 + total * 0.5, y0 - 1], [x0 + total + 30, y0 + 1]]), 2.4, 0.9, 'pencil', amp=1.4)
    draw_stroke(PENCIL, T([[x0 - 2, y0 + kh], [x0 + total * 0.5, y0 + kh + 2], [x0 + total + 20, y0 + kh]]), 2.4, 0.85, 'pencil', amp=1.6)
    # front lip (3D) below keys
    draw_stroke(PENCIL, T([[x0 - 2, y0 + kh + 18], [x0 + total + 10, y0 + kh + 19]]), 2.0, 0.65, 'pencil', amp=1.5)
    lip = T([[x0, y0 + kh], [x0 + total, y0 + kh], [x0 + total, y0 + kh + 18], [x0, y0 + kh + 18]])
    hatch_fill(PENCIL, [lip], 0.12, 3.6, width=2.0, pressure=0.32, kind='pencil', amp=0.6, overshoot=4)
    blacks = []
    pattern = [1, 1, 0, 1, 1, 1, 0]  # black key after C, D, (no E), F, G, A, (no B)
    for i in range(n_white + 1):
        xx = x0 + i * kw
        if i <= n_white:
            draw_stroke(PENCIL, T([[xx, y0 + 1], [xx + rng.normal(0, 1), y0 + kh - 1]]), 2.0, 0.85 * pf(xx), 'pencil', amp=0.6)
        if i < n_white and pattern[i % 7]:
            bx = xx + kw - 17 + rng.normal(0, 1.5)
            bw = 34 + rng.normal(0, 1.5)
            bl = 142 + rng.normal(0, 3)
            blacks.append(T([[bx, y0], [bx + bw, y0], [bx + bw + rng.normal(0, 1), y0 + bl], [bx + rng.normal(0, 1), y0 + bl]]))
    for b in blacks:
        f = pf(b[0, 0])
        hatch_fill(PENCIL, [b], 1.25, 2.7, width=2.2, pressure=0.9 * f, kind='pencil', amp=0.25, overshoot=0.6)
        hatch_fill(PENCIL, [b], 0.25, 3.4, width=2.0, pressure=0.6 * f, kind='pencil', amp=0.25, overshoot=0.6)
        draw_stroke(PENCIL, np.vstack([b, b[:1]]), 2.2, 0.9 * f, 'pencil', amp=0.4)
        # highlight bevel left as paper: little slanted gap at bottom
    return T([[x0, y0], [x0 + total, y0], [x0 + total, y0 + kh + 18], [x0, y0 + kh + 18]])


# ============================================================================= COFFEE
def coffee_ring(cx, cy, R, gap=(0.6, 1.5), strength=0.55):
    pad = 30
    s = int(2 * R + 2 * pad)
    ox, oy = int(cx - R - pad), int(cy - R - pad)
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    dx, dy = xx + ox - cx, yy + oy - cy
    th = np.arctan2(dy, dx); d = np.hypot(dx, dy)
    rr = R * (1 + 0.012 * np.sin(3 * th + 1) + 0.008 * np.sin(7 * th + 2) + 0.004 * np.sin(13 * th))
    rim = np.exp(-np.clip(d - rr, 0, None) ** 2 / 2.0 ** 2) * np.exp(-np.clip(rr - d, 0, None) / 6.0)
    rim *= (d < rr + 8)
    inner = 0.07 * (d < rr) * (1 + 0.6 * lowres_noise((s, s), 40))
    # tide lines inside
    rim2 = 0.35 * np.exp(-((d - rr * 0.93) / 2.5) ** 2) * (0.5 + 0.5 * np.sin(2 * th + 0.5))
    ang = np.mod(th - gap[0], 2 * np.pi)
    glen = np.mod(gap[1] - gap[0], 2 * np.pi)
    gapmask = 1 - 0.85 * np.clip(np.minimum(ang, glen - ang) / 0.25, 0, 1) * (ang < glen)
    strength_mod = 1 + 0.35 * np.sin(th * 2 + 0.3) + 0.15 * lowres_noise((s, s), 12)
    a = (0.55 * rim * gapmask + rim2 * gapmask + np.clip(inner, 0, 1)) * strength * strength_mod
    COFFEE.add(ox, oy, np.clip(a, 0, 1))


# ============================================================================= COMPOSE
def main():
    paper, tooth = make_paper()
    paper = print_rules(paper)

    # ---------------- header notes (pencil)
    write(PENCIL, "beat: 'Reine'  -  100 bpm", 350, 92, F_NOTE, 50, pressure=0.72, slope=-0.01)

    # ---------------- title + crown
    letters = draw_title()
    qx0, qx1 = [b for ch, ps, b in letters if ch == 'Q'][0]
    draw_crown((qx0 + qx1) / 2 + 10, TITLE_BASE - TITLE_H - 52, sc=0.8, rot=-0.2)

    # byline under title
    yb = rule_y(4) - 7
    write(PEN, 'Juice WRLD', 1296, yb, F_CAPS, 64, pressure=0.95, rot_jit=1.8, slope=-0.01)
    write(PEN, 'ft. Dave', 1640, yb - 3, F_CAPS, 64, pressure=0.95, rot_jit=1.8, slope=-0.012)

    # ---------------- hook lyrics (ballpoint)
    LS = 80
    write(PEN, "I ain't finna fall down", 342, rule_y(6) - 6, F_LYRIC, LS, slope=-0.008)
    l2 = write(PEN, "Fourth quarter, shorty, I'ma ball out", 342, rule_y(7) - 6, F_LYRIC, LS, slope=-0.006)
    write(PEN, "Don't go to work, baby, call out", 342, rule_y(8) - 6, F_LYRIC, LS, slope=-0.004)
    l4 = write(PEN, "Ain't no way, no slow", 342, rule_y(9) - 6, F_LYRIC, LS, slope=-0.006)
    strike(PEN, l4[-1], passes=2)
    write(PEN, "stall now", l4[-1][1] + 22, rule_y(9) - 8, F_LYRIC, LS, slope=-0.006)
    highlight_line(332, l2[-1][1] + 12, rule_y(7) - 21, h=44, pressure=0.55)

    # margin: brace + HOOK x3
    top, bot = rule_y(5) + 14, rule_y(9) + 8
    mid = (top + bot) / 2
    brace = catmull([[290, top], [272, top + 14], [271, mid - 26], [254, mid], [271, mid + 26],
                     [272, bot - 14], [290, bot]], 12)
    draw_stroke(PENCIL, brace, 2.3, 0.85, 'pencil', amp=0.6)
    write(PENCIL, 'HOOK', 140, mid - 6, F_CAPS, 50, pressure=0.85, rot_jit=2.5)
    write(RED, 'x3', 176, mid + 64, F_CAPS, 56, pressure=0.95)
    loop_circle(RED, 196, mid + 44, 40, 32, 'pen', 2.3, 0.9)

    # ---------------- scoreboard top right + ball
    draw_scoreboard(1452, 540, rot=0.035)
    write(PENCIL, 'clutch.', 1560, rule_y(10) - 8, F_NOTE, 58, pressure=0.8)
    draw_ball(1790, rule_y(10) - 30, 30)
    for k in range(3):
        draw_stroke(PENCIL, [[1738 - k * 4, rule_y(10) - 66 + k * 15], [1752 - k * 4, rule_y(10) - 61 + k * 15]], 1.8, 0.6, 'pencil', amp=0.2)

    # ---------------- title deliberation note
    yT = rule_y(11) - 6
    write(PENCIL, 'title?', 342, yT, F_NOTE, 58, pressure=0.85)
    a = write(PENCIL, 'Campfire', 500, yT, F_NOTE, 58, pressure=0.85)
    strike(PENCIL, a[0], kind='pencil', width=2.3, pressure=0.85, passes=2)
    b = write(PENCIL, 'Reine', 728, yT, F_NOTE, 58, pressure=0.85)
    strike(PENCIL, b[0], kind='pencil', width=2.3, pressure=0.85, passes=1)
    arrow(PENCIL, [[878, yT - 18], [920, yT - 22], [962, yT - 20]], head=12)
    c = write(PEN, 'FOURTH QUARTER', 990, yT + 2, F_CAPS, 54, pressure=0.95, slope=-0.01)
    loop_circle(PEN, (c[0][0] + c[-1][1]) / 2, yT - 17, (c[-1][1] - c[0][0]) / 2 + 22, 34, 'pen', 2.1, 0.75)
    print('title row ends at', c[-1][1])

    # ---------------- mic (pencil) + ON AIR
    mcx = 1650
    draw_mic(mcx, 1012)
    ox, oy = 1784, 1020
    box = np.array([[ox, oy], [ox + 150, oy - 6], [ox + 154, oy + 56], [ox + 3, oy + 60], [ox, oy]], float)
    draw_stroke(RED, catmull(box, 6), 2.4, 0.95, amp=0.6)
    write(RED, 'ON AIR', ox + 15, oy + 45, F_KALAM, 40, pressure=0.97, rot_jit=1.2, slope=-0.035)
    for (bx, by_, a0, l) in [(ox - 8, oy + 10, -2.6, 20), (ox + 20, oy - 12, -2.0, 18),
                             (ox + 132, oy - 16, -1.1, 18), (ox + 162, oy + 4, -0.5, 20)]:
        draw_stroke(RED, [[bx, by_], [bx + l * math.cos(a0), by_ + l * math.sin(a0)]], 2.0, 0.8, amp=0.2)

    r1 = write(PENCIL, 'live on the radio', 846, rule_y(14) - 6, F_NOTE, 56, pressure=0.85)
    write(PENCIL, "Paris, '18", 900, rule_y(15) - 6, F_NOTE, 56, pressure=0.85)
    print('radio note ends', r1[-1][1])
    draw_eiffel(1252, rule_y(16) + 34, Ht=204)
    draw_twinkle(1300, rule_y(14) + 8, 8)
    draw_twinkle(1165, rule_y(16) - 30, 6)

    # night sky over the fire
    draw_moon(430, 1060, 46)
    draw_star(545, 1000, 15, rot=0.2)
    draw_twinkle(360, 1185, 9)
    draw_star(520, 1170, 10, rot=-0.3, pressure=0.6)
    arrow(PENCIL, [[1150, rule_y(14) - 58], [1290, rule_y(13) - 30], [1420, rule_y(13) - 26], [1522, rule_y(13) + 4]], head=14)

    # ---------------- campfire
    draw_campfire(620, 1522)
    write(PENCIL, 'keep it campfire', 912, rule_y(18) - 6, F_NOTE, 56, pressure=0.85)
    write(PENCIL, '(warm. late. slow burn)', 912, rule_y(19) - 8, F_NOTE, 48, pressure=0.75)
    arrow(PENCIL, [[900, rule_y(18) - 34], [850, rule_y(17) - 30], [800, rule_y(17) - 8]], head=12)

    # ---------------- piano + coffee
    draw_keys(345, 1702, n_white=27, kw=57, kh=222, rot=-0.02)
    write(PENCIL, 'Dave - verse 2 on the keys', 900, rule_y(22) - 6, F_NOTE, 54, pressure=0.8)
    coffee_ring(1440, 1262, 148, gap=(2.3, 3.2), strength=0.75)

    # ---------------- compose
    img = paper.copy()
    t = tooth
    for L in (HILITE, HILITE2, COFFEE, PEN, RED, PENCIL):
        a = L.a
        if L is PENCIL:
            a = a * np.clip(0.42 + 0.95 * t, 0, 1.15) ** (1.3 - 0.6 * a)
            a = np.clip(a, 0, 1)
        elif L in (PEN, RED):
            a = a * (0.93 + 0.07 * t)
        elif L in (HILITE, HILITE2):
            a = a * (0.9 + 0.1 * t)
        img *= 1 - a[..., None] * (1 - L.color[None, None, :])
    # graphite smudge near the keys / mic (side of the hand)
    sm = gaussian_filter(PENCIL.a, 9) * 0.10 + gaussian_filter(PENCIL.a, 30) * 0.10
    img *= 1 - sm[..., None] * (1 - np.array([0.55, 0.55, 0.58]))
    img = punch_holes(img)
    # warm lamp light from upper right + vignette
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32) / W
    lamp = np.exp(-((xx - 0.9) ** 2 + (yy + 0.1) ** 2) / 1.3)
    lamp = 0.91 + 0.09 * lamp / lamp.max()
    vig = 1 - 0.10 * (((xx - 0.5) ** 2 + (yy - 0.5) ** 2) / 0.5) ** 1.4
    img *= (lamp * vig)[..., None]
    img *= np.array([1.0, 0.975, 0.925])[None, None, :] ** ((1 - lamp[..., None]) * 1.4)
    img += rng.normal(0, 0.006, img.shape).astype(np.float32)
    out = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(out).save(OUT, quality=93, subsampling=0)
    Image.fromarray(out).resize((200, 200), Image.LANCZOS).save(OUT.replace('.jpg', '_thumb.png'))
    print('saved', OUT)


if __name__ == '__main__':
    main()
