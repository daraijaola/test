#!/usr/bin/env python3
"""Straight vs swung/triplet feel of a track section, on its own beat grid.

Onset-envelope-weighted phase concentration R on four subdivisions of the beat period T:
  straight8 (T/2), straight16 (T/4), triplet8 (T/3), triplet16 (T/6)
plus a swing estimate: where the off-beat 16ths actually land (as a fraction of the 8th; 0.50 = straight,
0.67 = full triplet swing), from the envelope-weighted mean position of the 2nd and 4th 16ths.
Reine (the beat the guest will be on) is the reference: straight 16ths.
Usage: groove_feel.py AUDIO T0 PERIOD START END     (T0 = any beat time; prints JSON)
"""
import json
import sys

import librosa
import numpy as np


def feel(path, t0, T, start, end):
    y, sr = librosa.load(path, sr=22050, mono=True, offset=max(0.0, start), duration=end - start)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=128)
    t = librosa.frames_to_time(np.arange(len(env)), sr=sr, hop_length=128) + max(0.0, start)
    w = env / (env.sum() + 1e-9)
    out = {}
    for name, div in (("straight8", 2), ("straight16", 4), ("triplet8", 3), ("triplet16", 6)):
        s = T / div
        z = (w * np.exp(2j * np.pi * np.mod(t - t0, s) / s)).sum()
        out[name] = round(float(abs(z)), 3)
    # swing: position of the energy in the second half of each 8th (where the off 16th sits)
    ph = np.mod(t - t0, T / 2) / (T / 2)                     # 0..1 within an 8th
    m = (ph > 0.3) & (ph < 0.85)
    out["offbeat16_pos"] = round(float((w[m] * ph[m]).sum() / (w[m].sum() + 1e-9)), 3)
    out["ternary_ratio"] = round(out["triplet16"] / (out["straight16"] + 1e-9), 2)
    return out


if __name__ == "__main__":
    p, t0, T, a, b = sys.argv[1], *map(float, sys.argv[2:6])
    print(json.dumps(feel(p, t0, T, a, b)))
