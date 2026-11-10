"""Error bars for the central coverage claim: repeat the equal-budget comparison (ledger
theme view vs retrieval vs random sample at the same token budget) with a fresh post
sample and a fresh judge run each time. Run-to-run judge noise was ~±5 points.

Usage: python -m real_eval.coverage_repeat results/bsky_seedoils --repeats 2
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points
from sim.baseline import BM25


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--repeats", type=int, default=2)
    a = ap.parse_args()
    st = pickle.loads((a.dir / "ledger.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    ids = sorted(texts)
    view, _ = L.render_multires(32000)
    budget = L.est_tokens(view)
    bm = BM25([texts[i].lower().split() for i in ids])
    q = f"what do people say about {st['topic']}".split()

    def fill(order):
        sel, used = [], 0
        for i in order:
            t = L.est_tokens(texts[i]) + 2
            if used + t > budget:
                break
            sel.append(i); used += t
        return "\n".join(f"- {texts[i]}" for i in sel)
    runs = []
    for r in range(a.repeats):
        rng = np.random.default_rng(1000 + r)
        pts = points(texts, sorted(rng.choice(ids, size=150, replace=False).tolist()), st["topic"])
        ctx = {"ledger (theme view)": view, "RAG top-k, same tokens": fill(bm.top(q, len(ids))),
               "random sample, same tokens": fill(rng.permutation(ids).tolist())}
        run = {"points": len(pts)}
        for name, c in ctx.items():
            run[name] = coverage(name, c, pts)
            print(r, name, {k: round(v, 3) for k, v in run[name].items()}, flush=True)
        runs.append(run)
    (a.dir / "coverage_repeat.json").write_text(json.dumps(runs, indent=1))


if __name__ == "__main__":
    main()
