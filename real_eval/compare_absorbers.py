"""Is absorber strength the bottleneck? Two ledgers of the SAME posts built with different
absorber models, compared on: filing audit (same 100 posts, same judge), coverage of the same
sampled points (theme view and full ledger), size, and ingest cost.

Usage: python -m real_eval.compare_absorbers DIR_HAIKU DIR_SONNET
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import audit, coverage, points


def main(a: Path, b: Path):
    sts = {d.name: pickle.loads((d / "ledger.pkl").read_bytes()) for d in (a, b)}
    texts = next(iter(sts.values()))["texts"]
    ids = sorted(texts)
    rng = np.random.default_rng(5)
    aud = sorted(rng.choice(ids, size=100, replace=False).tolist())
    pts = points(texts, sorted(rng.choice(ids, size=150, replace=False).tolist()))
    res = {"points": len(pts)}
    for name, st in sts.items():
        L = st["ledger"]
        ing = json.loads((Path(a.parent) / name / "ingest.json").read_text())
        r = {"entries": len(L.entries), "ingest_usd": ing["usd"], "residual_pct": ing["residual_pct"],
             "audit": {k: v for k, v in audit(L, texts, aud).items() if k != "wrong_notes"}}
        for view, (text, _) in (("theme view", L.render_multires(32000)), ("full ledger", L.render(10_000_000))):
            r[view] = {**coverage(view, text, pts), "tokens_est": L.est_tokens(text)}
        res[name] = r
        print(name, json.dumps(r), flush=True)
    (b / "compare_absorbers.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
