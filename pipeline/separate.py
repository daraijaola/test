#!/usr/bin/env python3
"""Run one or more source-separation models on an input file.

Each model writes into OUT_DIR/<model-stem>/ as vocals.wav and instrumental.wav
(float WAV at the input's sample rate), so results from different models can be
compared side by side.

Usage:
  separate.py [--overlap N] INPUT OUT_DIR MODEL [MODEL ...]
--overlap trades speed for quality on RoFormer/MDX23C models (audio-separator
default is 8; 2 is ~4x faster and fine for ranking models against each other).
MODEL is an audio-separator model filename (e.g. model_bs_roformer_ep_317_sdr_12.9755.ckpt)
or "demucs:<name>" (e.g. demucs:htdemucs_ft).
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODEL_DIR = "/opt/models/audio-separator"
PY = "/opt/ml/bin/python"


def stem_of(model):
    return model.replace("demucs:", "demucs_").rsplit(".", 1)[0]


def run_audio_separator(inp, out, model, overlap):
    from audio_separator.separator import Separator

    tmp = out / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    sep = Separator(output_dir=str(tmp), model_file_dir=MODEL_DIR, output_format="WAV",
                    sample_rate=44100, use_soundfile=True,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": overlap, "pitch_shift": 0})
    sep.load_model(model_filename=model)
    files = sep.separate(str(inp))
    for f in files:
        p = tmp / Path(f).name
        low = p.name.lower()
        # audio-separator names stems "<input>_(Vocals)_<model>.wav" / "(Instrumental)" / "(Other)" etc.
        if "(vocals)" in low:
            shutil.move(p, out / "vocals.wav")
        elif "(instrumental)" in low or "(other)" in low or "(no vocals)" in low:
            shutil.move(p, out / "instrumental.wav")
        else:
            shutil.move(p, out / p.name)
    shutil.rmtree(tmp, ignore_errors=True)


def run_demucs(inp, out, name):
    tmp = out / "_tmp"
    subprocess.run([PY, "-m", "demucs", "-n", name, "--two-stems", "vocals", "--float32",
                    "-o", str(tmp), str(inp)], check=True)
    d = next(tmp.glob(f"{name}/*"))
    shutil.move(d / "vocals.wav", out / "vocals.wav")
    shutil.move(d / "no_vocals.wav", out / "instrumental.wav")
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    args = sys.argv[1:]
    overlap = 8
    if args[0] == "--overlap":
        overlap, args = int(args[1]), args[2:]
    inp, out_root, models = Path(args[0]), Path(args[1]), args[2:]
    os.makedirs(MODEL_DIR, exist_ok=True)
    for model in models:
        out = out_root / stem_of(model)
        if (out / "vocals.wav").exists():
            print(f"[skip] {model} (already done)")
            continue
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            if model.startswith("demucs:"):
                run_demucs(inp, out, model.split(":", 1)[1])
            else:
                run_audio_separator(inp, out, model, overlap)
            if not (out / "vocals.wav").exists() or not (out / "instrumental.wav").exists():
                raise RuntimeError("model produced no vocals/instrumental pair (corrupt checkpoint?)")
            print(f"[done] {model} in {time.time() - t0:.0f}s -> {out}")
        except Exception as e:
            shutil.rmtree(out, ignore_errors=True)
            print(f"[FAIL] {model}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
