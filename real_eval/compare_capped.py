"""Uncapped vs capped absorber index (+ cache warming) on the same 27.5k posts: cost, size,
filing quality, subject share, and coverage of the same points (compact view, same judge run).

Usage: python -m real_eval.compare_capped results/bsky_nuclear results/bsky_nuclear_capped
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import audit, coverage, points


def main(a: Path, b: Path):
    res = {}
    sts = {d.name: pickle.loads((d / "ledger_v3.pkl").read_bytes()) for d in (a, b)}
    texts = sts[a.name]["texts"]
    topic = sts[a.name]["topic"]
    ids = sorted(texts)
    for r in range(2):
        rng = np.random.default_rng(7000 + r)
        pts = points(texts, sorted(rng.choice(ids, size=150, replace=False).tolist()), topic)
        for name, st in sts.items():
            view, _ = st["ledger"].render_multires(32000, compact=True)
            res[f"run{r} | {name}"] = coverage(name, view, pts)
            print(r, name, {k: round(v, 3) for k, v in res[f"run{r} | {name}"].items()}, flush=True)
    aud = sorted(np.random.default_rng(5).choice(ids, size=100, replace=False).tolist())
    for name, st in sts.items():
        L = st["ledger"]
        ing = json.loads((Path(a.parent) / name / "ingest.json").read_text())
        an = L.entries[0].authors_by_stance()
        res[name] = {"entries": len(L.entries), "ingest_usd": ing["usd"], "usd_by_stage": ing["usd_by_stage"],
                     "residual_pct": ing["residual_pct"],
                     "agree_share": an["support"] / max(1, an["support"] + an["dispute"]),
                     "audit": {k: v for k, v in audit(L, texts, aud, topic).items() if k != "wrong_notes"}}
        print(name, json.dumps(res[name]), flush=True)
    (b / "compare_capped.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
