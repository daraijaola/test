#!/opt/av/bin/python
"""
harvest_ccmixter.py -- build a candidate-beat pool from ccMixter (Creative Commons remix community).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial fan project).
This script ONLY harvests: metadata via the public ccMixter Query API plus short 40 s audio
excerpts taken from the musical body of each track. No audio analysis is done here.

Two resumable stages
--------------------
A. metadata  : paginate the Query API (https://ccmixter.org/api/query?f=json&tags=...) over a
               prioritised list of tag combos (instrumental + genre / mood / bpm buckets), round-robin
               so the pool stays diverse. Every accepted upload is appended to
                   <out>/candidates_pending_clips.jsonl
               (same schema as candidates.jsonl, clip_path = null).
B. clips     : for every pending record, ffmpeg seeks into the remote mp3 (HTTP range requests, only
               the needed bytes are fetched), cuts 40 s starting ~30 % into the track, re-encodes to
               mp3 128k / 44.1 kHz, validates with ffprobe (>= 20 s) and appends the completed record to
                   <out>/candidates.jsonl              <- the contract file (only clip-backed rows)
               Failures go to <out>/clip_failures.jsonl.

Access note: ccMixter's /content/ file server answers "403 Forbidden" to non-browser HTTP clients
from some networks. This script sends plain, honest requests (no browser impersonation, no header
spoofing). A circuit breaker stops stage B after a few consecutive 403s so the server is not
hammered; the pending metadata stays on disk and `--clips-only --retry-blocked` resumes later.

Politeness: API calls are serialised and spaced >= --api-interval seconds (default 1.5 s), with
exponential backoff on errors. Clip downloads use at most --workers parallel ffmpeg processes (<= 8).

Usage
-----
  harvest_ccmixter.py --target 1500 --max-seconds 500            # both stages, resumable
  harvest_ccmixter.py --metadata-only                             # stage A only
  harvest_ccmixter.py --clips-only --retry-blocked --workers 8    # stage B only, retry 403s
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import http.client

import requests

# The ccMixter API echoes the whole JSON payload a second time in an "X-JSON" response header
# (prototype.js convention). For pages of 50 uploads that header is ~150 kB, far above
# http.client's 64 kB header-line limit, so raise the client-side parsing limit.
http.client._MAXLINE = 8 * 1024 * 1024

SOURCE = "ccmixter"
API = "https://ccmixter.org/api/query"
DEFAULT_OUT = Path("/home/user/test/work/catalog/ccmixter")
CA_BUNDLE = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or ""
HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""

CLIP_LEN_S = 40.0
MIN_TRACK_S = 60.0          # skip loops / stingers
MAX_TRACK_S = 15 * 60.0     # skip DJ mixes / hour-long sets
MIN_CLIP_S = 20.0

# ----------------------------------------------------------------------------------------------
# Query plan: (tag combo, per-query cap). Ordered by expected fit to a melodic, emotional
# Juice WRLD / afro-R&B remix. Stage A walks the plan round-robin (ROUND_QUOTA per query per
# round) so a few huge tags cannot crowd out the niche ones.
# All queries are AND-combinations of ccMixter tags, sorted by community rank.
# ----------------------------------------------------------------------------------------------
QUERY_PLAN: list[tuple[str, int]] = [
    # melodic hip-hop / trap / R&B core
    ("instrumental+hip_hop", 900),
    ("instrumental+trap", 60),
    ("instrumental+r_n_b", 40),
    ("instrumental+soul", 120),
    ("instrumental+trip_hop", 450),
    ("instrumental+guitar+hip_hop", 180),
    ("instrumental+piano+hip_hop", 180),
    ("instrumental+urban", 40),
    ("instrumental+beats", 50),
    ("instrumental+lo_fi", 10),
    ("instrumental+boom_bap", 5),
    ("instrumental+rap", 5),
    ("hip_hop+chill", 250),
    # emotional / mood tags
    ("instrumental+sad", 60),
    ("instrumental+melancholy", 30),
    ("instrumental+melancholic", 20),
    ("instrumental+emotional", 25),
    ("instrumental+romantic", 65),
    ("instrumental+love", 40),
    ("instrumental+mellow", 100),
    ("instrumental+dreamy", 40),
    ("instrumental+ballad", 45),
    ("instrumental+smooth", 30),
    ("instrumental+atmospheric", 70),
    # piano / guitar / acoustic / chill / downtempo
    ("instrumental+piano+chill", 300),
    ("instrumental+guitar+chill", 300),
    ("instrumental+acoustic+chill", 200),
    ("instrumental+downtempo", 400),
    ("instrumental+piano", 300),
    ("instrumental+acoustic", 200),
    ("instrumental+chill", 300),
    # pop / alt / emo / rock ballads
    ("instrumental+pop", 150),
    ("instrumental+electro_pop", 16),
    ("instrumental+synthpop", 4),
    ("instrumental+alternative", 120),
    ("instrumental+indie", 13),
    ("instrumental+punk", 8),
    ("instrumental+emo", 4),
    # afro / latin / caribbean / world
    ("instrumental+afro", 3),
    ("instrumental+dancehall", 4),
    ("instrumental+reggae", 48),
    ("instrumental+dub", 60),
    ("instrumental+latin", 60),
    ("instrumental+world", 41),
    # cinematic / orchestral / jazzy samples
    ("instrumental+orchestral", 120),
    ("instrumental+strings", 76),
    ("instrumental+music_for_film", 150),
    ("instrumental+jazzy", 120),
    ("instrumental+funk", 60),
    # tempo buckets (ballad / R&B tempi and half-time trap tempi)
    ("instrumental+bpm_070_075", 80),
    ("instrumental+bpm_075_080", 100),
    ("instrumental+bpm_080_085", 120),
    ("instrumental+bpm_085_090", 150),
    ("instrumental+bpm_090_095", 150),
    ("instrumental+bpm_095_100", 120),
    ("instrumental+bpm_100_105", 80),
    ("instrumental+bpm_135_140", 60),
    ("instrumental+bpm_140_145", 80),
    ("instrumental+bpm_145_150", 50),
    ("instrumental+bpm_150_155", 40),
    ("instrumental+bpm_155_160", 30),
    ("instrumental+bpm_160_165", 30),
]
ROUND_QUOTA = 30   # round 1 then touches (almost) every query before any is deepened
PAGE = 50

# Tags that describe the file, not the music -> not copied into `tags`.
SYSTEM_TAGS = {
    "media", "audio", "mp3", "44k", "48k", "22k", "stereo", "mono", "vbr", "cbr", "archive", "zip",
    "flac", "ogg", "wav", "aiff", "m4a", "preview", "non_commercial", "attribution", "share_alike",
    "nc_sampling_plus", "sampling_plus", "sampling", "cczero", "nc_share_alike", "noderives",
    "by_nc_nd", "by_nc", "by", "by_sa", "by_nc_sa", "featured", "editorial_pick",
    # ccMixter bookkeeping tags (usage trackbacks / membership), not musical descriptors
    "trackback", "in_video", "in_podcast", "in_web", "in_remix", "in_album", "in_game",
    "ccplus", "ccplus_stem", "ccplus_verify", "ccplus_verified", "contest_entry", "contest_source",
}
VOCAL_TAGS = {
    "vocals", "vocal", "female_vocals", "male_vocals", "female_vocal", "male_vocal", "singing",
    "singer", "rap", "rapping", "spoken_word", "spoken", "lyrics", "acappella", "a_cappella",
    "choir", "sung",
}
EXCLUDE_TAGS = {"acappella", "a_cappella"}   # we need beats, not vocals
ALLOW_VOCALS = False                           # set by --allow-vocals
KEY_RE = re.compile(r"^(?:key_(?:of_)?)?([a-g])(_?sharp|_?flat)?_(major|minor|maj|min)$")
BPM_TAG_RE = re.compile(r"^bpm_(\d{2,3})_(\d{2,3})$")
BPM_OVER_RE = re.compile(r"^bpm_above_(\d{2,3})$")


# ----------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if path.exists():
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass   # tolerate a half-written last line after an interrupted run
    return rows


class JsonlWriter:
    """Thread-safe append-only JSONL writer (one flush per line => safe to kill at any time)."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, obj: dict) -> None:
        with self.lock, self.path.open("a") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def parse_duration(ps: str | None) -> float | None:
    """ccMixter 'ps' playtime string: 'm:ss' or 'h:mm:ss'."""
    if not ps:
        return None
    try:
        parts = [float(p) for p in str(ps).strip().split(":")]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec or None


def txt(x) -> str:
    """API fields are usually strings but numeric titles/names arrive as ints."""
    return "" if x is None else str(x).strip()


def split_tags(s) -> list[str]:
    return [t.strip().lower() for t in txt(s).split(",") if t.strip()]


def parse_bpm(tags: list[str], extra_bpm) -> float | None:
    """bpm_XXX_YYY tag -> midpoint; the uploader's exact bpm (upload_extra.bpm) wins when it lies
    inside that bucket; bare upload_extra.bpm is the fallback."""
    lo = hi = None
    for t in tags:
        m = BPM_TAG_RE.match(t)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            break
        m = BPM_OVER_RE.match(t)
        if m:
            lo = hi = int(m.group(1))
    try:
        exact = float(extra_bpm) if extra_bpm not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        exact = None
    if exact is not None and not (30 <= exact <= 250):
        exact = None
    if lo is not None:
        if exact is not None and lo <= exact <= hi:
            return exact
        return (lo + hi) / 2.0
    return exact


def parse_key(tags: list[str]) -> str | None:
    """Explicit key tags only (e.g. 'a_minor', 'key_of_c_sharp_major'); ccMixter rarely has them."""
    for t in tags:
        m = KEY_RE.match(t)
        if m:
            acc = "#" if m.group(2) and "sharp" in m.group(2) else ("b" if m.group(2) else "")
            mode = "minor" if m.group(3).startswith("min") else "major"
            return f"{m.group(1).upper()}{acc} {mode}"
    return None


def is_instrumental(tags: list[str]) -> bool | None:
    inst = "instrumental" in tags
    voc = any(t in VOCAL_TAGS for t in tags)
    if inst and not voc:
        return True
    if voc and not inst:
        return False
    return None   # neither, or contradictory tags


def license_str(up: dict) -> str | None:
    name = re.sub(r"\s+", " ", txt(up.get("license_name")))
    url = txt(up.get("license_url"))
    if not name and not url:
        return None
    return f"{name} | {url}" if url else name


def pick_mp3(up: dict) -> dict | None:
    """First locally hosted mp3 audio file of the upload (ccMixter uploads may also carry zips)."""
    files = sorted(up.get("files") or [], key=lambda f: f.get("file_order") or 0)
    for f in files:
        info = f.get("file_format_info") or {}
        if info.get("media-type") == "audio" and str(info.get("format-name", "")).startswith("audio-mp3"):
            if f.get("download_url"):
                return f
    return None


def clip_start_for(dur: float) -> float:
    """Start ~30 % in (skip intros) but keep the full 40 s inside the track (3 s tail margin)."""
    start = 0.30 * dur
    start = min(start, dur - CLIP_LEN_S - 3.0)
    return round(max(0.0, start), 2)


# ----------------------------------------------------------------------------------------------
# API client (serialised, rate limited, retried)
# ----------------------------------------------------------------------------------------------
class Api:
    def __init__(self, interval: float):
        self.s = requests.Session()
        if CA_BUNDLE:
            self.s.verify = CA_BUNDLE
        self.interval = interval
        self.last = 0.0
        self.calls = 0

    def get(self, params: dict, tries: int = 5):
        delay = 2.0
        for attempt in range(1, tries + 1):
            wait = self.interval - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                r = self.s.get(API, params=params, timeout=60)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (403, 404):
                    log(f"API {r.status_code} for {params} -- not retrying")
                    return None
                log(f"API HTTP {r.status_code} (attempt {attempt})")
            except (requests.RequestException, ValueError) as e:
                log(f"API error {type(e).__name__}: {e} (attempt {attempt})")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        return None


# ----------------------------------------------------------------------------------------------
# Stage A: metadata
# ----------------------------------------------------------------------------------------------
def make_record(up: dict, query: str) -> dict | None:
    f = pick_mp3(up)
    if not f:
        return None
    dur = parse_duration((f.get("file_format_info") or {}).get("ps"))
    if dur is None or dur < MIN_TRACK_S or dur > MAX_TRACK_S:
        return None
    extra = up.get("upload_extra") or {}
    all_tags = split_tags(up.get("upload_tags"))
    if any(t in EXCLUDE_TAGS for t in all_tags):
        return None
    if is_instrumental(all_tags) is False and not ALLOW_VOCALS:
        return None   # explicitly vocal (vocal tags, no 'instrumental' tag): would clash with Juice's vocal
    # musical tags = user tags + ccMixter upload-type tags, minus file/system/license tags
    tags: list[str] = []
    for t in split_tags(extra.get("usertags")) + split_tags(extra.get("ccud")):
        if t not in SYSTEM_TAGS and t not in tags:
            tags.append(t)
    artist = txt(up.get("user_real_name")) or txt(up.get("user_name"))
    feat = txt(extra.get("featuring"))
    url = f["download_url"]
    return {
        "id": f"{SOURCE}:{up['upload_id']}",
        "source": SOURCE,
        "title": txt(up.get("upload_name")),
        "artist": artist + (f" feat. {feat}" if feat else ""),
        "page_url": up.get("file_page_url") or f"https://ccmixter.org/files/{up.get('user_name')}/{up['upload_id']}",
        "clip_path": None,
        "clip_start_s": clip_start_for(dur),
        "duration_full_s": round(dur, 2),
        "license": license_str(up),
        "full_audio_url": url,
        "full_audio_available": False,   # flipped to True once a clip was actually fetched from it
        "bpm_meta": parse_bpm(all_tags, extra.get("bpm")),
        "key_meta": parse_key(all_tags),
        "tags": tags,
        "is_instrumental_meta": is_instrumental(all_tags),
        "query": f"api/query?tags={query}&sort=rank&ord=desc",
        "is_reference": False,
    }


def stage_metadata(args, out: Path, deadline: float) -> None:
    pending_path = out / "candidates_pending_clips.jsonl"
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    qstate: dict = state.setdefault("queries", {})
    seen = {r["id"] for r in read_jsonl(pending_path)} | {r["id"] for r in read_jsonl(out / "candidates.jsonl")}
    writer = JsonlWriter(pending_path)
    api = Api(args.api_interval)
    log(f"stage A: {len(seen)} records already known, target {args.target}")

    def save_state():
        state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(state_path)

    rnd = 0
    while len(seen) < args.target and time.time() < deadline:
        rnd += 1
        progressed = False
        for tags, cap in QUERY_PLAN:
            if len(seen) >= args.target or time.time() >= deadline:
                break
            qs = qstate.setdefault(tags, {"offset": 0, "accepted": 0, "exhausted": False})
            if qs["exhausted"] or qs["accepted"] >= cap:
                continue
            quota = min(cap, qs["accepted"] + ROUND_QUOTA)
            while qs["accepted"] < quota and not qs["exhausted"] and len(seen) < args.target:
                if time.time() >= deadline:
                    break
                data = api.get({"f": "json", "tags": tags.replace("+", " "), "type": "all",
                                "sort": "rank", "ord": "desc", "limit": PAGE, "offset": qs["offset"]})
                if data is None:
                    log(f"  {tags}: API gave up at offset {qs['offset']}, skipping for this run")
                    break
                if not isinstance(data, list) or not data:
                    qs["exhausted"] = True
                    break
                new = processed = 0
                for up in data:
                    processed += 1
                    rid = f"{SOURCE}:{up.get('upload_id')}"
                    if rid in seen:
                        continue
                    rec = make_record(up, tags)
                    if rec is None:
                        continue
                    writer.write(rec)
                    seen.add(rid)
                    qs["accepted"] += 1
                    new += 1
                    if qs["accepted"] >= quota or len(seen) >= args.target:
                        break
                # advance only past what was looked at, so the rest of the page is seen next round
                qs["offset"] += processed
                progressed = progressed or new > 0
                if len(data) < PAGE and processed == len(data):
                    qs["exhausted"] = True
                save_state()
            log(f"  round {rnd} {tags:<32} accepted={qs['accepted']:<4} offset={qs['offset']:<5} pool={len(seen)}")
        if not progressed:
            log("stage A: every query exhausted or capped")
            break
    save_state()
    log(f"stage A done: pool={len(seen)} api_calls={api.calls}")


# ----------------------------------------------------------------------------------------------
# Stage B: clips
# ----------------------------------------------------------------------------------------------
def ffprobe_duration(path: Path) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return float(p.stdout.strip() or 0)
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def fetch_clip(rec: dict, clip_dir: Path) -> tuple[str, dict | None, str]:
    """Returns (status, completed_record_or_None, detail). status in ok|blocked|failed."""
    safe = rec["id"].replace(":", "_")
    dst = clip_dir / f"{safe}.mp3"
    tmp = clip_dir / f".{safe}.part.mp3"
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if HTTPS_PROXY:
        cmd += ["-http_proxy", HTTPS_PROXY]       # ffmpeg ignores https_proxy env, pass explicitly
    if CA_BUNDLE:
        cmd += ["-ca_file", CA_BUNDLE, "-tls_verify", "1"]
    cmd += ["-rw_timeout", "45000000",
            "-ss", f"{rec['clip_start_s']:.2f}", "-t", f"{CLIP_LEN_S:.0f}",   # input seek => HTTP range
            "-i", rec["full_audio_url"],
            "-vn", "-map_metadata", "-1", "-ar", "44100", "-b:a", "128k", "-f", "mp3", "-y", str(tmp)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        err = (p.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return "failed", None, "ffmpeg timeout"
    if p.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        if "403" in err:
            return "blocked", None, "HTTP 403 Forbidden"
        return "failed", None, err.strip().splitlines()[-1] if err.strip() else f"rc={p.returncode}"
    d = ffprobe_duration(tmp)
    if d < MIN_CLIP_S:
        tmp.unlink(missing_ok=True)
        return "failed", None, f"clip too short ({d:.1f}s)"
    tmp.replace(dst)
    out = dict(rec)
    out["clip_path"] = str(dst)
    out["full_audio_available"] = True
    return "ok", out, f"{d:.1f}s"


def stage_clips(args, out: Path, deadline: float) -> None:
    clip_dir = out / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    pending = read_jsonl(out / "candidates_pending_clips.jsonl")
    done = {r["id"] for r in read_jsonl(out / "candidates.jsonl")}
    fails = read_jsonl(out / "clip_failures.jsonl")
    permanent = {f["id"] for f in fails if f.get("status") == "failed"}
    blocked = {f["id"] for f in fails if f.get("status") == "blocked"}
    todo = [r for r in pending if r["id"] not in done and r["id"] not in permanent
            and (args.retry_blocked or r["id"] not in blocked)]
    log(f"stage B: pending={len(pending)} done={len(done)} todo={len(todo)} "
        f"(skipping {len(permanent)} failed, {0 if args.retry_blocked else len(blocked)} blocked)")
    if not todo:
        return
    ok_w = JsonlWriter(out / "candidates.jsonl")
    fail_w = JsonlWriter(out / "clip_failures.jsonl")
    stop = threading.Event()
    consecutive_blocked = 0
    counts = {"ok": 0, "blocked": 0, "failed": 0}
    lock = threading.Lock()

    # Probe sequentially first: if the file server refuses us, find out with a handful of requests
    # instead of 8 parallel workers hammering it.
    idx = 0
    while idx < len(todo) and idx < args.probe and time.time() < deadline:
        st, rec, detail = fetch_clip(todo[idx], clip_dir)
        counts[st] += 1
        log(f"  probe {todo[idx]['id']}: {st} {detail}")
        if rec:
            ok_w.write(rec)
        else:
            fail_w.write({"id": todo[idx]["id"], "status": st, "detail": detail, "ts": time.time()})
        consecutive_blocked = consecutive_blocked + 1 if st == "blocked" else 0
        idx += 1
        time.sleep(1.0)
    if consecutive_blocked >= args.probe:
        log(f"stage B: circuit breaker -- {consecutive_blocked} consecutive HTTP 403 from the file "
            f"server; stopping clip downloads (metadata kept in candidates_pending_clips.jsonl)")
        return

    def work(rec):
        nonlocal consecutive_blocked
        if stop.is_set() or time.time() >= deadline:
            return
        st, out_rec, detail = fetch_clip(rec, clip_dir)
        with lock:
            counts[st] += 1
            if out_rec:
                ok_w.write(out_rec)
            else:
                fail_w.write({"id": rec["id"], "status": st, "detail": detail, "ts": time.time()})
            consecutive_blocked = consecutive_blocked + 1 if st == "blocked" else 0
            if consecutive_blocked >= args.max_consecutive_blocked:
                stop.set()
            n = sum(counts.values())
            if n % 50 == 0:
                log(f"  clips: {counts}")

    with ThreadPoolExecutor(max_workers=min(8, args.workers)) as ex:
        futs = [ex.submit(work, r) for r in todo[idx:]]
        for _ in as_completed(futs):
            pass
    if stop.is_set():
        log("stage B: circuit breaker tripped (too many consecutive 403s)")
    log(f"stage B done: {counts}")


# ----------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=1500, help="metadata pool size to reach (stage A)")
    ap.add_argument("--max-seconds", type=float, default=500, help="wall-clock budget for this run")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=8, help="parallel ffmpeg clip downloads (max 8)")
    ap.add_argument("--api-interval", type=float, default=1.5, help="min seconds between API calls")
    ap.add_argument("--probe", type=int, default=5, help="sequential clip probes before going parallel")
    ap.add_argument("--max-consecutive-blocked", type=int, default=10)
    ap.add_argument("--retry-blocked", action="store_true", help="retry ids that previously got 403")
    ap.add_argument("--allow-vocals", action="store_true", help="keep uploads tagged as vocal songs")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--metadata-only", action="store_true")
    g.add_argument("--clips-only", action="store_true")
    args = ap.parse_args()

    global ALLOW_VOCALS
    ALLOW_VOCALS = args.allow_vocals
    out = args.out
    (out / "clips").mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.max_seconds
    if not args.clips_only:
        stage_metadata(args, out, deadline)
    if not args.metadata_only:
        stage_clips(args, out, deadline)
    n_ok = len(read_jsonl(out / "candidates.jsonl"))
    n_pend = len(read_jsonl(out / "candidates_pending_clips.jsonl"))
    log(f"summary: clip-backed candidates={n_ok}  metadata pool={n_pend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
