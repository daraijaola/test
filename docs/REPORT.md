# Juice WRLD, "Campfire" freestyle over Dadju's "Reine": Extended Cut and Remix

Personal, non-commercial fan edit. Juice WRLD's estate owns the freestyle, Mouv'/Radio France own the broadcast,
and the "Reine" composition and recording belong to Dadju, Seysey and Universal. The remix beats belong to their
producers. **No audio is committed to this repository**, and the deliverables were sent directly to the requester.
Don't upload them: expect Content ID takedowns.

Total wall time: about 7 hours on a 4-core CPU-only cloud box. Everything was open source.

---

## 1. Deliverables

| # | File | What it is |
|---|---|---|
| 01 | Extended Cut, Live | The untouched Mouv' recording, cleaned at the start, then the real "Reine" record carries on after Juice stops (3:04) |
| 02 | Extended Cut, Studio Rebuild | Juice's isolated vocal over the studio "Reine" instrumental for the whole song (3:04) |
| 03 | Extended Cut, Dadju continuation | Like 01, but after an 8-bar breakdown Dadju's own vocals come back for the rest of the song (3:04) |
| 04-06 | Remix: winner and 2 runners-up | Juice's vocal on the best beats found among 8,802 candidates. See section 6 |
| bonus | Remix: Forests (afro-pop guitar) | 4th place, kept so the work isn't lost. The afro version closest to the original's vibe |
| stems | `juice_acapella.wav`, `reine_live_instrumental.wav` | The performance only (14.3-117.85 s). They sum back to the mix exactly |

Each track comes as a 24-bit WAV and a 320 kbps MP3 with tags and generated cover art. Masters: Extended Cuts at -12 LUFS
(the studio record's own loudness), remixes at -11 LUFS, all at most -1.0 dBTP true peak with zero clipped samples.

## 2. The source (research)

| Fact | Value | Confidence |
|---|---|---|
| Performance | Juice WRLD live freestyle over Dadju "Reine". Fan names: "Campfire Song", "Campfire Freestyle", "Ball Out" | high |
| Where and who | Mouv' Live Club, Paris, hosted by DJ (Damien) Muxxa | high |
| Date | Mouv' says "le 19 octobre", year 2018 (Dailymotion upload 2018-10-19 15:06 UTC, the day *WRLD ON DRUGS* came out). It may be the air date of a session taped on his September 2018 European run; he played Élysée Montmartre on 2018-09-20 | high / medium |
| Session | 8 beats in 15:53. "Reine" is the 6th, at 8:55. On Juice WRLD's verified Audiomack. Never released on streaming services | high |
| The beat | Dadju "Reine" (2017, *Gentleman 2.0*), produced by **Seysey**, 98.0 BPM, D major / B minor pitch set. **No official instrumental exists** | high |
| Best audio | Mouv's own Facebook upload: AAC 317 kbps with genuine content to about 20 kHz. Every other copy measured worse. YouTube is unreachable from the build machine and was not circumvented | measured |
| Studio master | The only waveform-verified full copy (it matches the official Apple/Deezer previews at 0.994-0.999) is a Dailymotion upload. A SoundCloud "full song" that the pipeline first used turned out to be a **cover** (waveform match 0.03-0.06) and was replaced | measured |

Full dossiers: `docs/research/session.md`, `docs/research/reine.md`, `docs/research/sources_summary.md`.

## 3. What the DJ actually played (measured)

- **The original "Reine" instrumental, sped from 98 to 100.45 BPM with key-lock.** Live and studio instrumental onsets correlate at 0.88-0.94.
- Mapping: `live = 2.84218 + 0.975631 x studio`. It was fitted on 33 windows across the song: residual 0.94 ms, max 2.2 ms.
- He started at the top of the song (studio bar 1 = live 3.18 s) and let it run **unedited through the end of chorus 2** (live 117.9 s).
  That is exactly where Juice stops. After that the clip has Mouv's station jingle, spliced in by their video editor. In the full session
  the beat does **not** continue after Juice; the DJ moves to the next track.
- Juice: a hum from 14.55 s (a pickup into bar 6), first word at 16.90 s, last word ending at 117.70 s. The intro banter and the
  "DJ Muxxa" tag (12.6-14.4 s) are not Juice (speaker-verification cosine 0.05, against 0.90+ for his singing).
- His melody: range C#3-G#3, centred on E/F. His steady notes sit on F (slightly sharp) and D#/E, which is partly "outside" Reine's
  D major. That is why many candidate beats measure a *better* harmonic fit than Reine itself.

## 4. Extended Cut

All three start on the **verse-1 drop** (live bar 5) with one bar of beat before Juice comes in. The DJ's sung tag is removed from that bar
using the separated instrumental, handing back to the untouched recording in the 0.35 s of silence before his hum. All three end
on the record's **real ending** (bridge, chorus 3, outro, natural decay), placed exactly where the song would have continued.

- **Hand-off.** On the drum transient of beat 4 of chorus 2's last bar.
  - The DJ's time-stretching had put the live 808 in **phase opposition** to the studio 808 (correlation -0.63), which caused a 7.5 dB,
    20 ms hole in the crossfade.
  - Delaying only the studio's sub-180 Hz band by 4.78 ms brings them into phase (+0.60) and removes the hole. The worst 5 ms deviation
    from the original envelope is now -1.7 dB.
- **Continuity.** The studio continuation is loudness-matched to the live beat over chorus 2 and passed through a smoothed third-octave
  match EQ (linear-phase FIR), so the radio-to-studio hand-off doesn't jump.
- **Dadju version.** It switches from the instrumental to the full record on a beat *before* Dadju's bridge pickup, so his voice
  never collides with Juice's last line.
- **QA.** No clipped samples. Level changes at every edit match the original recording's own transients. The remaining "click candidates"
  are Juice's plosives on the live mic: they appear in the untouched source at the same times.

## 5. Vocal isolation

- **Bake-off** on a 30 s excerpt (dense vocal section plus bass section). The candidates were MelBand RoFormer Kim, Kim FT (unwa),
  Big Beta 4 (unwa) and Demucs htdemucs_ft. BS-RoFormer was dropped: it is 3-4x slower on this CPU.
- **Scoring** used ground-truth-free proxies: bleed in silent gaps, beat-synchronous drum bleed, sub-80 Hz bleed, vocal leakage at the
  sung f0 harmonics, and vocal capture. Result: **Big Beta 4 > Kim FT > Kim > Demucs**. Demucs left 40 dB more bleed in the gaps.
- **Final acapella** is an ensemble of Big Beta 4 (overlap 4) and Kim MelBand (inter-model correlation 0.9994). It was trimmed to Juice
  only and run through a conservative downward expander: 0.0 dB change while he sings, at most about -3 dB in gaps.

## 6. Remix search

| Stage | Count | How |
|---|---|---|
| Harvest | **8,983** tracks (8,802 candidates + references) | 7 parallel harvesters: Deezer (mainstream; 30 s previews plus BPM), SoundCloud, Internet Archive, Jamendo (MTG-Jamendo metadata, CC), FMA (CC), curated references. ccMixter's file server returned 403 on every download, which was not bypassed. 15 genre buckets, 4,447 instrumentals, 6,247 with full audio |
| Tier 1 | 8,983 analysed, 0 errors | Tempo, key, chroma and loudness for every clip |
| Stage 1 | 8,780 unique, scored | Tempo fit to 100.446 BPM (half/double allowed), harmonic fit of his melody at the best transposition (normalised to Reine), cross-library dedup |
| Tier 2 | 1,431 CLAP embeddings | Mood similarity to Reine plus Juice WRLD reference songs plus text prompts; instrumental probability |
| Stage 2 | 300 simulated | His actual verse, beat by beat, over each looped/stretched/transposed beat: every transposition x bar alignment, plus groove fit |
| Previews | 40 rendered | His full verse over each beat, with harmony and masking re-measured on the rendered audio |
| Judges | 4 lenses + devil's advocate | Harmony, groove, A&R/vibe, production/feasibility, then an adversarial review of the top 12 using the full tracks |
| Production | 5 finalists | Full arrangements on the real tracks, bar phase fixed from drums and downbeats, tags and chops removed where found |
| Final ranking | 3 lenses | A&R, engineering/harmony, skeptic, combined by Borda count |

Problems that the adversarial process caught and fixed:
1. The previews' bar alignment was chosen on harmony alone, so many put the beat's downbeat one beat off Juice's (snare on his 1 and 3). Final productions fix the bar phase from drum evidence and downbeats first, then optimise harmony.
2. A pyrubberband quirk (it mutates the options dict) applied the time-stretch **twice** whenever a beat was also transposed, so those beds drifted. It was fixed and the 14 affected previews were re-rendered.
3. The grid tempo initially came from Deezer metadata (97.97 BPM). A regression on the live beat gave 100.446 BPM (studio 98.00), which removed about 30 ms of end-of-verse drift.
4. "Forests": pitched vocal chops (44% of the track, a semitone above his notes) were removed with Demucs FT, and the out-of-phase sub-bass was folded to mono (L/R correlation -0.16 to +1.00). "Internet Money": a pitched producer tag in the intro was removed.

### Final ranking

A three-lens panel (A&R, engineering/harmony, skeptic) ranked the five finished productions. Borda points: **Sad Guitar 13,
Internet Money 11, Codeine 9**, Forests 8, Scared 4. After the panel, each finalist got the fixes the judges asked for. A final residual check
then put every vocal-separation stem at -40 to -48 dB under the mix wherever Juice is silent, which means no audible tags.

| Place | Beat | Why |
|---|---|---|
| 🥇 **04 - Remix: Sad Guitar** (2:45) | OAR Beatz, "Sad Guitar Type Beat" (= "Lil Yachty x 'Love Music' Type Beat", 2021). Strummed guitar, trap drums, sliding 808, F major (the relative major of D minor). No transposition | Best harmonic support *in his own register*: 1.33x Reine, with a semitone-clash share of 8.6% against Reine's 25.5%. Cleanest signal path: no tag, vocal, separation or pitch shift. Steadiest timing (beat lock within 3.9 ms). Guitar trap is core Juice territory (Lucid Dreams, Wishing Well), and a strummed guitar is the literal "Campfire". Re-phased after the panel so every section change lands on his phrase starts. The guitar-only intro carries the hook teaser, the drums come in with the verse, and both hooks ride the same full groove |
| 🥈 **05 - Remix: Internet Money** (2:47) | Run Carlie, "Internet Money" type beat (2020). Emo trap, D minor, rolling hats, heavy 808 drops | The most instantly "Juice WRLD" record: the Internet Money sound behind Lucid Dreams and Robbery. It has the best pure engineering (78 of 80 beat bars bit-identical) and the strongest hook drop, but only average in-register harmony (about 1.03x Reine). Re-arranged so the 808 drops land on his phrase starts. The intro was rebuilt from tag-free bars to remove a sung producer tag, and the outro was trimmed to 4 bars with a fade |
| 🥉 **06 - Remix: Codeine** (2:52) | Taz Taylor, "Codeine" (A$AP Rocky type beat, 2015). Hazy cloud-rap keys and a heavy 808. +2 semitones | Second-best harmony (in-register 1.22x) and the most coherent arrangement, with every change on a phrase start. The druggy haze suits the lyrics, and Taz Taylor founded Internet Money. A spoken URL producer tag every 16 bars was removed with Demucs FT around the tag regions only, and the hard ending now fades. It has the loosest pocket of the three (beat lock up to 18 ms in one window) |
| bonus | nytcyd, "Forests" (afro-pop guitar). +1 semitone | The closest to Reine's romantic afro DNA, and the skeptic's #1 once its fixes were verified. It needed the most processing: pitched vocal chops removed and out-of-phase sub-bass folded to mono. 4th overall |
| not delivered | VHS x Taz Taylor, "Scared" (Keith Ape type) | A dark, horror-trap lane against a romantic freestyle, the weakest harmony in his register (0.78x) and a one-beat displacement of its drum pattern |

## 7. Honest limitations

- Nobody listened. Every decision rests on measurements, spectrograms, adversarial agent review and musical knowledge. Take the ranking
  as a strong prior, not a verdict. Listen to all of them.
- The best freestyle audio available is a lossy radio broadcast (AAC, about 18-20 kHz). The remix beats come from 128-160 kbps
  streams (cutoff about 16 kHz). These are fine on a phone or headphones, but they aren't studio masters.
- Separation artifacts are minimised (ensemble, overlap 4) but not zero, especially in the remixes, where the acapella is exposed on a new beat.

## 8. Tools (all open source)
FFmpeg, yt-dlp, Rubber Band, SoX, audio-separator (MelBand / BS RoFormer and MDX models from the UVR community), Demucs v4,
faster-whisper (Whisper large-v3), SpeechBrain ECAPA, beat_this (CPJKU), Essentia, librosa, torchcrepe, LAION-CLAP (via transformers),
Spotify Pedalboard, pyloudnorm, NumPy/SciPy, Matplotlib, Pillow, mutagen. The pipeline is documented in `pipeline/README.md`.
