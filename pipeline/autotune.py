#!/usr/bin/env python3
"""Offline Auto-Tune-style correction for an isolated lead vocal: Praat PSOLA, chord-aware note choice.

Engine and analysis are ported from the pitch-correction bake-off (work/vocal_research/autotune_tools, which
compared Praat PSOLA, x42 fat1, Rubber Band R3/R2, WORLD and Autotalent on Juice's live acapella): PSOLA kept
the formants (leak 0.01-0.09 vs 0.3-1.0) and the transients, and copies unvoiced audio untouched.
  pitch    torchcrepe full with a dither-free Viterbi + local-average decoder (torchcrepe's stock decoders
           add +-10-20 c noise per frame, which a tuner would write into the output), refined by WORLD
           harvest where the two agree within 50 c
  notes    per voiced run, an offline Viterbi over the scale notes: cost |pitch - note| per frame, minus a
           chord bonus when the note belongs to the chord sounding at that moment (Reine: Em|D on odd bars,
           Bm|A on even bars), plus switch_cost per note change - so a pitch hovering between two notes stays
           on one, and a note sung between two key notes goes to the one the harmony supports
  shift    one-pole low-pass (tau per section) of target - pitch; notes start already tuned; decays to 0 on
           unvoiced frames (consonants, breaths untouched)
  resynth  Praat Manipulation: its own pitch tier x 2^(shift/12), overlap-add
Juice WRLD's records measure as a ~15-20 ms correction on sung lines and ~35-40 ms on rap-leaning ones
(work/vocal_research/measure), so sections can carry their own tau.

Usage: autotune.py IN.wav OUT.wav --start S --end E [--sections '[[t0,t1,tau_ms,switch_cost],...]']
       [--scale "D E F# G A B C#"] [--chord-bonus 0.3] [--bar1 3.1958 --bar 2.38934] [--report notes.json]
Times are on IN.wav's timeline (the live grid when --bar1/--bar describe it).
"""
import argparse
import json
import sys
import types

import numpy as np
import soundfile as sf

SR = 44100
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Reine's half-bar chords on the live grid (verified by chord-template matching over bars 5-48 and 57-72)
REINE_CHORDS = {("odd", 0): {4, 7, 11}, ("odd", 1): {2, 6, 9}, ("even", 0): {11, 2, 6}, ("even", 1): {9, 1, 4}}
_CENTS = None


def runs(mask):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]]).astype(int)
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def viterbi_local(logits):
    import torch
    import torchcrepe
    global _CENTS
    if _CENTS is None:
        _CENTS = torchcrepe.CENTS_PER_BIN * torch.arange(360, dtype=torch.float64) + 1997.3794084376191
    bins, _ = torchcrepe.decode.viterbi(logits.clone())
    sal = torch.sigmoid(logits.double())
    idx = torch.arange(360)[None, :, None]
    win = (idx >= (bins[:, None, :] - 4)) & (idx <= (bins[:, None, :] + 4))
    w = torch.where(win, sal, torch.zeros_like(sal))
    cents = (w * _CENTS[None, :, None]).sum(1) / w.sum(1).clamp_min(1e-12)
    return bins, (10 * 2 ** (cents / 1200)).float()


def crepe_track(y):
    import librosa
    import torch
    import torchcrepe
    torch.set_num_threads(4)
    y16 = librosa.resample(np.asarray(y, np.float32), orig_sr=SR, target_sr=16000)
    with torch.inference_mode():
        f0, per = torchcrepe.predict(torch.tensor(y16[None, :]), 16000, 160, fmin=65.0, fmax=1000.0, model="full",
                                     decoder=viterbi_local, return_periodicity=True, batch_size=256, device="cpu")
    per = torchcrepe.filter.median(per, 3)[0].numpy()
    f0 = f0[0].numpy().astype(np.float64)
    rms = librosa.feature.rms(y=y16, frame_length=1024, hop_length=160, center=True)[0][:len(f0)]
    rms = np.pad(rms, (0, len(f0) - len(rms)), mode="edge")
    return np.arange(len(f0)) * 0.01, f0, per, 20 * np.log10(rms + 1e-9)


def import_pyworld():
    # pyworld imports pkg_resources only for its version string; newer setuptools no longer ships it
    if "pkg_resources" not in sys.modules:
        m = types.ModuleType("pkg_resources")
        m.get_distribution = lambda name: types.SimpleNamespace(version="0.3.5")
        sys.modules["pkg_resources"] = m
    import pyworld
    return pyworld


def drive_track(y):
    t, f0, per, ldb = crepe_track(y)
    pw = import_pyworld()
    fh, _ = pw.harvest(np.ascontiguousarray(y, np.float64), SR, f0_floor=70.0, f0_ceil=900.0, frame_period=5.0)
    fhc = fh[np.clip(np.round(t / 0.005).astype(int), 0, len(fh) - 1)]
    agree = (fhc > 0) & (np.abs(1200 * np.log2(np.maximum(fhc, 1) / np.maximum(f0, 1))) < 50)
    vd = (per > 0.5) & (ldb > ldb.max() - 45)
    return t, np.where(vd, np.where(agree, fhc, f0), 0.0)


def chord_tones(abs_t, bar1, bar):
    k = int(np.floor((abs_t - bar1) / bar)) + 1
    half = int(((abs_t - bar1) / bar - (k - 1)) >= 0.5)
    return REINE_CHORDS[("odd" if k % 2 else "even", half)]


def note_viterbi(midi, abs_t, pcs, switch_cost, chord_bonus, bar1, bar):
    lo, hi = np.nanmin(midi) - 2, np.nanmax(midi) + 2
    notes = np.array([o * 12 + p for o in range(11) for p in pcs if lo <= o * 12 + p <= hi], float)
    if len(notes) == 0:
        grid = np.array([o * 12 + p for o in range(11) for p in pcs], float)
        notes = np.array([grid[np.argmin(np.abs(grid - np.nanmedian(midi)))]])
    m = np.where(np.isfinite(midi), midi, np.nanmedian(midi))
    C = np.abs(m[:, None] - notes[None, :])
    if chord_bonus > 0 and bar1 is not None:
        pc = (notes.astype(int) % 12)
        for i, tt in enumerate(abs_t):
            ct = chord_tones(tt, bar1, bar)
            C[i] -= chord_bonus * np.isin(pc, list(ct))
    T, K = C.shape
    D = C[0].copy()
    back = np.zeros((T, K), int)
    for i in range(1, T):
        best = int(np.argmin(D))
        sw = D[best] + switch_cost
        back[i] = np.where(sw < D, best, np.arange(K))
        D = np.minimum(D, sw) + C[i]
    path = np.zeros(T, int)
    path[-1] = int(np.argmin(D))
    for i in range(T - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return notes[path]


def make_shift(t, f0, t_off, sections, pcs, chord_bonus, bar1, bar, unv_ms=30.0, min_run_s=0.04):
    from scipy.signal import medfilt
    voiced = f0 > 0
    for s, e in runs(voiced):
        if t[min(e, len(t) - 1)] - t[s] < min_run_s:
            voiced[s:e] = False
    midi = np.where(voiced, 69 + 12 * np.log2(np.maximum(f0, 1e-3) / 440.0), np.nan)
    mm = medfilt(np.where(voiced, midi, 0.0), 3)
    midi = np.where(voiced, np.where(mm > 0, mm, midi), np.nan)
    abs_t = t + t_off

    def sec_of(tt):
        for t0, t1, tau, sc in sections:
            if t0 <= tt < t1:
                return tau, sc
        return sections[-1][2], sections[-1][3]

    target = np.full(len(t), np.nan)
    for s, e in runs(voiced):
        _, sc = sec_of(abs_t[s])
        target[s:e] = note_viterbi(midi[s:e], abs_t[s:e], pcs, sc, chord_bonus, bar1, bar)
    raw = np.where(voiced, target - midi, 0.0)
    dt = 0.01
    shift = np.zeros(len(t))
    sv = 0.0
    for i in range(len(t)):
        if voiced[i]:
            tau = sec_of(abs_t[i])[0] / 1000.0
            if i > 0 and not voiced[i - 1] and tau <= 0.03:
                sv = raw[i]                                   # start the note already tuned
            sv += (1.0 if tau <= 1e-4 else 1 - np.exp(-dt / tau)) * (raw[i] - sv)
        else:
            sv *= np.exp(-dt / (unv_ms / 1000.0))
        shift[i] = sv
    return shift, target, midi, voiced


def praat_psola(x, t, shift, fmin=75.0, fmax=900.0, step=0.005):
    import parselmouth
    from parselmouth.praat import call
    snd = parselmouth.Sound(np.asarray(x, np.float64), sampling_frequency=SR)
    man = call(snd, "To Manipulation", step, fmin, fmax)
    tier = call(man, "Extract pitch tier")
    n = int(call(tier, "Get number of points"))
    pts_t = np.array([call(tier, "Get time from index", i + 1) for i in range(n)])
    pts_f = np.array([call(tier, "Get value at index", i + 1) for i in range(n)])
    new_f = pts_f * 2 ** (np.interp(pts_t, t, shift) / 12.0)
    call(tier, "Remove points between", 0, snd.duration)
    for ti, fi in zip(pts_t, new_f):
        call(tier, "Add point", float(ti), float(fi))
    call([tier, man], "Replace pitch tier")
    y = call(man, "Get resynthesis (overlap-add)").values[0].astype(np.float64)
    return np.pad(y, (0, max(0, len(x) - len(y))))[:len(x)]


def tune(x_mono, t_off, sections, scale="D E F# G A B C#", chord_bonus=0.3, bar1=None, bar=None):
    """Tune a mono segment that starts at t_off on the grid timeline. Returns (y, report, frames)."""
    pcs = sorted(NOTES[p] for p in scale.split())
    t, f0 = drive_track(x_mono)
    shift, target, midi, voiced = make_shift(t, f0, t_off, sections, pcs, chord_bonus, bar1, bar)
    t5 = np.arange(0.0, t[-1] + 1e-9, 0.005)
    y = praat_psola(x_mono, t5, np.interp(t5, t, shift))
    v = voiced
    moved = np.abs(shift[v]) * 100
    tg = target[v]
    rep = {"voiced_s": round(float(v.sum() * 0.01), 1), "mean_abs_shift_cents": round(float(moved.mean()), 1),
           "p95_abs_shift_cents": round(float(np.percentile(moved, 95)), 1),
           "share_moved_over_60c": round(float(np.mean(moved > 60)), 3),
           "note_switches_per_voiced_s": round(float(np.sum(np.diff(tg) != 0) / max(1e-6, v.sum() * 0.01)), 2),
           "target_pitch_classes": {NAMES[int(p)]: round(float(np.mean((tg % 12).astype(int) == p)), 3)
                                    for p in pcs}}
    return y, rep, dict(t=t + t_off, f0=f0, shift=shift, target=target, midi=midi, voiced=voiced)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--sections", default="[[0, 1e9, 18, 3.0]]")
    ap.add_argument("--scale", default="D E F# G A B C#")
    ap.add_argument("--chord-bonus", type=float, default=0.3)
    ap.add_argument("--bar1", type=float, default=3.1958)
    ap.add_argument("--bar", type=float, default=2.38934)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    x, sr = sf.read(a.inp, always_2d=True, dtype="float64")
    assert sr == SR
    s0, s1 = int(a.start * SR), int(a.end * SR)
    y, rep, fr = tune(x[s0:s1].mean(axis=1), a.start, json.loads(a.sections), a.scale, a.chord_bonus, a.bar1, a.bar)
    out = np.zeros((len(x), 2))
    out[s0:s1] = y[:, None]
    sf.write(a.out, out.astype(np.float32), SR, subtype="FLOAT")
    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
        np.savez(a.report.replace(".json", ".npz"), **fr)
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
