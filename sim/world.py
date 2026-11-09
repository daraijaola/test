"""A synthetic niche-topic social feed with full ground truth.

Shaped like X/Twitter on a niche subject:
  * claims with heavy-tailed (Zipf) popularity: a few dominant, a long tail;
  * each claim has its own support/dispute split;
  * some claims are *emerging* (appear late), some *fading*;
  * authors have Zipf activity and tend to repeat themselves;
  * a coordinated bot flood pushes one minority claim with near-identical posts;
  * ~12% of posts are off-topic noise.
Text is bag-of-words over a shared topical vocabulary so claims overlap lexically
(that is what makes lexical/semantic retrieval confuse neighbouring claims).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Post:
    pid: int
    author: str
    t: float
    claims: list[tuple[int, str]]   # (claim id, stance)
    words: list[str]
    reach: float
    is_bot: bool = False


@dataclass
class World:
    posts: list[Post]
    n_claims: int
    claim_words: list[list[str]]
    support_p: np.ndarray
    profile: list[str]              # "steady" | "emerging" | "fading"
    bot_claim: int
    confusable: list[int]           # most lexically similar other claim


def make_world(seed: int = 0, n_claims: int = 300, n_posts: int = 20000, n_authors: int = 4000,
               zipf: float = 1.1, noise_frac: float = 0.12, n_bots: int = 6, bot_posts: int = 1500) -> World:
    rng = np.random.default_rng(seed)
    topical = [f"t{i}" for i in range(1200)]
    tw = 1 / np.arange(1, len(topical) + 1) ** 0.8
    tw /= tw.sum()
    sup_words = [f"yes{i}" for i in range(30)]
    dis_words = [f"no{i}" for i in range(30)]
    filler = [f"f{i}" for i in range(3000)]

    claim_words = [list(rng.choice(topical, size=6, replace=False, p=tw)) for _ in range(n_claims)]
    sets = [set(w) for w in claim_words]
    confusable = []
    for c in range(n_claims):
        ov = [len(sets[c] & sets[o]) if o != c else -1 for o in range(n_claims)]
        confusable.append(int(np.argmax(ov)))

    pop = 1 / np.arange(1, n_claims + 1) ** zipf
    pop /= pop.sum()
    support_p = rng.beta(1.5, 1.5, size=n_claims)
    profile = list(rng.choice(["steady", "emerging", "fading"], size=n_claims, p=[0.8, 0.12, 0.08]))
    act = 1 / np.arange(1, n_authors + 1) ** 0.9
    act /= act.sum()

    # bot target: a mid-tail claim that real people mostly dispute
    bot_claim = 40
    support_p[bot_claim] = 0.15
    profile[bot_claim] = "steady"

    def sample_t(c):
        u = rng.random()
        return {"steady": u, "emerging": 0.7 + 0.3 * u ** 0.5, "fading": 0.45 * u}[profile[c]]

    def text_for(claims):
        w = []
        for c, s in claims:
            w += list(rng.choice(claim_words[c], size=rng.integers(3, 5), replace=False))
            if s != "mention":
                w += list(rng.choice(sup_words if s == "support" else dis_words, size=rng.integers(1, 3)))
        w += list(rng.choice(topical, size=2, p=tw)) + list(rng.choice(filler, size=8))
        rng.shuffle(w)
        return w

    posts, last = [], {}
    for pid in range(n_posts):
        a = f"u{rng.choice(n_authors, p=act)}"
        reach = float(np.log1p(rng.pareto(1.5) * 5))
        if rng.random() < noise_frac:
            posts.append(Post(pid, a, rng.random(), [], list(rng.choice(topical, 3, p=tw)) + list(rng.choice(filler, 10)), reach))
            continue
        cs = []
        k = 1 if rng.random() < 0.8 else 2
        while len(cs) < k:
            c = last[a] if (a in last and rng.random() < 0.3) else int(rng.choice(n_claims, p=pop))
            if any(c == x for x, _ in cs):
                continue
            r = rng.random()
            s = "mention" if r < 0.15 else ("support" if rng.random() < support_p[c] else "dispute")
            cs.append((c, s))
        last[a] = cs[0][0]
        posts.append(Post(pid, a, sample_t(cs[0][0]), cs, text_for(cs), reach))

    base = text_for([(bot_claim, "support")])
    for j in range(bot_posts):
        w = list(base)
        w[rng.integers(len(w))] = str(rng.choice(filler))       # near-duplicate spam
        posts.append(Post(len(posts), f"bot{j % n_bots}", rng.random(), [(bot_claim, "support")], w, 0.1, True))

    order = rng.permutation(len(posts))
    posts = [posts[i] for i in order]
    for i, p in enumerate(posts):
        p.pid = i
    return World(posts, n_claims, claim_words, support_p, profile, bot_claim, confusable)


# ---------------------------------------------------------------- ground truth
def truth_author_stance(w: World) -> list[dict]:
    """Per claim: author -> latest stance, in time order (same rule the ledger uses)."""
    out = [dict() for _ in range(w.n_claims)]
    for p in sorted(w.posts, key=lambda p: p.t):
        for c, s in p.claims:
            if s != "mention" or p.author not in out[c]:
                out[c][p.author] = s
    return out


def support_share(author_stance: dict) -> float | None:
    s = sum(1 for v in author_stance.values() if v == "support")
    d = sum(1 for v in author_stance.values() if v == "dispute")
    return None if s + d == 0 else s / (s + d)


def truth_emerging(w: World, min_authors: int = 5) -> set[int]:
    ats = truth_author_stance(w)
    return {c for c in range(w.n_claims) if w.profile[c] == "emerging" and len(ats[c]) >= min_authors}
