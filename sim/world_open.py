"""An *open* niche-topic feed: new claims keep appearing forever.

The first simulation (world.py) had a fixed set of 300 claims, so the ledger stopped
growing, which flatters CEL. Here claims follow a Pitman-Yor process:
P(new claim) = (theta + sigma*K) / (n + theta), P(existing c) ∝ (n_c - sigma).
That gives a heavy-tailed claim distribution with K ~ N^sigma distinct claims (Heaps'
law), the regime real social-media topics are in. Claims belong to themes (a Chinese
restaurant process); the most confusable claim is another claim in the same theme.

Returns a World-compatible object, so sim_absorber.build_ledger can absorb it.
"""
from __future__ import annotations

import numpy as np

from sim.world import Post, World


def make_open_world(n_posts: int, seed: int = 0, theta: float = 30.0, sigma: float = 0.6,
                    theme_theta: float = 4.0, noise_frac: float = 0.12, authors_per_post: float = 0.2) -> World:
    rng = np.random.default_rng(seed)
    n_authors = max(100, int(n_posts * authors_per_post))
    act = 1 / np.arange(1, n_authors + 1) ** 0.9
    act /= act.sum()
    authors = rng.choice(n_authors, size=n_posts, p=act)
    reach = np.log1p(rng.pareto(1.5, size=n_posts) * 5)

    counts: list[int] = []      # claim -> posts so far
    theme: list[int] = []       # claim -> theme
    theme_n: list[int] = []     # theme -> claims
    assign: list[int] = []      # every claim mention so far (for proposal sampling)
    support_p: list[float] = []
    last: dict[int, int] = {}
    posts = []

    def new_claim():
        K = len(counts)
        nt = sum(theme_n)
        if rng.random() < theme_theta / (nt + theme_theta):
            theme_n.append(0)
            th = len(theme_n) - 1
        else:
            th = int(rng.choice(len(theme_n), p=np.array(theme_n) / nt))
        theme_n[th] += 1
        theme.append(th)
        counts.append(0)
        support_p.append(float(rng.beta(1.5, 1.5)))
        return K

    def draw_claim():
        n, K = len(assign), len(counts)
        if K == 0 or rng.random() < (theta + sigma * K) / (n + theta):
            return new_claim()
        while True:             # proposal ∝ n_c (copy a random earlier mention), accept w.p. (n_c - sigma)/n_c
            c = assign[rng.integers(n)]
            if rng.random() < (counts[c] - sigma) / counts[c]:
                return c

    for i in range(n_posts):
        a = int(authors[i])
        if rng.random() < noise_frac:
            posts.append(Post(i, f"u{a}", i / n_posts, [], [], float(reach[i])))
            continue
        k = 1 if rng.random() < 0.8 else 2
        cs = []
        while len(cs) < k:
            c = last[a] if (a in last and rng.random() < 0.3) else draw_claim()
            if any(c == x for x, _ in cs):
                if k == 2 and len(cs) == 1:
                    k = 1
                continue
            r = rng.random()
            s = "mention" if r < 0.15 else ("support" if rng.random() < support_p[c] else "dispute")
            cs.append((c, s))
            counts[c] += 1
            assign.append(c)
        last[a] = cs[0][0]
        posts.append(Post(i, f"u{a}", i / n_posts, cs, [], float(reach[i])))

    K = len(counts)
    by_theme: dict[int, list[int]] = {}
    for c, th in enumerate(theme):
        by_theme.setdefault(th, []).append(c)
    confusable = []
    for c in range(K):
        sib = by_theme[theme[c]]
        confusable.append(int(rng.choice(sib)) if len(sib) > 1 else int(rng.integers(K)))
    w = World(posts, K, [[] for _ in range(K)], np.array(support_p), ["steady"] * K, -1, confusable)
    w.theme = theme
    return w
