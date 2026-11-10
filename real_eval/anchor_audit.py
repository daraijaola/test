"""Anchor audit: an independent judge labels each sampled post's position on the anchor
statement (agree / disagree / none); compare with the ledger's anchor op to split errors
into missing (judge sees a position, ledger has no anchor op), inverted, and spurious.

Usage: python -m real_eval.anchor_audit results/bsky_seedoils [--n 150]
"""
from __future__ import annotations

import argparse
import json
import pickle
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm

JUDGE = "claude-sonnet-5-5"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["posts"],
          "properties": {"posts": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["post_id", "position"],
              "properties": {"post_id": {"type": "integer"},
                             "position": {"type": "string", "enum": ["agree", "disagree", "none"]}}}}}}


def ledger_position(L, d):
    for e, b, w in L.log[d]:
        if e is not None and L.resolve(e) == 0:
            return {"support": "agree", "dispute": "disagree"}.get(b, "none")
    return "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--pkl", default="ledger.pkl")
    a = ap.parse_args()
    st = pickle.loads((a.dir / a.pkl).read_bytes())
    L, texts = st["ledger"], st["texts"]
    statement = L.entries[0].text.replace("ANCHOR: ", "")
    ids = sorted(np.random.default_rng(7).choice(sorted(texts), size=a.n, replace=False).tolist())

    def one(chunk):
        user = (f"STATEMENT: {statement}\nFor each post: does its author AGREE or DISAGREE with the statement? "
                "Count clear signals (explicit claims, sarcasm, mocking one side, praising the other). Answer none "
                "if the post gives no discernible position on the statement.\n\n" +
                "\n".join(f"<post id={d}>{texts[d]}</post>" for d in chunk))
        out, _ = llm.complete(JUDGE, "You label stance. Output JSON only.", user, SCHEMA, effort="medium")
        return out["posts"]
    with ThreadPoolExecutor(4) as ex:
        rows = [r for rs in ex.map(one, [ids[i:i + 25] for i in range(0, len(ids), 25)]) for r in rs]
    cm = Counter((r["position"], ledger_position(L, r["post_id"])) for r in rows if r["post_id"] in L.log)
    judged_pos = sum(v for (j, l), v in cm.items() if j != "none")
    res = {"n": len(rows), "confusion_judge_vs_ledger": {f"{j}->{l}": v for (j, l), v in sorted(cm.items())},
           "agreement": sum(v for (j, l), v in cm.items() if j == l) / max(1, sum(cm.values())),
           "missing": sum(v for (j, l), v in cm.items() if j != "none" and l == "none") / max(1, judged_pos),
           "inverted": sum(v for (j, l), v in cm.items() if {j, l} == {"agree", "disagree"}) / max(1, judged_pos),
           "spurious": sum(v for (j, l), v in cm.items() if j == "none" and l != "none") /
           max(1, sum(v for (j, l), v in cm.items() if j == "none"))}
    # what the anchor-based share would be under the judge's labels vs the ledger's, on this sample
    for who, idx in (("judge", 0), ("ledger", 1)):
        c = Counter(k[idx] for k, v in cm.items() for _ in range(v))
        res[f"{who}_agree_share_among_positioned"] = c["agree"] / max(1, c["agree"] + c["disagree"])
    (a.dir / f"anchor_audit_{Path(a.pkl).stem}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
