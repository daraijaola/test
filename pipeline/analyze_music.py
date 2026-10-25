#!/usr/bin/env python3
"""Beat grid, downbeats, tempo and key for one or more audio files.

beat_this (CPJKU, ISMIR 2024) gives beats/downbeats; Essentia gives key with
several key profiles (they disagree on hip-hop/R&B, so we keep all of them)
plus an independent BPM estimate.

Usage: analyze_music.py OUTPUT.json INPUT [INPUT ...]
"""
import json
import sys

import numpy as np


def analyze(path, f2b):
    import essentia.standard as es

    beats, downbeats = f2b(path)
    ibi = np.diff(beats)
    audio = es.MonoLoader(filename=path, sampleRate=44100)()
    keys = {}
    for prof in ["edma", "bgate", "krumhansl", "temperley", "shaath"]:
        k, s, strength = es.KeyExtractor(profileType=prof)(audio)
        keys[prof] = {"key": f"{k} {s}", "strength": round(float(strength), 3)}
    bpm_ess, _, conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    return {
        "file": path,
        "duration": round(len(audio) / 44100, 3),
        "bpm_beat_this_median": round(float(60 / np.median(ibi)), 3) if len(ibi) else None,
        "bpm_beat_this_mean": round(float(60 / np.mean(ibi)), 3) if len(ibi) else None,
        "ibi_std_ms": round(float(np.std(ibi) * 1000), 2) if len(ibi) else None,
        "bpm_essentia": round(float(bpm_ess), 3),
        "essentia_conf": round(float(conf), 3),
        "keys": keys,
        "beats": [round(float(b), 4) for b in beats],
        "downbeats": [round(float(b), 4) for b in downbeats],
    }


def main():
    from beat_this.inference import File2Beats

    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    out = [analyze(p, f2b) for p in sys.argv[2:]]
    for r in out:
        print(f"{r['file']}: {r['duration']}s bpm(bt)={r['bpm_beat_this_median']} bpm(ess)={r['bpm_essentia']} "
              f"keys={ {k: v['key'] for k, v in r['keys'].items()} } beats={len(r['beats'])} downbeats={len(r['downbeats'])}")
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
