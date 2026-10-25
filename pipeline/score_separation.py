#!/usr/bin/env python3
"""Rank separation models on a real recording without ground truth (proxy metrics),
and optionally on a synthetic mixture with ground truth (SDR).

Proxy metrics (per model, lower is better unless noted):
  silence_bleed_db   vocal-stem level in frames where the model consensus says nobody sings
  drum_bleed_ratio   percussive energy of the vocal stem ON beats vs OFF beats (kick/snare leakage)
  sub_bleed_db       vocal-stem energy below 80 Hz relative to 200-4000 Hz (bass/kick leakage)
  vocal_in_inst_db   instrumental-stem energy at the sung f0 harmonics, relative to the vocal stem
  vocal_capture_db   (higher is better) vocal-stem level vs consensus in sung frames
Synthetic (--truth-vocals/--truth-inst): SDR of vocals and instrumental vs the truth.

Usage:
  score_separation.py MIX.wav STEMS_DIR OUT.json --beats-json analysis.json [--offset S]
  score_separation.py MIX.wav STEMS_DIR OUT.json --truth-vocals V.wav --truth-inst I.wav
"""
import argparse
import json
from pathlib import Path

import librosa
import numpy as np

SR = 44100
HOP = 1024


def load(p):
    y, _ = librosa.load(p, sr=SR, mono=True)
    return y


def frames_db(y):
    r = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    return 20 * np.log10(r + 1e-9)


def sdr(est, ref):
    n = min(len(est), len(ref))
    est, ref = est[:n], ref[:n]
    return float(10 * np.log10(np.sum(ref ** 2) / (np.sum((ref - est) ** 2) + 1e-12) + 1e-12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mix")
    ap.add_argument("stems_dir")
    ap.add_argument("out")
    ap.add_argument("--beats-json")
    ap.add_argument("--beats", default="")
    ap.add_argument("--truth-vocals")
    ap.add_argument("--truth-inst")
    a = ap.parse_args()

    models = sorted(d for d in Path(a.stems_dir).iterdir() if (d / "vocals.wav").exists())
    stems = {d.name: (load(str(d / "vocals.wav")), load(str(d / "instrumental.wav"))) for d in models}
    res = {m: {} for m in stems}

    if a.truth_vocals:
        tv, ti = load(a.truth_vocals), load(a.truth_inst)
        for m, (v, i) in stems.items():
            res[m]["sdr_vocals"] = round(sdr(v, tv), 2)
            res[m]["sdr_inst"] = round(sdr(i, ti), 2)
    else:
        n = min(len(v) for v, _ in stems.values())
        V = np.stack([v[:n] for v, _ in stems.values()])
        cons = np.median(V, axis=0)
        cdb = frames_db(cons)
        sung = cdb > np.percentile(cdb, 60)
        silent = cdb < (np.percentile(cdb, 95) - 35)
        beats = np.array([float(b) for b in a.beats.split(",") if b]) if a.beats else np.array([])
        if a.beats_json:
            beats = np.array(json.load(open(a.beats_json)))
        # f0 of consensus vocal for leakage-at-harmonics measurement
        f0, vflag, _ = librosa.pyin(cons, fmin=70, fmax=900, sr=SR, frame_length=4096, hop_length=HOP)
        for m, (v, i) in stems.items():
            v, i = v[:n], i[:n]
            vdb = frames_db(v)
            k = min(len(vdb), len(cdb))
            r = res[m]
            r["silence_bleed_db"] = round(float(np.mean(vdb[:k][silent[:k]])) if silent[:k].any() else float("nan"), 2)
            r["vocal_capture_db"] = round(float(np.mean(vdb[:k][sung[:k]] - cdb[:k][sung[:k]])), 2)
            S = np.abs(librosa.stft(v, n_fft=4096, hop_length=HOP))
            fr = librosa.fft_frequencies(sr=SR, n_fft=4096)
            sub = S[fr < 80].sum(axis=0)
            mid = S[(fr > 200) & (fr < 4000)].sum(axis=0)
            r["sub_bleed_db"] = round(float(20 * np.log10(sub.sum() / (mid.sum() + 1e-9) + 1e-9)), 2)
            if len(beats):
                _, perc = librosa.decompose.hpss(S)
                pe = perc.sum(axis=0)
                bf = librosa.time_to_frames(beats, sr=SR, hop_length=HOP)
                bf = bf[bf < len(pe) - 2]
                on = np.concatenate([pe[max(0, b - 1):b + 2] for b in bf]).mean()
                offf = librosa.time_to_frames(beats[:-1] + np.diff(beats) / 2, sr=SR, hop_length=HOP)
                offf = offf[offf < len(pe) - 2]
                off = np.concatenate([pe[max(0, b - 1):b + 2] for b in offf]).mean()
                r["drum_bleed_ratio"] = round(float(on / (off + 1e-9)), 3)
            Si = np.abs(librosa.stft(i, n_fft=4096, hop_length=HOP))
            leak, ref = [], []
            for t in range(min(len(f0), S.shape[1], Si.shape[1])):
                if not vflag[t] or np.isnan(f0[t]):
                    continue
                bins = [int(round(h * f0[t] / (SR / 4096))) for h in range(1, 9) if h * f0[t] < 8000]
                leak.append(Si[bins, t].sum())
                ref.append(S[bins, t].sum())
            r["vocal_in_inst_db"] = round(float(20 * np.log10(np.sum(leak) / (np.sum(ref) + 1e-9) + 1e-9)), 2) if leak else None

    # rank: z-score each metric (sign so that lower = better), average
    keys = [k for k in next(iter(res.values())).keys()]
    better_high = {"vocal_capture_db", "sdr_vocals", "sdr_inst"}
    for k in keys:
        vals = np.array([res[m][k] for m in res if res[m].get(k) is not None], dtype=float)
        if len(vals) < 2 or np.nanstd(vals) == 0:
            continue
        for m in res:
            if res[m].get(k) is None:
                continue
            z = (res[m][k] - np.nanmean(vals)) / np.nanstd(vals)
            res[m].setdefault("_z", {})[k] = round(float(z if k in better_high else -z), 2)
    for m in res:
        zs = res[m].get("_z", {})
        res[m]["score"] = round(float(np.mean(list(zs.values()))), 3) if zs else None
    ranked = sorted(res.items(), key=lambda kv: -(kv[1]["score"] or -9))
    for m, r in ranked:
        print(f"{m:55s} score={r['score']}  " + "  ".join(f"{k}={v}" for k, v in r.items() if k not in ("_z", "score")))
    json.dump(dict(ranked), open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
