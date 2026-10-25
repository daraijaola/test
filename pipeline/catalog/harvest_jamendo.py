#!/opt/av/bin/python
"""
harvest_jamendo.py -- build a candidate-beat pool from Jamendo (Creative Commons) for the
Juice WRLD "Reine" freestyle remix (personal, non-commercial fan project).

This script ONLY harvests: open metadata + short 40 s audio excerpts. No audio analysis.

No Jamendo API key is used (we do not have one, and none is needed):
  * Track selection comes from the open MTG-Jamendo dataset metadata on GitHub raw
    (https://github.com/MTG/mtg-jamendo-dataset, metadata licensed CC BY-NC-SA 4.0):
        data/raw_30s_cleantags.tsv   55,701 tracks: duration + genre/mood-theme/instrument tags
        data/raw.meta.tsv            track title, artist, album, release date, Jamendo URL
        audio_licenses.txt           per-track Creative Commons licence
        derived/music-classification-annotations/music-classification-annotations-clean.tsv
                                     human voice/instrumental labels for ~8.7k tracks
  * Audio comes from Jamendo's public storage endpoint, which serves the full-length mp3 with
    HTTP range support and without a key:
        https://prod-1.storage.jamendo.com/?trackid=<id>&format=mp32     (VBR ~200 kbps)
    (format=mp31 is the 96 kbps variant; mp3d.jamendo.com/download/track/<id>/mp32/ also works.)

Two resumable stages
--------------------
A. select : download (and cache) the metadata files, score every track for fit to a melodic,
            emotional Juice-style remix (genre + mood/theme + instrument weights, penalties for
            clearly unfit styles and for known vocals), assign each track to a stylistic "lane"
            (melodic trap/hip-hop, R&B/soul, afro/caribbean, downtempo/lo-fi, pop/synth, emo/alt
            rock, acoustic guitar, piano ballad, cinematic beats), cap tracks per artist/album, and
            interleave the lanes by quota. The ranked plan (a superset of the target, so missing
            tracks can be backfilled) is written to  <out>/selection.jsonl  (contract schema,
            clip_path = null). Deterministic: re-running gives the same plan.
B. clips  : walk the plan in order; for each track ffmpeg seeks ~30 % into the remote mp3
            (input -ss => HTTP range request, only ~1 MB is fetched), cuts 40 s, re-encodes to
            mp3 128k / 44.1 kHz, validates with ffprobe (>= 20 s) and appends the completed record
            to  <out>/candidates.jsonl  (the contract file). Failures go to clip_failures.jsonl.
            Stops when `--target` clips exist, the plan is exhausted, or `--max-seconds` elapse.

Politeness: at most --workers (<= 8) parallel ffmpeg fetches, retries with backoff, and a circuit
breaker that stops stage B after repeated consecutive server refusals (403/429/5xx).

Usage
-----
  harvest_jamendo.py --target 1500 --max-seconds 500      # both stages, resumable; repeat until done
  harvest_jamendo.py --select-only                         # stage A only (inspect selection.jsonl)
  harvest_jamendo.py --clips-only --workers 8              # stage B only
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

SOURCE = "jamendo"
DEFAULT_OUT = Path("/home/user/test/work/catalog/jamendo")
CA_BUNDLE = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or ""
HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""

MTG_RAW = "https://raw.githubusercontent.com/MTG/mtg-jamendo-dataset/master/"
META_FILES = {
    "raw_30s_cleantags.tsv": MTG_RAW + "data/raw_30s_cleantags.tsv",
    "raw.meta.tsv": MTG_RAW + "data/raw.meta.tsv",
    "audio_licenses.txt": MTG_RAW + "audio_licenses.txt",
    "music-classification-annotations-clean.tsv":
        MTG_RAW + "derived/music-classification-annotations/music-classification-annotations-clean.tsv",
}
AUDIO_URL = "https://prod-1.storage.jamendo.com/?trackid={id}&format=mp32"
PAGE_URL = "https://www.jamendo.com/track/{id}"

CLIP_LEN_S = 40.0
CLIP_POS = 0.30            # start the excerpt 30 % into the track (skip intros)
MIN_TRACK_S = 75.0         # skip sketches / stingers
MAX_TRACK_S = 600.0        # skip long-form ambient pieces and DJ sets
MIN_CLIP_S = 20.0
MAX_PER_ARTIST = 6         # diversity caps
MAX_PER_ALBUM = 3
PLAN_FACTOR = 1.5          # selection.jsonl holds target * PLAN_FACTOR tracks (backfill for failures)
MIN_SCORE = 3.0            # minimum fit score to enter the plan

# ----------------------------------------------------------------------------------------------
# Fit model. Weights are hand-set priors for a melodic, emotional remix bed for Juice WRLD's
# vocal (melodic trap / emo / afro-R&B territory). Positive = fits, negative = clearly unfit.
# ----------------------------------------------------------------------------------------------
# lane -> {genre tag: weight}. A track's lane is the lane with the highest summed genre weight.
LANE_GENRES: dict[str, dict[str, float]] = {
    "trap_hiphop": {"trap": 5, "instrumentalhiphop": 5, "hiphop": 3.5, "abstracthiphop": 3,
                    "rap": 2, "rapfrancais": 1.5, "gangstarap": 1, "gangsta": 1, "breakbeat": 0.5},
    "rnb_soul": {"rnb": 5, "soul": 3.5, "souljazz": 1.5, "gospel": 1, "funk": 1, "popfunk": 1.5,
                 "groove": 1, "smoothjazz": 1},
    "afro_caribbean": {"african": 4, "dancehall": 4, "reggaeton": 4, "ragga": 2.5, "reggae": 3,
                       "island": 2.5, "dub": 1.5, "rocksteady": 1.5, "latin": 1.5, "latino": 1.5,
                       "samba": 1.5, "bossanova": 1.5, "salsa": 1, "tribal": 0.5},
    "downtempo_lofi": {"lofi": 5, "triphop": 4, "trip": 3, "downtempo": 3.5, "downbeat": 3,
                       "chillout": 2.5, "chilloutlounge": 2.5, "lounge": 2, "acidjazz": 1.5,
                       "nujazz": 1.5, "electronica": 1.5, "electrojazz": 1},
    "pop_synth": {"pop": 2, "electropop": 3, "synthpop": 3, "dancepop": 2.5, "indiepop": 3,
                  "instrumentalpop": 3, "synthwave": 2.5, "dreampop": 3, "indietronica": 2.5,
                  "technopop": 1, "chansonfrancaise": 2, "variete": 2, "chanson": 1, "jrock": 1,
                  "electronic": 0.5},
    "emo_alt_rock": {"emo": 5, "poppunk": 5, "emocore": 4, "punkrock": 1.5, "alternative": 1.5,
                     "alternativerock": 2, "grunge": 1.5, "indie": 1.5, "indierock": 2,
                     "indierockpop": 2, "powerpop": 2, "britpop": 1.5, "poprock": 1.5,
                     "postrock": 1.5, "shoegaze": 2, "acousticrock": 3, "guitarrock": 1.5,
                     "rock": 0.5, "rockfrancais": 1},
    "acoustic_guitar": {"singersongwriter": 3, "popfolk": 2.5, "folk": 1, "guitarras": 2.5,
                        "americana": 1},
    "piano_ballad": {"easylistening": 1, "neoclassical": 0.5, "contemporary": 0.5},
    "cinematic_beats": {"soundtrack": 1, "orchestral": 1, "score": 0.5, "symphonic": 0.5},
}
# clearly unfit genres (summed, capped)
BAD_GENRES: dict[str, float] = {
    **{g: -4 for g in ["metal", "heavymetal", "deathmetal", "thrashmetal", "blackmetal", "death",
                       "powermetal", "progressivemetal", "metalcore", "numetal", "grindcore",
                       "hardcore", "noise", "industrial", "technoindustrial", "ebm", "doom",
                       "breakcore", "hardstyle", "hardtek", "tekno", "psytrance", "hardtrance",
                       "gothic", "goth"]},
    **{g: -2.5 for g in ["techno", "minimaltechno", "trance", "trancetechno", "drumnbass", "jungle",
                         "avantgarde", "freejazz", "improvisation", "darkambient", "drone",
                         "droneambient", "baroque", "opera", "medieval", "choral", "choir",
                         "march", "ragtime", "8bit", "chiptune", "cabaret", "eurodance",
                         "acidhouse", "acid", "rave", "darkwave", "darkelectro", "stoner",
                         "rapcore", "glitch", "idm"]},
    **{g: -1.5 for g in ["classical", "experimental", "minimal", "minimalism", "country",
                         "countryrock", "bluegrass", "celtic", "waltz", "tango", "swing", "bebop",
                         "polka", "christian", "hardrock", "rocknroll", "electrohouse", "edm",
                         "club", "progressive", "psychedelic", "krautrock", "spacerock",
                         "dubstep", "hard", "electropunk"]},
    **{g: -0.75 for g in ["ambient", "newage", "house", "techhouse", "technohouse", "dance",
                          "jazz", "blues", "bluesrock", "classicrock", "heavy", "world",
                          "worldfusion", "ethno", "oriental", "middleeastern", "asian",
                          "progressiverock", "jazzrock", "jazzfusion", "fusion", "dancehouse",
                          "electrodance", "disco"]},
}
MOOD_W: dict[str, float] = {
    # emotional / romantic core
    "sad": 3, "emotional": 3, "melancholic": 3, "romantic": 3, "love": 2.5, "ballad": 2.5,
    "sentimental": 2.5, "soulful": 2.5, "urban": 2.5, "depressed": 2, "nostalgic": 2,
    "dream": 2, "melodic": 2, "sexy": 2, "night": 2, "mellow": 2, "gloomy": 1.5, "pensive": 1.5,
    "reflective": 1.5, "beautiful": 1.5, "sweet": 1.5, "deep": 1.5, "dark": 1.5, "chilled": 1.5,
    "laidback": 1.5, "tropical": 1.5, "rain": 1, "warm": 1, "soft": 1, "slow": 1, "relaxing": 1,
    "cool": 1, "groovy": 1, "summer": 1, "hopeful": 1, "thoughtful": 1, "life": 1, "sensible": 1,
    "loved": 1, "quiet": 0.5, "calm": 0.5, "inspiring": 0.5, "contemplative": 0.5, "poetry": 0.5,
    "ethereal": 0.5, "spacey": 0.5, "drive": 0.5, "driving": 0.5, "hypnotic": 0.5,
    # stock-music / unfit themes
    "christmas": -3, "children": -3, "comedy": -2.5, "funny": -2.5, "humor": -2.5, "silly": -2.5,
    "jingle": -2.5, "halloween": -2.5, "horror": -2, "scary": -2, "news": -2, "lullaby": -1,
    "march": -2, "war": -1.5, "battle": -1.5, "aggressive": -1.5, "extreme": -1.5, "angry": -1,
    "violence": -1.5, "chaos": -1.5, "weird": -1.5, "strange": -1, "crazy": -1, "action": -1,
    "trailer": -1, "sport": -1, "corporate": -1, "business": -1, "presentation": -1,
    "advertising": -0.75, "commercial": -0.75, "game": -1, "videogame": -1, "western": -1,
    "festive": -1, "holiday": -1, "religious": -1, "spiritual": -0.5, "meditative": -0.75,
    "yoga": -1, "zen": -0.75, "medieval": -2, "heroic": -0.75, "epic": -0.5, "suspense": -0.75,
    "tension": -0.5, "fast": -0.5, "loud": -0.5, "documentary": -0.5, "nature": -0.5,
    "soundscape": -1, "ambiental": -0.75, "scifi": -0.5, "space": -0.5, "fantasy": -0.5,
}
INSTR_W: dict[str, float] = {
    "beat": 2, "drummachine": 1.5, "acousticguitar": 2, "guitar": 1.5, "piano": 1.5,
    "electricpiano": 1.5, "rhodes": 1.5, "sampler": 1.5, "electricguitar": 1, "synthesizer": 1,
    "drums": 1, "pad": 1, "classicalguitar": 1, "bass": 0.5, "keyboard": 0.5, "strings": 0.5,
    "bell": 0.5, "vocoder": 0.5, "computer": 0.25,
    "bagpipes": -2, "didgeridoo": -1.5, "pipeorgan": -1.5, "accordion": -1, "harpsichord": -1,
    "banjo": -1, "tuba": -1, "choir": -1, "theremin": -1, "kazoo": -2, "bombarde": -1,
    "alboka": -1, "musicalsaw": -1, "oboe": -0.5, "bassoon": -0.5, "timpani": -0.5,
    "cvp509": -0.5, "harmonica": -0.5, "jewsharp": -1, "tinwhistle": -0.5, "erhu": -0.5,
}
FIT_MOODS = {m for m, w in MOOD_W.items() if w >= 2}
GUITARS = {"acousticguitar", "guitar", "classicalguitar", "electricguitar"}
DRUMS = {"beat", "drummachine", "drums", "sampler"}
INSTRUMENTAL_GENRES = {"instrumentalhiphop", "instrumentalpop", "instrumentalrock"}
VOCAL_GENRES = {"rap", "rapfrancais", "gangstarap", "gangsta", "singersongwriter", "chanson",
                "chansonfrancaise", "chansonatexte", "variete", "christianrap", "opera"}

# Lane share of the final pool (interleaved in this proportion).
LANE_QUOTA: dict[str, float] = {
    "trap_hiphop": 0.20, "rnb_soul": 0.08, "afro_caribbean": 0.12, "downtempo_lofi": 0.15,
    "pop_synth": 0.13, "emo_alt_rock": 0.10, "acoustic_guitar": 0.09, "piano_ballad": 0.08,
    "cinematic_beats": 0.05,
}


# ----------------------------------------------------------------------------------------------
# helpers
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


def fetch_meta(meta_dir: Path) -> None:
    """Download the MTG-Jamendo metadata files once (a few MB each; cached)."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    if CA_BUNDLE:
        s.verify = CA_BUNDLE
    for name, url in META_FILES.items():
        dst = meta_dir / name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        delay = 2.0
        for attempt in range(1, 6):
            try:
                r = s.get(url, timeout=120)
                if r.status_code == 200 and r.content:
                    tmp = dst.with_suffix(".part")
                    tmp.write_bytes(r.content)
                    tmp.replace(dst)
                    log(f"meta: fetched {name} ({len(r.content) / 1e6:.1f} MB)")
                    break
                log(f"meta: HTTP {r.status_code} for {name} (attempt {attempt})")
            except requests.RequestException as e:
                log(f"meta: {type(e).__name__} for {name} (attempt {attempt})")
            time.sleep(delay)
            delay *= 2
        else:
            sys.exit(f"could not download {url}")


def native_id(track_id: str) -> int:
    """'track_0000214' -> 214"""
    return int(track_id.split("_")[1])


def load_tracks(meta_dir: Path) -> dict[int, dict]:
    tracks: dict[int, dict] = {}
    with (meta_dir / "raw_30s_cleantags.tsv").open() as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 5:
                continue
            tags = {"genre": [], "mood/theme": [], "instrument": []}
            for t in p[5:]:
                cat, _, val = t.partition("---")
                if cat in tags and val:
                    tags[cat].append(val)
            tracks[native_id(p[0])] = {"artist_id": p[1], "album_id": p[2], "path": p[3],
                                       "duration": float(p[4]), "genre": tags["genre"],
                                       "mood": tags["mood/theme"], "instrument": tags["instrument"]}
    with (meta_dir / "raw.meta.tsv").open() as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 8:
                continue
            t = tracks.get(native_id(p[0]))
            if t is not None:
                t.update(title=p[3].strip(), artist=p[4].strip(), album=p[5].strip(),
                         released=p[6].strip())
    # licences: blocks of "NN/ID.mp3" / "<title> by <artist> from Jamendo: url" / "Available under ...: url"
    cur = None
    with (meta_dir / "audio_licenses.txt").open() as fh:
        for line in fh:
            line = line.strip()
            m = re.fullmatch(r"\d+/(\d+)\.mp3", line)
            if m:
                cur = int(m.group(1))
                continue
            if cur is not None and line.startswith("Available under") and cur in tracks:
                url = line.rsplit(" ", 1)[-1]
                tracks[cur]["license"] = license_str(url)
    # human voice/instrumental labels (only perfect inter-annotator agreement rows are in -clean)
    with (meta_dir / "music-classification-annotations-clean.tsv").open() as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            for a in p[5:]:
                if a.startswith("voice_instrumental---"):
                    lab = a.split("---", 1)[1].split(",")[0]
                    t = tracks.get(native_id(p[0]))
                    if t is not None:
                        t["vi_label"] = lab
    return tracks


def license_str(url: str) -> str:
    """'http://creativecommons.org/licenses/by-nc-sa/2.0/fr/' -> 'CC BY-NC-SA 2.0 FR | <url>'"""
    m = re.search(r"licenses/([a-z-]+)/([\d.]+)(?:/([a-z]{2}))?", url)
    if not m:
        return url
    name = f"CC {m.group(1).upper()} {m.group(2)}" + (f" {m.group(3).upper()}" if m.group(3) else "")
    return f"{name} | {url}"


def instrumental_meta(t: dict) -> bool | None:
    g, ins = set(t["genre"]), set(t["instrument"])
    if t.get("vi_label") == "instrumental":
        return True
    if t.get("vi_label") == "voice":
        return False
    if "voice" in ins or "choir" in ins:
        return False
    if g & INSTRUMENTAL_GENRES:
        return True
    return None


def score_track(t: dict) -> tuple[float, str | None, dict[str, float]]:
    """Return (fit score, lane, per-lane genre scores)."""
    g, moods, ins = set(t["genre"]), set(t["mood"]), set(t["instrument"])
    lane_s = {lane: sum(w for tag, w in gw.items() if tag in g) for lane, gw in LANE_GENRES.items()}
    bad = max(-6.0, sum(BAD_GENRES.get(x, 0.0) for x in g))
    mood = sum(MOOD_W.get(m, 0.0) for m in moods)
    mood = max(-5.0, min(mood, 7.0))
    inst = sum(INSTR_W.get(i, 0.0) for i in ins)
    inst = max(-3.0, min(inst, 4.0))
    fit_mood = bool(moods & FIT_MOODS)

    # mood/instrument-defined lanes (tracks whose genre tags are generic or absent)
    if "piano" in ins and fit_mood and not (ins & DRUMS and lane_s["trap_hiphop"] > 0):
        lane_s["piano_ballad"] += 2.5
    if ins & GUITARS and fit_mood:
        lane_s["acoustic_guitar"] += 1.5 + (1.0 if "acousticguitar" in ins else 0.0)
    # cinematic lane only for orchestral pieces that also have a beat (orchestral hip-hop style)
    if lane_s["cinematic_beats"] > 0:
        lane_s["cinematic_beats"] += 2.5 if (ins & DRUMS or lane_s["trap_hiphop"] > 0) else -9

    lane = max(lane_s, key=lambda k: lane_s[k])
    if lane_s[lane] <= 0:
        return -99.0, None, lane_s
    # genre part: best lane counts fully, a second matching lane adds a little (cross-over styles)
    others = sorted((v for k, v in lane_s.items() if k != lane and v > 0), reverse=True)
    genre_part = min(lane_s[lane], 7.0) + (0.3 * min(others[0], 4.0) if others else 0.0)
    score = genre_part + bad + mood + 0.75 * inst

    vi = instrumental_meta(t)
    if vi is True:
        score += 1.0
    elif vi is False:
        score -= 2.5          # sung/rapped vocals would clash with Juice's vocal (only with --allow-vocals)
    elif g & VOCAL_GENRES:
        score -= 1.0          # vocal-heavy genre, vocals likely
    # gentle preference for typical song lengths (2-5 min)
    if not (120 <= t["duration"] <= 330):
        score -= 0.5
    return score, lane, lane_s


def clip_start_for(dur: float) -> float:
    """Start ~30 % in (skip intros) but keep the full 40 s inside the track (3 s tail margin)."""
    start = min(CLIP_POS * dur, dur - CLIP_LEN_S - 3.0)
    return round(max(0.0, start), 2)


def make_record(tid: int, t: dict, score: float, lane: str) -> dict:
    tags = ([f"lane:{lane}"] + [f"genre:{x}" for x in t["genre"]] + [f"mood:{x}" for x in t["mood"]]
            + [f"instrument:{x}" for x in t["instrument"]])
    if t.get("released"):
        tags.append(f"year:{t['released'][:4]}")
    lic = t.get("license")
    if lic:
        tags.append("license:" + lic.split(" | ")[0].replace("CC ", "").lower().replace(" ", "_"))
    if t.get("vi_label"):
        tags.append(f"annot:{t['vi_label']}")
    tags.append(f"fit:{score:.1f}")
    return {
        "id": f"{SOURCE}:{tid}",
        "source": SOURCE,
        "title": t.get("title") or "",
        "artist": t.get("artist") or "",
        "page_url": PAGE_URL.format(id=tid),
        "clip_path": None,
        "clip_start_s": clip_start_for(t["duration"]),
        "duration_full_s": round(t["duration"], 1),
        "license": lic,
        "full_audio_url": AUDIO_URL.format(id=tid),
        "full_audio_available": False,   # flipped to True once a clip was actually fetched from it
        "bpm_meta": None,                # MTG-Jamendo metadata carries no tempo
        "key_meta": None,                # ... and no key
        "tags": tags,
        "is_instrumental_meta": instrumental_meta(t),
        "query": f"mtg-jamendo:raw_30s_cleantags lane={lane} (genre/mood/instrument fit score)",
        "is_reference": False,
    }


# ----------------------------------------------------------------------------------------------
# Stage A: selection
# ----------------------------------------------------------------------------------------------
def stage_select(args, out: Path) -> list[dict]:
    meta_dir = out / "meta"
    fetch_meta(meta_dir)
    tracks = load_tracks(meta_dir)
    log(f"select: {len(tracks)} tracks in MTG-Jamendo raw_30s")

    by_lane: dict[str, list[tuple[float, int]]] = collections.defaultdict(list)
    for tid, t in tracks.items():
        if not (MIN_TRACK_S <= t["duration"] <= MAX_TRACK_S):
            continue
        if instrumental_meta(t) is False and not args.allow_vocals:
            continue      # known sung/rapped vocals (annotation or 'voice' tag): would clash with Juice
        score, lane, _ = score_track(t)
        if lane is None or score < MIN_SCORE:
            continue
        by_lane[lane].append((score, tid))
    for lane in by_lane:
        # highest score first; ties broken by newer track id (more recent catalogue, still online)
        by_lane[lane].sort(key=lambda x: (-x[0], -x[1]))
    log("select: eligible per lane: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(by_lane.items())))

    # Weighted round-robin interleave of lanes with artist/album caps. Every prefix of the plan is
    # (roughly) lane-balanced, so stopping stage B at any point keeps the pool diverse.
    plan_n = int(args.target * PLAN_FACTOR)
    per_artist: collections.Counter = collections.Counter()
    per_album: collections.Counter = collections.Counter()
    ptr = {lane: 0 for lane in LANE_QUOTA}
    credit = {lane: 0.0 for lane in LANE_QUOTA}
    plan: list[dict] = []
    while len(plan) < plan_n:
        live = [l for l in LANE_QUOTA if ptr[l] < len(by_lane.get(l, []))]
        if not live:
            break
        tot = sum(LANE_QUOTA[l] for l in live)
        for l in live:
            credit[l] += LANE_QUOTA[l] / tot
        lane = max(live, key=lambda l: credit[l])
        credit[lane] -= 1.0
        lst = by_lane[lane]
        while ptr[lane] < len(lst):
            score, tid = lst[ptr[lane]]
            ptr[lane] += 1
            t = tracks[tid]
            if per_artist[t["artist_id"]] >= MAX_PER_ARTIST or per_album[t["album_id"]] >= MAX_PER_ALBUM:
                continue
            per_artist[t["artist_id"]] += 1
            per_album[t["album_id"]] += 1
            plan.append(make_record(tid, t, score, lane))
            break

    sel_path = out / "selection.jsonl"
    tmp = sel_path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        for i, r in enumerate(plan):
            fh.write(json.dumps({**r, "plan_rank": i}, ensure_ascii=False) + "\n")
    tmp.replace(sel_path)
    lanes = collections.Counter(r["tags"][0] for r in plan)
    log(f"select: plan of {len(plan)} written to {sel_path}: " + ", ".join(f"{k}={v}" for k, v in sorted(lanes.items())))
    return plan


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
    """Returns (status, completed_record_or_None, detail). status in ok|missing|blocked|failed."""
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
    err = ""
    for attempt in range(3):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            err = (p.stderr or "")[-400:]
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc, err = -1, "ffmpeg timeout"
        if rc == 0 and tmp.exists():
            break
        tmp.unlink(missing_ok=True)
        if "404" in err:
            return "missing", None, "HTTP 404 (track no longer on Jamendo)"
        if "403" in err or "429" in err:
            return "blocked", None, "HTTP 403/429"
        time.sleep(3 * (attempt + 1))   # transient (5xx / network): back off and retry
    else:
        return "failed", None, err.strip().splitlines()[-1] if err.strip() else "ffmpeg failed"
    d = ffprobe_duration(tmp)
    if d < MIN_CLIP_S:
        tmp.unlink(missing_ok=True)
        return "failed", None, f"clip too short ({d:.1f}s)"
    tmp.replace(dst)
    out = dict(rec)
    out.pop("plan_rank", None)
    out["clip_path"] = str(dst)
    out["full_audio_available"] = True
    return "ok", out, f"{d:.1f}s"


def stage_clips(args, out: Path, deadline: float) -> None:
    clip_dir = out / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    for stale in clip_dir.glob(".*.part.mp3"):
        stale.unlink(missing_ok=True)       # leftovers of a killed run
    plan = read_jsonl(out / "selection.jsonl")
    done = {r["id"] for r in read_jsonl(out / "candidates.jsonl")}
    fails = read_jsonl(out / "clip_failures.jsonl")
    skip = {f["id"] for f in fails if f.get("status") in ("missing", "failed")}
    blocked = {f["id"] for f in fails if f.get("status") == "blocked"}
    need = args.target - len(done)
    log(f"clips: plan={len(plan)} done={len(done)} need={max(0, need)} "
        f"(skipping {len(skip)} missing/failed{'' if args.retry_blocked else f', {len(blocked)} blocked'})")
    if need <= 0:
        return
    todo = [r for r in plan if r["id"] not in done and r["id"] not in skip
            and (args.retry_blocked or r["id"] not in blocked)]
    ok_w = JsonlWriter(out / "candidates.jsonl")
    fail_w = JsonlWriter(out / "clip_failures.jsonl")
    counts = collections.Counter()
    lock = threading.Lock()
    stop = threading.Event()
    consecutive_blocked = [0]

    def handle(rec, st, res, detail):
        with lock:
            counts[st] += 1
            if st == "ok":
                ok_w.write(res)
                consecutive_blocked[0] = 0
            else:
                fail_w.write({"id": rec["id"], "status": st, "detail": detail,
                              "url": rec["full_audio_url"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
                if st == "blocked":
                    consecutive_blocked[0] += 1
                    if consecutive_blocked[0] >= 10:
                        log("clips: 10 consecutive refusals from the server -- stopping (circuit breaker)")
                        stop.set()
            if counts["ok"] >= need:
                stop.set()
            tot = sum(counts.values())
            if tot % 50 == 0:
                log(f"clips: {dict(counts)} total_done={len(done) + counts['ok']}")

    it = iter(todo)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        running = {}
        def submit_next():
            if stop.is_set() or time.time() >= deadline:
                return False
            # do not over-submit beyond what is still needed (plus a small margin for failures)
            with lock:
                if counts["ok"] + len(running) >= need + args.workers:
                    return len(running) > 0
            rec = next(it, None)
            if rec is None:
                return False
            running[ex.submit(fetch_clip, rec, clip_dir)] = rec
            return True
        for _ in range(args.workers):
            if not submit_next():
                break
        while running:
            fut = next(as_completed(list(running)))
            rec = running.pop(fut)
            try:
                st, res, detail = fut.result()
            except Exception as e:    # never let one bad track kill the run
                st, res, detail = "failed", None, f"{type(e).__name__}: {e}"
            handle(rec, st, res, detail)
            submit_next()
    log(f"clips: run finished {dict(counts)}; total clips={len(done) + counts['ok']} / target {args.target}"
        + (" (time budget reached)" if time.time() >= deadline else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--target", type=int, default=1500, help="number of clip-backed candidates wanted")
    ap.add_argument("--max-seconds", type=float, default=500, help="wall-clock budget for this run")
    ap.add_argument("--workers", type=int, default=8, help="parallel clip downloads (max 8)")
    ap.add_argument("--select-only", action="store_true")
    ap.add_argument("--clips-only", action="store_true")
    ap.add_argument("--reselect", action="store_true", help="rebuild selection.jsonl even if it exists")
    ap.add_argument("--allow-vocals", action="store_true",
                    help="keep tracks known to have vocals (excluded by default: Jamendo is not a mainstream source)")
    ap.add_argument("--retry-blocked", action="store_true", help="retry tracks that got 403/429 before")
    args = ap.parse_args()
    args.workers = max(1, min(8, args.workers))
    deadline = time.time() + args.max_seconds
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.clips_only and (args.reselect or args.select_only or not (args.out / "selection.jsonl").exists()):
        stage_select(args, args.out)
    if not args.select_only:
        stage_clips(args, args.out, deadline)


if __name__ == "__main__":
    main()
