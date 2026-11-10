"""How accurate is census on SEMANTIC claims? The prevalence test's gold was a Haiku census, so
'ledger + census' would be perfect by construction. Here an independent, stronger checker
(Sonnet, scanning every post) is the gold, and the cheap census is scored against it, on the
same claims as prevalence_test.

Usage: python -m real_eval.census_vs_strong results/bsky_4dw
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from celedger.cli import CHECK_SCHEMA


def scan(texts, ids, claim, model):
    pred = f"The author of this post asserts or endorses this claim (in substance): '{claim}'"

    def one(chunk):
        out, _ = llm.complete(model, "You check a predicate on each document. Output JSON only.",
                              f"PREDICATE: {pred}\nFor each document answer yes if the predicate holds.\n\n" +
                              "\n".join(f"<doc id={i}>{texts[i]}</doc>" for i in chunk), CHECK_SCHEMA)
        yes = {d["doc_id"] for d in out["docs"] if d["yes"]}
        return [i for i in chunk if i in yes]
    with ThreadPoolExecutor(8) as ex:
        return {h for hs in ex.map(one, [ids[i:i + 60] for i in range(0, len(ids), 60)]) for h in hs}


def main(d: Path):
    st = pickle.loads((d / "ledger_v3.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    prev = json.loads((d / "prevalence_test.json").read_text())
    ids = sorted(texts)
    rows = []
    for r in prev["rows"]:
        strong = scan(texts, ids, r["claim"], "claude-sonnet-5-5")
        cheap = scan(texts, ids, r["claim"], "claude-haiku-5-5")
        a_s = {L.docs[h].author for h in strong}
        a_c = {L.docs[h].author for h in cheap}
        row = {"claim": r["claim"], "strong_authors": len(a_s), "census_authors": len(a_c),
               "precision": len(cheap & strong) / max(1, len(cheap)), "recall": len(cheap & strong) / max(1, len(strong)),
               "answers_vs_strong": {k: v for k, v in r["answers"].items()}}
        rows.append(row)
        print(f"strong {len(a_s)} | census {len(a_c)} (P {row['precision']:.2f} R {row['recall']:.2f}) | " +
              " | ".join(f"{k} {v:.0f}" for k, v in r["answers"].items()) + f" | {r['claim'][:70]}", flush=True)
    summ = {}
    methods = {"ledger + census (cheap)": lambda r: r["census_authors"],
               **{k: (lambda r, k=k: r["answers_vs_strong"][k]) for k in rows[0]["answers_vs_strong"]}}
    for name, f in methods.items():
        err = [abs(f(r) - r["strong_authors"]) / max(1, r["strong_authors"]) for r in rows]
        summ[name] = {"median_rel_error": float(np.median(err)), "within_50pct": float(np.mean([e <= 0.5 for e in err])),
                      "within_25pct": float(np.mean([e <= 0.25 for e in err]))}
    res = {"rows": rows, "summary": summ}
    (d / "census_vs_strong.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
