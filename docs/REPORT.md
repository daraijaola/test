# Juice WRLD, "Campfire" freestyle over Dadju's "Reine": Extended Cut, Remix and Feature Song

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
| feature/01 | **Juice WRLD x Roddy Ricch** (2:59) | Follow-up request: the Extended Cut - Live, then a real guest verse on the same Reine beat, then Juice's hook returns, then Reine's own outro. See section 9 |
| feature/02 | Juice WRLD x Dave (3:09) | Same build with Dave's "Wanna Know" verse; the user named Dave as an example |
| **final** | **Juice WRLD x Dave [Studio Version]** (3:42) | The user's pick, polished into a full song: verse, hook, Dave's feature entrance, hook, Reine's outro. No Auto-Tune. See section 10 |

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

## 9. Follow-up: Juice WRLD x a real guest verse, on the real Reine beat

**The brief.** The user loved the Extended Cut - Live, disliked the remixes (weak beats, the beat too quiet under the voice) and asked
for the Extended Cut's intro and exact ending beat, with another rapper's *real* verse after Juice's, on that exact beat, to make a
complete song ("what will Juice WRLD and Central Cee sound like, or Juice WRLD and Dave"), the beat loud.

**Song form (both deliverables).**

| Output time | Bars (live grid) | What plays |
|---|---|---|
| 0:00-1:45 | 5-48 | The Extended Cut - Live, untouched (nulls against it at -65 dB, loudness matched to 0.03 LU) |
| 1:45-1:50 | 49-50 | Reine's own sparse bridge bars as a breath; the 808 enters on beat 4 with its own attack, spliced from Reine's chorus-2 entry |
| 1:50 | 51 | The 808 drop and the guest's bar 1 |
| guest verse | 51-65 (Roddy) / 51-70 (Dave) | Reine's 808 sections in whole bars: chorus 2 (41-48), then the bridge build and chorus 3 (61-72). Reine is a 2-bar chord loop, so every jump keeps bar parity and is seamless |
| hook | 67-70 / 71-74 | Juice's own opening hook from the freestyle, live bars 9-12 ("I ain't finna fall down / Fourth quarter, shorty, I'ma ball out / Don't go to work, baby, call out / Ain't no way, no stall now"), same tempo and grid, no stretch |
| outro | 71-81 / 75-85 | Reine's real outro, exactly as in the Extended Cut |

**Finding verses that fit.** Four scouts (UK, US melodic, French, afro) measured 400+ songs (Deezer previews, beat_this, bar-level
comb), keeping native tempos within about +-6% of 100.45 BPM (or half/double), located verses with synced lyrics, and downloaded 18
full songs (no YouTube). Central Cee's catalogue is almost all drill at 139-150 BPM (Sprinter 139, Doja 140, BAND4BAND 140): his
only fitting verse is "TOO MUCH" (95 BPM). Dave fits natively with "Wanna Know" (100.0) and "No Words" (100.5).

**Per verse.** Separation (RoFormer Big Beta 4, Kim FT, Demucs for screening), a comb-search beat grid on the guest's own record
(bar 1 from drums, chord changes and rhyme positions), whisper word timings, pitch vs Reine's chords for every transposition, groove
feel (straight vs triplet), placement that keeps each rapper's own offset to the drums (Reine's onsets sit +32 ms on the live grid;
each guest is shifted by that minus their own beat's offset), Rubber Band R3 with formant and centre-focus, and a mix with
**no ducking**: the guest sits +1.2 to +1.7 LU over the beat per 4-bar block (Juice sits +1.9 over the same 808 bars in his own
chorus 2), ridden partially (k = 0.6) so the voice opens up over sparser bars as his does.

**Judging.** 12 full songs were rendered and scored by four independent lenses (A&R, rhythm, mix, harmony) and the top two were
attacked by skeptics.

| Rank | Guest verse | Mean | Borda | Notes |
|---|---|---|---|---|
| 1 | **Roddy Ricch - High Fashion** | 7.73 | 40 | Same key as Reine (harmony 1.45x Juice's own), cleanest stem, romantic lines, 0.947 of words still recognised in the final mix (Juice: 0.919) |
| 2 | Roddy Ricch - Ballin' | 6.68 | 27 | Tightest pocket, but a Nipsey/Lauren name-check and heavy Mustard bleed in the stem |
| 3 | **Dave - Wanna Know** | 6.65 | 27 | A&R's #1 (named by the user, full 20 bars, no name-checks) but the loosest flow on the grid (16th lock 0.12 vs Juice 0.34) |
| 4 | Drake - The Motto | 6.58 | 25 | Rhythm's #1; YMCMB/Mac Dre name-checks read as a mashup |
| 5 | Stormzy - Own It | 6.10 | 24 | Best harmony after -1 st and the most romantic, but its last line is the song's title hook |
| 6-12 | Aitch, Drake (Ojuelegba), Cordae, Skepta, PNL, Central Cee (TOO MUCH), Dave (No Words) | 4.4-5.8 | | Central Cee's only tempo-fit verse opens on LAROI's sung "too much", ends mid-sentence into the hook and needs a 5.7% speed-up |

**What the skeptics caught (all fixed and re-measured).**
1. A typo of mine put Roddy's bar 1 100 ms early (41.0407 instead of 41.1407): he now sits +26 ms behind Reine's drums, as on his record.
2. His last word "want" was clipped by the fade: the cut moved into the gap before "Shawty".
3. **Rubber Band R3 processed L and R independently**: the near-mono guest vocal came out with L/R correlation 0.2 and lost 2.3 dB in
   mono. `--centre-focus` restores 0.94-0.97 (the source's own value) and -0.1 dB.
4. The raw live acapella of the hook drove the master limiter on every syllable (the 808 pumped down 3-6 dB under Juice). The hook now
   gets the guest's chain (24 dB/oct HPF, presence, compression, the same reverb/delay), a fast vocal-bus limiter for live-mic plosives,
   +0.8 LU over the beat and a -0.8 dB static trim of those 4 bars: master gain reduction there is now the same as in Juice's own
   approved chorus 2 (median -0.97 vs -0.88 dB; >3 dB 4.6% vs 4.8% of the time).
5. A 12 ms 808 notch at the drop created by the first version of the beat splice: the splice now runs through to beat 2 of bar 51.
6. Dave: whisper put the "road"/"Look" boundary inside the held vowel, leaving a chopped "-oad": the cut is now in the real silence.

**Limitations.** Nobody listened; every call rests on measurements and adversarial review. The guest sources are lossy (High
Fashion 128 kbps AAC to 16.6 kHz, Wanna Know 96 kbps to 14.75 kHz); the studio Reine continuation is band-limited to about 16 kHz
as in the Extended Cut. "If we hop in the Benz... ride at the top, babe" is High Fashion's sung refrain (it recurs in both of its
verses), so the first half of Roddy's part is sung, the second half rapped.

## 10. Polish: "Juice WRLD x Dave" as a complete studio record

**The brief.** The user picked the Dave version and asked for it to be polished with as much time as needed:
- Juice's voice sounded "a bit shallow" and maybe needed Auto-Tune, each artist the way they sound on their own
  records.
- Dave's entrance was "a bit cut"; it should feel like a complete, full song.
- Clean front to back, checked over and over.

**Research.**
- **Juice WRLD's records are tuned.** Ten record previews measure 98-100% in key at A440, with 81% of held notes
  within 8 cents. Correction is fast but not robotic: about 15-20 ms on sung lines, about 35 ms on rap lines.
  The live freestyle is untuned (21-24% within 8 cents).
- **Dave does not tune his rap verses.** His verse measures like pre-Auto-Tune recordings; his engineer uses it
  only as an effect on singing.
- **Feature entrances.** The conventions: a hook between the two verses, a short turnaround, a throw on the last
  word, a drop-out on the last beat, the guest's pickup in the gap, and the full beat on the guest's bar 1.

**Song form (final, 3:42).** Every join is one of Reine's own transitions, and the bar parity of its 2-bar
chord loop is kept everywhere.

| Output time | Bars | What plays |
|---|---|---|
| 0:00-1:45 | 5-48 | Juice's whole freestyle on the studio Reine instrumental (the Extended Cut's form) |
| 1:45-1:50 | 49-50 | Reine's own stop bar after chorus 2, then its build bar into chorus 3 |
| 1:50-2:09 | 51-58 | Hook: Juice's freestyle bars 9-16 ("I ain't finna fall down ... In the bedroom. Out") on chorus 3's 808. Its last bar is Reine's 808 drop-out bar |
| 2:08-2:57 | 58.75-78 | Dave's "Look," in the drop-out on beat 4, then his 20 bars from Reine's chorus-2 808 entry |
| 2:57-3:01 | 79-80 | Reine's natural 72->73 bar after his last word ("Brighton", with a delay throw), then the build bar |
| 3:01-3:20 | 81-88 | The hook again, ending on Reine's last chorus bar |
| 3:20-3:42 | 89- | Reine's real outro, as in the Extended Cut |

**Vocals: Auto-Tune built, heard, and removed.**
- **The tuner.** `autotune.py` (Praat PSOLA, chord-aware) won a tool bake-off against Rubber Band, fat1,
  Autotalent and WORLD: it gave the cleanest formants and transients. It uses a dither-free pitch track and a
  Viterbi note choice that prefers Reine's chord tones, and its output matched Juice's records:
  - concentration 0.76 vs 0.77
  - note-centre spread 6.2 vs 4.6-7.0 cents
  - transitions 43 vs 38-51 ms
- **The user rejected it.** After hearing it in review v3: "my only problem is genuinely the auto tune in both
  of them ... the cut in where Dave enter and everything also is good, just auto tune is bad". The final has
  **no pitch correction on anyone**: Juice's pitch measures natural (0.09; live 0.06-0.07; tuned 0.50). The
  pitch-shifted pseudo-doubles on the hooks were removed as well.
- **Dave's "Auto-Tune" was an exciter.** Dave was never tuned. What the user heard was a 10-16 kHz exciter that I
  had added for "record air": on the 96 kbps stem its synthetic highs were +15 dB at 16 kHz against the approved
  mix, which exaggerated the codec warble. Dave is back on exactly the approved chain, within 1 dB of it in
  every band.
- **Juice's "shallow" sound** is fixed without tuning. His de-reverbed live vocal goes through a chain fitted
  to his records' tone:
  - 400 Hz-1 kHz +3, 3-6 kHz -6, 6-10 kHz -10, 10-15 kHz -16 dB re 1-3 kHz
  - 150-400 Hz deliberately kept about 2 dB above the records: live, he sings about 8 semitones lower, so that
    band is his chest
  - FET then opto compression
  - a zero-phase split-band de-esser. The causal split used before boosted the band edges whenever it reduced
    gain; the same bug was in the guest chain and is fixed there too
  - 6% parallel saturation, plate and tempo delay

**Mix.**
- **Verse rides that keep his performance.** The Extended Cut's vocal-over-beat numbers were measured against
  the DJ's live beat. That beat sits 5.5-9.8 dB under the studio instrumental, by a different amount in every
  block, so copying the numbers carried the DJ's fader moves onto Juice's voice: -6 dB into bar 26 and +3.7 dB
  in the middle of "Fourth" at bar 10. `verse_targets.py` makes each block follow the acapella's own loudness,
  keeps the Extended Cut's overall balance, and moves every block boundary into a gap or the deepest breath.
  The bar-to-bar deviation from his performance fell from 2.1 to 0.7 dB.
- **Level targets on the wet vocal.** The targets are re-measured after the returns and the bus and corrected
  4 times.
- **Master glue.** The glue compressor's detector is high-passed at 150 Hz, so the 808 no longer pumps the
  vocals: per-beat swing on the hooks went from 4.3 to 3.2-3.5 dB, and on Dave from 3.1 to 2.5 dB.
- **Juice's peaks.** His dry track is peak-shaved in the live verse only, at a ceiling frozen on the first pass.
  Whole-mix limiter ducks of more than 3 dB in the verse went from 23 to 2. Two 3-5 ms consonant spikes in the
  hook clip are clamped to the vowel that follows.
- **Clean-up.** 20 Hz high-pass on the vocal bus (DC was -59 dBFS) and a 3 ms fade on the beat's first samples.

**Review.** Three rounds of independent reviewers worked by measurement (16, 7 and 4 agents), and two
skeptics tried to refute every finding before it was acted on.

| Round | What it found | Outcome |
|---|---|---|
| 1 (v3) | A weak drop into Dave (bar 1 stepped down in energy); the hook-1 echo landing on "Look,"; master pumping; the exciter | Pumping and exciter fixed. The stronger drop was tried in v5, then reverted: the reviewers read the user's message as approving v3's entrance, as I had not |
| 2 (v5) | The 6-7 dB verse drop into bar 26; v5's changed entrance | Both fixed in v6 |
| 2 (v6) | The peak shave limiting the hooks, with the level loop chasing it; 1.5 s rides swelling inside two lines; the gap before "Look," 2 dB emptier | Fixed in v7 |
| 3 (v7) | No blocker or should-fix. Nits: the "go to" spike; the MP3 peak at -0.98 dBTP | Both fixed (de-spike; the MP3 is encoded 0.3 dB lower) |

**Final numbers.**
- **Loudness:** integrated -10.77 LUFS. Juice's verse is -11.49, matching the Extended Cut's opening.
  Hooks -9.97 / -9.77, Dave -9.59.
- **Peaks:** WAV -1.28 dBTP; MP3 -1.39 dBTP after decoding. Zero clipped samples, DC under 1e-4.
- **Beat:** the bed is bit-identical to the approved v3.
- **Intelligibility:** whisper word recall in the mix is Juice 0.957 and Dave 0.914, the same as the approved
  version.

**Limitations.**
- Nobody listened; every call rests on measurements and adversarial review.
- Dave's stem keeps its 96 kbps codec warble.
- A few of Juice's held notes carry separation colour from the live recording.
- The 0.3 s rides at breath boundaries overlap voiced audio by up to 0.9 dB over about 150 ms.

## 8. Tools (all open source)
FFmpeg, yt-dlp, Rubber Band, SoX, audio-separator (MelBand / BS RoFormer and MDX models from the UVR community), Demucs v4,
faster-whisper (Whisper large-v3), SpeechBrain ECAPA, beat_this (CPJKU), Essentia, librosa, torchcrepe, LAION-CLAP (via transformers),
Spotify Pedalboard, pyloudnorm, NumPy/SciPy, Matplotlib, Pillow, mutagen. The pipeline is documented in `pipeline/README.md`.
