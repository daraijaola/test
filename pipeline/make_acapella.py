#!/usr/bin/env python3
"""Final Juice acapella (and matching instrumental) on the live timeline.

1. Ensemble: average the vocal (and instrumental) estimates of several separation models
   (averaging decorrelated model errors is the standard way to beat any single model).
2. Re-place on the live timeline (the HQ pass ran on a crop starting at --crop-start).
3. Keep only Juice: silence everything before --start (DJ tag) and after --end (station jingle),
   with short fades.
4. Gentle downward expander: in the gaps between his phrases, residual beat bleed is pulled down by
   up to --max-cut dB. Slow attack/release and a low threshold so breaths and reverb tails survive.

Usage: make_acapella.py OUT_VOCALS.wav OUT_INST.wav LIVE_MIX.wav --crop-start 12.0 --start 14.40 --end 117.72 MODEL_DIR [MODEL_DIR ...]
"""
import argparse
import os
import sys

import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402


def expander(v, sr, thresh_rel_db=-38.0, max_cut_db=12.0, win_s=0.03, hold_s=0.25, smooth_s=0.08):
    mono = np.abs(v).max(axis=1)
    w = max(1, int(win_s * sr))
    env = np.sqrt(np.maximum(uniform_filter1d(mono.astype(np.float64) ** 2, w), 0.0))
    env_db = 20 * np.log10(env + 1e-9)
    active = env_db[env_db > np.percentile(env_db, 50)]
    ref = np.percentile(active, 95) if len(active) else env_db.max()
    thr = ref + thresh_rel_db
    # how far below threshold, held so short dips inside words don't pump
    below = np.clip(thr - env_db, 0, None)
    below = -maximum_filter1d(-below, int(hold_s * sr))          # hold: take the minimum over the hold window
    gain_db = -np.clip(below, 0, max_cut_db)
    gain_db = uniform_filter1d(gain_db, int(smooth_s * sr))
    return v * (10 ** (gain_db / 20))[:, None].astype(np.float32), float(thr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_vocals")
    ap.add_argument("out_inst")
    ap.add_argument("live_mix")
    ap.add_argument("model_dirs", nargs="+")
    ap.add_argument("--crop-start", type=float, required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--max-cut", type=float, default=12.0)
    a = ap.parse_args()

    live = mx.load(a.live_mix)
    voc = [mx.load(os.path.join(d, "vocals.wav")) for d in a.model_dirs]
    ins = [mx.load(os.path.join(d, "instrumental.wav")) for d in a.model_dirs]
    n = min(len(x) for x in voc)
    v = np.mean([x[:n] for x in voc], axis=0).astype(np.float32)
    i = np.mean([x[:n] for x in ins], axis=0).astype(np.float32)
    pad = mx.sec(a.crop_start)
    full_v = np.zeros_like(live)
    full_i = live.copy()                     # outside the crop the instrumental is unknown: keep the mix
    full_v[pad:pad + n] = v[:len(live) - pad]
    full_i[pad:pad + n] = i[:len(live) - pad]
    full_v = mx.apply_mask(full_v, [(0, a.start), (a.end, len(live) / mx.SR)], fade_s=0.03)
    full_v, thr = expander(full_v, mx.SR, max_cut_db=a.max_cut)
    mx.save(a.out_vocals, full_v)
    mx.save(a.out_inst, full_i)
    corr = [float(np.corrcoef(voc[0][:n].mean(1), x[:n].mean(1))[0, 1]) for x in voc[1:]]
    print(f"ensemble of {len(voc)} models; inter-model vocal correlation {corr}; expander threshold {thr:.1f} dBFS")
    print(f"wrote {a.out_vocals} and {a.out_inst}")


if __name__ == "__main__":
    main()
