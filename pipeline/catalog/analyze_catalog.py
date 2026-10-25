#!/usr/bin/env python3
"""Analyse every harvested clip: tempo, key, chroma profile, loudness, CLAP embedding.

Resumable and parallel: results are appended to features.jsonl (one row per
clip) and CLAP audio embeddings to clap/<safe_id>.npy, so a crash or timeout
never loses work. Rows already present are skipped.

Two tiers (CLAP is the expensive part on CPU):
  tier 1  --no-clap : tempo / key / chroma / loudness for every clip
  tier 2  --ids FILE: (re)run with CLAP only for the shortlisted ids, adding clap/<id>.npy

Usage: analyze_catalog.py CATALOG.jsonl OUT_DIR [--workers 3] [--no-clap] [--ids FILE] [--max-seconds N] [--limit N]
"""
import argparse
import json
import multiprocessing as mp
import os
import re
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")
SR = 22050
CLAP_ID = "laion/clap-htsat-unfused"
_state = {}


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:150]


def _init(use_clap=True):
    _state["clap"] = use_clap
    if not use_clap:
        return
    import torch
    from transformers import ClapModel, ClapProcessor

    torch.set_num_threads(1)
    _state["model"] = ClapModel.from_pretrained(CLAP_ID).eval()
    _state["proc"] = ClapProcessor.from_pretrained(CLAP_ID)


def clap_embed(y48):
    import torch

    proc, model = _state["proc"], _state["model"]
    n = 48000 * 10
    if len(y48) > n:  # centre 10 s window (CLAP's native context)
        s = (len(y48) - n) // 2
        y48 = y48[s:s + n]
    inp = proc(audio=[y48], sampling_rate=48000, return_tensors="pt")
    with torch.no_grad():
        e = model.get_audio_features(**inp)
    if not isinstance(e, torch.Tensor):  # newer transformers may wrap the output
        e = e.pooler_output if hasattr(e, "pooler_output") else e[0]
    e = e[0].numpy()
    return e / (np.linalg.norm(e) + 1e-9)


def analyse(row, out_dir):
    import essentia.standard as es
    import librosa

    path = row["clip_path"]
    y, _ = librosa.load(path, sr=SR, mono=True)
    if len(y) < SR * 15:
        raise ValueError("clip too short")
    y44 = librosa.resample(y, orig_sr=SR, target_sr=44100).astype(np.float32)
    bpm, beats, conf, _, _ = es.RhythmExtractor2013(method="degara")(y44)
    k, s, strength = es.KeyExtractor(profileType="edma")(y44)
    keys = {"edma": [f"{k} {s}", round(float(strength), 3)]}
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=1024)
    cmean = chroma.mean(axis=1)
    cmean = cmean / (cmean.sum() + 1e-9)
    rms = float(np.sqrt(np.mean(y ** 2)))
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=1024))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    centroid = float((S.mean(axis=1) * freqs).sum() / (S.mean(axis=1).sum() + 1e-9))
    if _state.get("clap"):
        y48 = librosa.resample(y, orig_sr=SR, target_sr=48000).astype(np.float32)
        emb = clap_embed(y48)
        np.save(os.path.join(out_dir, "clap", safe(row["id"]) + ".npy"), emb.astype(np.float32))
    return {
        "id": row["id"], "bpm": round(float(bpm), 2), "bpm_conf": round(float(conf), 2),
        "beats": [round(float(b), 3) for b in beats][:200],
        "keys": keys, "chroma_mean": [round(float(c), 4) for c in cmean],
        "rms_db": round(20 * np.log10(rms + 1e-9), 2), "centroid_hz": round(centroid, 1),
        "clip_dur": round(len(y) / SR, 2),
    }


def _work(args):
    row, out_dir = args
    try:
        return analyse(row, out_dir)
    except Exception as e:
        return {"id": row["id"], "error": f"{type(e).__name__}: {str(e)[:160]}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalog")
    ap.add_argument("out_dir")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-seconds", type=float, default=1e9)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-clap", action="store_true")
    ap.add_argument("--ids", default=None, help="file with one id per line: CLAP-embed only these")
    a = ap.parse_args()

    os.makedirs(os.path.join(a.out_dir, "clap"), exist_ok=True)
    feat_path = os.path.join(a.out_dir, "features.jsonl")
    done = set()
    if os.path.exists(feat_path):
        for line in open(feat_path):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    rows = [json.loads(l) for l in open(a.catalog) if l.strip()]
    if a.ids:  # tier 2: CLAP for shortlisted ids that have no embedding yet
        want = {l.strip() for l in open(a.ids) if l.strip()}
        todo = [r for r in rows if r["id"] in want and r.get("clip_path") and os.path.exists(r["clip_path"])
                and not os.path.exists(os.path.join(a.out_dir, "clap", safe(r["id"]) + ".npy"))]
        feat_path = os.path.join(a.out_dir, "features_tier2.jsonl")
    else:
        todo = [r for r in rows if r["id"] not in done and r.get("clip_path") and os.path.exists(r["clip_path"])]
    # Analyse the most promising rows first: references, then metadata tempo compatible with
    # 100 BPM (within 10%, half/double allowed), then unknown tempo, then incompatible.
    def priority(r):
        if r.get("is_reference"):
            return 0
        b = r.get("bpm_meta")
        if not b:
            return 2
        dev = min(abs(100.0 / (b * m) - 1) for m in (0.5, 1.0, 2.0))
        return 1 if dev <= 0.10 else 3
    todo.sort(key=priority)
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(rows)} in catalog, {len(done)} done, {len(todo)} to analyse", flush=True)
    t0, n_ok, n_err = time.time(), 0, 0
    use_clap = not a.no_clap
    with mp.get_context("spawn").Pool(a.workers, initializer=_init, initargs=(use_clap,)) as pool, open(feat_path, "a") as out:
        for res in pool.imap_unordered(_work, [(r, a.out_dir) for r in todo], chunksize=4):
            out.write(json.dumps(res) + "\n")
            out.flush()
            if "error" in res:
                n_err += 1
            else:
                n_ok += 1
            if (n_ok + n_err) % 100 == 0:
                rate = (n_ok + n_err) / (time.time() - t0)
                print(f"  {n_ok} ok / {n_err} err  ({rate:.2f} clips/s)", flush=True)
            if time.time() - t0 > a.max_seconds:
                print("time budget reached; stopping (resumable)", flush=True)
                pool.terminate()
                break
    print(f"finished: {n_ok} ok, {n_err} errors in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
