#!/usr/bin/env python3
"""Juice WRLD "record vocal" from the live Mouv' acapella: Auto-Tune-style correction + his record chain.

Measured basis (work/vocal_research/juice_wrld_studio_vocal, 10 record previews vs the live freestyle):
records are tuned to the song's key at A=440 (81% of held notes within 8 cents, 98-100% in key; the live
freestyle: 21-24%, in key at chance), with a fast but not robotic correction (matches a 15-25 ms one-pole
retune); they have 4-8 dB less 400 Hz-1 kHz and a brighter, heavily de-essed top, 2.4 dB level spread
(live 3.8) and 11 dB crest (live 13.6), and stereo width from doubles.

1. Pitch track (torchcrepe full, 10 ms, viterbi), voiced = periodicity and level gates.
2. Correction: target = nearest note of the scale (hysteresis so speech hovering between two notes does not
   flicker), shift = one-pole low-pass (retune_ms) of target - input in semitones, decaying to 0 on unvoiced
   frames (consonants and breaths untouched); applied with Rubber Band R3's --pitchmap (formant-preserving)
   on the mono signal, map entries written map_advance_ms late (R3 applies them ~85 ms early), latency
   removed by aligning a zero-shift pass.
3. Chain: 24 dB/oct HPF, tone EQ toward the records, FET-style then opto-style compression, split-band
   de-esser, 12% parallel saturation -> lead (dry, centre). Two pseudo-doubles (+-8 cents, 17/29 ms, darker)
   -> doubles (stereo, unit level; the arrangement sets their level and where they play).
Writes OUT_DIR/{tuned,lead,doubles}.wav on the input's timeline and OUT_DIR/report.json.

Usage: juice_vocal.py IN.wav OUT_DIR [--retune-ms 20] [--hyst 0.3] [--min-note-ms 40] [--scale "D E F# G A B C#"]
       [--hpf 110] [--start S --end E]
"""
import argparse
import json
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from pedalboard import Compressor, Distortion, HighShelfFilter, LowShelfFilter, Pedalboard, PeakFilter, PitchShift
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, correlate, sosfilt

NOTES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7,
         "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
HOP = 0.01


def pitch_track(m, sr):
    import torch
    import torchcrepe
    from scipy.signal import resample_poly

    y = resample_poly(m, 160, sr // 100).astype(np.float32)            # -> 16 kHz
    torch.set_num_threads(4)
    f0, per = torchcrepe.predict(torch.tensor(y[None, :]), 16000, 160, fmin=65.0, fmax=1000.0, model="full",
                                 decoder=torchcrepe.decode.viterbi, return_periodicity=True, batch_size=512,
                                 device="cpu")
    per = torchcrepe.filter.median(per, 3)
    f0, per = f0[0].numpy(), per[0].numpy()
    rms = np.sqrt(uniform_filter1d(y.astype(np.float64) ** 2, 400))[::160][:len(f0)]
    rms = np.pad(rms, (0, len(f0) - len(rms)), mode="edge")
    ld = 20 * np.log10(rms + 1e-9)
    voiced = (per > 0.5) & (ld > np.percentile(ld[ld > -80], 30))
    voiced = uniform_filter1d(voiced.astype(float), 3) > 0.5          # drop single-frame blips
    return f0, per, voiced


def correction(f0, voiced, scale, ref_hz, retune_ms, hyst, humanize, min_note_ms=0.0):
    pcs = sorted(NOTES[p] for p in scale.split())
    midi = 69 + 12 * np.log2(np.maximum(f0, 1e-3) / ref_hz)
    grid = np.array([o * 12 + p for o in range(11) for p in pcs], float)
    n = len(f0)
    target = np.full(n, np.nan)
    cur = None
    for i in range(n):
        if not voiced[i]:
            cur = None
            continue
        near = grid[np.argmin(np.abs(grid - midi[i]))]
        if cur is None:
            cur = near
        elif near != cur and abs(midi[i] - cur) > abs((cur + near) / 2 - cur) * (1 + hyst):
            cur = near
        target[i] = cur
    # debounce: a note change must persist min_note_ms, else the previous note is kept (stops D/C# warble on
    # pitches hovering between two scale notes; falls keep their steps because each step lasts long enough)
    k = max(1, int(round(min_note_ms / 1000 / HOP)))
    i = 1
    while i < n:
        if voiced[i] and voiced[i - 1] and target[i] != target[i - 1]:
            j = i
            while j < n and voiced[j] and target[j] == target[i]:
                j += 1
            if j - i < k and j < n and voiced[j] and target[j] == target[i - 1]:
                target[i:j] = target[i - 1]
            i = j
        else:
            i += 1
    raw = np.where(voiced, target - midi, 0.0)
    held = np.zeros(n)
    for i in range(1, n):
        held[i] = held[i - 1] + HOP if (voiced[i] and target[i] == target[i - 1]) else 0.0
    shift = np.zeros(n)
    s = 0.0
    for i in range(n):
        if voiced[i]:
            tau = retune_ms / 1000.0
            if humanize > 0 and held[i] > 0.2:
                tau *= 1 + humanize * min(1.0, (held[i] - 0.2) / 0.4)
            s += (1.0 if tau <= 1e-4 else 1 - np.exp(-HOP / tau)) * (raw[i] - s)
        else:
            s *= np.exp(-HOP / 0.03)
        shift[i] = s
    return shift, target, midi


def rubberband_pitchmap(m, sr, shift, advance_ms):
    with tempfile.TemporaryDirectory() as td:
        wi = os.path.join(td, "in.wav")
        sf.write(wi, m, sr, subtype="FLOAT")

        def run(sh, name):
            pm, wo = os.path.join(td, name + ".map"), os.path.join(td, name + ".wav")
            with open(pm, "w") as fh:
                for i, v in enumerate(sh):
                    fh.write(f"{int(round((i * HOP + advance_ms / 1000) * sr))} {v:.4f}\n")
            subprocess.run(["rubberband", "-3", "-F", "-q", "--pitchmap", pm, wi, wo], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return sf.read(wo, dtype="float32")[0]

        y = run(shift, "tuned")
        z = run(np.zeros_like(shift), "zero")
    L = min(len(m), len(z))
    c = correlate(z[:L] if z.ndim == 1 else z[:L, 0], m[:L], mode="full", method="fft")
    lag = int(np.argmax(c) - (L - 1))
    y = y if y.ndim == 1 else y[:, 0]
    y = y[lag:] if lag > 0 else np.pad(y, (-lag, 0))
    return np.pad(y, (0, max(0, len(m) - len(y))))[:len(m)].astype(np.float32), lag


def level_db(m, sr, pct=90):
    r = np.sqrt(uniform_filter1d(m.astype(np.float64) ** 2, int(0.05 * sr)))[::int(0.025 * sr)]
    d = 20 * np.log10(r + 1e-9)
    return float(np.percentile(d[d > d.max() - 35], pct))


def deess(m, sr, lo=5500, hi=10000, ratio=6.0, below_p90=8.0):
    b = sosfilt(butter(4, [lo, hi], "bandpass", fs=sr, output="sos"), m)
    env = np.abs(b)
    out = np.empty_like(env)
    aa, ar = np.exp(-1 / (0.001 * sr)), np.exp(-1 / (0.06 * sr))
    e = 0.0
    for i, v in enumerate(env):
        e = aa * e + (1 - aa) * v if v > e else ar * e + (1 - ar) * v
        out[i] = e
    edb = 20 * np.log10(out + 1e-9)
    thr = np.percentile(edb[edb > edb.max() - 40], 90) - below_p90
    gr = -np.clip(edb - thr, 0, None) * (1 - 1 / ratio)
    return (m - b + b * 10 ** (gr / 20)).astype(np.float32), float(-gr.min())


def chain(m, sr, hpf):
    m = sosfilt(butter(4, hpf, "highpass", fs=sr, output="sos"), m).astype(np.float32)
    # tone toward the measured record average (bands vs 1-3 kHz): the first pass (shelf +5, cuts -4.5/-3)
    # overshot - 400 Hz-1 kHz came out 1.7 dB under the records and 6-15 kHz ~4 dB over them
    m = Pedalboard([LowShelfFilter(200, -2.0, 0.7), PeakFilter(300, -3.5, 0.8), PeakFilter(650, -1.5, 1.0),
                    PeakFilter(2800, 2.0, 1.0), HighShelfFilter(9000, 3.0, 0.7)])(m[None, :], sr)[0]
    m = Pedalboard([Compressor(threshold_db=level_db(m, sr) - 6, ratio=4, attack_ms=2, release_ms=60)])(m[None, :], sr)[0]
    m = Pedalboard([Compressor(threshold_db=level_db(m, sr, 50), ratio=1.8, attack_ms=15, release_ms=200)])(m[None, :], sr)[0]
    m, ds = deess(m, sr)
    sat = Pedalboard([Distortion(drive_db=10)])(m[None, :] * 0.5, sr)[0]
    sat = sosfilt(butter(2, 7000, "lowpass", fs=sr, output="sos"), sosfilt(butter(4, 300, "highpass", fs=sr, output="sos"), sat))
    m = (m + 0.12 * sat / (np.abs(sat).max() + 1e-9) * np.abs(m).max()).astype(np.float32)
    return m, ds


def doubles(m, sr):
    dbl = []
    for cents, ms in ((+8, 17), (-8, 29)):
        d = PitchShift(semitones=cents / 100)(m[None, :], sr)[0]
        d = np.concatenate([np.zeros(int(ms / 1000 * sr), np.float32), d])[:len(m)]
        d = sosfilt(butter(2, 9000, "lowpass", fs=sr, output="sos"), sosfilt(butter(4, 180, "highpass", fs=sr, output="sos"), d))
        dbl.append(d.astype(np.float32))
    th = 1.8 * np.pi / 4
    near, far = np.sin(th), np.cos(th)
    return np.stack([dbl[0] * near + dbl[1] * far, dbl[1] * near + dbl[0] * far], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out_dir")
    ap.add_argument("--retune-ms", type=float, default=20.0)
    ap.add_argument("--humanize", type=float, default=0.3)
    ap.add_argument("--hyst", type=float, default=0.3)
    ap.add_argument("--min-note-ms", type=float, default=40.0)
    ap.add_argument("--scale", default="D E F# G A B C#")
    ap.add_argument("--ref-hz", type=float, default=440.0)
    ap.add_argument("--advance-ms", type=float, default=85.0)
    ap.add_argument("--hpf", type=float, default=115.0)
    ap.add_argument("--start", type=float, default=None, help="process only this region (s, input timeline)")
    ap.add_argument("--end", type=float, default=None)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    x, sr = sf.read(a.inp, always_2d=True, dtype="float32")
    s0 = int((a.start or 0) * sr)
    s1 = int(a.end * sr) if a.end else len(x)
    m = x[s0:s1].mean(axis=1)
    f0, per, voiced = pitch_track(m, sr)
    shift, target, midi = correction(f0, voiced, a.scale, a.ref_hz, a.retune_ms, a.hyst, a.humanize, a.min_note_ms)
    tuned, lag = rubberband_pitchmap(m, sr, shift, a.advance_ms)
    lead, ds = chain(tuned, sr, a.hpf)
    dbl = doubles(lead, sr)
    full = lambda y: np.concatenate([np.zeros((s0,) + y.shape[1:], np.float32), y,
                                     np.zeros((len(x) - s1,) + y.shape[1:], np.float32)])
    sf.write(os.path.join(a.out_dir, "tuned.wav"), np.stack([full(tuned)] * 2, axis=1), sr, subtype="FLOAT")
    sf.write(os.path.join(a.out_dir, "lead.wav"), np.stack([full(lead)] * 2, axis=1), sr, subtype="FLOAT")
    sf.write(os.path.join(a.out_dir, "doubles.wav"), full(dbl), sr, subtype="FLOAT")
    # how audible / how jumpy the correction is: mean shift, note switches per voiced second
    v = voiced.astype(bool)
    tg = target[v]
    switches = int(np.sum(np.diff(tg) != 0)) if len(tg) > 1 else 0
    rep = {"rubberband_latency_samples": lag, "voiced_s": round(float(v.sum() * HOP), 1),
           "mean_abs_shift_cents": round(float(np.mean(np.abs(shift[v])) * 100), 1),
           "p95_abs_shift_cents": round(float(np.percentile(np.abs(shift[v]), 95) * 100), 1),
           "note_switches_per_voiced_s": round(switches / max(1e-6, v.sum() * HOP), 2),
           "deess_max_gr_db": round(ds, 1), "retune_ms": a.retune_ms, "hyst": a.hyst, "min_note_ms": a.min_note_ms, "scale": a.scale, "hpf": a.hpf}
    np.savez(os.path.join(a.out_dir, "f0.npz"), f0=f0, per=per, voiced=voiced, shift=shift, target=target,
             midi=midi, hop=HOP, start=(a.start or 0.0))
    json.dump(rep, open(os.path.join(a.out_dir, "report.json"), "w"), indent=1)
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
