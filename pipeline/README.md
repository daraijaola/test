# Pipeline: Juice WRLD "Reine" freestyle: Extended Cut + Remix

Everything here is open source and runs on CPU. Audio never goes into git. It lives in `work/` and
`deliverables/`, both ignored. The scripts are listed in the order they run.

## Environment
| Script | What it does |
|---|---|
| `setup_env.sh` | Creates the Python 3.11 venv at `/opt/ml`: PyTorch (CPU), audio-separator, Demucs, faster-whisper, beat_this, torchcrepe, Essentia, transformers (CLAP), Pedalboard, pyloudnorm, Rubber Band, Matchering, SpeechBrain. System packages: ffmpeg, rubberband-cli, sox. |
| `jobqueue.sh`, `enqueue.sh` | Serial compute queue. PyTorch jobs on a 4-core box slow down badly when run together (OpenMP oversubscription), so heavy steps run one at a time. |

## Sources and analysis
| Script | What it does |
|---|---|
| `measure_quality.py` | Measures real audio quality (effective HF cutoff and band levels), not the advertised bitrate. Used to pick the master: Mouv's official Facebook upload has genuine content to ~20 kHz. |
| `separate.py` | Runs any audio-separator model (RoFormer / MDX23C) or Demucs into `<out>/<model>/{vocals,instrumental}.wav`. `--overlap` trades speed for quality. |
| `score_separation.py` | Ranks separation models on the real recording with no ground truth, using bleed proxies. With ground truth available it ranks by SDR. |
| `transcribe.py` | Word-level timestamps (faster-whisper large-v3) plus per-segment language ID. The transcript is used only to place edit points (French host vs English Juice). It is never shipped as a lyric sheet. |
| `analyze_music.py` | Beats and downbeats (beat_this), tempo, and key with several profiles (Essentia). |
| `vocal_pitch.py` | Juice's sung melody (torchcrepe): frame-level f0, pitch-class histogram, range. |
| `align_reine.py` | Coarse alignment of the live beat against the studio record (chroma + onset features). |
| `studio_to_live.py` | Renders studio audio onto the live timeline (live = 2.8398 + 0.97565 x studio, from two-anchor onset alignment against the verified master). |

## Rendering
| Script | What it does |
|---|---|
| `mixlib.py` | Shared DSP: equal-power crossfades, Rubber Band R3 time/pitch (formant-preserving for vocals), vocal chain (HPF, EQ, split-band de-esser, two-stage compression, tempo-synced delay, reverb send), oversampled look-ahead true-peak limiter, LUFS mastering. |
| `arrange.py` | Renders any JSON arrangement plan (clips on tracks, with fades/stretch/mutes) and runs QA. |
| `build_extended.py` | The three Extended Cut versions on the live timeline, with level and match-EQ of the studio continuation to the live beat. |
| `remix_render.py` | Juice's vocal over a new beat, stretched to his 100.415 BPM grid, transposed, bar-aligned, looped with crossfades at loop jumps, then mixed and mastered. Self-test against the original alignment: 0.0 ms error. |
| `qa.py` | Objective QA: LUFS, short-term loudness, true peak, clipping, DC, stereo correlation, silence, click candidates, level jumps at edits, spectrogram PNG. |

## Remix search (`catalog/`)
| Script | What it does |
|---|---|
| `harvest_*.py` | One harvester per library: Deezer (mainstream, 30 s previews plus BPM), SoundCloud, Internet Archive, Jamendo (MTG-Jamendo metadata), FMA, ccMixter, plus curated references. Each writes `work/catalog/<src>/candidates.jsonl` and 30-45 s clips. |
| `merge_catalog.py` | Validates, deduplicates and merges everything into `work/catalog/catalog.jsonl`. |
| `analyze_catalog.py` | Tier 1: tempo, key, chroma and loudness for every clip. Tier 2: CLAP embeddings for the shortlist. Resumable and parallel. |
| `score_catalog.py` | Stage-1 screening: tempo fit to 100.415 BPM (half/double allowed), harmonic fit of Juice's melody (best transposition, normalised to the real Reine beat), CLAP vibe, instrumental probability, full-audio availability. |
| `fit_detailed.py` | Stage 2: a beat-by-beat simulation of his actual vocal over each looped, stretched and transposed candidate, searching every transposition and bar alignment, plus groove fit. |
