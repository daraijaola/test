#!/usr/bin/env python3
"""Arrange and mix the full song from stems on the live 100.45 BPM bar grid (a small DAW session in JSON).

Every source lives on the live freestyle's timeline (bar k downbeat = LIVE_BAR1 + (k-1)*LIVE_BAR), so a clip
is "copy source bar A.. to output bar B..": the hook can repeat, the guest verse (pre-rendered onto the grid)
can land anywhere, and the beat is re-ordered in whole Reine bars (a 2-bar chord loop, so odd<-odd keeps
the harmony). Order of work:
  1. beat bed from [out_bar, n_bars, src_bar] segments (n = 0: to the end of the outro), 12 ms crossfades at
     jumps, optional beat splices and low-pass dips (the classic filter dip before a new verse)
  2. vocal tracks: clips of pre-processed (tuned/EQ'd/compressed) dry stems, with short fades
  3. per-track levels: LU over the beat per block of bars (Juice's verse can copy the Extended Cut's own
     voice/beat balance block by block), smoothed 0.3 s ramps; "level_after_bus": N re-measures the finished
     vocal (returns + bus) N times and corrects each block, so the targets hold on the wet vocal
  4. time effects AFTER arranging, so tails run across clip edges: plate, tempo delays, slap; send
     automation for word throws; a track's returns can duck under another track (Juice's tails under Dave)
  5. vocal bus (light glue compression, parallel saturation), beat + vocals, master to a loudness that keeps
     the opening at the Extended Cut's level, QA.

Usage: song_build.py SONG.json
"""
import json
import os
import subprocess
import sys

import numpy as np
from pedalboard import Compressor, Delay, Distortion, Pedalboard, Reverb
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402

SR = mx.SR
BEAT = LIVE_BAR / 4


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def at(bar, beat=0.0):
    return live_bar(bar) + beat * BEAT


def band(x, lo=None, hi=None, order=4):
    if lo and hi:
        sos = butter(order, [lo, hi], "band", fs=SR, output="sos")
    elif lo:
        sos = butter(order, lo, "high", fs=SR, output="sos")
    else:
        sos = butter(order, hi, "low", fs=SR, output="sos")
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def fit(x, n):
    return x[:n] if len(x) >= n else np.concatenate([x, np.zeros((n - len(x),) + x.shape[1:], np.float32)])


# ---------------------------------------------------------------- 1. beat
def build_bed(src, bed, end_src_s, n_out, xf_s=0.012):
    out = np.zeros((n_out, 2), np.float32)
    xf = mx.sec(xf_s)
    prev = None
    for ob, n, sb in bed:
        o0, s0 = mx.sec(live_bar(ob)), mx.sec(live_bar(sb))
        length = (mx.sec(end_src_s) - s0) if n == 0 else (mx.sec(live_bar(ob + n)) - o0)
        seg = src[s0:s0 + length].copy()
        if prev is not None and s0 != prev:
            seg[:xf] = src[prev:prev + xf] * mx.fade(xf, "out") + seg[:xf] * mx.fade(xf, "in")
        out[o0:o0 + len(seg)] = seg[:max(0, min(len(seg), n_out - o0))]
        prev = s0 + length
    return out


def splice(track, src, splices, xf_s=0.012):
    xf = mx.sec(xf_s)
    for ob, obt, n, sb, sbt in splices:
        o0, o1 = mx.sec(at(ob, obt)), mx.sec(at(ob, obt + n))
        seg = src[mx.sec(at(sb, sbt)):][:o1 - o0].copy()
        seg[:xf] = track[o0:o0 + xf] * mx.fade(xf, "out") + seg[:xf] * mx.fade(xf, "in")
        seg[-xf:] = seg[-xf:] * mx.fade(xf, "out") + track[o1 - xf:o1] * mx.fade(xf, "in")
        track[o0:o1] = seg
    return track


def lowpass_dip(x, t0, t1, f_from=16000.0, f_to=400.0, release_s=0.01):
    """Cutoff sweeps (log) from f_from at t0 to f_to at t1, then snaps back open over release_s."""
    cut = [18000, 9000, 4500, 2200, 1100, 600, 320, 180]
    a0, a1 = mx.sec(t0), mx.sec(t1 + release_s)
    seg = x[a0:a1]
    renders = [seg] + [band(seg, hi=c) for c in cut[1:]]
    lf = np.log(np.array(cut, float))
    n = len(seg)
    t = np.arange(n) / SR
    span = t1 - t0
    f = np.where(t <= span, np.exp(np.log(f_from) + (np.log(f_to) - np.log(f_from)) * np.clip(t / max(span, 1e-6), 0, 1)),
                 np.exp(np.log(f_to) + (np.log(cut[0]) - np.log(f_to)) * np.clip((t - span) / release_s, 0, 1)))
    pos = np.interp(-np.log(f), -lf, np.arange(len(cut)))           # fractional index into the render list
    i0 = np.clip(np.floor(pos).astype(int), 0, len(cut) - 1)
    i1 = np.clip(i0 + 1, 0, len(cut) - 1)
    w = (pos - i0)[:, None].astype(np.float32)
    stack = np.stack(renders)                                       # (k, n, 2)
    y = stack[i0, np.arange(n)] * (1 - w) + stack[i1, np.arange(n)] * w
    x = x.copy()
    x[a0:a1] = y
    return x


# ---------------------------------------------------------------- 2-3. vocals
def place_clips(src, clips, n_out):
    out = np.zeros((n_out, 2), np.float32)
    for c in clips:
        s0, s1 = mx.sec(c["src_from_s"]), mx.sec(c["src_to_s"])
        seg = src[s0:s1].copy()
        fi, fo = mx.sec(c.get("fade_in_s", 0.015)), mx.sec(c.get("fade_out_s", 0.06))
        seg[:fi] *= mx.fade(fi, "in")
        seg[-fo:] *= mx.fade(fo, "out")
        o0 = mx.sec(live_bar(c["out_bar"]) + (c["src_from_s"] - live_bar(c["src_bar"])))
        seg *= 10 ** (c.get("gain_db", 0.0) / 20)
        e = min(n_out, o0 + len(seg))
        out[o0:e] += seg[:e - o0]
    return out


def level_curve(vox, beat, blocks, n_out, ramp_s=0.3):
    """Gain (dB) per sample so that LUFS(vox) - LUFS(beat) hits each block's target; 0 dB outside blocks."""
    g = np.full(n_out, np.nan)
    report = []
    for b0, b1, target in blocks:
        i0, i1 = mx.sec(live_bar(b0)), mx.sec(live_bar(b1))
        v = vox[i0:i1]
        act = np.abs(v).max(axis=1) > 1e-4
        if act.sum() < SR:                     # nothing (or under 1 s) sung in this block
            continue
        d = target - (mx.lufs(v) - mx.lufs(beat[i0:i1]))
        g[i0:i1] = d
        report.append([b0, b1, target, round(d, 2)])
    if np.all(np.isnan(g)):
        return np.zeros(n_out), report
    idx = np.where(~np.isnan(g))[0]
    g = np.interp(np.arange(n_out), idx, g[idx])                   # hold the nearest block outside them
    return uniform_filter1d(g, mx.sec(ramp_s), mode="nearest"), report


def env_follow(x, attack_s=0.005, release_s=0.25):
    m = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    e = uniform_filter1d(m.astype(np.float64), mx.sec(attack_s))
    # release: running max over the release window, then smooth
    from scipy.ndimage import maximum_filter1d
    e = maximum_filter1d(e, mx.sec(release_s))
    return uniform_filter1d(e, mx.sec(release_s / 2))


def send_automation(n_out, base_db, throws, duck=None, duck_db=0.0):
    a = np.full(n_out, base_db, np.float64)
    for th in throws:
        i0, i1 = mx.sec(th["at_s"]), mx.sec(th["at_s"] + th.get("dur_s", 0.6))
        a[i0:i1] = np.maximum(a[i0:i1], th["send_db"])
    a = uniform_filter1d(a, mx.sec(0.03), mode="nearest")
    if duck is not None:
        a = a - duck_db * duck
    return (10 ** (a / 20)).astype(np.float32)


def time_fx(dry, fx, bpm, n_out, duck_env=None):
    """Plate / tempo delay / slap returns of an arranged dry track (stereo)."""
    mono = dry.mean(axis=1).astype(np.float32)
    out = np.zeros((n_out, 2), np.float32)
    q = 60.0 / bpm
    duck = None
    if duck_env is not None and fx.get("duck_db"):
        duck = np.clip(duck_env / (np.percentile(duck_env[duck_env > 1e-4], 90) + 1e-9), 0, 1) if np.any(duck_env > 1e-4) else None
    if "plate" in fx:
        p = fx["plate"]
        snd = mono * send_automation(n_out, p["send_db"], p.get("throws", []))
        snd = np.concatenate([np.zeros(mx.sec(p.get("predelay_ms", 30) / 1000), np.float32), snd])[:n_out]
        snd = band(snd, lo=p.get("hp", 300))
        rv = Pedalboard([Reverb(room_size=p.get("room", 0.42), damping=p.get("damping", 0.6), wet_level=1.0,
                                dry_level=0.0, width=1.0)])(np.stack([snd, snd]), SR).T
        out += band(rv, hi=p.get("lp", 7000))
    if "delay" in fx:
        d = fx["delay"]
        snd = mono * send_automation(n_out, d["send_db"], d.get("throws", []))
        taps = []
        for frac in d.get("beats", [1.0, 0.75]):
            e = Pedalboard([Delay(delay_seconds=frac * q, feedback=d.get("feedback", 0.22), mix=1.0)])(snd[None, :], SR)[0]
            taps.append(band(e, lo=d.get("hp", 350), hi=d.get("lp", 4500)))
        if len(taps) == 1:
            taps = taps * 2
        out += np.stack(taps[:2], axis=1)
    if "slap" in fx:
        s = fx["slap"]
        snd = mono * send_automation(n_out, s["send_db"], s.get("throws", []))
        e = np.concatenate([np.zeros(mx.sec(s.get("ms", 80) / 1000), np.float32), snd])[:n_out]
        e = band(e, lo=s.get("hp", 300), hi=s.get("lp", 5000))
        out += np.stack([e, e], axis=1)
    if duck is not None:
        # duck the RETURNS (a sidechained delay/reverb): ducking the send would leave the echoes of words sung
        # before the other voice comes in running over its first words
        out *= (10 ** (-fx["duck_db"] * duck / 20))[:, None].astype(np.float32)
    return out


def vocal_bus(x, cfg):
    if not cfg:
        return x
    y = x
    if cfg.get("comp_ratio"):
        act = np.abs(x).max(axis=1)
        lvl = 20 * np.log10(np.percentile(act[act > 1e-4], 90) + 1e-9) if np.any(act > 1e-4) else -20
        y = Pedalboard([Compressor(threshold_db=lvl + cfg.get("comp_thresh_rel_db", -6.0), ratio=cfg["comp_ratio"],
                                   attack_ms=cfg.get("attack_ms", 20), release_ms=cfg.get("release_ms", 120))])(x, SR)
    if cfg.get("sat_mix"):
        sat = Pedalboard([Distortion(drive_db=cfg.get("sat_drive_db", 8))])(y * 0.5, SR)
        sat = band(sat, lo=200, hi=8000)
        y = y + cfg["sat_mix"] * sat * (np.abs(y).max() / (np.abs(sat).max() + 1e-9))
    return y.astype(np.float32)


# ---------------------------------------------------------------- main
def main():
    song = json.load(open(sys.argv[1]))
    beat_src = mx.load(song["beat"])
    end_src = song.get("song_end_src_s", 196.5)
    last = song["bed"][-1]
    out_end = live_bar(last[0]) + (end_src - live_bar(last[2]))
    n_out = mx.sec(out_end) + mx.sec(4.0)
    beat = build_bed(beat_src, song["bed"], end_src, n_out)
    if song.get("beat_splices"):
        beat = splice(beat, beat_src, song["beat_splices"])
    for d in song.get("beat_fx", []):
        if d["type"] == "lowpass_dip":
            beat = lowpass_dip(beat, at(*d["from"]), at(*d["to"]), d.get("f_from", 16000), d.get("f_to", 400))
    beat *= 10 ** (song.get("beat_gain_db", 0.0) / 20)

    bpm = 60.0 / BEAT
    tracks, placed, reports, curves = {}, {}, {}, {}
    for tr in song["vocals"]:
        placed[tr["name"]] = place_clips(mx.load(tr["src"]), tr["clips"], n_out)
        tracks[tr["name"]] = tr
        if tr.get("link_to"):                  # e.g. doubles ride with their lead, at a fixed offset (gain_db)
            curves[tr["name"]], reports[tr["name"]] = None, "linked to " + tr["link_to"]
        else:
            curves[tr["name"]], reports[tr["name"]] = level_curve(placed[tr["name"]], beat, tr.get("level_blocks", []),
                                                                  n_out)

    def render_vox():
        dry_out = {}
        for name, tr in tracks.items():
            g = curves[tr["link_to"]] if tr.get("link_to") else curves[name]
            dry_out[name] = placed[name] * (10 ** ((g + tr.get("gain_db", 0.0)) / 20))[:, None].astype(np.float32)
        vox = np.zeros((n_out, 2), np.float32)
        for name, tr in tracks.items():
            duck_env = None
            if tr.get("fx", {}).get("duck_under"):
                duck_env = env_follow(dry_out[tr["fx"]["duck_under"]])
            vox += dry_out[name] + time_fx(dry_out[name], tr.get("fx", {}), bpm, n_out, duck_env)
        return vocal_bus(vox, song.get("vocal_bus")), dry_out

    vox, dry_out = render_vox()
    # level_blocks measure the dry track; with "level_after_bus" the targets are met on the finished vocal
    # (FX returns and bus compression included), as the Extended Cut's own balance was measured on a wet stem
    for _ in range(song.get("level_after_bus", 0)):
        for name, tr in tracks.items():
            for b0, b1, target in ([] if tr.get("link_to") else tr.get("level_blocks", [])):
                i0, i1 = mx.sec(live_bar(b0)), mx.sec(live_bar(b1))
                if np.sum(np.abs(dry_out[name][i0:i1]).max(axis=1) > 1e-4) < SR:
                    continue
                err = target - (mx.lufs(vox[i0:i1]) - mx.lufs(beat[i0:i1]))
                ramp = np.zeros(n_out)
                ramp[i0:i1] = err
                curves[name] = curves[name] + uniform_filter1d(ramp, mx.sec(0.3), mode="constant")
        vox, dry_out = render_vox()
    after = {}
    for name, tr in tracks.items():
        if not tr.get("link_to") and tr.get("level_blocks"):
            after[name] = [[b0, b1, t, round(mx.lufs(vox[mx.sec(live_bar(b0)):mx.sec(live_bar(b1))]) -
                                             mx.lufs(beat[mx.sec(live_bar(b0)):mx.sec(live_bar(b1))]), 2)]
                           for b0, b1, t in tr["level_blocks"]]
    mix = beat + vox

    start = song.get("start_s", 12.7387)
    seg = mix[mx.sec(start):mx.sec(out_end)].copy()
    seg[:mx.sec(0.004)] *= mx.fade(mx.sec(0.004), "in")
    target = song.get("target_lufs", -11.0)
    y = mx.master(seg, SR, target_lufs=target, ceiling_db=-1.0)
    if song.get("match_opening_to"):
        ref = mx.load(song["match_opening_to"])
        j1 = mx.sec(live_bar(song.get("opening_end_bar", 49)) - start)
        want = mx.lufs(ref[:j1])
        for _ in range(4):
            dlt = want - mx.lufs(y[:j1])
            if abs(dlt) < 0.05:
                break
            target += dlt
            y = mx.master(seg, SR, target_lufs=target, ceiling_db=-1.0)
    os.makedirs(os.path.dirname(song["out"]), exist_ok=True)
    mx.save(song["out"], y)
    if song.get("save_stems"):
        for name, x in [("beat", beat), ("vox", vox)] + list(dry_out.items()):
            mx.save(song["out"][:-4] + f".stem_{name}.wav", x[mx.sec(start):mx.sec(out_end)])
    edits = sorted({round(live_bar(b[0]) - start, 3) for b in song["bed"]} |
                   {round(live_bar(c["out_bar"]) - start, 3) for tr in song["vocals"] for c in tr["clips"]})
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), song["out"], "--edits",
                    ",".join(f"{e:.3f}" for e in edits if e > 0), "--json", song["out"][:-4] + ".qa.json",
                    "--png", song["out"][:-4] + ".qa.png"], check=False, stdout=subprocess.DEVNULL)
    sections = {}
    for name, (b0, b1) in song.get("report_sections", {}).items():
        sections[name] = round(mx.lufs(y[mx.sec(live_bar(b0) - start):mx.sec(live_bar(b1) - start)]), 2)
    print(json.dumps({"out": song["out"], "duration": round(len(y) / SR, 2), "lufs": round(mx.lufs(y), 2),
                      "true_peak": round(mx.true_peak_db(y), 2), "master_target": round(target, 2),
                      "section_lufs": sections, "level_blocks": reports, "wet_vox_over_beat": after}))


if __name__ == "__main__":
    main()
