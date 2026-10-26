#!/usr/bin/env python3
"""Vocal level targets for a rebuilt verse that keep the performance's own phrase dynamics.

The Extended Cut's per-block "vocal LU over beat" was measured against the LIVE beat (the DJ's playback, which
sits 5.5-9.8 dB under the studio instrumental, by a different amount in every block). Copying those numbers onto
the studio beat carried the DJ's fader moves onto Juice's voice (a 6-7 dB drop into bar 26, +3.7 dB in the middle
of "Fourth" at bar 10). Instead:
  target_k = LUFS(acapella_k) - LUFS(studio_beat_k) + c,   c = mean over blocks of (studio beat - live beat)
so the vocal's loudness per block follows the acapella (his performance as heard in the Extended Cut) and the
overall vocal/beat balance stays the Extended Cut's. Block boundaries are moved into the nearest real gap in the
acapella (>= min_gap_s of silence within -1.2..+0.6 bars of the nominal bar line), or where he raps through the bar
line, into the deepest breath (lowest 120 ms of energy) in that window, so no ride lands mid-word (use a short
level_ramp_s, ~0.3 s, so the ride stays inside the breath).

Usage: verse_targets.py ACAPELLA.wav LIVE_BEAT.wav STUDIO_BEAT.wav EXT_BLOCKS.json OUT.json [--min-gap-s 0.33]
EXT_BLOCKS.json: [[bar0, bar1, lu_over_live_beat], ...] (the Extended Cut's blocks; only the bars are used,
plus the live/studio offset c). OUT.json: [[bar0, bar1, target], ...] for song_build level_blocks.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402


def bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def main():
    ap = argparse.ArgumentParser()
    for a in ("acapella", "live_beat", "studio_beat", "ext_blocks", "out"):
        ap.add_argument(a)
    ap.add_argument("--min-gap-s", type=float, default=0.33)
    a = ap.parse_args()
    ac, li, st = mx.load(a.acapella), mx.load(a.live_beat), mx.load(a.studio_beat)
    ext = json.load(open(a.ext_blocks))
    lu = lambda x, b0, b1: mx.lufs(x[mx.sec(bar(b0)):mx.sec(bar(b1))])

    # 10 ms energy of the acapella; "quiet" = 35 dB under its p90 over the verse
    m, hop = ac.mean(axis=1), int(0.01 * mx.SR)
    edb = 10 * np.log10(np.array([np.mean(m[i * hop:(i + 1) * hop] ** 2) for i in range(len(m) // hop)]) + 1e-12)
    t = np.arange(len(edb)) * 0.01
    verse = (t > bar(ext[0][0])) & (t < bar(ext[-1][1]))
    quiet = edb < np.percentile(edb[verse], 90) - 35

    def gaps(t0, t1):
        out, s = [], None
        i0, i1 = int(t0 / 0.01), int(t1 / 0.01)
        for i in range(i0, i1):
            if quiet[i] and s is None:
                s = i
            if (not quiet[i] or i == i1 - 1) and s is not None:
                if (i - s) * 0.01 >= a.min_gap_s:
                    out.append((s * 0.01, i * 0.01))
                s = None
        return out

    bounds, moved = [ext[0][0]], []
    for b0, _, _ in ext[1:]:
        g = gaps(bar(b0 - 1.2), bar(b0 + 0.6))
        if g:
            g0, g1 = min(g, key=lambda ab: abs((ab[0] + ab[1]) / 2 - bar(b0)))
            nb = round((g0 + g1) / 2 - LIVE_BAR1, 6) / LIVE_BAR + 1
            bounds.append(round(nb, 3))
            moved.append([b0, round(nb, 3)])
        else:
            # no silence: the deepest breath, lowest 120 ms of energy (10 ms frames), in the same window
            i0, i1 = int(bar(b0 - 1.2) / 0.01), int(bar(b0 + 0.6) / 0.01)
            w = np.convolve(10 ** (edb[i0:i1] / 10), np.ones(12) / 12, mode="valid")
            tc = (i0 + int(np.argmin(w)) + 6) * 0.01
            nb = (tc - LIVE_BAR1) / LIVE_BAR + 1
            bounds.append(round(nb, 3))
            moved.append([b0, round(nb, 3), "breath"])
    bounds.append(ext[-1][1])
    c = float(np.mean([lu(st, b0, b1) - lu(li, b0, b1) for b0, b1, _ in ext]))
    blocks = [[b0, b1, round(lu(ac, b0, b1) - lu(st, b0, b1) + c, 2)] for b0, b1 in zip(bounds[:-1], bounds[1:])]
    json.dump(blocks, open(a.out, "w"))
    print(json.dumps({"c": round(c, 2), "moved": moved, "blocks": blocks}))


if __name__ == "__main__":
    main()
