#!/usr/bin/env python3
"""Prepare a guest verse candidate for feature_song.py.

1. Decode the guest's full song (cands/<id>/full.*) to 44.1 kHz stereo.
2. Beat grid: beat_this beats -> linear regression around the verse (period T, phase t0).
3. Bar phase: beat_this downbeats + kick/snare evidence (as in analyze_finalist.py).
4. Verse bar 1: the downbeat closest to the first verse line (lrclib timing in meta.json), plus the
   bar count to the verse end.
5. Crop verse -6 s ... +4 s to crop.wav for separation (crop offset stored), then the caller queues separate.py.

Writes cands/<id>/grid.json. Usage: guest_prep.py CAND_DIR
"""
import glob
import json
import os
import subprocess
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR  # noqa: E402

SR = 22050


def main():
    d = sys.argv[1]
    meta = json.load(open(os.path.join(d, "meta.json")))
    src = sorted(glob.glob(os.path.join(d, "full.*")))[0]
    wav = os.path.join(d, "full44.wav")
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ar", "44100", "-ac", "2", wav], check=True)
    from beat_this.inference import File2Beats

    beats, downs = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(wav)
    beats, downs = np.asarray(beats), np.asarray(downs)
    vs, ve = float(meta["verse_start_s"]), float(meta["verse_end_s"])
    sel = beats[(beats > vs - 20) & (beats < ve + 10)]
    T0 = np.median(np.diff(sel))
    k = np.round((sel - sel[0]) / T0)
    T, t0 = np.polyfit(k, sel, 1)
    res = sel - (t0 + T * k)
    y, _ = librosa.load(wav, sr=SR, mono=True)
    dur = len(y) / SR
    grid = t0 + T * np.arange(int(np.floor(-t0 / T)), int((dur - t0) / T) + 1)
    grid = grid[grid >= 0]
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256))
    fr = librosa.fft_frequencies(sr=SR, n_fft=2048)
    lowf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[fr < 150]), sr=SR, hop_length=256)
    midf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[(fr > 1500) & (fr < 6000)]), sr=SR, hop_length=256)
    win = (grid > vs - 20) & (grid < ve + 10)
    gi = np.clip(librosa.time_to_frames(grid, sr=SR, hop_length=256), 0, len(lowf) - 1)
    kick = np.array([lowf[max(0, i - 2):i + 3].max() for i in gi])
    snare = np.array([midf[max(0, i - 2):i + 3].max() for i in gi])
    near_downs = downs[(downs > vs - 20) & (downs < ve + 10)]
    phases = []
    idx = np.arange(len(grid))
    for p in range(4):
        pos = (idx - p) % 4
        m0 = win & (pos == 0)
        agree = np.mean([np.min(np.abs(grid[m0] - x)) < 0.07 for x in near_downs]) if len(near_downs) else 0
        kw, sw = kick[win], snare[win]
        pw = pos[win]
        drum = (kw[pw == 0].mean() + kw[pw == 2].mean() - kw[pw % 2 == 1].mean()) / (kw.mean() + 1e-9) \
            + (sw[pw % 2 == 1].mean() - sw[pw % 2 == 0].mean()) / (sw.mean() + 1e-9)
        phases.append({"phase": p, "downbeat_agree": round(float(agree), 3), "drum_evidence": round(float(drum), 3),
                       "score": round(float(agree + 0.5 * drum), 3)})
    best = max(phases, key=lambda x: x["score"])["phase"]
    bar_downs = grid[best::4]
    j = int(np.argmin(np.abs(bar_downs - vs)))
    bar1 = float(bar_downs[j])
    n_bars = int(round((ve - bar1) / (4 * T)))
    c0 = max(0.0, bar1 - 6.0)
    c1 = min(dur, ve + 4.0)
    full = mx.load(wav)
    mx.save(os.path.join(d, "crop.wav"), full[mx.sec(c0):mx.sec(c1)], subtype="PCM_24")
    out = {"wav": wav, "period": round(float(T), 6), "t0": round(float(t0), 5), "bpm": round(60 / T, 3),
           "grid_residual_ms": round(float(np.std(res) * 1000), 1), "phases": phases, "best_phase": best,
           "verse_bar1": round(bar1, 4), "bar1_minus_first_line_s": round(bar1 - vs, 3),
           "alt_bar1": [round(float(x), 4) for x in bar_downs[max(0, j - 1):j + 2]],
           "verse_bars_est": n_bars, "stretch_rate": round(4 * T / LIVE_BAR, 5),
           "crop_offset_s": round(c0, 4), "crop_end_s": round(c1, 4)}
    json.dump(out, open(os.path.join(d, "grid.json"), "w"), indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
