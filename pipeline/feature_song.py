#!/usr/bin/env python3
"""Juice WRLD x <guest>: the "Extended Cut - Live" song with a real guest verse after Juice's verse.

The base is rebuilt exactly like build_extended.py's version A (bit-exact without a guest): clean intro bar,
untouched Mouv' mix, phase-matched hand-off to the studio "Reine" instrumental. After Juice's last bar the
studio instrumental can be re-ordered in whole bars (Reine is a 2-bar loop, so any jump that keeps the bar
parity is seamless). The guest's isolated verse, taken from one of the guest's own songs, is stretched to
the live tempo with Rubber Band R3 (formant-preserving) and placed so that its bar 1 lands on a chosen
output bar. It is lightly processed and set to Juice's own vocal level, so the voice/beat balance follows
the live part. The beat is never ducked.

Spec (JSON):
{
  "out": "work/renders/feature/juice_x_guest.wav",
  "base_config": "work/renders/extended/config.json",
  "cont": [[49, 16, 57], [65, 0, 73]],   # [output bar, n bars, studio bar]; n = 0 means "to the song end"
  "guest_acapella": "work/feature/x/vocals.wav", "guest_offset_s": 0.0,   # acapella t=0 on the source timeline
  "guest_period": 0.6012,                # source beat period (s); bars = 4 beats
  "guest_bar1": 41.234,                  # source time of the verse's bar-1 downbeat
  "guest_bars": 16, "guest_pickup_s": 0.4, "guest_tail_s": 0.6,
  "land_bar": 49,                        # output bar the verse's bar 1 lands on
  "transpose": 0, "guest_rel_db": -0.5, "target_lufs": -12.0
}
Usage: feature_song.py SPEC.json
"""
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_extended as be  # noqa: E402
import mixlib as mx  # noqa: E402
from remix_render import LIVE_BAR, LIVE_BAR1  # noqa: E402

JUICE_LAST_BAR = 48   # Juice's verse ends on the last beat of live bar 48 (end of chorus 2)


def live_bar(k):
    return LIVE_BAR1 + (k - 1) * LIVE_BAR


def rearrange(st, cont, song_end, xf_s=0.012):
    """Studio instrumental up to the end of Juice's last bar, then the `cont` bar plan. Returns (track, end_s)."""
    sr = mx.SR
    cut = mx.sec(live_bar(JUICE_LAST_BAR + 1))
    parts, out_end, prev_src_end = [st[:cut]], cut, cut
    xf = mx.sec(xf_s)
    for out_bar, n, src_bar in cont:
        o = mx.sec(live_bar(out_bar))
        if o != out_end:
            raise SystemExit(f"cont plan has a gap/overlap at output bar {out_bar}")
        s0 = mx.sec(live_bar(src_bar))
        s1 = mx.sec(song_end) if n == 0 else mx.sec(live_bar(src_bar + n))
        seg = st[s0:s1].copy()
        if s0 != prev_src_end:                       # a jump: crossfade from the natural continuation
            nat = st[prev_src_end:prev_src_end + xf]
            seg[:xf] = nat * mx.fade(xf, "out") + seg[:xf] * mx.fade(xf, "in")
        parts.append(seg)
        out_end += len(seg)
        prev_src_end = s1
    return np.concatenate(parts), out_end / sr


def base_mix(cfg, cont=None):
    """Version A pre-master mix on the live timeline (same steps as build_extended.py), optionally re-ordered
    after Juice's verse. Returns (mix, beat_only, juice_vocal_lufs, juice_vocal_minus_beat_lu, end_s)."""
    sr = mx.SR
    live_mix, live_voc, live_inst = mx.load(cfg["live_mix"]), mx.load(cfg["live_vocals"]), mx.load(cfg["live_inst"])
    st_inst = mx.load(cfg["studio_inst_live"])
    n = len(st_inst)
    pad = lambda x: np.concatenate([x, np.zeros((max(0, n - len(x)), 2), np.float32)])[:n]
    live_mix, live_voc, live_inst, st_inst = map(pad, (live_mix, live_voc, live_inst, st_inst))
    r0, r1 = (mx.sec(t) for t in cfg["match_ref"])
    taps, _ = be.match_eq(st_inst[r0:r1], live_inst[r0:r1], sr)
    st = be.apply_fir(st_inst, taps)
    st = be.delay_bass(st, sr, cfg.get("handoff_bass_delay_ms", 0.0))
    st *= 10 ** (be.loudness_gain(st[r0:r1], live_inst[r0:r1], sr) / 20)
    end_s = cfg["song_end"]
    if cont:
        st, end_s = rearrange(st, cont, cfg["song_end"])
        n = len(st)
        live_mix, live_voc, live_inst = (np.concatenate([x, np.zeros((max(0, n - len(x)), 2), np.float32)])[:n]
                                         for x in (live_mix, live_voc, live_inst))

    def ramp(t0, t1):
        g = np.zeros(n, np.float32)
        i0, i1 = mx.sec(t0), mx.sec(t1)
        g[i1:] = 1
        g[i0:i1] = np.linspace(0, 1, i1 - i0)
        return g[:, None]

    sw, hand, xf, je = cfg["intro_switch"], cfg["handoff"], cfg["handoff_xfade"], cfg["juice_end"]
    w_intro = 1 - ramp(sw - 0.03, sw + 0.03)
    w_studio = ramp(hand - xf / 2, hand + xf / 2)
    w_live = (1 - w_intro) * (1 - w_studio)
    tail = mx.apply_mask(live_voc, [(0, hand - xf / 2), (je + 0.02, n / sr)], fade_s=0.04)
    beat_only = live_inst * (1 - w_studio) + st * w_studio
    a = live_inst * w_intro + live_mix * w_live + st * w_studio + tail * w_studio
    j0, j1 = mx.sec(live_bar(6)), mx.sec(live_bar(JUICE_LAST_BAR + 1))
    juice_lufs = mx.lufs(live_voc[j0:j1])
    juice_rel = juice_lufs - mx.lufs(live_inst[j0:j1])
    return a, beat_only, juice_lufs, juice_rel, end_s


def guest_track(spec, n_out, sr=mx.SR):
    """Stretched, placed guest verse on the output timeline. Returns (track, start_s, bar1_s, end_s, rate)."""
    g = mx.load(spec["guest_acapella"])
    off = spec.get("guest_offset_s", 0.0)
    src_bar = 4 * spec["guest_period"]
    pick, tail = spec.get("guest_pickup_s", 0.0), spec.get("guest_tail_s", 0.6)
    s0 = spec["guest_bar1"] - pick - off
    s1 = spec["guest_bar1"] + spec["guest_bars"] * src_bar + tail - off
    seg = g[max(0, mx.sec(s0)):mx.sec(s1)].copy()
    rate = src_bar / LIVE_BAR                                   # >1 = the verse is sped up to the live tempo
    seg = mx.stretch(seg, rate, spec.get("transpose", 0), vocal=True)
    fi, fo = mx.sec(spec.get("fade_in_s", 0.02)), mx.sec(spec.get("fade_out_s", 0.3))
    seg[:fi] *= mx.fade(fi, "in")
    seg[-fo:] *= mx.fade(fo, "out")
    bar1 = live_bar(spec["land_bar"])
    at = bar1 - pick / rate
    trk = mx.place(np.zeros((n_out, 2), np.float32), seg, mx.sec(at))[:n_out]
    for m0, m1 in spec.get("guest_mute", []):                  # optional: drop words/ad-libs (source seconds)
        a0, a1 = bar1 + (m0 - spec["guest_bar1"]) / rate, bar1 + (m1 - spec["guest_bar1"]) / rate
        trk = mx.apply_mask(trk, [(a0, a1)], fade_s=0.02)
    return trk, at, bar1, at + len(seg) / sr, rate


def main():
    spec = json.load(open(sys.argv[1]))
    cfg = json.load(open(spec.get("base_config", "work/renders/extended/config.json")))
    sr = mx.SR
    a, beat_only, juice_lufs, juice_rel, end_s = base_mix(cfg, spec.get("cont"))
    trk, at, bar1, g_end, rate = guest_track(spec, len(a))
    if at < cfg["juice_end"] + 0.05:
        raise SystemExit(f"guest pickup would overlap Juice's last word (starts {at:.2f}s < {cfg['juice_end'] + 0.05:.2f}s)")
    # light processing: the isolated studio vocal already carries its own production
    gp = mx.vocal_chain(trk, sr, presence_db=spec.get("presence_db", 0.5), air_db=spec.get("air_db", 0.5),
                        comp_thresh=spec.get("comp_thresh", -22), reverb_wet=spec.get("reverb_wet", 0.06),
                        delay_wet=spec.get("delay_wet", 0.02), bpm=60 / (LIVE_BAR / 4))
    i0, i1 = mx.sec(bar1), mx.sec(min(g_end, bar1 + spec["guest_bars"] * LIVE_BAR))
    gain_db = (juice_lufs + spec.get("guest_rel_db", -0.5)) - mx.lufs(gp[i0:i1])
    gp *= 10 ** (gain_db / 20)
    rel_now = mx.lufs(gp[i0:i1]) - mx.lufs(beat_only[i0:i1])
    mix = a + gp
    b5 = cfg["bar5"]
    seg_out = mix[mx.sec(b5):mx.sec(end_s)].copy()
    seg_out[:mx.sec(0.004)] *= mx.fade(mx.sec(0.004), "in")
    y = mx.master(seg_out, sr, target_lufs=spec.get("target_lufs", cfg.get("target_lufs", -12.0)), ceiling_db=-1.0)
    os.makedirs(os.path.dirname(spec["out"]), exist_ok=True)
    mx.save(spec["out"], y)
    jumps = [live_bar(c[0]) - b5 for c in spec.get("cont", [])]
    edits = sorted([cfg["handoff"] - b5, at - b5, bar1 - b5] + jumps)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "qa.py"), spec["out"], "--edits",
                    ",".join(f"{e:.3f}" for e in edits), "--json", spec["out"][:-4] + ".qa.json",
                    "--png", spec["out"][:-4] + ".qa.png"], check=False, stdout=subprocess.DEVNULL)
    print(json.dumps({"out": spec["out"], "duration": round(len(y) / sr, 2), "lufs": round(mx.lufs(y), 2),
                      "true_peak": round(mx.true_peak_db(y), 2), "stretch_rate": round(rate, 4),
                      "guest_in_out_s": round(at - b5, 2), "guest_bar1_out_s": round(bar1 - b5, 2),
                      "guest_end_out_s": round(g_end - b5, 2), "guest_gain_db": round(gain_db, 2),
                      "juice_vocal_minus_beat_LU": round(juice_rel, 2), "guest_vocal_minus_beat_LU": round(rel_now, 2)}))


if __name__ == "__main__":
    main()
