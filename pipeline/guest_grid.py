#!/usr/bin/env python3
"""Robust beat grid + bar phase for a guest verse (refines guest_prep.py's grid.json).

beat_this can wander on sparse or pop productions (150+ ms residuals were seen), so the grid is re-fitted
over the verse window by a fine comb search on the full mix's onset envelope: period within +-4% of
the starting estimate (or the scout's measured BPM), phase on a 5 ms grid, score = mean onset strength at
the beat positions (+ half weight at 8th positions). Bar phase (which beat is "1") combines:
  drums     kick on 1/3 vs snare on 2/4 (cannot tell 1 from 3)
  harmony   chroma change at the candidate bar lines (chords move on bar lines; separates 1 from 3)
  lyrics    with analysis.json: line-final words (followed by a >= 0.3 s pause) cluster on beats 3-4,
            line starts on/just before beat 1
  beat_this downbeat agreement
Writes the refined fields back into grid.json (old values kept under "beat_this").
Usage: guest_grid.py CAND_DIR
"""
import json
import os
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remix_render import LIVE_BAR  # noqa: E402

SR = 22050
HOP = 128


def main():
    d = sys.argv[1]
    meta = json.load(open(os.path.join(d, "meta.json")))
    grid = json.load(open(os.path.join(d, "grid.json")))
    vs, ve = float(meta["verse_start_s"]), float(meta["verse_end_s"])
    y, _ = librosa.load(grid["wav"], sr=SR, mono=True)
    w0, w1 = max(0.0, vs - 12), min(len(y) / SR, ve + 6)
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    env = env / (env.max() + 1e-9)
    ft = librosa.frames_to_time(np.arange(len(env)), sr=SR, hop_length=HOP)
    win = (ft >= w0) & (ft <= w1)

    def comb(T, ph):
        t = np.arange(ph, w1, T)
        t = t[t >= w0]
        i = np.clip(np.round(t * SR / HOP).astype(int), 0, len(env) - 1)
        i8 = np.clip(np.round((t + T / 2) * SR / HOP).astype(int), 0, len(env) - 1)
        # max over +-1 frame tolerates sub-frame jitter
        g = np.maximum.reduce([env[np.clip(i + k, 0, len(env) - 1)] for k in (-1, 0, 1)])
        g8 = np.maximum.reduce([env[np.clip(i8 + k, 0, len(env) - 1)] for k in (-1, 0, 1)])
        return g.mean() + 0.5 * g8.mean()

    starts = [grid["period"]]
    if meta.get("native_bpm_measured"):
        starts.append(60.0 / float(meta["native_bpm_measured"]))
    best = (-1, None, None)
    for T0 in starts:
        for T in np.linspace(T0 * 0.96, T0 * 1.04, 161):
            for ph in np.arange(w0, w0 + T, 0.01):
                s = comb(T, ph)
                if s > best[0]:
                    best = (s, T, ph)
    _, T, ph = best
    for T_ in np.linspace(T * 0.997, T * 1.003, 61):           # fine pass
        for ph_ in np.arange(ph - 0.02, ph + 0.02, 0.002):
            s = comb(T_, ph_)
            if s > best[0]:
                best = (s, T_, ph_)
    score, T, ph = best
    beats = np.arange(ph - T * np.ceil(ph / T), len(y) / SR, T)
    beats = beats[beats >= 0]
    # residual vs strongest local onset peak (diagnostic)
    vb = beats[(beats >= w0) & (beats <= w1)]
    dev = []
    for b in vb:
        m = (ft > b - T / 4) & (ft < b + T / 4)
        if m.any() and env[m].max() > 0.2:
            dev.append(ft[m][np.argmax(env[m])] - b)
    resid = float(np.std(dev) * 1000) if dev else float("nan")
    med_dev = float(np.median(dev) * 1000) if dev else float("nan")

    # ---- bar phase evidence on beats inside the window
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256))
    fr = librosa.fft_frequencies(sr=SR, n_fft=2048)
    lowf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[fr < 150]), sr=SR, hop_length=256)
    midf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[(fr > 1500) & (fr < 6000)]), sr=SR, hop_length=256)
    gi = np.clip(librosa.time_to_frames(vb, sr=SR, hop_length=256), 0, len(lowf) - 1)
    kick = np.array([lowf[max(0, i - 2):i + 3].max() for i in gi])
    snare = np.array([midf[max(0, i - 2):i + 3].max() for i in gi])
    C = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=512)
    cf = librosa.time_to_frames(vb, sr=SR, hop_length=512)
    Cb = np.stack([C[:, a:b].mean(axis=1) if b > a else C[:, min(a, C.shape[1] - 1)]
                   for a, b in zip(cf, np.append(cf[1:], cf[-1] + int(T * SR / 512)))])
    Cb = Cb / (np.linalg.norm(Cb, axis=1, keepdims=True) + 1e-9)
    novelty = np.r_[0, 1 - (Cb[1:] * Cb[:-1]).sum(axis=1)]       # chroma change entering each beat
    bt_downs = np.asarray(grid.get("beat_this_downs", []))
    words = []
    an = os.path.join(d, "analysis.json")
    if os.path.exists(an):
        words = json.load(open(an)).get("words", [])
    ends = [w["s"] for w, nx in zip(words, words[1:] + [None]) if nx is None or nx["s"] - w["e"] >= 0.3]
    starts_l = [nx["s"] for w, nx in zip(words, words[1:]) if nx["s"] - w["e"] >= 0.3]
    idx = np.arange(len(vb))
    phases = []
    for p in range(4):
        pos = (idx - p) % 4
        drum = (kick[pos == 0].mean() + kick[pos == 2].mean() - kick[pos % 2 == 1].mean()) / (kick.mean() + 1e-9) \
            + (snare[pos % 2 == 1].mean() - snare[pos % 2 == 0].mean()) / (snare.mean() + 1e-9)
        harm = (novelty[pos == 0].mean() - novelty[pos == 2].mean()) / (novelty.mean() + 1e-9)
        bar0 = vb[pos == 0][0] if (pos == 0).any() else vb[0]
        bpos = lambda t: np.mod((np.asarray(t) - bar0) / T, 4)
        lyr = 0.0
        if len(ends) >= 4:
            e = bpos(ends)
            st = bpos(starts_l) if starts_l else np.array([])
            lyr = float(np.mean((e >= 2.25) & (e < 4.0))) - 0.5 * float(np.mean((e >= 0.25) & (e < 1.75)))
            if len(st):
                lyr += 0.5 * (float(np.mean((st >= 3.0) | (st < 0.5))) - 0.5)
        agree = float(np.mean([np.min(np.abs(vb[pos == 0] - x)) < 0.07 for x in bt_downs])) if len(bt_downs) else 0.0
        phases.append({"phase": p, "drum": round(float(drum), 3), "harm": round(float(harm), 3), "lyrics": round(lyr, 3),
                       "bt_agree": round(agree, 3),
                       "score": round(float(0.5 * drum + 1.0 * harm + 1.5 * lyr + 0.5 * agree), 3)})
    bp = max(phases, key=lambda x: x["score"])["phase"]
    downs_all = vb[bp::4]
    step = 4 * T
    downs_ext = np.arange(downs_all[0] - step * np.ceil(downs_all[0] / step), len(y) / SR, step)
    # verse bar 1: the downbeat at/just after the first verse line minus pickups (first line usually <= 1 beat early)
    j = int(np.argmin(np.abs(downs_ext - (vs + 0.5 * T))))
    bar1 = float(downs_ext[j])
    grid.setdefault("beat_this", {k: grid[k] for k in ("period", "t0", "bpm", "grid_residual_ms", "best_phase", "verse_bar1") if k in grid})
    grid.update({"period": round(float(T), 6), "t0": round(float(beats[0]), 5), "bpm": round(60 / T, 3),
                 "grid_residual_ms": round(resid, 1), "onset_lag_ms": round(med_dev, 1), "comb_score": round(float(score), 4),
                 "phases_refined": phases, "best_phase_refined": bp, "verse_bar1": round(bar1, 4),
                 "alt_bar1": [round(float(x), 4) for x in downs_ext[max(0, j - 1):j + 2]],
                 "bar1_minus_first_line_s": round(bar1 - vs, 3), "verse_bars_est": int(round((ve - bar1) / step)),
                 "stretch_rate": round(step / LIVE_BAR, 5)})
    json.dump(grid, open(os.path.join(d, "grid.json"), "w"), indent=1)
    print(json.dumps({k: grid[k] for k in ("bpm", "grid_residual_ms", "onset_lag_ms", "comb_score", "best_phase_refined",
                                           "verse_bar1", "bar1_minus_first_line_s", "verse_bars_est")}),
          [(p["phase"], p["score"]) for p in phases])


if __name__ == "__main__":
    main()
