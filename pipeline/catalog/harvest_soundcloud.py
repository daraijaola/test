#!/opt/av/bin/python
"""Harvest remix-beat candidates from SoundCloud search (via the yt-dlp library).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial).
This script ONLY harvests: it builds a large, diverse pool of candidate beats with
a 40 s audio excerpt from the musical body of each track plus metadata.  Scoring
(tempo / key / CLAP vibe) happens later in other pipeline stages.

How it works
------------
1. Search.  ~75 hand-written queries grouped into genre categories (Juice WRLD /
   Nick Mira type beats, emo + guitar trap, sad R&B, afro-R&B / afrobeats,
   French pop urbaine, pop-punk / acoustic, lo-fi, piano, cinematic, drill,
   amapiano, dancehall-lite, synth-pop, boom-bap ...).  Each query is run as
   ``scsearch<N>:<query>`` with flat extraction (= ``yt-dlp --flat-playlist -J``,
   done in-process through the yt_dlp Python API so no interpreter is spawned
   per call).  Results are cached as JSON per query, so re-runs are cheap and
   deterministic.
2. Plan.  Results are interleaved round-robin by search rank across queries
   (core Juice-style queries get weight 2), de-duplicated (track id and
   normalized title+duration for re-uploads), filtered (90 s <= duration <= 8 min;
   no slowed / sped-up / nightcore / 8D / a cappella / DJ-mix / podcast uploads;
   no Juice WRLD vocal uploads; no Dadju - "Reine" itself) and capped per uploader
   so prolific type-beat channels cannot flood the pool.  Wherever a run stops,
   the pool is balanced across genres.
3. Fetch.  For each planned track the stream formats are resolved (= ``yt-dlp -g``;
   only the HLS AAC transcodings are requested to keep SoundCloud API calls low,
   with a fallback to all formats).  The excerpt start is put ~30 % into the
   track (snapped to an HLS segment boundary); only the init segment + the ~5
   media segments covering the excerpt are downloaded (a few hundred kB), and
   ffmpeg re-encodes exactly 40 s to MP3 128 kbps / 44.1 kHz.  Progressive
   (HTTP) formats are cut with ffmpeg -ss/-t on the remote URL (HTTP range).
   Snipped (30 s "preview only") tracks keep their preview and are flagged
   full_audio_available=false.  Each clip is validated with ffprobe (>= 20 s)
   or deleted.
4. Records.  One JSON object per clip is appended to candidates.jsonl
   (contract keys only).  The signed stream URLs expire, so full_audio_url is
   null; the full track can be re-resolved later from page_url with yt-dlp.
   BPM / key are parsed from the title (then SoundCloud tags, then the
   description) when present.

Resumable: ids already in candidates.jsonl / rejects.jsonl are skipped (only
permanent failures are written to rejects.jsonl; network errors / HTTP 429 are
retried on the next run).  --max-seconds stops submitting work after a time
budget.  Run repeatedly until --target is reached or the plan is exhausted.

CPU-light by design: no audio analysis, ffmpeg runs single-threaded under nice.
Politeness: SoundCloud API track resolutions are limited to --rps per second,
HTTP 429 triggers a global back-off, all requests retry with exponential back-off.

Usage
-----
  /opt/av/bin/python harvest_soundcloud.py --target 2000 --max-seconds 500
  /opt/av/bin/python harvest_soundcloud.py --search-only     # run/cached searches only
  /opt/av/bin/python harvest_soundcloud.py --dry-run         # searches + print plan summary
  /opt/av/bin/python harvest_soundcloud.py --stats           # summarize the output JSONL
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter, defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import urljoin

import requests
import yt_dlp
from yt_dlp.extractor.soundcloud import SoundcloudBaseIE

# yt-dlp sends one HEAD request per track to probe the extension of the
# "original" artwork.  We never use artwork, so drop that size: a 100-result
# search then costs 1 API call instead of ~100 extra requests.
SoundcloudBaseIE._ARTWORK_MAP = {k: v for k, v in SoundcloudBaseIE._ARTWORK_MAP.items() if k != "original"}

# --------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------
SOURCE = "soundcloud"
ROOT = "/home/user/test"
OUT_DIR = os.path.join(ROOT, "work", "catalog", SOURCE)
CLIP_DIR = os.path.join(OUT_DIR, "clips")
TMP_DIR = os.path.join(OUT_DIR, "tmp")
SEARCH_DIR = os.path.join(OUT_DIR, "search_cache")
JSONL = os.path.join(OUT_DIR, "candidates.jsonl")
REJECTS = os.path.join(OUT_DIR, "rejects.jsonl")

MIN_FULL_DURATION = 90.0    # s; task: skip tracks shorter than 90 s
MAX_FULL_DURATION = 480.0   # s; task: skip tracks longer than 8 min
CLIP_LEN = 40.0             # s; excerpt length (contract: 30-45 s)
CLIP_START_FRAC = 0.30      # excerpt starts ~30 % into the track (skip intros)
MIN_CLIP_DURATION = 20.0    # s; contract: validate clip >= 20 s
MAX_TAGS_FROM_SC = 20       # keep at most this many SoundCloud tags per record

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Uploads we never want as beat candidates (tempo/pitch-warped, no beat, mixes).
BAD_VERSION_RE = re.compile(
    r"slowed|sped[\s-]*up|speed[\s-]*up|nightcore|\b8d\b|daycore|bass[\s-]*boost|"
    r"a[\s-]?cappella|acapella|accapella|\bvocals? only\b|\bstems?\b|"
    r"\bsnippet\b|\bpodcast\b|\bepisode\b|\bmixtape\b|full album|\bdj[\s-]*(mix|set)\b|"
    r"\blive[\s-]*set\b|\bmegamix\b|\bmashup\b|\bcompilation\b|\btutorial\b|"
    r"\b\d+\s*(hour|hr)s?\b|\bmeditation\b|\basmr\b|white noise|rain sounds",
    re.I,
)
# Metadata hints that a track is an instrumental (title / SoundCloud tags).
INSTR_RE = re.compile(
    r"type[\s-]?beats?|instrumental|\binstru\b|\binst\b|\bbeats?\b|\briddim\b|"
    r"backing track|karaoke|free for profit|\[free\]|\(free\)|\bfree\s+\w+\s+beat|\bbeat tape\b",
    re.I,
)
# Metadata hints that a track is a vocal song.
VOCAL_RE = re.compile(
    r"\b(feat\.?|ft\.?|featuring)\s|official (audio|video|music video)|music video|"
    r"\bcover\b|\(remix\)|\bremix\b|\bprod\.?\s+by\b|\(prod\b|\[prod\b",
    re.I,
)
JUICE_RE = re.compile(r"juice\s*wrld|juicewrld|juice\s*world", re.I)
# A Juice WRLD *instrumental / type beat* is fine; a Juice WRLD vocal upload is not.
BEATISH_RE = re.compile(r"type[\s-]?beat|instrumental|\binstru\b|\binst\b|\bbeat\b|\bkaraoke\b|remake|\bflp\b", re.I)

# BPM: "140 bpm", "140bpm", "BPM: 140", "bpm 140"
BPM_RES = [
    re.compile(r"(?<![\d.])(\d{2,3}(?:[.,]\d{1,2})?)\s*-?\s*bpm\b", re.I),
    re.compile(r"\bbpm\s*[:=\-@|]?\s*(\d{2,3}(?:[.,]\d{1,2})?)(?![\d])", re.I),
]
_NOTE = r"(?P<note>[A-G])(?P<acc>#|♯|♭|[\s-]?sharp|[\s-]?flat|b)?"
# Full mode words: "C# minor", "Ab Major", "F#min", "Gmaj", "A mineur", "B-flat major"
KEY_FULL_RE = re.compile(
    rf"(?<![A-Za-z0-9#]){_NOTE}[\s-]*(?P<mode>minor|major|mineur|majeur|min|maj|moll|dur)(?![A-Za-z])", re.I
)
# Short "m" form: "C#m", "Am", "Ebm" -- only trusted with bpm/key context nearby.
KEY_SHORT_RE = re.compile(rf"(?<![A-Za-z0-9#']){_NOTE}(?P<mode>m)(?![A-Za-z0-9'])")
# "Key: C#m", "key - A minor", "key Eb", "KEY : A-sharp minor"
KEY_LABEL_RE = re.compile(
    rf"\bkey\s*[:=\-|]?\s*{_NOTE}[\s-]*(?P<mode>minor|major|mineur|majeur|min|maj|m)?(?![A-Za-z0-9])", re.I
)

# --------------------------------------------------------------------------
# Query catalog: category -> list of (query, weight).  weight 2 = takes two
# results per round-robin round (core "Juice-style" territory).
# --------------------------------------------------------------------------
CATEGORIES: dict[str, list[tuple[str, int]]] = {
    "juice_type": [
        ("juice wrld type beat", 2), ("juice wrld type beat free", 2), ("nick mira type beat", 2),
        ("juice wrld guitar type beat", 2), ("juice wrld instrumental", 1),
        ("juice wrld x the kid laroi type beat", 1), ("emo rap beat 2019", 1),
        ("lucid dreams type beat", 1), ("taz taylor type beat", 1), ("internet money type beat", 1),
    ],
    "emo_guitar_trap": [
        ("emo guitar type beat", 2), ("sad guitar trap beat", 2), ("melodic trap instrumental", 2),
        ("guitar trap beat", 1), ("xxxtentacion type beat guitar", 1), ("lil peep type beat", 1),
        ("trippie redd type beat", 1), ("the kid laroi type beat", 1), ("iann dior type beat", 1),
        ("lil tecca type beat", 1), ("lil skies type beat", 1), ("post malone type beat", 1),
        ("emotional rap instrumental", 1), ("sad trap instrumental", 1), ("lil uzi vert melodic type beat", 1),
    ],
    "sad_hiphop": [
        ("rod wave type beat", 1), ("polo g type beat", 1), ("lil tjay type beat", 1),
        ("pain type beat", 1), ("sad piano trap beat", 1), ("nba youngboy sad type beat", 1),
    ],
    "rnb": [
        ("rnb instrumental love", 1), ("sad rnb instrumental", 1), ("alternative rnb instrumental", 1),
        ("bryson tiller type beat", 1), ("6lack type beat", 1), ("the weeknd type beat", 1),
        ("chris brown type beat", 1), ("rnb guitar beat", 1), ("trapsoul type beat", 1),
    ],
    "afro": [
        ("afro rnb instrumental", 2), ("afrobeat instrumental free", 1), ("afro love type beat", 1),
        ("afro pop instrumental", 1), ("burna boy type beat", 1), ("wizkid type beat", 1),
        ("rema type beat", 1), ("ckay type beat", 1), ("omah lay type beat", 1),
        ("afro guitar type beat", 1), ("afroswing instrumental", 1),
    ],
    "french_urbaine": [
        ("dadju type beat", 2), ("tayc type beat", 2), ("aya nakamura type beat", 1),
        ("instru pop urbaine", 1), ("instrumental rnb francais", 1), ("gims type beat", 1),
        ("ninho type beat melancolique", 1), ("instru afro love", 1),
    ],
    "amapiano_dancehall": [
        ("amapiano instrumental", 1), ("dancehall instrumental chill", 1), ("kizomba instrumental", 1),
    ],
    "rock_acoustic": [
        ("pop punk type beat", 1), ("emo pop punk instrumental", 1), ("alt rock ballad instrumental", 1),
        ("acoustic guitar rap beat", 1), ("campfire guitar beat", 1), ("acoustic guitar instrumental sad", 1),
        ("machine gun kelly type beat", 1),
    ],
    "lofi_piano": [
        ("lofi hip hop instrumental", 1), ("lofi guitar beat", 1), ("piano ballad instrumental rap", 1),
        ("sad piano instrumental", 1),
    ],
    "cinematic_boombap": [
        ("cinematic hip hop beat", 1), ("orchestral hip hop instrumental", 1),
        ("boom bap melodic sample beat", 1), ("soul sample boom bap beat", 1),
    ],
    "drill_synth": [
        ("melodic drill instrumental", 1), ("uk drill melodic type beat", 1),
        ("synth pop instrumental", 1), ("synthwave type beat", 1),
    ],
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def norm(s: str) -> str:
    """Lower-case, strip accents and punctuation (for de-duplication)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def slug(q: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")[:60]
    return f"{base}_{hashlib.md5(q.encode()).hexdigest()[:6]}"


def safe_id(native_id: str) -> str:
    return f"{SOURCE}_{re.sub(r'[^A-Za-z0-9_-]+', '_', str(native_id))}"


def load_jsonl(path: str) -> list[dict]:
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # torn last line from a killed run
    return out


def ffprobe_duration(path: str) -> float | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def parse_bpm(text: str) -> float | None:
    for rx in BPM_RES:
        for m in rx.finditer(text or ""):
            v = float(m.group(1).replace(",", "."))
            if 50 <= v <= 220:
                return round(v, 2)
    return None


def _fmt_key(m: re.Match) -> str:
    note = m.group("note").upper()
    acc = re.sub(r"[\s-]+", "", m.group("acc") or "").lower()
    acc = {"#": "#", "♯": "#", "sharp": "#", "b": "b", "♭": "b", "flat": "b"}.get(acc, "")
    mode = (m.group("mode") or "").lower()
    if mode in ("m", "min", "minor", "mineur", "moll"):
        return f"{note}{acc} minor"
    if mode in ("maj", "major", "majeur", "dur"):
        return f"{note}{acc} major"
    return f"{note}{acc}"


def parse_key(text: str) -> str | None:
    """Musical key from free text; conservative to avoid false positives."""
    text = text or ""
    m = KEY_LABEL_RE.search(text)
    if m:
        return _fmt_key(m)
    m = KEY_FULL_RE.search(text)
    if m:
        return _fmt_key(m)
    if re.search(r"bpm|\bkey\b", text, re.I):  # short "C#m" only with context
        for m in KEY_SHORT_RE.finditer(text):
            before = text[:m.start()].rstrip()
            after = text[m.end():].lstrip()
            # must be delimited like a label: "| Am |", "(140bpm, C#m)", "150 BPM Am", "Am 140 bpm"
            if (not before or before[-1] in "|([,/-–:" or re.search(r"bpm$", before, re.I)) and \
                    (not after or after[0] in "|)],/-–" or re.match(r"\d{2,3}\s*bpm", after, re.I)):
                return _fmt_key(m)
    return None


class RateLimiter:
    """Sliding-window limiter shared by all worker threads."""

    def __init__(self, max_calls: int, period: float):
        self.max_calls, self.period = max_calls, period
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()
        self.pause_until = 0.0  # global back-off after HTTP 429

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                if now < self.pause_until:
                    delay = self.pause_until - now
                else:
                    while self.calls and now - self.calls[0] > self.period:
                        self.calls.popleft()
                    if len(self.calls) < self.max_calls:
                        self.calls.append(now)
                        return
                    delay = self.period - (now - self.calls[0]) + 0.01
            time.sleep(max(delay, 0.01))

    def backoff(self, seconds: float) -> None:
        with self.lock:
            self.pause_until = max(self.pause_until, time.monotonic() + seconds)


# --------------------------------------------------------------------------
# yt-dlp plumbing (one YoutubeDL per thread; the extractor is not thread-safe)
# --------------------------------------------------------------------------
_tls = threading.local()


class _QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def ydl(formats: list[str] | None = None) -> yt_dlp.YoutubeDL:
    key = "ydl_" + ("default" if not formats else ",".join(formats))
    inst = getattr(_tls, key, None)
    if inst is None:
        opts = {
            "quiet": True, "no_warnings": True, "skip_download": True, "logger": _QuietLogger(),
            "extract_flat": "in_playlist", "socket_timeout": 20, "retries": 3,
            "extractor_retries": 3,
        }
        if formats:
            opts["extractor_args"] = {"soundcloud": {"formats": formats}}
        inst = yt_dlp.YoutubeDL(opts)
        setattr(_tls, key, inst)
    return inst


def http() -> requests.Session:
    s = getattr(_tls, "http", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _tls.http = s
    return s


def http_get(url: str, timeout: float = 25, tries: int = 4) -> bytes:
    last = None
    for i in range(tries):
        try:
            r = http().get(url, timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code in (401, 403, 404, 410):
                break
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * 2 ** i)
    raise TransientError(f"GET failed: {last}")


def is_rate_limited(msg: str) -> bool:
    """True for HTTP 429 (do not match track ids that merely contain "429")."""
    return bool(re.search(r"HTTP Error 429|Too Many Requests|status(?: code)?:? 429\b", msg, re.I))


class TransientError(Exception):
    """Network-ish failure: do not record a reject; retry on a later run."""


class PermanentError(Exception):
    """Track cannot be used (no formats, geo-blocked, ...): record in rejects."""


# --------------------------------------------------------------------------
# 1. Search
# --------------------------------------------------------------------------
def search(query: str, n: int, refresh: bool = False) -> list[dict]:
    """scsearch<n>:<query> flat results, cached as JSON."""
    path = os.path.join(SEARCH_DIR, f"{slug(query)}__{n}.json")
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["entries"]
    info = None
    for i in range(4):
        try:
            info = ydl().extract_info(f"scsearch{n}:{query}", download=False)
            break
        except Exception as e:  # noqa: BLE001 - yt-dlp raises DownloadError for everything
            wait_s = 30 * (i + 1) if is_rate_limited(str(e)) else 3 * (i + 1)
            log(f"  search retry {i+1} for {query!r}: {str(e)[:120]} (sleep {wait_s}s)")
            time.sleep(wait_s)
    if info is None:
        raise TransientError(f"search failed: {query}")
    entries = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        entries.append({
            "id": str(e["id"]),
            "url": e.get("url"),
            "webpage_url": e.get("webpage_url"),
            "title": e.get("title") or "",
            "uploader": e.get("uploader") or "",
            "uploader_id": str(e.get("uploader_id") or ""),
            "duration": e.get("duration"),
            "license": e.get("license"),
            "genres": e.get("genres") or [],
            "tags": e.get("tags") or [],
            "description": (e.get("description") or "")[:1500],
            "timestamp": e.get("timestamp"),
            "view_count": e.get("view_count"),
            "like_count": e.get("like_count"),
        })
    os.makedirs(SEARCH_DIR, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"query": query, "n": n, "fetched": int(time.time()), "entries": entries}, fh)
    os.replace(tmp, path)
    return entries


def run_searches(n: int, refresh: bool, deadline: float) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for cat, qs in CATEGORIES.items():
        for q, _w in qs:
            cached = os.path.exists(os.path.join(SEARCH_DIR, f"{slug(q)}__{n}.json"))
            if not cached and time.time() > deadline:
                log(f"  time budget hit during searches; {q!r} postponed")
                continue
            try:
                results[q] = search(q, n, refresh)
            except TransientError as e:
                log(f"  {e}")
                continue
            if not cached:
                log(f"  searched {q!r}: {len(results[q])} results")
                time.sleep(1.0)  # be polite between uncached searches
    return results


# --------------------------------------------------------------------------
# 2. Plan
# --------------------------------------------------------------------------
def skip_reason(e: dict) -> str | None:
    dur = e.get("duration")
    if not dur:
        return "no_duration"
    if dur < MIN_FULL_DURATION:
        return "too_short"
    if dur > MAX_FULL_DURATION:
        return "too_long"
    title, up = e.get("title") or "", e.get("uploader") or ""
    if BAD_VERSION_RE.search(title):
        return "bad_version"
    if JUICE_RE.fullmatch(up.strip()) or (JUICE_RE.search(title + " " + up) and not BEATISH_RE.search(title)):
        return "juice_vocal"  # official Juice WRLD uploads / leaks carry his vocals
    if re.search(r"\breine\b", title, re.I) and re.search(r"dadju", title + " " + up, re.I):
        return "reine_original"
    return None


def build_plan(results: dict[str, list[dict]], exclude: set[str], uploader_cap: int,
               prior_uploaders: Counter, prior_keys: set) -> tuple[list[dict], Counter]:
    """Round-robin by rank across queries (weighted), dedup, filter, cap."""
    queues = []
    for cat, qs in CATEGORIES.items():
        for q, w in qs:
            if q in results:
                queues.append((cat, q, w, deque(results[q])))
    plan, seen, reasons = [], set(), Counter()
    per_up = Counter(prior_uploaders)
    keys = set(prior_keys)
    while any(qd for *_, qd in queues):
        for cat, q, w, qd in queues:
            for _ in range(w):
                if not qd:
                    break
                e = qd.popleft()
                tid = e["id"]
                if tid in seen:
                    continue
                seen.add(tid)
                if f"{SOURCE}:{tid}" in exclude:
                    reasons["already_done"] += 1
                    continue
                r = skip_reason(e)
                if r:
                    reasons[r] += 1
                    continue
                k = (norm(e["title"]), round((e.get("duration") or 0) / 2))
                if k in keys:
                    reasons["dup_title"] += 1
                    continue
                up = e.get("uploader_id") or e.get("uploader")
                if per_up[up] >= uploader_cap:
                    reasons["uploader_cap"] += 1
                    continue
                keys.add(k)
                per_up[up] += 1
                plan.append({**e, "category": cat, "query": q})
    return plan, reasons


# --------------------------------------------------------------------------
# 3. Fetch one track
# --------------------------------------------------------------------------
FORMAT_PREF = ["hls_aac_160k", "http_mp3_128", "http_mp3", "hls_mp3_128", "hls_mp3",
               "hls_aac_96k", "hls_opus_64", "hls_opus"]


def pick_format(formats: list[dict]) -> dict | None:
    def rank(f):
        fid = f.get("format_id") or ""
        prev = "preview" in fid
        base = fid.replace("_preview", "")
        try:
            pos = FORMAT_PREF.index(base)
        except ValueError:
            pos = len(FORMAT_PREF)
        if fid == "download":  # original upload (rarely available anonymously)
            pos = len(FORMAT_PREF) + 1
        return (prev, pos)
    fs = [f for f in formats if f.get("url")]
    return sorted(fs, key=rank)[0] if fs else None


def resolve(e: dict, limiter: RateLimiter) -> dict:
    """Full extraction of one track (= yt-dlp -J / -g)."""
    url = e.get("url") or e.get("webpage_url")
    last = None
    for fmts in (["hls_aac"], None):  # cheap first, then every transcoding
        for attempt in range(3):
            limiter.acquire()
            try:
                info = ydl(fmts).extract_info(url, download=False, process=False)
            except Exception as ex:  # noqa: BLE001
                msg = str(ex)
                last = msg
                if is_rate_limited(msg):
                    log(f"  HTTP 429 from SoundCloud; global back-off 60 s")
                    limiter.backoff(60)
                    continue
                if re.search(r"geo|not available|HTTP Error (404|410)|DRM|private|blocked|removed", msg, re.I):
                    raise PermanentError(msg[:200])
                time.sleep(2 * (attempt + 1))
                continue
            if info.get("formats"):
                return info
            break  # no formats with this filter: try the next filter
    if last is None:
        raise PermanentError("no playable formats")
    raise TransientError(f"resolve failed: {str(last)[:200]}")


def parse_m3u8(text: str, base: str) -> tuple[list[str], list[tuple[float, str]], bool]:
    """Return (header lines incl. EXT-X-MAP with absolute URI, [(dur, url)], encrypted)."""
    header, segs, dur = [], [], None
    encrypted = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                line = line.replace(m.group(1), urljoin(base, m.group(1)))
            header.append(line)
        elif line.startswith("#EXT-X-KEY:"):
            encrypted = encrypted or "METHOD=NONE" not in line
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                line = line.replace(m.group(1), urljoin(base, m.group(1)))
            header.append(line)
        elif line.startswith("#EXTINF:"):
            dur = float(line.split(":", 1)[1].split(",")[0])
        elif line.startswith("#"):
            if line.startswith(("#EXT-X-VERSION", "#EXT-X-TARGETDURATION")):
                header.append(line)
        else:
            segs.append((dur or 0.0, urljoin(base, line)))
            dur = None
    return header, segs, encrypted


def ffmpeg_cut(inp: str, dest: str, ss: float, t: float, pre_input: list[str] | None = None) -> None:
    """Cut [ss, ss+t] of inp (file or URL) to MP3 128k / 44.1 kHz."""
    cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-threads", "1", "-y"]
    cmd += pre_input or []
    if ss > 0.01:
        cmd += ["-ss", f"{ss:.3f}"]
    cmd += ["-t", f"{t:.3f}", "-i", inp, "-vn", "-map", "0:a:0", "-ar", "44100",
            "-b:a", "128k", "-codec:a", "libmp3lame", "-threads", "1", dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise TransientError(f"ffmpeg failed: {r.stderr.strip()[-200:]}")


def choose_start(full_dur: float, preview: bool) -> float:
    if preview or full_dur <= CLIP_LEN + 5:
        return 0.0
    start = CLIP_START_FRAC * full_dur
    return max(0.0, min(start, full_dur - CLIP_LEN - 2.0))


def fetch_clip(fmt: dict, full_dur: float, preview: bool, dest: str) -> float:
    """Write the excerpt to dest; return the actual clip start (s, in the track)."""
    url, proto = fmt["url"], fmt.get("protocol") or ""
    os.makedirs(TMP_DIR, exist_ok=True)
    want = choose_start(full_dur, preview)
    if "m3u8" not in proto:
        # Progressive file: HTTP range seek directly on the remote URL.
        ffmpeg_cut(url, dest, want, CLIP_LEN,
                   pre_input=["-user_agent", UA, "-reconnect", "1", "-reconnect_streamed", "1",
                              "-reconnect_delay_max", "5"])
        return round(want, 3)

    text = http_get(url).decode("utf-8", "replace")
    header, segs, encrypted = parse_m3u8(text, url)
    if not segs:
        raise PermanentError("empty HLS playlist")
    # Pick the segment containing `want`, then enough segments to cover CLIP_LEN.
    starts, acc = [], 0.0
    for d, _u in segs:
        starts.append(acc)
        acc += d
    # nearest segment boundary to `want` that still leaves room for a full excerpt
    fits = [i for i, s in enumerate(starts) if s + CLIP_LEN <= acc] or [0]
    i0 = min(fits, key=lambda i: abs(starts[i] - want))
    seg_start = starts[i0]
    # Prefer starting on the segment boundary unless that would clip the end.
    if seg_start + CLIP_LEN <= acc:
        offset = 0.0
    else:
        offset = want - seg_start
    chosen, covered = [], 0.0
    for d, u in segs[i0:]:
        chosen.append((d, u))
        covered += d
        if covered >= offset + CLIP_LEN + 0.5:
            break
    clip_start = seg_start + offset

    tmp_base = os.path.join(TMP_DIR, os.path.basename(dest)[:-4])
    if encrypted:
        # Rare: AES-encrypted HLS -> let ffmpeg read a trimmed local playlist.
        m3u = tmp_base + ".m3u8"
        with open(m3u, "w") as fh:
            fh.write("#EXTM3U\n" + "\n".join(header) + "\n#EXT-X-MEDIA-SEQUENCE:0\n")
            for d, u in chosen:
                fh.write(f"#EXTINF:{d:.6f},\n{u}\n")
            fh.write("#EXT-X-ENDLIST\n")
        try:
            ffmpeg_cut(m3u, dest, offset, CLIP_LEN,
                       pre_input=["-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                                  "-allowed_extensions", "ALL"])
        finally:
            _rm(m3u)
        return round(clip_start, 3)

    # Plain HLS (fMP4 or TS): concatenating [init] + segments is a valid stream.
    init_url = None
    for h in header:
        if h.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', h)
            init_url = m.group(1) if m else None
    ext = ".mp4" if init_url or ".m4s" in chosen[0][1] or ".mp4" in chosen[0][1] else ".ts"
    if ".mp3" in chosen[0][1]:
        ext = ".mp3"
    part = tmp_base + ext
    try:
        with open(part, "wb") as fh:
            if init_url:
                fh.write(http_get(init_url))
            for _d, u in chosen:
                fh.write(http_get(u))
        ffmpeg_cut(part, dest, offset, CLIP_LEN)
    finally:
        _rm(part)
    return round(clip_start, 3)


def _rm(p: str) -> None:
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


def instrumental_meta(title: str, tags: list[str], genres: list[str]) -> bool | None:
    tag_txt = " ".join(tags + genres)
    if INSTR_RE.search(title) or re.search(r"type ?beat|instrumental|\bbeats?\b|\binstru\b", tag_txt, re.I):
        return True
    if VOCAL_RE.search(title):
        return False
    return None


def parse_meta(title: str, sc_tags: list[str], desc: str):
    """(bpm, bpm_src, key, key_src): title first, then SoundCloud tags, then description."""
    bpm, bpm_src = None, None
    key, key_src = None, None
    for src, text in (("title", title), ("tags", " | ".join(sc_tags)), ("description", desc)):
        if bpm is None and (v := parse_bpm(text)) is not None:
            bpm, bpm_src = v, src
        if key is None and (k := parse_key(text)) is not None:
            key, key_src = k, src
    return bpm, bpm_src, key, key_src


def reparse_meta() -> None:
    """Recompute bpm_meta / key_meta of existing records from the cached search
    metadata (no network), e.g. after improving the parsers.  Rewrites the JSONL."""
    import glob
    ents = {}
    for f in glob.glob(os.path.join(SEARCH_DIR, "*.json")):
        with open(f, encoding="utf-8") as fh:
            for e in json.load(fh)["entries"]:
                ents.setdefault(e["id"], e)
    recs = load_jsonl(JSONL)
    changed = 0
    for r in recs:
        e = ents.get(r["id"].split(":", 1)[1], {})
        sc_tags = [str(t).strip().lower() for t in (e.get("tags") or []) if str(t).strip()]
        bpm, bpm_src, key, key_src = parse_meta(r["title"], sc_tags, e.get("description") or "")
        tags = [t for t in r["tags"] if not t.startswith(("bpm_src:", "key_src:"))]
        if bpm is not None:
            tags.append(f"bpm_src:{bpm_src}")
        if key is not None:
            tags.append(f"key_src:{key_src}")
        if (bpm, key, tags) != (r["bpm_meta"], r["key_meta"], r["tags"]):
            changed += 1
        r.update(bpm_meta=bpm, key_meta=key, tags=tags)
    tmp = JSONL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, JSONL)
    log(f"reparsed bpm/key for {len(recs)} records ({changed} changed)")


def process(e: dict, limiter: RateLimiter) -> dict:
    tid = e["id"]
    sid = safe_id(tid)
    dest = os.path.join(CLIP_DIR, sid + ".mp3")
    info = resolve(e, limiter)
    fmt = pick_format(info.get("formats") or [])
    if not fmt:
        raise PermanentError("no playable formats")
    preview = "preview" in (fmt.get("format_id") or "")
    full_dur = float(info.get("duration") or e.get("duration") or 0)
    if not preview and not (MIN_FULL_DURATION <= full_dur <= MAX_FULL_DURATION):
        raise PermanentError(f"duration {full_dur}")
    _rm(dest)
    try:
        clip_start = fetch_clip(fmt, full_dur, preview, dest)
    except Exception:
        _rm(dest)
        raise
    d = ffprobe_duration(dest)
    if d is None or d < MIN_CLIP_DURATION:
        _rm(dest)
        if preview:
            raise PermanentError(f"preview clip too short ({d})")
        raise TransientError(f"clip invalid ({d})")

    title = info.get("title") or e.get("title") or ""
    artist = info.get("uploader") or e.get("uploader") or ""
    sc_tags = [str(t).strip().lower() for t in (info.get("tags") or e.get("tags") or []) if str(t).strip()]
    genres = [str(g).strip() for g in (info.get("genres") or e.get("genres") or []) if str(g).strip()]
    desc = info.get("description") or e.get("description") or ""

    bpm, bpm_src, key, key_src = parse_meta(title, sc_tags, desc)

    tags = [f"cat:{e['category']}"] + [f"genre:{g}" for g in genres]
    tags += sc_tags[:MAX_TAGS_FROM_SC]
    lic = info.get("license") or e.get("license")
    if lic:
        tags.append(f"license:{lic}")
    if bpm is not None:
        tags.append(f"bpm_src:{bpm_src}")
    if key is not None:
        tags.append(f"key_src:{key_src}")
    ts = info.get("timestamp") or e.get("timestamp")
    if ts:
        tags.append("year:" + time.strftime("%Y", time.gmtime(ts)))
    plays = info.get("view_count") if info.get("view_count") is not None else e.get("view_count")
    likes = info.get("like_count") if info.get("like_count") is not None else e.get("like_count")
    if plays is not None:
        tags.append(f"plays:{plays}")
    if likes is not None:
        tags.append(f"likes:{likes}")
    tags.append(f"fmt:{fmt.get('format_id')}")
    if preview:
        tags.append("sc:preview_only")
    tags.append("full:resolve_page_url_with_yt-dlp" if not preview else "full:unavailable_preview_only")

    return {
        "id": f"{SOURCE}:{tid}",
        "source": SOURCE,
        "title": title,
        "artist": artist,
        "page_url": info.get("webpage_url") or e.get("webpage_url"),
        "clip_path": dest,
        "clip_start_s": clip_start,
        "duration_full_s": round(full_dur, 3) if full_dur else None,
        "license": lic,
        "full_audio_url": None,  # signed HLS URLs expire within hours; re-resolve from page_url
        "full_audio_available": not preview,
        "bpm_meta": bpm,
        "key_meta": key,
        "tags": tags,
        "is_instrumental_meta": instrumental_meta(title, sc_tags, genres),
        "query": f"scsearch{e.get('_n', 100)}:{e['query']}",
        "is_reference": False,
    }


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def print_stats() -> None:
    recs = load_jsonl(JSONL)
    rej = load_jsonl(REJECTS)
    print(f"records: {len(recs)}   rejects: {len(rej)}")
    cats = Counter(next((t[4:] for t in r["tags"] if t.startswith("cat:")), "?") for r in recs)
    print("by category:", dict(cats.most_common()))
    print("instrumental_meta:", dict(Counter(str(r["is_instrumental_meta"]) for r in recs)))
    print("full_audio_available:", dict(Counter(str(r["full_audio_available"]) for r in recs)))
    print("license:", dict(Counter(str(r["license"]) for r in recs).most_common(8)))
    print("bpm_meta present:", sum(r["bpm_meta"] is not None for r in recs),
          " key_meta present:", sum(r["key_meta"] is not None for r in recs))
    print("queries:", len({r["query"] for r in recs}))
    print("by query:", dict(Counter(r["query"] for r in recs).most_common()))
    print("reject reasons:", dict(Counter(r.get("reason", "?")[:40] for r in rej).most_common(10)))
    size = sum(os.path.getsize(r["clip_path"]) for r in recs if os.path.exists(r["clip_path"]))
    missing = sum(not os.path.exists(r["clip_path"]) for r in recs)
    print(f"clip bytes: {size/1e6:.1f} MB   missing clips: {missing}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", type=int, default=2000, help="number of candidates to reach")
    ap.add_argument("--max-seconds", type=float, default=500, help="stop submitting work after this")
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads (<= 8)")
    ap.add_argument("--per-query", type=int, default=100, help="N in scsearchN:<query>")
    ap.add_argument("--uploader-cap", type=int, default=12, help="max candidates per uploader")
    ap.add_argument("--rps", type=float, default=2.0, help="SoundCloud track resolutions per second")
    ap.add_argument("--refresh-search", action="store_true", help="ignore the search cache")
    ap.add_argument("--search-only", action="store_true", help="only run / cache the searches")
    ap.add_argument("--dry-run", action="store_true", help="searches + plan summary, no downloads")
    ap.add_argument("--stats", action="store_true", help="only print stats of the output")
    ap.add_argument("--reparse-meta", action="store_true",
                    help="recompute bpm/key of existing records from cached metadata (offline)")
    args = ap.parse_args()

    if args.stats:
        print_stats()
        return 0
    if args.reparse_meta:
        reparse_meta()
        return 0
    try:
        os.nice(5)
    except OSError:
        pass
    t0 = time.time()
    deadline = t0 + args.max_seconds
    for d in (OUT_DIR, CLIP_DIR, TMP_DIR, SEARCH_DIR):
        os.makedirs(d, exist_ok=True)

    log(f"searches: {sum(len(v) for v in CATEGORIES.values())} queries x {args.per_query}")
    results = run_searches(args.per_query, args.refresh_search, deadline)
    log(f"search results: {sum(len(v) for v in results.values())} entries from {len(results)} queries")
    if args.search_only:
        return 0

    done = load_jsonl(JSONL)
    rejects = load_jsonl(REJECTS)
    done_ids = {r["id"] for r in done}
    exclude = done_ids | {r["id"] for r in rejects}
    prior_up = Counter()
    prior_keys = set()
    # Uploader cap / dedup also count already harvested records.
    by_id = {e["id"]: e for v in results.values() for e in v}
    for r in done:
        e = by_id.get(r["id"].split(":", 1)[1])
        prior_up[(e or {}).get("uploader_id") or r.get("artist")] += 1
        prior_keys.add((norm(r["title"]), round((r.get("duration_full_s") or 0) / 2)))
    plan, reasons = build_plan(results, exclude, args.uploader_cap, prior_up, prior_keys)
    for p in plan:
        p["_n"] = args.per_query
    need = max(0, args.target - len(done_ids))
    log(f"done: {len(done_ids)}  rejects: {len(rejects)}  plan: {len(plan)} eligible  need: {need}")
    log(f"plan filter reasons: {dict(reasons)}")
    if args.dry_run:
        print("plan by category:", dict(Counter(p["category"] for p in plan[:need])))
        for p in plan[:15]:
            print(f"  [{p['category']}] {p['title'][:70]!r} - {p['uploader'][:30]} ({p['duration']:.0f}s)")
        return 0
    if need == 0 or not plan:
        log("nothing to do")
        return 0

    limiter = RateLimiter(max_calls=max(1, int(args.rps * 5)), period=5.0)
    workers = max(1, min(8, args.workers))
    ok = perm = trans = 0
    it = iter(plan)
    inflight = {}
    with open(JSONL, "a", encoding="utf-8") as out, open(REJECTS, "a", encoding="utf-8") as rej, \
            ThreadPoolExecutor(max_workers=workers) as pool:
        def submit_more():
            while len(inflight) < workers * 2 and ok + len(inflight) < need and time.time() < deadline:
                e = next(it, None)
                if e is None:
                    return
                inflight[pool.submit(process, e, limiter)] = e

        submit_more()
        last_log = time.time()
        while inflight:
            finished, _ = wait(list(inflight), timeout=30, return_when=FIRST_COMPLETED)
            for f in finished:
                e = inflight.pop(f)
                try:
                    rec = f.result()
                except PermanentError as ex:
                    perm += 1
                    rej.write(json.dumps({"id": f"{SOURCE}:{e['id']}", "reason": str(ex)[:200],
                                          "title": e.get("title"), "t": int(time.time())}) + "\n")
                    rej.flush()
                except Exception as ex:  # TransientError + anything unexpected: retry next run
                    trans += 1
                    log(f"  transient {e['id']}: {str(ex)[:160]}")
                else:
                    ok += 1
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
            if time.time() - last_log > 30:
                last_log = time.time()
                el = time.time() - t0
                log(f"  ok {ok} (total {len(done_ids) + ok}/{args.target})  rejects {perm}  transient {trans}"
                    f"  inflight {len(inflight)}  {ok / max(el, 1):.2f}/s")
            submit_more()

    shutil.rmtree(TMP_DIR, ignore_errors=True)
    log(f"run finished: +{ok} ok, {perm} rejects, {trans} transient; total {len(done_ids) + ok}"
        f" in {time.time() - t0:.0f}s; plan remaining ~{max(0, len(plan) - ok - perm - trans)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
