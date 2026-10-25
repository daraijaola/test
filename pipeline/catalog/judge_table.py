#!/usr/bin/env python3
"""Join rendered-preview metrics with catalog metadata into one compact table for the judges.

Usage: judge_table.py PREVIEWS.jsonl CATALOG.jsonl OUT.json
"""
import json
import sys


def main():
    prev_path, cat_path, out_path = sys.argv[1:4]
    cat = {}
    for line in open(cat_path):
        if line.strip():
            r = json.loads(line)
            cat[r["id"]] = r
    rows = []
    for line in open(prev_path):
        if not line.strip():
            continue
        p = json.loads(line)
        if "preview" not in p:
            continue
        c = cat.get(p["id"], {})
        rows.append({
            "id": p["id"], "source": p["source"], "artist": p.get("artist"), "title": p.get("title"),
            "genre_bucket": c.get("genre_bucket"), "tags": (c.get("tags") or [])[:8], "license": p.get("license"),
            "page_url": p.get("page_url"), "full_audio_available": p.get("full_audio_available"),
            "is_instrumental_meta": c.get("is_instrumental_meta"), "p_instr_clap": p.get("p_instr"),
            "tempo_measured": p.get("tempo_measured"), "tempo_mult": p.get("tempo_mult"),
            "stretch": p.get("stretch"), "transpose_semitones": p.get("transpose"),
            "harmonic_ratio_sim": p.get("harmonic_ratio"), "harmonic_ratio_rendered": p.get("harmonic_ratio_rendered"),
            "groove": p.get("groove"), "vibe_clap": p.get("vibe"), "masking_db": p.get("masking_db"),
            "loop_similarity": p.get("loop_sim"), "stage2_fit": p.get("fit2"),
            "preview_wav": p["preview"], "preview_spectrogram_png": p["preview"][:-4] + ".qa.png",
        })
    json.dump(rows, open(out_path, "w"), indent=1)
    print(f"{len(rows)} candidates -> {out_path}")


if __name__ == "__main__":
    main()
