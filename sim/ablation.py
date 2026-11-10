"""Ablations: what does each CEL mechanism contribute? (simulation, 3 seeds)
Run: python -m sim.ablation   (writes results/ablation.md)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from celedger.ledger import N_TIME_BINS
from sim.experiment import census_stance, entry_share, ledger_views, spearman
from sim.sim_absorber import build_ledger
from sim.world import make_world, support_share, truth_author_stance, truth_emerging

VARIANTS = {"full CEL": {}, "no consolidation": {"do_consolidate": False},
            "no residual re-absorption": {"do_reabsorb": False},
            "neither": {"do_consolidate": False, "do_reabsorb": False}}


def metrics(w, L, rng):
    ats = truth_author_stance(w)
    org = [{a: s for a, s in x.items() if not a.startswith("bot")} for x in ats]
    n_org = np.array([len(x) for x in org])
    _, best = ledger_views(L, 32000)
    order = np.argsort(-n_org)
    probe = [c for c in order[:100] if n_org[c] >= 5]
    big = np.where(n_org >= 10)[0]
    em = truth_emerging(w)
    flag = {c for c, e in best.items() if len(e.author_stance) >= 5 and sum(e.time_bins) and
            sum(e.time_bins[int(N_TIME_BINS * 2 / 3):]) / sum(e.time_bins) >= 0.75}
    st = [abs((entry_share(best[c]) if c in best and entry_share(best[c]) is not None else 0.5) - support_share(org[c])) for c in probe]
    cen = [abs((census_stance(w, L, best[c], c, rng)[0] or 0.5) - support_share(org[c])) if c in best else 0.5 for c in probe]
    return {"entries": len(L.entries), "residual %": 100 * L.residual_mass / len(L.docs),
            "recall >=3": len(set(np.where(n_org >= 3)[0]) & set(best)) / (n_org >= 3).sum(),
            "Spearman": spearman(n_org[big], np.array([len(best[c].author_stance) if c in best else 0 for c in big])),
            "stance MAE (no census)": float(np.mean(st)), "stance MAE (census)": float(np.mean(cen)),
            "emerging recall": len(flag & em) / max(1, len(em))}


def main():
    out = ["# Ablations (simulation, 3 seeds, mean)\n"]
    for eps in (0.1, 0.2):
        rows = {}
        for name, kw in VARIANTS.items():
            ms = []
            for seed in (0, 1, 2):
                w = make_world(seed=seed)
                L, _ = build_ledger(w, eps, seed=seed + 7, **kw)
                ms.append(metrics(w, L, np.random.default_rng(seed)))
            rows[name] = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
        keys = list(next(iter(rows.values())))
        out += [f"\n## absorber eps = {eps}\n", "| variant | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
        for name, r in rows.items():
            out.append(f"| {name} | " + " | ".join(f"{r[k]:.0f}" if k == "entries" else
                                                   (f"{100 * r[k]:.0f}%" if k in ("recall >=3", "emerging recall") else f"{r[k]:.3f}")
                                                   for k in keys) + " |")
    Path("results/ablation.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
