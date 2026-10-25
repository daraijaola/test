#!/usr/bin/env python3
"""Write the export manifest: Extended Cuts first, then the remixes in final-ranking order.

Usage: make_manifest.py OUT.json REMIX_KEY [REMIX_KEY ...]   (winner first)
"""
import json
import sys

ALBUM = "Campfire (Reine Freestyle) - Fan Edits"
BASE = "Juice WRLD - Campfire (Reine Freestyle)"
EXT = [
    ("extended_A_live", "Extended Cut - Live", "Extended Cut · Live\nMouv' Live Club, Paris 2018\nbeat continues: Dadju 'Reine' (prod. Seysey)", (255, 140, 40)),
    ("extended_B_studio", "Extended Cut - Studio Rebuild", "Extended Cut · Studio Rebuild\nisolated vocal over the studio 'Reine'\n(prod. Seysey)", (255, 170, 70)),
    ("extended_C_dadju", "Extended Cut - Dadju Continuation", "Extended Cut · Dadju continuation\nthe record keeps playing:\nbridge, chorus & outro by Dadju", (240, 110, 60)),
]
REMIX = {
    "internet_money": ("remix_internet_money", "Run Carlie 'Internet Money' type beat", (120, 150, 255)),
    "sad_guitar": ("remix_sad_guitar", "OAR Beatz 'Sad Guitar' / 'Love Music' type beat", (110, 200, 255)),
    "codeine": ("remix_codeine", "Taz Taylor 'Codeine' (A$AP Rocky type beat)", (190, 120, 255)),
    "forests": ("remix_forests", "nytcyd 'Forests' (afro-pop guitar)", (120, 230, 150)),
    "scared": ("remix_scared", "VHS x Taz Taylor 'Scared' (Keith Ape type beat)", (255, 90, 120)),
}
LABEL = {0: "Remix", 1: "Remix (runner-up)", 2: "Remix (runner-up 2)"}


def main():
    out, order = sys.argv[1], sys.argv[2:]
    tracks = []
    for i, (src, sub, cover_sub, accent) in enumerate(EXT, 1):
        tracks.append({"src": f"work/renders/extended/{src}.wav", "name": f"{i:02d} - {BASE} [{sub}]",
                       "title": f"Campfire (Reine Freestyle) [{sub}]", "artist": "Juice WRLD",
                       "cover_title": "Campfire (Reine Freestyle)", "subtitle": cover_sub, "accent": accent,
                       "comment": "Fan edit, personal use only. Live vocal: Mouv' Live Club (DJ Muxxa), 2018. Beat: Dadju - Reine (prod. Seysey)."})
    for j, key in enumerate(order):
        src, beat, accent = REMIX[key]
        n = len(EXT) + j + 1
        lab = LABEL.get(j, "Remix (alt)")
        tracks.append({"src": f"work/renders/final/{src}.wav", "name": f"{n:02d} - {BASE} [{lab} - {key.replace('_', ' ').title()}]",
                       "title": f"Campfire (Reine Freestyle) [{lab} - {key.replace('_', ' ').title()}]", "artist": "Juice WRLD",
                       "cover_title": "Campfire (Remix)", "subtitle": f"{lab}\nbeat: {beat}", "accent": accent,
                       "comment": f"Fan remix, personal use only. Vocal: Juice WRLD live at Mouv' 2018. Beat: {beat} (all rights to the producer)."})
    json.dump({"out_dir": "deliverables", "album": ALBUM, "tracks": tracks}, open(out, "w"), indent=1)
    print(f"{len(tracks)} tracks -> {out}")


if __name__ == "__main__":
    main()
