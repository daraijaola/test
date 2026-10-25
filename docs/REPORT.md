# Juice WRLD, "Campfire" freestyle over Dadju's "Reine": Extended Cut and Remix

Personal, non-commercial fan edit. Juice WRLD's estate owns the freestyle, Mouv'/Radio France own the
broadcast, and the "Reine" composition and recording belong to Dadju/Seysey/Universal. No audio is
committed to this repository.

> This file is a working draft. The final numbers and the remix results are filled in at the end of the run.

## 1. The source

| Fact | Value | Confidence |
|---|---|---|
| Performance | Juice WRLD, live freestyle over Dadju "Reine" (fan names: "Campfire Song", "Campfire Freestyle", "Ball Out") | high |
| Where / who | Mouv' Live Club, Paris, hosted by DJ (Damien) Muxxa | high |
| Date | Mouv' says "le 19 octobre". The year is 2018 (Dailymotion upload 2018-10-19 15:06 UTC). That may be the air date of a session taped during his September 2018 European run (he played Élysée Montmartre on 2018-09-20). | high / medium |
| Session | 8 beats in 15:53 (Niska, Kalash, NTM, 113, Alonzo, **Dadju "Reine" at 8:55**, Aya Nakamura, Ninho). Also on Juice WRLD's verified Audiomack. Never released on streaming services. | high |
| The beat | Dadju "Reine" (2017, *Gentleman 2.0*), produced by **Seysey**, studio tempo 98 BPM, D major / B minor pitch set. No official instrumental exists. | high |
| Best audio | Mouv's own Facebook upload (AAC 317 kbps, real content to ~20 kHz). Every other copy measured worse; YouTube is not reachable from the build machine. | verified |

Full dossiers: `docs/research/session.md`, `docs/research/reine.md`, `docs/research/sources_summary.md`.

## 2. What the DJ actually played (measured)

- **The original "Reine" recording**, an instrumental version, **sped up from 98 to 100.45 BPM with key-lock** (pitch unchanged).
  Live and studio instrumentals correlate at 0.88-0.94 on onset envelopes.
- Mapping (live seconds vs studio-master seconds): `live = 2.84218 + 0.975631 x studio`. It was fitted on 33 windows across the
  whole song with a residual of 0.94 ms (max 2.2 ms).
- The DJ started the song at its top (studio bar 1 = live 3.18 s) and let it run **unedited through the end of chorus 2**
  (live 117.9 s). That is exactly where Juice stops, and then the station jingle (spliced in by Mouv's editor) takes over.
- Juice's performance: a hum from **14.55 s** (pickup into bar 6), first word at 16.90 s, last word ending at **117.70 s**.
  The "DJ Muxxa" tag at 12.6-14.4 s and the opening banter are not Juice (speaker-verification cosine 0.05 vs 0.90+ for his singing).

## 3. Extended Cut (three versions, about 3:04 each)

All three start on the **verse-1 drop** (live bar 5, 12.74 s), with one bar of beat before Juice comes in. The DJ's sung tag
is removed from that bar with the separated instrumental, handing back to the untouched recording in the 0.35 s of silence
before his hum. All three end on the record's **real ending** (bridge, chorus 3, outro, natural decay), placed exactly where
the song would have continued.

| Version | What it is |
|---|---|
| A, Live | The untouched Mouv' recording for the whole performance, then the studio "Reine" instrumental continues seamlessly from the last beat of chorus 2. |
| B, Studio rebuild | Juice's isolated vocal over the studio "Reine" instrumental for the whole song (the cleanest sound). |
| C, Dadju | Like A, but after an 8-bar instrumental breakdown **Dadju's own vocals come in** (bridge part 2, chorus 3, outro), as if the record kept playing. |

Engineering details:
- **Level and tone matching.** The studio continuation is loudness-matched to the live beat over chorus 2 and run through a smoothed third-octave match EQ (linear-phase FIR), so the radio-to-studio hand-off doesn't jump.
- **Hand-off.** On the drum transient of beat 4 of chorus 2's last bar. The DJ's time-stretching had put the live 808 in phase opposition to the studio 808 (correlation -0.63), which caused a 7.5 dB, 20 ms dip in the crossfade. Delaying only the studio's sub-180 Hz band by 4.78 ms brings the two 808s into phase (+0.60), and the dip is gone (worst 5 ms deviation from the original envelope: -1.7 dB).
- **Mastering.** -12 LUFS integrated (the studio record's own loudness), true peak at most -1 dBTP, look-ahead oversampled limiter.

## 4. Vocal isolation
(Filled in at the end of the run: bake-off ranking, ensemble, cleanup.)

## 5. Remix search
(Filled in at the end of the run.)

## 6. Tools (all open source)
FFmpeg, yt-dlp, Rubber Band, SoX, audio-separator (MelBand/BS RoFormer, MDX23C models from the UVR community), Demucs v4,
faster-whisper (Whisper large-v3), SpeechBrain ECAPA, beat_this (CPJKU), Essentia, librosa, torchcrepe, LAION-CLAP (via
transformers), Spotify Pedalboard, pyloudnorm, NumPy/SciPy, Matplotlib, mutagen.
