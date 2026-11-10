"""Round 5 evaluation on the real Bluesky ledger (no gold labels exist, so we measure
directly, with an independent judge model that did not build the ledger):

1. Absorber audit (real error rate): for 100 random posts, a judge grades the ops.
2. Coverage: for random posts that make a point, is that point present in what the
   reading model receives? Contexts compared at equal reading budgets:
     ledger (theme view, ~32k tokens) | RAG top-20 | RAG top-100 |
     RAG top-k with the same token budget as the ledger | uniform random sample, same budget
3. Counting questions (gold = text match) answered from the ledger, ledger+census, RAG.

Usage: python -m real_eval.bsky_eval results/bsky_seedoils
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

JUDGE = "claude-sonnet-5-5"
READER = "claude-opus-5-5"
CHECKER = "claude-haiku-5-5"

AUDIT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["posts"],
                "properties": {"posts": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["post_id", "verdict", "anchor_ok", "note"],
                    "properties": {"post_id": {"type": "integer"},
                                   "verdict": {"type": "string", "enum": ["correct", "minor_issue", "wrong"]},
                                   "anchor_ok": {"type": "string", "enum": ["yes", "no", "na"]},
                                   "note": {"type": "string"}}}}}}
POINT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["posts"],
                "properties": {"posts": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["post_id", "point"],
                    "properties": {"post_id": {"type": "integer"}, "point": {"type": ["string", "null"]}}}}}}
COVER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["posts"],
                "properties": {"posts": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["post_id", "covered"],
                    "properties": {"post_id": {"type": "integer"},
                                   "covered": {"type": "string", "enum": ["yes", "partly", "no"]}}}}}}
ANSWER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["count", "authors", "reasoning"],
                 "properties": {"count": {"type": "number"}, "authors": {"type": "number"},
                                "reasoning": {"type": "string"}}}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["predicate", "scope_all", "scope_entries"],
               "properties": {"predicate": {"type": "string"}, "scope_all": {"type": "boolean"},
                              "scope_entries": {"type": "array", "items": {"type": "integer"}}}}
CHECK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["docs"],
                "properties": {"docs": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["doc_id", "yes"],
                    "properties": {"doc_id": {"type": "integer"}, "yes": {"type": "boolean"}}}}}}
CANDIDATES = ["canola", "tallow", "rfk", "maha", "omega", "inflammation", "cancer", "butter", "olive",
              "kennedy", "heart", "fries", "mcdonald", "linoleic", "processed", "steak", "lard", "fda", "trump",
              "avocado", "coconut", "keto", "obesity", "diabetes"]


def pmap(fn, xs, workers=6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, xs))


def ops_desc(L, d):
    out = []
    for eid, b, w in L.log[d]:
        if eid is None:
            out.append(b)
        else:
            e = L.entries[L.resolve(eid)]
            out.append(f"{b} -> '{e.text}'")
    return "; ".join(out)


def audit(L, texts, sample, topic):
    anchor = L.entries[0].text.replace("ANCHOR: ", "") if 0 in L.entries else "(none)"

    def one(chunk):
        user = (f"Each post below was filed into a ledger of assertions about {topic}. Grade the filing.\n"
                "correct = every op fits (right entry meaning, right support/dispute/mention); minor_issue = "
                "roughly right but imprecise; wrong = misfiled, wrong stance, or a contentful post called "
                f"noise/residual. anchor_ok: is the support/dispute on the ANCHOR entry (statement: '{anchor}') "
                "right, or na if there is no anchor op and none was needed (answer 'no' if one was needed but missing).\n\n" +
                "\n\n".join(f"<post id={d}>{texts[d]}</post>\nOPS: {ops_desc(L, d)}" for d in chunk))
        out, _ = llm.complete(JUDGE, "You audit data labelling. Output JSON only.", user, AUDIT_SCHEMA, effort="medium")
        return out["posts"]
    rows = [r for rs in pmap(one, [sample[i:i + 20] for i in range(0, len(sample), 20)]) for r in rs]
    v = Counter(r["verdict"] for r in rows)
    a = Counter(r["anchor_ok"] for r in rows)
    return {"n": len(rows), "verdicts": dict(v), "anchor": dict(a),
            "error_rate_strict": v["wrong"] / max(1, len(rows)),
            "error_rate_incl_minor": (v["wrong"] + v["minor_issue"]) / max(1, len(rows)),
            "wrong_notes": [r["note"] for r in rows if r["verdict"] == "wrong"][:15]}


def points(texts, sample, topic):
    def one(chunk):
        user = (f"For each post, state in one short sentence the main point it makes about {topic} (or about "
                "people/policies related to them). Use null if it makes no point at all.\n\n" +
                "\n".join(f"<post id={d}>{texts[d]}</post>" for d in chunk))
        out, _ = llm.complete(JUDGE, "You summarise posts. Output JSON only.", user, POINT_SCHEMA)
        return out["posts"]
    rows = [r for rs in pmap(one, [sample[i:i + 25] for i in range(0, len(sample), 25)]) for r in rs]
    return {r["post_id"]: r["point"] for r in rows if r["point"]}


def coverage(context_name, context, pts, judge=None):
    ids = sorted(pts)

    def one(chunk):
        user = (f"MATERIAL ({context_name}):\n{context}\n\n"
                "For each POINT below: does the MATERIAL above contain this point (the same claim or opinion, from "
                "any author, in any wording)? yes = clearly present, partly = a broader or related version is present, "
                "no = absent.\n\n" + "\n".join(f"<point id={d}>{pts[d]}</point>" for d in chunk))
        out, _ = llm.complete(judge or JUDGE, "You check whether information is present. Output JSON only.", user,
                              COVER_SCHEMA)
        return out["posts"]
    rows = [r for rs in pmap(one, [ids[i:i + 25] for i in range(0, len(ids), 25)], workers=4) for r in rs]
    c = Counter(r["covered"] for r in rows)
    n = max(1, len(rows))
    return {"n": len(rows), "yes": c["yes"] / n, "partly": c["partly"] / n, "no": c["no"] / n,
            "score": (c["yes"] + 0.5 * c["partly"]) / n}


def mentions(x, ent):
    return re.search(rf"(?<![a-z0-9]){re.escape(ent)}", x.lower()) is not None


def census(L, texts, plan):
    if plan["scope_all"] or not plan["scope_entries"]:
        scope = sorted(L.docs)
    else:
        scope = sorted({d for e in plan["scope_entries"] if L.resolve(e) in L.entries for d in L.postings(L.resolve(e))})

    def one(chunk):
        user = (f"PREDICATE: {plan['predicate']}\nFor each document answer yes if the predicate holds, else no.\n\n"
                + "\n".join(f"<doc id={i}>{texts[i]}</doc>" for i in chunk))
        out, _ = llm.complete(CHECKER, "You check a predicate on each document. Output JSON only.", user, CHECK_SCHEMA)
        yes = {d["doc_id"] for d in out["docs"] if d["yes"]}
        return [i for i in chunk if i in yes]
    hits = [h for hs in pmap(one, [scope[i:i + 60] for i in range(0, len(scope), 60)], workers=8) for h in hs]
    return scope, hits


def qa(L, texts, render, bm, n, ents, topic):
    rows = []
    for ent in ents:
        gold_ids = [d for d in texts if mentions(texts[d], ent)]
        gold = {"count": len(gold_ids), "authors": len({L.docs[d].author for d in gold_ids})}
        q = (f"Across all {n} posts about {topic}: how many posts mention '{ent}' (as a word, prefix or hashtag), "
             f"and how many distinct authors wrote them?")
        ans, cost = {}, {}
        before = llm.SPEND["usd"]
        out, u = llm.complete(READER, "You answer corpus-level questions. Output JSON only.",
                              "THE COMPLETE LEDGER OF THIS CORPUS:\n" + render + "\n\nQUESTION: " + q, ANSWER_SCHEMA, effort="medium")
        ans["ledger"], cost["ledger"] = out, u
        plan, u1 = llm.complete(READER, "You plan an exhaustive census over a corpus. Output JSON only.",
                                "THE COMPLETE LEDGER OF THIS CORPUS:\n" + render + "\n\nQUESTION: " + q +
                                "\nWrite a yes/no PREDICATE a cheap model will check on every document in scope; choose "
                                "scope_all=true unless you are sure specific entries' posting lists cover every relevant "
                                "document.", PLAN_SCHEMA, effort="medium")
        c0 = llm.SPEND["usd"]
        scope, hits = census(L, texts, plan)
        c_census = llm.SPEND["usd"] - c0
        out, u2 = llm.complete(READER, "You answer corpus-level questions. Output JSON only.",
                               f"CENSUS RESULT: an exhaustive check of {len(scope)} posts for '{plan['predicate']}' found "
                               f"{len(hits)} matching posts by {len({L.docs[d].author for d in hits})} distinct authors."
                               "\n\nQUESTION: " + q, ANSWER_SCHEMA, effort="low")
        ans["ledger+census"], cost["ledger+census"] = out, u1 + c_census + u2
        for k in (20, 100):
            top = bm.top((ent + " " + topic).lower().split(), k)
            out, u = llm.complete(READER, "You answer corpus-level questions. Output JSON only.",
                                  f"RETRIEVED POSTS (top {k} of {n}):\n" + "\n".join(f"- {texts[d]}" for d in top) +
                                  "\n\nQUESTION: " + q, ANSWER_SCHEMA, effort="medium")
            ans[f"rag{k}"], cost[f"rag{k}"] = out, u
        rows.append({"entity": ent, "gold": gold, "plan": plan, "census_scope": len(scope), "census_hits": len(hits),
                     "census_precision": len(set(hits) & set(gold_ids)) / max(1, len(hits)),
                     "census_recall": len(set(hits) & set(gold_ids)) / max(1, len(gold_ids)),
                     "answers": {m: {"count": a["count"], "authors": a["authors"]} for m, a in ans.items()},
                     "cost": cost})
        print(f"  {ent}: gold {gold} | " + " | ".join(f"{m} {a['count']:.0f}/{a['authors']:.0f}" for m, a in ans.items()),
              flush=True)
    return rows


def main(d: Path, do_qa: bool = True):
    st = pickle.loads((d / "ledger.pkl").read_bytes())
    L, texts = st["ledger"], st["texts"]
    n = len(texts)
    rng = np.random.default_rng(42)
    res = {}
    render, _ = L.render_multires(32000)
    rtok = L.est_tokens(render)
    ids = sorted(texts)
    bm = BM25([texts[i].lower().split() for i in ids])

    sample = sorted(rng.choice(ids, size=min(100, len(ids)), replace=False).tolist())
    topic = st["topic"]
    res["audit"] = audit(L, texts, sample, topic)
    print("audit", {k: v for k, v in res["audit"].items() if k != "wrong_notes"}, flush=True)

    cov_sample = sorted(rng.choice(ids, size=min(150, len(ids)), replace=False).tolist())
    pts = points(texts, cov_sample, topic)
    res["points_n"] = len(pts)
    q = f"what do people say about {st['topic']}".split()

    def raw(sel):
        return "\n".join(f"- {texts[i]}" for i in sel)

    def fill(order):
        sel, used = [], 0
        for i in order:
            t = L.est_tokens(texts[i]) + 2
            if used + t > rtok:
                break
            sel.append(i); used += t
        return sel
    contexts = {"ledger (theme view)": render,
                "RAG top-20": raw(bm.top(q, 20)), "RAG top-100": raw(bm.top(q, 100)),
                "RAG top-k, same tokens as ledger": raw(fill(bm.top(q, n))),
                "random sample, same tokens as ledger": raw(fill(rng.permutation(ids).tolist()))}
    res["coverage"] = {}
    for name, ctx in contexts.items():
        res["coverage"][name] = {**coverage(name, ctx, pts), "context_tokens": L.est_tokens(ctx)}
        print("coverage", name, res["coverage"][name], flush=True)

    df = {c: sum(mentions(t, c) for t in texts.values()) for c in CANDIDATES}
    ents = [c for c, k in sorted(df.items(), key=lambda x: -x[1]) if max(3, n // 400) <= k <= 600][:8]
    res["qa"] = qa(L, texts, render, bm, n, ents, topic) if do_qa else []
    res["spend_usd"] = llm.SPEND["usd"]
    (d / "eval.json").write_text(json.dumps(res, indent=1))
    res["topic"] = topic
    write_md(d, res, n, rtok)


def write_md(d, res, n, rtok):
    a = res["audit"]
    md = [f"# Real X-like corpus: every public Bluesky post on '{res.get('topic', '?')}' ({n:,} posts)\n",
          "## 1. Absorber audit (independent judge, 100 random posts)\n",
          f"Verdicts: {a['verdicts']}. Strict error rate (wrong): **{100 * a['error_rate_strict']:.0f}%**; "
          f"including minor issues: {100 * a['error_rate_incl_minor']:.0f}%. Anchor op: {a['anchor']}.\n",
          "Judge notes on wrong filings (sample):\n"] + [f"- {x}" for x in a["wrong_notes"][:8]]
    md += [f"\n## 2. Coverage: is a random post's point present in what the reader receives? ({res['points_n']} posts with a point)\n",
           "| reader input | tokens | yes | partly | no | score (yes + ½ partly) |", "|---|---|---|---|---|---|"]
    for name, c in res["coverage"].items():
        md.append(f"| {name} | {c['context_tokens']:,} | {100 * c['yes']:.0f}% | {100 * c['partly']:.0f}% | "
                  f"{100 * c['no']:.0f}% | **{100 * c['score']:.0f}%** |")
    rows = res["qa"]
    if not rows:
        md.append("\n(no counting questions: no candidate entity in the frequency range)")
        (d / "eval.md").write_text("\n".join(md) + "\n")
        print("\n".join(md))
        return
    md += ["\n## 3. Counting questions (gold: text match over all posts)\n",
           "| method | posts: median rel. error | posts: within 20% | authors: median rel. error | $ / question |",
           "|---|---|---|---|---|"]
    for m in rows[0]["answers"]:
        rc = [abs(r["answers"][m]["count"] - r["gold"]["count"]) / r["gold"]["count"] for r in rows]
        ra = [abs(r["answers"][m]["authors"] - r["gold"]["authors"]) / max(1, r["gold"]["authors"]) for r in rows]
        md.append(f"| {m} | {100 * np.median(rc):.0f}% | {100 * np.mean([x <= 0.2 for x in rc]):.0f}% | "
                  f"{100 * np.median(ra):.0f}% | ${np.mean([r['cost'][m] for r in rows]):.3f} |")
    md.append(f"\nCensus checker vs text match: precision {np.mean([r['census_precision'] for r in rows]):.2f}, "
              f"recall {np.mean([r['census_recall'] for r in rows]):.2f}.\n")
    md += ["| entity | gold posts / authors | " + " | ".join(rows[0]["answers"]) + " |", "|---|---|" + "---|" * len(rows[0]["answers"])]
    for r in rows:
        md.append(f"| {r['entity']} | {r['gold']['count']} / {r['gold']['authors']} | " +
                  " | ".join(f"{v['count']:.0f} / {v['authors']:.0f}" for v in r["answers"].values()) + " |")
    md.append(f"\nEvaluation spend: ${res['spend_usd']:.2f}")
    (d / "eval.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main(Path(sys.argv[1]), do_qa="--no-qa" not in sys.argv)
