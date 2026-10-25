#!/usr/bin/env python3
"""Stage-1 screening of every analysed clip against Juice's vocal.

For each candidate:
  tempo   : stretch needed to land on the freestyle tempo (100.45 BPM), allowing half/double time
  harmony : consonance of Juice's sung pitch-class histogram with the clip's chroma at the best
            transposition (-3..+3 semitones, small penalty per semitone), normalised by the same
            measure on the original Reine beat (1.0 = fits as well as the beat he actually used)
  vibe    : CLAP cosine to the Reine beat + Juice-style reference centroid + text prompts
  instr   : CLAP zero-shot "instrumental" vs "vocals" probability
  source  : full-length audio obtainable (needed for the real production)
Writes scored.jsonl sorted by total score and prints a per-source / per-bucket summary.

Clips without a CLAP embedding (tier 1 only) get a neutral vibe so harmony/tempo decide;
the shortlist is CLAP-embedded afterwards and rescored.

Usage: score_catalog.py CATALOG.jsonl ANALYSIS_DIR JUICE_PITCH.json REINE_CHROMA.npy REINE_CLAP.npy OUT.jsonl
"""
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fitscore import INTERVAL_W  # noqa: E402

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
TARGET_BPM = 100.446  # live tempo, regression fit of the live beat (work/analysis/grid_refined.json)
PROMPTS_POS = ["emotional melodic hip hop beat with guitar", "sad emo rap instrumental",
               "romantic r&b instrumental", "warm afro pop instrumental", "melodic trap beat with piano"]
PROMPTS_INSTR = ["instrumental music without vocals", "a song with a person singing vocals"]


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:150]


def consonance(h, c):
    d = np.mod(np.arange(12)[:, None] - np.arange(12)[None, :], 12)
    return float(h @ (INTERVAL_W[d]) @ c)


def best_transpose(h, c, max_k=3, penalty=0.012):  # ~6% of the Reine baseline per semitone
    best = (-9, 0)
    for k in range(-max_k, max_k + 1):
        s = consonance(h, np.roll(c, k)) - penalty * abs(k)
        if s > best[0]:
            best = (s, k)
    return best


def tempo_fit(bpm):
    if not bpm or bpm <= 0:
        return 0.0, None, None
    opts = [(abs(TARGET_BPM / (bpm * m) - 1), m) for m in (0.5, 1.0, 2.0)]
    dev, m = min(opts)
    ratio = TARGET_BPM / (bpm * m)
    return float(np.exp(-(dev / 0.06) ** 2)), round(ratio, 4), m


def text_embeddings(prompts):
    import torch
    from transformers import ClapModel, ClapProcessor

    model = ClapModel.from_pretrained("laion/clap-htsat-unfused").eval()
    proc = ClapProcessor.from_pretrained("laion/clap-htsat-unfused")
    with torch.no_grad():
        e = model.get_text_features(**proc(text=prompts, return_tensors="pt", padding=True))
    if not isinstance(e, torch.Tensor):
        e = e.pooler_output if hasattr(e, "pooler_output") else e[0]
    e = e.numpy()
    return e / np.linalg.norm(e, axis=1, keepdims=True)


def main():
    cat_path, adir, pitch_json, reine_chroma, reine_clap, out_path = sys.argv[1:7]
    no_vibe = "--no-vibe" in sys.argv   # tier 1: rank on harmony/tempo only, ignore any CLAP present
    cat = {}
    for line in open(cat_path):
        if line.strip():
            r = json.loads(line)
            cat[r["id"]] = r
    feats = [json.loads(l) for l in open(os.path.join(adir, "features.jsonl")) if l.strip()]
    feats = [f for f in feats if "error" not in f and f["id"] in cat]
    hj = json.load(open(pitch_json))["pitch_class_hist"]
    h = np.array([hj[n] for n in NOTES])
    rc = np.load(reine_chroma)
    rc = rc / rc.sum()
    base = consonance(h, rc)
    rclap = np.load(reine_clap)

    E = {}
    for f in feats:
        p = os.path.join(adir, "clap", safe(f["id"]) + ".npy")
        if os.path.exists(p) and not no_vibe:
            E[f["id"]] = np.load(p)
    refs = [E[f["id"]] for f in feats if cat[f["id"]].get("is_reference") and f["id"] in E]
    ref_centroid = np.mean(refs, axis=0) if refs else rclap.copy()
    ref_centroid /= np.linalg.norm(ref_centroid)
    have_clap = len(E) > 0
    if have_clap:
        T_pos = text_embeddings(PROMPTS_POS)
        T_ins = text_embeddings(PROMPTS_INSTR)
    neutral_vibe = 0.25
    rows = []
    for f in feats:
        c = cat[f["id"]]
        if c.get("is_reference"):
            continue
        ch = np.array(f["chroma_mean"])
        hs, k = best_transpose(h, ch)
        harmony = hs / base if base > 0 else hs
        tscore, ratio, mult = tempo_fit(f["bpm"])
        e = E.get(f["id"])
        if e is not None:
            vibe = 0.4 * float(e @ rclap) + 0.4 * float(e @ ref_centroid) + 0.2 * float(np.max(T_pos @ e))
            logits = 100 * (T_ins @ e)
            p_instr = float(np.exp(logits[0] - logits.max()) / np.exp(logits - logits.max()).sum())
        else:
            vibe, p_instr = neutral_vibe, 0.5
        if c.get("is_instrumental_meta") is True:
            p_instr = max(p_instr, 0.8)
        source = 1.0 if c.get("full_audio_available") else 0.35
        total = (0.32 * np.clip(harmony, -0.5, 1.5) + 0.22 * tscore + 0.28 * vibe * 2.5
                 + 0.08 * p_instr + 0.10 * source)
        rows.append({"id": f["id"], "source": c["source"], "title": c.get("title"), "artist": c.get("artist"),
                     "page_url": c.get("page_url"), "full_audio_available": c.get("full_audio_available"),
                     "full_audio_url": c.get("full_audio_url"), "clip_path": c.get("clip_path"),
                     "license": c.get("license"), "bpm": f["bpm"], "stretch": ratio, "tempo_mult": mult,
                     "transpose": k, "harmony": round(harmony, 3), "tempo_score": round(tscore, 3),
                     "vibe": round(vibe, 3), "has_clap": e is not None, "p_instr": round(p_instr, 3), "key": f["keys"]["edma"][0],
                     "total": round(float(total), 4)})
    rows.sort(key=lambda r: -r["total"])
    # the same song often appears in several libraries: keep its best-scoring row
    seen, uniq = set(), []
    for r in rows:
        key = (re.sub(r"[^a-z0-9]", "", (r["artist"] or "").lower())[:40],
               re.sub(r"\(.*?\)|\[.*?\]|[^a-z0-9]", "", (r["title"] or "").lower())[:60])
        if key in seen and key != ("", ""):
            continue
        seen.add(key)
        uniq.append(r)
    rows = uniq
    with open(out_path, "w") as fo:
        for r in rows:
            fo.write(json.dumps(r) + "\n")
    print(f"baseline consonance with Reine: {base:.4f}; scored {len(rows)} candidates")
    for r in rows[:40]:
        print(f"{r['total']:.3f} h={r['harmony']:.2f} t={r['tempo_score']:.2f} v={r['vibe']:.2f} i={r['p_instr']:.2f} "
              f"k={r['transpose']:+d} x{r['stretch']} [{r['source']}] {r['artist']} - {r['title']}"[:170])


if __name__ == "__main__":
    main()
