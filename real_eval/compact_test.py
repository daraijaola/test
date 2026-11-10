"""Standard vs compact line format at the same budget (more entries fit when lines carry the
same numbers in fewer tokens). Same points, same judge run.
Usage: python -m real_eval.compact_test results/bsky_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from real_eval.bsky_eval import coverage, points


def main(d: Path):
    st = pickle.loads((d / "ledger_v3.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    res = []
    for r in range(2):
        rng = np.random.default_rng(5000 + r)
        pts = points(texts, sorted(rng.choice(sorted(texts), size=150, replace=False).tolist()), st["topic"])
        row = {}
        for name, compact in (("standard lines", False), ("compact lines", True)):
            text, shown = L.render_multires(32000, compact=compact)
            row[name] = {**coverage(name, text, pts), "entries_shown": len(shown)}
            print(r, name, {k: round(v, 3) for k, v in row[name].items()}, flush=True)
        res.append(row)
    (d / "compact_test.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
