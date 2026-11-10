"""Throughput: parallel absorption lanes. Within an epoch, P lanes absorb concurrently
against the same frozen index and cannot see each other's new entries until the epoch's
consolidation. How much accuracy does P-fold speed cost? (simulation, 3 seeds, eps=0.1)
Run: python -m sim.lanes   (writes results/lanes.md)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from sim.ablation import metrics
from sim.sim_absorber import build_ledger
from sim.world import make_world

LANES = [1, 4, 16, 64]


def main():
    out = ["# Parallel absorption lanes (simulation, 21.5k posts, eps=0.1, 3 seeds)\n",
           "Epoch = 20 batches of 100 posts; with P lanes, wall-clock time is ~1/P of sequential.\n"]
    rows = {}
    for P in LANES:
        ms = []
        for seed in (0, 1, 2):
            w = make_world(seed=seed)
            L, st = build_ledger(w, 0.1, seed=seed + 7, lanes=P)
            m = metrics(w, L, np.random.default_rng(seed))
            m["merges"] = st["merges"]
            ms.append(m)
        rows[P] = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
    keys = list(rows[1])
    out += ["| lanes | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for P, r in rows.items():
        out.append(f"| {P} | " + " | ".join(f"{r[k]:.0f}" if k in ("entries", "merges") else
                                            (f"{100 * r[k]:.0f}%" if k in ("recall >=3", "emerging recall") else f"{r[k]:.3f}")
                                            for k in keys) + " |")
    Path("results/lanes.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
