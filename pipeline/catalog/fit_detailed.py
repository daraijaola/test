#!/usr/bin/env python3
"""Stage-2 fit: simulate Juice's actual vocal over each shortlisted beat, beat by beat.

For every candidate clip:
  * beat-track it (beat_this), measure its tempo, and treat its bars as a loop at Juice's tempo
  * beat-synchronous chroma of the clip; beat-synchronous pitch-class distribution of Juice's vocal
  * search transposition (-3..+3 semitones) x bar alignment (offset in beats, all 4 beat phases x loop bars)
  * harmonic fit = consonance-weighted match of what he sings vs the beat's harmony on that beat,
    normalised by the same score for the real Reine beat at its true alignment (1.0 = as good as Reine)
  * groove fit = correlation of where his syllables vs the beat's onsets fall inside the bar (16ths)
Writes fit_detailed.jsonl (one row per candidate, best configuration) sorted by combined score.

Usage: fit_detailed.py SCORED.jsonl TOP_N OUT.jsonl
"""
import json
import os
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fitscore import INTERVAL_W  # noqa: E402

ROOT = "/home/user/test"
BAR1, BAR_LEN = 3.1958, 2.38934          # live grid, regression fit (work/analysis/grid_refined.json)
BEAT = BAR_LEN / 4
VOCAL_START, VOCAL_END = 14.5, 117.72    # Juice's performance on the live timeline
TARGET_BPM = 60 / BEAT
SR = 22050
D = np.mod(np.arange(12)[:, None] - np.arange(12)[None, :], 12)
WM = INTERVAL_W[D]                        # (vocal pc, chord pc) -> consonance weight


def juice_beat_profiles():
    d = np.load(f"{ROOT}/work/analysis/juice_pitch.npz")
    t, f0, per, voiced = d["times"], d["f0"], d["periodicity"], d["voiced"]
    sel = voiced & (t >= VOCAL_START) & (t <= VOCAL_END)
    pc = np.mod(np.round(69 + 12 * np.log2(np.maximum(f0[sel], 1e-3) / 440.0)), 12).astype(int)
    j = np.floor((t[sel] - BAR1) / BEAT).astype(int)
    j0, j1 = int(np.floor((VOCAL_START - BAR1) / BEAT)), int(np.ceil((VOCAL_END - BAR1) / BEAT))
    P = np.zeros((j1 - j0, 12))
    np.add.at(P, (j - j0, pc), per[sel])
    return P, j0


def juice_onsets():
    y, _ = librosa.load(f"{ROOT}/work/stems/freestyle_fast/vocals_mel_band_roformer/vocals.wav", sr=SR,
                        offset=VOCAL_START, duration=VOCAL_END - VOCAL_START)
    on = librosa.onset.onset_detect(y=y, sr=SR, units="time", backtrack=False) + VOCAL_START
    pos = np.mod((on - BAR1) / BAR_LEN, 1.0)
    h = np.bincount((pos * 16).astype(int) % 16, minlength=16).astype(float)
    return h / h.sum()


def beat_chroma(y, beats):
    c = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=512)
    fr = librosa.time_to_frames(beats, sr=SR, hop_length=512)
    fr = np.clip(fr, 0, c.shape[1] - 1)
    B = np.stack([c[:, a:b].mean(axis=1) if b > a else c[:, a] for a, b in zip(fr[:-1], fr[1:])])
    return B / (B.sum(axis=1, keepdims=True) + 1e-9)


def best_alignment(P, C, n_loop):
    """P: (nb, 12) Juice per-beat pitch mass; C: (n_loop, 12) candidate beat chroma loop.
    Returns best (score, transpose, offset_beats). Score is the weighted mean consonance."""
    nb = len(P)
    w = P.sum(axis=1)
    tot = w.sum() + 1e-9
    best = (-9.0, 0, 0)
    for k in range(-3, 4):
        Ck = np.roll(C, k, axis=1)
        S = P @ WM @ Ck.T                                  # (nb, n_loop) consonance of beat i vs loop beat j
        for o in range(n_loop):
            idx = (np.arange(nb) + o) % n_loop
            s = S[np.arange(nb), idx].sum() / tot - 0.012 * abs(k)
            if s > best[0]:
                best = (float(s), k, o)
    return best


def onset_hist(y, beats):
    on = librosa.onset.onset_detect(y=y, sr=SR, units="time")
    if len(beats) < 8:
        return None
    bl = np.median(np.diff(beats)) * 4
    pos = np.mod((on - beats[0]) / bl, 1.0)
    h = np.bincount((pos * 16).astype(int) % 16, minlength=16).astype(float)
    return h / (h.sum() + 1e-9)


def main():
    scored_path, top_n, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    from beat_this.inference import File2Beats

    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    P, j0 = juice_beat_profiles()
    hv = juice_onsets()

    # baseline: the real Reine beat (live instrumental stem) at its true alignment, transpose 0
    yb, _ = librosa.load(f"{ROOT}/work/stems/freestyle_fast/vocals_mel_band_roformer/instrumental.wav", sr=SR)
    grid = BAR1 + BEAT * np.arange(j0, j0 + len(P) + 1)
    Cb = beat_chroma(yb, grid)
    w = P.sum(axis=1)
    base = float((np.einsum("ij,jk,ik->i", P, WM, Cb)).sum() / (w.sum() + 1e-9))
    print(f"baseline (Reine, true alignment): {base:.4f}", flush=True)

    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["id"] for l in open(out_path) if l.strip()}
    rows = [json.loads(l) for l in open(scored_path) if l.strip()][:top_n]
    with open(out_path, "a") as fo:
        for n, r in enumerate(rows):
            if r["id"] in done:
                continue
            try:
                y, _ = librosa.load(r["clip_path"], sr=SR, mono=True)
                beats, downs = f2b(r["clip_path"])
                beats = np.asarray(beats)
                if len(beats) < 12:
                    raise ValueError("too few beats")
                tempo = 60 / np.median(np.diff(beats))
                mult = min((0.5, 1.0, 2.0), key=lambda m: abs(TARGET_BPM / (tempo * m) - 1))
                if mult == 2.0:      # beat is half-time vs Juice: use every beat twice -> subdivide
                    beats = np.sort(np.concatenate([beats, (beats[:-1] + beats[1:]) / 2]))
                elif mult == 0.5:    # double-time: take every other beat
                    beats = beats[::2]
                stretch = TARGET_BPM / (60 / np.median(np.diff(beats)))
                C = beat_chroma(y, beats)
                n_loop = (len(C) // 4) * 4
                if n_loop < 8:
                    raise ValueError("clip too short for a loop")
                C = C[:n_loop]
                s, k, o = best_alignment(P, C, n_loop)
                hb = onset_hist(y, beats)
                groove = float(np.corrcoef(hv, hb)[0, 1]) if hb is not None and hb.std() > 0 else 0.0
                # loop consistency: do the two halves of the clip carry similar harmony? (clean loopable beat)
                half = n_loop // 2
                loop_sim = float(np.mean(np.sum(C[:half] * C[half:2 * half], axis=1) /
                                 (np.linalg.norm(C[:half], axis=1) * np.linalg.norm(C[half:2 * half], axis=1) + 1e-9)))
                hr = s / base if base > 0 else s
                stretch_pen = np.exp(-((stretch - 1) / 0.07) ** 2)
                combined = 0.45 * hr + 0.15 * groove + 0.15 * stretch_pen + 0.25 * r.get("vibe", 0) * 2.5
                out = {**r, "tempo_measured": round(float(tempo), 2), "tempo_mult": mult, "stretch": round(float(stretch), 4),
                       "transpose": k, "offset_beats": o, "harmonic_ratio": round(hr, 3), "groove": round(groove, 3),
                       "loop_sim": round(loop_sim, 3), "fit2": round(float(combined), 4)}
            except Exception as e:
                out = {**r, "error": f"{type(e).__name__}: {str(e)[:120]}"}
            fo.write(json.dumps(out) + "\n")
            fo.flush()
            if n % 25 == 0:
                print(f"  {n}/{len(rows)}", flush=True)
    allrows = [json.loads(l) for l in open(out_path) if l.strip()]
    good = sorted([x for x in allrows if "fit2" in x], key=lambda x: -x["fit2"])
    for x in good[:30]:
        print(f"{x['fit2']:.3f} harm={x['harmonic_ratio']:.2f} groove={x['groove']:.2f} x{x['stretch']} k={x['transpose']:+d} "
              f"vibe={x.get('vibe')} [{x['source']}] {x.get('artist')} - {x.get('title')}"[:170])


if __name__ == "__main__":
    main()
