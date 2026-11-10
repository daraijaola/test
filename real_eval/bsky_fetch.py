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
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _canon(ts: str) -> str | None:
    """createdAt strings vary (offsets, missing zone); the API's `until` wants canonical UTC."""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _step_back(ts: str, seconds: int) -> str:
    d = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) - timedelta(seconds=seconds)
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

API = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def fetch(q: str, max_posts: int, pause: float = 1.0, resume: list | None = None, salt: str | None = None):
    salt = salt or secrets.token_hex(8)
    out, until, seen, stalls = list(resume or []), None, set(), 0
    if out:      # continue backwards from the oldest post already fetched
        until = min(c for c in (_canon(p["created"]) for p in out) if c)
        seen = {p.get("uri") for p in out if p.get("uri")}
    while len(out) < max_posts:
        # page backwards in time with `until` (cursor paging is refused for unauthenticated clients)
        params = {"q": q, "limit": 100, "sort": "latest"}
        if until:
            params["until"] = until
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "research-client/0.1"})
        for attempt in range(8):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                break
            except Exception as e:  # noqa: BLE001 - retry with backoff
                print(f"fetch retry {attempt + 1}: {e}", flush=True)
                time.sleep(min(60, 2 ** (attempt + 1)))
        else:
            print("giving up after repeated failures", flush=True)
            break
        posts = d.get("posts", [])
        new = [p for p in posts if p["uri"] not in seen]
        if not new:
            stalls += 1
            if stalls > 5 or not until:
                break
            until = _step_back(until, 60 * stalls)       # step past a stuck timestamp
            continue
        stalls = 0
        for p in posts:
            if p["uri"] in seen:
                continue
            seen.add(p["uri"])
            rec = p.get("record", {})
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            out.append({
                "id": len(out), "uri": p["uri"],
                "author": hashlib.sha256((salt + p["author"]["did"]).encode()).hexdigest()[:12],
                "created": rec.get("createdAt", ""),
                "likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0),
                "reply": "reply" in rec,
                "text": text,
            })
        stamps = [_canon(p.get("record", {}).get("createdAt", "") or p["indexedAt"]) for p in posts]
        stamps = [t for t in stamps if t]
        if not stamps:
            break
        oldest = min(stamps)
        until = oldest if oldest != until else _step_back(oldest, 1)
        time.sleep(pause)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("out", type=Path)
    ap.add_argument("--max", type=int, default=5000)
    ap.add_argument("--resume", action="store_true", help="continue from OUT/posts.json, older than its oldest post")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    prev = json.loads((a.out / "posts.json").read_text()) if a.resume and (a.out / "posts.json").exists() else None
    salt_file = a.out / ".salt"          # one salt per corpus, so pseudonyms stay stable across resumes
    if prev and not salt_file.exists():
        raise SystemExit("cannot resume: the original salt was not saved (pseudonyms would not match)")
    salt = salt_file.read_text() if salt_file.exists() else secrets.token_hex(8)
    salt_file.write_text(salt)
    posts = fetch(a.query, a.max, resume=prev, salt=salt)
    posts.sort(key=lambda p: p["created"])
    for i, p in enumerate(posts):
        p["id"] = i
    (a.out / "posts.json").write_text(json.dumps(posts))
    print(len(posts), posts[0]["created"][:10] if posts else "", posts[-1]["created"][:10] if posts else "",
          len({p["author"] for p in posts}), "authors")


if __name__ == "__main__":
    main()
