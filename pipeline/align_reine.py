#!/usr/bin/env python3
"""Locate the live freestyle's beat inside the studio "Reine" and measure how it was played.

Answers: which part of the studio song did the DJ play, at what speed (tempo
ratio), and did he cut/loop/rewind anywhere? Works in two passes:
  1. coarse: windowed cross-correlation of chroma + onset features
     (robust to the vocal on top) -> a (live_time -> studio_time) map;
  2. fine: sample-level cross-correlation of waveforms around anchor points
     -> offset to the sample and drift across the clip.

Usage: align_reine.py LIVE.wav STUDIO.wav OUT.json [--live-start S --live-end S]
LIVE ideally is the separated live instrumental; STUDIO ideally the studio
instrumental (full mixes work too, just less precisely).
"""
import argparse
import json

import librosa
import numpy as np
from scipy.signal import correlate

SR = 22050
HOP = 512


def features(y):
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    n = min(chroma.shape[1], len(onset))
    chroma, onset = chroma[:, :n], onset[:n]
    chroma = (chroma - chroma.mean(axis=1, keepdims=True)) / (chroma.std(axis=1, keepdims=True) + 1e-6)
    onset = (onset - onset.mean()) / (onset.std() + 1e-6)
    return np.vstack([chroma, 2.0 * onset[None, :]])


def best_lag(win, ref):
    """Normalised cross-correlation of a feature window against the whole reference."""
    w = win.shape[1]
    scores = np.zeros(ref.shape[1] - w + 1)
    for k in range(win.shape[0]):
        scores += correlate(ref[k], win[k], mode="valid")
    # normalise by reference window energy
    energy = np.sqrt(np.convolve((ref ** 2).sum(axis=0), np.ones(w), mode="valid")) + 1e-6
    scores /= energy * np.sqrt((win ** 2).sum())
    i = int(np.argmax(scores))
    second = np.max(np.delete(scores, np.arange(max(0, i - 20), min(len(scores), i + 20))))
    return i, float(scores[i]), float(scores[i] - second)


def fine_offset(live, studio, t_live, t_studio_guess, sr, win=4.0, search=0.25):
    a = live[int(t_live * sr):int((t_live + win) * sr)]
    s0 = int((t_studio_guess - search) * sr)
    b = studio[max(0, s0):s0 + int((win + 2 * search) * sr)]
    if len(a) < sr or len(b) <= len(a):
        return None, 0.0
    c = correlate(b, a, mode="valid")
    norm = np.sqrt(np.convolve(b ** 2, np.ones(len(a)), mode="valid")) * np.sqrt((a ** 2).sum()) + 1e-9
    c = c / norm
    i = int(np.argmax(c))
    return (max(0, s0) + i) / sr, float(c[i])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("live")
    ap.add_argument("studio")
    ap.add_argument("out")
    ap.add_argument("--live-start", type=float, default=0.0)
    ap.add_argument("--live-end", type=float, default=None)
    ap.add_argument("--win", type=float, default=6.0)
    ap.add_argument("--step", type=float, default=2.0)
    a = ap.parse_args()

    live, _ = librosa.load(a.live, sr=SR, mono=True)
    studio, _ = librosa.load(a.studio, sr=SR, mono=True)
    fl, fs = features(live), features(studio)
    fps = SR / HOP
    end = a.live_end or len(live) / SR
    rows = []
    t = a.live_start
    while t + a.win <= end:
        i0, i1 = int(t * fps), int((t + a.win) * fps)
        lag, score, margin = best_lag(fl[:, i0:i1], fs)
        rows.append({"live_t": round(t, 3), "studio_t": round(lag / fps, 3),
                     "offset": round(lag / fps - t, 3), "score": round(score, 3), "margin": round(margin, 3)})
        t += a.step

    # robust linear fit studio_t = slope * live_t + intercept over confident windows
    good = [r for r in rows if r["score"] > 0.35 and r["margin"] > 0.03]
    fit = None
    if len(good) >= 3:
        x = np.array([r["live_t"] for r in good])
        y = np.array([r["studio_t"] for r in good])
        med_off = np.median(y - x)
        inl = np.abs((y - x) - med_off) < 0.5
        if inl.sum() >= 3:
            slope, intercept = np.polyfit(x[inl], y[inl], 1)
            fit = {"slope": round(float(slope), 5), "intercept": round(float(intercept), 4),
                   "inliers": int(inl.sum()), "windows": len(good)}

    # fine, sample-accurate offsets at anchors along the clip (using the full-rate audio)
    fine = []
    if fit:
        live44, sr44 = librosa.load(a.live, sr=44100, mono=True)
        st44, _ = librosa.load(a.studio, sr=44100, mono=True)
        for r in good[::2]:
            guess = fit["slope"] * r["live_t"] + fit["intercept"]
            ts, c = fine_offset(live44, st44, r["live_t"], guess, sr44)
            if ts is not None:
                fine.append({"live_t": r["live_t"], "studio_t": round(ts, 5),
                             "offset": round(ts - r["live_t"], 5), "corr": round(c, 3)})

    out = {"live": a.live, "studio": a.studio, "windows": rows, "fit": fit, "fine": fine}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print("fit:", fit)
    for r in rows:
        flag = "" if (r["score"] > 0.35 and r["margin"] > 0.03) else "  (weak)"
        print(f"live {r['live_t']:7.2f} -> studio {r['studio_t']:7.2f}  off {r['offset']:+8.3f}  "
              f"score {r['score']:.2f} margin {r['margin']:.2f}{flag}")
    for r in fine:
        print(f"fine live {r['live_t']:7.2f} -> studio {r['studio_t']:9.4f}  off {r['offset']:+.5f}  corr {r['corr']:.3f}")


if __name__ == "__main__":
    main()
