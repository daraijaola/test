#!/usr/bin/env python3
"""Measure the real (not advertised) audio quality of one or more files.

Bitrate alone lies: a 320 kbps file can be a re-encode of a 128 kbps one. This
decodes each file with ffmpeg and reports duration, peak, RMS, the effective
high-frequency cutoff and per-band levels relative to the 1-4 kHz midrange.

Usage: measure_quality.py FILE [FILE ...]
"""
import subprocess
import sys

import numpy as np

SR = 48000
BANDS = [(10000, 12000), (12000, 14000), (14000, 15000), (15000, 16000), (16000, 17000),
         (17000, 18000), (18000, 19000), (19000, 20000), (20000, 22000)]


def decode_mono(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def measure(path):
    x = decode_mono(path)
    n, hop = 8192, 4096
    if len(x) < n:
        return {"file": path, "error": "too short"}
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    spec = np.mean(np.abs(np.fft.rfft(frames, axis=1)) ** 2, axis=0)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    db = 10 * np.log10(spec + 1e-20)
    ref = np.median(db[(freqs > 1000) & (freqs < 4000)])
    above = freqs[(db - ref) > -60]
    return {
        "file": path,
        "duration_s": round(len(x) / SR, 2),
        "peak": round(float(np.abs(x).max()), 3),
        "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)), 1),
        "cutoff_khz": round(float(above.max()) / 1000 if len(above) else 0.0, 1),
        "bands_db": {f"{lo // 1000}-{hi // 1000}k": round(float(np.median(db[(freqs >= lo) & (freqs < hi)]) - ref), 1)
                     for lo, hi in BANDS},
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        try:
            r = measure(p)
        except Exception as e:  # keep going on unreadable files
            r = {"file": p, "error": str(e)[:200]}
        print(r)
