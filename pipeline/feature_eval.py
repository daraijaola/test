#!/usr/bin/env python3
"""Objective checks of a rendered "Juice WRLD x guest" song (run after feature_song.py).

intelligibility  faster-whisper on the guest's part of the FINAL MIX vs the words recognised on the clean
                 acapella (multiset word recall). The beat is loud on purpose; this says whether the verse
                 still reads through it. Baseline: the same measure for Juice's part of the Extended Cut.
timing           guest syllable onsets mapped onto the output timeline, folded onto Reine's 16th-note grid:
                 concentration R (1 = every onset on a 16th) and the mean signed offset in ms. Juice's own
                 onsets on the live grid give the reference for both.
Writes OUT.eval.json next to the render. Usage: feature_eval.py SPEC.json
"""
import collections
import json
import os
import re
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402

ROOT = "/home/user/test"
S16 = LIVE_BAR / 16


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def norm(w):
    return re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœæ']", "", w.lower())


def transcribe(y, language):
    from faster_whisper import WhisperModel

    y16 = librosa.resample(y.mean(axis=1), orig_sr=mx.SR, target_sr=16000).astype(np.float32)
    model = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = model.transcribe(y16, language=language, word_timestamps=True, beam_size=5,
                               condition_on_previous_text=False, vad_filter=False, temperature=0.0)
    return [w.word for s in segs for w in (s.words or [])]


def recall(ref, hyp):
    r = collections.Counter(norm(w) for w in ref if norm(w))
    h = collections.Counter(norm(w) for w in hyp if norm(w))
    return sum((r & h).values()) / max(1, sum(r.values()))


def lock(onsets, grid0):
    ph = np.mod(onsets - grid0, S16) / S16                 # 0..1 within a 16th
    z = np.exp(2j * np.pi * ph).mean()
    return float(abs(z)), float(np.angle(z) / (2 * np.pi) * S16 * 1000)


def main():
    spec = json.load(open(sys.argv[1]))
    cfg = json.load(open(spec.get("base_config", f"{ROOT}/work/renders/extended/config.json")))
    b5 = cfg["bar5"]
    cand = os.path.dirname(spec["guest_acapella"])
    meta = json.load(open(os.path.join(cand, "meta.json")))
    lang = meta.get("language", "en")
    y = mx.load(spec["out"])
    T = spec["guest_period"]
    rate = 4 * T / LIVE_BAR
    bar1_out = live_bar(spec["land_bar"]) - b5
    g0 = spec["guest_bar1"] - spec.get("guest_pickup_s", 0.0)
    g1 = spec["guest_bar1"] + spec["guest_bars"] * 4 * T + spec.get("guest_tail_s", 0.6)
    o0, o1 = bar1_out - spec.get("guest_pickup_s", 0.0) / rate, bar1_out + (g1 - spec["guest_bar1"]) / rate
    words = json.load(open(os.path.join(cand, "words.json")))["words"]
    ref = [w["w"] for w in words if g0 - 0.05 <= w["s"] <= g1]
    hyp = transcribe(y[mx.sec(max(0, o0 - 0.3)):mx.sec(o1 + 0.3)], lang)
    rec = recall(ref, hyp)

    # timing: guest onsets (clean acapella, source timeline) -> output timeline -> Reine 16th grid
    v, _ = librosa.load(spec["guest_acapella"], sr=22050, mono=True)
    on = librosa.onset.onset_detect(y=v, sr=22050, units="time") + spec.get("guest_offset_s", 0.0)
    on = on[(on >= g0) & (on <= g1)]
    import feature_song as fs
    on_live = live_bar(spec["land_bar"]) + fs.guest_shift_ms(spec) / 1000.0 + (on - spec["guest_bar1"]) / rate
    R, off_ms = lock(on_live, LIVE_BAR1)
    jv, _ = librosa.load(f"{ROOT}/work/stems/juice_acapella_hq.wav", sr=22050, mono=True)
    jon = librosa.onset.onset_detect(y=jv, sr=22050, units="time")
    jon = jon[(jon > 15.1) & (jon < 117.7)]
    jR, joff = lock(jon, LIVE_BAR1)

    base_p = f"{ROOT}/work/renders/feature/juice_part_intelligibility.json"
    if os.path.exists(base_p):
        base = json.load(open(base_p))
    else:                                                  # Juice's part of the Extended Cut, once
        a = mx.load(f"{ROOT}/work/renders/extended/extended_A_live.wav")
        tj = json.load(open(f"{ROOT}/work/analysis/transcript_vocals.json"))
        jref = [w["word"] for s in tj.get("segments", []) for w in s.get("words", [])
                if 60.0 <= w.get("start", 0) <= 117.7 and s.get("language", "en") == "en"]
        jhyp = transcribe(a[mx.sec(60.0 - b5):mx.sec(117.7 - b5)], "en")
        base = {"juice_recall_in_mix": round(recall(jref, jhyp), 3), "n_ref": len(jref)}
        json.dump(base, open(base_p, "w"), indent=1)
    out = {"render": spec["out"], "artist": meta.get("artist"), "title": meta.get("title"),
           "guest_recall_in_mix": round(rec, 3), "n_ref_words": len(ref), "juice_recall_in_mix": base["juice_recall_in_mix"],
           "guest_16th_lock_R": round(R, 3), "guest_16th_offset_ms": round(off_ms, 1),
           "juice_16th_lock_R": round(jR, 3), "juice_16th_offset_ms": round(joff, 1),
           "hyp_text": " ".join(hyp)}
    json.dump(out, open(spec["out"][:-4] + ".eval.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "hyp_text"}))


if __name__ == "__main__":
    main()
