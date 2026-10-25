#!/usr/bin/env python3
"""Analyse a finalist beat (full track) for production.

1. Beat grid: beat_this beats -> linear regression (period T, phase t0), residual check.
2. Bar phase: score each of the 4 possible downbeat phases by (a) agreement with beat_this
   downbeats and (b) drum evidence (kick-band onsets on beats 1/3 vs snare-band onsets on 2/4).
   This fixes the "snare on Juice's 1 and 3" displacement the groove judge found in previews.
3. Harmony: for the musically valid phases only (best phase and the half-bar shift, which keeps a
   backbeat/dembow pattern intact), search transposition (-3..+3) and the beat bar that Juice's bar 5
   lands on (first 24 bars), scoring beat-by-beat consonance of his sung pitch vs the beat's chroma
   across his whole verse, normalised by the original Reine beat.
4. Bar-level energy profile + a spectrogram with the bar grid, to plan intro/verse/outro.

Usage: analyze_finalist.py BEAT_AUDIO OUT_PREFIX
"""
import json
import os
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fitscore import INTERVAL_W  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402

ROOT = "/home/user/test"
SR = 22050
D = np.mod(np.arange(12)[:, None] - np.arange(12)[None, :], 12)
WM = INTERVAL_W[D]
LBEAT = LIVE_BAR / 4


def juice_beats():
    d = np.load(f"{ROOT}/work/analysis/juice_pitch.npz")
    t, f0, per, voiced = d["times"], d["f0"], d["periodicity"], d["voiced"]
    sel = voiced & (t >= 14.5) & (t <= 117.72)
    pc = np.mod(np.round(69 + 12 * np.log2(np.maximum(f0[sel], 1e-3) / 440.0)), 12).astype(int)
    b5 = LIVE_BAR1 + 4 * LIVE_BAR
    j = np.floor((t[sel] - b5) / LBEAT).astype(int)          # beat index relative to Juice's bar-5 downbeat
    nb = int(np.ceil((117.72 - b5) / LBEAT)) + 1
    P = np.zeros((nb, 12))
    ok = (j >= -4) & (j < nb)
    np.add.at(P, (np.clip(j[ok], 0, nb - 1), pc[ok]), per[sel][ok])
    return P


def main():
    path, prefix = sys.argv[1], sys.argv[2]
    from beat_this.inference import File2Beats

    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    beats, downs = f2b(path)
    beats, downs = np.asarray(beats), np.asarray(downs)
    y, _ = librosa.load(path, sr=SR, mono=True)
    dur = len(y) / SR
    T0 = np.median(np.diff(beats))
    k = np.round((beats - beats[0]) / T0)
    T, t0 = np.polyfit(k, beats, 1)
    res = beats - (t0 + T * k)
    # extrapolate grid to cover the whole file
    kmin = int(np.floor(-t0 / T))
    grid = t0 + T * np.arange(kmin, int((dur - t0) / T) + 1)
    grid = grid[grid >= 0]
    # drum evidence on the fitted grid
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256))
    fr = librosa.fft_frequencies(sr=SR, n_fft=2048)
    lowf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[fr < 150]), sr=SR, hop_length=256)
    midf = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[(fr > 1500) & (fr < 6000)]), sr=SR, hop_length=256)
    gi = np.clip(librosa.time_to_frames(grid, sr=SR, hop_length=256), 0, len(lowf) - 1)
    kick = np.array([lowf[max(0, i - 2):i + 3].max() for i in gi])
    snare = np.array([midf[max(0, i - 2):i + 3].max() for i in gi])
    phases = []
    for p in range(4):
        idx = np.arange(len(grid))
        pos = (idx - p) % 4                                    # 0 = downbeat under phase p
        db_t = grid[pos == 0]
        agree = np.mean([np.min(np.abs(db_t - d)) < 0.07 for d in downs]) if len(downs) else 0
        drum = (kick[pos == 0].mean() + kick[pos == 2].mean() - kick[pos % 2 == 1].mean()) / (kick.mean() + 1e-9) \
            + (snare[pos % 2 == 1].mean() - snare[pos % 2 == 0].mean()) / (snare.mean() + 1e-9)
        phases.append({"phase": p, "downbeat_agree": round(float(agree), 3), "drum_evidence": round(float(drum), 3)})
    for ph in phases:
        ph["score"] = round(ph["downbeat_agree"] + 0.5 * ph["drum_evidence"], 3)
    best = max(phases, key=lambda x: x["score"])["phase"]
    valid = [best, (best + 2) % 4]

    # harmony search (beat chroma on the fitted grid)
    c = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=512)
    cf = np.clip(librosa.time_to_frames(grid, sr=SR, hop_length=512), 0, c.shape[1] - 1)
    C = np.stack([c[:, a:b].mean(axis=1) if b > a else c[:, a] for a, b in zip(cf[:-1], cf[1:])])
    C = C / (C.sum(axis=1, keepdims=True) + 1e-9)
    P = juice_beats()
    w = P.sum(axis=1)
    # Reine baseline at true alignment
    yb, _ = librosa.load(f"{ROOT}/work/stems/live_inst_hq.wav", sr=SR, mono=True)
    b5 = LIVE_BAR1 + 4 * LIVE_BAR
    bg = b5 + LBEAT * np.arange(len(P) + 1)
    cb = librosa.feature.chroma_cqt(y=yb, sr=SR, hop_length=512)
    bf = np.clip(librosa.time_to_frames(bg, sr=SR, hop_length=512), 0, cb.shape[1] - 1)
    Cb = np.stack([cb[:, a:b].mean(axis=1) for a, b in zip(bf[:-1], bf[1:])])
    Cb = Cb / (Cb.sum(axis=1, keepdims=True) + 1e-9)
    base = float(np.einsum("ij,jk,ik->i", P, WM, Cb).sum() / w.sum())
    cands = []
    for p in valid:
        for e in range(0, 24):                                 # beat bar that Juice's bar 5 lands on
            start = p + 4 * e
            if start + len(P) > len(C):
                break
            Cs = C[start:start + len(P)]
            for kk in range(-3, 4):
                s = float(np.einsum("ij,jk,ik->i", P, WM, np.roll(Cs, kk, axis=1)).sum() / w.sum())
                cands.append({"phase": p, "entry_bar": e, "transpose": kk, "harm": round(s / base, 3),
                              "harm_pen": round(s / base - 0.03 * abs(kk), 3)})
    cands.sort(key=lambda x: -x["harm_pen"])
    # bar energy profile (on the best phase)
    first = t0 + ((best - kmin) % 4) * T if False else grid[best]
    bars_t = np.arange(first, dur, 4 * T)
    rms = librosa.feature.rms(y=y, hop_length=512)[0]
    rt = librosa.frames_to_time(np.arange(len(rms)), sr=SR, hop_length=512)
    bar_db = [round(float(20 * np.log10(rms[(rt >= a) & (rt < a + 4 * T)].mean() + 1e-9)), 1) for a in bars_t]
    low_db = []
    for a in bars_t:
        m = (librosa.frames_to_time(np.arange(S.shape[1]), sr=SR, hop_length=256) >= a) & \
            (librosa.frames_to_time(np.arange(S.shape[1]), sr=SR, hop_length=256) < a + 4 * T)
        low_db.append(round(float(20 * np.log10(S[fr < 120][:, m].mean() + 1e-9)), 1))
    out = {"file": path, "duration": round(dur, 2), "beat_period": round(float(T), 6), "beat_t0": round(float(t0), 4),
           "bpm": round(60 / float(T), 3), "grid_residual_ms": round(float(np.std(res) * 1000), 1),
           "stretch_to_juice": round(float(LBEAT / T), 5), "phases": phases, "best_phase": best,
           "first_downbeat": round(float(grid[best]), 4), "n_bars": len(bars_t),
           "top_alignments": cands[:12], "bar_rms_db": bar_db, "bar_low_db": low_db}
    json.dump(out, open(prefix + ".json", "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("bar_rms_db", "bar_low_db", "top_alignments")}, indent=1))
    print("top alignments:", out["top_alignments"][:6])

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.signal import stft
    f_, t_, Z = stft(y, SR, nperseg=2048, noverlap=1536)
    Sdb = 20 * np.log10(np.abs(Z) + 1e-9)
    fig, ax = plt.subplots(2, 1, figsize=(26, 9), gridspec_kw={"height_ratios": [3, 1]})
    ax[0].pcolormesh(t_, f_, Sdb, shading="auto", vmin=Sdb.max() - 80, vmax=Sdb.max(), cmap="magma")
    ax[0].set_yscale("symlog", linthresh=200)
    ax[0].set_ylim(30, 11000)
    for i, a in enumerate(bars_t):
        ax[0].axvline(a, color="cyan" if i % 4 == 0 else "white", lw=1.4 if i % 4 == 0 else 0.4, alpha=0.8)
        if i % 4 == 0:
            ax[0].text(a + 0.2, 9000, str(i), color="w", fontsize=8)
    ax[1].plot(bars_t, bar_db, "-o", ms=3, label="bar RMS dB")
    ax[1].plot(bars_t, np.array(low_db) - np.median(low_db) + np.median(bar_db), "-", label="sub-120 Hz (shifted)")
    ax[1].legend()
    ax[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(prefix + ".png", dpi=50)


if __name__ == "__main__":
    main()
