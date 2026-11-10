"""Head-to-head coverage of two ledgers of the same corpus (e.g. v2 vs v4 'refine'), with
the SAME sampled points and the same judge run, at both the theme view and the full ledger.

Usage: python -m real_eval.compare_versions DIR_A DIR_B   (each holding ledger_v3.pkl)
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points


def main(a: Path, b: Path):
    La = pickle.loads((a / "ledger_v3.pkl").read_bytes())
    Lb = pickle.loads((b / "ledger_v3.pkl").read_bytes())
    texts = La["texts"]
    ids = sorted(texts)
    rng = np.random.default_rng(42)
    rng.choice(ids, size=min(100, len(ids)), replace=False)
    sample = sorted(rng.choice(ids, size=min(150, len(ids)), replace=False).tolist())
    pts = points(texts, sample)
    res = {"points": len(pts)}
    for tag, st in ((a.name, La), (b.name, Lb)):
        L = st["ledger"]
        for view, (text, _) in (("theme view", L.render_multires(32000)), ("full ledger", L.render(10_000_000))):
            r = coverage(f"{tag} {view}", text, pts)
            r["context_tokens_est"] = L.est_tokens(text)
            r["entries"] = len(L.entries)
            r["refinements"] = sum(1 for e in L.entries.values() if e.parent is not None)
            res[f"{tag} | {view}"] = r
            print(tag, view, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
    (b / "compare_versions.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
