"""Objective "does Juice's melody fit this beat?" metrics.

harmonic_fit: for every confidently sung 10 ms frame, compare the pitch class
Juice sings with the beat's chroma at that moment, weighting each chord tone by
how consonant the interval is (unison/fifth/third good; minor second/major
seventh/tritone bad). Averaged over voiced frames -> roughly [-1, 1].
The original Reine beat (the one he actually freestyled on) is the baseline.

groove_fit: correlation between where Juice's syllable onsets fall inside the
bar (16th-note grid) and where the beat's own onsets fall.
"""
import librosa
import numpy as np

# consonance weight of (vocal pitch class - chord tone) mod 12
INTERVAL_W = np.array([1.0, -1.0, 0.0, 0.7, 0.7, 0.6, -0.6, 0.8, 0.6, 0.6, 0.0, -1.0])


def beat_chroma(y, sr, hop=512):
    c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    # emphasise sustained harmony over transients
    c = librosa.decompose.nn_filter(c, aggregate=np.median, metric="cosine")
    c = c / (c.sum(axis=0, keepdims=True) + 1e-9)
    t = librosa.frames_to_time(np.arange(c.shape[1]), sr=sr, hop_length=hop)
    return t, c


def harmonic_fit(v_times, v_f0, v_weight, c_times, chroma, transpose=0):
    """v_* are the vocal pitch track (times in the SAME timeline as the beat), chroma (12, T)."""
    sel = (v_weight > 0) & (v_times >= c_times[0]) & (v_times <= c_times[-1])
    if sel.sum() < 50:
        return float("nan")
    midi = 69 + 12 * np.log2(np.maximum(v_f0[sel], 1e-3) / 440.0)
    pc = np.mod(np.round(midi), 12).astype(int)
    idx = np.clip(np.searchsorted(c_times, v_times[sel]), 0, chroma.shape[1] - 1)
    ch = np.roll(chroma, transpose, axis=0)[:, idx]  # (12, N)
    d = np.mod(pc[None, :] - np.arange(12)[:, None], 12)
    per_frame = (ch * INTERVAL_W[d]).sum(axis=0)
    w = v_weight[sel]
    return float((per_frame * w).sum() / (w.sum() + 1e-9))


def onset_bar_histogram(onset_times, downbeats, bar_len, divisions=16):
    h = np.zeros(divisions)
    for t in onset_times:
        k = np.searchsorted(downbeats, t, side="right") - 1
        if k < 0:
            continue
        pos = (t - downbeats[k]) / bar_len
        if 0 <= pos < 1:
            h[int(pos * divisions) % divisions] += 1
    return h / (h.sum() + 1e-9)


def groove_fit(vocal_onsets, beat_onsets, downbeats, bar_len):
    hv = onset_bar_histogram(vocal_onsets, downbeats, bar_len)
    hb = onset_bar_histogram(beat_onsets, downbeats, bar_len)
    if hv.std() == 0 or hb.std() == 0:
        return float("nan")
    return float(np.corrcoef(hv, hb)[0, 1])
