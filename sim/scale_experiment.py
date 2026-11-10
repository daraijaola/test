"""Scaling test on an open world (claims never stop arriving).

For N = 20k .. 200k posts: how big does the ledger get, does sharding the absorber's
index hurt, how much of the long tail stays visible under a fixed 32k-token reading
budget (flat vs theme-grouped view), and what does it cost vs RAG at equal coverage?

Run: python -m sim.scale_experiment   (writes results/scale.json + results/scale.md)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from celedger.ledger import DISPUTE, SUPPORT
from sim import cost
from sim.baseline import claims_seen
from sim.experiment import spearman
from sim.sim_absorber import build_ledger
from sim.world import support_share, truth_author_stance
from sim.world_open import make_open_world

NS = [20_000, 50_000, 100_000, 200_000, 500_000]
EPS = 0.10
CONFIGS = [("flat index", None, 0.0), ("sharded >2k entries, 5% misroute", 2000, 0.05), ("sharded >2k entries, 15% misroute", 2000, 0.15)]
BUDGET = 32_000
FRACS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.4]


def share(e):
    a = e.authors_by_stance()
    return None if a[SUPPORT] + a[DISPUTE] == 0 else a[SUPPORT] / (a[SUPPORT] + a[DISPUTE])


def run(N: int, seed: int = 0) -> dict:
    w = make_open_world(N, seed=seed)
    ats = truth_author_stance(w)
    n_auth = np.array([len(x) for x in ats])
    out = {"N": N, "claims": w.n_claims, "themes": max(w.theme) + 1,
           "claims_ge3": int((n_auth >= 3).sum()), "claims_ge10": int((n_auth >= 10).sum()), "configs": {}}
    rng = np.random.default_rng(seed + 11)
    order = np.argsort(-n_auth)
    head = list(order[:20])
    mid = [c for c in order[20:200] if n_auth[c] >= 10][:20]
    tail = [c for c in order if 10 <= n_auth[c] < 30]
    tail = list(rng.choice(tail, size=min(20, len(tail)), replace=False)) if tail else []

    # RAG at equal coverage: smallest uniform sample fraction reaching 90% of >=10-person claims
    tgt = set(np.where(n_auth >= 10)[0])
    out["rag_parity"] = {}
    for f in FRACS:
        seen = claims_seen(w, list(rng.choice(len(w.posts), size=int(f * len(w.posts)), replace=False)))
        out["rag_parity"][f] = len(tgt & set(seen)) / max(1, len(tgt))

    for name, cap, rho in CONFIGS:
        t0 = time.time()
        L, st = build_ledger(w, EPS, seed=seed + 3, shard_cap=cap, route_err=rho)
        r = {"entries": len(L.entries), "residual_pct": 100 * L.residual_mass / len(L.docs),
             "sharded_doc_share": st["sharded_batches"] / max(1, st["batches"]), "misroutes": st["misroutes"]}
        frag = {}
        for e in L.entries.values():
            frag.setdefault(e.label, []).append(e)
        r["fragments_per_claim_ge10"] = float(np.mean([len(frag.get(c, [])) for c in tgt])) if tgt else 0
        best_all = {c: max(es, key=lambda e: len(e.author_stance)) for c, es in frag.items()}
        for view in ("flat", "multires"):
            text, shown = (L.render if view == "flat" else L.render_multires)(BUDGET)
            vis = {}
            for eid in shown:
                e = L.entries[eid]
                if e.label not in vis or len(e.author_stance) > len(vis[e.label].author_stance):
                    vis[e.label] = e
            for m in (3, 10, 30, 100):
                tg = set(np.where(n_auth >= m)[0])
                r[f"{view}_recall_ge{m}"] = len(tg & set(vis)) / max(1, len(tg))
            big = np.where(n_auth >= 10)[0]
            r[f"{view}_spearman"] = spearman(n_auth[big], np.array([len(vis[c].author_stance) if c in vis else 0 for c in big]))
            r[f"{view}_tokens"] = L.est_tokens(text)
            if view == "multires" and N == NS[-1] and name == CONFIGS[1][0]:
                Path("results/sample_multires_view.txt").write_text(text[:5000] + "\n...\n")
        for nm, cs in (("head", head), ("mid", mid), ("tail", tail)):
            errs = []
            for c in cs:
                est = share(best_all[c]) if c in best_all else None
                errs.append(abs((0.5 if est is None else est) - support_share(ats[c])))
            r[f"stance_mae_{nm}"] = float(np.mean(errs)) if errs else None
        if N == NS[-1] and name == CONFIGS[0][0]:
            r["budget_sweep"] = {}
            for B in (32_000, 64_000, 128_000, 256_000):
                for view in ("flat", "multires"):
                    _, shown = (L.render if view == "flat" else L.render_multires)(B)
                    labs = {L.entries[e].label for e in shown}
                    r["budget_sweep"][f"{view}_{B}"] = {m: len(set(np.where(n_auth >= m)[0]) & labs) / max(1, (n_auth >= m).sum())
                                                        for m in (3, 10, 30)}
        ing = cost.ledger_ingest_cost(N, st["frozen_entries"], st["fresh_entries"], st["epochs"], len(L.entries),
                                      discount=0.5)
        r["ingest_usd_batch_api"] = ing["usd"]
        r["seconds"] = time.time() - t0
        out["configs"][name] = r
        print(f"N={N} {name}: D={len(L.entries)} K={w.n_claims} recall>=10 flat={r['flat_recall_ge10']:.2f} "
              f"multires={r['multires_recall_ge10']:.2f} ${ing['usd']:.2f} {r['seconds']:.0f}s", flush=True)
    return out


def main():
    runs = [run(N) for N in NS]
    Path("results").mkdir(exist_ok=True)
    Path("results/scale.json").write_text(json.dumps(runs, indent=1, default=float))
    lnN = np.log([r["N"] for r in runs])
    beta_K = np.polyfit(lnN, np.log([r["claims"] for r in runs]), 1)[0]
    beta_D = np.polyfit(lnN, np.log([r["configs"][CONFIGS[0][0]]["entries"] for r in runs]), 1)[0]
    L = ["# Scaling on an open world (claims keep arriving)\n",
         f"Pitman-Yor claim stream (sigma=0.6), claims grouped into themes, absorber eps={EPS}. "
         f"Reading budget {BUDGET:,} tokens. Fitted growth: true claims K ~ N^{beta_K:.2f}, ledger entries D ~ N^{beta_D:.2f}.\n",
         "## Size and fragmentation\n",
         "| N posts | true claims | claims >=10 people | config | entries D | entries per >=10-person claim | residual % | ingest $ (Batches) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in runs:
        for name, *_ in CONFIGS:
            c = r["configs"][name]
            L.append(f"| {r['N']:,} | {r['claims']:,} | {r['claims_ge10']:,} | {name} | {c['entries']:,} | "
                     f"{c['fragments_per_claim_ge10']:.2f} | {c['residual_pct']:.2f} | ${c['ingest_usd_batch_api']:.2f} |")
    L += ["\n## What the reading model can see within 32k tokens\n",
          "Entry-level visibility of claims held by >= m people (every claim's mass is always counted in a theme or fold line).\n",
          "| N | config | view | >=3 | >=10 | >=30 | >=100 | prevalence Spearman | tokens |", "|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        for name, *_ in CONFIGS:
            c = r["configs"][name]
            for v in ("flat", "multires"):
                L.append(f"| {r['N']:,} | {name} | {v} | " + " | ".join(f"{100 * c[f'{v}_recall_ge{m}']:.0f}%" for m in (3, 10, 30, 100))
                         + f" | {c[f'{v}_spearman']:.3f} | {c[f'{v}_tokens']:,} |")
    sw = runs[-1]["configs"][CONFIGS[0][0]].get("budget_sweep")
    if sw:
        L += [f"\n## Reading budget vs visibility at N={runs[-1]['N']:,}\n",
              "| budget (tokens) | view | >=3 | >=10 | >=30 | Opus 5.5 cached read $/query |", "|---|---|---|---|---|---|"]
        for B in (32_000, 64_000, 128_000, 256_000):
            for v in ("flat", "multires"):
                x = sw[f"{v}_{B}"]
                L.append(f"| {B:,} | {v} | {100 * x[3]:.0f}% | {100 * x[10]:.0f}% | {100 * x[30]:.0f}% | "
                         f"${cost.usd('claude-opus-5-5', cache_read=B, inp=120, out=600):.3f} |")
    L += ["\n## Stance accuracy (MAE of support share, best entry for the claim)\n",
          "| N | config | head | mid | tail (10-29 people) |", "|---|---|---|---|---|"]
    for r in runs:
        for name, *_ in CONFIGS:
            c = r["configs"][name]
            L.append(f"| {r['N']:,} | {name} | " + " | ".join(
                "n/a" if c[f"stance_mae_{b}"] is None else f"{c[f'stance_mae_{b}']:.3f}" for b in ("head", "mid", "tail")) + " |")
    L += ["\n## RAG at equal coverage\n",
          "Fraction of claims held by >=10 people seen by an ideal uniform random sample of the corpus.\n",
          "| N | " + " | ".join(f"{int(100 * f)}% sample" for f in FRACS) + " |", "|---|" + "---|" * len(FRACS)]
    for r in runs:
        L.append(f"| {r['N']:,} | " + " | ".join(f"{100 * r['rag_parity'][f]:.0f}%" for f in FRACS) + " |")
    L += ["\n## Cost of 1,000 questions at roughly equal coverage\n",
          "| N | ledger: ingest + 1,000 cached reads | RAG reading the sample that reaches ~90% of >=10-person claims, x1,000 |",
          "|---|---|---|"]
    for r in runs:
        c = r["configs"][CONFIGS[1][0]]
        f = next((f for f in FRACS if r["rag_parity"][f] >= 0.9), FRACS[-1])
        k = int(f * r["N"])
        rag = cost.rag_cost(r["N"], k, 1000)["total"] if k * 45 < 1_000_000 else None
        L.append(f"| {r['N']:,} | ${c['ingest_usd_batch_api'] + cost.ledger_query_cost(BUDGET, 1000):,.2f} | "
                 + (f"${rag:,.2f} (k={k:,})" if rag else f"does not fit in 1M context (k={k:,})") + " |")
    Path("results/scale.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
