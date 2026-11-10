"""v3: subject stance from a dedicated pass instead of an optional extra in the main pass.

The anchor question is fixed at setup ("does this author agree with the anchor statement?"),
so one cheap call per batch of posts that asks only that has far higher recall than asking
the absorber to remember it while filing assertions (round-5 audit: 54-71% of positions
were missing in v2). Each post's anchor op is replaced, mass-conservingly.

Usage: python -m real_eval.anchor_pass results/bsky_seedoils   (writes ledger_v3.pkl + renders)
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from celedger import llm
from real_eval.anchor_audit import SCHEMA

MODEL = "claude-haiku-5-5"


def run_anchor(L, texts: dict, ids: list) -> float:
    """Dedicated anchor pass over `ids`; replaces each post's anchor op (mass-conserving).
    Returns the model spend."""
    statement = L.entries[0].text.replace("ANCHOR: ", "")

    def one(chunk):
        user = (f"STATEMENT: {statement}\nFor each post: does its author AGREE or DISAGREE with the statement? "
                "Count clear signals (explicit claims, sarcasm, mocking one side, praising the other). Answer none "
                "if the post gives no discernible position on the statement.\n\n" +
                "\n".join(f"<post id={i}>{texts[i]}</post>" for i in chunk))
        out, usd = llm.complete(MODEL, "You label stance. Output JSON only.", user, SCHEMA)
        return out["posts"], usd
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, [ids[i:i + 50] for i in range(0, len(ids), 50)]))
    pos = {r["post_id"]: r["position"] for rows, _ in res for r in rows}
    touched = set()
    for i in ids:
        rows = [(e if e is None else L.resolve(e), s) for e, s, _ in L.log[i]]
        rest = [(e, s) for e, s in rows if e != 0]
        p = pos.get(i, "none")
        if p == "none":
            new = rest or [(None, "residual")]
        else:
            new = [(e, s) for e, s in rest if not (e is None and s == "noise")]
            new.append((0, "support" if p == "agree" else "dispute"))
        if sorted(map(str, new)) != sorted(map(str, rows)):
            touched |= L.replace_ops(i, new)
    for e in touched:
        if e in L.entries:
            L.recompute(e)
    L.check_conservation()
    return sum(u for _, u in res)


def main(d: Path):
    st = pickle.loads((d / "ledger.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    before = L.entries[0].authors_by_stance()
    usd = run_anchor(L, texts, sorted(texts))
    after = L.entries[0].authors_by_stance()
    st["ledger"] = L
    (d / "ledger_v3.pkl").write_bytes(pickle.dumps(st))
    (d / "ledger_v3_multires.txt").write_text(L.render_multires(32000)[0])
    info = {"anchor_before": before, "anchor_after": after, "usd": usd}
    (d / "anchor_pass.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
