#!/usr/bin/env python3
"""Analyse an isolated guest verse against the Reine continuation (run after guest_prep.py + separate.py).

1. Clean: conservative downward expander on the vocal stem (bleed of the guest's own beat in the gaps).
   Bleed metric = level of the gaps (no words) relative to the words, before and after the expander.
2. Words: faster-whisper large-v3 word timestamps on the clean stem (source timeline). Gives the true first
   word (pickup before bar 1), the last word, and the bar count.
3. Harmony: torchcrepe pitch of the stem, mapped onto the output timeline (verse bar 1 on a Reine bar),
   consonance-weighted against the Reine instrumental's chroma for transpositions -3..+3 and both
   positions in Reine's 2-bar chord loop; normalised by Juice's own score on his beat (1.0 = as good as Juice).
4. Groove: 16th-position histogram of the guest's syllable onsets vs the Reine beat's onsets (bars 57-72),
   next to Juice's own value on his beat.

Writes CAND_DIR/analysis.json and CAND_DIR/vocals_clean.wav (crop timeline).
Usage: guest_analyze.py CAND_DIR [--model-dir sep/<model-stem>]
"""
import argparse
import glob
import json
import os
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitscore as fsc  # noqa: E402
import mixlib as mx  # noqa: E402
from make_acapella import expander  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402

ROOT = "/home/user/test"
REF_BAR = 57          # Reine bar the verse's bar 1 is scored against (bars 57-72 loop)


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def words_of(path, language="en"):
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    model = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = model.transcribe(decode_audio(path, sampling_rate=16000), language=language, word_timestamps=True,
                               beam_size=5, condition_on_previous_text=False, vad_filter=False, temperature=0.0)
    out = []
    for s in segs:
        for w in s.words or []:
            out.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)})
    return out


def pitch_of(path):
    import torch
    import torchcrepe

    y, _ = librosa.load(path, sr=16000, mono=True)
    torch.set_num_threads(4)
    f0, per = torchcrepe.predict(torch.tensor(y[None, :]), 16000, 160, fmin=65.0, fmax=1050.0, model="full",
                                 decoder=torchcrepe.decode.viterbi, return_periodicity=True, batch_size=512, device="cpu")
    per = torchcrepe.filter.median(per, 3)
    f0, per = f0[0].numpy(), per[0].numpy()
    t = np.arange(len(f0)) * 0.01
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=160, center=True)[0][:len(f0)]
    ld = 20 * np.log10(rms + 1e-9)
    w = np.where((per > 0.55) & (ld > np.percentile(ld, 40)), per, 0.0)
    return t, f0, w


def gap_level(v, words, offset, sr=mx.SR):
    """Median level of no-word regions minus the 90th percentile level of word regions (dB)."""
    mono = v.mean(axis=1)
    hop = int(0.05 * sr)
    n = len(mono) // hop
    rms = np.sqrt(np.mean(mono[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    tt = (np.arange(n) + 0.5) * hop / sr + offset
    inw = np.zeros(n, bool)
    for w in words:
        inw |= (tt >= w["s"] - 0.05) & (tt <= w["e"] + 0.15)
    if inw.sum() < 10 or (~inw).sum() < 10:
        return float("nan")
    return float(np.median(db[~inw]) - np.percentile(db[inw], 90))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("--model-dir", default=None)
    a = ap.parse_args()
    d = a.cand
    meta = json.load(open(os.path.join(d, "meta.json")))
    grid = json.load(open(os.path.join(d, "grid.json")))
    mdir = os.path.join(d, a.model_dir) if a.model_dir else sorted(glob.glob(os.path.join(d, "sep", "*")))[0]
    off = grid["crop_offset_s"]
    T = grid["period"]
    bar_src = 4 * T
    rate = bar_src / LIVE_BAR
    bar1 = grid["verse_bar1"]
    v = mx.load(os.path.join(mdir, "vocals.wav"))
    vc, thr = expander(v, mx.SR, thresh_rel_db=-40.0, max_cut_db=15.0)
    clean = os.path.join(d, "vocals_clean.wav")
    mx.save(clean, vc)

    cache = os.path.join(d, "words.json")            # whisper is the slow step: reuse words for the same stem
    wc = json.load(open(cache)) if os.path.exists(cache) else {}
    if wc.get("model_dir") == mdir and wc.get("offset") == off:
        words = wc["words"]
    else:
        words = words_of(clean, meta.get("language", "en"))
        for w in words:
            w["s"] = round(w["s"] + off, 3)
            w["e"] = round(w["e"] + off, 3)
        json.dump({"model_dir": mdir, "offset": off, "words": words}, open(cache, "w"))
    vs, ve = float(meta["verse_start_s"]), float(meta["verse_end_s"])
    verse = [w for w in words if vs - 1.5 <= w["s"] <= ve + 0.5]
    first, last = (verse[0], verse[-1]) if verse else (None, None)

    # harmony: output-timeline frames (verse bar 1 -> REF_BAR), against Reine studio instrumental chroma
    t, f0, wt = pitch_of(clean)
    src_t = t + off
    sel = (src_t >= bar1 - 1.0) & (src_t <= ve + 1.0)
    yb, _ = librosa.load(f"{ROOT}/work/renders/extended/studio_inst_on_live.wav", sr=22050, mono=True)
    ct, chroma = fsc.beat_chroma(yb, 22050)
    res = {}
    for shift in (0, 1):                                      # 0: bar 1 on a D-type bar, 1: on an A-type bar
        bpos = (src_t - bar1) / bar_src                       # verse bar position (float)
        bi = np.floor(bpos)
        ref = live_bar(REF_BAR + shift) + np.mod(bi, 16) * LIVE_BAR + (bpos - bi) * LIVE_BAR
        for k in range(-3, 4):
            res[f"{shift}:{k}"] = fsc.harmonic_fit(ref[sel], f0[sel], wt[sel], ct, chroma, transpose=-k)
    jp = np.load(f"{ROOT}/work/analysis/juice_pitch.npz")
    yl, _ = librosa.load(f"{ROOT}/work/stems/live_inst_hq.wav", sr=22050, mono=True)
    lt, lc = fsc.beat_chroma(yl, 22050)
    jsel = (jp["times"] >= 14.5) & (jp["times"] <= 117.7)
    jw = np.where(jp["voiced"], jp["periodicity"], 0.0)
    juice_h = fsc.harmonic_fit(jp["times"][jsel], jp["f0"][jsel], jw[jsel], lt, lc)
    best = max(res, key=lambda k: (res[k] if np.isfinite(res[k]) else -9) - 0.02 * abs(int(k.split(":")[1])))
    voiced_s = float((wt[sel] > 0).sum() * 0.01)

    # groove: guest onsets on the output grid vs Reine onsets in bars 57-72; Juice's own value for reference
    y22, _ = librosa.load(clean, sr=22050, mono=True)
    on = librosa.onset.onset_detect(y=y22, sr=22050, units="time", backtrack=False) + off
    on = on[(on >= bar1 - 1.0) & (on <= ve + 0.5)]
    on_out = live_bar(REF_BAR) + (on - bar1) / rate
    b_on = librosa.onset.onset_detect(y=yb, sr=22050, units="time")
    downs = live_bar(REF_BAR) + LIVE_BAR * np.arange(-1, 40)
    b_sel = b_on[(b_on >= live_bar(57)) & (b_on < live_bar(73))]
    on_loop = live_bar(57) + np.mod(on_out - live_bar(57), 16 * LIVE_BAR)
    groove = fsc.groove_fit(on_loop, b_sel, downs, LIVE_BAR)
    jv, _ = librosa.load(f"{ROOT}/work/stems/juice_acapella_hq.wav", sr=22050, mono=True)
    j_on = librosa.onset.onset_detect(y=jv, sr=22050, units="time")
    j_on = j_on[(j_on > 15.1) & (j_on < 117.7)]
    l_on = librosa.onset.onset_detect(y=yl, sr=22050, units="time")
    l_on = l_on[(l_on > 15.1) & (l_on < 117.7)]
    jdowns = live_bar(1) + LIVE_BAR * np.arange(0, 60)
    juice_g = fsc.groove_fit(j_on, l_on, jdowns, LIVE_BAR)
    # syllable density (onsets per bar) - flow speed
    dens = len(on) / max(1e-6, (ve - bar1) / bar_src)

    out = {
        "artist": meta.get("artist"), "title": meta.get("title"), "model_dir": mdir,
        "bpm": grid["bpm"], "stretch_rate": round(rate, 5), "verse_bar1": bar1,
        "first_word": first, "last_word": last,
        "pickup_s": round(bar1 - first["s"], 3) if first else None,
        "verse_bars": round((last["e"] - bar1) / bar_src, 2) if last else None,
        "n_words": len(verse), "mean_word_prob": round(float(np.mean([w["p"] for w in verse])), 3) if verse else None,
        "gap_level_db_raw": round(gap_level(v, words, off), 1), "gap_level_db_clean": round(gap_level(vc, words, off), 1),
        "voiced_s": round(voiced_s, 1),
        "harmony": {k: round(x / juice_h, 3) if np.isfinite(x) else None for k, x in res.items()},
        "harmony_best": best, "harmony_best_rel": round(res[best] / juice_h, 3),
        "juice_harmony_raw": round(juice_h, 4),
        "groove": round(groove, 3), "juice_groove": round(juice_g, 3), "onsets_per_bar": round(dens, 1),
        "text": " ".join(w["w"] for w in verse),
        "words": verse,
    }
    json.dump(out, open(os.path.join(d, "analysis.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "words"}, indent=1))


if __name__ == "__main__":
    main()
