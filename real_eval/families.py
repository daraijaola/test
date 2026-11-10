"""Claim families: fix the 'ledger tallies are lower bounds for broad claims' weakness found in
the prevalence test. One pass of the stronger model over the INDEX (not the posts) proposes
broad claims and assigns entries to them; each family then reports the exact union of
distinct authors across its members (from provenance). Re-runs the prevalence questions
from prevalence_test.json against the same golds, plus a coverage check.

Usage: python -m real_eval.families results/bsky_4dw
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from celedger import llm
from real_eval.bsky_eval import coverage, points

FAM = {"type": "object", "additionalProperties": False, "required": ["families"],
       "properties": {"families": {"type": "array", "items": {"type": "string"}}}}
ASSIGN = {"type": "object", "additionalProperties": False, "required": ["entries"],
          "properties": {"entries": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["id", "family"],
              "properties": {"id": {"type": "integer"}, "family": {"type": "integer"}}}}}}
NUM = {"type": "object", "additionalProperties": False, "required": ["authors", "reasoning"],
       "properties": {"authors": {"type": "number"}, "reasoning": {"type": "string"}}}


def build_families(L, topic):
    lines = [f"e{e.eid}: {e.text}" for e in sorted(L.entries.values(), key=lambda e: -len(e.author_stance))
             if e.eid != 0]
    out, _ = llm.complete("claude-sonnet-5-5", "You organise a claim ledger. Output JSON only.",
                          f"TOPIC: {topic}\nPropose 60-120 BROAD CLAIMS (each a statement someone could agree or "
                          "disagree with) such that most entries below are a specific instance or rewording of one of "
                          "them. Cover both sides. One sentence each.\n\n" + "\n".join(lines[:900]), FAM, effort="medium")
    fams = {k: t for k, t in enumerate(out["families"])}
    table = "\n".join(f"F{k}: {t}" for k, t in fams.items())
    for s in range(0, len(lines), 250):
        out, _ = llm.complete("claude-sonnet-5-5", "You organise a claim ledger. Output JSON only.",
                              f"BROAD CLAIMS:\n{table}\n\nFor every entry below give the number of the broad claim it is an "
                              "instance or rewording of (asserting the entry implies asserting the broad claim), or -1 if "
                              "none fits.\n\n" + "\n".join(lines[s:s + 250]), ASSIGN)
        for r in out["entries"]:
            if r["id"] in L.entries and r["family"] in fams:
                L.entries[r["id"]].family = r["family"]
    return fams


def main(d: Path):
    st = pickle.loads((d / "ledger_v3.pkl").read_bytes())
    L, texts, topic = st["ledger"], st["texts"], st["topic"]
    n = len(texts)
    s0 = llm.SPEND["usd"]
    fams = build_families(L, topic)
    fam_usd = llm.SPEND["usd"] - s0
    view_f, _ = L.render_with_families(fams, 32000)
    view_p, _ = L.render_multires(32000)
    prev = json.loads((d / "prevalence_test.json").read_text())
    strong = {}
    if (d / "census_vs_strong.json").exists():
        strong = {r["claim"]: r["strong_authors"] for r in json.loads((d / "census_vs_strong.json").read_text())["rows"]}
    rows = []
    for r in prev["rows"]:
        ans, _ = llm.complete("claude-opus-5-5",
                              f"You estimate corpus statistics for a corpus of {n} posts on {topic}, using ONLY the "
                              "material below. Output JSON only.\n\nTHE COMPLETE LEDGER OF THE CORPUS:\n" + view_f,
                              f"How many DISTINCT AUTHORS in the whole corpus assert this claim (in substance)? "
                              f"Claim: '{r['claim']}'. Give your best numeric estimate.", NUM, effort="medium")
        row = {"claim": r["claim"], "gold_cheap_census": r["gold_authors"], "gold_strong": strong.get(r["claim"]),
               "ledger_with_families": ans["authors"], **{k: v for k, v in r["answers"].items()}}
        rows.append(row)
        print(f"cheap-gold {row['gold_cheap_census']} strong-gold {row['gold_strong']} | families "
              f"{ans['authors']:.0f} | plain {r['answers']['ledger (theme view)']:.0f} | summary "
              f"{r['answers']['map-reduce summary']:.0f} | {r['claim'][:60]}", flush=True)
    summ = {}
    methods = ["ledger_with_families", "ledger (theme view)", "map-reduce summary", "retrieval top-k, same budget"]
    for gold in ("gold_cheap_census", "gold_strong"):
        rs = [r for r in rows if r[gold] is not None]
        if not rs:
            continue
        for m in methods:
            err = [abs(r[m] - r[gold]) / max(1, r[gold]) for r in rs]
            summ[f"{gold} | {m}"] = {"median_rel_error": float(np.median(err)),
                                     "within_50pct": float(np.mean([e <= 0.5 for e in err]))}
    rng = np.random.default_rng(1000)
    pts = points(texts, sorted(rng.choice(sorted(texts), size=150, replace=False).tolist()), topic)
    cov = {"plain view": coverage("plain", view_p, pts), "view with families": coverage("families", view_f, pts)}
    res = {"families": len(fams), "entries_in_families": sum(1 for e in L.entries.values() if e.family is not None),
           "entries": len(L.entries), "family_pass_usd": fam_usd, "rows": rows, "summary": summ, "coverage": cov}
    (d / "families.json").write_text(json.dumps(res, indent=1))
    st["families"] = fams
    (d / "ledger_fam.pkl").write_bytes(pickle.dumps(st))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
