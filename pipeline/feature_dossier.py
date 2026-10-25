#!/usr/bin/env python3
"""Collect everything known about each rendered "Juice WRLD x guest" candidate into one dossier for judging.

For every spec in work/feature/specs/ named on the command line: render facts (feature_song output, QA),
evaluation (intelligibility in the mix, 16th-grid timing), guest verse analysis (harmony vs Reine, words),
groove feel of the guest's original beat and vocal (straight vs triplet), tempo stretch, the scouts' notes
(why it fits / risks), and the verse lyrics as recognised. Also Juice's own reference numbers.
Writes work/feature/dossier.json and prints a compact table.
Usage: feature_dossier.py SPEC_NAME [SPEC_NAME ...]
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groove_feel import feel  # noqa: E402

ROOT = "/home/user/test"


def load(p, default=None):
    return json.load(open(p)) if os.path.exists(p) else default


def main():
    out = {"reference": {"juice_vocal_16th_lock_env": 0.179, "juice_vocal_ternary": 0.09, "reine_straight16": 0.46,
                         "reine_ternary": 0.13, "juice_recall_in_mix": 0.919, "reine_key": "D major / B minor, 2-bar loop",
                         "reine_bpm_live": 100.446,
                         "juice_freestyle_transcript": " ".join(
                             w["word"] for s in load(f"{ROOT}/work/analysis/transcript_vocals.json")["segments"]
                             for w in s.get("words", []) if 14.5 <= w.get("start", 0) <= 117.7)},
           "candidates": []}
    for name in sys.argv[1:]:
        spec = load(f"{ROOT}/work/feature/specs/{name}.json")
        cand = os.path.join(ROOT, os.path.dirname(spec["guest_acapella"]))
        meta, grid, an = load(f"{cand}/meta.json", {}), load(f"{cand}/grid.json", {}), load(f"{cand}/analysis.json", {})
        ev = load(os.path.join(ROOT, spec["out"][:-4] + ".eval.json"), {})
        qa = load(os.path.join(ROOT, spec["out"][:-4] + ".qa.json"), {})
        sd = sorted(glob.glob(f"{cand}/sep/*/"))
        gf = {}
        if sd:
            off, b1, T = grid["crop_offset_s"], grid["verse_bar1"], grid["period"]
            vs, ve = float(meta["verse_start_s"]), float(meta["verse_end_s"])
            for stem in ("instrumental", "vocals"):
                gf[stem] = feel(sd[0] + f"{stem}.wav", b1 - off, T, max(0, vs - off), ve - off)
        g0 = spec["guest_bar1"] - spec["guest_pickup_s"]
        g1 = spec["guest_bar1"] + spec["guest_bars"] * 4 * spec["guest_period"] + spec["guest_tail_s"]
        words = load(f"{cand}/words.json", {}).get("words", [])
        c = {"name": name, "render": spec["out"], "artist": meta.get("artist"), "title": meta.get("title"),
             "language": meta.get("language", "en"), "guest_bpm": grid.get("bpm"),
             "stretch_pct": round((4 * spec["guest_period"] / 2.38934 - 1) * 100, 2), "verse_bars": spec["guest_bars"],
             "duration_s": qa.get("duration_s"), "lufs": qa.get("lufs_integrated"), "true_peak_db": qa.get("true_peak_db"),
             "edit_level_jumps_db": qa.get("edit_level_jumps_db"),
             "intelligibility_in_mix": ev.get("guest_recall_in_mix"), "timing_16th_lock_R": ev.get("guest_16th_lock_R"),
             "timing_offset_vs_reine_drums_ms": round(ev["guest_16th_offset_ms"] - 32.0, 1) if "guest_16th_offset_ms" in ev else None,
             "harmony_vs_reine_rel_to_juice": an.get("harmony", {}).get(f"0:{int(spec.get('transpose', 0))}"),
             "harmony_best_shift": an.get("harmony_best"), "voiced_s": an.get("voiced_s"),
             "stem_gap_level_db": an.get("gap_level_db_raw"), "groove_feel": gf,
             "scout_why": meta.get("why_it_fits"), "scout_risks": meta.get("risks"),
             "lyrics": " ".join(w["w"] for w in words if g0 - 0.05 <= w["s"] <= g1),
             "qa_png": spec["out"][:-4] + ".qa.png"}
        out["candidates"].append(c)
    json.dump(out, open(f"{ROOT}/work/feature/dossier.json", "w"), indent=1)
    for c in out["candidates"]:
        gi, gv = c["groove_feel"].get("instrumental", {}), c["groove_feel"].get("vocals", {})
        print(f"{c['name']:34s} {str(c['artist'])[:22]:22s} str {c['stretch_pct']:+5.1f}% bars {c['verse_bars']:2d} dur {c['duration_s']} "
              f"intel {c['intelligibility_in_mix']} lockR {c['timing_16th_lock_R']} off {c['timing_offset_vs_reine_drums_ms']} "
              f"harm {c['harmony_vs_reine_rel_to_juice']} voiced {c['voiced_s']} gap {c['stem_gap_level_db']} "
              f"inst_tern {gi.get('ternary_ratio')} voc_s16 {gv.get('straight16')}")


if __name__ == "__main__":
    main()
