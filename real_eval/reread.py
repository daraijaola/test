"""Re-ask the reader on saved v2 ledgers after adding the anchor legend to the render;
also report the anchor-only computed estimate. No re-ingestion.
Usage: python -m real_eval.reread results/real_remix_v2
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from real_eval import semeval


def one(f: Path):
    st = pickle.loads(f.read_bytes())
    L, tweets, topic = st["ledger"], st["tweets"], st["topic"]
    n = len(tweets)
    gold = {k: 100 * sum(g == k for _, g in tweets) / n for k in ("favor", "against", "none")}
    a = L.entries[0].authors_by_stance()
    anchor = {"favor": 100 * a["support"] / n, "against": 100 * a["dispute"] / n}
    anchor["none"] = 100 - anchor["favor"] - anchor["against"]
    render, _ = L.render(32000)
    log = []
    read = semeval.ask_distribution("THE COMPLETE LEDGER OF THIS CORPUS:\n" + render, topic, n, log, "reread")
    return {"tag": f.stem, "gold": gold, "anchor_only": anchor, "read_with_legend": read,
            "mae_anchor_only": semeval.dist_mae(anchor, gold), "mae_read_with_legend": semeval.dist_mae(read, gold),
            "usd": sum(u for _, u in log)}


if __name__ == "__main__":
    d = Path(sys.argv[1])
    with ThreadPoolExecutor(5) as ex:
        rows = list(ex.map(one, sorted(d.glob("ledger_*.pkl"))))
    (d / "reread.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        print(r["tag"], "anchor-only %.1f  read+legend %.1f" % (r["mae_anchor_only"], r["mae_read_with_legend"]))
    print("MEAN anchor-only %.1f  read+legend %.1f" % (np.mean([r["mae_anchor_only"] for r in rows]),
                                                       np.mean([r["mae_read_with_legend"] for r in rows])))
