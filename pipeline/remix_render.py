#!/usr/bin/env python3
"""Render a remix: Juice's isolated vocal (live timeline) over a new beat.

Spec (JSON):
{
  "out": "work/renders/remix_x.wav",
  "beat": "path/to/beat.wav|mp3",        # full track or a clip
  "beat_downbeat": 1.234,                # a downbeat in the ORIGINAL beat file (s)
  "beat_bar_len": 2.45,                  # bar length in the original beat (s)
  "transpose": 0,                        # semitones applied to the beat
  "start_bar": 0,                        # beat bar (relative to beat_downbeat) the output starts on
  "intro_bars": 4,                       # bars of beat before Juice's bar 5 downbeat
  "loop": [a, b] | null,                 # beat bars [a, b) to loop if the beat runs out
  "outro_bars": 8,
  "vocal": "work/stems/.../vocals.wav",
  "vocal_rel_lu": 1.5,                   # vocal loudness relative to beat in sung bars (LU)
  "hook": {"src": [t0, t1], "at_bars": [..]} | null,   # optional repeated line (live times)
  "intro_lowpass": true,                 # filtered intro opening up on Juice's entry
  "target_lufs": -10.5
}
Juice's performance spans live bars 5..49 (hum pickup ~0.55 s before bar 6, last word ends 117.72 s).

Usage: remix_render.py SPEC.json
"""
import json
import os
import subprocess
import sys

import numpy as np
from pedalboard import LowpassFilter, Pedalboard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402

LIVE_BAR1, LIVE_BAR = 3.1958, 2.38934   # regression fit of beat_this beats on the live beat (work/analysis/grid_refined.json)
VOCAL_FROM_BAR, VOCAL_END = 5, 117.72
VOCAL_PRE = 0.0                          # vocal region starts exactly at live bar 5 (hum is inside it)


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def build_bed(beat, d0, bar, start_bar, n_bars, loop):
    """Concatenate n_bars of the (already stretched) beat from start_bar, looping bars [a, b) when
    the beat runs out. Contiguous bars are copied sample-for-sample; at a loop jump the previous
    bar's natural continuation is crossfaded (12 ms, equal power) into the new bar."""
    L, xf, D = mx.sec(bar), mx.sec(0.012), mx.sec(d0)

    def get(start, n):
        seg = beat[max(0, start):max(0, start) + n]
        if start < 0:
            seg = np.concatenate([np.zeros((min(n, -start), 2), np.float32), beat[:max(0, n + start)]])
        if len(seg) < n:
            seg = np.concatenate([seg, np.zeros((n - len(seg), 2), np.float32)])
        return seg

    avail = int((len(beat) - D) // L)
    seq, b = [], start_bar
    for _ in range(n_bars):
        if b >= avail or (loop and b >= loop[1]):
            b = loop[0] if loop else max(0, avail - 4)
        seq.append(b)
        b += 1
    out = np.zeros((n_bars * L, 2), np.float32)
    for i, bb in enumerate(seq):
        out[i * L:(i + 1) * L] = get(D + bb * L, L)
        if i > 0 and seq[i - 1] + 1 != bb:
            cont = get(D + (seq[i - 1] + 1) * L, xf)
            out[i * L:i * L + xf] = cont * mx.fade(xf, "out") + out[i * L:i * L + xf] * mx.fade(xf, "in")
    return out, seq


def render(spec):
    beat = mx.load(spec["beat"])
    rate = spec["beat_bar_len"] / LIVE_BAR                       # >1 speeds the beat up
    beat = mx.stretch(beat, rate, spec.get("transpose", 0))
    d0 = spec["beat_downbeat"] / rate
    intro, outro = spec.get("intro_bars", 4), spec.get("outro_bars", 8)
    vocal_bars = int(np.ceil((VOCAL_END - live_bar(VOCAL_FROM_BAR)) / LIVE_BAR))
    n_bars = intro + vocal_bars + outro
    bed, seq = build_bed(beat, d0, LIVE_BAR, spec.get("start_bar", 0), n_bars, spec.get("loop"))

    voc_src = mx.load(spec["vocal"])
    v0 = mx.sec(live_bar(VOCAL_FROM_BAR) - VOCAL_PRE)
    voc = voc_src[v0:mx.sec(VOCAL_END + 0.03)].copy()
    voc[-mx.sec(0.05):] *= mx.fade(mx.sec(0.05), "out")
    at = mx.sec(intro * LIVE_BAR - VOCAL_PRE)
    vtrack = np.zeros_like(bed)
    vtrack = mx.place(vtrack, voc, at)
    hook = spec.get("hook")
    if hook:
        h = voc_src[mx.sec(hook["src"][0]):mx.sec(hook["src"][1])].copy()
        h[:mx.sec(0.02)] *= mx.fade(mx.sec(0.02), "in")
        h[-mx.sec(0.08):] *= mx.fade(mx.sec(0.08), "out")
        # hook times are placed relative to the bar they start in on the live grid
        hb = (hook["src"][0] - LIVE_BAR1) / LIVE_BAR
        frac = hb - np.floor(hb)
        for bar_pos in hook["at_bars"]:
            vtrack = mx.place(vtrack, h, mx.sec((bar_pos + frac) * LIVE_BAR))
    vtrack = vtrack[:len(bed)] if len(vtrack) >= len(bed) else np.concatenate(
        [vtrack, np.zeros((len(bed) - len(vtrack), 2), np.float32)])

    if spec.get("intro_lowpass", True) and intro > 0:
        n = mx.sec(intro * LIVE_BAR)
        lp = Pedalboard([LowpassFilter(cutoff_frequency_hz=900)])(bed[:n], mx.SR)
        ramp = np.clip((np.arange(n) - (n - mx.sec(LIVE_BAR))) / mx.sec(LIVE_BAR), 0, 1)[:, None]
        bed[:n] = lp * (1 - ramp) + bed[:n] * ramp            # last intro bar opens the filter

    vproc = mx.vocal_chain(vtrack, mx.SR, bpm=60 / (LIVE_BAR / 4))
    bproc = mx.beat_chain(bed, mx.SR)
    s0, s1 = at, at + len(voc)
    lv = mx.lufs(vproc[s0:s1]) if s1 - s0 > mx.SR * 3 else -20
    lb = mx.lufs(bproc[s0:s1]) if s1 - s0 > mx.SR * 3 else -20
    g = 10 ** ((spec.get("vocal_rel_lu", 1.5) - (lv - lb)) / 20)
    mix = bproc + vproc * g
    # outro: fade the last 2 bars
    nf = mx.sec(2 * LIVE_BAR)
    mix[-nf:] *= mx.fade(nf, "out", "linear")
    y = mx.master(mix, mx.SR, target_lufs=spec.get("target_lufs", -10.5), ceiling_db=-1.0)
    return y, {"bars": n_bars, "bar_sequence": seq, "stretch_rate": round(rate, 4),
               "vocal_gain_db": round(float(20 * np.log10(g)), 2), "vocal_at_s": round(at / mx.SR, 3)}


def main():
    spec = json.load(open(sys.argv[1]))
    y, info = render(spec)
    os.makedirs(os.path.dirname(spec["out"]) or ".", exist_ok=True)
    mx.save(spec["out"], y)
    info.update({"out": spec["out"], "duration": round(len(y) / mx.SR, 2), "lufs": round(mx.lufs(y), 2),
                 "true_peak": round(mx.true_peak_db(y), 2)})
    print(json.dumps({k: v for k, v in info.items() if k != "bar_sequence"}))
    base = os.path.splitext(spec["out"])[0]
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), spec["out"],
                    "--json", base + ".qa.json", "--png", base + ".qa.png"], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
