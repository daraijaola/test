"""Stand-in for the LLM absorber with an explicit error model.

The point of the simulation is to measure the *architecture* (what reaches the
reading model, at what cost) separately from absorber quality.  Absorber quality
is a single knob eps, applied as:
  miss       eps/2   claim goes to residual (absorber unsure)
  misassign  eps     claim credited to the most lexically confusable entry
  fragment   eps     a matching entry exists but a duplicate NEW entry is made
  stance     eps/2   stance flipped
  noise leak eps/2   an off-topic post is credited to a random entry
  merge miss eps     consolidation fails to notice a duplicate pair
Real LLM error rates on such a constrained, local task should be measured
(see docs/DESIGN.md, "Validation plan"); we sweep eps from 0 to 0.3.
"""
from __future__ import annotations

import numpy as np

from celedger.ledger import DocMeta, Ledger, Op
from sim.world import World

FLIP = {"support": "dispute", "dispute": "support", "mention": "mention"}


def build_ledger(w: World, eps: float, seed: int = 1, batch: int = 100, epoch_batches: int = 20,
                 trace: list | None = None, shard_cap: int | None = None, route_err: float = 0.0,
                 cross_merge: float = 0.5, do_consolidate: bool = True,
                 do_reabsorb: bool = True) -> tuple[Ledger, dict]:
    """shard_cap: above this many entries the absorber sees only one routed theme's entries
    (route_err = probability the router picks the wrong theme). cross_merge: relative chance
    that consolidation notices a duplicate living in a *different* theme."""
    rng = np.random.default_rng(seed)
    L = Ledger()
    by_label: dict[int, list[int]] = {}
    stats = {"batches": 0, "epochs": 0, "frozen_entries": [], "fresh_entries": [], "merges": 0,
             "sharded_batches": 0, "misroutes": 0}
    themes = getattr(w, "theme", None)
    n_themes = (max(themes) + 1) if themes else 1
    shard = {"on": False, "theme": None}

    def theme_for_new(c):
        if themes is None:
            return None
        if shard["on"]:
            return shard["theme"]
        return themes[c] if rng.random() >= eps else int(rng.integers(n_themes))

    def visible(e):
        return not shard["on"] or L.entries[e].theme == shard["theme"]

    def live(c):
        ids = [L.resolve(e) for e in by_label.get(c, [])]
        ids = sorted({e for e in ids if e in L.entries})
        by_label[c] = ids
        return [e for e in ids if visible(e)]

    def any_visible():
        if not shard["on"]:
            return list(L.entries)
        return [e for e in shard_members.get(shard["theme"], ()) if e in L.entries]

    shard_members: dict = {}

    def ops_for(p):
        if not p.claims:
            if rng.random() < eps / 2 and L.entries:
                e = int(rng.choice(list(L.entries)))
                return [Op("assign", e, "mention")]
            return [Op("noise")]
        ops = []
        if themes is not None and shard_cap is not None and len(L.entries) > shard_cap:
            th = themes[p.claims[0][0]]
            if rng.random() < route_err:
                th = int(rng.integers(n_themes)); stats["misroutes"] += 1
            shard["on"], shard["theme"] = True, th
        else:
            shard["on"] = False
        for c, s in p.claims:
            if rng.random() < eps / 2:
                s = FLIP[s]
            r = rng.random()
            if r < eps / 2:
                ops.append(Op("residual"))
                continue
            if r < eps / 2 + eps:
                tgt = live(w.confusable[c]) or any_visible()
                if tgt:
                    ops.append(Op("assign", int(rng.choice(tgt)), s))
                    continue
            ids = live(c)
            if ids and rng.random() >= eps:
                mass = np.array([L.entries[e].total + 1 for e in ids])
                ops.append(Op("assign", int(rng.choice(ids, p=mass / mass.sum())), s))
            else:
                ops.append(Op("new", None, s, f"claim {c} wording {len(ids)}", label=(c, theme_for_new(c))))
        return ops

    posts = sorted(w.posts, key=lambda p: p.t)
    frozen = 0
    for i in range(0, len(posts), batch):
        stats["batches"] += 1
        stats["frozen_entries"].append(frozen)
        before = len(L.entries)
        for p in posts[i:i + batch]:
            ops = ops_for(p)
            created = L.absorb(DocMeta(p.pid, p.author, p.t, p.reach), ops)
            for eid in created:
                e = L.entries[eid]
                c, th = e.label
                e.label, e.theme = c, th
                by_label.setdefault(c, []).append(eid)
                shard_members.setdefault(th, []).append(eid)
            if shard["on"]:
                stats["sharded_batches"] += 1 / batch
        stats["fresh_entries"].append(len(L.entries) - frozen)
        if stats["batches"] % epoch_batches == 0 and do_consolidate:
            stats["merges"] += consolidate_sim(L, by_label, eps, rng, cross_merge)
            stats["epochs"] += 1
            frozen = len(L.entries)
        if trace is not None:
            trace.append((i + batch, len(L.entries)))
    if do_consolidate:
        stats["merges"] += consolidate_sim(L, by_label, eps, rng, cross_merge)
    shard["on"] = False
    # second-chance pass over the residual
    pmap = {p.pid: p for p in w.posts}
    for d in sorted(L.residual) if do_reabsorb else []:
        L.reabsorb_residual(d, ops_for(pmap[d]))
    L.check_conservation()
    return L, stats


def consolidate_sim(L: Ledger, by_label: dict, eps: float, rng, cross_merge: float = 0.5) -> int:
    n = 0
    for c, ids in by_label.items():
        ids = sorted({L.resolve(e) for e in ids if L.resolve(e) in L.entries},
                     key=lambda e: -L.entries[e].total)
        for g in ids[1:]:
            same = L.entries[ids[0]].theme == L.entries[g].theme
            if rng.random() < (1 - eps) * (1.0 if same else cross_merge):
                L.merge(ids[0], g)
                n += 1
    L.epoch += 1
    L.check_conservation()
    return n
