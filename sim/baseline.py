"""RAG baseline: BM25 top-k over posts, read by a *perfect* reader.

This is deliberately generous to RAG: the reader is assumed to correctly
identify which retrieved posts are about the asked-about claim and their stance,
and to deduplicate by author.  Any error left is purely the selection step.
(Lexical BM25 stands in for the selection step; dense retrieval changes which
k posts are chosen, not the fact that only k are.)
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

from sim.world import World


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.N = len(docs)
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = self.len.mean()
        self.k1, self.b = k1, b
        self.inv: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.inv[t].append((i, f))

    def top(self, query: list[str], k: int) -> list[int]:
        s = np.zeros(self.N)
        for t in set(query):
            post = self.inv.get(t, [])
            if not post:
                continue
            idf = math.log(1 + (self.N - len(post) + 0.5) / (len(post) + 0.5))
            ids = np.array([i for i, _ in post])
            f = np.array([f for _, f in post], dtype=float)
            s[ids] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[ids] / self.avg))
        k = min(k, self.N)
        idx = np.argpartition(-s, k - 1)[:k]
        return list(idx[np.argsort(-s[idx])])


def reader_stance(w: World, pids: list[int], c: int, dedup_authors: bool = True) -> float | None:
    """Perfect reader: support share for claim c among retrieved posts."""
    posts = sorted((w.posts[i] for i in pids), key=lambda p: p.t)
    if dedup_authors:
        st = {}
        for p in posts:
            for cc, s in p.claims:
                if cc == c and (s != "mention" or p.author not in st):
                    st[p.author] = s
        vals = list(st.values())
    else:
        vals = [s for p in posts for cc, s in p.claims if cc == c]
    sup, dis = vals.count("support"), vals.count("dispute")
    return None if sup + dis == 0 else sup / (sup + dis)


def claims_seen(w: World, pids: list[int]) -> Counter:
    """claim -> distinct authors seen in the retrieved set."""
    a = defaultdict(set)
    for i in pids:
        for c, _ in w.posts[i].claims:
            a[c].add(w.posts[i].author)
    return Counter({c: len(v) for c, v in a.items()})
