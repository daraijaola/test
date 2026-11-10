"""Coverage with the FULL ledger (every entry, no folding) vs raw posts at the same token
budget. The 32k-token view folds about half the entries (mostly one-author assertions), which
is where its 'partly' answers came from; this checks what an unfolded ledger buys.

Usage: python -m real_eval.coverage_full results/bsky_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points
from sim.baseline import BM25


def main(d: Path):
    st = pickle.loads((d / "ledger.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    ids = sorted(texts)
    rng = np.random.default_rng(42)
    rng.choice(ids, size=min(100, len(ids)), replace=False)           # same draws as bsky_eval
    sample = sorted(rng.choice(ids, size=min(150, len(ids)), replace=False).tolist())
    pts = points(texts, sample, st["topic"])
    full, shown = L.render(10_000_000)
    budget = L.est_tokens(full)
    bm = BM25([texts[i].lower().split() for i in ids])

    def fill(order):
        sel, used = [], 0
        for i in order:
            t = L.est_tokens(texts[i]) + 2
            if used + t > budget:
                break
            sel.append(i); used += t
        return "\n".join(f"- {texts[i]}" for i in sel)
    q = f"what do people say about {st['topic']}".split()
    ctx = {"full ledger (all entries)": full,
           "RAG top-k, same tokens": fill(bm.top(q, len(ids))),
           "random sample, same tokens": fill(np.random.default_rng(1).permutation(ids).tolist())}
    res = {"entries_shown": len(shown), "entries": len(L.entries), "points": len(pts)}
    for name, c in ctx.items():
        res[name] = {**coverage(name, c, pts), "context_tokens": L.est_tokens(c)}
        print(name, res[name], flush=True)
    (d / "coverage_full.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
