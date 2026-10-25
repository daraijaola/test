#!/usr/bin/env python3
"""Write a feature_song.py spec for one guest verse.

Arrangement after Juice's last bar (48): 2 bars of the Reine bridge (49-50) as a breath, then the verse over
an 808 bed made of whole Reine bars, then Reine's own outro (73 ->). The bed is sized to the verse:
   8: chorus 3 (65-72)                       20: chorus 2 + build + chorus 3 (41-48, 61-72)
  12: build + chorus 3 (61-72)               24: chorus 2 + bridge B + build + chorus 3 (41-48, 57-72)
  16: chorus 2 + chorus 3 (41-48, 65-72)     28/32: chorus 2 repeated in front of the 24-bar bed
All jumps keep Reine's 2-bar chord loop parity (odd output bar <- odd studio bar).

Usage: make_feature_spec.py CAND_DIR NAME --start S --end E --bars N [--post-bars 4] [--land 51]
       [--acapella PATH] [--over-beat 1.5] [--transpose 0] [--bar1 S]
  S/E: source-time cut points (first pickup syllable / after the last word); N: verse bars from bar 1.
"""
import argparse
import json
import math
import os

ROOT = "/home/user/test"
BEDS = {8: [(65, 8)], 12: [(61, 12)], 16: [(41, 8), (65, 8)], 20: [(41, 8), (61, 12)], 24: [(41, 8), (57, 16)],
        28: [(45, 4), (41, 8), (57, 16)], 32: [(41, 8), (41, 8), (57, 16)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("name")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--bars", type=int, required=True)
    ap.add_argument("--post-bars", type=int, default=0)
    ap.add_argument("--land", type=int, default=51)
    ap.add_argument("--acapella", default=None)
    ap.add_argument("--over-beat", type=float, default=1.5)
    ap.add_argument("--transpose", type=float, default=0.0)
    ap.add_argument("--bar1", type=float, default=None, help="override the verse bar-1 downbeat (source s)")
    a = ap.parse_args()
    g = json.load(open(os.path.join(a.cand, "grid.json")))
    b1, T = (a.bar1 if a.bar1 is not None else g["verse_bar1"]), g["period"]
    L = 4 * math.ceil((a.bars + a.post_bars) / 4)
    if L not in BEDS:
        raise SystemExit(f"no bed for {L} bars")
    cont = [[49, a.land - 49, 49]] if a.land > 49 else []
    o = a.land
    for sb, n in BEDS[L]:
        if cont and cont[-1][2] + cont[-1][1] == sb and cont[-1][0] + cont[-1][1] == o:
            cont[-1][1] += n
        else:
            cont.append([o, n, sb])
        o += n
    cont.append([o, 0, 73])
    spec = {
        "out": f"work/renders/feature/{a.name}.wav",
        "cont": cont,
        "guest_acapella": a.acapella or os.path.relpath(os.path.join(a.cand, "vocals_clean.wav"), ROOT),
        "guest_offset_s": g["crop_offset_s"], "guest_period": T, "guest_bar1": b1,
        "guest_bars": a.bars, "guest_pickup_s": round(b1 - a.start, 3),
        "guest_tail_s": round(a.end - (b1 + a.bars * 4 * T), 3), "fade_in_s": 0.02, "fade_out_s": 0.08,
        "land_bar": a.land, "transpose": a.transpose, "guest_inst_onset_ms": g.get("inst_onset_offset_ms", 32.0),
        "guest_over_beat_lu": a.over_beat, "post_trim_db": -1.0, "post_trim_from_bar": a.land,
        "match_juice_to": "work/renders/extended/extended_A_live.wav", "target_lufs": -12.0}
    os.makedirs(f"{ROOT}/work/feature/specs", exist_ok=True)
    p = f"{ROOT}/work/feature/specs/{a.name}.json"
    json.dump(spec, open(p, "w"), indent=1)
    print(p, json.dumps({k: spec[k] for k in ("cont", "guest_pickup_s", "guest_tail_s")}))


if __name__ == "__main__":
    main()
