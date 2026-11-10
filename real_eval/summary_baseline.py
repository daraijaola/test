"""Strongest obvious competitor: summarise everything (map-reduce), at the ledger's budget.

Map: the cheap model summarises every batch of 50 posts (distinct points, rough counts).
Reduce: the stronger model merges groups of batch summaries; the result is trimmed to the
same estimated token budget as the ledger's theme view. Then, on the same points and judge:
coverage (ledger vs summary), and the subject-level share question answered from each.

Usage: python -m real_eval.summary_baseline results/bsky_seedoils
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from celedger import llm
from real_eval.bsky_eval import coverage, points

TEXT = {"type": "object", "additionalProperties": False, "required": ["summary"],
        "properties": {"summary": {"type": "string"}}}
SHARE = {"type": "object", "additionalProperties": False, "required": ["agree_pct_among_positioned", "reasoning"],
         "properties": {"agree_pct_among_positioned": {"type": "number"}, "reasoning": {"type": "string"}}}


def main(d: Path, map_words: int = 250, group: int = 15, tag: str = ""):
    st = pickle.loads((d / "ledger_v3.pkl").read_bytes())
    L, texts, topic = st["ledger"], st["texts"], st["topic"]
    anchor = L.entries[0].text.replace("ANCHOR: ", "")
    ids = sorted(texts)
    view, _ = L.render_multires(32000)
    budget_chars = 4 * L.est_tokens(view)
    spend0 = llm.SPEND["usd"]

    def mapper(chunk):
        out, _ = llm.complete("claude-haiku-5-5", "You summarise social-media posts. Output JSON only.",
                              f"TOPIC: {topic}\nSummarise the distinct points these {len(chunk)} posts make, noting roughly "
                              f"how many posts make each point and which side they take. Under {map_words} words.\n\n" +
                              "\n".join(f"- {texts[i]}" for i in chunk), TEXT)
        return out["summary"]
    with ThreadPoolExecutor(8) as ex:
        maps = list(ex.map(mapper, [ids[i:i + 50] for i in range(0, len(ids), 50)]))
    groups = [maps[i:i + group] for i in range(0, len(maps), group)]
    per_group = budget_chars // len(groups)

    def reducer(g):
        out, _ = llm.complete("claude-sonnet-5-5", "You merge summaries. Output JSON only.",
                              f"TOPIC: {topic}\nMerge these {len(g)} batch summaries (each covers 50 posts) into one summary "
                              f"of about {per_group // 6} words (use the space). Keep every distinct point, with approximate counts "
                              "and sides; merge repeats.\n\n" + "\n\n".join(g), TEXT, effort="medium")
        return out["summary"]
    with ThreadPoolExecutor(4) as ex:
        reduced = list(ex.map(reducer, groups))
    summary = "\n\n".join(f"[Part {k + 1}: posts {k * 50 * group + 1}-{min(len(ids), (k + 1) * 50 * group)}]\n{s}"
                          for k, s in enumerate(reduced))[:budget_chars]
    build_usd = llm.SPEND["usd"] - spend0
    rng = np.random.default_rng(1000)
    pts = points(texts, sorted(rng.choice(ids, size=150, replace=False).tolist()), topic)
    res = {"summary_tokens_est": len(summary.encode()) // 4, "ledger_tokens_est": L.est_tokens(view),
           "summary_build_usd": build_usd}
    compact, _ = L.render_multires(32000, compact=True)
    for name, ctx in (("ledger (theme view)", view), ("ledger (compact lines)", compact), ("map-reduce summary", summary)):
        res[name] = coverage(name, ctx, pts)
        out, _ = llm.complete("claude-opus-5-5", "You estimate corpus statistics. Output JSON only.",
                              f"MATERIAL about {len(ids)} posts on {topic}:\n{ctx}\n\nAmong authors who take a discernible "
                              f"position on the statement '{anchor}', what percentage agree with it?", SHARE, effort="medium")
        res[name]["agree_share_estimate"] = out["agree_pct_among_positioned"]
        print(name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res[name].items()}, flush=True)
    (d / f"summary_baseline{tag}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if not isinstance(v, dict)}, indent=1))


if __name__ == "__main__":
    if "--compact" in sys.argv:    # same as --large, plus the compact-line ledger view
        main(Path(sys.argv[1]), map_words=500, group=6, tag="_compact")
    elif "--large" in sys.argv:      # fill the ledger's budget: longer map summaries, smaller reduce groups
        main(Path(sys.argv[1]), map_words=500, group=6, tag="_large")
    else:
        main(Path(sys.argv[1]))
