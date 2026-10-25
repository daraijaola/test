#!/usr/bin/env bash
# Reproducible environment for the Juice WRLD "Reine" project.
# System deps: ffmpeg, rubberband-cli, sox, libsndfile1 (apt). Python 3.11 venv at /opt/ml.
set -u
PY=/opt/ml/bin/python
IDX="--index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match"
[ -x "$PY" ] || uv venv --python /usr/bin/python3.11 /opt/ml -q
step() { echo "=== $1 ==="; shift; uv pip install --python "$PY" $IDX "$@" && echo "OK" || echo "FAILED: $*"; }
step "torch (cpu)"   torch torchaudio
step "core audio"    numpy scipy soundfile librosa pyloudnorm pedalboard pyrubberband mutagen pillow matplotlib pandas requests yt-dlp
step "separation"    "audio-separator[cpu]" demucs
step "transcription" faster-whisper
step "beat tracking" "git+https://github.com/CPJKU/beat_this.git"
step "pitch"         torchcrepe
step "mir"           essentia
step "embeddings"    transformers
step "mastering"     matchering
step "speaker"       speechbrain
$PY - <<'P'
import importlib
for m in ["torch","torchaudio","librosa","pyloudnorm","pedalboard","pyrubberband","audio_separator","demucs","faster_whisper","beat_this","torchcrepe","essentia","transformers","matchering","speechbrain","yt_dlp","mutagen"]:
    try:
        mod = importlib.import_module(m); print(f"{m:16s} OK  {getattr(mod,'__version__','')}")
    except Exception as e:
        print(f"{m:16s} FAIL {type(e).__name__}: {str(e)[:120]}")
P
