"""Breadth vs specificity at a fixed budget: the theme view as-is vs the same view with one
verbatim exemplar quote per entry (found by provenance; fewer entries fit). Same points,
same judge run. Quote views contain raw post text and are not written to disk.

Usage: python -m real_eval.quotes_test results/bsky_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points


def main(d: Path):
    st = pickle.loads((d / "ledger.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    ids = sorted(texts)
    res = []
    for r in range(2):
        rng = np.random.default_rng(3000 + r)
        pts = points(texts, sorted(rng.choice(ids, size=150, replace=False).tolist()))
        row = {"points": len(pts)}
        for name, (text, shown) in (("plain view", L.render_multires(32000)),
                                    ("view + quotes", L.render_multires(32000, quotes=texts))):
            row[name] = {**coverage(name, text, pts), "entries_shown": len(shown), "tokens_est": L.est_tokens(text)}
            print(r, name, {k: round(v, 3) for k, v in row[name].items()}, flush=True)
        res.append(row)
    (d / "quotes_test.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
