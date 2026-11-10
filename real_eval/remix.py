"""Contamination-free aggregate test.

SemEval-2016 is public, and the reader model appears to know its label statistics (in
round 1, RAG with 20 tweets reproduced the gold split to within a point). Here each
target's tweets are re-sampled to a stance mix far from the published one, so memorised
statistics give the wrong answer. A 'prior only' query (no data shown) measures how much
the reader brings from memory.

Usage: python -m real_eval.remix DATA_DIR --out results/real_remix [--absorber-version v1|v2]
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from real_eval import semeval

MIX = {  # (favor, against, none) shares, chosen to be far from each target's published split
    "abortion": (0.50, 0.20, 0.30),
    "atheism": (0.45, 0.25, 0.30),
    "climate": (0.30, 0.15, 0.55),
    "feminist": (0.50, 0.25, 0.25),
    "hillary": (0.40, 0.20, 0.40),
}


def remix(tweets, shares, cap=300, seed=0):
    rng = np.random.default_rng(seed)
    pools = {c: [t for t in tweets if t[1] == c] for c in ("favor", "against", "none")}
    n = int(min(cap, *(len(pools[c]) / s for c, s in zip(("favor", "against", "none"), shares))))
    out = []
    for c, s in zip(("favor", "against", "none"), shares):
        idx = rng.choice(len(pools[c]), size=int(round(n * s)), replace=False)
        out += [pools[c][i] for i in idx]
    rng.shuffle(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("results/real_remix"))
    ap.add_argument("--version", default="v1", choices=["v1", "v2"])
    a = ap.parse_args()
    semeval.CFG["version"] = a.version
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for t, shares in MIX.items():
        tw = remix(semeval.load(a.data_dir, t), shares)
        jobs.append((t, tw))
    with ThreadPoolExecutor(len(jobs)) as ex:
        res = list(ex.map(lambda j: semeval.run_target(j[0], a.data_dir, 40, 4, a.out, tweets=j[1],
                                                       tag=f"{j[0]}_remix"), jobs))
    (a.out / "summary.json").write_text(json.dumps({"spend": llm.SPEND}, indent=1))
    print(json.dumps({"spend": llm.SPEND}))


if __name__ == "__main__":
    main()
