#!/usr/bin/env python3
"""Render a studio-timeline file onto the live freestyle's timeline.

The DJ played "Reine" key-locked at a constant faster tempo, so the mapping is
linear:   live_t = intercept + slope * studio_t   (slope ~ 98/100).
Given that mapping (from align_reine.py's fine fit), this time-stretches the
studio audio by 1/slope with Rubber Band (R3, pitch unchanged) and pads it so
studio time 0 lands at live time `intercept`. The output can be mixed sample-for-
sample against the live recording and its stems.

Usage: studio_to_live.py STUDIO.wav OUT.wav --slope S --intercept I [--length SECONDS]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("studio")
    ap.add_argument("out")
    ap.add_argument("--slope", type=float, required=True)
    ap.add_argument("--intercept", type=float, required=True)
    ap.add_argument("--length", type=float, default=None)
    a = ap.parse_args()

    x = mx.load(a.studio)
    # rate > 1 speeds up: studio seconds per live second = 1 / slope
    y = mx.stretch(x, 1.0 / a.slope)
    pad = mx.sec(a.intercept)
    if pad >= 0:
        y = np.concatenate([np.zeros((pad, 2), np.float32), y])
    else:
        y = y[-pad:]
    if a.length:
        n = mx.sec(a.length)
        y = y[:n] if len(y) >= n else np.concatenate([y, np.zeros((n - len(y), 2), np.float32)])
    mx.save(a.out, y)
    print(f"wrote {a.out}: {len(y) / mx.SR:.2f}s (slope {a.slope}, intercept {a.intercept})")


if __name__ == "__main__":
    main()
