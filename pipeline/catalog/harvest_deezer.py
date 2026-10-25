#!/opt/av/bin/python
"""Harvest remix-beat candidates from the public Deezer API (30 s previews).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial).
This script ONLY harvests: it builds a large, diverse pool of candidate tracks
(plus a small set of reference tracks) with short audio clips and metadata.
Scoring (tempo / key / CLAP vibe) happens later in other pipeline stages.

How it works
------------
1. Seeds.  A hand-written catalog of ~20 genre "categories" (melodic trap, type
   beats, sad R&B, afro-R&B, French pop urbaine, pop-punk, acoustic, lo-fi,
   piano, drill, amapiano, dancehall, synth-pop, cinematic, boom-bap, ...).
   Each category lists seed artists, track-search queries, playlist-search
   queries (Deezer editorial playlists preferred), optional genre charts and
   optional "related artist" expansion.  Every API response used for seeding
   is cached in SQLite so re-runs are deterministic and cheap.
2. Ordering.  Inside a category the sources are interleaved round-robin
   (rank-1 of every source, then rank-2, ...); across categories a weighted
   stride scheduler interleaves categories by their weight.  Duplicates,
   unwanted versions (slowed / sped up / nightcore / 8D / live / a cappella),
   Juice WRLD's own tracks and Dadju - "Reine" are dropped, and a per-artist
   cap keeps the pool diverse.  Wherever the run stops, the pool is balanced.
3. Fetch.  For each selected track: GET /track/{id} (fresh signed preview URL,
   bpm, duration, contributors), GET /album/{id} (genres, cached), then ffmpeg
   pulls the 30 s preview and re-encodes it to MP3 128 kbps / 44.1 kHz.  Each
   clip is validated with ffprobe (>= 20 s) or deleted.
4. References.  Juice WRLD's top tracks + Dadju - "Reine" are harvested the
   same way with is_reference=true (they anchor the "Juice vibe" embedding).

Resumable: ids already present in candidates.jsonl / rejects.jsonl are skipped,
valid clips left over from an interrupted run are reused, and --max-seconds
makes a run stop submitting work after a time budget.  Run repeatedly until
the target is reached.

Rate limiting: a global sliding window keeps API traffic <= --rps requests/s
(default 8/s, Deezer's limit is 50 requests / 5 s); quota errors back off.

Usage
-----
  /opt/av/bin/python harvest_deezer.py --target 2500 --max-seconds 500
  /opt/av/bin/python harvest_deezer.py --dry-run      # seed + show the plan only
  /opt/av/bin/python harvest_deezer.py --stats        # summarize the output JSONL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import urlencode

import requests

# --------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------
SOURCE = "deezer"
API = "https://api.deezer.com"
ROOT = "/home/user/test"
OUT_DIR = os.path.join(ROOT, "work", "catalog", SOURCE)
CLIP_DIR = os.path.join(OUT_DIR, "clips")
JSONL = os.path.join(OUT_DIR, "candidates.jsonl")
REJECTS = os.path.join(OUT_DIR, "rejects.jsonl")
CACHE_DB = os.path.join(OUT_DIR, "api_cache.sqlite")

LICENSE = "all-rights-reserved (Deezer 30 s preview; personal non-commercial use only)"
UA = "remix-catalog-harvester/1.0 (personal non-commercial fan project)"

MIN_FULL_DURATION = 75      # s; drops skits / interludes / snippets
MAX_FULL_DURATION = 600     # s; drops DJ mixes and 1-hour compilations
MIN_CLIP_DURATION = 20.0    # s; contract: validate clip >= 20 s
MAX_CLIP_DURATION = 44.5    # s; previews are ~30 s, a few run 45 s+; keep clips < 45 s
ARTIST_CAP = 10             # max candidates per (primary) artist

# Versions we never want as beat candidates (tempo/pitch-warped or no beat).
BAD_VERSION_RE = re.compile(
    r"slowed|sped[\s-]*up|speed[\s-]*up|nightcore|\b8d\b|\breverb\b|daycore|"
    r"a[\s-]?cappella|acapella|accapella|\bvocals? only\b|"
    r"[\(\[\-]\s*live\b|\blive (at|from|in|on|session|version)\b|"
    r"\bskit\b|\binterlude\b|\bmeditation\b|\basmr\b|white noise|rain sounds",
    re.I,
)
# Metadata hints that a track is an instrumental.
INSTR_RE = re.compile(
    r"instrumental|\binstru\b|type[\s-]?beat|karaoke|\bbeats?\b|\briddim\b|\bbeat tape\b",
    re.I,
)
FEAT_JUICE_RE = re.compile(r"\b(feat\.?|ft\.?|featuring|with)\s+juice\s*wrld", re.I)

# --------------------------------------------------------------------------
# Seed catalog.  weight ~ share of the final pool.  artist_instr is the
# is_instrumental_meta default for that category's artist top tracks
# (False = vocal artists, True = instrumental artists, None = mixed).
# --------------------------------------------------------------------------
CATEGORIES: dict[str, dict] = {
    "emo_trap": dict(
        weight=280, artist_instr=False, related_k=12,
        artists=[
            "Lil Peep", "XXXTENTACION", "Trippie Redd", "Lil Uzi Vert", "The Kid LAROI",
            "Iann Dior", "Lil Skies", "Lil Mosey", "Lil Tecca", "Polo G", "Rod Wave",
            "YNW Melly", "Lil Tjay", "A Boogie Wit da Hoodie", "Post Malone", "Swae Lee",
            "Roddy Ricch", "Lil Durk", "Gunna", "Don Toliver", "Toosii", "Kid Cudi",
            "Internet Money", "Powfu", "Sueco", "24kGoldn", "blackbear", "Lil Xan",
            "Lil Tracy", "Nothing,Nowhere.", "Yung Lean", "Cold Hart",
            "Wicca Phase Springs Eternal", "Bexey", "glaive", "ericdoa", "brakence",
            "SoFaygo", "Autumn!", "Lil Poppa", "Rylo Rodriguez", "NoCap", "Kevin Gates",
            "Quando Rondo", "Morray", "Lil Baby", "Future", "Travis Scott",
            "YoungBoy Never Broke Again", "Kodak Black", "Landon Cube", "Scorey",
            "Lil Skies", "Arizona Zervas", "NF", "Yung Bleu", "Lil Nas X",
        ],
        queries=["emo rap", "sad rap", "melodic rap", "guitar rap", "sad trap"],
        playlists=["emo rap", "sad rap", "melodic rap"],
    ),
    "type_beats": dict(
        weight=380, artist_instr=None, pages=2,
        artists=[],
        queries=[
            "juice wrld type beat", "lil peep type beat", "xxxtentacion type beat",
            "nick mira type beat", "internet money type beat", "guitar type beat",
            "sad guitar type beat", "emo rap beat", "sad type beat", "emotional type beat",
            "melodic trap beat", "trap instrumental", "sad trap instrumental",
            "rod wave type beat", "polo g type beat", "the kid laroi type beat",
            "iann dior type beat", "trippie redd type beat", "lil uzi vert type beat",
            "lil tecca type beat", "post malone type beat", "piano type beat",
            "sad piano beat", "hip hop instrumental", "rap instrumental", "beats",
            "guitar beat", "acoustic type beat", "pop punk type beat", "emo type beat",
            "love type beat", "lil tjay type beat", "kid cudi type beat",
            "melodic type beat", "freestyle beat", "rap beat instrumental",
        ],
        playlists=["type beats", "instrumental rap beats", "sad beats"],
    ),
    "rnb": dict(
        weight=230, artist_instr=False, related_k=10,
        artists=[
            "Frank Ocean", "SZA", "Daniel Caesar", "H.E.R.", "Giveon", "Brent Faiyaz",
            "Summer Walker", "Jhené Aiko", "Khalid", "Lucky Daye", "Kehlani", "Ari Lennox",
            "Snoh Aalegra", "Sabrina Claudio", "Kali Uchis", "Steve Lacy", "Omar Apollo",
            "dvsn", "6LACK", "Bryson Tiller", "PARTYNEXTDOOR", "Drake", "Tory Lanez",
            "Chris Brown", "Tinashe", "Ty Dolla $ign", "Jeremih", "Miguel", "Ne-Yo",
            "Joji", "keshi", "d4vd", "Muni Long", "Coco Jones", "Victoria Monét",
            "Russ", "Roy Woods", "Majid Jordan", "Jacquees", "Trey Songz", "Sonder",
            "Ella Mai", "Jorja Smith", "Mahalia", "Usher", "Brent Faiyaz",
        ],
        queries=["sad r&b", "alternative r&b", "rnb love song", "trapsoul"],
        playlists=["sad r&b", "alternative r&b", "r&b love"],
    ),
    "rnb_instr": dict(
        weight=140, artist_instr=None, pages=2,
        artists=[],
        queries=[
            "rnb instrumental", "r&b type beat", "trapsoul type beat",
            "bryson tiller type beat", "6lack type beat", "the weeknd type beat",
            "sza type beat", "chill rnb beat", "slow jam instrumental",
            "smooth rnb instrumental", "neo soul instrumental", "love song instrumental",
            "drake type beat", "partynextdoor type beat", "frank ocean type beat",
            "brent faiyaz type beat", "giveon type beat", "rnb beat",
        ],
        playlists=["rnb instrumentals"],
    ),
    "afro": dict(
        weight=270, artist_instr=False, related_k=12,
        artists=[
            "Burna Boy", "Wizkid", "Davido", "Rema", "Tems", "Omah Lay", "Ayra Starr",
            "CKay", "Fireboy DML", "Joeboy", "Asake", "Kizz Daniel", "Tiwa Savage",
            "Mr Eazi", "Adekunle Gold", "Yemi Alade", "Simi", "Victony", "Bnxn", "Ruger",
            "Oxlade", "Lojay", "Mayorkun", "Tekno", "Patoranking", "Johnny Drille",
            "King Promise", "Black Sherif", "Stonebwoy", "Diamond Platnumz", "Rayvanny",
            "Harmonize", "Zuchu", "Sauti Sol", "Libianca", "Darkoo", "J Hus", "NSG",
            "Kojo Funds", "Yxng Bane", "Not3s", "Fave", "KiDi", "Kuami Eugene",
            "Wande Coal", "P-Square", "Fally Ipupa", "Innoss'B", "Locko", "Chike",
            "Gyakie", "Amaarae",
        ],
        queries=["afro love", "afrobeats love", "afro rnb", "afropop"],
        playlists=["afro love", "afro hits", "afrobeats", "afro chill"],
    ),
    "afro_instr": dict(
        weight=130, artist_instr=None, pages=2,
        artists=[],
        queries=[
            "afrobeat instrumental", "afro type beat", "afrobeats type beat",
            "burna boy type beat", "wizkid type beat", "rema type beat",
            "omah lay type beat", "ckay type beat", "afro rnb type beat", "afro love beat",
            "afropop instrumental", "afro guitar beat", "afroswing type beat",
            "afro instru", "kompa instrumental", "zouk instrumental",
            "afro trap instrumental",
        ],
        playlists=["afrobeat instrumentals"],
    ),
    "french": dict(
        weight=230, artist_instr=False, related_k=12,
        artists=[
            "Dadju", "Tayc", "Aya Nakamura", "GIMS", "Ninho", "Niska", "Naza", "KeBlack",
            "Franglish", "Vegedream", "Hamza", "Damso", "SCH", "PNL", "Tiakola",
            "Joé Dwèt Filé", "Ronisia", "Imen Es", "Lyna Mahyem", "Wejdene", "Marwa Loud",
            "Slimane", "Vitaa", "Amel Bent", "Kendji Girac", "Black M", "Soolking", "Zola",
            "Werenoi", "Nej'", "Kalash", "Ya Levis", "Abou Debeing", "Hiro", "Leto",
            "Lefa", "Dinos", "Lomepal", "Jok'air", "Shay", "Uzi", "Nesly", "Dystinct",
            "Josman", "Maes", "Djadja & Dinaz", "Zaho", "Genezio", "Bolémvn", "L2B",
        ],
        queries=["rnb francais", "love afro francais", "pop urbaine", "chanson d'amour rnb"],
        playlists=["rnb francais", "pop urbaine", "love afro", "zouk konpa"],
    ),
    "french_instr": dict(
        weight=80, artist_instr=None, pages=2,
        artists=[],
        queries=[
            "instru rap francais", "instrumental rap francais", "instru triste",
            "instru piano triste", "instru guitare", "instru afro", "instru rnb",
            "dadju type beat", "tayc type beat", "ninho type beat",
            "aya nakamura type beat", "instru love", "instru melancolique",
        ],
        playlists=[],
    ),
    "poppunk": dict(
        weight=180, artist_instr=False, related_k=8,
        artists=[
            "blink-182", "Paramore", "Fall Out Boy", "My Chemical Romance", "Green Day",
            "Yellowcard", "All Time Low", "Sum 41", "Simple Plan", "Good Charlotte",
            "Neck Deep", "State Champs", "The Story So Far", "Mayday Parade",
            "Taking Back Sunday", "Dashboard Confessional", "Jimmy Eat World", "The Used",
            "Hawthorne Heights", "Brand New", "Modern Baseball", "Movements",
            "Hot Mulligan", "Knuckle Puck", "Real Friends", "Machine Gun Kelly",
            "Avril Lavigne", "YUNGBLUD", "WILLOW", "Waterparks", "Panic! At The Disco",
            "Linkin Park", "Three Days Grace", "Evanescence", "Twenty One Pilots",
            "The 1975", "Coldplay", "Snow Patrol", "The Fray", "OneRepublic",
            "Imagine Dragons", "Radiohead", "Sting", "Nirvana", "Olivia Rodrigo",
            "Pierce The Veil", "Sleeping With Sirens", "Bring Me The Horizon", "PVRIS",
            "Boys Like Girls", "5 Seconds of Summer", "The Wonder Years", "Mom Jeans.",
        ],
        queries=["pop punk instrumental", "emo instrumental", "rock ballad instrumental",
                 "midwest emo instrumental"],
        playlists=["pop punk", "emo classics", "rock ballads"],
    ),
    "acoustic": dict(
        weight=110, artist_instr=False,
        artists=[
            "Ed Sheeran", "Vance Joy", "Passenger", "Hozier", "Ben Howard", "Jack Johnson",
            "John Mayer", "Dermot Kennedy", "James Bay", "Shawn Mendes", "Lewis Capaldi",
            "Tom Odell", "Gerry Cinnamon", "Noah Kahan", "Zach Bryan", "Phoebe Bridgers",
            "Bon Iver", "Iron & Wine", "José González", "Damien Rice", "Jason Mraz",
            "Jake Bugg", "Alec Benjamin", "Jeremy Zucker", "Rex Orange County",
            "Dominic Fike", "Gracie Abrams", "Conan Gray", "Vianney", "Lauv",
        ],
        queries=["acoustic love song", "acoustic cover sad"],
        playlists=["acoustic chill", "acoustic covers"],
    ),
    "guitar_instr": dict(
        weight=90, artist_instr=True, pages=2,
        artists=["Tommy Emmanuel", "Andy McKee", "Sungha Jung", "Gabriella Quevedo",
                 "Antoine Dufour", "Ichika Nito", "Mike Dawes", "Jon Gomm"],
        queries=["acoustic guitar instrumental", "guitar instrumental", "fingerstyle guitar",
                 "campfire guitar", "sad guitar instrumental", "chill guitar",
                 "acoustic instrumental", "guitar loop"],
        playlists=["acoustic guitar instrumental"],
    ),
    "lofi": dict(
        weight=140, artist_instr=None, pages=2,
        artists=["Nujabes", "J Dilla", "Jinsang", "Tomppabeats", "idealism", "Kupla",
                 "Philanthrope", "Saib", "eery", "Joakim Karud", "Tom Doolie", "Aso",
                 "Knowmadic", "Kudasaibeats", "Mujo", "Sleepy Fish", "Elijah Who", "potsu",
                 "emune", "xander."],
        queries=["lofi hip hop", "lofi", "lofi beats", "chill beats", "lofi guitar",
                 "lofi piano", "sad lofi", "lofi rnb", "jazzhop", "chillhop"],
        playlists=["lofi beats", "lofi hip hop", "chillhop"],
    ),
    "piano_ballad": dict(
        weight=50, artist_instr=False,
        artists=["Adele", "Sam Smith", "James Arthur", "Birdy", "Calum Scott",
                 "Christina Perri", "A Great Big World", "Billie Eilish", "Lady Gaga",
                 "John Legend", "Alicia Keys", "Rag'n'Bone Man"],
        queries=["piano ballad", "sad piano song"],
        playlists=["piano ballads"],
    ),
    "piano_instr": dict(
        weight=90, artist_instr=True, pages=2,
        artists=["Ludovico Einaudi", "Yiruma", "Joep Beving", "Ólafur Arnalds",
                 "Max Richter", "Riopy", "Alexis Ffrench", "Fabrizio Paterlini",
                 "Philip Wesley", "Brian Crain"],
        queries=["piano instrumental", "sad piano", "emotional piano",
                 "piano ballad instrumental", "rap piano instrumental", "piano beat"],
        playlists=["peaceful piano", "sad piano"],
    ),
    "drill": dict(
        weight=80, artist_instr=False, related_k=4,
        artists=["Central Cee", "Headie One", "Pop Smoke", "Fivio Foreign", "Digga D",
                 "M Huncho", "ArrDee", "Dutchavelli", "Russ Millions", "Loski", "Fredo",
                 "Tion Wayne", "Gazo", "Sheff G", "Unknown T", "K-Trap", "Clavish"],
        queries=["melodic drill type beat", "drill instrumental", "uk drill beat",
                 "sad drill beat", "piano drill type beat", "guitar drill type beat",
                 "central cee type beat", "drill love type beat"],
        playlists=["drill uk"],
    ),
    "amapiano": dict(
        weight=75, artist_instr=None, related_k=4,
        artists=["Kabza De Small", "DJ Maphorisa", "Focalistic", "Uncle Waffles",
                 "Tyler ICU", "Young Stunna", "Mellow & Sleazy", "Major League DJz",
                 "Daliwonga", "Musa Keys", "Sha Sha", "Lady Du", "Kamo Mphela",
                 "Kelvin Momo", "Mas Musiq", "Toss", "Mr JazziQ", "Vigro Deep",
                 "De Mthuda", "MFR Souls", "Busta 929", "Tyla"],
        queries=["amapiano instrumental", "amapiano", "private school amapiano",
                 "amapiano love", "amapiano type beat"],
        playlists=["amapiano"],
    ),
    "dancehall": dict(
        weight=55, artist_instr=False,
        artists=["Sean Paul", "Popcaan", "Shenseea", "Koffee", "Charly Black", "Konshens",
                 "Shaggy", "Kranium", "Alkaline", "Masicka", "Vybz Kartel", "Chronixx",
                 "Protoje", "Jah Cure"],
        queries=["dancehall instrumental", "dancehall riddim", "reggae instrumental",
                 "afro dancehall type beat", "chill dancehall beat"],
        playlists=["dancehall"],
    ),
    "synthpop": dict(
        weight=75, artist_instr=False,
        artists=["The Weeknd", "The Midnight", "M83", "CHVRCHES", "Glass Animals",
                 "Tame Impala", "LANY", "Cigarettes After Sex", "Wallows", "Beach House",
                 "The Neighbourhood", "Chase Atlantic", "Gunship", "FM-84", "Kavinsky",
                 "Timecop1983", "Lorde", "Lana Del Rey", "Halsey", "Bastille"],
        queries=["synthwave", "synthwave instrumental", "retrowave", "dream pop",
                 "chillwave", "80s synth instrumental"],
        playlists=["synthwave", "dream pop"],
    ),
    "cinematic": dict(
        weight=60, artist_instr=True, pages=2,
        artists=["Hans Zimmer", "Two Steps From Hell", "Audiomachine", "Really Slow Motion",
                 "Explosions In The Sky", "This Will Destroy You", "Mogwai"],
        queries=["cinematic hip hop instrumental", "epic rap beat", "orchestral trap beat",
                 "cinematic trap", "dark orchestral hip hop", "emotional cinematic",
                 "violin type beat", "cello beat", "strings hip hop instrumental"],
        playlists=["cinematic"],
    ),
    "boombap": dict(
        weight=80, artist_instr=False,
        artists=["J. Cole", "Kendrick Lamar", "Mac Miller", "Joey Bada$$", "Nas",
                 "Common", "A Tribe Called Quest", "The Pharcyde", "Pete Rock & CL Smooth",
                 "Little Brother", "Statik Selektah", "Apollo Brown", "Dela", "Madlib",
                 "MF DOOM", "Kanye West", "Lupe Fiasco", "Mos Def", "Logic"],
        queries=["boom bap instrumental", "boom bap beat", "jazz hip hop instrumental",
                 "soul sample beat", "old school hip hop instrumental", "chill boom bap",
                 "90s hip hop instrumental"],
        playlists=["boom bap"],
    ),
    "charts": dict(
        weight=60, artist_instr=None,
        artists=[], queries=[], playlists=[],
        charts=[116, 165, 2, 85, 152, 132],   # rap, R&B, African, alternative, rock, pop
    ),
}

# Reference anchors (is_reference=true): Juice WRLD's catalog + Dadju - Reine.
REF_ARTIST = "Juice WRLD"
REF_EXTRA = [("Dadju", "Reine")]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def norm(s: str) -> str:
    """Lower-case, accent-stripped, punctuation-free form used for matching."""
    s = s or ""
    a = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    if not a.strip():                       # non-Latin scripts: keep original
        a = s.lower()
    return re.sub(r"[^\w]+", " ", a).strip()


def title_key(title: str) -> str:
    """Dedupe key for a title: drops feat./remaster/edit tags, keeps 'instrumental'."""
    t = title or ""
    instr = bool(re.search(r"instrumental|\binstru\b|karaoke", t, re.I))
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)                 # (feat ...), [Remastered]
    t = re.sub(r"\s[-–]\s.*$", " ", t)                          # " - Remastered 2011"
    t = re.sub(r"\b(feat|ft|featuring)\b\.?.*$", " ", t, flags=re.I)
    k = norm(t)
    return k + (" #instr" if instr else "")


def instr_hint(title: str, album_title: str = "", artist: str = "") -> bool:
    """True when title/album/artist name says 'instrumental', 'type beat', 'beats'..."""
    return any(INSTR_RE.search(x or "") for x in (title, album_title, artist))


def is_juice(name: str) -> bool:
    return norm(name).replace(" ", "") == "juicewrld"


def is_reine(title: str, artist: str) -> bool:
    nt, na = norm(title), norm(artist)
    return re.search(r"\breine\b", nt) is not None and ("dadju" in na or "dadju" in nt)


def safe_id(tid) -> str:
    return f"{SOURCE}_{int(tid)}"


def load_jsonl(path: str) -> list[dict]:
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass                        # tolerate a torn last line
    return rows


def ffprobe_duration(path: str) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return None


# --------------------------------------------------------------------------
# Deezer client: rate limit + retries + SQLite cache (for seeding calls)
# --------------------------------------------------------------------------
class RateLimiter:
    """Sliding-window limiter shared by all threads."""

    def __init__(self, max_calls: int, period: float):
        self.max_calls, self.period = max_calls, period
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                delay = self.period - (now - self.calls[0]) + 0.02
            time.sleep(delay)


class Deezer:
    def __init__(self, cache_path: str, rps: float):
        self.rl = RateLimiter(max(1, int(rps * 5)), 5.0)
        self.local = threading.local()
        self.db_lock = threading.Lock()
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
        self.db.commit()
        self.n_requests = 0

    def _session(self) -> requests.Session:
        s = getattr(self.local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = UA
            self.local.s = s
        return s

    def get(self, path: str, params: dict | None = None, cache: bool = True):
        params = dict(params or {})
        key = path + ("?" + urlencode(sorted(params.items())) if params else "")
        if cache:
            with self.db_lock:
                row = self.db.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
            if row is not None:
                return json.loads(row[0])
        data = None
        for attempt in range(6):
            self.rl.acquire()
            self.n_requests += 1
            try:
                r = self._session().get(API + path, params=params, timeout=20)
            except requests.RequestException:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            try:
                data = r.json()
            except ValueError:
                time.sleep(1.5 * (attempt + 1))
                continue
            if isinstance(data, dict) and "error" in data:
                code = (data.get("error") or {}).get("code")
                if code == 4:                              # quota exceeded
                    time.sleep(5.0 + 2 * attempt)
                    data = None
                    continue
                data = None                                # 800 no data / 300 / 100 ...
                if code == 800 and cache:
                    self._store(key, None)
                return None
            break
        else:
            return None
        if cache and data is not None:
            self._store(key, data)
        return data

    def _store(self, key, data):
        with self.db_lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                            (key, json.dumps(data), time.time()))
            self.db.commit()

    # ---- endpoint wrappers ------------------------------------------------
    def resolve_artist(self, name: str):
        d = self.get("/search/artist", {"q": name, "limit": 10})
        rows = (d or {}).get("data") or []
        if not rows:
            return None
        exact = [a for a in rows if norm(a.get("name")) == norm(name)]
        pick = max(exact, key=lambda a: a.get("nb_fan") or 0) if exact else rows[0]
        return {"id": pick["id"], "name": pick["name"]}

    def artist_top(self, aid: int, limit: int = 25) -> list:
        d = self.get(f"/artist/{aid}/top", {"limit": limit})
        return (d or {}).get("data") or []

    def related(self, aid: int, limit: int = 10) -> list:
        d = self.get(f"/artist/{aid}/related", {"limit": limit})
        return (d or {}).get("data") or []

    def search_tracks(self, q: str, pages: int = 1) -> list:
        out = []
        for p in range(pages):
            d = self.get("/search", {"q": q, "limit": 100, "index": p * 100})
            rows = (d or {}).get("data") or []
            out.extend(rows)
            if len(rows) < 100 or not (d or {}).get("next"):
                break
        return out

    def search_playlists(self, q: str, n: int = 2) -> list:
        d = self.get("/search/playlist", {"q": q, "limit": 25})
        rows = [p for p in ((d or {}).get("data") or []) if (p.get("nb_tracks") or 0) >= 15]
        editorial = [p for p in rows if "deezer" in norm((p.get("user") or {}).get("name"))]
        others = [p for p in rows if p not in editorial]
        return (editorial + others)[:n]

    def playlist_tracks(self, pid: int) -> list:
        d = self.get(f"/playlist/{pid}/tracks", {"limit": 100})
        return (d or {}).get("data") or []

    def chart_tracks(self, gid: int) -> list:
        d = self.get(f"/chart/{gid}/tracks", {"limit": 100})
        return (d or {}).get("data") or []

    def album_genres(self, alb_id) -> list[str]:
        if not alb_id:
            return []
        d = self.get(f"/album/{alb_id}")
        return [g.get("name") for g in ((d or {}).get("genres") or {}).get("data") or []
                if g.get("name")]


# --------------------------------------------------------------------------
# Seeding: build the ordered candidate plan
# --------------------------------------------------------------------------
def to_stub(t: dict, category: str, kind: str, query: str, instr_default) -> dict | None:
    if not isinstance(t, dict) or not t.get("id") or not t.get("artist"):
        return None
    return {
        "id": int(t["id"]),
        "title": t.get("title") or "",
        "artist": (t.get("artist") or {}).get("name") or "",
        "artist_id": (t.get("artist") or {}).get("id"),
        "album_title": (t.get("album") or {}).get("title") or "",
        "duration": t.get("duration") or 0,
        "readable": t.get("readable", True),
        "has_preview": bool(t.get("preview")),
        "category": category,
        "kind": kind,
        "query": query,
        "instr_default": instr_default,
    }


def collect_sources(dz: Deezer, workers: int, log) -> dict[str, list[tuple[str, list]]]:
    """Run all seed jobs (cached) and return {category: [(label, [stubs])...]}."""
    all_seed_names = {norm(a) for c in CATEGORIES.values() for a in c.get("artists", [])}
    jobs = []        # (category, kind, arg)
    for cat, cfg in CATEGORIES.items():
        seen_a = set()
        for a in cfg.get("artists", []):
            if norm(a) not in seen_a:
                seen_a.add(norm(a))
                jobs.append((cat, "artist", a))
        for q in cfg.get("queries", []):
            jobs.append((cat, "search", q))
        for q in cfg.get("playlists", []):
            jobs.append((cat, "playlist", q))
        for g in cfg.get("charts", []):
            jobs.append((cat, "chart", g))

    def run(job):
        cat, kind, arg = job
        cfg = CATEGORIES[cat]
        res = []                      # list of (label, kind, query, rows, instr_default)
        if kind == "artist":
            a = dz.resolve_artist(arg)
            if a and not is_juice(a["name"]):
                res.append((f"artist:{a['name']}", "artist_top", f"artist_top:{a['name']}",
                            dz.artist_top(a["id"], 25), cfg.get("artist_instr")))
            return job, res, a
        if kind == "search":
            res.append((f"search:{arg}", "search", f"search:{arg}",
                        dz.search_tracks(arg, cfg.get("pages", 1)), None))
        elif kind == "playlist":
            for p in dz.search_playlists(arg, 2):
                label = f"playlist:{p.get('title')} ({p['id']})"
                res.append((label, "playlist", f"playlist_search:{arg} -> {label}",
                            dz.playlist_tracks(p["id"]), None))
        elif kind == "chart":
            res.append((f"chart:{arg}", "chart", f"chart:genre_{arg}",
                        dz.chart_tracks(arg), None))
        return job, res, None

    log(f"[seed] running {len(jobs)} seed jobs ...")
    results = {}
    resolved = {}                     # (cat, artist name) -> resolved artist
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (job, res, a) in enumerate(ex.map(run, jobs)):
            results[job] = res
            if job[1] == "artist" and a:
                resolved[(job[0], job[2])] = a
            if (i + 1) % 100 == 0:
                log(f"[seed]   {i + 1}/{len(jobs)} jobs, api requests so far {dz.n_requests}")

    # Related-artist expansion (adds artist diversity to the core categories).
    rel_jobs = []
    seen_rel = set()
    for cat, cfg in CATEGORIES.items():
        k = cfg.get("related_k", 0)
        core = [resolved[(cat, a)] for a in cfg.get("artists", []) if (cat, a) in resolved][:k]
        for a in core:
            rel_jobs.append((cat, a))

    def run_rel(job):
        cat, a = job
        out = []
        for r in dz.related(a["id"], 10)[:5]:
            out.append(r)
        return job, out

    rel_targets = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (cat, a), rels in ex.map(run_rel, rel_jobs):
            for r in rels:
                nm = norm(r.get("name"))
                if nm in all_seed_names or nm in seen_rel or is_juice(r.get("name", "")):
                    continue
                seen_rel.add(nm)
                rel_targets.append((cat, a["name"], r))

    def run_rel_top(job):
        cat, src, r = job
        return job, dz.artist_top(r["id"], 10)

    rel_results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (cat, src, r), rows in ex.map(run_rel_top, rel_targets):
            rel_results.setdefault(cat, []).append(
                (f"related:{src}->{r['name']}", "related", f"related:{src}->{r['name']}", rows))
    log(f"[seed] related expansion: {len(rel_targets)} new artists; api requests {dz.n_requests}")

    sources: dict[str, list] = {c: [] for c in CATEGORIES}
    for job in jobs:
        cat = job[0]
        for label, kind, query, rows, instr_default in results.get(job, []):
            stubs = [s for s in (to_stub(t, cat, kind, query, instr_default) for t in rows) if s]
            if stubs:
                sources[cat].append((label, stubs))
    for cat, lst in rel_results.items():
        for label, kind, query, rows in lst:
            stubs = [s for s in (to_stub(t, cat, kind, query, None) for t in rows) if s]
            if stubs:
                sources[cat].append((label, stubs))
    return sources


def stub_ok(s: dict) -> str | None:
    """Pre-filter on listing metadata. Returns a reject reason or None."""
    if not s["readable"] or not s["has_preview"]:
        return "no_preview"
    if s["duration"] and not (MIN_FULL_DURATION <= s["duration"] <= MAX_FULL_DURATION):
        return "duration"
    if BAD_VERSION_RE.search(s["title"]) or BAD_VERSION_RE.search(s["album_title"]):
        return "bad_version"
    if is_juice(s["artist"]) or FEAT_JUICE_RE.search(s["title"]):
        return "juice_wrld"
    if is_reine(s["title"], s["artist"]):
        return "reine"
    return None


def build_plan(sources: dict[str, list], exclude_ids: set[int]) -> list[dict]:
    """Interleave sources (round-robin inside a category, weighted stride across
    categories), dedupe and cap per artist.  Deterministic given the cache."""
    def rr(srcs):
        depth = 0
        maxlen = max((len(st) for _, st in srcs), default=0)
        while depth < maxlen:
            for _, st in srcs:
                if depth < len(st):
                    yield st[depth]
            depth += 1

    gens = {c: rr(s) for c, s in sources.items() if s}
    passv = {c: 0.0 for c in gens}
    seen_ids, seen_keys = set(exclude_ids), set()
    per_artist: Counter = Counter()
    plan = []
    while gens:
        cat = min(gens, key=lambda c: (passv[c], c))
        try:
            s = next(gens[cat])
        except StopIteration:
            del gens[cat]
            continue
        if s["id"] in seen_ids:
            continue
        seen_ids.add(s["id"])
        if stub_ok(s):
            continue
        key = (norm(s["artist"]), title_key(s["title"]))
        if key in seen_keys:
            continue
        akey = s["artist_id"] or norm(s["artist"])
        if per_artist[akey] >= ARTIST_CAP:
            continue
        seen_keys.add(key)
        per_artist[akey] += 1
        plan.append(s)
        passv[cat] += 1.0 / CATEGORIES[cat]["weight"]
    return plan


def reference_plan(dz: Deezer, n_refs: int) -> list[dict]:
    """Juice WRLD top tracks (deduped by title) + Dadju - Reine."""
    plan = []
    a = dz.resolve_artist(REF_ARTIST)
    if a:
        seen = set()
        n_juice = max(0, n_refs - len(REF_EXTRA))
        for t in dz.artist_top(a["id"], 100):
            s = to_stub(t, "reference", "reference", f"reference:artist_top:{a['name']}", False)
            if not s or not s["has_preview"]:
                continue
            k = title_key(s["title"])
            if k in seen:
                continue
            seen.add(k)
            plan.append(s)
            if len(plan) >= n_juice:
                break
    for artist, title in REF_EXTRA:
        rows = []
        for q in (f'artist:"{artist}" track:"{title}"', f"{artist} {title}"):
            d = dz.get("/search", {"q": q, "limit": 25})
            rows = (d or {}).get("data") or []
            if rows:
                break
        rows = [t for t in rows if norm(t["artist"]["name"]) == norm(artist)
                and norm(t["title"]) == norm(title)] or [
               t for t in rows if norm(t["artist"]["name"]) == norm(artist)]
        if rows:
            s = to_stub(rows[0], "reference", "reference",
                        f"reference:{artist} - {title}", False)
            if s:
                plan.append(s)
    return plan


# --------------------------------------------------------------------------
# Fetch + clip
# --------------------------------------------------------------------------
def download_clip(url: str, dest: str) -> float | None:
    """Pull the preview with ffmpeg (only the bytes needed), re-encode, validate."""
    tmp = dest[:-4] + ".part.mp3"
    cmd = ["nice", "-n", "15", "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4",
           "-rw_timeout", "20000000",
           "-i", url, "-t", str(MAX_CLIP_DURATION), "-vn", "-map_metadata", "-1",
           "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", "-threads", "1", tmp]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        pass
    dur = ffprobe_duration(tmp) if os.path.exists(tmp) else None
    if dur is not None and dur >= MIN_CLIP_DURATION:
        os.replace(tmp, dest)
        return dur
    if os.path.exists(tmp):
        os.remove(tmp)
    return None


def process(stub: dict, dz: Deezer, is_ref: bool, juice_id: int | None):
    """Fetch details, clip the preview, return ('ok', record) or ('reject', reason)."""
    tid = stub["id"]
    t = dz.get(f"/track/{tid}", cache=False)          # fresh signed preview URL
    if not t:
        return "reject", "no_detail"
    if not t.get("readable") or not t.get("preview"):
        return "reject", "no_preview"
    dur_full = t.get("duration") or stub.get("duration") or 0
    contributors = t.get("contributors") or []
    if not is_ref:
        if dur_full and not (MIN_FULL_DURATION <= dur_full <= MAX_FULL_DURATION):
            return "reject", "duration"
        if any(c.get("id") == juice_id or is_juice(c.get("name", "")) for c in contributors):
            return "reject", "juice_wrld_feature"
        if is_reine(t.get("title", ""), (t.get("artist") or {}).get("name", "")):
            return "reject", "reine"

    clip = os.path.join(CLIP_DIR, safe_id(tid) + ".mp3")
    cdur = ffprobe_duration(clip) if os.path.exists(clip) else None   # reuse leftovers
    if cdur is None or cdur < MIN_CLIP_DURATION:
        cdur = download_clip(t["preview"], clip)
        if cdur is None:                              # one retry with a fresh URL
            time.sleep(1.0)
            t2 = dz.get(f"/track/{tid}", cache=False) or {}
            if t2.get("preview"):
                cdur = download_clip(t2["preview"], clip)
        if cdur is None:
            return "reject", "download_failed"

    album = t.get("album") or {}
    genres = dz.album_genres(album.get("id"))
    title = t.get("title") or stub["title"]
    album_title = album.get("title") or stub.get("album_title") or ""
    bpm = t.get("bpm")
    try:
        bpm = round(float(bpm), 2) if bpm and float(bpm) > 0 else None
    except (TypeError, ValueError):
        bpm = None

    main_artist = (t.get("artist") or {}).get("name") or stub["artist"]
    instr_kw = instr_hint(title, album_title, main_artist)
    instr = True if instr_kw else stub.get("instr_default")

    tags = [f"cat:{stub['category']}", f"src:{stub['kind']}"]
    tags += [f"genre:{g}" for g in genres]
    if (t.get("release_date") or "")[:4].isdigit():
        tags.append(f"year:{t['release_date'][:4]}")
    if t.get("explicit_lyrics"):
        tags.append("explicit")
    if instr_kw:
        tags.append("instrumental_kw")
    if re.search(r"type[\s-]?beat", title, re.I):
        tags.append("type_beat")
    if is_ref:
        tags.append("reference")

    feats = [c.get("name") for c in contributors
             if c.get("name") and c.get("name") != (t.get("artist") or {}).get("name")]
    artist = (t.get("artist") or {}).get("name") or stub["artist"]
    if feats:
        artist = artist + " feat. " + ", ".join(feats[:3])

    rec = {
        "id": f"{SOURCE}:{tid}",
        "source": SOURCE,
        "title": title,
        "artist": artist,
        "page_url": t.get("link") or f"https://www.deezer.com/track/{tid}",
        "clip_path": clip,
        "clip_start_s": None,                          # 30 s preview kept as-is
        "duration_full_s": dur_full or None,
        "license": LICENSE,
        "full_audio_url": None,
        "full_audio_available": False,
        "bpm_meta": bpm,
        "key_meta": None,
        "tags": tags,
        "is_instrumental_meta": instr,
        "query": stub["query"],
        "is_reference": bool(is_ref),
    }
    return "ok", rec


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def print_stats(log):
    rows = load_jsonl(JSONL)
    cands = [r for r in rows if not r.get("is_reference")]
    refs = [r for r in rows if r.get("is_reference")]
    cats = Counter(next((t[4:] for t in r["tags"] if t.startswith("cat:")), "?") for r in cands)
    size = sum(os.path.getsize(r["clip_path"]) for r in rows if os.path.exists(r["clip_path"]))
    log(f"[stats] candidates={len(cands)} references={len(refs)} "
        f"instrumental_meta_true={sum(1 for r in cands if r['is_instrumental_meta'] is True)} "
        f"bpm_known={sum(1 for r in cands if r['bpm_meta'])} "
        f"artists={len({r['artist'] for r in cands})} clips_bytes={size / 1e6:.0f}MB")
    log("[stats] by category: " + ", ".join(f"{k}={v}" for k, v in cats.most_common()))
    rej = load_jsonl(REJECTS)
    if rej:
        log("[stats] rejects: " + ", ".join(
            f"{k}={v}" for k, v in Counter(r.get("reason") for r in rej).most_common()))


def retag(log):
    """Offline pass: mark records instrumental when title/artist match INSTR_RE.
    Only ever flips a flag to True and adds the 'instrumental_kw' tag."""
    rows = load_jsonl(JSONL)
    n = 0
    for r in rows:
        artist = r["artist"].split(" feat. ")[0]
        if not r.get("is_reference") and instr_hint(r["title"], "", artist):
            if r["is_instrumental_meta"] is not True:
                n += 1
            r["is_instrumental_meta"] = True
            if "instrumental_kw" not in r["tags"]:
                r["tags"].append("instrumental_kw")
    tmp = JSONL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, JSONL)
    log(f"[retag] {n} records newly marked instrumental")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", type=int, default=2500, help="number of (non-reference) candidates")
    ap.add_argument("--n-refs", type=int, default=60, help="number of reference tracks")
    ap.add_argument("--max-seconds", type=float, default=500, help="stop submitting work after this")
    ap.add_argument("--workers", type=int, default=8, help="parallel fetch/download workers (<= 8)")
    ap.add_argument("--rps", type=float, default=8.0, help="API requests per second (Deezer max 10)")
    ap.add_argument("--dry-run", action="store_true", help="seed + print the plan, no downloads")
    ap.add_argument("--stats", action="store_true", help="only print stats of the output")
    ap.add_argument("--retag", action="store_true",
                    help="re-apply the instrumental keyword rule to existing records (no API)")
    args = ap.parse_args()

    t0 = time.monotonic()
    log = lambda m: print(f"{time.monotonic() - t0:7.1f}s {m}", flush=True)  # noqa: E731
    os.makedirs(CLIP_DIR, exist_ok=True)
    if args.stats:
        print_stats(log)
        return
    if args.retag:
        retag(log)
        return
    for f in os.listdir(CLIP_DIR):                     # leftovers of killed ffmpeg runs
        if f.endswith(".part.mp3"):
            os.remove(os.path.join(CLIP_DIR, f))

    workers = max(1, min(args.workers, 8))
    dz = Deezer(CACHE_DB, min(args.rps, 9.0))

    done_rows = load_jsonl(JSONL)
    done = {int(r["id"].split(":", 1)[1]) for r in done_rows}
    n_cand = sum(1 for r in done_rows if not r.get("is_reference"))
    n_ref = sum(1 for r in done_rows if r.get("is_reference"))
    rejected = {int(r["native_id"]) for r in load_jsonl(REJECTS)}
    log(f"[resume] {n_cand} candidates + {n_ref} references done, {len(rejected)} rejected")

    juice = dz.resolve_artist(REF_ARTIST)
    juice_id = juice["id"] if juice else None
    refs = reference_plan(dz, args.n_refs)
    ref_ids = {s["id"] for s in refs}
    sources = collect_sources(dz, workers, log)
    plan = build_plan(sources, exclude_ids=ref_ids)
    log(f"[plan] {len(plan)} candidate tracks in plan (target {args.target}), "
        f"{len(refs)} references; api requests {dz.n_requests}")
    head = Counter(s["category"] for s in plan[: args.target])
    log("[plan] first-target mix: " + ", ".join(f"{k}={v}" for k, v in head.most_common()))
    if args.dry_run:
        tot = Counter(s["category"] for s in plan)
        log("[plan] full pool: " + ", ".join(f"{k}={v}" for k, v in tot.most_common()))
        return

    out = open(JSONL, "a", encoding="utf-8")
    rej_out = open(REJECTS, "a", encoding="utf-8")
    queue = [(s, True) for s in refs if s["id"] not in done and s["id"] not in rejected]
    queue += [(s, False) for s in plan if s["id"] not in done and s["id"] not in rejected]
    log(f"[fetch] {len(queue)} queued; workers={workers}")

    stats = Counter()
    it = iter(queue)
    inflight = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while True:
            # keep the pool busy, but never overshoot the target
            while (len(inflight) < workers * 2 and time.monotonic() - t0 < args.max_seconds):
                pending_c = sum(1 for v in inflight.values() if not v[1])
                nxt = next(it, None)
                if nxt is None:
                    break
                s, is_ref = nxt
                if not is_ref and n_cand + pending_c >= args.target:
                    it = iter(())                      # target reached: stop feeding
                    break
                inflight[ex.submit(process, s, dz, is_ref, juice_id)] = (s, is_ref)
            if not inflight:
                break
            fin, _ = wait(list(inflight), timeout=60, return_when=FIRST_COMPLETED)
            for fu in fin:
                s, is_ref = inflight.pop(fu)
                try:
                    status, payload = fu.result()
                except Exception as e:                 # never let one track kill the run
                    status, payload = "reject", f"error:{type(e).__name__}"
                if status == "ok":
                    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    out.flush()
                    if is_ref:
                        n_ref += 1
                    else:
                        n_cand += 1
                    stats["ok"] += 1
                else:
                    # transient failures are retried on the next run; others are final
                    if payload != "no_detail" and not payload.startswith("error:"):
                        rej_out.write(json.dumps({"native_id": s["id"], "reason": payload,
                                                  "title": s["title"], "artist": s["artist"]},
                                                 ensure_ascii=False) + "\n")
                        rej_out.flush()
                    stats[payload] += 1
                if sum(stats.values()) % 100 == 0:
                    log(f"[fetch] candidates={n_cand} refs={n_ref} this-run={dict(stats)} "
                        f"api={dz.n_requests}")
    out.close()
    rej_out.close()
    log(f"[done] candidates={n_cand}/{args.target} refs={n_ref} this-run={dict(stats)}; "
        f"{'TARGET REACHED' if n_cand >= args.target else 'run again to continue'}")
    print_stats(log)


if __name__ == "__main__":
    main()
