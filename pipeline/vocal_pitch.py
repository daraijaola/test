#!/usr/bin/env python3
"""Track the sung melody of an isolated vocal (torchcrepe) and summarise it.

Outputs an .npz with frame times, f0 (Hz), periodicity and loudness, plus a
JSON summary: a duration-weighted pitch-class histogram of confidently voiced
frames, the best-matching major/minor keys for the melody (Krumhansl-Kessler
profiles) and the vocal range. Remix candidates are later scored against the
frame-level pitch track, so this is the "what notes does Juice actually sing"
ground truth.

Usage: vocal_pitch.py VOCALS.wav OUT_PREFIX [--start S --end S]
"""
import argparse
import json

import librosa
import numpy as np
import torch
import torchcrepe

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def key_scores(hist):
    out = []
    for i in range(12):
        for name, prof in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            out.append((float(np.corrcoef(hist, np.roll(prof, i))[0, 1]), f"{NOTES[i]} {name}"))
    return sorted(out, reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("out_prefix")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    a = ap.parse_args()

    sr = 16000
    y, _ = librosa.load(a.vocals, sr=sr, mono=True)
    torch.set_num_threads(4)
    hop = 160  # 10 ms
    audio = torch.tensor(y[None, :], dtype=torch.float32)
    f0, per = torchcrepe.predict(audio, sr, hop, fmin=65.0, fmax=1050.0, model="full",
                                 decoder=torchcrepe.decode.viterbi, return_periodicity=True,
                                 batch_size=512, device="cpu")
    per = torchcrepe.filter.median(per, 3)
    f0, per = f0[0].numpy(), per[0].numpy()
    times = np.arange(len(f0)) * hop / sr
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop, center=True)[0][:len(f0)]
    loud_db = 20 * np.log10(rms + 1e-9)

    sel = (per > 0.55) & (loud_db > np.percentile(loud_db, 40)) & (times >= a.start)
    if a.end is not None:
        sel &= times <= a.end
    midi = 69 + 12 * np.log2(np.maximum(f0, 1e-3) / 440.0)
    pcs = np.mod(np.round(midi[sel]), 12).astype(int)
    hist = np.bincount(pcs, weights=per[sel], minlength=12)
    hist = hist / (hist.sum() + 1e-9)
    ks = key_scores(hist)

    np.savez(a.out_prefix + ".npz", times=times, f0=f0, periodicity=per, loud_db=loud_db, voiced=sel)
    summary = {
        "vocals": a.vocals,
        "voiced_seconds": round(float(sel.sum() * hop / sr), 2),
        "pitch_class_hist": {NOTES[i]: round(float(hist[i]), 4) for i in range(12)},
        "top_keys": [{"key": k, "r": round(r, 3)} for r, k in ks[:6]],
        "range_midi": [round(float(np.percentile(midi[sel], 5)), 1), round(float(np.percentile(midi[sel], 95)), 1)],
        "median_midi": round(float(np.median(midi[sel])), 1),
    }
    with open(a.out_prefix + ".json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
