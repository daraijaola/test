#!/usr/bin/env python3
"""Run any audio-separator model and keep every stem it produces (de-reverb, denoise, karaoke, ...).

separate.py insists on a vocals/instrumental pair; models such as BS-RoFormer De-Reverb write "(Noreverb)" /
"(Reverb)" stems instead. This writes OUT_DIR/<stem-label-lowercase>.wav for each stem, e.g. noreverb.wav.

Usage: sep_any.py [--overlap N] INPUT OUT_DIR MODEL
"""
import re
import shutil
import sys
import time
from pathlib import Path

MODEL_DIR = "/opt/models/audio-separator"


def main():
    args = sys.argv[1:]
    overlap = 4
    if args[0] == "--overlap":
        overlap, args = int(args[1]), args[2:]
    inp, out, model = Path(args[0]), Path(args[1]), args[2]
    from audio_separator.separator import Separator

    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    t0 = time.time()
    sep = Separator(output_dir=str(tmp), model_file_dir=MODEL_DIR, output_format="WAV", sample_rate=44100,
                    use_soundfile=True,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False, "batch_size": 1,
                                 "overlap": overlap, "pitch_shift": 0})
    sep.load_model(model_filename=model)
    names = []
    for f in sep.separate(str(inp)):
        p = tmp / Path(f).name
        m = re.search(r"_\(([^)]+)\)", p.name)
        label = (m.group(1) if m else p.stem).lower().replace(" ", "_")
        shutil.move(p, out / f"{label}.wav")
        names.append(label)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[done] {model} in {time.time() - t0:.0f}s -> {out}: {names}")


if __name__ == "__main__":
    main()
