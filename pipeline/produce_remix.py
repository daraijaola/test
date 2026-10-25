#!/usr/bin/env python3
"""Final remix production from a bar-level plan (one JSON per remix).

Plan:
{
  "out": "work/renders/final/remix_x.wav",
  "beat": "work/finalists/01/full.mp3",
  "beat_t0": 0.512, "beat_period": 0.6001,     # regression-fitted beat grid of the ORIGINAL beat file
  "bar_phase": 1,                              # which beat (0-3) of that grid is the downbeat
  "transpose": 0,
  "bed": [[out_bar, n_bars, beat_bar], ...],   # copy n_bars of the beat starting at beat_bar to out_bar
  "vocals": [[out_bar, live_bar_from, live_bar_to, {"fade_in": 0.01, "fade_out": 0.08, "trim_start": s, "trim_end": s}], ...],
  "intro_lowpass_bars": 4,                     # low-pass that opens over the first N bars
  "outro_fade_bars": 2,
  "vocal": "work/stems/juice_acapella_hq.wav",
  "vocal_rel_lu": 1.5, "duck_db": 3.0, "target_lufs": -11.0
}
Bars are on Juice's live grid (100.446 BPM); the beat is stretched by bar_len_beat / bar_len_live with
Rubber Band R3 and transposed, then each bar segment is copied sample-exactly (crossfaded only where
the plan jumps). Juice's vocal is taken from the live timeline by bar numbers (+ trims).

Usage: produce_remix.py PLAN.json
"""
import json
import os
import subprocess
import sys

import numpy as np
from pedalboard import LowpassFilter, Pedalboard
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def duck_band(beat, vocal, sr, depth_db=3.0, lo=1000, hi=4000):
    """Dynamic EQ: dip the beat's vocal band by up to depth_db while the vocal is present."""
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    band = sosfiltfilt(sos, beat, axis=0).astype(np.float32)
    env = np.sqrt(np.maximum(uniform_filter1d(vocal.mean(axis=1).astype(np.float64) ** 2, int(0.05 * sr)), 0))
    env_db = 20 * np.log10(env + 1e-9)
    ref = np.percentile(env_db[env_db > np.percentile(env_db, 60)], 90) if np.any(env_db > -80) else -20
    amt = np.clip((env_db - (ref - 30)) / 30, 0, 1)                 # 0 when silent, 1 when singing loud
    amt = uniform_filter1d(amt, int(0.12 * sr))
    g = 10 ** (-depth_db * amt / 20) - 1                             # extra gain applied to the band only
    return beat + band * g[:, None].astype(np.float32)


def main():
    plan = json.load(open(sys.argv[1]))
    sr = mx.SR
    src = mx.load(plan["beat"])
    beat_bar_len = 4 * plan["beat_period"]
    rate = beat_bar_len / LIVE_BAR
    st = mx.stretch(src, rate, plan.get("transpose", 0))
    first_down = (plan["beat_t0"] + plan.get("bar_phase", 0) * plan["beat_period"]) / rate   # stretched timeline
    L = mx.sec(LIVE_BAR)
    xf = mx.sec(0.012)
    n_out = max(b[0] + b[1] for b in plan["bed"])
    bed = np.zeros((n_out * L + mx.sec(4.0), 2), np.float32)

    def beat_bar(k, n=1):
        s = mx.sec(first_down) + k * L
        seg = st[max(0, s):max(0, s) + n * L]
        if s < 0:
            seg = np.concatenate([np.zeros((-s, 2), np.float32), seg])[:n * L]
        return np.concatenate([seg, np.zeros((n * L - len(seg), 2), np.float32)]) if len(seg) < n * L else seg

    prev_end = None
    for out_bar, n, bb in sorted(plan["bed"]):
        seg = beat_bar(bb, n)
        o = out_bar * L
        if prev_end is not None and prev_end != bb:   # jump: crossfade from the natural continuation
            cont = beat_bar(prev_end, 1)[:xf]
            seg = seg.copy()
            seg[:xf] = cont * mx.fade(xf, "out") + seg[:xf] * mx.fade(xf, "in")
        bed[o:o + n * L] = seg
        prev_end = bb + n
    bed = bed[:n_out * L]

    lp_bars = plan.get("intro_lowpass_bars", 0)
    if lp_bars:
        n = lp_bars * L
        lp = Pedalboard([LowpassFilter(cutoff_frequency_hz=700)])(bed[:n], sr)
        ramp = np.clip((np.arange(n) - (n - L)) / L, 0, 1)[:, None] ** 2
        bed[:n] = lp * (1 - ramp) + bed[:n] * ramp

    vsrc = mx.load(plan["vocal"])
    vt = np.zeros_like(bed)
    for out_bar, lb_from, lb_to, opt in plan["vocals"]:
        a = live_bar(lb_from) + opt.get("trim_start", 0.0)
        b = live_bar(lb_to) + opt.get("trim_end", 0.0)
        seg = vsrc[mx.sec(a):mx.sec(b)].copy()
        fi, fo = mx.sec(opt.get("fade_in", 0.01)), mx.sec(opt.get("fade_out", 0.08))
        seg[:fi] *= mx.fade(fi, "in")
        seg[-fo:] *= mx.fade(fo, "out")
        vt = mx.place(vt, seg, out_bar * L + mx.sec(opt.get("trim_start", 0.0)))
    vt = vt[:len(bed)]

    vproc = mx.vocal_chain(vt, sr, bpm=60 / (LIVE_BAR / 4))
    bproc = mx.beat_chain(bed, sr, vocal_pocket_db=-1.0)
    bproc = duck_band(bproc, vt, sr, plan.get("duck_db", 3.0))
    sung = np.abs(vt).max(axis=1) > 1e-4
    lv = mx.lufs(vproc[sung]) if sung.sum() > sr * 5 else -20
    lb = mx.lufs(bproc[sung]) if sung.sum() > sr * 5 else -20
    g = 10 ** ((plan.get("vocal_rel_lu", 1.5) - (lv - lb)) / 20)
    mix = bproc + vproc * g
    fb = plan.get("outro_fade_bars", 0)
    if fb:
        nf = fb * L
        mix[-nf:] *= mx.fade(nf, "out", "linear")
    y = mx.master(mix, sr, target_lufs=plan.get("target_lufs", -11.0), ceiling_db=-1.0)
    os.makedirs(os.path.dirname(plan["out"]), exist_ok=True)
    mx.save(plan["out"], y)
    edits = sorted({round(b[0] * LIVE_BAR, 3) for b in plan["bed"]} | {round(v[0] * LIVE_BAR, 3) for v in plan["vocals"]})
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), plan["out"],
                    "--edits", ",".join(map(str, edits)), "--json", plan["out"][:-4] + ".qa.json",
                    "--png", plan["out"][:-4] + ".qa.png"], check=False, stdout=subprocess.DEVNULL)
    print(json.dumps({"out": plan["out"], "duration": round(len(y) / sr, 2), "lufs": round(mx.lufs(y), 2),
                      "true_peak": round(mx.true_peak_db(y), 2), "stretch_rate": round(rate, 5),
                      "vocal_gain_db": round(float(20 * np.log10(g)), 2)}))


if __name__ == "__main__":
    main()
