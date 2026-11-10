"""Where does stance get lost between a tweet and the ledger?

For each saved ledger: confusion matrix (gold vs ledger-chain prediction) and, for every
tweet whose gold stance is favor/against but whose chain prediction is wrong, the cause:
  noise        absorber called it off-topic
  residual     absorber could not place it
  neutral      placed in an entry the polarity labeller called neutral
  flipped      placed in an entry, but support/dispute x polarity gave the opposite stance
Usage: python -m real_eval.errors results/real_remix_v1 [--examples 6]
"""
from __future__ import annotations

import argparse
import pickle
from collections import Counter
from pathlib import Path


def causes(st):
    L, pol, pred, tweets = st["ledger"], st["polarity"], st["pred"], st["tweets"]
    cm, cause, ex = Counter(), Counter(), {}
    for i, (x, g) in enumerate(tweets):
        p = pred[i]
        cm[(g, p)] += 1
        if g == "none" or g == p:
            continue
        rows = L.log[i]
        kinds = [b for e, b, w in rows]
        if all(k == "noise" for k in kinds):
            c = "noise"
        elif all(k in ("noise", "residual") for k in kinds):
            c = "residual"
        elif p == "none":
            c = "neutral"
        else:
            c = "flipped"
        cause[c] += 1
        ents = [(L.entries[L.resolve(e)].text, b, pol.get(L.resolve(e))) for e, b, w in rows if e is not None]
        ex.setdefault(c, []).append((g, p, x, ents))
    return cm, cause, ex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--examples", type=int, default=4)
    a = ap.parse_args()
    tot_cause = Counter()
    for f in sorted(a.dir.glob("ledger_*.pkl")):
        st = pickle.loads(f.read_bytes())
        cm, cause, ex = causes(st)
        tot_cause += cause
        n_err = sum(cause.values())
        print(f"\n=== {f.stem}  ({len(st['tweets'])} tweets, {n_err} stance-bearing tweets mispredicted)")
        print("gold\\pred  " + "  ".join(f"{p:>8}" for p in ("favor", "against", "none")))
        for g in ("favor", "against", "none"):
            print(f"{g:>9}  " + "  ".join(f"{cm[(g, p)]:>8}" for p in ("favor", "against", "none")))
        print("causes:", dict(cause))
        for c, xs in ex.items():
            for g, p, x, ents in xs[:a.examples]:
                print(f"  [{c}] gold={g} pred={p}: {x[:140]}")
                for t, b, pl in ents:
                    print(f"        -> {b} '{t[:100]}' (polarity {pl})")
    n = sum(tot_cause.values())
    print("\nALL TARGETS causes:", {k: f"{v} ({100 * v / n:.0f}%)" for k, v in tot_cause.most_common()})


if __name__ == "__main__":
    main()
