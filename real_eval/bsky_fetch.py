"""Fetch every searchable public Bluesky post on a topic (X-like social media, real authors,
timestamps and likes; not a benchmark, so no memorised answers).

Authors are pseudonymised (salted hash) at fetch time. Raw posts stay in the given output
directory and are never committed to the repo; only aggregates and the paraphrased
ledger are.

Usage: python -m real_eval.bsky_fetch "seed oils" OUT_DIR [--max 5000]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def fetch(q: str, max_posts: int, pause: float = 1.0):
    salt = secrets.token_hex(8)
    out, until, seen = [], None, set()
    while len(out) < max_posts:
        # page backwards in time with `until` (cursor paging is refused for unauthenticated clients)
        params = {"q": q, "limit": 100, "sort": "latest"}
        if until:
            params["until"] = until
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "research-client/0.1"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                break
            except Exception:  # noqa: BLE001 - retry with backoff
                time.sleep(2 ** (attempt + 1))
        else:
            break
        posts = d.get("posts", [])
        new = [p for p in posts if p["uri"] not in seen]
        if not new:
            break
        for p in posts:
            if p["uri"] in seen:
                continue
            seen.add(p["uri"])
            rec = p.get("record", {})
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            out.append({
                "id": len(out),
                "author": hashlib.sha256((salt + p["author"]["did"]).encode()).hexdigest()[:12],
                "created": rec.get("createdAt", ""),
                "likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0),
                "reply": "reply" in rec,
                "text": text,
            })
        oldest = min(p.get("record", {}).get("createdAt", "") or p["indexedAt"] for p in posts)
        if oldest == until:
            break
        until = oldest
        time.sleep(pause)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("out", type=Path)
    ap.add_argument("--max", type=int, default=5000)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    posts = fetch(a.query, a.max)
    posts.sort(key=lambda p: p["created"])
    for i, p in enumerate(posts):
        p["id"] = i
    (a.out / "posts.json").write_text(json.dumps(posts))
    print(len(posts), posts[0]["created"][:10] if posts else "", posts[-1]["created"][:10] if posts else "",
          len({p["author"] for p in posts}), "authors")


if __name__ == "__main__":
    main()
