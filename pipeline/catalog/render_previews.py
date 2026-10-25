#!/usr/bin/env python3
"""Render full-verse previews of Juice over the top stage-2 candidates and re-measure the fit on
the rendered audio (not the simulation).

For each candidate: beat_this grid (same half/double-time handling as fit_detailed) -> seamless
tiled loop of the clip's whole bars -> anchor chosen from fit_detailed's best offset -> render with
remix_render.render (stretch to 100.415 BPM, transpose, vocal chain, master). Post-render metrics:
  harmonic_ratio_rendered : beat-synchronous consonance of his sung pitch vs the rendered bed,
                            normalised by the real Reine beat (1.0 = as good as the original)
  masking_db              : bed level in the 1-4 kHz vocal band relative to the vocal, on sung beats
Writes work/renders/previews/<n>_<id>.wav + .qa.png and previews.jsonl.

Usage: render_previews.py FIT_DETAILED.jsonl TOP_N VOCALS.wav
"""
import json
import os
import re
import sys
import warnings

import librosa
import numpy as np

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import mixlib as mx  # noqa: E402
import remix_render as rr  # noqa: E402
from fitscore import INTERVAL_W  # noqa: E402

ROOT = "/home/user/test"
OUT = f"{ROOT}/work/renders/previews"
BAR1, BAR = rr.LIVE_BAR1, rr.LIVE_BAR
BEAT = BAR / 4
TARGET_BPM = 60 / BEAT
D = np.mod(np.arange(12)[:, None] - np.arange(12)[None, :], 12)
WM = INTERVAL_W[D]


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:80]


def safe_id(s):  # same convention as analyze_catalog.py's CLAP file names
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:150]


def cand_beats(f2b, path):
    beats, _ = f2b(path)
    beats = np.asarray(beats)
    tempo = 60 / np.median(np.diff(beats))
    mult = min((0.5, 1.0, 2.0), key=lambda m: abs(TARGET_BPM / (tempo * m) - 1))
    if mult == 2.0:
        beats = np.sort(np.concatenate([beats, (beats[:-1] + beats[1:]) / 2]))
    elif mult == 0.5:
        beats = beats[::2]
    # beat_this works on a 20 ms frame grid; produced beats have a steady tempo, so a linear fit
    # over all beats gives sample-level period and phase (otherwise tiling/stretching drifts)
    k = np.arange(len(beats))
    T, t0 = np.polyfit(k, beats, 1)
    resid = beats - (t0 + T * k)
    if np.std(resid) < 0.015:
        beats = t0 + T * k
    return beats


def tiled_loop(path, beats, n_loop, tiles=8):
    x = mx.load(path)
    a, b = mx.sec(beats[0]), mx.sec(beats[n_loop])
    loop = x[a:b]
    xf = mx.sec(0.01)
    out = loop.copy()
    for _ in range(tiles - 1):
        out = mx.crossfade(out, np.concatenate([x[max(0, a - xf):a], loop]) if a >= xf else loop, xf)
    return out, (b - a) / mx.SR


def juice_profiles():
    d = np.load(f"{ROOT}/work/analysis/juice_pitch.npz")
    t, f0, per, voiced = d["times"], d["f0"], d["periodicity"], d["voiced"]
    sel = voiced & (t >= 14.5) & (t <= 117.72)
    pc = np.mod(np.round(69 + 12 * np.log2(np.maximum(f0[sel], 1e-3) / 440.0)), 12).astype(int)
    return t[sel], pc, per[sel]


def rendered_metrics(bed, voc_track, vocal_at, jt, jpc, jw, base):
    """bed/voc_track are the output-timeline beat and vocal tracks (pre-master)."""
    sr = mx.SR
    # map Juice's live pitch frames into output time: output = live - bar5_live + vocal_at
    shift = vocal_at - rr.live_bar(rr.VOCAL_FROM_BAR)
    ot = jt + shift
    y = librosa.resample(bed.mean(axis=1), orig_sr=sr, target_sr=22050)
    c = librosa.feature.chroma_cqt(y=y, sr=22050, hop_length=512)
    c = c / (c.sum(axis=0, keepdims=True) + 1e-9)
    fr = np.clip(librosa.time_to_frames(ot, sr=22050, hop_length=512), 0, c.shape[1] - 1)
    cons = np.einsum("kn,nk->n", c[:, fr], WM[jpc])   # sum over chord pcs of chroma x consonance
    score = float((cons * jw).sum() / (jw.sum() + 1e-9))
    # masking: 1-4 kHz band energy of bed vs vocal over sung segments
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, [1000, 4000], btype="band", fs=sr, output="sos")
    bb = sosfiltfilt(sos, bed.mean(axis=1))
    vb = sosfiltfilt(sos, voc_track.mean(axis=1))
    i0, i1 = mx.sec(vocal_at), mx.sec(vocal_at + 100)
    mask_db = 10 * np.log10((bb[i0:i1] ** 2).mean() / ((vb[i0:i1] ** 2).mean() + 1e-12))
    return score / base, float(mask_db)


def main():
    fit_path, top_n, vocals = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    from beat_this.inference import File2Beats

    os.makedirs(OUT, exist_ok=True)
    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    rows = [json.loads(l) for l in open(fit_path) if l.strip()]
    rows = sorted([r for r in rows if "fit2" in r], key=lambda r: -r["fit2"])
    # selection: mostly real beats (groove >= 0.15) plus a few drumless "campfire" options,
    # skipping near-duplicates (same beat from two uploaders) by CLAP cosine > 0.97
    def emb(r):
        q = f"{ROOT}/work/catalog/analysis/clap/{safe_id(r['id'])}.npy"
        return np.load(q) if os.path.exists(q) else None
    picked, embs = [], []
    n_drumless = max(4, top_n // 8)
    for want_beat in (True, False):
        quota = top_n - n_drumless if want_beat else top_n - len(picked)
        for r in rows:
            if len([x for x in picked if (x.get("groove", 0) >= 0.15) == want_beat]) >= quota:
                break
            if (r.get("groove", 0) >= 0.15) != want_beat or r in picked:
                continue
            e = emb(r)
            if e is not None and any(float(e @ f) > 0.97 for f in embs):
                continue
            picked.append(r)
            if e is not None:
                embs.append(e)
    rows = picked
    jt, jpc, jw = juice_profiles()
    # baseline: same rendered-metric on the real Reine beat in its original alignment
    live_inst = mx.load(f"{ROOT}/work/stems/freestyle_fast/vocals_mel_band_roformer/instrumental.wav")
    b5 = rr.live_bar(rr.VOCAL_FROM_BAR)
    seg = live_inst[mx.sec(b5 - 2 * BAR):mx.sec(118)]
    y = librosa.resample(seg.mean(axis=1), orig_sr=mx.SR, target_sr=22050)
    c = librosa.feature.chroma_cqt(y=y, sr=22050, hop_length=512)
    c = c / (c.sum(axis=0, keepdims=True) + 1e-9)
    fr = np.clip(librosa.time_to_frames(jt - (b5 - 2 * BAR), sr=22050, hop_length=512), 0, c.shape[1] - 1)
    base = float((np.einsum("kn,nk->n", c[:, fr], WM[jpc]) * jw).sum() / jw.sum())
    print(f"rendered-metric baseline (Reine): {base:.4f}", flush=True)

    done = set()
    out_jsonl = f"{OUT}/previews.jsonl"
    if os.path.exists(out_jsonl):
        done = {json.loads(l)["id"] for l in open(out_jsonl) if l.strip()}
    for n, r in enumerate(rows):
        if r["id"] in done:
            continue
        try:
            beats = cand_beats(f2b, r["clip_path"])
            n_loop = ((len(beats) - 1) // 4) * 4
            loop, loop_dur = tiled_loop(r["clip_path"], beats, n_loop)
            orig_bar = loop_dur / (n_loop / 4)
            o = int(r["offset_beats"])
            # fit_detailed: Juice beat j (from j0 = beat of 14.5 s) <-> loop beat (j - j0 + o) mod n_loop.
            j0 = int(np.floor((14.5 - BAR1) / BEAT))
            j_bar5 = int(round((b5 - BAR1) / BEAT))        # beat index of live bar 5
            anchor_beat = (j_bar5 - j0 + o) % n_loop + 2 * n_loop   # in the tiled loop (3rd tile)
            anchor_t = anchor_beat * (orig_bar / 4)
            tmp = f"{OUT}/_loop.wav"
            mx.save(tmp, loop)
            spec = {"out": f"{OUT}/{n:02d}_{safe(r['id'])}.wav", "beat": tmp, "beat_downbeat": anchor_t,
                    "beat_bar_len": orig_bar, "transpose": int(r["transpose"]), "start_bar": -2, "intro_bars": 2,
                    "loop": None, "outro_bars": 2, "vocal": vocals, "vocal_rel_lu": 1.5, "hook": None,
                    "intro_lowpass": False, "target_lufs": -11.0}
            # stretch once (fast engine), build bed + vocal track, measure, then mix and master
            beat = mx.stretch(mx.load(tmp), orig_bar / BAR, spec["transpose"], fast=True)
            bed, _ = rr.build_bed(beat, anchor_t / (orig_bar / BAR), BAR, -2, 2 + 44 + 2, None)
            voc = mx.load(vocals)[mx.sec(b5):mx.sec(117.75)]
            vt = mx.place(np.zeros_like(bed), voc, mx.sec(2 * BAR))[:len(bed)]
            hr, mask = rendered_metrics(bed, vt, 2 * BAR, jt, jpc, jw, base)
            vproc = mx.vocal_chain(vt, mx.SR, bpm=60 / BEAT)
            bproc = mx.beat_chain(bed, mx.SR)
            s0, s1 = mx.sec(2 * BAR), mx.sec(2 * BAR) + len(voc)
            g = 10 ** ((spec["vocal_rel_lu"] - (mx.lufs(vproc[s0:s1]) - mx.lufs(bproc[s0:s1]))) / 20)
            mix = bproc + vproc * g
            nf = mx.sec(2 * BAR)
            mix[-nf:] *= mx.fade(nf, "out", "linear")
            y = mx.master(mix, mx.SR, target_lufs=spec["target_lufs"], ceiling_db=-1.0, max_iter=2)
            mx.save(spec["out"], y)
            import subprocess
            subprocess.run([sys.executable, f"{ROOT}/pipeline/qa.py", spec["out"], "--json", spec["out"][:-4] + ".qa.json",
                            "--png", spec["out"][:-4] + ".qa.png"], check=False, stdout=subprocess.DEVNULL)
            res = {**r, "preview": spec["out"], "harmonic_ratio_rendered": round(hr, 3), "masking_db": round(mask, 2),
                   "preview_lufs": round(mx.lufs(y), 2), "orig_bar_len": round(orig_bar, 4), "anchor_t": round(anchor_t, 4)}
        except Exception as e:
            res = {**r, "preview_error": f"{type(e).__name__}: {str(e)[:160]}"}
        with open(out_jsonl, "a") as fo:
            fo.write(json.dumps(res) + "\n")
        print(f"{n:02d} {res.get('harmonic_ratio_rendered')} mask={res.get('masking_db')} {r.get('artist')} - {r.get('title')}"[:150], flush=True)


if __name__ == "__main__":
    main()
