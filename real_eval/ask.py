"""Open questions about a real topic, answered (a) from the ledger held as a CACHED system
prompt, asked back to back so the measured cost reflects caching, and (b) by RAG top-20 /
top-100. Writes a side-by-side file for human inspection plus measured per-question costs.

Usage: python -m real_eval.ask results/bsky_seedoils [--pkl ledger_v3.pkl]
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

from celedger import llm
from sim.baseline import BM25

READER = "claude-opus-5-5"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}
QUESTIONS = {
    "seed": [
        "What are the main arguments made by people who think seed oils are harmful, and roughly how many people make each?",
        "How do defenders of seed oils respond, and which of their arguments are most common?",
        "Overall, what share of people with a discernible position think seed oils are safe?",
        "Which claims or themes became prominent only recently, and which faded?",
        "Is there evidence of coordinated or bot-like amplification of any claim?",
        "What do people say about beef tallow specifically, and is that mostly praise or criticism?",
    ],
    "upf": [
        "What are the main health harms people attribute to ultra-processed foods, and how widespread is each claim?",
        "Who pushes back on the ultra-processed food narrative, and with what arguments?",
        "Overall, what share of people with a discernible position think ultra-processed foods are harmful?",
        "Which claims or themes became prominent only recently, and which faded?",
        "What policy proposals come up (bans, labels, taxes, school food), and how much support does each get?",
        "How is the topic tied to politics or specific public figures?",
    ],
}
INSTR = ("Answer questions about a corpus of social-media posts using ONLY the material provided. Give numbers "
         "(people, posts, shares) where the material supports them, say what the material does not tell you, and "
         "keep the answer under 180 words.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--pkl", default="ledger_v3.pkl")
    a = ap.parse_args()
    st = pickle.loads((a.dir / a.pkl).read_bytes())
    L, texts = st["ledger"], st["texts"]
    qs = QUESTIONS["seed" if "seed" in str(a.dir) else "upf"]
    view, _ = L.render_multires(32000)
    n = len(texts)
    out = {"ledger": [], "rag20": [], "rag100": []}
    system = INSTR + "\n\nTHE COMPLETE LEDGER OF THIS CORPUS:\n" + view
    for q in qs:                                   # back to back: the cached system prompt is reused
        k0 = len(llm.CALLS)
        r, usd = llm.complete(READER, system, q, SCHEMA, effort="medium")
        out["ledger"].append({"q": q, "a": r["answer"], **llm.CALLS[k0]})
    ids = sorted(texts)
    bm = BM25([texts[i].lower().split() for i in ids])
    for k in (20, 100):
        for q in qs:
            top = bm.top(q.lower().split(), k)
            k0 = len(llm.CALLS)
            r, usd = llm.complete(READER, INSTR, f"RETRIEVED POSTS (top {k} of {n}):\n" +
                                  "\n".join(f"- {texts[i]}" for i in top) + "\n\nQUESTION: " + q, SCHEMA, effort="medium")
            out[f"rag{k}"].append({"q": q, "a": r["answer"], **llm.CALLS[k0]})
    (a.dir / "ask.json").write_text(json.dumps(out, indent=1))
    md = [f"# Open questions, side by side ({n:,} posts)\n",
          "Same reader (Opus 5.5, medium effort). Ledger = theme view held as a cached system prompt. RAG = BM25 top-k.\n",
          "| method | mean $ / question | mean cache-read tokens | mean uncached input tokens |", "|---|---|---|---|"]
    for m, rows in out.items():
        md.append(f"| {m} | ${sum(r['usd'] for r in rows) / len(rows):.3f} | {sum(r['cache_read'] for r in rows) / len(rows):,.0f} | "
                  f"{sum(r['input'] + r['cache_write'] for r in rows) / len(rows):,.0f} |")
    md.append(f"\nLedger, first question (cache write): ${out['ledger'][0]['usd']:.3f}; later questions (cache read): "
              f"${sum(r['usd'] for r in out['ledger'][1:]) / max(1, len(out['ledger']) - 1):.3f} each.\n")
    for i, q in enumerate(qs):
        md += [f"\n## Q{i + 1}. {q}\n"]
        for m in out:
            md += [f"**{m}:** {out[m][i]['a']}\n"]
    (a.dir / "ask.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:8]))


if __name__ == "__main__":
    main()
