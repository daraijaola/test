"""Round 5: absorb a real, uncurated X-like corpus (every searchable public Bluesky post
on one niche topic) with the v2 absorber, keeping real authors/times/reach.

Usage: python -m real_eval.bsky POSTS_JSON OUT_DIR --topic "seed oils"
Writes OUT_DIR/ledger.pkl, ledger_flat.txt, ledger_multires.txt, ingest.json
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from celedger import llm
from celedger.ledger import DocMeta, Ledger
from real_eval import semeval

THEME_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["themes"],
                "properties": {"themes": {"type": "array", "items": {"type": "string"}}}}
ASSIGN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["entries"],
                 "properties": {"entries": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["id", "theme"],
                     "properties": {"id": {"type": "integer"}, "theme": {"type": "string"}}}}}}


def to_t(created: str, t0: float, t1: float) -> float:
    try:
        x = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.5
    return min(1.0, max(0.0, (x - t0) / max(1.0, t1 - t0)))


def assign_themes(L: Ledger, topic: str, log: list) -> list[str]:
    top = sorted(L.entries.values(), key=lambda e: -len(e.author_stance))[:600]
    out, usd = llm.complete(semeval.CONSOLIDATOR, "You organise a claim ledger. Output JSON only.",
                            f"TOPIC: {topic}\nPropose 8-15 short theme names that together cover these assertions "
                            "(the ledger's sections). Include a catch-all 'other'.\n\n" +
                            "\n".join(f"e{e.eid}: {e.text}" for e in top), THEME_SCHEMA)
    log.append(("themes", usd))
    themes = out["themes"]
    lines = L.index_lines()
    for s in range(0, len(lines), 300):
        out, usd = llm.complete(semeval.CONSOLIDATOR, "You organise a claim ledger. Output JSON only.",
                                "THEMES: " + " | ".join(themes) + "\nAssign every entry id to exactly one theme "
                                "(use the theme names verbatim).\n\n" + "\n".join(lines[s:s + 300]), ASSIGN_SCHEMA)
        log.append(("themes", usd))
        for r in out["entries"]:
            if r["id"] in L.entries:
                L.entries[r["id"]].theme = r["theme"] if r["theme"] in themes else "other"
    for e in L.entries.values():
        if e.theme is None:
            e.theme = "other"
    return themes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("posts", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--anchor", required=True, help="unambiguous statement whose support/dispute = subject stance")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--epoch-batches", type=int, default=5)
    ap.add_argument("--lanes", type=int, default=1, help="batches absorbed concurrently within an epoch")
    ap.add_argument("--version", default="v2", choices=["v2", "v4"])
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    semeval.CFG["version"] = a.version
    posts = json.loads(a.posts.read_text())
    ts = [datetime.fromisoformat(p["created"].replace("Z", "+00:00")).timestamp() for p in posts if p["created"]]
    t0, t1 = min(ts), max(ts)
    metas = {p["id"]: DocMeta(p["id"], p["author"], to_t(p["created"], t0, t1),
                              math.log1p(p["likes"] + p["reposts"])) for p in posts}
    texts = {p["id"]: p["text"].replace("\n", " ")[:600] for p in posts}
    n = len(posts)
    log, growth = [], []
    stats = {"hallucinated_ids": 0, "missing_docs": 0}
    start = time.time()
    L = Ledger()
    L.new_entry(semeval.ANCHOR_STATEMENT_TEXT.format(statement=a.anchor))
    L.epoch += 1
    frozen = "\n".join(L.index_lines())
    ids = [p["id"] for p in posts]                       # chronological
    lock = threading.Lock()
    batches = [ids[s:s + a.batch] for s in range(0, n, a.batch)]
    for ep in range(0, len(batches), a.epoch_batches):
        group = batches[ep:ep + a.epoch_batches]

        def run(chunk, frozen=frozen):
            return semeval.absorb_batch(L, a.topic, frozen, [(i, texts[i]) for i in chunk], log, n, metas, lock)
        with ThreadPoolExecutor(max(1, a.lanes)) as ex:
            for r in ex.map(run, group):
                for k in stats:
                    stats[k] += r[k]
        done = min((ep + len(group)) * a.batch, n)
        growth.append((done, len(L.entries)))
        semeval.consolidate(L, a.topic, semeval.ABSORBER, True, log)
        frozen = "\n".join(L.index_lines())
        print(f"{done}/{n} docs, {len(L.entries)} entries, ${sum(u for _, u in log):.2f}, "
              f"{time.time() - start:.0f}s", flush=True)
    semeval.consolidate(L, a.topic, semeval.ABSORBER, True, log)
    pre_global = len(L.entries)
    semeval.consolidate(L, a.topic, semeval.CONSOLIDATOR, False, log)
    res_before = L.residual_mass
    semeval.reabsorb_residual(L, a.topic, texts, log)
    pol = semeval.label_polarity(L, a.topic, log)
    pol[0] = "favor"
    themes = assign_themes(L, a.topic, log)
    L.check_conservation()
    flat, _ = L.render(32000)
    multi, _ = L.render_multires(32000)
    (a.out / "ledger_flat.txt").write_text(flat)
    (a.out / "ledger_multires.txt").write_text(multi)
    with open(a.out / "ledger.pkl", "wb") as fh:
        pickle.dump({"ledger": L, "polarity": pol, "texts": texts, "topic": a.topic, "themes": themes}, fh)
    info = {"n": n, "authors": len({m.author for m in metas.values()}), "entries": len(L.entries),
            "entries_before_global_merge": pre_global, "themes": themes,
            "residual_pct_before": 100 * res_before / n, "residual_pct": 100 * L.residual_mass / n,
            "noise_pct": 100 * L.noise_mass / n, **stats,
            "anchor": {s_: v for s_, v in L.entries[0].authors_by_stance().items()} if 0 in L.entries else None,
            "growth": growth, "usd": sum(u for _, u in log),
            "usd_by_stage": {k: sum(u for kk, u in log if kk == k) for k in {kk for kk, _ in log}},
            "render_tokens": {"flat": L.est_tokens(flat), "multires": L.est_tokens(multi)},
            "corpus_tokens_est": sum(len(t) for t in texts.values()) // 4, "seconds": time.time() - start}
    (a.out / "ingest.json").write_text(json.dumps(info, indent=1))
    print(json.dumps({k: v for k, v in info.items() if k != "growth"}, indent=1))


if __name__ == "__main__":
    main()
