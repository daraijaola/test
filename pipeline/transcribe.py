#!/usr/bin/env python3
"""Word-level transcription with per-segment language identification.

Used to find exactly where Juice WRLD's first and last words are and to tell
the host (French) apart from Juice (English). The transcript is only used
internally for edit points; it is never shipped as a lyric sheet.

Usage: transcribe.py INPUT.wav OUTPUT.json [--model large-v3]
"""
import argparse
import json

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--model", default="large-v3")
    args = ap.parse_args()

    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=4)
    audio = decode_audio(args.input, sampling_rate=16000)
    segments, info = model.transcribe(
        audio, word_timestamps=True, multilingual=True, beam_size=5,
        condition_on_previous_text=False, vad_filter=False, temperature=0.0)

    out = {"input": args.input, "model": args.model, "duration": len(audio) / 16000,
           "global_language": info.language, "global_language_prob": info.language_probability,
           "segments": []}
    for s in segments:
        chunk = audio[int(s.start * 16000):int(s.end * 16000)]
        langs = {}
        if len(chunk) > 16000 * 0.6:
            try:
                _, _, probs = model.detect_language(chunk)
                langs = {k: round(v, 3) for k, v in probs[:3]}
            except Exception:
                pass
        out["segments"].append({
            "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
            "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3),
            "languages": langs,
            "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip(),
                       "p": round(w.probability, 3)} for w in (s.words or [])],
        })
        print(f"[{s.start:7.2f}-{s.end:7.2f}] {langs} {s.text.strip()[:90]}")
    with open(args.output, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
