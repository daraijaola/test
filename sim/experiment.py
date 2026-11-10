"""Head-to-head: Conserved Evidence Ledger vs top-k RAG on whole-corpus questions.

Run:  python -m sim.experiment            (writes results/results.json + results/results.md)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from celedger.ledger import N_TIME_BINS, SUPPORT, DISPUTE
from sim import cost
from sim.baseline import BM25, claims_seen, reader_stance
PARITY_KS = [200, 500, 1000, 2000, 5000, 10000, 20000]
from sim.sim_absorber import build_ledger
from sim.world import make_world, support_share, truth_author_stance, truth_emerging

EPS = [0.0, 0.05, 0.10, 0.20, 0.30]
KS = [10, 20, 50, 100]
RENDER_BUDGET = 32_000
SEEDS = [0, 1, 2]


def _rank(x):
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x)); r[order] = np.arange(len(x))
    for v in np.unique(x):            # average ranks over ties
        m = x == v
        r[m] = r[m].mean()
    return r


def spearman(a, b):
    ra, rb = _rank(a), _rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def flagged_accounts(e, conc_thresh=0.5, per_acct=0.05):
    """Accounts a reader would discount after seeing the concentration flag."""
    if e.concentration() <= conc_thresh or e.total < 50:
        return set()
    return {a for a, m in e.author_docs.items() if m / e.total >= per_acct}


def census_stance(w, L, e, c, rng, cap=300):
    """Exact-scope verification: a strong reader re-reads up to `cap` docs drawn
    uniformly from the entry's exact posting list (no similarity search)."""
    docs = L.postings(e.eid)
    if len(docs) > cap:
        docs = list(rng.choice(docs, size=cap, replace=False))
    return reader_stance(w, docs, c), len(docs)


def ledger_views(L, budget):
    text, shown = L.render(budget)
    vis = [L.entries[e] for e in shown]
    best = {}                                 # label -> largest visible entry (conservative reader)
    for e in vis:
        if e.label is not None and (e.label not in best or len(e.author_stance) > len(best[e.label].author_stance)):
            best[e.label] = e
    return text, best


def entry_share(e):
    a = e.authors_by_stance()
    return None if a[SUPPORT] + a[DISPUTE] == 0 else a[SUPPORT] / (a[SUPPORT] + a[DISPUTE])


def run_seed(seed: int) -> dict:
    w = make_world(seed=seed)
    ats = truth_author_stance(w)
    n_auth = np.array([len(x) for x in ats])
    organic = [{a: s for a, s in x.items() if not a.startswith("bot")} for x in ats]
    n_org = np.array([len(x) for x in organic])
    bm = BM25([p.words for p in w.posts])
    rng = np.random.default_rng(100 + seed)

    order = np.argsort(-n_org)
    head = [c for c in order[:20]]
    mid = [c for c in order[20:100] if n_org[c] >= 5][:20]
    tail = [c for c in order[100:] if n_org[c] >= 5][:20]
    probe = {"head": head, "mid": mid, "tail": tail}
    emerging = truth_emerging(w)
    out = {"seed": seed, "n_docs": len(w.posts), "rag": {}, "ledger": {}}

    # ------------------------------------------------------------------ RAG
    generic = [f"t{i}" for i in range(12)]
    for k in KS:
        r = {}
        seen_g = claims_seen(w, bm.top(generic, k))
        sample = list(rng.choice(len(w.posts), size=k, replace=False))
        seen_r = claims_seen(w, sample)
        for m in (3, 10, 30):
            tgt = set(np.where(n_org >= m)[0])
            r[f"landscape_recall_ge{m}_query"] = len(tgt & set(seen_g)) / len(tgt)
            r[f"landscape_recall_ge{m}_randsample"] = len(tgt & set(seen_r)) / len(tgt)
        big = np.where(n_org >= 10)[0]
        r["prevalence_spearman_randsample"] = spearman(n_org[big], np.array([seen_r.get(c, 0) for c in big]))
        r["prevalence_spearman_query"] = spearman(n_org[big], np.array([seen_g.get(c, 0) for c in big]))
        for name, cs in probe.items():
            errs, unknown = [], 0
            for c in cs:
                est = reader_stance(w, bm.top(w.claim_words[c], k), c)
                tru = support_share(organic[c])
                if est is None:
                    unknown += 1; est = 0.5
                errs.append(abs(est - tru))
            r[f"stance_mae_{name}"] = float(np.mean(errs)); r[f"stance_unknown_{name}"] = unknown / len(cs)
        # emerging, from an (optimistic) uniform sample of k posts
        tim = {}
        for i in sample:
            for c, _ in w.posts[i].claims:
                tim.setdefault(c, []).append(w.posts[i].t)
        flag = {c for c, ts in tim.items() if len(ts) >= 2 and min(ts) >= 2 / 3}
        tp = len(flag & emerging)
        r["emerging_recall"] = tp / max(1, len(emerging))
        r["emerging_precision"] = tp / len(flag) if flag else 0.0
        bc = w.bot_claim
        pids = bm.top(w.claim_words[bc], k)
        r["bot_claim_share_dedup"] = reader_stance(w, pids, bc, True)
        r["bot_claim_share_raw"] = reader_stance(w, pids, bc, False)
        r["bot_fraction_of_retrieved"] = float(np.mean([w.posts[i].is_bot for i in pids]))
        out["rag"][k] = r
    out["bot_truth_organic"] = support_share(organic[w.bot_claim])
    out["parity"] = {}
    for k in PARITY_KS:
        seen = claims_seen(w, list(rng.choice(len(w.posts), size=k, replace=False)))
        out["parity"][k] = {m: len(set(np.where(n_org >= m)[0]) & set(seen)) / len(np.where(n_org >= m)[0]) for m in (3, 10, 30)}

    # --------------------------------------------------------------- ledger
    for eps in EPS:
        t0 = time.time()
        trace = []
        L, st = build_ledger(w, eps, seed=seed + 7, trace=trace)
        text, best = ledger_views(L, RENDER_BUDGET)
        r = {"entries": len(L.entries), "render_tokens": L.est_tokens(text)}
        r["residual_pct"] = 100 * L.residual_mass / len(L.docs)
        r["conservation_total"] = L.check_conservation()
        for m in (3, 10, 30):
            tgt = set(np.where(n_org >= m)[0])
            r[f"landscape_recall_ge{m}"] = len(tgt & set(best)) / len(tgt)
        big = np.where(n_org >= 10)[0]
        r["prevalence_spearman"] = spearman(n_org[big], np.array([len(best[c].author_stance) if c in best else 0 for c in big]))
        for name, cs in probe.items():
            errs, unknown = [], 0
            for c in cs:
                est = entry_share(best[c]) if c in best else None
                if est is None:
                    unknown += 1; est = 0.5
                errs.append(abs(est - support_share(organic[c])))
            r[f"stance_mae_{name}"] = float(np.mean(errs)); r[f"stance_unknown_{name}"] = unknown / len(cs)
            cerrs, cdocs = [], []
            for c in cs:
                est, nd = census_stance(w, L, best[c], c, rng) if c in best else (None, 0)
                cerrs.append(abs((0.5 if est is None else est) - support_share(organic[c]))); cdocs.append(nd)
            r[f"census_mae_{name}"] = float(np.mean(cerrs)); r[f"census_docs_{name}"] = float(np.mean(cdocs))
        flag = set()
        for c, e in best.items():
            tot = sum(e.time_bins)
            if len(e.author_stance) >= 5 and tot and sum(e.time_bins[int(N_TIME_BINS * 2 / 3):]) / tot >= 0.75:
                flag.add(c)
        tp = len(flag & emerging)
        r["emerging_recall"] = tp / max(1, len(emerging))
        r["emerging_precision"] = tp / len(flag) if flag else 0.0
        bc = w.bot_claim
        r["bot_claim_share_authors"] = entry_share(best[bc]) if bc in best else None
        if bc in best:
            fl = flagged_accounts(best[bc])
            a = best[bc].authors_by_stance(exclude=fl)
            r["bot_claim_share_discounted"] = a[SUPPORT] / max(1, a[SUPPORT] + a[DISPUTE])
            r["bot_flagged_accounts"] = len(fl)
            r["bot_flagged_true_bots"] = sum(1 for x in fl if x.startswith("bot"))
            # false alarms: other visible entries carrying the flag
            r["false_flags"] = sum(1 for e in best.values() if e.label != bc and flagged_accounts(e))
        r["bot_claim_share_raw_docs"] = (best[bc].mass[SUPPORT] / (best[bc].mass[SUPPORT] + best[bc].mass[DISPUTE])) if bc in best else None
        ing = cost.ledger_ingest_cost(len(w.posts), st["frozen_entries"], st["fresh_entries"], st["epochs"], len(L.entries))
        r["ingest_usd"] = ing["usd"]; r["ingest_tokens"] = ing["tokens"]
        r["merges"] = st["merges"]; r["build_seconds"] = time.time() - t0
        r["growth_trace"] = trace[:: max(1, len(trace) // 20)]
        out["ledger"][eps] = r
        if eps == 0.10 and seed == 0:
            Path("results").mkdir(exist_ok=True)
            Path("results/sample_ledger_view.txt").write_text(text[:6000] + "\n...\n" + text[-800:])
    return out


def agg(runs, path):
    vals = [r for r in runs]
    def g(fn):
        xs = [fn(r) for r in vals]
        xs = [x for x in xs if x is not None]
        return (float(np.mean(xs)), float(np.std(xs))) if xs else (None, None)
    return g


def main():
    runs = [run_seed(s) for s in SEEDS]
    Path("results").mkdir(exist_ok=True)
    Path("results/results.json").write_text(json.dumps(runs, indent=1, default=float))
    write_markdown(runs)


def fmt(m, pct=False):
    if m[0] is None:
        return "n/a"
    return f"{100 * m[0]:.0f}%" if pct else f"{m[0]:.3f}"


def mean(runs, f):
    xs = [f(r) for r in runs]
    xs = [x for x in xs if x is not None]
    return (float(np.mean(xs)), float(np.std(xs))) if xs else (None, None)


def write_markdown(runs):
    n = runs[0]["n_docs"]
    L = []
    L.append(f"# Experiment results\n\nSynthetic niche-topic feed: {n} posts (incl. 1,500 bot posts), 300 latent claims, "
             f"{len(SEEDS)} seeds, mean shown. Ledger view budget: {RENDER_BUDGET:,} tokens. "
             "RAG = BM25 top-k with a *perfect* reader (best case for RAG). Ledger eps = absorber error rate.\n")
    L.append("## 1. Landscape: what fraction of claims held by >= m distinct people is visible to the model at all?\n")
    L.append("| method | >=3 people | >=10 people | >=30 people |\n|---|---|---|---|")
    for k in KS:
        for v, lab in (("query", f"RAG k={k} (topic query)"), ("randsample", f"RAG k={k} (ideal unbiased sample)")):
            L.append(f"| {lab} | " + " | ".join(fmt(mean(runs, lambda r: r['rag'][k][f'landscape_recall_ge{m}_{v}']), True) for m in (3, 10, 30)) + " |")
    for e in EPS:
        L.append(f"| Ledger eps={e} | " + " | ".join(fmt(mean(runs, lambda r: r['ledger'][e][f'landscape_recall_ge{m}']), True) for m in (3, 10, 30)) + " |")
    L.append("\n## 2. Prevalence ranking (Spearman vs truth, claims with >=10 people)\n")
    L.append("| method | Spearman |\n|---|---|")
    for k in KS:
        L.append(f"| RAG k={k} (topic query) | {fmt(mean(runs, lambda r: r['rag'][k]['prevalence_spearman_query']))} |")
        L.append(f"| RAG k={k} (ideal sample) | {fmt(mean(runs, lambda r: r['rag'][k]['prevalence_spearman_randsample']))} |")
    for e in EPS:
        L.append(f"| Ledger eps={e} | {fmt(mean(runs, lambda r: r['ledger'][e]['prevalence_spearman']))} |")
    L.append("\n## 3. Stance: mean absolute error of 'what share of people support claim X' (organic authors)\n")
    L.append("Query names the claim using its own vocabulary (best case for retrieval). 'unknown' = model saw no stance-bearing evidence.\n")
    L.append("| method | head MAE | mid MAE | tail MAE | tail unknown |\n|---|---|---|---|---|")
    for k in KS:
        L.append(f"| RAG k={k} | " + " | ".join(fmt(mean(runs, lambda r: r['rag'][k][f'stance_mae_{b}'])) for b in ("head", "mid", "tail"))
                 + f" | {fmt(mean(runs, lambda r: r['rag'][k]['stance_unknown_tail']), True)} |")
    for e in EPS:
        L.append(f"| Ledger eps={e} | " + " | ".join(fmt(mean(runs, lambda r: r['ledger'][e][f'stance_mae_{b}'])) for b in ("head", "mid", "tail"))
                 + f" | {fmt(mean(runs, lambda r: r['ledger'][e]['stance_unknown_tail']), True)} |")
    for e in EPS:
        L.append(f"| Ledger eps={e} + census verify (<=300 docs from exact posting list) | " + " | ".join(fmt(mean(runs, lambda r: r['ledger'][e][f'census_mae_{b}'])) for b in ("head", "mid", "tail"))
                 + f" | avg docs read: {mean(runs, lambda r: r['ledger'][e]['census_docs_head'])[0]:.0f} head / {mean(runs, lambda r: r['ledger'][e]['census_docs_tail'])[0]:.0f} tail |")
    L.append("\n## 4. Trend: which claims are emerging? (precision / recall)\n")
    L.append("| method | precision | recall |\n|---|---|---|")
    for k in KS:
        L.append(f"| RAG k={k} (ideal sample) | {fmt(mean(runs, lambda r: r['rag'][k]['emerging_precision']), True)} | {fmt(mean(runs, lambda r: r['rag'][k]['emerging_recall']), True)} |")
    for e in EPS:
        L.append(f"| Ledger eps={e} | {fmt(mean(runs, lambda r: r['ledger'][e]['emerging_precision']), True)} | {fmt(mean(runs, lambda r: r['ledger'][e]['emerging_recall']), True)} |")
    L.append(f"\n## 5. Coordinated bot flood (6 accounts, 1,500 near-identical posts supporting one claim)\n")
    L.append(f"True organic support share: **{fmt(mean(runs, lambda r: r['bot_truth_organic']), True)}**\n")
    L.append("| method | estimated support share | bots among evidence |\n|---|---|---|")
    for k in KS:
        L.append(f"| RAG k={k}, reader dedups authors | {fmt(mean(runs, lambda r: r['rag'][k]['bot_claim_share_dedup']), True)} | {fmt(mean(runs, lambda r: r['rag'][k]['bot_fraction_of_retrieved']), True)} of posts |")
        L.append(f"| RAG k={k}, reader counts posts | {fmt(mean(runs, lambda r: r['rag'][k]['bot_claim_share_raw']), True)} | |")
    for e in EPS:
        L.append(f"| Ledger eps={e}, author tally | {fmt(mean(runs, lambda r: r['ledger'][e]['bot_claim_share_authors']), True)} | 6 of the entry's authors, visible |")
    for e in EPS:
        L.append(f"| Ledger eps={e}, reader discounts accounts behind the ⚠ concentration flag | {fmt(mean(runs, lambda r: r['ledger'][e].get('bot_claim_share_discounted')), True)} | "
                 f"flagged {mean(runs, lambda r: r['ledger'][e].get('bot_flagged_accounts'))[0]:.1f} accts ({mean(runs, lambda r: r['ledger'][e].get('bot_flagged_true_bots'))[0]:.1f} true bots); "
                 f"false flags on other entries: {mean(runs, lambda r: r['ledger'][e].get('false_flags'))[0]:.1f} |")
    L.append(f"| Ledger eps=0.1, raw doc mass (what a post-counting view would say) | {fmt(mean(runs, lambda r: r['ledger'][0.1]['bot_claim_share_raw_docs']), True)} | |")

    L.append("\n## 5b. How much would RAG have to read to match the ledger's coverage?\n")
    L.append("Ideal unbiased random sample of k posts (better than any query-driven top-k for coverage).\n")
    L.append("| k | >=3 people | >=10 people | >=30 people | Opus 5.5 $/query | fits 1M window? |\n|---|---|---|---|---|---|")
    for k in PARITY_KS:
        pq = cost.rag_cost(n, k, 1)['per_query']
        L.append(f"| {k:,} | " + " | ".join(fmt(mean(runs, lambda r: r['parity'][k][m]), True) for m in (3, 10, 30))
                 + f" | ${pq:.2f} | {'yes' if k * 45 < 1_000_000 else 'no'} |")
    L.append("\n## 6. Size, residual, conservation\n")
    L.append("| eps | entries | rendered tokens | residual % | merges | conservation (mass == docs) |\n|---|---|---|---|---|---|")
    for e in EPS:
        r0 = runs[0]["ledger"][e]
        L.append(f"| {e} | {mean(runs, lambda r: r['ledger'][e]['entries'])[0]:.0f} | {mean(runs, lambda r: r['ledger'][e]['render_tokens'])[0]:,.0f} | "
                 f"{mean(runs, lambda r: r['ledger'][e]['residual_pct'])[0]:.2f} | {mean(runs, lambda r: r['ledger'][e]['merges'])[0]:.0f} | "
                 f"{r0['conservation_total']:.4f} == {n} |")

    L.append("\n## 7. Cost (USD, list prices; see sim/cost.py for assumptions)\n")
    r10 = runs[0]["ledger"][0.1]
    ing = r10["ingest_usd"]; rt = r10["render_tokens"]
    L.append(f"Ledger ingest at eps=0.1 (Haiku 5.5 absorber + consolidation, every post read once): **${ing:.2f}** standard, "
             f"**${ing / 2:.2f}** via Message Batches (one-time; {r10['ingest_tokens'] / 1e6:.1f}M tokens processed). Rendered ledger: {rt:,} tokens.\n")
    L.append("| queries | Ledger (ingest + Opus 5.5 reads full ledger, cached) | RAG k=20 (Opus 5.5) | RAG k=100 | Long-context: whole corpus in window (cached) |\n|---|---|---|---|---|")
    for q in (1, 10, 100, 1000, 10000):
        led = ing + cost.ledger_query_cost(rt, q)
        lc = cost.long_context_cost(n, q)
        L.append(f"| {q:,} | ${led:,.2f} | ${cost.rag_cost(n, 20, q)['total']:,.2f} | ${cost.rag_cost(n, 100, q)['total']:,.2f} | "
                 + (f"${lc['total']:,.2f} ({lc['ctx_tokens'] / 1e3:.0f}k tok)" if lc else "does not fit") + " |")
    L.append(f"\nPer-query marginal: ledger ${cost.ledger_query_cost(rt, 2) - cost.ledger_query_cost(rt, 1):.4f}, "
             f"RAG k=20 ${cost.rag_cost(n, 20, 1)['per_query']:.4f}, RAG k=100 ${cost.rag_cost(n, 100, 1)['per_query']:.4f}.\n")
    L.append("\n## 8. Scaling projection (assumption-driven, not measured)\n")
    L.append("Distinct assertions D are assumed to grow as D = 2 * N^beta (Heaps-like). Ingest uses Message Batches pricing; absorber prefix sharded above 150k tokens; render capped at 32k tokens with exact folding below the cap. 'RAG k=20' is the cheap, low-coverage baseline; 'RAG at parity' reads 10% of the corpus per query, roughly what section 5b shows is needed (~93%) to approach the ledger's coverage of >=10-person claims.\n")
    L.append("| posts N | beta | entries D | ingest $ | 1,000 queries: ledger | 1,000 queries: RAG k=20 | 1,000 queries: RAG at parity (k=10% of N) | long-context |\n|---|---|---|---|---|---|---|---|")
    for N in (20_000, 200_000, 2_000_000):
        for beta in (0.6, 0.8):
            D = int(2.0 * N ** beta)
            frozen = [D * i // max(1, N // 100) for i in range(N // 100)]
            fresh = [min(D, 50)] * (N // 100)
            ing2 = cost.ledger_ingest_cost(N, frozen, fresh, N // 2000, D, discount=0.5)["usd"]
            rtok = min(32_000, 120 + 30 * D)
            lc = cost.long_context_cost(N, 1000)
            L.append(f"| {N:,} | {beta} | {D:,} | ${ing2:,.2f} | ${ing2 + cost.ledger_query_cost(rtok, 1000):,.2f} | "
                     f"${cost.rag_cost(N, 20, 1000)['total']:,.2f} | "
                     + (f"${cost.rag_cost(N, N // 10, 1000)['total']:,.2f}" if N // 10 * 45 < 1_000_000 else "does not fit") + " | "
                     + (f"${lc['total']:,.2f}" if lc else "does not fit") + " |")
    Path("results/results.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
