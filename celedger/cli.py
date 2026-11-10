"""Command-line tool: absorb a whole topic, ask questions of it, keep it up to date.

  python -m celedger.cli ingest posts.jsonl --topic "seed oils" \\
        --anchor "Seed oils are safe and healthy to eat." --out ledgers/seedoils
  python -m celedger.cli ask    ledgers/seedoils "What do skeptics argue, and how many make each argument?"
  python -m celedger.cli update ledgers/seedoils new_posts.jsonl
  python -m celedger.cli census ledgers/seedoils "the post mentions beef tallow"
  python -m celedger.cli view   ledgers/seedoils [--budget 32000] [--flat]

posts.jsonl: one JSON object per line with "text" (required) and optionally "author",
"created" (ISO-8601), "likes", "reposts". An X/Twitter export maps onto this directly.
`ask` gives the reader the whole ledger as a cached prompt; the reader decides whether it
needs a census (an exhaustive check of every post in scope) and gets the exact result
before answering.

Model calls go through celedger.llm (the `claude` CLI).
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import time
from datetime import datetime
from pathlib import Path

from celedger import llm
from celedger.ledger import DocMeta, Ledger

READER = "claude-opus-5-5"
CHECKER = "claude-haiku-5-5"
ASK_SCHEMA = {"type": "object", "additionalProperties": False,
              "required": ["answer", "needs_census", "predicate", "scope_all", "scope_entries"],
              "properties": {"answer": {"type": "string"}, "needs_census": {"type": "boolean"},
                             "predicate": {"type": "string"}, "scope_all": {"type": "boolean"},
                             "scope_entries": {"type": "array", "items": {"type": "integer"}}}}
FINAL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
                "properties": {"answer": {"type": "string"}}}
CHECK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["docs"],
                "properties": {"docs": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["doc_id", "yes"],
                    "properties": {"doc_id": {"type": "integer"}, "yes": {"type": "boolean"}}}}}}
READER_SYS = (
    "You answer questions about a topic using its COMPLETE LEDGER: every post on the topic was absorbed into it, "
    "with exact counts of people and posts per assertion. Use the counts. Say what the ledger cannot tell you. "
    "If the question needs an exact number the ledger does not hold (e.g. how many posts mention a word, or a "
    "property no entry records), set needs_census=true and write a yes/no predicate to be checked on EVERY post "
    "in scope (scope_all=true unless specific entries' posts surely suffice); your answer will then be revised "
    "with the exact result. Keep answers under 200 words.")


# ------------------------------------------------------------------ storage
def load(d: Path) -> dict:
    return pickle.loads((d / "ledger.pkl").read_bytes())


def save(d: Path, st: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "ledger.pkl").write_bytes(pickle.dumps(st))
    (d / "view.txt").write_text(st["ledger"].render_multires(32000, compact=True)[0])


def read_posts(path: Path, start_id: int = 0) -> list[dict]:
    rows = []
    for k, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        p = json.loads(line)
        rows.append({"id": start_id + len(rows), "text": str(p["text"]).replace("\n", " ")[:600],
                     "author": str(p.get("author") or f"anon{start_id + k}"), "created": p.get("created") or "",
                     "likes": int(p.get("likes") or 0), "reposts": int(p.get("reposts") or 0)})
    rows.sort(key=lambda p: p["created"])
    return rows


def _ts(created: str) -> float | None:
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _metas(posts: list[dict], abs_t: dict) -> dict:
    """Normalised times over the whole (old + new) window; posts without a time get the median."""
    for p in posts:
        abs_t[p["id"]] = _ts(p["created"])
    known = sorted(v for v in abs_t.values() if v is not None)
    t0, t1 = (known[0], known[-1]) if known else (0.0, 1.0)
    mid = known[len(known) // 2] if known else 0.5
    return {i: (((v if v is not None else mid) - t0) / max(1.0, t1 - t0)) for i, v in abs_t.items()}


# ------------------------------------------------------------------ commands
def _cost_controls(a):
    from real_eval import semeval
    semeval.INDEX_CAP["entries"] = a.index_cap or None


def cmd_ingest(a):
    from real_eval import bsky, semeval
    from real_eval.anchor_pass import run_anchor
    semeval.CFG["version"] = "v2"
    _cost_controls(a)
    posts = read_posts(a.posts)
    abs_t: dict = {}
    tnorm = _metas(posts, abs_t)
    metas = {p["id"]: DocMeta(p["id"], p["author"], tnorm[p["id"]], math.log1p(p["likes"] + p["reposts"]))
             for p in posts}
    texts = {p["id"]: p["text"] for p in posts}
    L = Ledger()
    L.new_entry(semeval.ANCHOR_STATEMENT_TEXT.format(statement=a.anchor))
    L.epoch += 1
    log, stats, growth = [], {"hallucinated_ids": 0, "missing_docs": 0}, []
    bsky.absorb_stream(L, a.topic, [p["id"] for p in posts], texts, metas, log, stats, growth, lanes=a.lanes,
                       warm=a.warm)
    pol, themes = bsky.finish(L, a.topic, texts, log)
    usd = sum(u for _, u in log) + run_anchor(L, texts, sorted(texts))
    save(a.out, {"ledger": L, "polarity": pol, "texts": texts, "topic": a.topic, "themes": themes,
                 "abs_t": abs_t, "anchor": a.anchor})
    print(f"ingested {len(posts)} posts -> {len(L.entries)} entries; residual "
          f"{100 * L.residual_mass / len(posts):.1f}%; ${usd:.2f}; view: {a.out / 'view.txt'}")


def cmd_update(a):
    """Absorb new posts into an existing ledger. Earlier posts keep their ops; time bins of every
    entry are rebuilt exactly from provenance on the widened time window."""
    from real_eval import bsky, semeval
    from real_eval.anchor_pass import run_anchor
    semeval.CFG["version"] = "v2"
    _cost_controls(a)
    st = load(a.dir)
    L, texts = st["ledger"], st["texts"]
    # skip only true re-submissions (same author, same text); identical text from different
    # people (shared links, headlines) is evidence and must be counted
    seen = {(L.docs[i].author, " ".join(t.split())) for i, t in texts.items() if i in L.docs}
    new = [p for p in read_posts(a.posts, start_id=max(texts) + 1)
           if (p["author"], " ".join(p["text"].split())) not in seen]
    for k, p in enumerate(new):
        p["id"] = max(texts) + 1 + k
    if not new:
        print("no new posts")
        return
    abs_t = st.setdefault("abs_t", {i: None for i in texts})
    tnorm = _metas(new, abs_t)
    for i, m in list(L.docs.items()):                     # re-normalise old posts on the wider window
        L.docs[i] = DocMeta(i, m.author, tnorm.get(i, m.t), m.reach)
    metas = {p["id"]: DocMeta(p["id"], p["author"], tnorm[p["id"]], math.log1p(p["likes"] + p["reposts"]))
             for p in new}
    texts.update({p["id"]: p["text"] for p in new})
    before = len(L.entries)
    L.epoch += 1
    log, stats, growth = [], {"hallucinated_ids": 0, "missing_docs": 0}, []
    bsky.absorb_stream(L, st["topic"], [p["id"] for p in new], texts, metas, log, stats, growth, lanes=a.lanes,
                       warm=a.warm)
    semeval.consolidate(L, st["topic"], semeval.ABSORBER, True, log)
    semeval.reabsorb_residual(L, st["topic"], texts, log)
    usd = sum(u for _, u in log) + run_anchor(L, texts, [p["id"] for p in new])
    fresh = [e for e in L.entries.values() if e.theme is None]
    for e in fresh:
        e.theme = "new since last update"
    if fresh:
        lines = [f"e{e.eid}: {e.text}" for e in fresh]
        out, u = llm.complete("claude-sonnet-5-5", "You label statements. Output JSON only.",
                              f"TARGET statement: {st.get('anchor', st['topic'])}\nFor each statement: if a person "
                              "asserts it, do they agree (favor), disagree (against) with the target, or neither "
                              "(neutral)?\n\n" + "\n".join(lines), semeval.POLARITY_SCHEMA)
        st["polarity"].update({r["id"]: r["polarity"] for r in out["entries"]})
        usd += u
    for eid in list(L.entries):                           # exact rebuild of tallies/time bins from provenance
        L.recompute(eid)
    L.check_conservation()
    save(a.dir, st)
    print(f"absorbed {len(new)} new posts: {len(L.entries) - before:+d} entries "
          f"({len(fresh)} new, the rest merged/assigned); total {len(L.docs)} posts; ${usd:.2f}")


def census(L: Ledger, texts: dict, predicate: str, scope_all: bool = True, scope_entries=()) -> tuple[list, list]:
    from concurrent.futures import ThreadPoolExecutor
    if scope_all or not scope_entries:
        scope = sorted(L.docs)
    else:
        scope = sorted({d for e in scope_entries if L.resolve(e) in L.entries for d in L.postings(L.resolve(e))})

    def one(chunk):
        out, _ = llm.complete(CHECKER, "You check a predicate on each document. Output JSON only.",
                              f"PREDICATE: {predicate}\nFor each document answer yes if the predicate holds.\n\n" +
                              "\n".join(f"<doc id={i}>{texts[i]}</doc>" for i in chunk), CHECK_SCHEMA)
        yes = {d["doc_id"] for d in out["docs"] if d["yes"]}
        return [i for i in chunk if i in yes]
    with ThreadPoolExecutor(8) as ex:
        hits = [h for hs in ex.map(one, [scope[i:i + 60] for i in range(0, len(scope), 60)]) for h in hs]
    return scope, hits


def census_summary(L: Ledger, scope, hits, predicate) -> str:
    authors = {L.docs[d].author for d in hits}
    an = L.entries[0].author_stance if 0 in L.entries else {}
    pro = sum(1 for x in authors if an.get(x) == "support")
    con = sum(1 for x in authors if an.get(x) == "dispute")
    return (f"CENSUS (exhaustive check of {len(scope)} posts for: '{predicate}'): {len(hits)} matching posts by "
            f"{len(authors)} distinct authors; of those authors, {pro} agree and {con} disagree with the anchor.")


def cmd_census(a):
    st = load(a.dir)
    scope, hits = census(st["ledger"], st["texts"], a.predicate, not a.entries,
                         [int(x) for x in a.entries.split(",")] if a.entries else ())
    print(census_summary(st["ledger"], scope, hits, a.predicate))


def cmd_ask(a):
    st = load(a.dir)
    L, texts = st["ledger"], st["texts"]
    view, _ = L.render_multires(a.budget, compact=True)
    system = READER_SYS + "\n\nTHE COMPLETE LEDGER:\n" + view
    k0 = len(llm.CALLS)
    out, _ = llm.complete(READER, system, a.question, ASK_SCHEMA, effort="medium")
    if out["needs_census"] and out["predicate"]:
        scope, hits = census(L, texts, out["predicate"], out["scope_all"], out["scope_entries"])
        summary = census_summary(L, scope, hits, out["predicate"])
        print(f"[{summary}]\n")
        out, _ = llm.complete(READER, system, f"{a.question}\n\nYour first answer was:\n{out['answer']}\n\n{summary}\n"
                              "Revise the answer using the exact census result.", FINAL_SCHEMA, effort="medium")
    print(out["answer"])
    print(f"\n(cost ${sum(c['usd'] for c in llm.CALLS[k0:]):.3f}, {len(llm.CALLS) - k0} model calls)")


def cmd_view(a):
    L = load(a.dir)["ledger"]
    print((L.render(a.budget) if a.flat else L.render_multires(a.budget, compact=True))[0])


def main():
    ap = argparse.ArgumentParser(prog="celedger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("posts", type=Path); p.add_argument("--topic", required=True)
    p.add_argument("--anchor", required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lanes", type=int, default=8)
    p.add_argument("--index-cap", type=int, default=0,
                   help="above ~10k posts: cap the absorber's index (e.g. 2000) to stay under the long-context price "
                        "tier; ~3x cheaper at 27k posts, but more misfilings (4%% -> 10%% measured)")
    p.add_argument("--warm", action="store_true", help="warm the prompt cache once per epoch before fanning out lanes")
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("update"); p.add_argument("dir", type=Path); p.add_argument("posts", type=Path)
    p.add_argument("--lanes", type=int, default=8)
    p.add_argument("--index-cap", type=int, default=0, help="see ingest --index-cap")
    p.add_argument("--warm", action="store_true", help="see ingest --warm")
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("ask"); p.add_argument("dir", type=Path); p.add_argument("question")
    p.add_argument("--budget", type=int, default=32000); p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("census"); p.add_argument("dir", type=Path); p.add_argument("predicate")
    p.add_argument("--entries", default=""); p.set_defaults(fn=cmd_census)
    p = sub.add_parser("view"); p.add_argument("dir", type=Path); p.add_argument("--budget", type=int, default=32000)
    p.add_argument("--flat", action="store_true"); p.set_defaults(fn=cmd_view)
    a = ap.parse_args()
    t = time.time()
    a.fn(a)
    print(f"({time.time() - t:.0f}s)")


if __name__ == "__main__":
    main()
