#!/opt/av/bin/python
"""
harvest_archive.py -- build a candidate-beat pool from the Internet Archive (archive.org).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial fan project).
This script ONLY harvests: item metadata from the public archive.org APIs plus short 40 s audio
excerpts taken from the musical body of each track. No audio analysis is done here (the BPM / key /
voice-vs-instrumental hints come from descriptor files archive.org itself publishes per track).

Three resumable stages
----------------------
A. search   : for every entry of QUERY_PLAN, page through
                  https://archive.org/advancedsearch.php?q=<query>&fl[]=identifier,title,...&sort[]=downloads desc
              (mediatype:audio, junk collections such as audiobooks / podcasts / sample-CD ISOs / live
              concert tapes excluded, items > 2 GB excluded). Result docs are buffered in state.json.
B. expand   : walk the plan round-robin (ROUND_QUOTA tracks per query per round, so niche queries are
              not crowded out). For each buffered item: GET https://archive.org/metadata/<identifier>,
              pick the best mp3 rendition per audio original (VBR MP3 > 128Kbps MP3 > other mp3), drop
              skits / intros / a cappellas / DJ mixes, take at most --per-item tracks (default 5; the
              instrumental versions first, the rest spread evenly over the tracklist). Diversity caps:
              <= MAX_ITEMS_PER_CREATOR items per creator, <= MAX_ITEMS_PER_LABEL items per specific
              collection (label), soft de-duplication on normalised artist+title. Accepted tracks go to
                  <out>/candidates_pending_clips.jsonl   (contract schema + private "_ess_*" keys)
C. clips    : for every pending track, ffmpeg seeks into the remote mp3 (input -ss => HTTP range
              requests, only the needed bytes are fetched), cuts 40 s starting ~30 % into the track
              (intro skipped, 3 s tail margin kept), re-encodes to mp3 128k / 44.1 kHz, validates with
              ffprobe (>= 20 s) or deletes it. Then the track's archive.org Essentia descriptor files
              (*_esslow.json.gz ~20 kB: bpm + key; *_esshigh.json.gz ~2 kB: voice/instrumental, genre,
              mood classifiers) are read when they exist. Completed rows are appended to
                  <out>/candidates.jsonl            <- the contract file (only clip-backed rows)
              Failures go to <out>/clip_failures.jsonl and are not retried (unless --retry-failed).

Metadata precedence: explicit text (track title / file name / item subjects) beats the Essentia
estimate. The source of each hint is recorded in `tags` ("bpm_src:title", "key_src:essentia",
"instr_src:subjects", ...), and the Essentia classifier outputs are stored as "essentia:<name>=<v>" tags.

Politeness: all JSON API calls share one limiter (>= --api-interval s apart, default 0.2 s => <= 5/s)
with exponential backoff on 429/5xx. Clip downloads use at most --workers ffmpeg processes (<= 8),
each run under `nice -n 19` to keep the busy CPU free for separation jobs.

Usage
-----
  harvest_archive.py --target 1000 --max-seconds 500     # all stages, resumable; re-run until done
  harvest_archive.py --search-only                       # stages A+B (metadata pool only)
  harvest_archive.py --clips-only --workers 8            # stage C only
  harvest_archive.py --stats                             # summarise the output JSONL
  harvest_archive.py --reclassify                        # re-run the clean-up / labelling pass only
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, unquote

import requests

SOURCE = "archive"
SEARCH_API = "https://archive.org/advancedsearch.php"
META_API = "https://archive.org/metadata/"
DOWNLOAD = "https://archive.org/download/"
DETAILS = "https://archive.org/details/"
DEFAULT_OUT = Path("/home/user/test/work/catalog/archive")
CA_BUNDLE = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or ""
HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
UA = "remix-catalog-harvester/1.0 (personal non-commercial fan project; polite, low volume)"

CLIP_LEN_S = 40.0
MIN_TRACK_S = 60.0           # skip stingers / loops / skits
MAX_TRACK_S = 600.0          # skip DJ mixes, continuous albums, hour-long sets
MIN_CLIP_S = 20.0
MAX_ITEM_BYTES = 2_000_000_000
MAX_ITEMS_PER_CREATOR = 3
MAX_ITEMS_PER_LABEL = 30     # per specific collection (generic collections are not capped)
ROUND_QUOTA = 15             # tracks per query per round
SEARCH_ROWS = 100
OVERSHOOT = 1.08             # stage B builds a pool this much larger than --target (clip failures)

CONTRACT_KEYS = ["id", "source", "title", "artist", "page_url", "clip_path", "clip_start_s",
                 "duration_full_s", "license", "full_audio_url", "full_audio_available", "bpm_meta",
                 "key_meta", "tags", "is_instrumental_meta", "query", "is_reference"]

# Collections that are never music beds (audiobooks, podcasts, sermons, radio, sample-CD ISOs,
# live-concert tape archives, 78 rpm transfers) -- excluded in the search query itself.
BAD_COLLECTIONS = [
    "librivoxaudio", "audio_bookspoetry", "podcasts", "podcasts_miscellaneous", "podcasts_compilations",
    "audio_religion", "audio_islamic", "samplecds", "radioprograms", "oldtimeradio", "etree",
    "GratefulDead", "78rpm", "georgeblood", "audio_news", "audio_tech", "audio_podcast",
    "radio-programs", "radio_programs", "otrr", "audio_foreign", "sermons",
]
# Big catch-all collections: not used for the per-label diversity cap.
GENERIC_COLLECTIONS = {
    "opensource_audio", "community", "netlabels", "audio_music", "folksoundomy", "folksoundomy_music",
    "folksoundomy_audio_y2k", "hifidelity", "hifidelity_potpourri", "jamendo-albums", "audio",
    "soundcloud-collection", "opensource", "cratediggers", "lemon-tunes", "vaporwave",
    "instrumentalscomng",
}
JUNK_ITEM_RE = re.compile(
    r"podcast|episode|\bep\.? ?\d{2,}|audiobook|librivox|sermon|quran|qur'an|bible|lecture|interview|"
    r"radio show|discography|nonstop|non-stop|megamix|mega mix|dj set|dj mix|mixed by|live at|live in|"
    r"concert|karaoke|sample pack|samplepack|drum kit|drumkit|loop kit|sound kit|construction kit|"
    r"happy birthday|ringtone|sound effects?|sfx|asmr|meditation|sleep music|white noise|binaural|"
    r"\d+ ?hours?\b|full album playlist|top \d{2,}|best of \d{4}|hits? (19|20)\d\d|\d{2,3} songs",
    re.I)
SKIP_TRACK_RE = re.compile(
    r"\b(intro|outro|skit|interlude|a ?cc?apella|acappella|acapela|vocals? only|vocal stem|stems?|"
    r"preview|snippet|teaser|jingle|commercial|sample|loop|sfx|bonus video"
    r")\b", re.I)
INSTR_RE = re.compile(
    r"\b(?:instrumentals?|instru|type ?beats?|beat ?tapes?|free ?beats?|riddims?|backing tracks?|"
    r"no vocals|without vocals|beats?)\b|\binst\.", re.I)
VOCAL_RE = re.compile(r"\b(?:feat|ft|featuring|with vocals|vocal (?:mix|version)|lyrics?)\b", re.I)
INSTR_SUBJECTS = {"instrumental", "instrumentals", "instrumental hip hop", "instrumental hip-hop",
                  "hip hop instrumental", "instrumental hiphop", "instrumentalhiphop", "beats", "type beat",
                  "type beats", "beat tape", "beattape", "lofi beats", "lo-fi beats", "chillhop", "riddim",
                  "trap beat", "trap beats", "trap instrumental", "rnb instrumental", "r&b instrumental",
                  "piano instrumental", "guitar instrumental", "acoustic instrumental",
                  "instrumentals.com.ng"}

MP3_RANK = {"VBR MP3": 0, "128Kbps MP3": 1, "160Kbps MP3": 2, "192Kbps MP3": 3, "256Kbps MP3": 4,
            "320Kbps MP3": 5, "MP3": 6, "96Kbps MP3": 7, "64Kbps MP3": 8, "56Kbps MP3": 9,
            "32Kbps MP3": 10}
AUDIO_ORIG_FORMATS = set(MP3_RANK) | {"Flac", "24bit Flac", "WAVE", "Ogg Vorbis", "Apple Lossless Audio",
                                      "AIFF", "Windows Media Audio", "M4A", "Advanced Audio Coding",
                                      "Opus", "MPEG-4 Audio"}

# ----------------------------------------------------------------------------------------------
# Query plan: (label, Lucene query, cap in tracks, max tracks per item).
# Ordered by expected fit to a melodic, emotional Juice WRLD / afro-R&B remix; walked round-robin.
# "CC" in the label = Creative-Commons-licensed sources (netlabels, Jamendo mirror) or CC filter.
# ----------------------------------------------------------------------------------------------
CC = 'licenseurl:(*creativecommons* OR *publicdomain*)'
JAM = "collection:jamendo-albums"
NET = "collection:netlabels"
QUERY_PLAN: list[tuple[str, str, int, int]] = [
    # --- melodic trap / emo rap / type beats -------------------------------------------------
    ("juice_style_type_beats",
     'title:("juice wrld" OR "nick mira" OR "lil peep" OR xxxtentacion OR "trippie redd" OR "iann dior" '
     'OR "lil uzi" OR "the kid laroi" OR "polo g" OR "lil tecca") AND (title:"type beat" OR '
     'title:instrumental OR subject:instrumental OR subject:"type beat")', 40, 3),
    ("type_beat_any", '(title:"type beat" OR subject:"type beat" OR subject:"type beats")', 140, 3),
    ("melodic_trap_instr",
     'subject:("melodic trap" OR "melodic rap" OR "emo rap" OR "emo trap" OR "sad trap" OR "guitar trap") '
     'AND (subject:instrumental OR title:instrumental OR title:beat OR subject:beats OR subject:beat)', 40, 4),
    ("trap_beats", '(subject:("trap beat" OR "trap beats" OR "trap instrumental") OR '
                   'title:("trap beat" OR "trap instrumental" OR "trap instrumentals"))', 70, 3),
    ("netlabel_trap_CC", f'{NET} AND subject:(trap)', 40, 4),
    ("jamendo_trap_emotional_CC",
     f'{JAM} AND subject:(trap) AND subject:(emotional OR sad OR melancholic OR dark OR love OR romantic)', 50, 3),
    ("jamendo_beats_CC",
     f'{JAM} AND title:(beat OR beats OR instrumental OR instrumentals OR "type beat") AND '
     'subject:(hiphop OR trap OR rnb OR lofi OR rap OR urban)', 60, 3),
    # --- instrumental hip-hop / lo-fi / boom-bap / trip-hop ----------------------------------
    ("netlabel_instr_hiphop_CC",
     f'{NET} AND subject:("instrumental hip hop" OR "instrumental hip-hop" OR "hip hop instrumental" '
     'OR instrumentalhiphop OR "instrumental hiphop")', 100, 4),
    ("instr_hiphop_other",
     'subject:("instrumental hip hop" OR "hip hop instrumental" OR "hip-hop instrumental" OR '
     f'"instrumental hip-hop") AND -{NET}', 80, 4),
    ("beattapes", '(subject:(beats OR beattape OR "beat tape" OR "beat-tape") AND '
                  f'(subject:instrumental OR {NET} OR subject:"hip hop"))', 80, 4),
    ("lofi_hiphop", 'subject:("lofi hip hop" OR "lo-fi hip hop" OR "lofi beats" OR chillhop OR '
                    '"lo-fi beats" OR "chill hop")', 80, 4),
    ("netlabel_lofi_CC", f'{NET} AND subject:(lofi OR "lo-fi" OR chillhop OR "chill hop")', 40, 4),
    ("jamendo_lofi_CC", f'{JAM} AND subject:(lofi OR chillhop OR "lo-fi")', 40, 3),
    ("boom_bap_instr", 'subject:("boom bap" OR boombap) AND (subject:instrumental OR subject:beats OR '
                       'title:instrumental OR title:beat OR title:beats)', 40, 4),
    ("trip_hop_sad", 'subject:("trip hop" OR "trip-hop" OR triphop OR downtempo) AND '
                     'subject:(sad OR melancholic OR melancholy OR emotional OR rainy OR dark)', 40, 3),
    ("jamendo_hiphop_emotional_CC",
     f'{JAM} AND subject:(hiphop OR rap) AND subject:(emotional OR sad OR melancholic OR romantic)', 70, 3),
    ("sad_instrumentals",
     'subject:(sad OR emotional OR melancholic) AND subject:(instrumental) AND '
     'subject:("hip hop" OR hiphop OR rap OR trap OR beats OR rnb OR piano OR guitar)', 50, 4),
    ("generic_instr_beats", '(title:instrumental AND title:(beat OR beats))', 50, 3),
    # --- R&B / soul / French R&B ---------------------------------------------------------------
    ("rnb_instrumentals",
     '(subject:("rnb instrumental" OR "r&b instrumental" OR "rnb beat" OR "r&b beat") OR '
     'title:("rnb instrumental" OR "r&b instrumental" OR "rnb beat" OR "r&b type beat" OR '
     '"rnb type beat") OR (subject:(rnb OR "r&b") AND subject:instrumental))', 60, 3),
    ("netlabel_rnb_soul_CC", f'{NET} AND subject:(rnb OR "r&b" OR "neo soul" OR "neo-soul" OR soul)', 50, 4),
    ("jamendo_rnb_romantic_CC",
     f'{JAM} AND subject:(rnb OR "r&b" OR neosoul OR soul) AND '
     'subject:(romantic OR love OR emotional OR sad OR mellow OR sensual)', 60, 2),
    ("french_rnb", 'subject:("french rnb" OR "rnb francais" OR "r&b francais" OR "pop urbaine" OR '
                   '"rnb français" OR "r&b français")', 30, 3),
    ("kizomba_zouk", 'subject:(kompa OR zouk OR "zouk love" OR kizomba OR "ghetto zouk")', 25, 3),
    # --- afro / amapiano / dancehall ----------------------------------------------------------
    ("instrumentals_ng_afro",
     'collection:instrumentalscomng AND title:(afro OR afropop OR "afro pop" OR love OR slow OR rnb OR '
     '"type beat" OR highlife OR amapiano OR emotional OR sad OR guitar OR piano OR romantic OR wedding)',
     70, 1),
    ("instrumentals_ng_any", 'collection:instrumentalscomng', 40, 1),
    ("afro_instr", 'subject:(afrobeat OR afrobeats OR afropop OR "afro pop" OR "afro beat" OR afroswing '
                   'OR "afro-fusion" OR "afro fusion") AND (subject:instrumental OR title:instrumental OR '
                   'title:beat OR subject:beat OR subject:beats OR title:"type beat")', 50, 3),
    ("jamendo_afro_CC", f'{JAM} AND subject:(afrobeat OR afro OR afropop OR afrobeats)', 50, 3),
    ("amapiano", '(subject:amapiano OR title:amapiano)', 30, 3),
    ("riddims", '(subject:riddim OR title:riddim) AND (subject:dancehall OR subject:instrumental OR '
                'title:instrumental OR subject:reggae)', 40, 3),
    ("jamendo_dancehall_CC", f'{JAM} AND subject:(reggaeton OR dancehall)', 30, 3),
    ("netlabel_afro_dancehall_CC",
     f'{NET} AND subject:(afro OR afrobeat OR highlife OR afrobeats OR dancehall OR reggae)', 30, 3),
    # --- guitar / acoustic / piano ballads ------------------------------------------------------
    ("guitar_instrumentals",
     f'subject:("guitar instrumental" OR "acoustic instrumental" OR "acoustic guitar") AND '
     f'(subject:instrumental OR {CC})', 50, 3),
    ("netlabel_acoustic_CC",
     f'{NET} AND subject:(acoustic OR guitar) AND subject:(instrumental OR folk OR "singer-songwriter")', 30, 3),
    ("jamendo_acoustic_sad_CC",
     f'{JAM} AND subject:(acoustic OR guitar) AND subject:(sad OR emotional OR melancholic OR romantic)', 50, 2),
    ("piano_instrumentals",
     '(subject:("piano instrumental" OR "sad piano" OR "piano ballad" OR "emotional piano") OR '
     '(subject:piano AND subject:instrumental AND subject:(sad OR emotional OR melancholic OR romantic '
     'OR "hip hop" OR chill)))', 40, 3),
    ("jamendo_piano_sad_CC",
     f'{JAM} AND subject:piano AND subject:(sad OR emotional OR melancholic) AND '
     'subject:(hiphop OR pop OR rnb OR lofi OR chillout)', 40, 2),
    # --- pop-punk / emo / alt ballads ---------------------------------------------------------
    ("jamendo_emo_punk_CC",
     f'{JAM} AND subject:(punk OR emo OR poppunk OR "pop punk") AND '
     'subject:(sad OR emotional OR melancholic OR love)', 40, 2),
    ("netlabel_emo_CC", f'{NET} AND subject:(emo OR "pop punk" OR "pop-punk" OR "post-hardcore")', 25, 3),
    ("jamendo_alt_ballads_CC",
     f'{JAM} AND subject:(poprock OR "pop rock" OR indie OR alternative) AND '
     'subject:(ballad OR sad OR melancholic)', 30, 2),
    # --- synth-pop / cinematic / drill --------------------------------------------------------
    ("jamendo_synthpop_CC",
     f'{JAM} AND subject:(synthpop OR electropop OR synthwave) AND '
     'subject:(emotional OR sad OR melancholic OR romantic OR love)', 40, 2),
    ("netlabel_synthpop_CC", f'{NET} AND subject:(synthpop OR "synth pop" OR "synth-pop" OR chillwave OR '
                             'dreampop OR "dream pop")', 30, 3),
    ("cinematic_hiphop", 'subject:(cinematic OR orchestral OR epic) AND '
                         'subject:("hip hop" OR hiphop OR trap OR beats)', 40, 3),
    ("drill_beats", 'subject:(drill OR "uk drill" OR "melodic drill") AND (subject:beat OR '
                    'subject:instrumental OR title:beat OR title:instrumental OR title:"type beat")', 30, 3),
]

TAG_STOP = {"music", "audio", "mp3", "album", "single", "ep", "free", "download", "netlabel", "netlabels",
            "creative commons", "cc", "free music", "royalty free", "royalty-free", "music, instruments",
            "instruments", "various artists", "va", "compilation"}


# ----------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------
LOG_FH = None


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG_FH:
        LOG_FH.write(line + "\n")
        LOG_FH.flush()


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


def as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def txt(x) -> str:
    if isinstance(x, list):
        x = "; ".join(str(v) for v in x if v)
    return "" if x is None else re.sub(r"\s+", " ", str(x)).strip()


def safe_id(rid: str) -> str:
    """Filesystem-safe id; same alphabet as analyze_catalog.safe(), kept <= 150 chars (hash suffix)."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", rid)
    if len(s) > 150:
        s = s[:139] + "_" + hashlib.sha1(rid.encode()).hexdigest()[:10]
    return s


def make_id(identifier: str, fname: str) -> str:
    rid = f"{SOURCE}:{identifier}/{fname}"
    if len(re.sub(r"[^A-Za-z0-9_.-]+", "_", rid)) > 150:      # keep ids short and collision-free
        rid = f"{SOURCE}:{identifier}/#{hashlib.sha1(fname.encode()).hexdigest()[:12]}"
    return rid


def parse_length(v) -> float | None:
    """archive.org 'length' is either seconds ('134.3') or 'mm:ss' / 'h:mm:ss'."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        if ":" in s:
            sec = 0.0
            for p in s.split(":"):
                sec = sec * 60 + float(p)
            return sec
        return float(s)
    except ValueError:
        return None


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def split_subjects(subj) -> list[str]:
    out: list[str] = []
    for s in as_list(subj):
        for part in re.split(r"[;,]", str(s)):
            p = re.sub(r"\s+", " ", part).strip().lower()
            if p and len(p) <= 40 and p not in out:
                out.append(p)
    return out


# --- explicit BPM / key hints in titles and file names ("prodw!ll yafeelme g#min 95", "90 bpm") ---
BPM_RES = [re.compile(r"(?<!\d)(\d{2,3}(?:\.\d)?)\s*bpm\b", re.I),
           re.compile(r"\bbpm\s*[:=_-]?\s*(\d{2,3}(?:\.\d)?)(?!\d)", re.I)]
KEY_RE = re.compile(r"(?<![a-z0-9])([a-g])\s?(#|♯|b|♭|sharp|flat)?[\s_-]?(minor|min|major|maj)(?![a-z])",
                    re.I)
NUM_RE = re.compile(r"(?<![\d.])(\d{2,3})(?![\d.])")


def text_bpm_key(*texts: str) -> tuple[float | None, str | None]:
    bpm = key = None
    for t in texts:
        if not t:
            continue
        t2 = t.replace("_", " ")
        if bpm is None:
            for rx in BPM_RES:
                m = rx.search(t2)
                if m and 50 <= float(m.group(1)) <= 220:
                    bpm = float(m.group(1))
                    break
        if key is None:
            m = KEY_RE.search(t2)
            if m:
                acc = m.group(2) or ""
                acc = "#" if acc.lower() in ("#", "♯", "sharp") else ("b" if acc else "")
                mode = "minor" if m.group(3).lower().startswith("min") else "major"
                key = f"{m.group(1).upper()}{acc} {mode}"
                if bpm is None:   # "G#min 95" / "90 Gmin": a bare number right next to the key token
                    near = t2[max(0, m.start() - 6):m.end() + 6]
                    for n in NUM_RE.findall(near):
                        if 55 <= int(n) <= 200:
                            bpm = float(n)
                            break
    return bpm, key


PROD_BY_RE = re.compile(r"\bprod(?:\.|uced)?\s*by\s*:?\s*([^()\[\]|]{2,30}?)\s*(?:via\b|[()\[\]|]|-\s|$)", re.I)
BY_VIA_RE = re.compile(r"\bby\s+([^()\[\]|]{2,30}?)\s+via\b", re.I)
SONG_ARTIST_RE = re.compile(r"^\s*([^\-–()\[\]|]{2,40}?)\s+[-–]\s+\S")
SITE_ARTISTS = {"instrumentals.com.ng", "instrumentals com ng", "instrumentalstv.com", "instrumentalstv",
                "music", "unknown", "various", "various artists"}


def guess_artist(artist: str, *texts: str) -> str:
    """Fill empty / placeholder (download-site) artists from the title: 'prod by X', 'by X via site',
    or 'Artist - Song (Instrumental)'; else keep the placeholder / 'unknown'."""
    if artist and artist.lower() not in SITE_ARTISTS:
        return artist
    for rx in (PROD_BY_RE, BY_VIA_RE, SONG_ARTIST_RE):
        for t in texts:
            m = rx.search(t or "")
            if m:
                cand = m.group(1).strip(" .-_")
                if cand and cand.lower() not in SITE_ARTISTS and not re.match(r"^[\d\W_]+$", cand) \
                        and not re.search(r"\b(free|type beat|beat|instrumental)\b", cand, re.I):
                    return cand
    return artist or "unknown"


# item-level evidence must be stronger than track-level evidence: a bare "beats" in an album's
# free-text subjects ("hard-hitting beats") says nothing about the album being instrumental.
INSTR_STRONG_RE = re.compile(
    r"\b(?:instrumentals?|instru|type ?beats?|beat ?tapes?|free ?beats?|riddims?|backing tracks?|"
    r"no vocals|without vocals)\b|\binst\.", re.I)
VOCAL_SUBJ_RE = re.compile(r"vocal|lyric|singer|songwriter|rapper|a ?cc?apella|spoken|chanson", re.I)


def text_instrumental(track_text: str, item_title: str, subjects: list[str]) -> tuple[bool | None, str | None]:
    """Explicit text signals only. Track-level text wins over item-level text:
    track title/file name  >  exact instrumental-type subjects (vetoed by vocal subjects)  >  item title."""
    if INSTR_RE.search(track_text):
        return True, "title"
    if VOCAL_RE.search(track_text):
        return False, "title"
    instr_subj = any(s in INSTR_SUBJECTS for s in subjects)
    vocal_subj = any(VOCAL_SUBJ_RE.search(s) for s in subjects)
    if instr_subj and not vocal_subj:
        return True, "subjects"
    if vocal_subj and not instr_subj:
        return False, "subjects"
    if not vocal_subj and INSTR_STRONG_RE.search(item_title):
        return True, "item_title"
    return None, None


def essentia_voice(tags: list[str]) -> tuple[bool | None, str | None]:
    """Fallback: archive.org Essentia voice/instrumental classifier, only when confident (>= 0.80)."""
    for t in tags:
        m = re.match(r"essentia:voice_instrumental=(\w+)@([\d.]+)$", t)
        if m and float(m.group(2)) >= 0.80:
            return m.group(1) == "instrumental", "essentia"
    return None, None


# ----------------------------------------------------------------------------------------------
# HTTP client: one shared limiter for all JSON API traffic, retries with backoff
# ----------------------------------------------------------------------------------------------
class Http:
    def __init__(self, interval: float):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        if CA_BUNDLE:
            self.s.verify = CA_BUNDLE
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
        self.s.mount("https://", adapter)
        self.interval = interval
        self.lock = threading.Lock()
        self.next_slot = 0.0
        self.calls = 0

    def _wait_slot(self):
        with self.lock:
            now = time.time()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
            self.calls += 1
        if slot > now:
            time.sleep(slot - now)

    def get(self, url: str, params=None, tries: int = 4, timeout: float = 60, raw: bool = False):
        delay = 3.0
        for attempt in range(1, tries + 1):
            self._wait_slot()
            try:
                r = self.s.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.content if raw else r.json()
                if r.status_code in (403, 404, 410):
                    return None
                if r.status_code == 429:
                    delay = max(delay, float(r.headers.get("Retry-After") or 10))
                log(f"HTTP {r.status_code} {url[:90]} (attempt {attempt})")
            except (requests.RequestException, ValueError) as e:
                log(f"HTTP error {type(e).__name__} {url[:90]} (attempt {attempt})")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        return None


# ----------------------------------------------------------------------------------------------
# state (search buffers + per-query counters + diversity counters)
# ----------------------------------------------------------------------------------------------
class State:
    def __init__(self, path: Path):
        self.path = path
        self.d = json.loads(path.read_text()) if path.exists() else {}
        self.d.setdefault("queries", {})
        self.d.setdefault("items_done", {})        # identifier -> n tracks accepted (0 = rejected)
        self.d.setdefault("creator_items", {})
        self.d.setdefault("label_items", {})
        self.d.setdefault("title_keys", [])
        self.lock = threading.Lock()

    def q(self, label: str) -> dict:
        return self.d["queries"].setdefault(label, {"page": 0, "buffer": [], "exhausted": False,
                                                    "accepted": 0, "items": 0, "num_found": None})

    def save(self):
        with self.lock:
            self.d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d))
            tmp.replace(self.path)


# ----------------------------------------------------------------------------------------------
# Stage A: search
# ----------------------------------------------------------------------------------------------
def full_query(q: str) -> str:
    bad = " OR ".join(BAD_COLLECTIONS)
    return f"mediatype:audio AND ({q}) AND -collection:({bad}) AND item_size:[1 TO {MAX_ITEM_BYTES}]"


def search_page(http: Http, q: str, page: int) -> tuple[list[dict], int] | None:
    params = [("q", full_query(q)), ("rows", SEARCH_ROWS), ("page", page), ("output", "json"),
              ("sort[]", "downloads desc")]
    for f in ("identifier", "title", "creator", "licenseurl", "subject", "collection", "item_size",
              "downloads", "date"):
        params.append(("fl[]", f))
    data = http.get(SEARCH_API, params=params)
    if not data or "response" not in data:
        return None
    resp = data["response"]
    return resp.get("docs") or [], int(resp.get("numFound") or 0)


def refill_buffer(http: Http, st: State, label: str, q: str) -> bool:
    qs = st.q(label)
    if qs["exhausted"]:
        return False
    res = search_page(http, q, qs["page"] + 1)
    if res is None:
        log(f"  search {label}: request failed (will retry next run)")
        return False
    docs, num = res
    qs["page"] += 1
    qs["num_found"] = num
    keep = ["identifier", "title", "creator", "licenseurl", "subject", "collection", "item_size"]
    qs["buffer"].extend({k: d.get(k) for k in keep} for d in docs)
    if len(docs) < SEARCH_ROWS or qs["page"] * SEARCH_ROWS >= num:
        qs["exhausted"] = True
    return bool(docs)


def item_prefilter(doc: dict, st: State) -> str | None:
    """Cheap filter on search fields. Returns a reject reason or None."""
    ident = doc.get("identifier") or ""
    if not ident or ident in st.d["items_done"]:
        return "seen"
    title = txt(doc.get("title"))
    if JUNK_ITEM_RE.search(title) or JUNK_ITEM_RE.search(ident):
        return "junk_title"
    try:
        if int(doc.get("item_size") or 0) > MAX_ITEM_BYTES:
            return "too_big"
    except (TypeError, ValueError):
        pass
    creator = norm_key(txt(doc.get("creator")))
    if creator and st.d["creator_items"].get(creator, 0) >= MAX_ITEMS_PER_CREATOR:
        return "creator_cap"
    for c in as_list(doc.get("collection")):
        if c not in GENERIC_COLLECTIONS and not str(c).startswith("fav-") and \
                st.d["label_items"].get(c, 0) >= MAX_ITEMS_PER_LABEL:
            return "label_cap"
    return None


# ----------------------------------------------------------------------------------------------
# Stage B: expand items into track records
# ----------------------------------------------------------------------------------------------
def pick_tracks(meta: dict, per_item: int) -> list[dict]:
    """Best mp3 rendition per audio original; filtered and spread over the tracklist."""
    files = meta.get("files") or []
    by_name = {f.get("name"): f for f in files if f.get("name")}
    groups: dict[str, list[dict]] = {}
    for f in files:
        fmt = f.get("format") or ""
        if fmt not in MP3_RANK or str(f.get("private", "")).lower() == "true":
            continue
        orig = f.get("original") if f.get("source") == "derivative" else None
        root = orig if orig in by_name else f["name"]
        groups.setdefault(root, []).append(f)
    # Essentia descriptor files, keyed by the audio file they were computed from
    ess: dict[str, dict] = {}
    for f in files:
        fmt = f.get("format") or ""
        if fmt in ("Essentia High GZ", "Essentia Low GZ"):
            kind = "high" if "High" in fmt else "low"
            ess.setdefault(f.get("original") or "", {})[kind] = f["name"]
    tracks = []
    for root, cands in groups.items():
        best = min(cands, key=lambda f: MP3_RANK.get(f.get("format"), 99))
        rootf = by_name.get(root, best)
        dur = parse_length(best.get("length")) or parse_length(rootf.get("length"))
        if dur is None or dur < MIN_TRACK_S or dur > MAX_TRACK_S:
            continue
        ttl = txt(best.get("title") or rootf.get("title"))
        stem = Path(best["name"]).stem
        label_text = f"{ttl} {stem}"
        if SKIP_TRACK_RE.search(ttl or stem.replace("_", " ")):
            continue
        e = dict(ess.get(root) or ess.get(best["name"]) or {})
        # the high-level file is usually derived from the low-level one, so match by stem as well
        for kind, suf in (("high", "_esshigh.json.gz"), ("low", "_esslow.json.gz")):
            for cand in (Path(root).stem + suf, stem + suf):
                if kind not in e and cand in by_name:
                    e[kind] = cand
        try:
            trackno = int(re.match(r"\d+", str(best.get("track") or rootf.get("track") or "")).group())
        except (AttributeError, ValueError):
            trackno = 10_000
        tracks.append({"file": best, "root": rootf, "dur": dur, "title": ttl, "stem": stem,
                       "label_text": label_text, "ess": e, "trackno": trackno})
    tracks.sort(key=lambda t: (t["trackno"], t["file"]["name"]))
    if len(tracks) <= per_item:
        return tracks
    # instrumental versions first, then spread the remaining picks evenly over the tracklist
    instr = [t for t in tracks if INSTR_RE.search(t["label_text"])]
    chosen = instr[:per_item]
    rest = [t for t in tracks if t not in chosen]
    k = per_item - len(chosen)
    if k > 0 and rest:
        if k == 1:
            idx = [len(rest) // 2]
        else:
            idx = sorted({round(i * (len(rest) - 1) / (k - 1)) for i in range(k)})
        chosen += [rest[i] for i in idx]
    chosen.sort(key=lambda t: (t["trackno"], t["file"]["name"]))
    return chosen


def clip_start_for(dur: float) -> float:
    """Start ~30 % in (skip intros) but keep the full 40 s inside the track (3 s tail margin)."""
    start = min(0.30 * dur, dur - CLIP_LEN_S - 3.0)
    return round(max(0.0, start), 2)


def build_records(doc: dict, meta: dict, label: str, q: str, per_item: int, st: State) -> list[dict]:
    md = meta.get("metadata") or {}
    if str(md.get("access-restricted-item", "")).lower() == "true" or meta.get("is_dark"):
        return []                          # lending / streaming-only items: no open file access
    ident = md.get("identifier") or doc["identifier"]
    item_title = txt(md.get("title") or doc.get("title"))
    item_creator = txt(md.get("creator") or doc.get("creator"))
    lic = txt(md.get("licenseurl") or doc.get("licenseurl")) or None
    subjects = split_subjects(md.get("subject") or doc.get("subject"))
    collections = [c for c in as_list(md.get("collection") or doc.get("collection"))
                   if c and not str(c).startswith("fav-")]
    st.d.setdefault("item_info", {})[ident] = {"title": item_title, "subjects": subjects}
    base_tags = [s for s in subjects if s not in TAG_STOP and norm_key(s) != norm_key(item_title)]
    base_tags += [f"ia_collection:{c}" for c in collections]
    if lic and re.search(r"creativecommons|publicdomain", lic, re.I):
        base_tags.append("license:cc")
    recs = []
    for t in pick_tracks(meta, per_item):
        f = t["file"]
        title = t["title"] or re.sub(r"[_]+", " ", t["stem"]).strip()
        artist = txt(f.get("creator") or f.get("artist") or t["root"].get("creator")) or item_creator
        artist = guess_artist(artist, title, t["stem"].replace("_", " "), item_title)
        tkey = norm_key(artist) + "|" + norm_key(re.sub(r"\(.*?\)|\[.*?\]", "", title))
        if tkey in st.d["title_keys"]:
            continue                       # same song already harvested from another upload
        track_text = f"{title} {t['stem'].replace('_', ' ')}"
        bpm, key = text_bpm_key(title, t["stem"], item_title if len(meta.get("files") or []) < 15 else "")
        instr, instr_src = text_instrumental(track_text, item_title, subjects)
        tags = list(base_tags)
        genre = txt(f.get("genre") or t["root"].get("genre"))
        if genre and len(genre) <= 40:
            tags.append(f"genre:{genre.lower()}")
        album = txt(f.get("album") or t["root"].get("album")) or item_title
        if album and len(album) <= 80:
            tags.append(f"album:{album}")
        if bpm is not None:
            tags.append("bpm_src:title")
        if key is not None:
            tags.append("key_src:title")
        if instr_src:
            tags.append(f"instr_src:{instr_src}")
        rid = make_id(ident, f["name"])
        recs.append({
            "id": rid,
            "source": SOURCE,
            "title": title,
            "artist": artist,
            "page_url": DETAILS + quote(ident),
            "clip_path": None,
            "clip_start_s": clip_start_for(t["dur"]),
            "duration_full_s": round(t["dur"], 2),
            "license": lic,
            "full_audio_url": DOWNLOAD + quote(ident) + "/" + quote(f["name"]),
            "full_audio_available": True,
            "bpm_meta": bpm,
            "key_meta": key,
            "tags": tags,
            "is_instrumental_meta": instr,
            "query": f"{label}: {q}",
            "is_reference": False,
            "_ess_high": (DOWNLOAD + quote(ident) + "/" + quote(t["ess"]["high"])) if t["ess"].get("high") else None,
            "_ess_low": (DOWNLOAD + quote(ident) + "/" + quote(t["ess"]["low"])) if t["ess"].get("low") else None,
            "_mp3_format": f.get("format"),
        })
        st.d["title_keys"].append(tkey)
    return recs


def stage_search_expand(args, out: Path, http: Http, st: State, deadline: float) -> None:
    pending_path = out / "candidates_pending_clips.jsonl"
    pending = read_jsonl(pending_path)
    done = {r["id"] for r in read_jsonl(out / "candidates.jsonl")}
    fails = read_jsonl(out / "clip_failures.jsonl")
    n_fail = Counter(r["id"] for r in fails)
    failed = {r["id"] for r in fails if r.get("status") == "failed"} | {i for i, n in n_fail.items() if n >= 2}
    seen_ids = {r["id"] for r in pending} | done
    usable = len(done) + sum(1 for r in pending if r["id"] not in done and r["id"] not in failed)
    goal = int(args.target * OVERSHOOT)
    writer = JsonlWriter(pending_path)
    log(f"stage A/B: usable pool={usable} (clips done={len(done)}, failed={len(failed)}), goal={goal}")
    plan = [p for p in QUERY_PLAN if not args.only or p[0] in args.only.split(",")]
    rnd = 0
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        while usable < goal and time.time() < deadline:
            rnd += 1
            progressed = False
            # Level-based round robin (stable across resumed runs): every live query is first brought
            # up to level * ROUND_QUOTA tracks before any query goes beyond it.
            live = [st.q(lb)["accepted"] for lb, _, cap, _ in plan
                    if st.q(lb)["accepted"] < cap and not (st.q(lb)["exhausted"] and not st.q(lb)["buffer"])]
            if not live:
                log("stage A/B: every query exhausted or capped")
                break
            level = min(live) // ROUND_QUOTA + 1
            for label, q, cap, per_item in plan:
                if usable >= goal or time.time() >= deadline:
                    break
                qs = st.q(label)
                quota = min(cap, level * ROUND_QUOTA)
                if qs["accepted"] >= quota or (qs["exhausted"] and not qs["buffer"]):
                    continue
                per = min(per_item, args.per_item)
                while qs["accepted"] < quota and usable < goal and time.time() < deadline:
                    # make sure enough candidate items are buffered for this round
                    if len(qs["buffer"]) < 8 and not qs["exhausted"]:
                        if not refill_buffer(http, st, label, q) and not qs["buffer"]:
                            break       # search failed or empty: try again next round / next run
                    batch = []
                    while qs["buffer"] and len(batch) < 8:
                        doc = qs["buffer"].pop(0)
                        why = item_prefilter(doc, st)
                        if why is None and doc["identifier"] not in [b["identifier"] for b in batch]:
                            batch.append(doc)
                    if not batch:
                        if qs["exhausted"] and not qs["buffer"]:
                            break
                        continue
                    metas = list(pool.map(lambda d: http.get(META_API + quote(d["identifier"])), batch))
                    for doc, meta in zip(batch, metas):
                        ident = doc["identifier"]
                        if qs["accepted"] >= quota or usable >= goal:
                            qs["buffer"].insert(0, doc)      # not consumed; keep for the next round
                            continue
                        if not meta or not meta.get("files"):
                            st.d["items_done"][ident] = 0
                            continue
                        recs = [r for r in build_records(doc, meta, label, q, per, st) if r["id"] not in seen_ids]
                        st.d["items_done"][ident] = len(recs)
                        if not recs:
                            continue
                        for r in recs:
                            writer.write(r)
                            seen_ids.add(r["id"])
                        qs["accepted"] += len(recs)
                        qs["items"] += 1
                        usable += len(recs)
                        progressed = True
                        creator = norm_key(txt(doc.get("creator")))
                        if creator:
                            st.d["creator_items"][creator] = st.d["creator_items"].get(creator, 0) + 1
                        for c in as_list(doc.get("collection")):
                            if c not in GENERIC_COLLECTIONS and not str(c).startswith("fav-"):
                                st.d["label_items"][c] = st.d["label_items"].get(c, 0) + 1
                    st.save()
                log(f"  round {rnd} {label:<30} tracks={qs['accepted']:<4} items={qs['items']:<4} "
                    f"buffer={len(qs['buffer']):<4} found={qs['num_found']} pool={usable}")
            if not progressed:
                log("stage A/B: every query exhausted or capped")
                break
    finally:
        pool.shutdown(wait=True)
        st.save()
    log(f"stage A/B done: usable pool={usable} api_calls={http.calls}")


# ----------------------------------------------------------------------------------------------
# Stage C: clips + Essentia descriptors
# ----------------------------------------------------------------------------------------------
def ffprobe_duration(path: Path) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return float(p.stdout.strip() or 0)
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def fetch_clip(rec: dict, clip_dir: Path) -> tuple[str, Path | None, str]:
    sid = re.sub(r"\.mp3$", "", safe_id(rec["id"]), flags=re.I)
    dst = clip_dir / f"{sid}.mp3"
    if dst.exists() and ffprobe_duration(dst) >= MIN_CLIP_S:
        return "ok", dst, "reused"
    tmp = clip_dir / f".{sid}.part.mp3"
    cmd = ["nice", "-n", "19", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if HTTPS_PROXY:
        cmd += ["-http_proxy", HTTPS_PROXY]       # ffmpeg ignores https_proxy env, pass explicitly
    if CA_BUNDLE:
        cmd += ["-ca_file", CA_BUNDLE, "-tls_verify", "1"]
    cmd += ["-user_agent", UA, "-rw_timeout", "45000000", "-reconnect", "1", "-reconnect_delay_max", "8",
            "-ss", f"{rec['clip_start_s']:.2f}", "-t", f"{CLIP_LEN_S:.0f}",   # input seek => HTTP range
            "-i", rec["full_audio_url"],
            "-vn", "-map_metadata", "-1", "-ar", "44100", "-b:a", "128k", "-f", "mp3", "-y", str(tmp)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        err = (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return "transient", None, "ffmpeg timeout"
    if p.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        detail = err.splitlines()[-1][:200] if err else f"rc={p.returncode}"
        if re.search(r"5XX|50[0-9]|timed out|Connection reset|I/O error|End of file|Immediate exit", err, re.I):
            return "transient", None, detail
        return "failed", None, detail
    d = ffprobe_duration(tmp)
    if d < MIN_CLIP_S:
        tmp.unlink(missing_ok=True)
        return "failed", None, f"clip too short ({d:.1f}s)"
    tmp.replace(dst)
    return "ok", dst, f"{d:.1f}s"


ESS_HIGH_KEYS = ["voice_instrumental", "genre_rosamerica", "genre_dortmund", "mood_sad", "mood_relaxed",
                 "mood_happy", "mood_party", "mood_aggressive", "mood_acoustic", "mood_electronic",
                 "danceability"]


def essentia_hints(http: Http, rec: dict) -> dict:
    """Read archive.org's own Essentia descriptors (computed on the full track) if published."""
    out: dict = {"tags": []}
    if rec.get("_ess_low"):
        raw = http.get(rec["_ess_low"], raw=True, tries=2, timeout=40)
        try:
            d = json.loads(gzip.decompress(raw)) if raw else None
        except (OSError, ValueError):
            d = None
        if d:
            bpm = (d.get("rhythm") or {}).get("bpm")
            tonal = d.get("tonal") or {}
            if isinstance(bpm, (int, float)) and 40 <= bpm <= 250:
                out["bpm"] = round(float(bpm), 1)
            if tonal.get("key_key") and tonal.get("key_scale"):
                out["key"] = f"{tonal['key_key']} {tonal['key_scale']}"
                ks = tonal.get("key_strength")
                if isinstance(ks, (int, float)):
                    out["tags"].append(f"essentia:key_strength={ks:.2f}")
    if rec.get("_ess_high"):
        raw = http.get(rec["_ess_high"], raw=True, tries=2, timeout=40)
        try:
            d = json.loads(gzip.decompress(raw)) if raw else None
        except (OSError, ValueError):
            d = None
        hl = (d or {}).get("highlevel") or {}
        for k in ESS_HIGH_KEYS:
            v = hl.get(k)
            if not isinstance(v, dict) or "value" not in v:
                continue
            prob = v.get("probability")
            if k.startswith("mood_") or k == "danceability":
                # store P(positive class), e.g. essentia:mood_sad=0.62
                pos = k.replace("mood_", "") if k.startswith("mood_") else "danceable"
                p = (v.get("all") or {}).get(pos)
                if isinstance(p, (int, float)):
                    out["tags"].append(f"essentia:{k}={p:.2f}")
            else:
                out["tags"].append(f"essentia:{k}={v['value']}@{prob:.2f}" if isinstance(prob, (int, float))
                                   else f"essentia:{k}={v['value']}")
            if k == "voice_instrumental" and isinstance(prob, (int, float)):
                out["voice_instrumental"] = (v["value"], float(prob))
    return out


def finalize(rec: dict, clip: Path, hints: dict) -> dict:
    r = dict(rec)
    r["clip_path"] = str(clip)
    r["artist"] = guess_artist(r.get("artist") or "", r.get("title") or "")
    tags = list(r.get("tags") or [])
    if r.get("bpm_meta") is None and hints.get("bpm") is not None:
        r["bpm_meta"] = hints["bpm"]
        tags.append("bpm_src:essentia")
    if r.get("key_meta") is None and hints.get("key"):
        r["key_meta"] = hints["key"]
        tags.append("key_src:essentia")
    vi = hints.get("voice_instrumental")
    if r.get("is_instrumental_meta") is None and vi and vi[1] >= 0.80:
        r["is_instrumental_meta"] = vi[0] == "instrumental"
        tags.append("instr_src:essentia")
    tags += hints.get("tags", [])
    r["tags"] = tags
    return {k: r.get(k) for k in CONTRACT_KEYS}


def stage_clips(args, out: Path, http: Http, deadline: float) -> None:
    clip_dir = out / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    pending = read_jsonl(out / "candidates_pending_clips.jsonl")
    done = {r["id"] for r in read_jsonl(out / "candidates.jsonl")}
    fails = read_jsonl(out / "clip_failures.jsonl")
    n_fail = Counter(r["id"] for r in fails)
    # permanent = hard failure once, or transient (5xx / timeout) twice
    failed = {r["id"] for r in fails if r.get("status") == "failed"} | {i for i, n in n_fail.items() if n >= 2}
    todo = [r for r in pending if r["id"] not in done and (args.retry_failed or r["id"] not in failed)]
    if args.target:   # only clip what the target still needs (+50 spare for failures)
        todo = [] if len(done) >= args.target else todo[: args.target - len(done) + 50]
    log(f"stage C: pending={len(pending)} done={len(done)} failed={len(failed)} todo={len(todo)}")
    if not todo:
        return
    ok_w = JsonlWriter(out / "candidates.jsonl")
    fail_w = JsonlWriter(out / "clip_failures.jsonl")
    counts = Counter()
    lock = threading.Lock()
    consecutive_fail = [0]
    stop = threading.Event()

    def work(rec):
        if stop.is_set() or time.time() >= deadline:
            return
        st, clip, detail = fetch_clip(rec, clip_dir)
        if st == "ok":
            try:
                hints = essentia_hints(http, rec)
            except Exception as e:   # descriptor problems must never cost us the clip
                hints = {"tags": []}
                log(f"  essentia error {rec['id']}: {e}")
            row = finalize(rec, clip, hints)
        with lock:
            counts[st] += 1
            if st == "ok":
                ok_w.write(row)
                consecutive_fail[0] = 0
            else:
                fail_w.write({"id": rec["id"], "status": st, "detail": detail, "ts": time.time()})
                consecutive_fail[0] += 1
                if consecutive_fail[0] >= 25:
                    stop.set()
            n = sum(counts.values())
            if n % 50 == 0:
                log(f"  clips: {dict(counts)}")

    with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as ex:
        futs = [ex.submit(work, r) for r in todo]
        for _ in as_completed(futs):
            pass
    if stop.is_set():
        log("stage C: circuit breaker tripped (25 consecutive failures) -- check network / archive.org")
    log(f"stage C done: {dict(counts)}")


# ----------------------------------------------------------------------------------------------
def ident_of(row: dict) -> str:
    return unquote(row["page_url"].split("/details/", 1)[1])


def normalize_rows(out: Path, st: State, http: Http | None = None, refetch: bool = False) -> None:
    """Idempotent clean-up pass over candidates.jsonl (run at the end of every invocation, single
    threaded): drop rows whose clip vanished, de-duplicate ids, re-apply artist guessing, and re-derive
    is_instrumental_meta with the current rules from the cached item title/subjects (state.json
    'item_info'; with refetch=True missing item info is fetched from /metadata/<id>/metadata)."""
    path = out / "candidates.jsonl"
    raw = read_jsonl(path)
    info = st.d.setdefault("item_info", {})
    if refetch and http is not None:
        missing = sorted({ident_of(r) for r in raw} - set(info))
        log(f"normalize: fetching item metadata for {len(missing)} items")
        with ThreadPoolExecutor(max_workers=4) as ex:
            for ident, res in zip(missing, ex.map(lambda i: http.get(META_API + quote(i) + "/metadata"), missing)):
                md = (res or {}).get("result") or {}
                if md:
                    info[ident] = {"title": txt(md.get("title")), "subjects": split_subjects(md.get("subject"))}
        st.save()
    if refetch and http is not None:
        # backfill high-level Essentia descriptors for rows harvested before the stem-matching fix
        pend = {p["id"]: p for p in read_jsonl(out / "candidates_pending_clips.jsonl")}
        need = [r for r in raw if (pend.get(r["id"]) or {}).get("_ess_low")
                and not any(t.startswith("essentia:voice_instrumental") for t in r["tags"])]
        log(f"normalize: backfilling Essentia high-level tags for {len(need)} rows")
        def high(r):
            url = pend[r["id"]]["_ess_low"].replace("_esslow.json.gz", "_esshigh.json.gz")
            return essentia_hints(http, {"_ess_high": url})
        with ThreadPoolExecutor(max_workers=4) as ex:
            for r, h in zip(need, ex.map(high, need)):
                r["tags"] = r["tags"] + [t for t in h.get("tags", []) if t not in r["tags"]]
    rows, seen = [], set()
    for r in raw:
        if r["id"] in seen or not r.get("clip_path") or not Path(r["clip_path"]).exists():
            continue
        seen.add(r["id"])
        r["artist"] = guess_artist(r.get("artist") or "", r.get("title") or "")
        it = info.get(ident_of(r))
        if it is not None:
            stem = Path(unquote(r["full_audio_url"].rsplit("/", 1)[-1])).stem.replace("_", " ")
            instr, src = text_instrumental(f"{r['title']} {stem}", it["title"], it["subjects"])
            tags = [t for t in r["tags"] if not t.startswith("instr_src:")]
            if instr is None:
                instr, src = essentia_voice(tags)
            r["is_instrumental_meta"] = instr
            r["tags"] = tags + ([f"instr_src:{src}"] if src else [])
        rows.append({k: r.get(k) for k in CONTRACT_KEYS})
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def stats(out: Path) -> None:
    rows = read_jsonl(out / "candidates.jsonl")
    print(f"clip-backed candidates: {len(rows)}")
    qc = Counter(r["query"].split(":")[0] for r in rows)
    for k, v in qc.most_common():
        print(f"  {k:<32} {v}")
    print("instrumental:", Counter(str(r["is_instrumental_meta"]) for r in rows))
    print("license cc:", sum(1 for r in rows if "license:cc" in r["tags"]), " null:",
          sum(1 for r in rows if not r["license"]))
    print("bpm_meta:", sum(1 for r in rows if r["bpm_meta"] is not None),
          " key_meta:", sum(1 for r in rows if r["key_meta"]))
    print("items:", len({r["page_url"] for r in rows}), " artists:", len({r["artist"].lower() for r in rows}))
    size = sum(Path(r["clip_path"]).stat().st_size for r in rows if Path(r["clip_path"]).exists())
    print(f"clip bytes: {size / 1e6:.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=1000, help="clip-backed candidates to reach")
    ap.add_argument("--max-seconds", type=float, default=500, help="wall-clock budget for this run")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=8, help="parallel ffmpeg clip downloads (max 8)")
    ap.add_argument("--per-item", type=int, default=5, help="max tracks per archive.org item (<= 5)")
    ap.add_argument("--api-interval", type=float, default=0.2, help="min seconds between API calls")
    ap.add_argument("--only", default="", help="comma-separated query labels to run (debug)")
    ap.add_argument("--retry-failed", action="store_true", help="retry ids in clip_failures.jsonl")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--search-only", action="store_true", help="stages A+B only")
    g.add_argument("--clips-only", action="store_true", help="stage C only")
    g.add_argument("--stats", action="store_true", help="summarise candidates.jsonl and exit")
    g.add_argument("--reclassify", action="store_true",
                   help="only re-run the clean-up pass, fetching item metadata it lacks (no new clips)")
    args = ap.parse_args()
    args.per_item = max(1, min(5, args.per_item))

    out = args.out
    if args.stats:
        stats(out)
        return 0
    (out / "clips").mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    global LOG_FH
    LOG_FH = (out / "logs" / "harvest.log").open("a")
    deadline = time.time() + args.max_seconds
    http = Http(args.api_interval)
    st = State(out / "state.json")
    if not (args.clips_only or args.reclassify):
        stage_search_expand(args, out, http, st, deadline)
    if not (args.search_only or args.reclassify):
        stage_clips(args, out, http, deadline)
    normalize_rows(out, st, http, refetch=args.reclassify)
    n_ok = len(read_jsonl(out / "candidates.jsonl"))
    n_pend = len(read_jsonl(out / "candidates_pending_clips.jsonl"))
    log(f"summary: clip-backed candidates={n_ok}  metadata pool={n_pend}  api_calls={http.calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
