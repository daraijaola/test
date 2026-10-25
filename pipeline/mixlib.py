"""Shared mixing/mastering helpers for every render in this project.

All audio is float32, shape (n, 2), 44.1 kHz unless stated otherwise.
Open-source building blocks: Rubber Band (time/pitch), Spotify Pedalboard
(EQ/dynamics/reverb/limiting), pyloudnorm (ITU-R BS.1770 loudness).
"""
import numpy as np
import pyloudnorm as pyln
import pyrubberband as pyrb
import soundfile as sf
from pedalboard import (Compressor, Delay, HighpassFilter, HighShelfFilter,
                        LowpassFilter, LowShelfFilter, Pedalboard, PeakFilter, Reverb)
from numba import njit
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, resample_poly, sosfiltfilt

SR = 44100


# ---------------------------------------------------------------- I/O
def load(path, sr=SR):
    x, s = sf.read(path, always_2d=True, dtype="float32")
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if s != sr:
        x = resample_poly(x, sr, s, axis=0).astype(np.float32)
    return x


def save(path, x, sr=SR, subtype="FLOAT"):
    sf.write(path, np.asarray(x, dtype=np.float32), sr, subtype=subtype)


def sec(t, sr=SR):
    return int(round(t * sr))


# ---------------------------------------------------------------- editing
def fade(n, kind="in", curve="equal_power"):
    t = np.linspace(0, 1, n, dtype=np.float32)
    g = np.sin(t * np.pi / 2) if curve == "equal_power" else t
    return (g if kind == "in" else g[::-1])[:, None]


def crossfade(a, b, n, curve="equal_power"):
    """Join a and b, overlapping the last n samples of a with the first n of b."""
    if n <= 0:
        return np.concatenate([a, b])
    n = min(n, len(a), len(b))
    mid = a[-n:] * fade(n, "out", curve) + b[:n] * fade(n, "in", curve)
    return np.concatenate([a[:-n], mid, b[n:]])


def place(dst, src, at, gain=1.0):
    """Add src into dst starting at sample `at` (grows dst if needed)."""
    end = at + len(src)
    if end > len(dst):
        dst = np.concatenate([dst, np.zeros((end - len(dst), dst.shape[1]), np.float32)])
    dst[at:end] += src * gain
    return dst


def apply_mask(x, regions, fade_s=0.03, sr=SR):
    """Zero the given (start, end) second regions of x with short fades (for removing host speech)."""
    g = np.ones(len(x), np.float32)
    nf = sec(fade_s, sr)
    for s, e in regions:
        i0, i1 = max(0, sec(s, sr)), min(len(x), sec(e, sr))
        if i1 <= i0:
            continue
        g[i0:i1] = 0
        a = max(0, i0 - nf)
        g[a:i0] = np.minimum(g[a:i0], np.linspace(1, 0, i0 - a))
        b = min(len(x), i1 + nf)
        g[i1:b] = np.minimum(g[i1:b], np.linspace(0, 1, b - i1))
    return x * g[:, None]


# ---------------------------------------------------------------- time / pitch
def stretch(x, rate, semitones=0.0, vocal=False, sr=SR, fast=False):
    """Rubber Band R3 ('finer') engine; rate > 1 = faster. Formant-preserving for vocals.
    fast=True uses the quicker R2 engine (previews/screening only)."""
    if abs(rate - 1) < 1e-6 and abs(semitones) < 1e-6:
        return x
    args = {} if fast else {"-3": ""}
    if vocal:
        args["--formant"] = ""
    y = pyrb.time_stretch(x, sr, rate, rbargs=args) if abs(rate - 1) > 1e-6 else x
    if abs(semitones) > 1e-6:
        y = pyrb.pitch_shift(y, sr, semitones, rbargs=args)
    return y.astype(np.float32)


# ---------------------------------------------------------------- dynamics / tone
def deess(x, freq=6500, thresh_db=-28, ratio=4.0, sr=SR):
    """Split-band de-esser: compress only the band above `freq`."""
    sos = butter(4, freq, btype="high", fs=sr, output="sos")
    hi = sosfiltfilt(sos, x, axis=0).astype(np.float32)
    lo = x - hi
    comp = Pedalboard([Compressor(threshold_db=thresh_db, ratio=ratio, attack_ms=1.0, release_ms=60)])
    return lo + comp(hi, sr)


def vocal_chain(v, sr=SR, presence_db=2.5, air_db=2.0, comp_thresh=-20, reverb_wet=0.12,
                delay_wet=0.06, bpm=100.0):
    """Clean, modern rap/R&B vocal: HPF, mud cut, presence/air, de-ess, two-stage compression,
    plus tempo-synced slap/eighth delay and a small plate-like reverb on a parallel send."""
    dry = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=90),
        PeakFilter(cutoff_frequency_hz=280, gain_db=-2.5, q=1.0),
        PeakFilter(cutoff_frequency_hz=3200, gain_db=presence_db, q=0.9),
        HighShelfFilter(cutoff_frequency_hz=10000, gain_db=air_db, q=0.7),
        Compressor(threshold_db=comp_thresh, ratio=3.0, attack_ms=8, release_ms=120),
    ])(v, sr)
    dry = deess(dry, sr=sr)
    dry = Pedalboard([Compressor(threshold_db=comp_thresh + 6, ratio=2.0, attack_ms=20, release_ms=200)])(dry, sr)
    eighth = 60.0 / bpm / 2
    send_d = Pedalboard([HighpassFilter(cutoff_frequency_hz=300), LowpassFilter(cutoff_frequency_hz=6000),
                         Delay(delay_seconds=eighth, feedback=0.25, mix=1.0)])(dry, sr)
    send_r = Pedalboard([HighpassFilter(cutoff_frequency_hz=250),
                         Reverb(room_size=0.45, damping=0.55, wet_level=1.0, dry_level=0.0, width=1.0),
                         LowpassFilter(cutoff_frequency_hz=9000)])(dry, sr)
    return dry + delay_wet * send_d + reverb_wet * send_r


def beat_chain(b, sr=SR, vocal_pocket_db=-1.5):
    """Gentle carve of the 2-4 kHz vocal pocket so the voice sits on top of the beat."""
    return Pedalboard([PeakFilter(cutoff_frequency_hz=2800, gain_db=vocal_pocket_db, q=0.8)])(b, sr)


# ---------------------------------------------------------------- loudness / mastering
def lufs(x, sr=SR):
    return float(pyln.Meter(sr).integrated_loudness(x))


def true_peak_db(x):
    return float(20 * np.log10(np.max(np.abs(resample_poly(x, 4, 1, axis=0))) + 1e-12))


@njit(cache=True)
def _release(g, coef):
    out = np.empty_like(g)
    cur = g[0]
    for i in range(len(g)):
        if g[i] < cur:
            cur = g[i]  # attack is handled by the look-ahead ramp
        else:
            cur = g[i] + (cur - g[i]) * coef
        out[i] = cur
    return out


def limit(x, sr=SR, ceiling_db=-1.0, lookahead_ms=2.0, release_ms=80.0, os_factor=4):
    """Transparent look-ahead brickwall limiter on a 4x oversampled signal (true-peak aware).
    Gain = min required over a +/-L window, box-smoothed (so it ramps down *before* each peak),
    then one-pole release. No makeup gain, no extra compression stage."""
    c = 10 ** (ceiling_db / 20)
    up = resample_poly(x, os_factor, 1, axis=0).astype(np.float32)
    sru = sr * os_factor
    peak = np.abs(up).max(axis=1)
    greq = np.minimum(1.0, c / np.maximum(peak, 1e-9)).astype(np.float64)
    L = max(1, int(lookahead_ms * 1e-3 * sru))
    g = minimum_filter1d(greq, size=2 * L + 1, mode="nearest")
    g = uniform_filter1d(g, size=2 * L + 1, mode="nearest")
    g = _release(g, float(np.exp(-1.0 / (release_ms * 1e-3 * sru))))
    up = up * g[:, None].astype(np.float32)
    return resample_poly(up, 1, os_factor, axis=0).astype(np.float32)


def master(x, sr=SR, target_lufs=-10.5, ceiling_db=-1.0, low_shelf_db=0.0, high_shelf_db=0.0, glue=True, max_iter=6):
    """Tilt EQ -> optional glue compression -> loudness gain -> look-ahead true-peak limiter,
    iterated so the result lands on the loudness target with true peak <= ceiling."""
    chain = [LowShelfFilter(cutoff_frequency_hz=110, gain_db=low_shelf_db),
             HighShelfFilter(cutoff_frequency_hz=9000, gain_db=high_shelf_db)]
    if glue:
        chain.append(Compressor(threshold_db=-18, ratio=1.6, attack_ms=30, release_ms=250))
    pre = Pedalboard(chain)(x, sr)
    gain_db = target_lufs - lufs(pre, sr)
    y = pre
    for _ in range(max_iter):
        y = limit(pre * 10 ** (gain_db / 20), sr, ceiling_db=ceiling_db - 0.2)
        err = target_lufs - lufs(y, sr)
        if abs(err) < 0.15:
            break
        gain_db += err
    tp = true_peak_db(y)
    if tp > ceiling_db:  # resampling can leave tiny overs; trim them
        y = y * 10 ** ((ceiling_db - tp - 0.02) / 20)
    return y.astype(np.float32)
