#!/usr/bin/env python3
"""Merge, validate and deduplicate the per-source beat catalogs into one catalog.

Inputs   work/catalog/<source>/candidates.jsonl   (every sub-directory that has one)
Outputs  work/catalog/catalog.jsonl               merged rows (contract keys first, then extras)
         work/catalog/coverage.md                 counts per source / genre bucket / licence ... + known gaps
         work/catalog/merge_dropped.jsonl         every row that was dropped, with the reason
         work/catalog/.merge_probe_cache.json     ffprobe results keyed by clip path (+ size, mtime)

Pipeline
  1. load    : parse every line; rows with bad JSON, missing contract keys or a repeated id are dropped.
  2. validate: the clip must exist, be non-empty and ffprobe must report an audio stream of >= 20 s.
               ffprobe runs under `nice -n 19`, a few at a time, and is cached, so re-runs are almost free.
  3. normalise: strings trimmed, numbers coerced (bpm outside 40-250 or 0 -> null, duration <= 0 -> null),
               key_meta written as "<Note> <major|minor>" with sharps (the raw spelling is kept as a key_raw: tag),
               booleans coerced, tags de-duplicated, full_audio_available forced true when a full_audio_url exists.
  4. annotate: extra fields `genre_bucket` (one of BUCKETS, inferred from each source's own category
               tag / query label, refined with title+query keywords), `license_class` (cc-by-nc-sa, arr, ...),
               `clip_dur_s` (ffprobe), `also_in` (ids of duplicates folded into this row). Flags are tags:
               juice_own_beat (an instrumental of one of Juice's own songs), warn:possible_juice_vocal,
               control:original_beat (Dadju "Reine" itself is never a new-beat candidate).
  5. dedup   : rows are linked when they share a track-level page_url (archive.org pages are item level,
               so its file URL is used instead), a full_audio_url, a clip file, an explicit also_in:<id> tag,
               or the same normalised (primary artist, title) key -- titles keep version words such as
               "instrumental"/"remix"/"acoustic", so a beat is never folded into its vocal original, and
               two key-matched rows whose full durations differ by > max(8 s, 6 %) stay separate.
               Per linked group the kept row is the best by: full audio available > licence quality
               (open CC > CC-ND > other > all-rights-reserved > unknown) > curated source priority >
               longer clip > richer metadata. The kept row inherits is_reference=true if any member was a
               reference, and missing bpm/key/instrumental metadata from the others (tag meta_from:<id>).

No audio is decoded (ffprobe only reads headers), so it is light on a busy CPU.

Usage: merge_catalog.py [--catalog-dir DIR] [--workers 3] [--min-clip 20] [--max-seconds N] [--dry-run]
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

CONTRACT_KEYS = ["id", "source", "title", "artist", "page_url", "clip_path", "clip_start_s", "duration_full_s",
                 "license", "full_audio_url", "full_audio_available", "bpm_meta", "key_meta", "tags",
                 "is_instrumental_meta", "query", "is_reference"]
EXTRA_KEYS = ["genre_bucket", "license_class", "clip_dur_s", "also_in"]

# Curated / stable-URL sources win ties between duplicates (after full audio and licence).
SOURCE_PRIORITY = {"refs": 7, "jamendo": 6, "fma": 5, "ccmixter": 5, "archive": 4, "soundcloud": 3, "deezer": 2}
# Output order: references first, then sources in this order (original order inside a source).
SOURCE_ORDER = ["refs", "deezer", "soundcloud", "archive", "jamendo", "fma", "ccmixter"]

BUCKETS = ["melodic_trap_emo", "sad_hiphop", "hiphop_boombap", "rnb_soul", "afro", "amapiano", "caribbean_dancehall",
           "french_urbaine", "poppunk_emo_rock", "acoustic_guitar", "piano_ballad", "lofi_chill", "drill",
           "synthpop_pop", "cinematic"]
BUCKET_DESC = {
    "melodic_trap_emo": "melodic trap / emo rap / guitar trap / Juice WRLD & Nick Mira type beats",
    "sad_hiphop": "sad / pain hip-hop (Rod Wave, Polo G, NBA YoungBoy, Lil Tjay type beats, sad instrumentals)",
    "hiphop_boombap": "general hip-hop / rap / boom-bap / instrumental hip-hop & beat tapes",
    "rnb_soul": "R&B / alt-R&B / trapsoul / soul",
    "afro": "afrobeats / afro-pop / afro-R&B / afroswing / African",
    "amapiano": "amapiano",
    "caribbean_dancehall": "dancehall / reggae / riddims / kizomba / zouk / kompa / reggaeton / latin",
    "french_urbaine": "French R&B / pop urbaine (Dadju, Tayc, Aya, GIMS ...)",
    "poppunk_emo_rock": "pop-punk / emo / alt & indie rock ballads",
    "acoustic_guitar": "acoustic / campfire guitar / folk / singer-songwriter",
    "piano_ballad": "piano ballads & piano instrumentals",
    "lofi_chill": "lo-fi hip-hop / chill / downtempo / trip-hop",
    "drill": "melodic / UK drill",
    "synthpop_pop": "synth-pop / electro-pop / pop",
    "cinematic": "cinematic / orchestral / soundtrack hip-hop",
}

# Keyword rules (checked in this order) used to refine a broad source category or to classify a row
# whose category is unknown. Text = folded title + query + genre tags.
KEYWORD_RULES = [
    ("amapiano", r"amapiano|log ?drum"),
    ("drill", r"\bdrill\b"),
    ("caribbean_dancehall", r"dancehall|riddim|reggae(?!ton)|reggaeton|kizomba|\bzouk|kompa|konpa|dembow|\bsoca\b|"
                            r"\bdub\b|bachata|latin|bossa"),
    ("afro", r"\bafro|naija|highlife|burna|wizkid|\brema\b|ckay|omah lay|davido|asake|\btems\b|fireboy|african|"
             r"afrobeat"),
    ("french_urbaine", r"francais|french|pop urbaine|dadju|\btayc\b|aya nakamura|\bgims\b|ninho|\bmhd\b|"
                       r"\bamour\b|chanson|variete|\btriste\b|melancoli|instru rap|rap fr"),
    ("sad_hiphop", r"rod wave|polo g|youngboy|lil tjay|\bpain\b|kevin gates|lil durk|nocap|quando rondo|"
                   r"sad instrumentals|sad piano trap"),
    ("lofi_chill", r"lo-?fi|chillhop|trip-?hop|triphop|downtempo|chill-?out|chillout|\bchill\b|study|wonky|ambient"),
    ("piano_ballad", r"piano"),
    ("poppunk_emo_rock", r"pop.?punk|\bemo\b(?!\s*(rap|trap))|\bpunk|alt(ernative)?.?rock|indie.?rock|\brock\b|grunge|shoegaze|"
                         r"power.?pop|machine gun kelly|\bmgk\b|ballad"),
    ("acoustic_guitar", r"acoustic|campfire|\bfolk|singer.?songwriter|guitar"),
    ("cinematic", r"cinematic|orchestral|\bepic\b|soundtrack|\bfilm|\bscore\b|strings|cello"),
    ("synthpop_pop", r"synth|\b80s\b|retro|electro.?pop|dream.?pop|hyper.?pop|new wave|\bsynthpop\b"),
    ("rnb_soul", r"r&b|\brnb\b|r'n'b|r and b|\bsoul|trapsoul|6lack|bryson tiller|chris brown|weeknd"),
    ("hiphop_boombap", r"boom.?bap|jazz.?hop|old school|\b90s\b|beat.?tape|hip.?hop|\brap\b"),
    ("melodic_trap_emo", r"type beat|\btrap\b|juice|nick mira|melodic|emo rap|lil peep|xxxtentacion|iann dior|"
                         r"laroi|trippie|lil skies|lil tecca"),
]
KEYWORD_RE = [(b, re.compile(p)) for b, p in KEYWORD_RULES]

# Source category -> (default bucket, buckets the keyword rules may switch it to).
# Keys are "<source>|<category>" where category is the cat:/lane: tag value or the archive query label.
ALL = tuple(BUCKETS)
TYPE_BEAT_REFINE = ("drill", "amapiano", "caribbean_dancehall", "afro", "french_urbaine", "sad_hiphop",
                    "poppunk_emo_rock", "rnb_soul", "synthpop_pop")
CATEGORY_MAP = {
    # deezer
    "deezer|type_beats": ("melodic_trap_emo", TYPE_BEAT_REFINE),
    "deezer|emo_trap": ("melodic_trap_emo", ("sad_hiphop",)),
    "deezer|rnb": ("rnb_soul", ()), "deezer|rnb_instr": ("rnb_soul", ()),
    "deezer|afro": ("afro", ("amapiano", "caribbean_dancehall")),
    "deezer|afro_instr": ("afro", ("amapiano", "caribbean_dancehall")),
    "deezer|french": ("french_urbaine", ()), "deezer|french_instr": ("french_urbaine", ()),
    "deezer|poppunk": ("poppunk_emo_rock", ()),
    "deezer|acoustic": ("acoustic_guitar", ()), "deezer|guitar_instr": ("acoustic_guitar", ()),
    "deezer|lofi": ("lofi_chill", ()),
    "deezer|piano_ballad": ("piano_ballad", ()), "deezer|piano_instr": ("piano_ballad", ()),
    "deezer|drill": ("drill", ()), "deezer|amapiano": ("amapiano", ()),
    "deezer|dancehall": ("caribbean_dancehall", ()), "deezer|synthpop": ("synthpop_pop", ()),
    "deezer|cinematic": ("cinematic", ()), "deezer|boombap": ("hiphop_boombap", ()),
    "deezer|charts": ("synthpop_pop", ALL),           # refined by the chart genre (see CHART_GENRE)
    # soundcloud
    "soundcloud|juice_type": ("melodic_trap_emo", ()),
    "soundcloud|emo_guitar_trap": ("melodic_trap_emo", ()),
    "soundcloud|french_urbaine": ("french_urbaine", ()),
    "soundcloud|afro": ("afro", ()),
    "soundcloud|rock_acoustic": ("acoustic_guitar", ("poppunk_emo_rock",)),
    "soundcloud|rnb": ("rnb_soul", ()),
    "soundcloud|sad_hiphop": ("sad_hiphop", ()),
    "soundcloud|cinematic_boombap": ("cinematic", ("hiphop_boombap",)),
    "soundcloud|drill_synth": ("drill", ("synthpop_pop",)),
    "soundcloud|amapiano_dancehall": ("amapiano", ("caribbean_dancehall",)),
    "soundcloud|lofi_piano": ("lofi_chill", ("piano_ballad",)),
    # fma (cat: tag; the bucket:<listing> tag refines inside the broad ones)
    "fma|hiphop": ("hiphop_boombap", ("lofi_chill", "melodic_trap_emo")),
    "fma|juice_type": ("melodic_trap_emo", ("drill",)),
    "fma|afro_international": ("afro", ("amapiano", "caribbean_dancehall", "french_urbaine")),
    "fma|rnb": ("rnb_soul", ()),
    "fma|chill_electronic": ("lofi_chill", ()),
    "fma|folk_acoustic": ("acoustic_guitar", ()),
    "fma|cinematic": ("cinematic", ()),
    "fma|pop": ("synthpop_pop", ()),
    "fma|lofi": ("lofi_chill", ()),
    "fma|rock_emo": ("poppunk_emo_rock", ()),
    "fma|piano_ballad": ("piano_ballad", ()),
    # jamendo lanes
    "jamendo|trap_hiphop": ("hiphop_boombap", ("melodic_trap_emo",)),
    "jamendo|downtempo_lofi": ("lofi_chill", ()),
    "jamendo|pop_synth": ("synthpop_pop", ()),
    "jamendo|afro_caribbean": ("caribbean_dancehall", ("afro",)),
    "jamendo|emo_alt_rock": ("poppunk_emo_rock", ()),
    "jamendo|acoustic_guitar": ("acoustic_guitar", ()),
    "jamendo|rnb_soul": ("rnb_soul", ()),
    "jamendo|piano_ballad": ("piano_ballad", ()),
    "jamendo|cinematic_beats": ("cinematic", ()),
    # refs (non-reference curated candidates)
    "refs|emo_trap": ("melodic_trap_emo", ()), "refs|afro": ("afro", ()), "refs|rnb": ("rnb_soul", ()),
    "refs|french": ("french_urbaine", ()), "refs|poppunk": ("poppunk_emo_rock", ()),
    "refs|acoustic": ("acoustic_guitar", ()), "refs|piano": ("piano_ballad", ()),
    "refs|synthpop": ("synthpop_pop", ()), "refs|amapiano": ("amapiano", ()), "refs|lofi": ("lofi_chill", ()),
    "refs|sad_hiphop": ("sad_hiphop", ()), "refs|dancehall": ("caribbean_dancehall", ()),
    "refs|drill": ("drill", ()), "refs|boombap": ("hiphop_boombap", ()),
}
_ARCHIVE_LABELS = {
    "melodic_trap_emo": ["juice_style_type_beats", "type_beat_any", "trap_beats", "melodic_trap_instr",
                         "netlabel_trap_CC", "jamendo_trap_emotional_CC"],
    "drill": ["drill_beats"],
    "hiphop_boombap": ["jamendo_beats_CC", "netlabel_instr_hiphop_CC", "instr_hiphop_other", "beattapes",
                       "boom_bap_instr", "jamendo_hiphop_emotional_CC", "generic_instr_beats"],
    "cinematic": ["cinematic_hiphop"],
    "lofi_chill": ["lofi_hiphop", "netlabel_lofi_CC", "jamendo_lofi_CC", "trip_hop_sad"],
    "sad_hiphop": ["sad_instrumentals"],
    "rnb_soul": ["rnb_instrumentals", "netlabel_rnb_soul_CC", "jamendo_rnb_romantic_CC"],
    "french_urbaine": ["french_rnb"],
    "caribbean_dancehall": ["kizomba_zouk", "riddims", "jamendo_dancehall_CC"],
    "afro": ["instrumentals_ng_afro", "afro_instr", "jamendo_afro_CC", "netlabel_afro_dancehall_CC"],
    "amapiano": ["amapiano"],
    "acoustic_guitar": ["guitar_instrumentals", "netlabel_acoustic_CC", "jamendo_acoustic_sad_CC"],
    "piano_ballad": ["piano_instrumentals", "jamendo_piano_sad_CC"],
    "poppunk_emo_rock": ["jamendo_emo_punk_CC", "netlabel_emo_CC", "jamendo_alt_ballads_CC"],
    "synthpop_pop": ["jamendo_synthpop_CC", "netlabel_synthpop_CC"],
}
for _b, _labels in _ARCHIVE_LABELS.items():
    for _l in _labels:
        CATEGORY_MAP[f"archive|{_l}"] = (_b, ())
CATEGORY_MAP["archive|instrumentals_ng_any"] = ("afro", ALL)       # remakes of Nigerian *and* US hits
CATEGORY_MAP["archive|netlabel_afro_dancehall_CC"] = ("afro", ("caribbean_dancehall",))
CATEGORY_MAP["archive|type_beat_any"] = ("melodic_trap_emo", TYPE_BEAT_REFINE)
# Deezer editorial genre charts: /chart/<genre>/tracks
CHART_GENRE = {"116": "hiphop_boombap", "165": "rnb_soul", "2": "afro", "85": "poppunk_emo_rock",
               "152": "poppunk_emo_rock", "132": "synthpop_pop"}

GENERIC_TITLES = {"untitled", "intro", "outro", "interlude", "beat", "instrumental", "track", "demo", "skit",
                  "type beat", "free", "loop", "theme", "main theme"}
VERSION_RE = re.compile(r"instrumental|\binstru\b|karaoke|remake|\bre\s?prod|backing")
JUICE_RE = re.compile(r"juice\s*wrld|juice\s*world|juicewrld")


# ---------------------------------------------------------------- small helpers
def fold(s):
    """Lowercase + strip accents (non-Latin letters such as Cyrillic are kept), for matching only."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def clean_str(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def to_float(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None


def to_bool_or_none(x):
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    s = str(x).strip().lower()
    return True if s in ("true", "yes", "1") else False if s in ("false", "no", "0") else None


NOTE_PC = {"c": 0, "b#": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "fb": 4, "e#": 5, "f": 5,
           "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11, "cb": 11}
SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KEY_RE = re.compile(r"^([a-g])\s*(#|b|-?sharp|-?flat)?\s*(major|maj|minor|min|m)?$")


def norm_key(k):
    """'Bb minor' / 'B-flat Major' / 'C#m' / 'Am' -> 'A# minor' / 'A# major' / 'C# minor' / 'A minor'.
    A key without a mode keeps no mode ('E'). Unparseable spellings are returned unchanged."""
    s = clean_str(k)
    if not s:
        return None
    s2 = s.replace("\u266f", "#").replace("\u266d", "b").strip()
    major_m = bool(re.fullmatch(r"[A-Ga-g]\s*[#b]?\s*M", s2))      # 'CM' = C major (capital M)
    m = KEY_RE.match(s2.lower().rstrip("m") if major_m else s2.lower())
    if not m:
        return s
    note, acc, mode = m.group(1), (m.group(2) or ""), m.group(3)
    acc = "#" if ("sharp" in acc or acc == "#") else "b" if ("flat" in acc or acc == "b") else ""
    pc = NOTE_PC.get(note + acc)
    if pc is None:
        return s
    if major_m:
        return f"{SHARPS[pc]} major"
    if mode is None:
        return SHARPS[pc]
    return f"{SHARPS[pc]} {'major' if mode.startswith('maj') else 'minor'}"


def license_class(lic):
    """Coarse licence family: cc0 | pd | cc-by[-nc][-sa|-nd] | fma-limited | arr | arr-preview | other | unknown."""
    if lic is None or not str(lic).strip():
        return "unknown"
    s = str(lic).lower()
    if "deezer 30 s preview" in s:
        return "arr-preview"
    if "all-rights-reserved" in s or "all rights reserved" in s:
        return "arr"
    if "fma-limited" in s or "fma_license" in s:
        return "fma-limited"
    if "publicdomain/zero" in s or "cc0" in s:
        return "cc0"
    if "publicdomain" in s or "public domain" in s:
        return "pd"
    m = re.search(r"licenses/([a-z-]+)/", s)
    if m:
        parts = set(m.group(1).split("-"))
    else:
        t = (s.replace("noncommercial", " nc ").replace("non-commercial", " nc ").replace("sharealike", " sa ")
             .replace("share alike", " sa ").replace("noderivatives", " nd ").replace("no derivative works", " nd ")
             .replace("noderivs", " nd ").replace("attribution", " by "))
        parts = set(re.findall(r"[a-z]+", t))
    if "by" in parts or parts & {"nc", "sa", "nd"}:
        return "cc-" + "-".join(["by"] + [p for p in ("nc", "sa", "nd") if p in parts])
    return "other"


def license_rank(cls):
    if cls in ("cc0", "pd") or (cls.startswith("cc-") and not cls.endswith("-nd")):
        return 4      # open CC: remix allowed (NC = non-commercial only)
    if cls.startswith("cc-"):
        return 3      # CC with NoDerivatives
    if cls in ("fma-limited", "other"):
        return 2
    if cls in ("arr", "arr-preview"):
        return 1
    return 0          # unknown


# ---------------------------------------------------------------- dedup keys
ARTIST_SPLIT = re.compile(r"\s*(?:,|;|/|\||\bfeat\b\.?|\bft\b\.?|\bfeaturing\b|\sx\s|\s&\s|\band\b|\bwith\b|\bvs\b\.?)\s*")


def primary_artist(a):
    a = fold(a)
    a = ARTIST_SPLIT.split(a)[0]
    a = re.sub(r"^the\s+", "", a.strip())
    return re.sub(r"[\W_]+", "", a)


def norm_title(title, artist_primary):
    t = fold(title)
    t = re.sub(r"\bvia\s+\S+\.(com\.ng|com|ng|net|org)\b.*$", " ", t)                    # "... via instrumentalstv.com"
    t = re.sub(r"[\(\[]\s*(official\s+)?(audio|video|music video|lyric video|lyrics|visualizer)\s*[\)\]]", " ", t)
    t = re.sub(r"[\(\[][^\)\]]*\bremaster(ed)?\b[^\)\]]*[\)\]]", " ", t)
    t = re.sub(r"\s-\s(\d{4}\s+)?remaster(ed)?(\s+\d{4})?(\s+version)?\s*$", " ", t)
    t = re.sub(r"[\(\[]\s*(feat|ft|featuring|with|prod)\b\.?[^\)\]]*[\)\]]", " ", t)        # (feat. X) / [prod. Y]
    t = re.sub(r"\s(feat|ft|featuring)\b\.?\s[^\(\[\-|]*", " ", t)                         # trailing feat. X
    t = re.sub(r"^\s*\d{1,3}\s*[-_.)]\s+", "", t)                                        # "01 - Song"
    t = re.sub(r"[\W_]+", " ", t).strip()
    if artist_primary:  # "Artist - Title" uploads (archive.org, SoundCloud)
        lead = re.sub(r"[\W_]+", "", t[:len(artist_primary) + 8])
        if lead.startswith(artist_primary) and len(t.split()) > 1:
            words, acc = t.split(), ""
            for i, w in enumerate(words):
                acc += w
                if acc == artist_primary:
                    rest = " ".join(words[i + 1:]).strip()
                    if rest:
                        t = rest
                    break
                if len(acc) > len(artist_primary):
                    break
    return t


def is_generic_title(nt):
    """Titles that many different beats share ('nick mira type beat', 'untitled', 'beat 3'): such key matches
    only count as duplicates when the full durations agree within 2 s."""
    if nt in GENERIC_TITLES or len(nt) < 3:
        return True
    if "type beat" in nt or re.fullmatch(r"(beat|instrumental|track|untitled|demo)\s*\d*", nt):
        rest = re.sub(r"\b(free|type|beat|beats|instrumental|prod|by|x|and|\d+)\b", " ", nt).split()
        return len(rest) <= 3
    return False


def track_url_key(r):
    """A URL that identifies one recording. archive.org page_urls are item (album) level -> use the file URL."""
    url = r.get("page_url") if r["source"] != "archive" else r.get("full_audio_url")
    if not url:
        return None
    u = url.strip().lower().replace("http://", "https://").replace("://www.", "://")
    if "soundcloud.com" in u:
        u = u.split("?")[0]
    return u.rstrip("/")


def durations_compatible(a, b, abs_tol=8.0, rel_tol=0.06):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(abs_tol, rel_tol * max(a, b))


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


# ---------------------------------------------------------------- ffprobe (cached)
def probe(path):
    cmd = ["nice", "-n", "19", "ffprobe", "-v", "error", "-show_entries",
           "format=duration,bit_rate,format_name:stream=codec_type,codec_name,sample_rate,channels",
           "-of", "json", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timeout"}
    if out.returncode != 0:
        return {"error": (out.stderr or "ffprobe failed").strip()[:200]}
    try:
        j = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": "ffprobe bad json"}
    audio = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    fmt = j.get("format", {})
    if not audio:
        return {"error": "no audio stream"}
    a = audio[0]
    return {"duration": to_float(fmt.get("duration")), "codec": a.get("codec_name"),
            "sample_rate": int(a.get("sample_rate") or 0), "channels": a.get("channels"),
            "bit_rate": int(to_float(fmt.get("bit_rate")) or 0), "format": fmt.get("format_name")}


def probe_all(paths, cache_path, workers, max_seconds):
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except Exception:
            cache = {}
    results, todo = {}, []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        sig = [st.st_size, st.st_mtime_ns]
        c = cache.get(p)
        if c and c[0] == sig[0] and c[1] == sig[1]:
            results[p] = c[2]
        else:
            todo.append((p, sig))
    print(f"  ffprobe: {len(results)} cached, {len(todo)} to probe ({workers} workers, nice 19)", flush=True)
    t0, done, complete = time.time(), 0, True

    def save():
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, cache_path)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        it = iter(todo)
        futs = {}
        for _ in range(workers * 4):
            nxt = next(it, None)
            if nxt is None:
                break
            futs[ex.submit(probe, nxt[0])] = nxt
        while futs:
            for fut in as_completed(list(futs)):
                p, sig = futs.pop(fut)
                res = fut.result()
                results[p] = res
                cache[p] = [sig[0], sig[1], res]
                done += 1
                if done % 1000 == 0:
                    save()
                    print(f"    probed {done}/{len(todo)} ({done / (time.time() - t0):.0f}/s)", flush=True)
                if time.time() - t0 > max_seconds:
                    complete = False
                    continue
                nxt = next(it, None)
                if nxt is not None:
                    futs[ex.submit(probe, nxt[0])] = nxt
                break
    save()
    return results, complete


# ---------------------------------------------------------------- per-row logic
def category_of(r):
    for t in r["tags"]:
        if t.startswith("cat:") or t.startswith("lane:"):
            return t.split(":", 1)[1]
    if r["source"] == "archive":
        return (r.get("query") or "").split(":", 1)[0].strip()
    return ""


def infer_bucket(r):
    if r["is_reference"]:
        return "reference"
    src, cat = r["source"], category_of(r)
    # Refinement text: title (+ artist) always; the query only where it is a human search string (archive's
    # Lucene queries and Jamendo's lane label would match everything); genre/mood tags only where they are
    # curated per track (Jamendo, FMA).
    parts = [fold(r["title"]), fold(r.get("artist"))]
    if src in ("deezer", "soundcloud", "fma", "refs"):
        parts.append(fold(r.get("query")))
    if src in ("jamendo", "fma"):
        parts += [fold(t) for t in r["tags"] if t.startswith(("genre:", "mood:"))]
    text = re.sub(r"[_]+", " ", " ".join(parts))
    default, allowed = CATEGORY_MAP.get(f"{src}|{cat}", (None, ALL))
    if default is not None:
        allowed = tuple(allowed) + (default,)   # rules run in KEYWORD_RULES order; the default may win first
    if src == "deezer" and cat == "charts":
        m = re.search(r"chart:genre_(\d+)", r.get("query") or "")
        if m and m.group(1) in CHART_GENRE:
            default, allowed = CHART_GENRE[m.group(1)], ()
    if src == "fma":                      # FMA listing bucket gives a sharper genre than the broad cat
        lb = next((t.split(":", 1)[1] for t in r["tags"] if t.startswith("bucket:")), "")
        fma_lb = {"c_triphop": "lofi_chill", "c_wonky": "lofi_chill", "c_french": "french_urbaine",
                  "s_amour": "french_urbaine", "s_drill": "drill", "s_amapiano": "amapiano",
                  "c_dancehall": "caribbean_dancehall", "s_dancehall": "caribbean_dancehall",
                  "c_reggae_dub": "caribbean_dancehall", "g_reggaeton": "caribbean_dancehall",
                  "s_kizomba": "caribbean_dancehall", "c_latin_america": "caribbean_dancehall",
                  "c_synthpop": "synthpop_pop", "s_pop_punk": "poppunk_emo_rock", "s_piano": "piano_ballad"}
        if lb in fma_lb:
            return fma_lb[lb]
    for b, rx in KEYWORD_RE:
        if (default is None or b in allowed) and rx.search(text):
            return b
    return default or "hiphop_boombap"


def flag_row(r):
    """Juice / Reine safety flags (tags) for non-reference candidates."""
    t = re.sub(r"[^a-z0-9#&]+", " ", fold(r["title"])).strip()
    a = re.sub(r"[^a-z0-9#&]+", " ", fold(r["artist"])).strip()
    tags = r["tags"]
    juice = bool(JUICE_RE.search(t) or JUICE_RE.search(a))
    if juice and "type beat" not in t and VERSION_RE.search(t) and "juice_own_beat" not in tags:
        tags.append("juice_own_beat")
    if r["is_reference"]:
        return
    if juice and ("type beat" not in t) and (not VERSION_RE.search(t)) and \
            (primary_artist(r["artist"]) == "juicewrld" or "freestyle" in t or not re.search(r"\bbeat", t)):
        tags.append("warn:possible_juice_vocal")
    if re.search(r"\breine\b", t) and ("dadju" in t or "dadju" in a) and "control:original_beat" not in tags:
        tags += ["control:original_beat", "ref_group:control", "reference"]
        r["is_reference"] = True


def normalise(r, src_dir):
    """Coerce one row to the contract types. Returns (row, None) or (None, reason)."""
    miss = [k for k in CONTRACT_KEYS if k not in r]
    if miss:
        return None, "missing_keys:" + ",".join(miss)
    out = {}
    rid = clean_str(r["id"])
    if not rid:
        return None, "empty_id"
    src = clean_str(r["source"]) or src_dir
    if src != src_dir:
        return None, f"source_mismatch:{src}!={src_dir}"
    if not rid.startswith(src + ":"):
        return None, "id_without_source_prefix"
    out["id"], out["source"] = rid, src
    out["title"] = clean_str(r["title"]) or ""
    out["artist"] = clean_str(r["artist"]) or ""
    out["page_url"] = clean_str(r["page_url"])
    cp = clean_str(r["clip_path"])
    if not cp:
        return None, "no_clip_path"
    out["clip_path"] = os.path.abspath(cp)
    cs = to_float(r["clip_start_s"])
    out["clip_start_s"] = round(cs, 3) if cs is not None and cs >= 0 else None
    d = to_float(r["duration_full_s"])
    out["duration_full_s"] = round(d, 3) if d and d > 0 else None
    out["license"] = clean_str(r["license"])
    out["full_audio_url"] = clean_str(r["full_audio_url"])
    fa = to_bool_or_none(r["full_audio_available"])
    out["full_audio_available"] = bool(fa) or bool(out["full_audio_url"])
    b = to_float(r["bpm_meta"])
    out["bpm_meta"] = round(b, 2) if b and 40 <= b <= 250 else None
    tags = r["tags"] if isinstance(r["tags"], list) else ([r["tags"]] if r["tags"] else [])
    seen, tl = set(), []
    for t in tags:
        t = clean_str(t)
        if t and t not in seen:
            seen.add(t)
            tl.append(t)
    km = norm_key(r["key_meta"])
    if km and clean_str(r["key_meta"]) != km:
        tl.append("key_raw:" + clean_str(r["key_meta"]))
    out["key_meta"] = km
    out["tags"] = tl
    out["is_instrumental_meta"] = to_bool_or_none(r["is_instrumental_meta"])
    out["query"] = clean_str(r["query"]) or ""
    out["is_reference"] = bool(to_bool_or_none(r["is_reference"]))
    return out, None


def meta_richness(r):
    return sum(x is not None for x in (r["bpm_meta"], r["key_meta"], r["duration_full_s"], r["is_instrumental_meta"],
                                       r["license"], r["full_audio_url"]))


def keep_score(r):
    return (r["full_audio_available"], license_rank(r["license_class"]), SOURCE_PRIORITY.get(r["source"], 0),
            round(r["clip_dur_s"] or 0), meta_richness(r))


# ---------------------------------------------------------------- coverage report
def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "-"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def tempo_compatible(b, target=100.4, tol=0.08):
    return b is not None and min(abs(target / (b * m) - 1) for m in (0.5, 1.0, 2.0)) <= tol


def write_coverage(path, final, stats, src_stats, read_sources, probe_info, dup_groups):
    cands = [r for r in final if not r["is_reference"]]
    refs = [r for r in final if r["is_reference"]]
    srcs = [s for s in SOURCE_ORDER if s in read_sources] + sorted(set(read_sources) - set(SOURCE_ORDER))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    size_by_src = collections.Counter()
    for r in final:
        try:
            size_by_src[r["source"]] += os.path.getsize(r["clip_path"])
        except OSError:
            pass
    total_mb = sum(size_by_src.values()) / 1e6
    L = [f"# Beat catalog coverage", "",
         f"Generated {now} by `pipeline/catalog/merge_catalog.py` from `work/catalog/*/candidates.jsonl`.", "",
         f"**{len(final)} rows** in `work/catalog/catalog.jsonl`: **{len(cands)} candidates** + "
         f"**{len(refs)} references** (Juice WRLD / peer style anchors, Dadju \"Reine\" and the Reine-beat control). "
         f"Read {stats['read']} rows, dropped {stats['broken']} broken and {stats['dup']} duplicates "
         f"({dup_groups} duplicate groups). Clips total **{total_mb / 1000:.2f} GB**.", ""]

    # per source
    L += ["## Per source", ""]
    rows = []
    for s in srcs:
        ss = src_stats[s]
        fr = [r for r in final if r["source"] == s]
        fc = [r for r in fr if not r["is_reference"]]
        rows.append([s, ss["read"], ss["broken"], ss["dup"], len(fr), len(fr) - len(fc), len(fc),
                     sum(r["is_instrumental_meta"] is True for r in fc),
                     sum(r["full_audio_available"] for r in fc),
                     sum(r["bpm_meta"] is not None for r in fr), sum(r["key_meta"] is not None for r in fr),
                     f"{size_by_src[s] / 1e6:.0f}"])
    rows.append(["**total**", stats["read"], stats["broken"], stats["dup"], len(final), len(refs), len(cands),
                 sum(r["is_instrumental_meta"] is True for r in cands), sum(r["full_audio_available"] for r in cands),
                 sum(r["bpm_meta"] is not None for r in final), sum(r["key_meta"] is not None for r in final),
                 f"{total_mb:.0f}"])
    L += [table(["source", "read", "broken", "dup dropped", "kept", "refs", "candidates", "instr=true",
                 "full audio", "bpm_meta", "key_meta", "clips MB"], rows), ""]
    if stats["broken_reasons"]:
        L += ["Broken rows by reason: " + ", ".join(f"{k} {v}" for k, v in stats["broken_reasons"].most_common()), ""]

    # per bucket
    L += ["## Per inferred genre bucket (candidates only)", "",
          "Bucket = the source's own category tag / query label, refined by title+query keywords "
          "(field `genre_bucket`, tag `genre_bucket:<b>`).", ""]
    by_b = collections.defaultdict(list)
    for r in cands:
        by_b[r["genre_bucket"]].append(r)
    rows = []
    for b in BUCKETS:
        rs = by_b.get(b, [])
        sc = collections.Counter(r["source"] for r in rs)
        rows.append([b, len(rs), sum(r["is_instrumental_meta"] is True for r in rs),
                     sum(r["is_instrumental_meta"] is False for r in rs),
                     f"{sum(r['full_audio_available'] for r in rs)} ({pct(sum(r['full_audio_available'] for r in rs), len(rs))})",
                     sum(license_rank(r["license_class"]) >= 3 for r in rs),
                     sum(tempo_compatible(r["bpm_meta"]) for r in rs),
                     ", ".join(f"{k} {v}" for k, v in sc.most_common()), BUCKET_DESC[b]])
    L += [table(["bucket", "n", "instr=true", "instr=false", "full audio", "CC licensed", "bpm_meta ~100",
                 "by source", "covers"], rows), ""]

    # instrumental / vocal
    L += ["## Instrumental vs vocal (is_instrumental_meta, candidates)", ""]
    rows = []
    for s in srcs:
        fc = [r for r in cands if r["source"] == s]
        rows.append([s, sum(r["is_instrumental_meta"] is True for r in fc),
                     sum(r["is_instrumental_meta"] is False for r in fc),
                     sum(r["is_instrumental_meta"] is None for r in fc)])
    rows.append(["**total**", sum(r["is_instrumental_meta"] is True for r in cands),
                 sum(r["is_instrumental_meta"] is False for r in cands),
                 sum(r["is_instrumental_meta"] is None for r in cands)])
    L += [table(["source", "instrumental (true)", "vocal (false)", "unknown (null)"], rows), "",
          "`true` is mostly keyword based (type beat / instrumental / instru / beat / riddim, FMA flag, MTG annotations, "
          "archive.org Essentia >= 0.8); `null` rows (Jamendo/FMA/archive songs, Deezer search items) need the CLAP "
          "instrumental check downstream.", ""]

    # full audio
    L += ["## Full-audio availability (candidates)", ""]
    rows = []
    for s in srcs:
        fc = [r for r in cands if r["source"] == s]
        how = {"deezer": "30 s preview only", "soundcloud": "re-resolve page_url with yt-dlp (signed HLS expires)",
               "refs": "SoundCloud rows: re-resolve page_url; Deezer rows: preview only",
               "archive": "direct archive.org/download mp3", "jamendo": "direct prod-1.storage.jamendo.com mp3",
               "fma": "direct files.freemusicarchive.org mp3", "ccmixter": "blocked (HTTP 403)"}.get(s, "")
        rows.append([s, sum(r["full_audio_available"] for r in fc), len(fc),
                     sum(bool(r["full_audio_url"]) for r in fc), how])
    rows.append(["**total**", sum(r["full_audio_available"] for r in cands), len(cands),
                 sum(bool(r["full_audio_url"]) for r in cands), ""])
    L += [table(["source", "full audio available", "of", "with direct full_audio_url", "how to get the full track"],
                rows), ""]

    # licence
    L += ["## Licence mix (candidates)", ""]
    lc = collections.Counter(r["license_class"] for r in cands)
    rows = []
    for k, v in lc.most_common():
        note = ("remix OK (non-commercial if NC)" if license_rank(k) == 4 else
                "no derivatives: personal use only, do not publish a remix" if license_rank(k) == 3 else
                "all rights reserved: personal use only" if license_rank(k) == 1 else
                "unknown: treat as all rights reserved" if k == "unknown" else "restricted / read the terms")
        srcs_k = collections.Counter(r["source"] for r in cands if r["license_class"] == k)
        rows.append([k, v, ", ".join(f"{a} {b}" for a, b in srcs_k.most_common()), note])
    L += [table(["license_class", "n", "by source", "meaning"], rows), "",
          f"Open CC (remixable, no ND): {sum(license_rank(r['license_class']) == 4 for r in cands)}; "
          f"CC-ND: {sum(license_rank(r['license_class']) == 3 for r in cands)}; "
          f"all-rights-reserved / unknown: {sum(license_rank(r['license_class']) <= 1 for r in cands)}. "
          "This is a personal, non-commercial fan project, but only open-CC beats could be shared publicly.", ""]

    # clips
    durs = sorted(r["clip_dur_s"] for r in final if r["clip_dur_s"])
    def q(p):
        return durs[min(len(durs) - 1, int(p * len(durs)))] if durs else 0
    L += ["## Clips", "",
          f"{len(durs)} clips, {total_mb / 1000:.2f} GB. ffprobe duration min {durs[0]:.1f} s, "
          f"p5 {q(0.05):.1f} s, median {q(0.5):.1f} s, max {durs[-1]:.1f} s. "
          f"Formats: " + ", ".join(f"{k} {v}" for k, v in probe_info["formats"].most_common(6)) + ". "
          "Deezer/Deezer-refs clips are the 30 s previews (clip_start_s null); all others are 40 s excerpts from "
          "~30 % into the full track.", ""]

    # metadata
    nb = [r for r in cands if r["bpm_meta"] is not None]
    L += ["## Tempo / key metadata (candidates)", "",
          f"bpm_meta: {len(nb)} ({pct(len(nb), len(cands))}), of which {sum(tempo_compatible(r['bpm_meta']) for r in nb)} "
          "are within 8 % of the freestyle tempo (~100.4 BPM, half/double allowed). Values are unverified metadata "
          "(Deezer/Essentia octave errors happen). "
          f"key_meta: {sum(r['key_meta'] is not None for r in cands)} ({pct(sum(r['key_meta'] is not None for r in cands), len(cands))}). "
          "Real tempo/key must come from the audio analysis stage.", ""]

    # flags
    fl = collections.Counter(t for r in final for t in r["tags"]
                             if t in ("juice_own_beat", "warn:possible_juice_vocal", "control:original_beat"))
    L += ["## Flags", "",
          f"- `juice_own_beat` (instrumentals/remakes of Juice WRLD's own songs, not a *new* beat): {fl['juice_own_beat']}",
          f"- `warn:possible_juice_vocal` (a candidate that may contain Juice's own vocal): {fl['warn:possible_juice_vocal']}",
          f"- `control:original_beat` (Dadju \"Reine\" beat; forced to is_reference): {fl['control:original_beat']}",
          f"- duplicates folded into a kept row are listed in its `also_in` field (and `also_in:<id>` tags); "
          f"every dropped row is in `work/catalog/merge_dropped.jsonl`.", ""]

    # gaps
    L += ["## Known gaps", ""]
    gaps = []
    for b in BUCKETS:
        rs = by_b.get(b, [])
        n, nfa = len(rs), sum(r["full_audio_available"] for r in rs)
        nins = sum(r["is_instrumental_meta"] is True for r in rs)
        issues = []
        if n < 250:
            issues.append(f"thin ({n} candidates)")
        if n and nfa / n < 0.5:
            issues.append(f"only {nfa} ({pct(nfa, n)}) have full audio, the rest are 30 s Deezer previews")
        if n and nins / n < 0.3:
            issues.append(f"only {nins} confirmed instrumentals ({pct(nins, n)})")
        if n and sum(license_rank(r["license_class"]) == 4 for r in rs) < 25:
            issues.append(f"{sum(license_rank(r['license_class']) == 4 for r in rs)} open-CC tracks")
        if issues:
            gaps.append(f"- **{b}**: " + "; ".join(issues) + ".")
    if src_stats.get("ccmixter", {}).get("read", 0) == 0:
        gaps.append("- **ccMixter contributes nothing**: every file under ccmixter.org/content answers HTTP 403 "
                    "(re-checked by the merger with one plain request). 1500 metadata-only rows wait in "
                    "`work/catalog/ccmixter/candidates_pending_clips.jsonl` (1230 tagged instrumental, 1206 with bpm); "
                    "resume with `harvest_ccmixter.py --clips-only --retry-blocked` if access is ever granted.")
    gaps += [
        "- **Key metadata is nearly absent** (Deezer, Jamendo and FMA have none); key fit must come from chroma analysis.",
        "- **BPM metadata is sparse and unverified** (Deezer bpm, SoundCloud titles/descriptions, archive Essentia).",
        "- **Deezer rows are 30 s previews only** (no full audio): fine for screening, but a Deezer winner would have "
        "to be sourced elsewhere (for remakes, look for the same title on SoundCloud/archive).",
        "- **French R&B / pop urbaine on CC sources is thin**: almost all of it is Deezer previews and SoundCloud type "
        "beats (all rights reserved).",
        "- **Vocal status unknown for many CC songs** (Jamendo/FMA/archive `null`): the CLAP instrumental check matters.",
        "- **Clip position is blind**: excerpts start ~30 % in without silence/breakdown checks (no audio analysis was "
        "allowed during harvesting).",
        "- **ND licences**: CC-ND tracks (mostly archive/FMA/Jamendo) can be test-mixed privately but a remix on them "
        "must not be published.",
        "- **Not harvested**: YouTube (blocked), Bandcamp, Audiomack, BeatStars, Spotify (no clean preview access); "
        "SoundCloud, Jamendo, FMA and Deezer all have unharvested eligible tracks (see each source's notes).",
    ]
    L += gaps + [""]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(L))
    os.replace(tmp, path)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog-dir", default="/home/user/test/work/catalog")
    ap.add_argument("--workers", type=int, default=3, help="parallel ffprobe processes (niced)")
    ap.add_argument("--min-clip", type=float, default=20.0, help="minimum clip duration in seconds")
    ap.add_argument("--max-seconds", type=float, default=540, help="probe time budget; re-run to continue")
    ap.add_argument("--dry-run", action="store_true", help="validate and print stats, write nothing but the probe cache")
    a = ap.parse_args()
    cdir = a.catalog_dir
    out_path = os.path.join(cdir, "catalog.jsonl")
    cov_path = os.path.join(cdir, "coverage.md")
    drop_path = os.path.join(cdir, "merge_dropped.jsonl")
    cache_path = os.path.join(cdir, ".merge_probe_cache.json")

    # 1. load
    sources = sorted(d for d in os.listdir(cdir) if os.path.isfile(os.path.join(cdir, d, "candidates.jsonl")))
    stats = {"read": 0, "broken": 0, "dup": 0, "broken_reasons": collections.Counter()}
    src_stats = {s: collections.Counter() for s in sources}
    rows, dropped, seen_ids = [], [], set()

    def drop(rid, src, reason, **kw):
        dropped.append(dict(id=rid, source=src, reason=reason, **kw))
        if reason != "duplicate":
            stats["broken"] += 1
            src_stats[src]["broken"] += 1
            stats["broken_reasons"][reason.split(":")[0]] += 1

    for s in sources:
        for ln, line in enumerate(open(os.path.join(cdir, s, "candidates.jsonl"), encoding="utf-8"), 1):
            if not line.strip():
                continue
            stats["read"] += 1
            src_stats[s]["read"] += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                drop(f"{s}:line{ln}", s, "bad_json")
                continue
            r, why = normalise(raw, s)
            if r is None:
                drop(str(raw.get("id")), s, why)
                continue
            if r["id"] in seen_ids:
                drop(r["id"], s, "duplicate_id")
                continue
            seen_ids.add(r["id"])
            rows.append(r)
    print(f"loaded {len(rows)} rows from {len(sources)} sources: " +
          ", ".join(f"{s} {src_stats[s]['read']}" for s in sources), flush=True)

    # 2. validate clips
    paths = sorted({r["clip_path"] for r in rows})
    probes, complete = probe_all([p for p in paths if os.path.isfile(p)], cache_path, a.workers, a.max_seconds)
    if not complete:
        print("probe time budget reached; cache saved -- re-run to finish (nothing else written)", flush=True)
        sys.exit(2)
    valid, clip_owner = [], {}
    formats = collections.Counter()
    for r in rows:
        p = r["clip_path"]
        if not os.path.isfile(p):
            drop(r["id"], r["source"], "clip_missing", clip_path=p)
            continue
        if os.path.getsize(p) == 0:
            drop(r["id"], r["source"], "clip_empty", clip_path=p)
            continue
        pr = probes.get(p) or {"error": "not probed"}
        if "error" in pr:
            drop(r["id"], r["source"], "probe_failed:" + pr["error"][:80], clip_path=p)
            continue
        if not pr["duration"] or pr["duration"] < a.min_clip:
            drop(r["id"], r["source"], f"clip_too_short:{pr['duration']}", clip_path=p)
            continue
        r["clip_dur_s"] = round(pr["duration"], 2)
        formats[f"{pr['codec']}/{pr['sample_rate']}Hz/{pr['channels']}ch/{round(pr['bit_rate'] / 1000)}k"] += 1
        if pr["duration"] > 46:
            r["tags"].append("warn:clip_longer_than_45s")
        valid.append(r)

    # 3/4. annotate
    for r in valid:
        flag_row(r)
        r["license_class"] = license_class(r["license"])
        r["genre_bucket"] = infer_bucket(r)
        r["tags"] = [t for t in r["tags"] if not t.startswith("genre_bucket:")] + ["genre_bucket:" + r["genre_bucket"]]
        r["also_in"] = []
        if r["is_reference"] and "reference" not in r["tags"]:
            r["tags"].append("reference")

    # 5. dedup
    n = len(valid)
    dsu = DSU(n)
    link_reason = {}
    idx_by_id = {r["id"]: i for i, r in enumerate(valid)}

    def link(i, j, why):
        if dsu.find(i) != dsu.find(j):
            dsu.union(i, j)
            link_reason[(min(i, j), max(i, j))] = why

    for keyfn, why in ((track_url_key, "page_url"), (lambda r: r["full_audio_url"], "full_audio_url"),
                       (lambda r: r["clip_path"], "clip_path")):
        first = {}
        for i, r in enumerate(valid):
            k = keyfn(r)
            if k:
                if k in first:
                    link(first[k], i, why)
                else:
                    first[k] = i
    for i, r in enumerate(valid):
        for t in r["tags"]:
            if t.startswith("also_in:"):
                j = idx_by_id.get(t.split(":", 1)[1])
                if j is not None and j != i:
                    link(i, j, "also_in_tag")
    by_key = collections.defaultdict(list)
    for i, r in enumerate(valid):
        pa = primary_artist(r["artist"])
        nt = norm_title(r["title"], pa)
        if not pa or not nt:
            continue
        by_key[(pa, nt)].append(i)
    for (pa, nt), idxs in by_key.items():
        if len(idxs) < 2:
            continue
        generic = is_generic_title(nt)
        clusters = []  # greedy clustering on full-track duration
        for i in idxs:
            d = valid[i]["duration_full_s"]
            for c in clusters:
                d0 = valid[c[0]]["duration_full_s"]
                if generic and (d is None or d0 is None or abs(d - d0) > 2):
                    continue
                if durations_compatible(d, d0):
                    c.append(i)
                    break
            else:
                clusters.append([i])
        for c in clusters:
            for j in c[1:]:
                link(c[0], j, "artist_title")

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[dsu.find(i)].append(i)
    final, dup_groups = [], 0
    for root, members in groups.items():
        if len(members) == 1:
            final.append(valid[members[0]])
            continue
        dup_groups += 1
        ms = sorted(members, key=lambda i: keep_score(valid[i]), reverse=True)
        keep = valid[ms[0]]
        for i in ms[1:]:
            o = valid[i]
            why = next((v for (x, y), v in link_reason.items() if i in (x, y) and dsu.find(x) == root), "linked")
            drop(o["id"], o["source"], "duplicate", duplicate_of=keep["id"], link=why)
            stats["dup"] += 1
            src_stats[o["source"]]["dup"] += 1
            keep["also_in"].append(o["id"])
            if f"also_in:{o['id']}" not in keep["tags"]:
                keep["tags"].append(f"also_in:{o['id']}")
            if o["is_reference"] and not keep["is_reference"]:
                keep["is_reference"] = True
                keep["genre_bucket"] = "reference"
                keep["tags"] = [t for t in keep["tags"] if not t.startswith("genre_bucket:")] + \
                               ["genre_bucket:reference", "reference"]
            filled = False
            for k in ("bpm_meta", "key_meta", "is_instrumental_meta"):
                if keep[k] is None and o[k] is not None:
                    keep[k] = o[k]
                    filled = True
            if filled:
                keep["tags"].append(f"meta_from:{o['id']}")
        final.append(keep)

    # order: references first, then by source order, original order inside a source
    pos = {r["id"]: i for i, r in enumerate(valid)}
    sord = {s: i for i, s in enumerate(SOURCE_ORDER)}
    final.sort(key=lambda r: (not r["is_reference"], sord.get(r["source"], 99), pos[r["id"]]))
    out_rows = [{k: r[k] for k in CONTRACT_KEYS + EXTRA_KEYS} for r in final]

    # sanity: unique ids and clip paths
    assert len({r["id"] for r in out_rows}) == len(out_rows)
    assert len({r["clip_path"] for r in out_rows}) == len(out_rows)

    print(f"valid {len(valid)}, broken {stats['broken']}, duplicates dropped {stats['dup']} in {dup_groups} groups, "
          f"final {len(out_rows)} ({sum(r['is_reference'] for r in out_rows)} references)", flush=True)
    print("  broken reasons:", dict(stats["broken_reasons"]))
    print("  dup links:", dict(collections.Counter(d.get("link") for d in dropped if d["reason"] == "duplicate")))
    print("  buckets:", dict(collections.Counter(r["genre_bucket"] for r in out_rows).most_common()))
    if a.dry_run:
        return
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, out_path)
    with open(drop_path + ".tmp", "w", encoding="utf-8") as f:
        for d in dropped:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    os.replace(drop_path + ".tmp", drop_path)
    write_coverage(cov_path, out_rows, stats, src_stats, sources, {"formats": formats}, dup_groups)
    print(f"wrote {out_path}, {cov_path}, {drop_path}", flush=True)


if __name__ == "__main__":
    main()
