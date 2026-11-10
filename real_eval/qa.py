"""Round 4: end-to-end questions with gold answers on the real SemEval ledgers.

For each target we pick entities that appear in 12-150 tweets (from hashtags) and ask:
  A. "How many of the N tweets mention <entity>?"            gold: text match
  B. "Of those, what percentage are against <target>?"        gold: SemEval labels
Methods (same reader model, Opus 5.5):
  ledger        reads the rendered ledger only
  ledger+census reads the ledger, writes a census plan (predicate + scope); a cheap model
                checks EVERY document in scope; the reader answers from the exact result
  rag20/rag100  BM25 top-k for the question, reader told the corpus size
Usage: python -m real_eval.qa results/real
"""
from __future__ import annotations

import json
import pickle
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from sim.baseline import BM25

READER = "claude-opus-5-5"
CHECKER = "claude-haiku-5-5"

ANSWER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["count", "against_pct", "reasoning"],
                 "properties": {"count": {"type": "number"}, "against_pct": {"type": "number"},
                                "reasoning": {"type": "string"}}}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["predicate", "scope_all", "scope_entries"],
               "properties": {"predicate": {"type": "string"}, "scope_all": {"type": "boolean"},
                              "scope_entries": {"type": "array", "items": {"type": "integer"}}}}
CHECK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["docs"],
                "properties": {"docs": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["doc_id", "yes"],
                    "properties": {"doc_id": {"type": "integer"}, "yes": {"type": "boolean"}}}}}}


def pick_entities(tweets, k=3):
    df = Counter()
    for x, _ in tweets:
        df.update({h.lower() for h in re.findall(r"#(\w+)", x)})
    cands = [(h, n) for h, n in df.most_common() if 12 <= n <= 150 and h != "semst"]
    return [h for h, _ in cands[:k]]


def mentions(x: str, ent: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(ent)}(?![a-z0-9])", x.lower()) is not None


def question(ent, topic, n):
    return (f"Across the corpus of {n} tweets about '{topic}': (A) how many tweets mention '{ent}' "
            f"(as a word or hashtag)? (B) of the tweets that mention it, what percentage are AGAINST '{topic}'?")


def ask(context, q, tag, log):
    out, usd = llm.complete(READER, "You answer corpus-level questions. Output JSON only.",
                            context + "\n\nQUESTION: " + q + "\nGive your best numeric estimates.", ANSWER_SCHEMA,
                            effort="medium")
    log.append((tag, usd))
    return out


def census(L, tweets, plan, log, batch=60):
    if plan["scope_all"] or not plan["scope_entries"]:
        scope = sorted(L.docs)
    else:
        scope = sorted({d for e in plan["scope_entries"] if L.resolve(e) in L.entries for d in L.postings(L.resolve(e))})
    hits = []
    for s in range(0, len(scope), batch):
        chunk = scope[s:s + batch]
        user = (f"PREDICATE: {plan['predicate']}\nFor each document answer yes if the predicate holds, else no.\n\n"
                + "\n".join(f"<doc id={i}>{tweets[i][0]}</doc>" for i in chunk))
        out, usd = llm.complete(CHECKER, "You check a predicate on each document. Output JSON only.", user, CHECK_SCHEMA)
        log.append(("census", usd))
        yes = {d["doc_id"] for d in out["docs"] if d["yes"]}
        hits += [i for i in chunk if i in yes]
    return scope, hits


def run_target(pkl: Path):
    st = pickle.loads(pkl.read_bytes())
    L, tweets, topic, pred = st["ledger"], st["tweets"], st["topic"], st["pred"]
    n = len(tweets)
    render, _ = L.render(32000)
    bm = BM25([x.lower().split() for x, _ in tweets])
    rows = []
    for ent in pick_entities(tweets):
        log = []
        gold_ids = [i for i, (x, _) in enumerate(tweets) if mentions(x, ent)]
        gold = {"count": len(gold_ids),
                "against_pct": 100 * sum(tweets[i][1] == "against" for i in gold_ids) / max(1, len(gold_ids))}
        q = question(ent, topic, n)
        ans = {"ledger": ask("THE COMPLETE LEDGER OF THIS CORPUS:\n" + render, q, "ledger", log)}
        plan, usd = llm.complete(READER, "You plan an exhaustive census over a corpus. Output JSON only.",
                                 "THE COMPLETE LEDGER OF THIS CORPUS:\n" + render + "\n\nQUESTION: " + q +
                                 "\nWrite a yes/no PREDICATE a cheap model will check on every document in scope, and "
                                 "choose the scope: all documents (scope_all=true) or the posting lists of specific "
                                 "entries (their ids). Choose all documents unless you are sure the entries cover every "
                                 "relevant document.", PLAN_SCHEMA, effort="medium")
        log.append(("plan", usd))
        scope, hits = census(L, tweets, plan, log)
        pstats = Counter(pred[i] for i in hits)
        ans["ledger+census"] = ask(
            "THE COMPLETE LEDGER OF THIS CORPUS:\n" + render +
            f"\n\nCENSUS RESULT (exhaustive check of {len(scope)} documents for predicate '{plan['predicate']}'): "
            f"{len(hits)} matching documents. Ledger stance toward the target among the matches: "
            f"favor {pstats['favor']}, against {pstats['against']}, none/unclear {pstats['none']}.", q, "ledger+census", log)
        for k in (20, 100):
            top = bm.top((ent + " " + topic).lower().split(), k)
            ans[f"rag{k}"] = ask(f"RETRIEVED TWEETS (top {k} matches out of {n}):\n" +
                                 "\n".join(f"- {tweets[i][0]}" for i in top), q, f"rag{k}", log)
        row = {"target": pkl.stem, "entity": ent, "gold": gold, "plan": plan, "census_scope": len(scope),
               "census_hits": len(hits), "census_precision": len(set(hits) & set(gold_ids)) / max(1, len(hits)),
               "census_recall": len(set(hits) & set(gold_ids)) / max(1, len(gold_ids)),
               "answers": {m: {"count": a["count"], "against_pct": a["against_pct"]} for m, a in ans.items()},
               "cost": {m: sum(u for t, u in log if t == m or (m == "ledger+census" and t in ("plan", "census"))) for m in ans}}
        rows.append(row)
        print(f"[{pkl.stem}] {ent}: gold {gold['count']}/{gold['against_pct']:.0f}% | " +
              " | ".join(f"{m} {a['count']:.0f}/{a['against_pct']:.0f}%" for m, a in ans.items()), flush=True)
    return rows


def main(d: Path):
    pkls = sorted(d.glob("ledger_*.pkl"))
    with ThreadPoolExecutor(len(pkls)) as ex:
        rows = [r for rs in ex.map(run_target, pkls) for r in rs]
    (d / "qa.json").write_text(json.dumps(rows, indent=1))
    methods = list(rows[0]["answers"])
    md = ["# End-to-end questions on real ledgers (SemEval-2016 stance tweets)\n",
          "A = how many tweets mention an entity (gold: text match); B = % of those against the target (gold: labels).\n",
          "| method | A: median relative error | A: within 20% | B: mean abs error (pts) | $ per question |", "|---|---|---|---|---|"]
    for m in methods:
        rel = [abs(r["answers"][m]["count"] - r["gold"]["count"]) / r["gold"]["count"] for r in rows]
        b = [abs(r["answers"][m]["against_pct"] - r["gold"]["against_pct"]) for r in rows]
        md.append(f"| {m} | {100 * np.median(rel):.0f}% | {100 * np.mean([x <= 0.2 for x in rel]):.0f}% | "
                  f"{np.mean(b):.1f} | ${np.mean([r['cost'][m] for r in rows]):.3f} |")
    md.append(f"\nCensus checker vs text-match gold: precision {np.mean([r['census_precision'] for r in rows]):.2f}, "
              f"recall {np.mean([r['census_recall'] for r in rows]):.2f}; reader chose scope=all in "
              f"{sum(r['plan']['scope_all'] for r in rows)}/{len(rows)} questions.\n")
    md.append("| target | entity | gold A/B | " + " | ".join(methods) + " |")
    md.append("|---|---|---|" + "---|" * len(methods))
    for r in rows:
        md.append(f"| {r['target']} | {r['entity']} | {r['gold']['count']} / {r['gold']['against_pct']:.0f}% | " +
                  " | ".join(f"{r['answers'][m]['count']:.0f} / {r['answers'][m]['against_pct']:.0f}%" for m in methods) + " |")
    (d / "qa.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(json.dumps({"spend": llm.SPEND}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
