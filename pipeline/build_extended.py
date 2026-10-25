#!/usr/bin/env python3
"""Build the three "Extended Cut" versions on the live timeline.

Inputs (config JSON):
  live_mix, live_vocals, live_inst      : the Mouv' master and its best stems (live timeline)
  studio_inst_live, studio_full_live    : studio instrumental / full mix rendered onto the live
                                          timeline with studio_to_live.py
  bar5, bar6, bar_len                   : live times of song bar 5 (verse 1 drop) and bar 6, bar length
  intro_switch                          : live time between the end of the DJ's sung tag and Juice's
                                          first hum, where the cleaned intro hands over to the real mix
  juice_end                             : end of Juice's last word (live s)
  handoff                               : live time where the live beat hands over to studio
  handoff_xfade                         : crossfade length (s), linear (correlated material)
  handoff_bass_delay_ms                 : delay applied to the studio's <180 Hz band so its 808 is in phase
                                          with the live 808 at the hand-off
  match_ref                             : [start, end] live-time window used for loudness/EQ match
  song_end                              : live time where the studio song ends
  dadju_switch                          : live time (a beat, before Dadju's bridge-half pickup) where the
                                          continuation switches from instrumental to the full song
  out_dir
Versions:
  A  live      : clean intro bar (live instrumental stem) -> untouched Mouv' mix -> studio instrumental
  B  studio    : Juice's isolated vocal over the studio instrumental for the whole song
  C  dadju     : like A, but the continuation is the original song with Dadju's vocals

Usage: build_extended.py CONFIG.json
"""
import json
import os
import subprocess
import sys

import numpy as np
from scipy.signal import butter, fftconvolve, firwin2, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402


def band_levels(x, sr, lo, hi, n_bands=30):
    """Long-term average spectrum in log-spaced bands (dB)."""
    mono = x.mean(axis=1)
    n = 8192
    frames = np.lib.stride_tricks.sliding_window_view(mono, n)[::n // 2] * np.hanning(n)
    spec = np.mean(np.abs(np.fft.rfft(frames, axis=1)) ** 2, axis=0)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    edges = np.geomspace(lo, hi, n_bands + 1)
    centers = np.sqrt(edges[:-1] * edges[1:])
    lv = np.array([10 * np.log10(spec[(freqs >= a) & (freqs < b)].mean() + 1e-20) for a, b in zip(edges[:-1], edges[1:])])
    return centers, lv


def match_eq(src, ref, sr, max_db=6.0):
    """Linear-phase FIR that moves src's long-term spectrum toward ref's (smoothed, clamped)."""
    c, ls = band_levels(src, sr, 40, 16000)
    _, lr = band_levels(ref, sr, 40, 16000)
    diff = lr - ls
    diff -= np.median(diff)  # tone only; loudness is matched separately
    diff = np.convolve(np.pad(diff, 2, mode="edge"), np.ones(5) / 5, mode="valid")  # smooth
    diff = np.clip(diff, -max_db, max_db)
    f = np.concatenate([[0], c, [sr / 2]]) / (sr / 2)
    g = 10 ** (np.concatenate([[diff[0]], diff, [diff[-1]]]) / 20)
    taps = firwin2(4097, f, g)
    return taps, dict(zip([round(float(x)) for x in c], [round(float(d), 2) for d in diff]))


def apply_fir(x, taps):
    y = np.stack([fftconvolve(x[:, ch], taps, mode="same") for ch in range(x.shape[1])], axis=1)
    return y.astype(np.float32)


def delay_bass(x, sr, delay_ms, split_hz=180.0):
    """Delay only the band below split_hz (zero-phase split, low + (x - low) reconstructs x exactly).
    Used to bring the studio 808 into phase with the DJ's time-stretched 808 at the hand-off, which
    otherwise cancels (measured correlation -0.63 at 0 ms, +0.60 at +4.78 ms)."""
    if not delay_ms:
        return x
    sos = butter(4, split_hz, btype="low", fs=sr, output="sos")
    low = sosfiltfilt(sos, x, axis=0).astype(np.float32)
    high = x - low
    d = int(round(delay_ms * 1e-3 * sr))
    low = np.concatenate([np.zeros((d, x.shape[1]), np.float32), low[:-d]]) if d > 0 else low
    return high + low


def loudness_gain(src, ref, sr):
    return mx.lufs(ref, sr) - mx.lufs(src, sr)


def main():
    cfg = json.load(open(sys.argv[1]))
    sr = mx.SR
    out_dir = cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    live_mix, live_voc, live_inst = mx.load(cfg["live_mix"]), mx.load(cfg["live_vocals"]), mx.load(cfg["live_inst"])
    st_inst, st_full = mx.load(cfg["studio_inst_live"]), mx.load(cfg["studio_full_live"])
    n = max(len(st_inst), len(st_full))
    pad = lambda x: np.concatenate([x, np.zeros((max(0, n - len(x)), 2), np.float32)])[:n]
    live_mix, live_voc, live_inst, st_inst, st_full = map(pad, (live_mix, live_voc, live_inst, st_inst, st_full))

    b5, b6, juice_end = cfg["bar5"], cfg["bar6"], cfg["juice_end"]
    hand, xf = cfg["handoff"], cfg["handoff_xfade"]
    song_end = cfg["song_end"]
    r0, r1 = (mx.sec(t) for t in cfg["match_ref"])

    # ---- tone + level match of the studio material to the live beat (same musical section)
    taps, eq_curve = match_eq(st_inst[r0:r1], live_inst[r0:r1], sr)
    st_inst_m = apply_fir(st_inst, taps)
    st_full_m = apply_fir(st_full, taps)
    bd = cfg.get("handoff_bass_delay_ms", 0.0)
    st_inst_m = delay_bass(st_inst_m, sr, bd)
    st_full_m = delay_bass(st_full_m, sr, bd)
    g_inst = loudness_gain(st_inst_m[r0:r1], live_inst[r0:r1], sr)
    st_inst_m *= 10 ** (g_inst / 20)
    st_full_m *= 10 ** (g_inst / 20)  # same gain: the vocals ride on the same beat level
    report = {"eq_match_db": eq_curve, "studio_gain_db": round(g_inst, 2), "handoff_bass_delay_ms": bd}

    def ramp(t0, t1, length):
        """Linear 0->1 gain curve between t0 and t1 over an array of `length` samples."""
        g = np.zeros(length, np.float32)
        i0, i1 = mx.sec(t0), mx.sec(t1)
        g[i1:] = 1
        g[i0:i1] = np.linspace(0, 1, i1 - i0)
        return g[:, None]

    # ---- A: live
    sw = cfg["intro_switch"]
    w_intro = 1 - ramp(sw - 0.03, sw + 0.03, n)                    # intro: live instrumental stem (DJ tag removed)
    w_studio = ramp(hand - xf / 2, hand + xf / 2, n)              # hand-off to studio
    w_live = (1 - w_intro) * (1 - w_studio)
    a = live_inst * w_intro + live_mix * w_live + st_inst_m * w_studio
    # Juice's final word continues over the studio beat after the hand-off (stem, faded at word end)
    tail = mx.apply_mask(live_voc, [(0, hand - xf / 2), (juice_end + 0.02, n / sr)], fade_s=0.04)
    a = a + tail * w_studio
    # ---- C: dadju (same, continuation = full original song)
    ds = cfg["dadju_switch"]
    w_full = ramp(ds - 0.05, ds + 0.05, n)
    cont = st_inst_m * (1 - w_full) + st_full_m * w_full
    c = live_inst * w_intro + live_mix * w_live + cont * w_studio + tail * w_studio
    # ---- B: studio rebuild (vocal stem over studio beat for the whole song)
    voc = mx.apply_mask(live_voc, [(0, sw), (juice_end + 0.02, n / sr)], fade_s=0.05)
    voc_p = mx.vocal_chain(voc, sr, presence_db=1.0, air_db=1.0, comp_thresh=-24, reverb_wet=0.10, delay_wet=0.03)
    # put the vocal at the same level relative to the beat as in the live mix
    v_ref = mx.lufs(live_voc[mx.sec(b6):mx.sec(juice_end)], sr) - mx.lufs(live_inst[mx.sec(b6):mx.sec(juice_end)], sr)
    v_now = mx.lufs(voc_p[mx.sec(b6):mx.sec(juice_end)], sr) - mx.lufs(st_inst[mx.sec(b6):mx.sec(juice_end)], sr)
    b = st_inst + voc_p * 10 ** ((v_ref - v_now + 0.5) / 20)
    report["studio_vocal_gain_db"] = round(v_ref - v_now + 0.5, 2)

    renders = {}
    for name, x in (("A_live", a), ("B_studio", b), ("C_dadju", c)):
        seg = x[mx.sec(b5):mx.sec(song_end)]
        seg[:mx.sec(0.004)] *= mx.fade(mx.sec(0.004), "in")
        y = mx.master(seg, sr, target_lufs=cfg.get("target_lufs", -10.5), ceiling_db=-1.0)
        path = os.path.join(out_dir, f"extended_{name}.wav")
        mx.save(path, y)
        renders[name] = {"path": path, "duration": round(len(y) / sr, 2), "lufs": round(mx.lufs(y, sr), 2),
                         "true_peak": round(mx.true_peak_db(y), 2)}
        edits = [sw - b5, hand - b5, juice_end - b5] + ([cfg["dadju_switch"] - b5] if name == "C_dadju" else [])
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), path,
                        "--edits", ",".join(f"{e:.3f}" for e in edits), "--json", path[:-4] + ".qa.json",
                        "--png", path[:-4] + ".qa.png"], check=False, stdout=subprocess.DEVNULL)
    report["renders"] = renders
    json.dump(report, open(os.path.join(out_dir, "extended_report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
