#!/usr/bin/env python3
"""Objective QA for a rendered track (I can't listen, so everything is measured).

Reports duration, integrated loudness (LUFS), max short-term loudness, sample
and true peak (4x oversampled), clipped samples, DC offset, stereo correlation,
leading/trailing silence, click candidates (sharp discontinuities relative to
the local level) and, optionally, energy continuity around given edit points.
Writes a spectrogram + loudness PNG next to the JSON when --png is given.

Usage: qa.py TRACK.wav [--edits t1,t2,...] [--json out.json] [--png out.png]
"""
import argparse
import json

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt


def true_peak_db(x, sr):
    up = resample_poly(x, 4, 1, axis=0)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-12))


def short_term_lufs(x, sr, meter, win=3.0, hop=1.0):
    vals = []
    n, h = int(win * sr), int(hop * sr)
    for i in range(0, max(1, len(x) - n), h):
        seg = x[i:i + n]
        if len(seg) == n:
            vals.append(meter.integrated_loudness(seg) if np.any(seg) else -70.0)
    return np.array(vals)


def click_candidates(x, sr, thresh=12.0):
    """Find samples where a 4 kHz+ high-passed signal jumps far above its local RMS."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    sos = butter(4, 4000, btype="high", fs=sr, output="sos")
    hp = sosfilt(sos, mono)
    d = np.abs(np.diff(hp))
    win = int(0.02 * sr)
    env = np.sqrt(np.convolve(d ** 2, np.ones(win) / win, mode="same")) + 1e-6
    ratio = d / env
    idx = np.where(ratio > thresh)[0]
    clicks, last = [], -sr
    for i in idx:
        if i - last > sr * 0.05:  # one report per 50 ms
            clicks.append(round(i / sr, 3))
        last = i
    return clicks


def edit_continuity(x, sr, t):
    """Level change (dB) between 50 ms just before and just after an edit point."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    i, w = int(t * sr), int(0.05 * sr)
    a, b = mono[max(0, i - w):i], mono[i:i + w]
    ra = 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9)
    rb = 20 * np.log10(np.sqrt(np.mean(b ** 2)) + 1e-9)
    return round(float(rb - ra), 2)


def silence_edges(x, sr, thresh_db=-60):
    mono = np.abs(x.mean(axis=1) if x.ndim > 1 else x)
    thr = 10 ** (thresh_db / 20)
    nz = np.where(mono > thr)[0]
    if len(nz) == 0:
        return None, None
    return round(nz[0] / sr, 3), round((len(mono) - nz[-1]) / sr, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--edits", default="")
    ap.add_argument("--json")
    ap.add_argument("--png")
    a = ap.parse_args()

    x, sr = sf.read(a.track, always_2d=True)
    meter = pyln.Meter(sr)
    st = short_term_lufs(x, sr, meter)
    lead, trail = silence_edges(x, sr)
    rep = {
        "track": a.track,
        "duration_s": round(len(x) / sr, 3),
        "sr": sr,
        "lufs_integrated": round(float(meter.integrated_loudness(x)), 2),
        "lufs_short_term_max": round(float(st.max()), 2) if len(st) else None,
        "lufs_short_term_p10": round(float(np.percentile(st, 10)), 2) if len(st) else None,
        "sample_peak_db": round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 2),
        "true_peak_db": round(true_peak_db(x, sr), 2),
        "clipped_samples": int(np.sum(np.abs(x) >= 0.999)),
        "dc_offset": [round(float(v), 5) for v in x.mean(axis=0)],
        "stereo_correlation": round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 3) if x.shape[1] == 2 else None,
        "lead_silence_s": lead,
        "trail_silence_s": trail,
        "click_candidates_s": click_candidates(x, sr)[:50],
    }
    if a.edits:
        rep["edit_level_jumps_db"] = {t: edit_continuity(x, sr, float(t)) for t in a.edits.split(",") if t}
    print(json.dumps(rep, indent=1))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rep, f, indent=1)
    if a.png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from scipy.signal import stft

        f, t, Z = stft(x.mean(axis=1), sr, nperseg=4096, noverlap=3072)
        S = 20 * np.log10(np.abs(Z) + 1e-9)
        fig, ax = plt.subplots(2, 1, figsize=(22, 8), gridspec_kw={"height_ratios": [3, 1]})
        ax[0].pcolormesh(t, f, S, shading="auto", vmin=S.max() - 90, vmax=S.max(), cmap="magma")
        ax[0].set_yscale("symlog", linthresh=500)
        ax[0].set_ylim(30, sr / 2)
        step = 5 if len(x) / sr < 200 else 10
        for axx in ax:
            axx.set_xticks(np.arange(0, len(x) / sr, step))
            axx.grid(alpha=0.3)
        for e in (a.edits.split(",") if a.edits else []):
            for axx in ax:
                axx.axvline(float(e), color="cyan", lw=1)
        ax[0].set_title(a.track.split("/")[-1])
        ax[1].plot(np.arange(len(st)) + 1.5, st)
        ax[1].set_ylabel("short-term LUFS")
        plt.tight_layout()
        plt.savefig(a.png, dpi=65)


if __name__ == "__main__":
    main()
