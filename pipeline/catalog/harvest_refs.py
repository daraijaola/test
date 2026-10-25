#!/opt/av/bin/python
"""Harvest hand-curated STYLE REFERENCES + famous instrumentals ("refs" source).

Part of the Juice WRLD "Reine" freestyle remix project (personal, non-commercial).
This script ONLY harvests clips + metadata; scoring (tempo / key / CLAP vibe)
happens later in other pipeline stages.

Two parts
---------
1. References (is_reference=true).  ~80 songs that DEFINE the target sound,
   as 30 s Deezer previews: Juice WRLD's melodic hits and deep cuts, close
   peers' guitar-led emo-rap (Trippie Redd, The Kid LAROI, iann dior, Lil Peep,
   XXXTENTACION ballads, Nick Mira / Internet Money productions) and the
   original Dadju - "Reine".  They anchor the "Juice vibe" embedding.
2. Candidates (is_reference=false).  ~100 deliberately chosen "plausibly
   perfect" backings for a melodic Juice vocal: instrumental versions of
   famous emo-rap / R&B / afro / French pop-urbaine / pop-punk / lo-fi songs
   (official instrumentals when they exist, faithful remakes otherwise), a few
   acoustic-guitar versions and natively-instrumental / sparse originals, and
   (for the most important songs, or where Deezer has none) a SoundCloud upload
   of the instrumental so the FULL beat can be fetched later.  Every candidate
   carries a one-line "rationale: ..." tag explaining why it was chosen.
   One extra is_reference=true record is a calibration CONTROL: a remake of the
   original Reine instrumental (tag control:original_beat), i.e. the expected
   upper bound of the tempo / key fit scores - not a new-beat candidate.

How a curated item is resolved
------------------------------
* The original song is looked up on Deezer (artist + title match, highest
  rank, no remix/live/instrumental versions) -> duration / bpm sanity anchor.
* Deezer instrumental: "<title> instrumental" / "<artist> <title> instrumental"
  searches; a result must contain the song title + an instrumental keyword,
  must not be a slowed / sped-up / lo-fi / piano / sax / "best part" / loop
  re-interpretation (unless that variant is asked for), and its duration must
  be within 0.55x-1.7x of the original.  Ranking: official (same artist) >
  "instrumental" remakes > karaoke, then Deezer popularity, then duration fit.
* Title matching is strict: some " - " / "|" segment of the result title must
  be exactly the song name once artist names and noise words ("Originally
  Performed by", "Instrumental Version", "Remake" ...) are removed, so other
  songs containing the name ("Empty Out Your Pockets", "Love Scars 3") are
  rejected.  Generic titles ("Changes", "Water", "Baby") must also name the
  original artist in the title / album / artist field (DISTINCT_TITLES lists the
  titles exempt from that rule).
* SoundCloud instrumental: scsearch30 "<artist> <title> instrumental"; same
  title / keyword / variant rules, no type beats / mashups / flips, full-length
  streams preferred over 30 s "snipped" previews; ranked by plays and duration fit.
* Clips: Deezer previews are kept as-is (<= 44.5 s).  SoundCloud clips are
  40 s starting ~30 % into the track; only the needed HLS segments are fetched.
  Everything is re-encoded to MP3 128 kbps / 44.1 kHz and validated with
  ffprobe (>= 20 s) or deleted.

Plumbing is reused from the sibling harvesters (same directory): the Deezer
client (rate limit + retries + SQLite cache) from harvest_deezer.py and the
SoundCloud search / resolve / HLS-excerpt code from harvest_soundcloud.py,
pointed at this source's own cache / tmp directories.

Resumable: every record carries an "item:<key>" tag; items already in
candidates.jsonl or rejects.jsonl (permanent "no match") are skipped, network
failures are retried on the next run, --max-seconds stops submitting work.
CPU-light: no audio analysis; ffmpeg runs single-threaded under nice.
Politeness: Deezer <= --rps requests/s (limit is 50 / 5 s), SoundCloud
resolutions <= --sc-rps per second with global back-off on HTTP 429.

Usage
-----
  /opt/av/bin/python harvest_refs.py --max-seconds 500          # harvest (repeat until done)
  /opt/av/bin/python harvest_refs.py --dry-run                  # resolve picks, no downloads
  /opt/av/bin/python harvest_refs.py --only refs|candidates     # one part only
  /opt/av/bin/python harvest_refs.py --retry-rejects            # re-try "no match" items (after list edits)
  /opt/av/bin/python harvest_refs.py --stats                    # summarize the output JSONL
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_deezer as hdz  # noqa: E402  (Deezer client, clip download, helpers)
import harvest_soundcloud as hsc  # noqa: E402  (SoundCloud search / resolve / HLS excerpt)

# --------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------
SOURCE = "refs"
ROOT = "/home/user/test"
OUT_DIR = os.path.join(ROOT, "work", "catalog", SOURCE)
CLIP_DIR = os.path.join(OUT_DIR, "clips")
TMP_DIR = os.path.join(OUT_DIR, "tmp")
JSONL = os.path.join(OUT_DIR, "candidates.jsonl")
REJECTS = os.path.join(OUT_DIR, "rejects.jsonl")
DZ_CACHE = os.path.join(OUT_DIR, "deezer_cache.sqlite")
SC_SEARCH_DIR = os.path.join(OUT_DIR, "sc_search_cache")
OTHER_SOURCES = ("deezer", "soundcloud")      # tagged "also_in:<id>" on overlap

DZ_LICENSE = "all-rights-reserved (Deezer 30 s preview; personal non-commercial use only)"
SC_PER_QUERY = 30
MIN_CLIP = 20.0
DUR_RATIO = (0.55, 1.7)                       # instrumental duration vs original

# Point the reused SoundCloud helpers at this source's directories.
hsc.TMP_DIR = TMP_DIR
hsc.SEARCH_DIR = SC_SEARCH_DIR

norm = hdz.norm

# A result title must contain one of these to count as an instrumental.
INSTR_KW = re.compile(r"instrumental|instrumentale|\binstru\b|karaoke|backing track|\bremake\b|"
                      r"\breprod\b|\bre-?prod\b", re.I)
SC_INSTR_KW = re.compile(INSTR_KW.pattern + r"|\binst\b|\bbeat\b", re.I)  # NOT "prod." (vocal uploads)
# Re-interpretations that change tempo / instrumentation (rejected unless asked for).
# Applied to the NORMALIZED title with the song title itself removed (so a song
# called "Slow Dancing In The Dark" or "Fast" is not rejected for its own name).
_VB = (r"slowed|sped|speed\s*up|reverb|nightcore|\b8d\b|daycore|lo\s*fi|piano|\bsax|violin|"
       r"cello|string|music\s*box|lullaby|orchestr|jazz|bossa|harp|marimba|kalimba|flute|"
       r"8\s*bit|ringtone|meditation|relax|sleep|chill\s*out|best part|\bloop|tik\s*tok|"
       r"\bedit\b|extended|\bcover\b|\bremix\b|\bmix\b|bass\s*boost|phonk|drill|jersey|"
       r"\bfunk\b|amapiano version|reggae version|rock version|metal|"
       r"a\s*cappella|acapella|vocals? only|\bhours?\b|\bflip\b|rework|bootleg|mashup|\bvs\b|"
       r"type\s*beat|beat\s*type|snippet|\bleak|unreleased|\bclean\b|\bdirty\b|\bslow\b|\bfast\b|"
       r"\bsolo\b|\bmidi\b|marching|choir|gospel|cumbia|salsa|bachata|\bversion \d|"
       r"\b9d\b|\b16d\b|rhodes|fitness|workout|aerobic|\bwedding\b|\bbirthday\b")
VARIANT_BAD = re.compile(_VB + r"|acoustic|guitar", re.I)
VARIANT_BAD_ACOUSTIC = re.compile(_VB, re.I)          # for variant="acoustic"
# Same idea for artist / album names of tribute labels (piano / lo-fi / lullaby ...).
ARTIST_BAD = re.compile(
    r"piano|lo\s*fi|lullaby|rockabye|\bsax|violin|cello|string|quartet|music\s*box|8\s*bit|"
    r"jazz|\bkids?\b|bossa|harp|relax|sleep|meditation|slowed|reverb|chill|guitar|acoustic|"
    r"orchestr|marimba|kalimba|ringtone|\bstudy\b|\bspa\b|nightcore|8d", re.I)
# Version tags that disqualify a track as "the original" (references / originals).
ORIG_BAD = re.compile(
    r"instrumental|\binstru\b|karaoke|slowed|sped|speed[\s-]*up|reverb|nightcore|\b8d\b|"
    r"remix|\blive\b|acoustic|a ?cappella|acapella|\bdemo\b|\bclean\b|\bversion\b|"
    r"\bedit\b|\bmix\b|extended|piano|lo-?fi|cover|tribute|karaoké|\bvip\b", re.I)
# Harmless version tags of an original recording.
ORIG_OK = re.compile(r"album version|original version|original mix|radio edit|"
                     r"(explicit|clean|main|lp|single) version|explicit|"
                     r"with instrumental by [^)\]]*|bonus track( version)?|"
                     r"remaster(ed)?( \d{4})?|\d{4} remaster(ed)?|from [^)\]]*soundtrack[^)\]]*", re.I)
SC_MASHUP = re.compile(r"mashup|medley|\bblend\b", re.I)   # plus: >= 2 " - " separators


# --------------------------------------------------------------------------
# Curated lists
# --------------------------------------------------------------------------
@dataclass
class Ref:
    artist: str          # Deezer main artist of the original
    title: str
    group: str           # juice_hit / juice_deep_cut / peer_<name> / nick_mira / original
    note: str            # why it is a style anchor
    alt: tuple = ()      # other acceptable main-artist names
    q: str = ""          # extra Deezer search query when "<artist> <title>" is not enough
    dz_id: int = 0       # pinned Deezer track id when search cannot find a short title

    @property
    def key(self) -> str:
        return f"ref|{norm(self.artist)}|{norm(self.title)}"


@dataclass
class Cand:
    artist: str          # original artist (Deezer main artist)
    title: str           # original title
    cat: str             # genre bucket
    why: str             # one-line rationale (stored as "rationale: ..." tag)
    via: str = "dz"      # dz | sc | both
    variant: str = "instrumental"   # instrumental | acoustic | original
    alt: tuple = ()      # other acceptable main-artist names for the original
    q: tuple = ()        # Deezer search queries (default: "<title> instrumental", ...)
    scq: str = ""        # SoundCloud query (default: "<artist> <title> instrumental")
    instr: bool | None = None   # is_instrumental_meta for variant=original
    distinct: bool = False      # title is distinctive: accept remakes that do not name the artist
    as_ref: bool = False        # store as is_reference=true (calibration control, not a candidate)
    aliases: tuple = ()         # other spellings of the title used by uploaders ("NypensePlus")
    allow: tuple = ()           # version words tolerated for this item (e.g. "remix")

    def wants(self) -> list[str]:
        return [w for w in dict.fromkeys([core(self.title)] + [core(a) for a in self.aliases]) if w]

    def key(self, platform: str) -> str:
        kind = "control" if self.as_ref else "cand"
        return f"{kind}|{platform}|{self.variant}|{norm(self.artist)}|{norm(self.title)}"


J = "Juice WRLD"
REFERENCES: list[Ref] = [
    # --- Juice WRLD: melodic hits ----------------------------------------
    Ref(J, "Lucid Dreams", "juice_hit", "Nick Mira guitar loop; the signature melodic Juice sound"),
    Ref(J, "All Girls Are The Same", "juice_hit", "breakout emo-rap single, dark guitar/synth"),
    Ref(J, "Robbery", "juice_hit", "piano-ballad heartbreak, long sung melodies"),
    Ref(J, "Wishing Well", "juice_hit", "airy guitar, sad-but-bright melodic flow"),
    Ref(J, "Legends", "juice_hit", "soft guitar ballad, slow"),
    Ref(J, "Righteous", "juice_hit", "dreamy psychedelic guitar, floating melody"),
    Ref(J, "Hear Me Calling", "juice_hit", "dancehall/afro-tinged melodic trap"),
    Ref(J, "Empty", "juice_hit", "guitar trap, emotional minor loop"),
    Ref(J, "Lean Wit Me", "juice_hit", "sad guitar loop, Goodbye & Good Riddance"),
    Ref(J, "Bandit", "juice_hit", "Nick Mira bouncy melodic trap", alt=("YoungBoy Never Broke Again",),
        dz_id=765869632),                        # Juice's own release (search surfaces NBA's copy)
    Ref(J, "Come & Go", "juice_hit", "pop-punk guitar + EDM; rock-crossover lane", alt=("Marshmello",)),
    Ref(J, "Conversations", "juice_hit", "melancholic synth/guitar, heartfelt delivery"),
    Ref(J, "Life's A Mess", "juice_hit", "love duet with Halsey, guitar-led", alt=("Halsey",)),
    Ref(J, "Smile", "juice_hit", "R&B-leaning love duet with The Weeknd", alt=("The Weeknd",)),
    Ref(J, "Wasted", "juice_hit", "melodic trap duet with Lil Uzi Vert", alt=("Lil Uzi Vert",)),
    Ref(J, "Black & White", "juice_hit", "upbeat melodic trap, guitar plucks"),
    Ref(J, "Hide", "juice_hit", "Spider-Verse soundtrack love song, soft", alt=("Seezyn",)),
    Ref(J, "Let Me Know (I Wonder Why Freestyle)", "juice_hit",
        "Juice's own melodic LOVE FREESTYLE - closest format to the Reine freestyle"),
    Ref(J, "Fast", "juice_hit", "guitar-driven, introspective"),
    Ref(J, "Used To", "juice_hit", "sad guitar melodic trap"),
    Ref(J, "I'll Be Fine", "juice_hit", "emo-rap guitar, Goodbye & Good Riddance"),
    Ref(J, "Candles", "juice_hit", "minor guitar loop, dark melodic"),
    Ref(J, "Burn", "juice_hit", "melodic guitar trap, posthumous"),
    Ref(J, "Cigarettes", "juice_hit", "love-song melodic trap, posthumous"),
    Ref(J, "Already Dead", "juice_hit", "melancholic guitar/synth"),
    Ref(J, "Stay High", "juice_hit", "melodic trap"),
    Ref(J, "Maze", "juice_hit", "guitar emo-rap, Death Race for Love"),
    Ref(J, "Flaws And Sins", "juice_hit", "love song, soft guitar"),
    Ref(J, "Reminds Me Of You", "juice_hit", "love song with The Kid LAROI (Cherish sample)",
        alt=("The Kid LAROI",)),
    Ref(J, "Wandered To LA", "juice_hit", "pop-rap with Justin Bieber, melodic", alt=("Justin Bieber",)),
    Ref(J, "Girl Of My Dreams", "juice_hit", "love song with SUGA, melodic", alt=("SUGA",)),
    Ref(J, "Feeling", "juice_hit", "melodic trap, sung"),
    Ref(J, "Tell Me U Luv Me", "juice_hit", "love song with Trippie Redd", alt=("Trippie Redd",)),
    # --- Juice WRLD: deep cuts ------------------------------------------
    Ref(J, "Won't Let Go", "juice_deep_cut", "love song, guitar ballad"),
    Ref(J, "She's The One", "juice_deep_cut", "love song, Death Race for Love"),
    Ref(J, "Desire", "juice_deep_cut", "guitar emo-rap, deep cut"),
    Ref(J, "Make Believe", "juice_deep_cut", "melancholic love song"),
    Ref(J, "Rich And Blind", "juice_deep_cut", "guitar ballad"),
    Ref(J, "Scared Of Love", "juice_deep_cut", "acoustic-leaning love song"),
    Ref(J, "End Of The Road", "juice_deep_cut", "sad melodic, Goodbye & Good Riddance"),
    Ref(J, "Ring Ring", "juice_deep_cut", "melodic love song with Clever", alt=("Clever",)),
    Ref(J, "Fighting Demons", "juice_deep_cut", "posthumous melodic emo-rap"),
    Ref(J, "Up Up And Away", "juice_deep_cut", "uplifting melodic trap"),
    # --- Peers -----------------------------------------------------------
    Ref("Trippie Redd", "Love Scars", "peer_trippie", "dreamy guitar love-trap"),
    Ref("Trippie Redd", "Taking A Walk", "peer_trippie", "guitar-led melodic trap"),
    Ref("Trippie Redd", "Topanga", "peer_trippie", "melodic emo-trap, 2018"),
    Ref("Trippie Redd", "Dark Knight Dummo", "peer_trippie", "melodic trap with Travis Scott",
        alt=("Travis Scott",)),
    Ref("Trippie Redd", "Who Needs Love", "peer_trippie", "emo-rap love song"),
    Ref("The Kid LAROI", "WITHOUT YOU", "peer_laroi", "acoustic guitar breakup ballad"),
    Ref("The Kid LAROI", "WRONG", "peer_laroi", "melodic guitar emo-rap", alt=("Lil Mosey",)),
    Ref("The Kid LAROI", "Thousand Miles", "peer_laroi", "pop-punk guitar"),
    Ref("The Kid LAROI", "So Done", "peer_laroi", "guitar pop-rap"),
    Ref("The Kid LAROI", "TRAGIC", "peer_laroi", "melodic emo-rap", alt=("YoungBoy Never Broke Again",)),
    Ref("The Kid LAROI", "GO", "peer_laroi", "duet with Juice WRLD, guitar", alt=(J,),
        dz_id=1445417802),                       # Deezer search does not surface the 2-letter title
    Ref("iann dior", "emotions", "peer_iann_dior", "guitar emo-trap"),
    Ref("iann dior", "gone girl", "peer_iann_dior", "guitar pop-rap love song", alt=("Trippie Redd",)),
    Ref("iann dior", "prospect", "peer_iann_dior", "emo-rap", alt=("Lil Baby",)),
    Ref("24kGoldn", "Mood", "peer_iann_dior", "guitar pop-rap hit with iann dior", alt=("iann dior",)),
    Ref("Lil Peep", "Star Shopping", "peer_lil_peep", "lo-fi guitar emo-rap blueprint"),
    Ref("Lil Peep", "Awful Things", "peer_lil_peep", "pop-punk emo ballad", alt=("Lil Tracy",)),
    Ref("Lil Peep", "Benz Truck", "peer_lil_peep", "guitar emo-trap"),
    Ref("Lil Peep", "Save That Shit", "peer_lil_peep", "melodic emo-rap"),
    Ref("Lil Peep", "The Way I See Things", "peer_lil_peep", "acoustic guitar emo"),
    Ref("Lil Peep", "Falling Down", "peer_lil_peep", "acoustic duet with XXXTENTACION",
        alt=("XXXTENTACION",)),
    Ref("Lil Peep", "Beamer Boy", "peer_lil_peep", "guitar emo-rap"),
    Ref("XXXTENTACION", "Jocelyn Flores", "peer_xxx", "sad lo-fi guitar/piano ballad"),
    Ref("XXXTENTACION", "SAD!", "peer_xxx", "piano melodic trap heartbreak"),
    Ref("XXXTENTACION", "changes", "peer_xxx", "piano love ballad"),
    Ref("XXXTENTACION", "Moonlight", "peer_xxx", "dark melodic trap"),
    Ref("XXXTENTACION", "Fuck Love", "peer_xxx", "guitar emo-trap with Trippie Redd",
        alt=("Trippie Redd",)),
    Ref("XXXTENTACION", "Hope", "peer_xxx", "soft melodic ballad"),
    Ref("XXXTENTACION", "Revenge", "peer_xxx", "acoustic guitar emo ballad"),
    Ref("XXXTENTACION", "the remedy for a broken heart (why am I so in love)", "peer_xxx",
        "love song, melodic"),
    # --- Nick Mira / Internet Money productions ----------------------------
    Ref("Lil Tecca", "Ransom", "nick_mira", "Nick Mira & Taz Taylor production"),
    Ref("Lil Tecca", "Did It Again", "nick_mira", "Internet Money production, melodic pluck"),
    Ref("Internet Money", "Lemonade", "nick_mira", "Internet Money guitar trap",
        alt=("Gunna", "Don Toliver", "NAV")),
    Ref("Internet Money", "Somebody", "nick_mira", "Internet Money melodic trap",
        alt=("Lil Tecca", "A Boogie Wit da Hoodie")),
    Ref("Lil Uzi Vert", "XO TOUR Llif3", "peer_emo", "emo-rap anthem, melodic synth"),
    # --- The original ------------------------------------------------------
    Ref("Dadju", "Reine", "original", "the original song Juice freestyled over (afro-pop / R&B)"),
]

CANDIDATES: list[Cand] = [
    # --- Juice WRLD's own famous beats (instrumentals) -----------------------
    Cand(J, "Lucid Dreams", "emo_trap", "Nick Mira guitar loop on the Sting sample; the archetypal Juice beat", via="both"),
    Cand(J, "All Girls Are The Same", "emo_trap", "Nick Mira dark guitar/synth melodic trap, his 2018 breakout sound", via="both"),
    Cand(J, "Robbery", "emo_trap", "piano-ballad trap about heartbreak; slow, room for long sung lines", via="both"),
    Cand(J, "Wishing Well", "emo_trap", "airy guitar/synth melodic trap, mid-tempo sad-bright mood", via="both"),
    Cand(J, "Legends", "emo_trap", "soft guitar-arpeggio ballad, slow and spacious"),
    Cand(J, "Righteous", "emo_trap", "dreamy psychedelic guitar bed, floating melody"),
    Cand(J, "Hear Me Calling", "emo_trap", "dancehall/afro-tinged melodic trap: bridges Juice's style and the afro-pop original", via="both"),
    Cand(J, "Empty", "emo_trap", "Death Race era guitar trap, emotional minor loop"),
    Cand(J, "Lean Wit Me", "emo_trap", "Nick Mira sad guitar loop, Goodbye & Good Riddance era"),
    Cand(J, "Let Me Know (I Wonder Why Freestyle)", "emo_trap", "beat of Juice's own melodic love freestyle - same improvised setting", via="both",
         q=("let me know instrumental", "let me know i wonder why freestyle instrumental"),
         scq="juice wrld let me know instrumental"),
    Cand(J, "Come & Go", "poppunk", "pop-punk guitar verses + EDM drop; Juice's rock-crossover lane", alt=("Marshmello",)),
    # --- peers' emo-rap / melodic trap ----------------------------------------
    Cand("XXXTENTACION", "Jocelyn Flores", "emo_trap", "sad guitar/piano lo-fi loop (Potsu sample), minimal heartbreak", via="both"),
    Cand("XXXTENTACION", "changes", "piano", "bare piano love ballad, slow"),
    Cand("XXXTENTACION", "SAD!", "emo_trap", "bright piano/synth melodic trap, 2018 emo-rap peak"),
    Cand("XXXTENTACION", "Moonlight", "emo_trap", "dark melodic pluck trap, hypnotic minor loop"),
    Cand("Lil Peep", "Star Shopping", "emo_trap", "Kryptik lo-fi guitar loop, the emo-rap blueprint", via="both"),
    Cand("Lil Peep", "Awful Things", "poppunk", "pop-punk guitar ballad x trap hybrid", alt=("Lil Tracy",), via="both"),
    Cand("Lil Peep", "Benz Truck", "emo_trap", "guitar-driven emo trap, mid-tempo"),
    Cand("The Kid LAROI", "WITHOUT YOU", "acoustic", "acoustic-guitar pop-rap breakup ballad by Juice's protege", via="both"),
    Cand("The Kid LAROI", "Thousand Miles", "poppunk", "upbeat pop-punk guitar in the Juice/LAROI rock lane"),
    Cand("iann dior", "emotions", "emo_trap", "guitar emo trap from the 2019 Internet Money circle", via="both"),
    Cand("Trippie Redd", "Love Scars", "emo_trap", "dreamy guitar/synth love-trap, emo-rap classic", via="both"),
    Cand("Trippie Redd", "Taking A Walk", "emo_trap", "guitar-led melodic trap, upbeat sadness"),
    Cand("Lil Uzi Vert", "XO TOUR Llif3", "emo_trap", "TM88 dark melodic synth, emo-rap anthem"),
    Cand("Lil Tecca", "Ransom", "emo_trap", "Nick Mira & Taz Taylor bouncy pluck melody (Internet Money)"),
    Cand("Internet Money", "Lemonade", "emo_trap", "Internet Money (Nick Mira's collective) melodic guitar trap",
         alt=("Gunna", "Don Toliver", "NAV")),
    Cand("Post Malone", "Circles", "acoustic", "soft-rock guitar groove, live-band melodic pop-rap", via="both"),
    Cand("Post Malone", "Better Now", "emo_trap", "melancholic guitar/synth pop-rap breakup song"),
    Cand("Lil Skies", "Red Roses", "emo_trap", "melodic guitar trap with a love theme", alt=("Landon Cube",), via="both"),
    Cand("Lil Mosey", "Noticed", "emo_trap", "bouncy melodic guitar trap, 2018", via="both"),
    Cand("Polo G", "RAPSTAR", "emo_trap", "ukulele/guitar melodic trap, reflective"),
    Cand("Lil Tjay", "Calling My Phone", "rnb", "guitar-led sad R&B-trap love song (with 6LACK)", alt=("6LACK",)),
    Cand("Rod Wave", "Heart On Ice", "sad_hiphop", "soulful sad guitar/piano trap ballad"),
    Cand("Kid Cudi", "Pursuit Of Happiness", "synthpop", "Ratatat synth-psych melodic hip-hop, the emo-rap ancestor",
         alt=("MGMT", "Ratatat")),
    # --- R&B -------------------------------------------------------------------
    Cand("Daniel Caesar", "Best Part", "rnb", "slow guitar R&B love duet - matches Reine's love theme", via="both",
         alt=("H.E.R.",)),
    Cand("Daniel Caesar", "Best Part", "acoustic", "acoustic-guitar instrumental of the R&B love duet (campfire guitar)",
         variant="acoustic", via="sc", alt=("H.E.R.",), scq="daniel caesar best part acoustic instrumental"),
    Cand("Khalid", "Location", "rnb", "minimal guitar R&B, slow 6/8 love groove"),
    Cand("Bryson Tiller", "Don't", "rnb", "trapsoul blueprint: R&B melodies over trap drums"),
    Cand("6LACK", "PRBLMS", "rnb", "moody guitar trapsoul about relationship problems"),
    Cand("The Weeknd", "Call Out My Name", "rnb", "6/8 heartbreak R&B ballad"),
    Cand("The Weeknd", "Die For You", "rnb", "synth R&B love ballad, much remixed"),
    Cand("Drake", "Passionfruit", "dancehall", "dancehall-lite R&B groove with warm keys"),
    Cand("Drake", "Hold On, We're Going Home", "synthpop", "80s synth R&B love song", alt=("Majid Jordan",)),
    Cand("Drake", "One Dance", "afro", "afro-dancehall groove (Wizkid/Kyla) bridging afro-pop and hip-hop",
         alt=("Wizkid", "Kyla")),
    Cand("Frank Ocean", "Thinkin Bout You", "rnb", "lush synth R&B love song, falsetto-friendly"),
    Cand("SZA", "Snooze", "rnb", "guitar-led modern R&B love song (2023)"),
    Cand("Giveon", "Heartbreak Anniversary", "rnb", "soulful slow R&B heartbreak ballad"),
    Cand("Chris Brown", "Under The Influence", "rnb", "slow seductive synth R&B (viral 2022)"),
    Cand("Steve Lacy", "Bad Habit", "rnb", "alt-R&B guitar groove"),
    Cand("Joji", "Slow Dancing In The Dark", "rnb", "alt-R&B slow ballad, emotional, lo-fi texture"),
    # --- afro -------------------------------------------------------------------
    Cand("CKay", "love nwantiti (ah ah ah)", "afro", "afro-R&B acoustic-guitar love song - closest afro-love vibe to Reine",
         via="both", q=("love nwantiti instrumental", "ckay love nwantiti instrumental"),
         scq="ckay love nwantiti instrumental"),
    Cand("CKay", "love nwantiti (ah ah ah)", "afro", "acoustic-guitar instrumental of the afro-love hit: campfire take on the Reine vibe",
         variant="acoustic", q=("love nwantiti acoustic instrumental", "love nwantiti guitar instrumental")),
    Cand("Rema", "Calm Down", "afro", "afro-pop love song, guitar + log drum, ~107 bpm", via="both",
         alt=("Selena Gomez",)),
    Cand("Wizkid", "Essence", "afro", "smooth mid-tempo afro-R&B love groove", via="both", alt=("Tems", "WizKid")),
    Cand("Burna Boy", "Last Last", "afro", "afro-fusion breakup song (Toni Braxton sample)", via="both"),
    Cand("Omah Lay", "soso", "afro", "melancholic afro-R&B", via="both"),
    Cand("Fireboy DML", "Peru", "afro", "afro-pop guitar groove", alt=("Ed Sheeran",)),
    Cand("Tems", "Free Mind", "afro", "alte afro-R&B, slow and moody", via="both"),
    Cand("Ayra Starr", "Rush", "afro", "afro-pop with an emotional melody"),
    Cand("Davido", "FALL", "afro", "afropop love classic", via="both"),
    Cand("Libianca", "People", "afro", "afro-soul ballad about loneliness", alt=("Cian Ducrot", "Ayra Starr", "Omah Lay")),
    Cand("Joeboy", "Baby", "afro", "afro-pop love song with sweet guitar", via="both"),
    Cand("Tyla", "Water", "amapiano", "amapiano-pop love groove"),
    Cand("Burna Boy", "For My Hand", "afro", "Burna Boy x Ed Sheeran afro-pop love song, guitar-led", alt=("Ed Sheeran",)),
    Cand("Burna Boy", "It's Plenty", "afro", "mellow afro-fusion mid-tempo groove"),
    Cand("Omah Lay", "Woman", "afro", "soft afro-R&B love song"),
    Cand("CKay", "emiliana", "afro", "afro-R&B love song from the love nwantiti singer"),
    Cand("Wizkid", "True Love", "afro", "afro-R&B love song (with Tay Iwar & Projexx)", alt=("WizKid", "Tay Iwar", "Projexx")),
    Cand("Wizkid", "MOOD", "afro", "mellow afro-R&B with Buju, guitar licks", alt=("WizKid", "Buju", "BNXN")),
    Cand("Asake", "Lonely At The Top", "amapiano", "amapiano-afrobeats with a sad melody"),
    # --- French R&B / pop urbaine -------------------------------------------------
    Cand("Dadju", "Jaloux", "french", "Dadju's own afro-R&B love song - same artist / production world as Reine", via="both",
         q=("jaloux dadju instrumental", "jaloux instrumental", "jaloux instru"), scq="dadju jaloux instrumental"),
    Cand("Dadju", "Bob Marley", "french", "Dadju afro-pop love song", via="both",
         q=("dadju bob marley instrumental", "bob marley dadju instru")),
    Cand("Dadju", "Mon Soleil", "french", "Dadju x Anitta sunny afro-pop love song - same singer as Reine",
         alt=("Anitta",), via="both"),
    Cand("Dadju", "Grand bain", "french", "Dadju pop urbaine mid-tempo", alt=("Ninho",), via="both",
         q=("grand bain instrumental", "dadju grand bain instru")),
    Cand("Tayc", "N'y pense plus", "french", "French afro-love with soft guitar (Tayc)", via="both",
         aliases=("NypensePlus",), scq="tayc n'y pense plus instrumental karaoke",
         q=("n'y pense plus instrumental", "tayc n'y pense plus instru")),
    Cand("Tayc", "Le temps", "french", "French R&B ballad", via="both",
         q=("tayc le temps instrumental", "le temps tayc instru")),
    Cand("GIMS", "Est-ce que tu m'aimes ?", "french", "guitar-led pop-urbaine love ballad", alt=("Maître Gims",),
         q=("est-ce que tu m'aimes instrumental", "gims est ce que tu m'aimes instru")),
    Cand("Aya Nakamura", "Pookie", "french", "afro-pop urbaine groove", via="both",
         q=("pookie instrumental", "aya nakamura pookie instru")),
    Cand("Aya Nakamura", "Plus Jamais", "french", "Aya x Stormzy afro-R&B breakup song, mid-tempo", alt=("Stormzy",),
         via="both"),
    Cand("Aya Nakamura", "Copines", "french", "Aya Nakamura afro-pop hit, love/jealousy theme like Reine's world", via="sc"),
    Cand("Dadju", "Par amour", "french", "Dadju R&B love ballad - same voice / label world as Reine", via="sc"),
    Cand("Dadju", "Compliqué", "french", "Dadju afro-pop heartbreak song, mid-tempo", via="sc"),
    Cand("GIMS", "Tu ne le vois pas", "french", "GIMS x Dadju (brothers) guitar pop-urbaine love song", via="sc",
         alt=("Maître Gims", "Dadju")),
    Cand("MHD", "Bébé", "french", "MHD x Dadju afro-trap love song", via="sc", alt=("Dadju",)),
    Cand("Joé Dwèt Filé", "4 Kampé", "french", "kompa love groove, Caribbean-French", alt=("Burna Boy",),
         q=("4 kampé instrumental", "4 kampe instru")),
    # --- pop-punk / alt-rock / acoustic ----------------------------------------------
    Cand("blink-182", "I Miss You", "poppunk", "acoustic emo pop-punk, a direct Juice WRLD influence", via="both"),
    Cand("Green Day", "Boulevard of Broken Dreams", "poppunk", "melancholic alt-rock power ballad"),
    Cand("Paramore", "The Only Exception", "acoustic", "acoustic-guitar love ballad"),
    Cand("Machine Gun Kelly", "bloody valentine", "poppunk", "2020 pop-punk revival guitar love song"),
    Cand("Sting", "Shape Of My Heart", "acoustic", "the nylon-guitar riff Lucid Dreams sampled (original recording, sparse vocal)",
         variant="original", instr=False),
    # --- lo-fi / piano / cinematic / boom-bap / drill ------------------------------------
    Cand("Nujabes", "Aruarian Dance", "lofi", "lo-fi hip-hop classic, jazzy loop (natively instrumental)",
         variant="original", instr=True),
    Cand("Central Cee", "Sprinter", "drill", "melodic drill over a guitar loop", alt=("Dave",)),
    Cand("Kanye West", "Runaway", "piano", "iconic piano-led cinematic hip-hop ballad", alt=("Pusha T", "Ye")),
    Cand("J. Cole", "Love Yourz", "boombap", "soulful piano boom-bap, reflective", via="both"),
    Cand("Mac Miller", "Good News", "lofi", "soft melancholy guitar/bass groove"),
    Cand("Lewis Capaldi", "Someone You Loved", "piano", "piano heartbreak ballad with a huge melodic hook"),
    # --- calibration control (is_reference=true): the ORIGINAL Reine beat --------------
    Cand("Dadju", "Reine", "control", "the original Reine instrumental: upper bound for tempo/key fit scores (not a NEW beat)",
         via="both", as_ref=True, q=("dadju reine instrumental", "reine dadju instru"), scq="dadju instrumental",
         allow=("remix",)),
]

# Titles distinctive enough that a remake need not name the original artist
# (everything else, e.g. "Changes", "Water", "Baby", must be confirmed by the
# artist's name in the remake's title / album / artist field).
DISTINCT_TITLES = {
    "Lucid Dreams", "All Girls Are The Same", "Wishing Well", "Hear Me Calling", "Lean Wit Me",
    "Jocelyn Flores", "Star Shopping", "Awful Things", "Benz Truck", "Love Scars", "Taking A Walk",
    "XO TOUR Llif3", "RAPSTAR", "Calling My Phone", "Heart On Ice", "Pursuit Of Happiness",
    "Call Out My Name", "Hold On, We're Going Home", "Thinkin Bout You", "Heartbreak Anniversary",
    "Slow Dancing In The Dark", "PRBLMS", "love nwantiti (ah ah ah)", "Last Last", "N'y pense plus",
    "Est-ce que tu m'aimes ?", "4 Kampé", "Boulevard of Broken Dreams", "The Only Exception",
    "Someone You Loved", "Love Yourz",
}
for _c in CANDIDATES:
    _c.distinct = _c.distinct or norm(_c.title) in {norm(t) for t in DISTINCT_TITLES}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


APOS = str.maketrans({"\u2019": "'", "\u2018": "'", "\u00b4": "'", "`": "'"})


def core(title: str) -> str:
    """Normalized song title without (feat ...), [tags] and ' - suffix' parts."""
    t = re.sub(r"(?i)f\*+ck", "fuck", (title or "").translate(APOS))
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)
    t = re.sub(r"\s[-–]\s.*$", " ", t)
    t = re.sub(r"\b(feat|ft|featuring)\b\.?.*$", " ", t, flags=re.I)
    return norm(t)


def nrm(text: str) -> str:
    """norm() that also maps f*ck -> fuck (censored titles)."""
    return norm(re.sub(r"(?i)f\*+ck", "fuck", (text or "").translate(APOS)))


def contains_words(hay: str, needle: str) -> bool:
    """Whole-word containment on normalized strings."""
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay) is not None


def without(hay: str, needle: str) -> str:
    """Normalized `hay` with the (first) normalized `needle` removed."""
    return re.sub(rf"(?<!\w){re.escape(needle)}(?!\w)", " ", hay, count=1) if needle else hay


# Words that may surround the song name in a remake's title without making it
# a different song ("<Artist> - <Song> (Instrumental) [Reprod. by X]").
NOISE_WORDS = set(
    "instrumental instrumentale instru inst version karaoke remake official reprod re prod prod "
    "produced by originally performed made popular famous in the style of tribute beat beats "
    "free dl download hq cdq original feat ft x and with music audio playback backing track "
    "vrs".split())
SEG_SPLIT = re.compile(r"\s*[-\u2013\u2014_|/:]\s+|\s+[-\u2013\u2014_|/:]\s*|\s*[\"\u201c\u201d]\s*")


def strip_noise(words: str, extra: tuple = ()) -> str:
    return " ".join(w for w in words.split() if w not in NOISE_WORDS and w not in extra)


def match_want(title: str, wants: list[str], toks: list[str], extra: tuple = ()) -> str | None:
    """The matching song-name spelling for `title`, or None (see title_matches)."""
    nt = nrm(title)
    for w in wants:
        if (contains_words(nt, w) or contains_words(nt.replace(" ", ""), w.replace(" ", ""))) \
                and title_matches(title, w, toks, extra):
            return w
    return None


def title_matches(title: str, want: str, toks: list[str], extra: tuple = ()) -> bool:
    """True when some ' - ' / '|' segment of `title` (brackets removed) is exactly the
    song name once artist names and noise words are dropped.  Rejects other songs
    that merely contain the name ("Empty Out Your Pockets", "Love Scars 3")."""
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]?", " ", (title or "").translate(APOS))
    t = re.sub(r"(?i)f\*+ck", "fuck", t)
    target = strip_noise(want, extra)
    for seg in SEG_SPLIT.split(t):
        n = norm(seg)
        for a in sorted(toks, key=len, reverse=True):
            n = without(n, a) if a and a != want else n
        got = strip_noise(n, extra)
        if target and (got == target or got.replace(" ", "") == target.replace(" ", "")):
            return True
    return False


def strip_allow(text: str, allow: tuple) -> str:
    return " ".join(x for x in text.split() if x not in allow)


def artist_ok(name: str, wanted: list[str]) -> bool:
    n = norm(name)
    return any(n == w or (len(w) >= 4 and n.startswith(w + " ")) for w in wanted)


def artist_tokens(c: "Cand") -> list[str]:
    """Normalized original-artist names used to confirm that a remake is OF this song."""
    return [re.sub(r"^the ", "", norm(a)) for a in (c.artist, *c.alt) if norm(a)]


def names_artist(text: str, toks: list[str]) -> bool:
    n = norm(text)
    return any(contains_words(n, t) for t in toks)


def load_jsonl(path: str) -> list[dict]:
    return hdz.load_jsonl(path)


def item_key_of(rec: dict) -> str | None:
    return next((t[5:] for t in rec.get("tags", []) if t.startswith("item:")), None)


def other_source_ids() -> set[str]:
    """Native ids already harvested by the generic Deezer / SoundCloud sources."""
    ids = set()
    for src in OTHER_SOURCES:
        for r in load_jsonl(os.path.join(ROOT, "work", "catalog", src, "candidates.jsonl")):
            ids.add(r["id"])
    return ids


class NoMatch(Exception):
    """Permanent: nothing on the platform matches the curated item."""


class Transient(Exception):
    """Network-ish failure: retry on a later run."""


# --------------------------------------------------------------------------
# Deezer resolution
# --------------------------------------------------------------------------
class DzResolver:
    def __init__(self, rps: float):
        self.dz = hdz.Deezer(DZ_CACHE, rps)
        self.lock = threading.Lock()
        self.claimed: set[int] = set()   # Deezer ids already used by another item this run

    def search(self, q: str, limit: int = 50) -> list[dict]:
        d = self.dz.get("/search", {"q": q, "limit": limit})
        if d is None:
            # cached "no data" or failure -> treat as empty (search errors are rare)
            return []
        return d.get("data") or []

    def find_original(self, artist: str, title: str, alt: tuple = (), extra_q: str = "") -> dict | None:
        """Best-ranked Deezer track of the original song (no remix / live / instr. versions).
        Preference: exact title > prefix match, primary artist > featured/alt, then rank."""
        wanted = [norm(a) for a in (artist, *alt)]
        want = core(title)
        bad_ok = bool(ORIG_BAD.search(title))  # e.g. "(I Wonder Why Freestyle)" is fine anyway
        best, best_s = None, None
        queries = ([extra_q] if extra_q else []) + [f"{artist} {title}", f"{core(title)} {artist}", title]
        for q in queries:
            for t in self.search(q):
                if not t.get("readable", True) or not t.get("preview"):
                    continue
                if not artist_ok((t.get("artist") or {}).get("name", ""), wanted):
                    continue
                rt = t.get("title") or ""
                rt_chk = ORIG_OK.sub(" ", rt + " " + (t.get("title_version") or ""))
                if not bad_ok and ORIG_BAD.search(rt_chk):
                    continue
                ct = core(rt)
                if ct == want:
                    m = 2
                elif len(want) >= 4 and (ct.startswith(want) or want.startswith(ct)) and len(ct) >= 3:
                    m = 1
                else:
                    continue
                primary = artist_ok((t.get("artist") or {}).get("name", ""), [norm(artist)])
                s = (m, primary, t.get("rank") or 0)
                if best_s is None or s > best_s:
                    best, best_s = t, s
            if best is not None and best_s[0] == 2 and best_s[1]:
                break                                   # exact title by the primary artist
        return best

    def instrumental_picks(self, c: Cand, orig: dict | None) -> list[tuple[float, dict, str]]:
        """Ranked (score, track, query) list of instrumental versions of a curated song.

        A remake must name the original artist somewhere (title / album / artist
        field) unless the curated title is marked distinct=True, because generic
        titles ("Changes", "Water", "Baby") collide with other songs."""
        want = core(c.title)
        wants = c.wants()
        if c.q:
            qs = list(c.q)
        elif c.variant == "acoustic":
            qs = [f"{c.artist} {want} acoustic instrumental", f"{want} acoustic instrumental"]
        else:
            qs = [f"{c.artist} {want} instrumental"] + ([f"{want} instrumental"] if c.distinct else [])
        wanted_artists = [norm(a) for a in (c.artist, *c.alt)]
        toks = artist_tokens(c)
        orig_dur = (orig or {}).get("duration") or 0
        bad_re = VARIANT_BAD_ACOUSTIC if c.variant == "acoustic" else VARIANT_BAD
        pool: dict[int, tuple[dict, str]] = {}
        for q in qs:
            for t in self.search(q):
                pool.setdefault(t["id"], (t, q))
        out = []
        for t, q in pool.values():
            if orig and t["id"] == orig["id"]:
                continue
            title = t.get("title") or ""
            artist = (t.get("artist") or {}).get("name") or ""
            album = (t.get("album") or {}).get("title") or ""
            if not t.get("readable", True) or not t.get("preview"):
                continue
            nt = nrm(title)
            if not INSTR_KW.search(title):
                continue
            w = match_want(title, wants, toks, c.allow)
            if w is None:
                continue
            rest = strip_allow(without(nt, w), c.allow)     # title minus the song name
            if bad_re.search(rest):
                continue
            if c.variant == "acoustic" and not re.search(r"acoustic|guitar", rest):
                continue
            if ARTIST_BAD.search(artist) or (c.variant != "acoustic" and ARTIST_BAD.search(without(nrm(album), want))):
                continue
            confirmed = names_artist(f"{title} {album} {artist}", toks)
            if not confirmed and not c.distinct:
                continue
            dur = t.get("duration") or 0
            if dur < 75:
                continue
            ratio = dur / orig_dur if orig_dur else 1.0
            if not (DUR_RATIO[0] <= ratio <= DUR_RATIO[1]):
                continue
            s = math.log10((t.get("rank") or 0) + 10)
            if artist_ok(artist, wanted_artists):
                s += 4.0                                  # official instrumental
            s += 1.5 if confirmed else -0.8
            if re.search(r"instrumental|instru", title, re.I):
                s += 1.0
            if re.search(r"karaoke", title + " " + album, re.I):
                s -= 1.5                                  # may carry guide melody / backing vox
            elif re.search(r"originally (performed|by)|in the style of|made (famous|popular)|tribute", title, re.I):
                s -= 0.3
            if re.search(r"remake|reprod|official", title, re.I):
                s += 0.5
            s -= 2.0 * abs(math.log(ratio))
            out.append((round(s, 3), t, q))
        out.sort(key=lambda x: -x[0])
        return out

    def track(self, tid: int) -> dict | None:
        return self.dz.get(f"/track/{tid}", cache=False)

    def claim(self, tid: int) -> bool:
        with self.lock:
            if tid in self.claimed:
                return False
            self.claimed.add(tid)
            return True


def dz_record(res: DzResolver, t_stub: dict, *, is_ref: bool, query: str, tags: list[str],
              instr, others: set[str]) -> dict:
    """Fetch details, download the 30 s preview, build the contract record."""
    tid = int(t_stub["id"])
    t = res.track(tid)
    if not t:
        raise Transient("no track detail")
    if not t.get("readable") or not t.get("preview"):
        raise NoMatch("no preview")
    clip = os.path.join(CLIP_DIR, f"{SOURCE}_deezer-{tid}.mp3")
    cdur = hdz.ffprobe_duration(clip) if os.path.exists(clip) else None
    if cdur is None or cdur < MIN_CLIP:
        cdur = hdz.download_clip(t["preview"], clip)
        if cdur is None:
            time.sleep(1.0)
            t2 = res.track(tid) or {}
            if t2.get("preview"):
                cdur = hdz.download_clip(t2["preview"], clip)
        if cdur is None:
            raise Transient("preview download failed")
    album = t.get("album") or {}
    genres = res.dz.album_genres(album.get("id"))
    bpm = t.get("bpm")
    try:
        bpm = round(float(bpm), 2) if bpm and float(bpm) > 0 else None
    except (TypeError, ValueError):
        bpm = None
    main = (t.get("artist") or {}).get("name") or ""
    feats = [c.get("name") for c in (t.get("contributors") or []) if c.get("name") and c.get("name") != main]
    artist = main + (" feat. " + ", ".join(feats[:3]) if feats else "")
    tags = list(tags) + [f"genre:{g}" for g in genres] + ["platform:deezer", "deezer_preview_30s"]
    if (t.get("release_date") or "")[:4].isdigit():
        tags.append(f"year:{t['release_date'][:4]}")
    if t.get("explicit_lyrics"):
        tags.append("explicit")
    if f"deezer:{tid}" in others:
        tags.append(f"also_in:deezer:{tid}")
    return {
        "id": f"{SOURCE}:deezer-{tid}",
        "source": SOURCE,
        "title": t.get("title") or t_stub.get("title") or "",
        "artist": artist,
        "page_url": t.get("link") or f"https://www.deezer.com/track/{tid}",
        "clip_path": clip,
        "clip_start_s": None,                 # 30 s preview kept as-is (offset unknown)
        "duration_full_s": t.get("duration") or None,
        "license": DZ_LICENSE,
        "full_audio_url": None,
        "full_audio_available": False,
        "bpm_meta": bpm,
        "key_meta": None,
        "tags": tags,
        "is_instrumental_meta": instr,
        "query": query,
        "is_reference": bool(is_ref),
    }


# --------------------------------------------------------------------------
# SoundCloud resolution
# --------------------------------------------------------------------------
_SC_EXTRA = (r"|\blyrics?\b|\breact|\bdj\b|\bvip\b|\bv2\b|\bversion 2\b|\bflp\b|"
             r"tutorial|how to|\bcdq\b|\bwith hook\b|\bhook\b|\bchorus\b|\bvocals?\b|\bacapella\b")
SC_BAD = re.compile(VARIANT_BAD.pattern + _SC_EXTRA, re.I)
SC_BAD_ACOUSTIC = re.compile(VARIANT_BAD_ACOUSTIC.pattern + _SC_EXTRA, re.I)


def sc_picks(c: Cand, orig_dur: float) -> tuple[list[tuple[float, dict]], str]:
    """Ranked (score, entry) SoundCloud uploads of the song's instrumental."""
    want = core(c.title)
    wants = c.wants()
    q = c.scq or f"{c.artist} {want} instrumental"
    entries = hsc.search(q, SC_PER_QUERY)
    toks = artist_tokens(c)
    out = []
    for e in entries:
        title = e.get("title") or ""
        nt = nrm(title)
        w = match_want(title, wants, toks, c.allow)
        if w is None or not SC_INSTR_KW.search(title):
            continue
        rest = strip_allow(without(nt, w), c.allow)
        bad_re = SC_BAD_ACOUSTIC if c.variant == "acoustic" else SC_BAD
        if bad_re.search(rest) or SC_MASHUP.search(title) or title.count(" - ") >= 2:
            continue
        if c.variant == "acoustic" and not re.search(r"acoustic|guitar", rest):
            continue
        if ARTIST_BAD.search(e.get("uploader") or ""):
            continue
        confirmed = names_artist(f"{title} {e.get('uploader') or ''}", toks)
        if not confirmed and not c.distinct:
            continue
        dur = float(e.get("duration") or 0)
        if not (hsc.MIN_FULL_DURATION <= dur <= hsc.MAX_FULL_DURATION):
            continue
        ratio = dur / orig_dur if orig_dur else 1.0
        if not (DUR_RATIO[0] <= ratio <= DUR_RATIO[1]):
            continue
        if norm(e.get("uploader")) == norm(c.artist) and not INSTR_KW.search(title):
            continue                                       # the artist's own vocal upload
        s = math.log10((e.get("view_count") or 0) + 10)
        s += 1.0 if confirmed else -0.5
        if re.search(r"official", title, re.I):
            s += 0.7
        if re.search(r"remake|reprod", title, re.I):
            s += 0.2
        s -= 2.0 * abs(math.log(ratio))
        out.append((round(s, 3), e))
    out.sort(key=lambda x: -x[0])
    return out, q


def sc_record(c: Cand, e: dict, limiter, *, query: str, tags: list[str], others: set[str]) -> dict:
    tid = str(e["id"])
    dest = os.path.join(CLIP_DIR, f"{SOURCE}_soundcloud-{tid}.mp3")
    info = hsc.resolve(e, limiter)
    fmt = hsc.pick_format(info.get("formats") or [])
    if not fmt:
        raise NoMatch("no playable formats")
    preview = "preview" in (fmt.get("format_id") or "")
    full_dur = float(info.get("duration") or e.get("duration") or 0)
    hsc._rm(dest)
    try:
        start = hsc.fetch_clip(fmt, full_dur, preview, dest)
    except Exception:
        hsc._rm(dest)
        raise
    d = hdz.ffprobe_duration(dest)
    if d is None or d < MIN_CLIP:
        hsc._rm(dest)
        raise Transient(f"clip invalid ({d})")
    title = info.get("title") or e.get("title") or ""
    sc_tags = [str(t).strip().lower() for t in (info.get("tags") or e.get("tags") or []) if str(t).strip()]
    genres = [str(g).strip() for g in (info.get("genres") or e.get("genres") or []) if str(g).strip()]
    bpm, bpm_src, key, key_src = hsc.parse_meta(title, sc_tags, info.get("description") or e.get("description") or "")
    tags = list(tags) + [f"genre:{g}" for g in genres] + sc_tags[:10] + ["platform:soundcloud"]
    if bpm is not None:
        tags.append(f"bpm_src:{bpm_src}")
    if key is not None:
        tags.append(f"key_src:{key_src}")
    plays = info.get("view_count") if info.get("view_count") is not None else e.get("view_count")
    if plays is not None:
        tags.append(f"plays:{plays}")
    ts = info.get("timestamp") or e.get("timestamp")
    if ts:
        tags.append("year:" + time.strftime("%Y", time.gmtime(ts)))
    tags.append(f"fmt:{fmt.get('format_id')}")
    tags.append("sc:preview_only" if preview else "full:resolve_page_url_with_yt-dlp")
    if f"soundcloud:{tid}" in others:
        tags.append(f"also_in:soundcloud:{tid}")
    lic = info.get("license") or e.get("license")
    return {
        "id": f"{SOURCE}:soundcloud-{tid}",
        "source": SOURCE,
        "title": title,
        "artist": info.get("uploader") or e.get("uploader") or "",
        "page_url": info.get("webpage_url") or e.get("webpage_url"),
        "clip_path": dest,
        "clip_start_s": start,
        "duration_full_s": round(full_dur, 3) if full_dur else None,
        "license": lic,
        "full_audio_url": None,            # signed stream URLs expire; re-resolve page_url with yt-dlp
        "full_audio_available": not preview,
        "bpm_meta": bpm,
        "key_meta": key,
        "tags": tags,
        "is_instrumental_meta": True,
        "query": query,
        "is_reference": bool(c.as_ref),
    }


# --------------------------------------------------------------------------
# Item workers
# --------------------------------------------------------------------------
def orig_tags(orig: dict | None) -> list[str]:
    if not orig:
        return []
    out = [f"orig_deezer_id:{orig['id']}"]
    if orig.get("duration"):
        out.append(f"orig_dur:{orig['duration']}")
    return out


def do_ref(r: Ref, res: DzResolver, others: set[str], dry: bool) -> dict | str:
    t = res.dz.get(f"/track/{r.dz_id}") if r.dz_id else res.find_original(r.artist, r.title, r.alt, r.q)
    if not t:
        raise NoMatch("original not found on Deezer")
    q = f"curated_ref:deezer_search:{r.artist} {r.title}"
    if dry:
        return f"{t['id']} | {t['title']} | {t['artist']['name']} | {t.get('duration')}s"
    tags = [f"item:{r.key}", "reference", "curated", f"cat:reference", f"ref_group:{r.group}",
            f"rationale: {r.note}"]
    return dz_record(res, t, is_ref=True, query=q, tags=tags, instr=False, others=others)


def do_cand_dz(c: Cand, res: DzResolver, others: set[str], dry: bool) -> dict | str:
    orig = res.find_original(c.artist, c.title, c.alt)
    base = [f"item:{c.key('dz')}", "curated", f"cat:{c.cat}", f"rationale: {c.why}",
            f"orig:{c.artist} - {c.title}", f"variant:{c.variant}"] + orig_tags(orig)
    if c.as_ref:
        base += ["reference", "ref_group:control", "control:original_beat"]
    if hdz.is_juice(c.artist):
        base.append("juice_own_beat")
    if c.variant == "original":
        if not orig:
            raise NoMatch("original not found on Deezer")
        if dry:
            return f"[original] {orig['id']} | {orig['title']} | {orig['artist']['name']}"
        q = f"curated:deezer_search:{c.artist} {c.title}"
        return dz_record(res, orig, is_ref=c.as_ref, query=q, tags=base + ["pick:original"],
                         instr=c.instr, others=others)
    picks = res.instrumental_picks(c, orig)
    if not picks:
        raise NoMatch("no instrumental version on Deezer")
    if dry:
        o = f"orig={orig['id']} {orig.get('duration')}s" if orig else "orig=?"
        return f"{o} -> " + " || ".join(
            f"{s:.2f} {t['id']} {t['title']} / {t['artist']['name']} ({t['duration']}s)" for s, t, _ in picks[:3])
    last = None
    for s, t, q in picks[:4]:
        if not res.claim(int(t["id"])):
            continue
        artist = (t.get("artist") or {}).get("name") or ""
        kind = ("official" if artist_ok(artist, [norm(a) for a in (c.artist, *c.alt)])
                else "karaoke" if re.search(r"karaoke", t.get("title") or "", re.I) else "remake")
        try:
            return dz_record(res, t, is_ref=c.as_ref, query=f"curated:deezer_search:{q}",
                             tags=base + [f"pick:{kind}", f"pick_score:{s}"], instr=True, others=others)
        except NoMatch as ex:
            last = ex
            continue
    raise last or NoMatch("all picks failed")


def do_cand_sc(c: Cand, res: DzResolver, limiter, others: set[str], dry: bool) -> dict | str:
    orig = res.find_original(c.artist, c.title, c.alt)
    orig_dur = float((orig or {}).get("duration") or 0)
    picks, q = sc_picks(c, orig_dur)
    if not picks:
        raise NoMatch("no instrumental upload on SoundCloud")
    if dry:
        return " || ".join(f"{s:.2f} {e['id']} {e['title'][:60]} / {e['uploader'][:20]} ({e['duration']:.0f}s)"
                           for s, e in picks[:3])
    base = [f"item:{c.key('sc')}", "curated", f"cat:{c.cat}", f"rationale: {c.why}",
            f"orig:{c.artist} - {c.title}", f"variant:{c.variant}"] + orig_tags(orig)
    if c.as_ref:
        base += ["reference", "ref_group:control", "control:original_beat"]
    if hdz.is_juice(c.artist):
        base.append("juice_own_beat")
    preview_rec = None
    last = None
    for s, e in picks[:4]:
        try:
            rec = sc_record(c, e, limiter, query=f"curated:scsearch{SC_PER_QUERY}:{q}",
                            tags=base + [f"pick_score:{s}"], others=others)
        except hsc.PermanentError as ex:
            last = NoMatch(str(ex)[:200])
            continue
        if rec["full_audio_available"]:
            if preview_rec:
                hsc._rm(preview_rec["clip_path"])
            return rec
        if preview_rec is None:
            preview_rec = rec                 # keep as fallback, try to find a full stream
        else:
            hsc._rm(rec["clip_path"])
    if preview_rec:
        return preview_rec
    raise last or NoMatch("all SoundCloud picks failed")


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def print_stats() -> None:
    recs = load_jsonl(JSONL)
    rej = load_jsonl(REJECTS)
    refs = [r for r in recs if r["is_reference"]]
    cands = [r for r in recs if not r["is_reference"]]
    print(f"records: {len(recs)}  references: {len(refs)}  candidates: {len(cands)}  rejects: {len(rej)}")
    grp = Counter(next((t[10:] for t in r["tags"] if t.startswith("ref_group:")), "?") for r in refs)
    print("references by group:", dict(grp.most_common()))
    cats = Counter(next((t[4:] for t in r["tags"] if t.startswith("cat:")), "?") for r in cands)
    print("candidates by cat:", dict(cats.most_common()))
    print("candidates by platform:", dict(Counter(
        next((t[9:] for t in r["tags"] if t.startswith("platform:")), "?") for r in cands)))
    print("pick kinds:", dict(Counter(next((t[5:] for t in r["tags"] if t.startswith("pick:")), "sc")
                                      for r in cands)))
    print("full_audio_available:", sum(r["full_audio_available"] for r in recs),
          " instrumental_meta:", dict(Counter(str(r["is_instrumental_meta"]) for r in recs)))
    print("bpm_meta present:", sum(r["bpm_meta"] is not None for r in recs),
          " key_meta present:", sum(r["key_meta"] is not None for r in recs))
    print("reject reasons:", dict(Counter(r.get("reason", "?")[:50] for r in rej).most_common()))
    for r in rej:
        print("   reject:", r.get("key"), "->", r.get("reason"))
    size = sum(os.path.getsize(r["clip_path"]) for r in recs if os.path.exists(r["clip_path"]))
    missing = sum(not os.path.exists(r["clip_path"]) for r in recs)
    print(f"clip bytes: {size / 1e6:.1f} MB   missing clips: {missing}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def build_jobs(only: str | None) -> list[tuple[str, str, object]]:
    jobs = []
    if only in (None, "refs"):
        jobs += [(r.key, "ref", r) for r in REFERENCES]
    if only in (None, "candidates"):
        for c in CANDIDATES:
            if c.via in ("dz", "both"):
                jobs.append((c.key("dz"), "dz", c))
        for c in CANDIDATES:                     # SoundCloud after Deezer (slower)
            if c.via in ("sc", "both"):
                jobs.append((c.key("sc"), "sc", c))
    seen, out = set(), []
    for j in jobs:
        if j[0] not in seen:
            seen.add(j[0])
            out.append(j)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", type=int, default=200, help="stop once this many records exist")
    ap.add_argument("--max-seconds", type=float, default=500, help="stop submitting work after this")
    ap.add_argument("--workers", type=int, default=8, help="parallel items (<= 8)")
    ap.add_argument("--rps", type=float, default=6.0, help="Deezer API requests/s (limit 10)")
    ap.add_argument("--sc-rps", type=float, default=1.0, help="SoundCloud resolutions/s")
    ap.add_argument("--only", choices=["refs", "candidates"], help="harvest one part only")
    ap.add_argument("--dry-run", action="store_true", help="resolve picks and print them, no downloads")
    ap.add_argument("--retry-rejects", action="store_true", help="also retry items in rejects.jsonl")
    ap.add_argument("--stats", action="store_true", help="only print stats of the output")
    args = ap.parse_args()

    if args.stats:
        print_stats()
        return 0
    try:
        os.nice(5)
    except OSError:
        pass
    t0 = time.time()
    for d in (OUT_DIR, CLIP_DIR, TMP_DIR, SC_SEARCH_DIR):
        os.makedirs(d, exist_ok=True)
    for f in os.listdir(CLIP_DIR):                 # leftovers of killed ffmpeg runs
        if f.endswith(".part.mp3"):
            os.remove(os.path.join(CLIP_DIR, f))

    done = load_jsonl(JSONL)
    done_keys = {item_key_of(r) for r in done}
    rejects = load_jsonl(REJECTS)
    rej_keys = set() if args.retry_rejects else {r["key"] for r in rejects}
    jobs = [j for j in build_jobs(args.only) if j[0] not in done_keys and j[0] not in rej_keys]
    if args.retry_rejects and not args.dry_run:
        # drop the retried items' old reject lines (they are re-recorded if they fail again)
        retry = {j[0] for j in jobs}
        keep = [r for r in rejects if r["key"] not in retry]
        with open(REJECTS + ".tmp", "w", encoding="utf-8") as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(REJECTS + ".tmp", REJECTS)
    log(f"done {len(done)} records, {len(rej_keys)} rejected items, {len(jobs)} items to process")
    if not jobs:
        print_stats()
        return 0

    res = DzResolver(min(args.rps, 9.0))
    # Deezer ids already used by finished records must not be re-picked.
    for r in done:
        if r["id"].startswith(f"{SOURCE}:deezer-") and not r["is_reference"]:
            res.claimed.add(int(r["id"].split("-", 1)[1]))
    limiter = hsc.RateLimiter(max_calls=max(1, int(args.sc_rps * 5)), period=5.0)
    others = other_source_ids()
    done_ids = {r["id"] for r in done}

    def run(job):
        key, kind, item = job
        if kind == "ref":
            return do_ref(item, res, others, args.dry_run)
        if kind == "dz":
            return do_cand_dz(item, res, others, args.dry_run)
        return do_cand_sc(item, res, limiter, others, args.dry_run)

    stats = Counter()
    n_rec = len(done)
    it = iter(jobs)
    inflight = {}
    workers = max(1, min(8, args.workers))
    with open(JSONL, "a", encoding="utf-8") as out, open(REJECTS, "a", encoding="utf-8") as rej, \
            ThreadPoolExecutor(max_workers=workers) as pool:
        def submit_more():
            while (len(inflight) < workers and time.time() - t0 < args.max_seconds
                   and (args.dry_run or n_rec + len(inflight) < args.target)):
                j = next(it, None)
                if j is None:
                    return
                inflight[pool.submit(run, j)] = j

        submit_more()
        while inflight:
            fin, _ = wait(list(inflight), timeout=60, return_when=FIRST_COMPLETED)
            for f in fin:
                key, kind, item = inflight.pop(f)
                try:
                    payload = f.result()
                except NoMatch as ex:
                    stats["no_match"] += 1
                    log(f"  no match [{kind}] {key}: {ex}")
                    if not args.dry_run:
                        rej.write(json.dumps({"key": key, "reason": str(ex), "t": int(time.time())},
                                             ensure_ascii=False) + "\n")
                        rej.flush()
                    continue
                except Exception as ex:          # Transient + unexpected: retry next run
                    stats["transient"] += 1
                    log(f"  transient [{kind}] {key}: {type(ex).__name__}: {str(ex)[:160]}")
                    continue
                if args.dry_run:
                    print(f"[{kind}] {key}\n      {payload}", flush=True)
                    stats["resolved"] += 1
                    continue
                if payload["id"] in done_ids:     # same track reached via two items: keep one
                    stats["dup_track"] += 1
                    log(f"  duplicate track {payload['id']} for {key}; skipped")
                    rej.write(json.dumps({"key": key, "reason": f"duplicate of {payload['id']}",
                                          "t": int(time.time())}) + "\n")
                    rej.flush()
                    continue
                done_ids.add(payload["id"])
                out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                out.flush()
                n_rec += 1
                stats[f"ok_{kind}"] += 1
                if sum(stats.values()) % 20 == 0:
                    log(f"  progress {dict(stats)} records={n_rec} dz_api={res.dz.n_requests}")
            submit_more()

    shutil.rmtree(TMP_DIR, ignore_errors=True)
    left = len(jobs) - sum(stats.values())
    log(f"run finished in {time.time() - t0:.0f}s: {dict(stats)}; records={n_rec}; "
        f"items not attempted this run={left}; deezer api requests={res.dz.n_requests}")
    if not args.dry_run:
        print_stats()
    return 0


if __name__ == "__main__":
    sys.exit(main())
