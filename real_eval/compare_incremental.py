"""Incremental vs batch: is a ledger built as ingest(older posts) + update(newer posts)
equivalent to one built from all posts at once?

Compares: size, residual, anchor split, entries whose authors are mostly recent, and coverage
of the same sampled points (same judge run). Points are sampled from the NEW posts as well
as from all posts, since the update is what is being tested.

Usage: python -m real_eval.compare_incremental results/bsky_seedoils results/incremental_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points


def summary(L):
    a = L.entries[0].authors_by_stance()
    pos = a["support"] + a["dispute"]
    return {"posts": len(L.docs), "entries": len(L.entries), "residual_pct": 100 * L.residual_mass / len(L.docs),
            "anchor_agree": a["support"], "anchor_disagree": a["dispute"],
            "anchor_agree_share": a["support"] / max(1, pos)}


def main(batch_dir: Path, inc_dir: Path):
    B = pickle.loads((batch_dir / "ledger_v3.pkl").read_bytes())
    I = pickle.loads((inc_dir / "ledger.pkl").read_bytes())
    res = {"batch": summary(B["ledger"]), "incremental": summary(I["ledger"])}
    texts = I["texts"]
    abs_t = I["abs_t"]
    new_ids = sorted(i for i, t in abs_t.items() if t is not None and t >= 1790812800)   # 2026-10-01T00:00Z
    rng = np.random.default_rng(11)
    samples = {"all posts": sorted(rng.choice(sorted(texts), size=150, replace=False).tolist()),
               "new posts only": sorted(rng.choice(new_ids, size=min(120, len(new_ids)), replace=False).tolist())}
    for sname, ids in samples.items():
        pts = points(texts, ids, I["topic"])
        for name, st in (("batch", B), ("incremental", I)):
            view, _ = st["ledger"].render_multires(32000)
            r = coverage(f"{name} ledger", view, pts)
            res[f"{sname} | {name}"] = r
            print(sname, name, {k: round(v, 3) for k, v in r.items()}, flush=True)
    (inc_dir / "compare_incremental.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if "|" not in k}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
