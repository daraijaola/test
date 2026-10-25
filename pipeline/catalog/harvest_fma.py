#!/opt/av/bin/python
"""Harvest remix-beat candidates from the Free Music Archive (freemusicarchive.org).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial).
This script ONLY harvests: it builds a large, diverse pool of candidate beats with
a 40 s audio excerpt from the musical body of each track plus metadata.  Scoring
(tempo / key / CLAP vibe) happens later in other pipeline stages.

Why the live site and not the FMA research dataset
-------------------------------------------------
The dataset host (os.unige.ch: fma_metadata.zip / fma_large.zip / fma_full.zip)
is not reachable from this environment (proxy 502), and the Hugging Face mirrors
are parquet shards of ~0.5 GB that embed the audio (one row group = many tracks),
so per-track access is not possible without pulling hundreds of MB.  The live
freemusicarchive.org site, however, exposes for every track a direct, full-length
MP3 on its CDN (files.freemusicarchive.org, HTTP range supported), the license,
genres, the "Instrumental" / "AI generated" flags and play counts.  Track ids are
the same numeric FMA ids used by the research dataset (ids < ~155k are in it).

How it works
------------
1. Discover.  ~80 listing "buckets", each a ranked list of tracks:
     * charts  : /music/charts/all?genre=<FMA genre id>&sort=downloads|favorites|listens
                 (genre ids from the dataset's genres.csv: 811 Hip-Hop Beats,
                 286 Trip-Hop, 14 Soul-RnB, 495 Downtempo, 81 Afrobeat, ...)
     * genres  : /genre/<slug>?sort=_score  for post-2017 genres that have no id
                 (Lo-fi-Hip-Hop, Lo-fi-Soul-RnB, Lo-fi-Electronic, reggaeton ...)
     * search  : /search?quicksearch=<keyword>  (type beat, trap, sad, emo, piano,
                 afro, amapiano, dancehall, acoustic, juice wrld, lil peep ...)
   200 rows per page; every fetched page is cached as JSON (cache/listings/), so
   re-runs are cheap and deterministic.
2. Plan.  Buckets carry weights that are scaled to --target x --plan-factor.
   Tracks are interleaved round-robin across buckets in rank order, de-duplicated
   by track id, filtered (duration 70 s .. 8 min when known; out-of-territory
   genres such as noise / metal / free-jazz / spoken / old-time are dropped,
   "soft" genres such as classical / jazz / techno only pass together with a
   fitting genre; no podcasts / DJ mixes / skits / sound effects) and capped per
   artist (--artist-cap) so prolific uploaders cannot flood the pool.  Wherever
   a run stops, the pool is balanced across genres.  The plan is written to
   plan.json for transparency.
3. Fetch.  For each planned track the track page is fetched (rate-limited,
   --rps): license, genres, duration, instrumental / explicit / AI flags, plays,
   downloads, release year, direct file URL.  AI-generated uploads are skipped
   (unless --allow-ai).  ffmpeg then cuts 40 s starting ~30 % into the track
   straight from the remote MP3 (-ss before -i => HTTP range, only ~1 MB is
   fetched) and re-encodes to MP3 128 kbps / 44.1 kHz stereo.  Each clip is
   validated with ffprobe (>= 20 s) or deleted.
4. Records.  One JSON object per clip is appended to candidates.jsonl with the
   contract keys (id = "fma:<track id>").  full_audio_url is the direct CDN MP3,
   full_audio_available = true.  BPM / key are parsed from the title when the
   uploader put them there (e.g. "... 140 BPM C#m"), else null.

Resumable: ids already in candidates.jsonl / rejects.jsonl are skipped (only
permanent failures - AI-generated, off-territory genre on the track page,
missing audio, too short - are written to rejects.jsonl; network errors are
retried on the next run).  --max-seconds stops submitting work after a time
budget.  Run repeatedly until --target is reached or the plan is exhausted.

CPU-light by design: no audio analysis, ffmpeg runs single-threaded under nice.
Politeness: HTML requests to freemusicarchive.org are limited to --rps per
second (default 2.5) with exponential back-off and Retry-After on 429/5xx.

Usage
-----
  /opt/av/bin/python harvest_fma.py --target 1200 --max-seconds 500
  # the 2026-10-25 pool: --target 1200 (x2 chunks), then the rest of the same plan
  # (identical quotas because target * plan_factor stays 1620):
  /opt/av/bin/python harvest_fma.py --target 1500 --plan-factor 1.08 --max-seconds 520
  /opt/av/bin/python harvest_fma.py --discover-only   # fetch/cached listings only
  /opt/av/bin/python harvest_fma.py --dry-run         # listings + print plan summary
  /opt/av/bin/python harvest_fma.py --stats           # summarize the output JSONL
  /opt/av/bin/python harvest_fma.py --refresh-meta    # re-derive metadata offline
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import hashlib
import html
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse

import requests

# --------------------------------------------------------------------------- #
# Paths / constants
# --------------------------------------------------------------------------- #
SOURCE = "fma"
BASE = "https://freemusicarchive.org"
OUT_DIR = "/home/user/test/work/catalog/fma"
CLIP_DIR = os.path.join(OUT_DIR, "clips")
CAND_PATH = os.path.join(OUT_DIR, "candidates.jsonl")
REJECT_PATH = os.path.join(OUT_DIR, "rejects.jsonl")
CACHE_DIR = os.path.join(OUT_DIR, "cache", "listings")
PLAN_PATH = os.path.join(OUT_DIR, "plan.json")
LOG_DIR = os.path.join(OUT_DIR, "logs")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 (personal non-commercial remix research)")
PAGE_SIZE = 200          # FMA accepts 20/50/100/200
CLIP_LEN = 40.0          # seconds (contract: 30-45 s)
MIN_CLIP = 20.0          # ffprobe validation threshold
START_FRAC = 0.30        # excerpt start as a fraction of the full duration
MIN_DUR, MAX_DUR = 70.0, 480.0

# --------------------------------------------------------------------------- #
# Listing buckets: (name, category, kind, param, sort, weight, max_pages)
#   kind = chart  -> param is an FMA genre id (from genres.csv), sort in
#                    downloads|favorites|listens
#   kind = genre  -> param is a genre slug, sort is the site sort key
#   kind = search -> param is the quicksearch keyword (site ANDs the words)
# Weights are relative; they are scaled to target * plan_factor.
# --------------------------------------------------------------------------- #
BUCKETS: list[tuple[str, str, str, str, str, int, int]] = [
    # --- Juice-style / melodic trap / emo rap (keyword searches) -------------
    ("s_type_beat", "juice_type", "search", "type beat", "", 45, 2),
    ("s_trap", "juice_type", "search", "trap", "", 45, 2),
    ("s_emo", "juice_type", "search", "emo", "", 10, 1),
    ("s_sad", "juice_type", "search", "sad", "", 30, 1),
    ("s_melodic", "juice_type", "search", "melodic", "", 20, 1),
    ("s_guitar", "juice_type", "search", "guitar", "", 25, 1),
    ("s_juice", "juice_type", "search", "juice wrld", "", 5, 1),
    ("s_peep", "juice_type", "search", "lil peep", "", 5, 1),
    ("s_xxx", "juice_type", "search", "xxxtentacion", "", 5, 1),
    ("s_heartbreak", "juice_type", "search", "heartbreak", "", 10, 1),
    ("s_drill", "juice_type", "search", "drill", "", 15, 1),
    ("s_emotional", "juice_type", "search", "emotional", "", 20, 1),
    ("s_lonely", "juice_type", "search", "lonely", "", 15, 1),
    ("s_melancholy", "juice_type", "search", "melancholy", "", 10, 1),
    ("s_rap_beat", "juice_type", "search", "rap beat", "", 12, 1),
    ("s_trap_beat", "juice_type", "search", "trap beat", "", 12, 1),
    ("s_free_beat", "juice_type", "search", "free beat", "", 10, 1),
    ("s_prod", "juice_type", "search", "prod", "", 15, 1),
    ("s_hiphop_instr", "juice_type", "search", "hip hop instrumental", "", 30, 1),
    ("s_nostalgic", "juice_type", "search", "nostalgic", "", 10, 1),
    ("s_heart", "juice_type", "search", "heart", "", 15, 1),
    ("s_night", "juice_type", "search", "night", "", 10, 1),
    ("s_dreamy", "juice_type", "search", "dreamy", "", 10, 1),
    ("s_rain", "juice_type", "search", "rain", "", 8, 1),
    # --- hip-hop instrumentals / beats -------------------------------------
    ("c_hiphop_beats", "hiphop", "chart", "811", "downloads", 110, 2),
    ("c_hiphop_dl", "hiphop", "chart", "21", "downloads", 120, 3),
    ("c_hiphop_fav", "hiphop", "chart", "21", "favorites", 50, 2),
    ("c_hiphop_listens", "hiphop", "chart", "21", "listens", 40, 2),
    ("c_alt_hiphop", "hiphop", "chart", "100", "downloads", 45, 1),
    ("c_abstract_hiphop", "hiphop", "chart", "580", "downloads", 20, 1),
    ("c_rap", "hiphop", "chart", "539", "downloads", 35, 1),
    ("c_wonky", "hiphop", "chart", "693", "downloads", 10, 1),
    ("c_triphop", "hiphop", "chart", "286", "downloads", 55, 1),
    ("g_lofi_hiphop", "lofi", "genre", "Lo-fi-Hip-Hop", "_score", 55, 2),
    ("g_hiphop_beats", "hiphop", "genre", "Hip-Hop_Beats", "_score", 25, 1),
    ("s_lofi", "lofi", "search", "lofi", "", 25, 1),
    ("s_boom_bap", "hiphop", "search", "boom bap", "", 15, 1),
    ("s_chill", "lofi", "search", "chill", "", 20, 1),
    ("s_piano", "piano_ballad", "search", "piano", "", 25, 1),
    ("s_love", "rnb", "search", "love", "", 20, 1),
    # --- R&B / soul ----------------------------------------------------------
    ("c_soul_rnb_dl", "rnb", "chart", "14", "downloads", 70, 2),
    ("c_soul_rnb_fav", "rnb", "chart", "14", "favorites", 25, 1),
    ("g_soul_rnb", "rnb", "genre", "Soul-RB", "_score", 25, 1),
    ("g_lofi_soul", "rnb", "genre", "Lo-fi-Soul-RnB", "_score", 25, 1),
    ("s_rnb", "rnb", "search", "rnb", "", 20, 1),
    # --- chill electronic -------------------------------------------------
    ("c_downtempo", "chill_electronic", "chart", "495", "downloads", 45, 1),
    ("c_chillout", "chill_electronic", "chart", "400", "downloads", 40, 1),
    ("g_lofi_electronic", "chill_electronic", "genre", "Lo-fi-Electronic", "_score", 20, 1),
    ("c_ambient_electronic", "chill_electronic", "chart", "42", "downloads", 15, 1),
    # --- pop / synth-pop -----------------------------------------------------
    ("c_pop", "pop", "chart", "10", "downloads", 45, 1),
    ("c_synthpop", "pop", "chart", "362", "downloads", 40, 1),
    ("c_experimental_pop", "pop", "chart", "76", "downloads", 15, 1),
    # --- folk / acoustic -----------------------------------------------------
    ("c_singer_songwriter", "folk_acoustic", "chart", "103", "downloads", 40, 1),
    ("c_folk", "folk_acoustic", "chart", "17", "downloads", 30, 1),
    ("s_acoustic", "folk_acoustic", "search", "acoustic", "", 25, 1),
    ("s_acoustic_guitar", "folk_acoustic", "search", "acoustic guitar", "", 15, 1),
    # --- pop-punk / emo / alt-rock ballads ---------------------------------
    ("c_power_pop", "rock_emo", "chart", "111", "downloads", 20, 1),
    ("c_indie_rock", "rock_emo", "chart", "66", "downloads", 25, 1),
    ("c_punk", "rock_emo", "chart", "25", "downloads", 12, 1),
    ("c_shoegaze", "rock_emo", "chart", "359", "downloads", 8, 1),
    ("s_ballad", "rock_emo", "search", "ballad", "", 10, 1),
    ("s_pop_punk", "rock_emo", "search", "pop punk", "", 20, 1),
    # --- afro / international / dancehall ---------------------------------
    ("c_afrobeat", "afro_international", "chart", "81", "downloads", 40, 1),
    ("c_african", "afro_international", "chart", "92", "downloads", 30, 1),
    ("c_dancehall", "afro_international", "chart", "602", "downloads", 25, 1),
    ("c_reggae_dub", "afro_international", "chart", "79", "downloads", 12, 1),
    ("c_french", "afro_international", "chart", "77", "downloads", 35, 1),
    ("c_latin_america", "afro_international", "chart", "46", "downloads", 10, 1),
    ("g_reggaeton", "afro_international", "genre", "reggaeton", "_score", 12, 1),
    ("s_afro", "afro_international", "search", "afro", "", 20, 1),
    ("s_afrobeats", "afro_international", "search", "afrobeats", "", 10, 1),
    ("s_amapiano", "afro_international", "search", "amapiano", "", 10, 1),
    ("s_dancehall", "afro_international", "search", "dancehall", "", 10, 1),
    ("s_kizomba", "afro_international", "search", "kizomba", "", 8, 1),
    ("s_zouk", "afro_international", "search", "zouk", "", 2, 1),
    ("s_afro_pop", "afro_international", "search", "afro pop", "", 10, 1),
    ("s_amour", "afro_international", "search", "amour", "", 12, 1),
    # --- instrumental / cinematic -----------------------------------------
    ("c_instrumental", "cinematic", "chart", "1235", "downloads", 45, 1),
    ("c_soundtrack", "cinematic", "chart", "18", "downloads", 30, 1),
    ("s_cinematic", "cinematic", "search", "cinematic", "", 20, 1),
    ("s_orchestral", "cinematic", "search", "orchestral", "", 10, 1),
]

# Genre names (lower-case, as shown on FMA) that put a track out of territory.
HARD_EXCLUDE = {
    "noise", "noise-rock", "metal", "death-metal", "black-metal", "grindcore",
    "hardcore", "thrash", "sludge", "industrial", "breakcore - hard", "chip music",
    "chiptune", "free-jazz", "jazz: out", "spoken", "spoken weird", "poetry",
    "audio collage", "field recordings", "drone", "sound art", "musique concrete",
    "sound collage", "polka", "klezmer", "old-time / historic", "comedy",
    "talk radio", "radio art", "sound poetry", "novelty", "kid-friendly",
    "christmas", "halloween", "holiday", "electroacoustic", "avant-garde",
    "sound effects", "nerdcore", "radio", "interview", "audiobook", "news",
    "ambient noise", "white noise", "meditation", "asmr", "sleep",
}
# Genres that only pass when the track also carries a FIT genre.
SOFT_EXCLUDE = {
    "classical", "jazz", "country", "blues", "bluegrass", "opera", "choral music",
    "baroque", "contemporary classical", "20th century classical", "chamber music",
    "techno", "minimal electronic", "idm", "glitch", "dubstep", "drum & bass",
    "jungle", "house", "psych-rock", "garage", "krautrock", "post-rock",
    "loud-rock", "space-rock", "goth", "no wave", "surf", "electro-punk",
    "progressive", "rock opera", "experimental", "unclassifiable", "free-folk",
    "freak-folk", "psych-folk", "balkan", "celtic", "flamenco", "tango", "fado",
    "turkish", "indian", "middle east", "romany (gypsy)", "big band/swing",
    "be-bop", "modern jazz", "jazz: vocal", "new age", "ambient", "bigbeat",
    "skweee", "dance", "disco", "deep funk", "funk", "lounge", "easy listening",
    "spoken word",
}
FIT = {
    "hip-hop", "hiphop", "hip-hop beats", "rap", "alternative hip-hop",
    "abstract hip-hop", "wonky", "breakbeat", "trip-hop", "lo-fi hip-hop",
    "lo-fi soul-rnb", "lo-fi electronic", "soul-rnb", "r&b", "rnb", "pop",
    "synth pop", "experimental pop", "indie-pop", "downtempo", "chill-out",
    "chillwave", "singer-songwriter", "folk", "acoustic", "soundtrack",
    "instrumental", "ambient electronic", "indie-rock", "power-pop", "punk",
    "emo", "lo-fi", "shoegaze", "afrobeat", "african", "reggae - dancehall",
    "reggae - dub", "reggaeton", "dancehall", "latin america", "latin", "french",
    "international", "electronic", "cinematic", "trap", "cloud rap", "piano",
}

BAD_TITLE = re.compile(
    r"\b(podcast|episode|interview|skit|radio show|full album|mixtape|dj ?mix|"
    r"live set|megamix|continuous mix|sound ?effects?|sfx|ringtone|meditation|"
    r"sleep music|white noise|asmr|audiobook|reading|chapter|a ?cappella|"
    r"acapella|vocals? only|8d audio|nightcore|slowed|sped up)\b"
    r"|\bmix\s*#?\d|^\s*(intro|outro|interlude)\s*$",
    re.I)

LOG_FH = None
_print_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    with _print_lock:
        print(line, flush=True)
        if LOG_FH:
            LOG_FH.write(line + "\n")
            LOG_FH.flush()


def safe_id(native_id: str) -> str:
    return "fma_" + re.sub(r"[^A-Za-z0-9_-]+", "_", str(native_id))


def load_jsonl(path: str) -> list[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # tolerate a torn last line after a hard kill
    return out


def append_jsonl(path: str, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def norm_artist(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def parse_mmss(s: str) -> float | None:
    parts = s.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return float(total)


def parse_bpm(text: str) -> float | None:
    m = re.search(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*(?:bpm|b\.p\.m)\b", text, re.I) or \
        re.search(r"\bbpm\s*[:=]?\s*(\d{2,3}(?:\.\d+)?)", text, re.I)
    if m:
        v = float(m.group(1))
        if 50 <= v <= 220:
            return v
    return None


_KEY_RE = re.compile(
    r"(?:\bkey\s*(?:of\s*)?[:=]?\s*|\bin\s+|\bbpm\s*[,|-]?\s*|[\(\[\|,-]\s*)"
    r"([A-G])\s*(#|b|♯|♭|sharp|flat)?\s*"
    r"(maj(?:or)?|min(?:or)?|m(?![a-z]))\b", re.I)


def parse_key(text: str) -> str | None:
    m = _KEY_RE.search(text or "")
    if not m:
        return None
    note = m.group(1).upper()
    acc = (m.group(2) or "").lower()
    acc = {"♯": "#", "sharp": "#", "♭": "b", "flat": "b"}.get(acc, acc)
    mode = "minor" if m.group(3).lower().startswith("m") and not m.group(3).lower().startswith("maj") else "major"
    return f"{note}{acc} {mode}"


def ffprobe_duration(target: str, timeout: int = 40) -> float | None:
    cmd = ["ffprobe", "-v", "error"]
    if target.startswith("http"):
        cmd += proxy_args() + ["-user_agent", UA, "-rw_timeout", "30000000"]
    cmd += ["-show_entries", "format=duration", "-of", "csv=p=0", target]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
        return float(out.splitlines()[0]) if out else None
    except Exception:
        return None


def proxy_args() -> list[str]:
    """ffmpeg/ffprobe HTTP(S) proxy + CA options (outbound goes through a proxy)."""
    args = []
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        args += ["-http_proxy", proxy]
    ca = os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(ca):
        args += ["-ca_file", ca, "-tls_verify", "1"]
    return args


# --------------------------------------------------------------------------- #
# Polite HTTP
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Global minimum interval between HTML requests + shared back-off."""

    def __init__(self, rps: float):
        self.interval = 1.0 / max(rps, 0.1)
        self.lock = threading.Lock()
        self.next_t = 0.0

    def acquire(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait = self.next_t - now
            self.next_t = max(now, self.next_t) + self.interval
        if wait > 0:
            time.sleep(wait)

    def backoff(self, seconds: float) -> None:
        with self.lock:
            self.next_t = max(self.next_t, time.monotonic() + seconds)


_tls = threading.local()


def http() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en;q=0.9"})
        _tls.s = s
    return s


class PermanentHTTPError(Exception):
    pass


def http_get(url: str, limiter: RateLimiter, timeout: float = 30, tries: int = 5) -> str:
    last = None
    for attempt in range(tries):
        limiter.acquire()
        try:
            r = http().get(url, timeout=timeout)
            if r.status_code == 200:
                return r.text
            if r.status_code in (404, 410):
                raise PermanentHTTPError(f"HTTP {r.status_code}")
            if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else 2 ** attempt * 2
                limiter.backoff(min(wait, 60))
                last = f"HTTP {r.status_code}"
            else:
                last = f"HTTP {r.status_code}"
        except PermanentHTTPError:
            raise
        except requests.RequestException as e:
            last = repr(e)[:200]
        time.sleep((2 ** attempt) * (0.5 + random.random()))
    raise RuntimeError(f"GET failed after {tries} tries: {url} ({last})")


# --------------------------------------------------------------------------- #
# Listing pages
# --------------------------------------------------------------------------- #
_GENRE_LINK = re.compile(r'href="https://freemusicarchive\.org/genre/([^"/?]+)/?"[^>]*>\s*([^<]+?)\s*</a>')
_DUR = re.compile(r">\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*<")


def listing_url(kind: str, param: str, sort: str, page: int) -> str:
    if kind == "chart":
        q = {"genre": param, "sort": sort, "pageSize": PAGE_SIZE, "page": page}
        return f"{BASE}/music/charts/all?" + urllib.parse.urlencode(q)
    if kind == "genre":
        q = {"pageSize": PAGE_SIZE, "page": page, "sort": sort, "d": 0}
        return f"{BASE}/genre/{param}?" + urllib.parse.urlencode(q)
    if kind == "search":
        q = {"quicksearch": param, "pageSize": PAGE_SIZE, "page": page}
        return f"{BASE}/search?" + urllib.parse.urlencode(q)
    raise ValueError(kind)


def parse_track_info(raw: str) -> dict | None:
    try:
        return json.loads(html.unescape(raw))
    except json.JSONDecodeError:
        return None


def parse_listing(page_html: str) -> list[dict]:
    """Return one dict per track row (id, title, artist, album, url, file_url,
    genres, duration_s, count) in page order."""
    rows = []
    chunks = page_html.split("data-track-info='")
    for chunk in chunks[1:]:
        end = chunk.find("'")
        info = parse_track_info(chunk[:end])
        if not info or not info.get("id"):
            continue
        rest = chunk[end:]
        # the row ends at the next play-item; restrict genre/duration search to it
        cut = rest.find('class="play-item')
        rest = rest[:cut] if cut > 0 else rest[:12000]
        genres = []
        for slug, name in _GENRE_LINK.findall(rest):
            name = html.unescape(name).strip()
            if name and name not in genres:
                genres.append(name)
        dm = _DUR.search(rest)
        cm = re.search(r'chartcol-listens[^>]*>\s*([\d,]+)\s*<', rest)
        rows.append({
            "id": str(info["id"]),
            "handle": info.get("handle"),
            "title": html.unescape(info.get("title") or "").strip(),
            "artist": html.unescape(info.get("artistName") or "").strip(),
            "album": html.unescape(info.get("albumTitle") or "").strip() or None,
            "url": info.get("url"),
            "file_url": info.get("fileUrl"),
            "playback_url": info.get("playbackUrl"),
            "genres": genres,
            "duration_s": parse_mmss(dm.group(1)) if dm else None,
            "chart_count": int(cm.group(1).replace(",", "")) if cm else None,
        })
    return rows


def fetch_listing(url: str, limiter: RateLimiter, refresh: bool = False) -> list[dict]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["rows"]
    rows = parse_listing(http_get(url, limiter))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"url": url, "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}, fh)
    os.replace(tmp, path)
    return rows


def discover(limiter: RateLimiter, deadline: float, refresh: bool) -> dict[str, list[dict]]:
    """Fetch (or load cached) listing pages for every bucket."""
    results: dict[str, list[dict]] = {}
    n_net = 0
    for name, cat, kind, param, sort, weight, max_pages in BUCKETS:
        rows: list[dict] = []
        for page in range(1, max_pages + 1):
            url = listing_url(kind, param, sort, page)
            path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
            cached = os.path.exists(path) and not refresh
            if not cached and time.time() > deadline:
                log(f"[discover] time budget hit before {name} p{page}")
                break
            try:
                page_rows = fetch_listing(url, limiter, refresh)
            except Exception as e:  # keep going; next run retries
                log(f"[discover] {name} p{page} failed: {e}")
                break
            if not cached:
                n_net += 1
            rows.extend(page_rows)
            if len(page_rows) < PAGE_SIZE:
                break
        results[name] = rows
    log(f"[discover] {len(results)} buckets, {sum(len(v) for v in results.values())} rows "
        f"({n_net} pages fetched from network)")
    return results


# --------------------------------------------------------------------------- #
# Filtering + plan
# --------------------------------------------------------------------------- #
def genre_reject(genres: list[str]) -> str | None:
    gl = [g.lower().strip() for g in genres]
    hard = [g for g in gl if g in HARD_EXCLUDE]
    if hard:
        return "genre_hard:" + hard[0]
    soft = [g for g in gl if g in SOFT_EXCLUDE]
    if soft and not any(g in FIT for g in gl):
        return "genre_soft:" + soft[0]
    return None


def skip_reason(row: dict) -> str | None:
    t = row.get("title") or ""
    if BAD_TITLE.search(t):
        return "title"
    d = row.get("duration_s")
    if d is not None and not (MIN_DUR <= d <= MAX_DUR):
        return "duration"
    if row.get("genres"):
        return genre_reject(row["genres"])
    return None


def build_plan(results: dict[str, list[dict]], exclude: set[str], target: int,
               plan_factor: float, artist_cap: int, done_records: list[dict]) -> list[dict]:
    """Round-robin interleave buckets in rank order with scaled quotas.

    Already-harvested ids count toward their bucket's quota (so re-runs rebuild
    the same plan); permanently rejected ids are skipped and replaced."""
    done_ids = {r["id"] for r in done_records}
    total_w = sum(b[5] for b in BUCKETS)
    scale = target * plan_factor / total_w
    quota = {b[0]: max(3, round(b[5] * scale)) for b in BUCKETS}
    meta = {b[0]: b for b in BUCKETS}
    artist_n: collections.Counter = collections.Counter()
    for r in done_records:  # artists already harvested count toward the cap
        artist_n[norm_artist(r.get("artist", ""))] += 1
    seen: set[str] = set()
    plan: list[dict] = []
    cursors = {name: 0 for name in results}
    taken = collections.Counter()
    active = [b[0] for b in BUCKETS if results.get(b[0])]
    while active:
        nxt = []
        for name in active:
            rows = results[name]
            picked = False
            while cursors[name] < len(rows) and taken[name] < quota[name]:
                row = rows[cursors[name]]
                rank = cursors[name] + 1
                cursors[name] += 1
                tid = row["id"]
                if tid in seen:
                    continue
                seen.add(tid)
                if f"{SOURCE}:{tid}" in done_ids:
                    taken[name] += 1   # already harvested: counts toward quota
                    picked = True
                    break
                if f"{SOURCE}:{tid}" in exclude:
                    continue           # permanently rejected earlier
                if skip_reason(row):
                    continue
                a = norm_artist(row["artist"])
                if artist_n[a] >= artist_cap:
                    continue
                artist_n[a] += 1
                taken[name] += 1
                b = meta[name]
                plan.append(dict(row, bucket=name, category=b[1], rank=rank,
                                 query=describe_bucket(b)))
                picked = True
                break
            if picked and taken[name] < quota[name] and cursors[name] < len(rows):
                nxt.append(name)
        active = nxt
    return plan


def describe_bucket(b: tuple) -> str:
    name, cat, kind, param, sort, _, _ = b
    if kind == "chart":
        return f"chart:genre_id={param}:sort={sort} ({name})"
    if kind == "genre":
        return f"genre:{param}:sort={sort} ({name})"
    return f"search:quicksearch={param} ({name})"


# --------------------------------------------------------------------------- #
# Track page + clip
# --------------------------------------------------------------------------- #
def _field(page: str, label: str) -> str | None:
    m = re.search(re.escape(label) + r"\s*</span>\s*(?:</span>\s*)?<span[^>]*>\s*([^<]*?)\s*</span>",
                  page, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def parse_track_page(page: str) -> dict:
    out: dict = {}
    m = re.search(r"data-track-info='([^']*)'", page)
    info = parse_track_info(m.group(1)) if m else None
    out["info"] = info or {}
    # license: the CC deed link + its human-readable name
    lic_url = None
    lic_name = None
    for lm in re.finditer(r'<a[^>]*rel="license"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        lic_url = lm.group(1)
        txt = re.sub(r"<[^>]+>", "", lm.group(2)).strip()
        if txt:
            lic_name = html.unescape(txt)
    if not lic_url:
        lm = re.search(r'href="(https?://creativecommons\.org/[^"]+)"', page)
        lic_url = lm.group(1) if lm else None
    if lic_url or lic_name:
        out["license"] = f"{lic_name or 'license'} ({lic_url})" if lic_url else lic_name
        out["license_short"] = short_license(lic_url or lic_name or "")
    else:
        lm = re.search(r"is licensed under (?:a |an |the )?([^<.]+)", page)
        out["license"] = html.unescape(lm.group(1)).strip() if lm else None
        out["license_short"] = short_license(out["license"] or "")
    # genres from the "Track info" block
    ti = page.find("Track info")
    block = page[ti:ti + 20000] if ti >= 0 else ""
    gi = block.find("Genres")
    gblock = block[gi:gi + 6000] if gi >= 0 else ""
    genres = []
    for slug, name in _GENRE_LINK.findall(gblock):
        name = html.unescape(name).strip()
        if name and name not in genres:
            genres.append(name)
    out["genres"] = genres
    out["instrumental"] = _field(block, "Instrumental")
    out["explicit"] = _field(block, "Explicit")
    out["ai"] = _field(block, "AI generated?")
    out["released"] = _field(page, "Released")
    pm = re.search(r"Plays\s*</span>\s*</span>\s*<span[^>]*title=\"(\d+)\"", page)
    dm = re.search(r"Downloads\s*</span>\s*</span>\s*<span[^>]*title=\"(\d+)\"", page)
    out["plays"] = int(pm.group(1)) if pm else None
    out["downloads"] = int(dm.group(1)) if dm else None
    # duration: inside the play-item row for this track (second data-track-info)
    idx = [mm.start() for mm in re.finditer("data-track-info=", page)]
    dur = None
    if len(idx) >= 2:
        seg = page[idx[1]: idx[1] + 15000]
        dd = re.search(r"col-span-2 inline-flex justify-end items-center\">\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*<", seg) \
            or _DUR.search(seg)
        if dd:
            dur = parse_mmss(dd.group(1))
    out["duration_s"] = dur
    return out


def short_license(s: str) -> str:
    m = re.search(r"licenses/([a-z\-+]+)/(\d\.\d)", s)
    if m:
        return f"cc-{m.group(1)}-{m.group(2)}"
    if "publicdomain/zero" in s:
        return "cc0"
    if "publicdomain/mark" in s:
        return "public-domain-mark"
    if "FMA_License" in s or "FMA-Limited" in s:
        return "fma-limited-download-only"
    s2 = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s2[:40] or "unknown"


def choose_start(dur: float | None) -> float:
    if not dur:
        return 45.0  # unknown length: skip a typical intro
    if dur <= CLIP_LEN + 4:
        return 0.0
    st = dur * START_FRAC
    if st + CLIP_LEN > dur - 2:
        st = max(0.0, dur - CLIP_LEN - 2)
    return round(st, 2)


def ffmpeg_cut(url: str, dest: str, ss: float, t: float) -> None:
    tmp = dest + ".part.mp3"
    cmd = (["nice", "-n", "15", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
           + proxy_args()
           + ["-user_agent", UA, "-rw_timeout", "30000000",
              "-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "4",
              "-ss", f"{ss:.2f}", "-t", f"{t:.2f}", "-i", url,
              "-vn", "-map_metadata", "-1", "-threads", "1", "-ac", "2", "-ar", "44100",
              "-c:a", "libmp3lame", "-b:a", "128k", "-y", tmp])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        if p.returncode != 0:
            err = (p.stderr or "").strip()
            if "Output file is empty" in err:  # file shorter than the seek point / truncated upload
                raise Reject("empty_output")
            raise RuntimeError("ffmpeg: " + err[-300:])
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class Reject(Exception):
    """Permanent rejection (recorded in rejects.jsonl, never retried)."""


TITLE_INSTR = re.compile(r"\b(instrumental|instr\.?|type beat|beat|beats|riddim)\b", re.I)
INSTR_GENRES = {"hip-hop beats", "instrumental", "soundtrack", "ambient electronic",
                "lo-fi hip-hop", "lo-fi electronic", "downtempo", "chill-out", "ambient"}
VOCAL_GENRES = {"rap", "singer-songwriter", "jazz: vocal"}


def is_yes(v: str | None) -> bool:
    """FMA flags read "No" or e.g. "Yes, this track (or part of it) was generated by AI"."""
    return (v or "").strip().lower().startswith("yes")


def instrumental_meta(title: str, flag: str | None, genres: list[str]) -> bool | None:
    gl = {g.lower() for g in genres}
    if is_yes(flag):
        return True
    if re.search(r"\b(feat\.?|ft\.?|featuring)\b", title, re.I) and not re.search(r"instrumental", title, re.I):
        return False
    if TITLE_INSTR.search(title):
        return True
    if gl & VOCAL_GENRES:
        return False
    if gl and gl <= INSTR_GENRES | {"hip-hop", "electronic", "experimental"} and gl & INSTR_GENRES:
        return True  # purely beat/instrumental genres: FMA's default "No" is unreliable here
    if (flag or "").lower() == "no":
        return False
    return None


def fix_page_url(url: str | None) -> str | None:
    """Album-less singles are listed as /music/<artist>//<track>/ (404); the real
    page lives at /music/<artist>/single/<track>/."""
    if not url:
        return None
    head, sep, path = url.partition("://")
    return head + sep + path.replace("//", "/single/") if sep else url


def process(row: dict, limiter: RateLimiter, allow_ai: bool) -> dict:
    tid = row["id"]
    page_url = fix_page_url(row.get("url")) or f"{BASE}/track/{row.get('handle')}/"
    try:
        tp = parse_track_page(http_get(page_url, limiter))
    except PermanentHTTPError as e:
        raise Reject(f"track_page:{e}")
    info = tp["info"]
    if str(info.get("id", tid)) != tid:
        raise Reject(f"id_mismatch:{info.get('id')}")
    genres = tp["genres"] or row.get("genres") or []
    if is_yes(tp.get("ai")) and not allow_ai:
        raise Reject("ai_generated")
    gr = genre_reject(genres)
    if gr:
        raise Reject(gr)
    file_url = info.get("fileUrl") or row.get("file_url")
    stream_url = file_url or info.get("playbackUrl") or row.get("playback_url")
    if not stream_url:
        raise Reject("no_audio_url")
    dur = tp.get("duration_s") or row.get("duration_s")
    if not dur and file_url:
        dur = ffprobe_duration(file_url)
    if dur and not (MIN_DUR <= dur <= MAX_DUR):
        raise Reject(f"duration:{dur:.0f}")
    ss = choose_start(dur)
    t = CLIP_LEN if not dur else min(CLIP_LEN, max(MIN_CLIP, dur - ss - 1))
    dest = os.path.join(CLIP_DIR, safe_id(tid) + ".mp3")
    ffmpeg_cut(stream_url, dest, ss, t)
    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    got = ffprobe_duration(dest)
    if not got or got < MIN_CLIP:
        if os.path.exists(dest):
            os.remove(dest)
        if size < 2048:  # ffmpeg exited 0 but decoded nothing: truncated/short upload
            raise Reject("empty_output")
        if dur and got is not None:
            raise Reject(f"short_clip:{got}")
        raise RuntimeError(f"clip validation failed ({got})")
    title = info.get("title") or row["title"]
    title = html.unescape(title).strip()
    artist = html.unescape(info.get("artistName") or row["artist"]).strip()
    text_for_meta = f"{title} {info.get('albumTitle') or row.get('album') or ''}"
    year = None
    if tp.get("released"):
        ym = re.search(r"(19|20)\d{2}", tp["released"])
        year = ym.group(0) if ym else None
    tags = [f"cat:{row['category']}", f"bucket:{row['bucket']}", f"rank:{row['rank']}"]
    tags += [f"genre:{g}" for g in genres]
    if tp.get("license_short"):
        tags.append(f"license:{tp['license_short']}")
    if tp.get("instrumental"):
        tags.append(f"fma_instrumental:{tp['instrumental'].lower()}")
    if tp.get("explicit"):
        tags.append(f"explicit:{tp['explicit'].lower()}")
    if tp.get("ai"):
        tags.append("ai_generated:" + ("yes" if is_yes(tp["ai"]) else tp["ai"].lower()))
    if year:
        tags.append(f"year:{year}")
    if tp.get("plays") is not None:
        tags.append(f"plays:{tp['plays']}")
    if tp.get("downloads") is not None:
        tags.append(f"downloads:{tp['downloads']}")
    if row.get("album"):
        tags.append(f"album:{row['album']}")
    if int(tid) < 156000:
        tags.append("fma_dataset_era")  # id range of the 2017 FMA research dataset
    tags.append("full:direct_mp3")
    return {
        "id": f"{SOURCE}:{tid}",
        "source": SOURCE,
        "title": title,
        "artist": artist,
        "page_url": fix_page_url(info.get("url")) or page_url,
        "clip_path": dest,
        "clip_start_s": ss,
        "duration_full_s": dur,
        "license": tp.get("license"),
        "full_audio_url": file_url,
        "full_audio_available": bool(file_url),
        "bpm_meta": parse_bpm(text_for_meta),
        "key_meta": parse_key(title),
        "tags": tags,
        "is_instrumental_meta": instrumental_meta(title, tp.get("instrumental"), genres),
        "query": row["query"],
        "is_reference": False,
    }


# --------------------------------------------------------------------------- #
# Re-derive metadata of existing records (no network)
# --------------------------------------------------------------------------- #
def refresh_meta(allow_ai: bool) -> None:
    """Recompute derived fields (is_instrumental_meta, bpm/key, license tag) from
    the stored tags/title with the current rules, and drop AI-flagged records
    (clip deleted, id moved to rejects.jsonl) unless --allow-ai."""
    recs = load_jsonl(CAND_PATH)
    keep, dropped = [], 0
    for r in recs:
        tags = r["tags"]
        ai = next((t.split(":", 1)[1] for t in tags if t.startswith("ai_generated:")), None)
        if is_yes(ai) and not allow_ai:
            if os.path.exists(r["clip_path"]):
                os.remove(r["clip_path"])
            append_jsonl(REJECT_PATH, {"id": r["id"], "title": r["title"], "artist": r["artist"],
                                       "reason": "ai_generated",
                                       "bucket": next((t[7:] for t in tags if t.startswith("bucket:")), None)})
            dropped += 1
            continue
        tags = [("ai_generated:yes" if t.startswith("ai_generated:") and is_yes(t[13:]) else t) for t in tags]
        genres = [t[6:] for t in tags if t.startswith("genre:")]
        flag = next((t.split(":", 1)[1] for t in tags if t.startswith("fma_instrumental:")), None)
        album = next((t[6:] for t in tags if t.startswith("album:")), "")
        r["is_instrumental_meta"] = instrumental_meta(r["title"], flag, genres)
        r["bpm_meta"] = parse_bpm(f"{r['title']} {album}")
        r["key_meta"] = parse_key(r["title"])
        if r.get("license"):
            tags = [("license:" + short_license(r["license"]) if t.startswith("license:") else t) for t in tags]
        r["tags"] = tags
        keep.append(r)
    tmp = CAND_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in keep:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, CAND_PATH)
    print(f"refresh-meta: kept {len(keep)}, dropped {dropped} AI-flagged")


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def print_stats() -> None:
    recs = load_jsonl(CAND_PATH)
    rej = load_jsonl(REJECT_PATH)
    print(f"records: {len(recs)}   rejects: {len(rej)}")
    cats = collections.Counter(next((t[4:] for t in r["tags"] if t.startswith("cat:")), "?") for r in recs)
    print("by category:", dict(cats.most_common()))
    lic = collections.Counter(next((t[8:] for t in r["tags"] if t.startswith("license:")), "?") for r in recs)
    print("by license:", dict(lic.most_common()))
    print("instrumental_meta:", dict(collections.Counter(str(r["is_instrumental_meta"]) for r in recs)))
    print("full_audio_available:", sum(1 for r in recs if r["full_audio_available"]))
    print("bpm_meta:", sum(1 for r in recs if r["bpm_meta"]), " key_meta:", sum(1 for r in recs if r["key_meta"]))
    arts = collections.Counter(r["artist"] for r in recs)
    print("artists:", len(arts), " top:", arts.most_common(8))
    print("reject reasons:", dict(collections.Counter(r.get("reason", "?").split(":")[0] for r in rej).most_common()))
    size = sum(os.path.getsize(r["clip_path"]) for r in recs if os.path.exists(r["clip_path"]))
    print(f"clip bytes: {size / 1e6:.1f} MB")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    global LOG_FH
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", type=int, default=1200, help="stop when this many records exist")
    ap.add_argument("--max-seconds", type=float, default=500, help="time budget for this run")
    ap.add_argument("--workers", type=int, default=6, help="parallel track fetch+clip jobs (<= 8)")
    ap.add_argument("--rps", type=float, default=2.5, help="max HTML requests/s to freemusicarchive.org")
    ap.add_argument("--artist-cap", type=int, default=8, help="max planned tracks per artist")
    ap.add_argument("--plan-factor", type=float, default=1.35,
                    help="plan size = target * factor (headroom for rejects)")
    ap.add_argument("--allow-ai", action="store_true", help="keep tracks flagged AI-generated")
    ap.add_argument("--refresh", action="store_true", help="re-fetch cached listing pages")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="discover + print the plan summary")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--refresh-meta", action="store_true",
                    help="re-derive metadata of existing records offline (and drop AI-flagged ones)")
    args = ap.parse_args()

    if args.stats:
        print_stats()
        return 0
    if args.refresh_meta:
        refresh_meta(args.allow_ai)
        return 0

    for d in (OUT_DIR, CLIP_DIR, CACHE_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    LOG_FH = open(os.path.join(LOG_DIR, time.strftime("harvest_%Y%m%d_%H%M%S.log")), "w")
    t0 = time.time()
    deadline = t0 + args.max_seconds
    limiter = RateLimiter(args.rps)

    results = discover(limiter, deadline - 60, args.refresh)
    if args.discover_only:
        return 0

    done = load_jsonl(CAND_PATH)
    rejects = load_jsonl(REJECT_PATH)
    done_ids = {r["id"] for r in done}
    exclude = done_ids | {r["id"] for r in rejects}
    plan = build_plan(results, exclude, args.target, args.plan_factor, args.artist_cap, done)
    with open(PLAN_PATH, "w", encoding="utf-8") as fh:
        json.dump([{k: p[k] for k in ("id", "title", "artist", "bucket", "rank", "genres", "duration_s")}
                   for p in plan], fh, ensure_ascii=False, indent=0)
    by_cat = collections.Counter(p["category"] for p in plan)
    log(f"[plan] {len(plan)} new tracks planned (done={len(done_ids)}, rejected={len(rejects)}) "
        f"by category: {dict(by_cat.most_common())}")
    if args.dry_run:
        by_b = collections.Counter(p["bucket"] for p in plan)
        for b in BUCKETS:
            print(f"  {b[0]:24s} rows={len(results.get(b[0], [])):4d} planned={by_b.get(b[0], 0)}")
        return 0

    need = args.target - len(done_ids)
    if need <= 0:
        log(f"[done] target reached ({len(done_ids)} records)")
        return 0

    n_ok = n_rej = n_err = 0
    it = iter(plan)
    inflight: dict[cf.Future, dict] = {}
    workers = max(1, min(args.workers, 8))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        def submit_more() -> None:
            while (len(inflight) < workers * 2 and time.time() < deadline - 20
                   and n_ok + len(inflight) < need):
                row = next(it, None)
                if row is None:
                    return
                inflight[ex.submit(process, row, limiter, args.allow_ai)] = row

        submit_more()
        while inflight:
            fin, _ = cf.wait(list(inflight), return_when=cf.FIRST_COMPLETED)
            for fut in fin:
                row = inflight.pop(fut)
                try:
                    rec = fut.result()
                    append_jsonl(CAND_PATH, rec)
                    n_ok += 1
                    if n_ok % 25 == 0:
                        log(f"[fetch] +{n_ok} ok, {n_rej} rejected, {n_err} errors "
                            f"(total {len(done_ids) + n_ok}) {time.time() - t0:.0f}s")
                except Reject as e:
                    n_rej += 1
                    append_jsonl(REJECT_PATH, {"id": f"{SOURCE}:{row['id']}", "title": row["title"],
                                               "artist": row["artist"], "reason": str(e),
                                               "bucket": row["bucket"]})
                except Exception as e:  # transient: retried next run
                    n_err += 1
                    log(f"[fetch] error {row['id']} {row['title'][:40]!r}: {str(e)[:160]}")
            submit_more()

    total = len(done_ids) + n_ok
    left = sum(1 for _ in it)
    log(f"[run] +{n_ok} ok, {n_rej} rejected, {n_err} transient errors in {time.time() - t0:.0f}s; "
        f"total records {total}/{args.target}; plan items not yet attempted: {left}")
    if total >= args.target:
        log("[done] target reached")
    elif left == 0 and n_ok + len(inflight) < need:
        log("[note] plan exhausted for this run; re-run (plan is rebuilt with remaining rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
