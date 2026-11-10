"""The decisive comparison against summarise-everything: PREVALENCE of specific claims.

"How many distinct people assert X?" Claims are drawn half from the ledger (entries at
ranks 2, 5, 10, 20) and half from the summary (4 claims a judge extracts from it, of varying
prominence), so neither method picks its own questions. Gold = exhaustive census over every
post (cheap model checks 'does this post assert X?'; distinct authors among matches).
Each method answers from its own material at the same token budget (ledger theme view,
map-reduce summary, retrieval top-k), with the material held as a cached system prompt.

Usage: python -m real_eval.prevalence_test results/bsky_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from celedger.cli import census
from real_eval import summary_baseline as sb
from sim.baseline import BM25

NUM = {"type": "object", "additionalProperties": False, "required": ["authors", "reasoning"],
       "properties": {"authors": {"type": "number"}, "reasoning": {"type": "string"}}}
CLAIMS = {"type": "object", "additionalProperties": False, "required": ["claims"],
          "properties": {"claims": {"type": "array", "items": {"type": "string"}}}}


def build_summary(L, texts, topic, budget_chars):
    ids = sorted(texts)

    def mapper(chunk):
        out, _ = llm.complete("claude-haiku-5-5", "You summarise social-media posts. Output JSON only.",
                              f"TOPIC: {topic}\nSummarise the distinct points these {len(chunk)} posts make, noting roughly "
                              "how many posts make each point and which side they take. Under 500 words.\n\n" +
                              "\n".join(f"- {texts[i]}" for i in chunk), sb.TEXT)
        return out["summary"]
    with ThreadPoolExecutor(8) as ex:
        maps = list(ex.map(mapper, [ids[i:i + 50] for i in range(0, len(ids), 50)]))
    groups = [maps[i:i + 6] for i in range(0, len(maps), 6)]
    per = budget_chars // len(groups)

    def reducer(g):
        out, _ = llm.complete("claude-sonnet-5-5", "You merge summaries. Output JSON only.",
                              f"TOPIC: {topic}\nMerge these {len(g)} batch summaries (each covers 50 posts) into one summary "
                              f"of about {per // 6} words (use the space). Keep every distinct point, with approximate "
                              "counts and sides; merge repeats.\n\n" + "\n\n".join(g), sb.TEXT, effort="medium")
        return out["summary"]
    with ThreadPoolExecutor(4) as ex:
        red = list(ex.map(reducer, groups))
    return "\n\n".join(f"[Part {k + 1}]\n{s}" for k, s in enumerate(red))[:budget_chars]


def main(d: Path):
    st = pickle.loads((d / "ledger_v3.pkl").read_bytes())
    L, texts, topic = st["ledger"], st["texts"], st["topic"]
    n = len(texts)
    view, _ = L.render_multires(32000)
    budget_chars = 4 * L.est_tokens(view)
    summary = build_summary(L, texts, topic, budget_chars)
    ids = sorted(texts)
    bm = BM25([texts[i].lower().split() for i in ids])
    sel, used = [], 0
    for i in bm.top(f"what do people say about {topic}".split(), n):
        t = L.est_tokens(texts[i]) + 2
        if used + t > L.est_tokens(view):
            break
        sel.append(i); used += t
    rag = "\n".join(f"- {texts[i]}" for i in sel)

    ranked = sorted((e for e in L.entries.values() if e.eid != 0), key=lambda e: -len(e.author_stance))
    claims = [("ledger", ranked[r].text) for r in (1, 4, 9, 19) if r < len(ranked)]
    out, _ = llm.complete("claude-sonnet-5-5", "You extract claims. Output JSON only.",
                          "From this summary, list 4 distinct, specific claims that posters make (a sentence each): one "
                          "very prominent, one fairly common, two less common. Do not list meta-observations.\n\n" + summary,
                          CLAIMS)
    claims += [("summary", c) for c in out["claims"][:4]]

    materials = {"ledger (theme view)": "THE COMPLETE LEDGER OF THE CORPUS:\n" + view,
                 "map-reduce summary": "A SUMMARY OF THE WHOLE CORPUS:\n" + summary,
                 "retrieval top-k, same budget": "RETRIEVED POSTS:\n" + rag}
    rows = []
    for src, claim in claims:
        scope, hits = census(L, texts, f"The author of this post asserts or endorses this claim (in substance): '{claim}'")
        gold = len({L.docs[h].author for h in hits})
        row = {"claim": claim, "source": src, "gold_authors": gold, "gold_posts": len(hits), "answers": {}}
        for name, mat in materials.items():
            ans, _ = llm.complete("claude-opus-5-5",
                                  f"You estimate corpus statistics for a corpus of {n} posts on {topic}, using ONLY the "
                                  "material below. Output JSON only.\n\n" + mat,
                                  f"How many DISTINCT AUTHORS in the whole corpus assert this claim (in substance)? "
                                  f"Claim: '{claim}'. Give your best numeric estimate.", NUM, effort="medium")
            row["answers"][name] = ans["authors"]
        rows.append(row)
        print(f"[{src}] gold {gold} | " + " | ".join(f"{k} {v:.0f}" for k, v in row["answers"].items()) + f" | {claim[:80]}",
              flush=True)
    summ = {}
    for name in materials:
        err = [abs(r["answers"][name] - r["gold_authors"]) / max(1, r["gold_authors"]) for r in rows]
        lg = [abs(np.log((r["answers"][name] + 1) / (r["gold_authors"] + 1))) for r in rows]
        summ[name] = {"median_rel_error": float(np.median(err)), "within_50pct": float(np.mean([e <= 0.5 for e in err])),
                      "mean_abs_log_ratio": float(np.mean(lg))}
    res = {"rows": rows, "summary": summ, "usd": llm.SPEND["usd"]}
    (d / "prevalence_test.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
