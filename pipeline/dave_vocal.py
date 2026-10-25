#!/usr/bin/env python3
"""Dave's "Wanna Know" verse as his record sounds, placed on the live 100.45 BPM grid.

Measured basis (work/vocal_research/dave): his rapped verses carry no pitch correction (the verse measures
like pre-Auto-Tune recordings; his engineer: Auto-Tune only "as an effect" on singing), so NO tuning here.
His record vocal is bright, close, even and dry-ish (Sony C800G, light compression at every stage, "always
more high end", a parallel exciter bus). The stem (96 kbps source) is already flat 1-10 kHz with a 2.7 dB
crest, so: 24 dB/oct HPF 85 Hz, side channel -6 dB (codec/separation residue, not his effects), -1.5 dB at
300 Hz, a parallel exciter for the 10-16 kHz air the codec removed, gentle split-band de-esser, no extra
compression (any more flattens it).
Placement: the verse is cut at the spec's points, stretched with Rubber Band R3 (formant + centre focus) to the
live tempo and placed so its bar 1 lands on live bar `land_bar`, keeping his own offset to the drums
(feature_song.guest_track). Writes OUT_DIR/lead.wav (stereo, dry) and OUT_DIR/report.json.

Usage: dave_vocal.py SPEC.json OUT_DIR [--land-bar 51]
"""
import argparse
import json
import os
import sys

import numpy as np
from pedalboard import Pedalboard, PeakFilter
from scipy.signal import butter, sosfilt, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feature_song as fs  # noqa: E402
import mixlib as mx  # noqa: E402

SR = mx.SR


def exciter(m, drive=4.0):
    """Parallel 'air' generator: 3-8 kHz band, soft-clipped (new harmonics above it), keep only > 9 kHz."""
    b = sosfiltfilt(butter(4, [3000, 8000], "band", fs=SR, output="sos"), m)
    pk = np.percentile(np.abs(b), 99.5) + 1e-9
    h = np.tanh(drive * b / pk) * pk / drive
    return sosfiltfilt(butter(4, 9000, "high", fs=SR, output="sos"), h)


def deess(m, ratio=4.0, avg_gr_db=0.7):
    b = sosfilt(butter(4, 6000, "high", fs=SR, output="sos"), m)
    env = np.abs(b)
    out = np.empty_like(env)
    aa, ar = np.exp(-1 / (0.001 * SR)), np.exp(-1 / (0.06 * SR))
    e = 0.0
    for i, v in enumerate(env):
        e = aa * e + (1 - aa) * v if v > e else ar * e + (1 - ar) * v
        out[i] = e
    edb = 20 * np.log10(out + 1e-9)
    act = edb > edb.max() - 50
    thr = np.percentile(edb[act], 90)
    for _ in range(20):                         # find the threshold that gives the asked average reduction
        gr = np.clip(edb - thr, 0, None) * (1 - 1 / ratio)
        if np.mean(gr[act]) <= avg_gr_db:
            break
        thr += 1.0
    gr = np.clip(edb - thr, 0, None) * (1 - 1 / ratio)
    return m - b + b * 10 ** (-gr / 20), float(np.mean(gr[act])), float(gr.max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("out_dir")
    ap.add_argument("--land-bar", type=int, default=51)
    ap.add_argument("--air-db", type=float, default=2.5, help="target lift of the 10-16 kHz band")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    spec["land_bar"] = a.land_bar
    n = mx.sec(fs.live_bar(a.land_bar) + 70.0)
    trk, at, bar1, g_end, rate = fs.guest_track(spec, n)
    x = sosfiltfilt(butter(4, 85.0, "high", fs=SR, output="sos"), trk, axis=0)
    mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2 * 10 ** (-6 / 20)
    mid = Pedalboard([PeakFilter(300, -1.5, 1.0)])(mid[None, :].astype(np.float32), SR)[0]
    # parallel exciter, scaled so the 10-16 kHz band rises by air_db
    ex = exciter(mid)
    hb = lambda s: sosfiltfilt(butter(4, [10000, 16000], "band", fs=SR, output="sos"), s)
    p0 = np.mean(hb(mid) ** 2) + 1e-20
    pe = np.mean(hb(ex) ** 2) + 1e-20
    k = np.sqrt(p0 * (10 ** (a.air_db / 10) - 1) / pe)          # assumes uncorrelated: power adds
    mid = mid + k * ex
    mid, ds_avg, ds_max = deess(mid)
    y = np.stack([mid + side, mid - side], axis=1).astype(np.float32)
    os.makedirs(a.out_dir, exist_ok=True)
    mx.save(os.path.join(a.out_dir, "lead.wav"), y)
    rep = {"land_bar": a.land_bar, "starts_s": round(at, 3), "bar1_s": round(bar1, 3), "ends_s": round(g_end, 3),
           "stretch_rate": round(rate, 5), "exciter_gain": round(float(k), 3), "deess_avg_gr_db": round(ds_avg, 2),
           "deess_max_gr_db": round(ds_max, 1)}
    json.dump(rep, open(os.path.join(a.out_dir, "report.json"), "w"), indent=1)
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
