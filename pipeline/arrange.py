#!/usr/bin/env python3
"""Render a track from a JSON arrangement plan (the single source of truth for every edit).

Plan format:
{
  "out": "work/renders/x.wav",
  "bpm": 100,                                  # used by tempo-synced effects
  "tracks": {
    "<name>": {
      "chain": "none" | "vocal" | "beat",      # processing applied to the whole track
      "chain_params": {...},                   # kwargs for mixlib.vocal_chain / beat_chain
      "gain_db": 0,
      "clips": [ {"src": "file.wav", "src_start": s, "src_end": e, "at": t,
                  "fade_in": 0.01, "fade_out": 0.01, "curve": "equal_power",
                  "rate": 1.0, "semitones": 0, "gain_db": 0, "mute": [[s, e], ...]} ]
    }
  },
  "master": {"target_lufs": -10.5, "ceiling_db": -1.0, "low_shelf_db": 0, "high_shelf_db": 0, "glue": true} | null,
  "end": null | seconds,                       # hard length (after master); tail fade below
  "tail_fade": 0.0
}
Clip times (src_start/src_end) are in the SOURCE file's timeline, before stretching; "at" is
in the output timeline. Overlapping clips on one track with fades = crossfades.
"mute" regions (source timeline) are silenced with short fades before placement.

Usage: arrange.py PLAN.json [--no-qa]
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402

_cache = {}


def src_audio(path):
    if path not in _cache:
        _cache[path] = mx.load(path)
    return _cache[path]


def render_clip(c):
    x = src_audio(c["src"])
    s = mx.sec(c.get("src_start", 0.0))
    e = mx.sec(c["src_end"]) if c.get("src_end") is not None else len(x)
    seg = x[max(0, s):min(len(x), e)].copy()
    if s < 0:  # allow pre-roll silence
        seg = np.concatenate([np.zeros((-s, 2), np.float32), seg])
    if c.get("mute"):
        seg = mx.apply_mask(seg, [(a - c.get("src_start", 0.0), b - c.get("src_start", 0.0)) for a, b in c["mute"]])
    seg = mx.stretch(seg, c.get("rate", 1.0), c.get("semitones", 0.0), vocal=c.get("vocal", False))
    fi, fo = mx.sec(c.get("fade_in", 0.005)), mx.sec(c.get("fade_out", 0.005))
    curve = c.get("curve", "equal_power")
    if fi > 0:
        seg[:fi] *= mx.fade(min(fi, len(seg)), "in", curve)[:len(seg[:fi])]
    if fo > 0:
        seg[-fo:] *= mx.fade(min(fo, len(seg)), "out", curve)[-len(seg[-fo:]):]
    return seg * 10 ** (c.get("gain_db", 0.0) / 20)


def render(plan):
    bpm = plan.get("bpm", 100.0)
    bus = np.zeros((1, 2), np.float32)
    for name, tr in plan["tracks"].items():
        buf = np.zeros((1, 2), np.float32)
        for c in tr["clips"]:
            buf = mx.place(buf, render_clip(c), mx.sec(c["at"]))
        chain = tr.get("chain", "none")
        params = tr.get("chain_params", {})
        if chain == "vocal":
            buf = mx.vocal_chain(buf, bpm=bpm, **params)
        elif chain == "beat":
            buf = mx.beat_chain(buf, **params)
        if len(buf) > len(bus):
            bus = np.concatenate([bus, np.zeros((len(buf) - len(bus), 2), np.float32)])
        bus[:len(buf)] += buf * 10 ** (tr.get("gain_db", 0.0) / 20)
    if plan.get("master"):
        bus = mx.master(bus, **plan["master"])
    if plan.get("end"):
        bus = bus[:mx.sec(plan["end"])]
    tf = mx.sec(plan.get("tail_fade", 0.0))
    if tf > 0:
        bus[-tf:] *= mx.fade(tf, "out", "linear")
    return bus


def main():
    plan = json.load(open(sys.argv[1]))
    out = render(plan)
    os.makedirs(os.path.dirname(plan["out"]) or ".", exist_ok=True)
    mx.save(plan["out"], out)
    print(f"wrote {plan['out']}  {len(out) / mx.SR:.2f}s  LUFS {mx.lufs(out):.2f}  TP {mx.true_peak_db(out):.2f}")
    if "--no-qa" not in sys.argv:
        edits = sorted({round(c["at"], 3) for t in plan["tracks"].values() for c in t["clips"]})
        base = os.path.splitext(plan["out"])[0]
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), plan["out"],
                        "--edits", ",".join(str(e) for e in edits), "--json", base + ".qa.json",
                        "--png", base + ".qa.png"], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
