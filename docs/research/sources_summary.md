# Source inventory: Juice WRLD "Reine" / Campfire freestyle fan edit

Completeness review of the research and sourcing phase, 2026-10-25. Every kept audio file below was re-probed (ffprobe) and re-measured
(`pipeline/measure_quality.py` plus a per-frame high-frequency check), and identity-checked by cross-correlation against official references.
"Real cutoff" is the highest band that is present in a *typical* frame, not the meter's mean-spectrum figure. The meter overstates HE-AAC files (SBR) and
files with occasional HF bursts. Confidence: H = high, M = medium, L = low. This file quotes no lyrics.

Verification scripts (numpy only, run with nice): `/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/critic/scripts/`
(ident.py, splice.py, stretchmatch.py, stretch2.py, pitchshift.py, remake_tempo.py, bass.py).

---

## 1. Bottom line

| Need | Status | File |
|---|---|---|
| (a) Best freestyle master | **Yes, verified.** No copy found anywhere has better real audio. | `work/sources/freestyle/fb_mouv_hd.mp4` |
| (a') Full-session context (lead-in, real tail) | Yes, at lower quality (hard 16 kHz cutoff) | `work/sources/freestyle/sc_full_willpincince_160k.m4a` |
| (b) Full studio "Reine" | **Yes, verified as the untouched master** (128k AAC, about 15.5 kHz) | `work/sources/reine/dm_reine_studio_shedevtv_128k.m4a` (decoded by the pipeline to `master_full.wav` / `master_from8.wav`, also verified) |
| (c) Instrumental | **Only re-made instrumentals; no official one exists in reach.** Same tempo and key as the original. | `dm_reine_karaoke_remake_64k.m4a`, `sc_reine_instr_unesxbl_remake_128k.mp3` |
| Misidentified file | `benoit_full.wav` (SoundCloud 1667838315) was a cover or re-recording, not the master (waveform NCC 0.03 to 0.06 at every speed and channel tested). The pipeline has since deleted it and re-pointed to the verified master (`work/analysis/align_master.json`). **Resolved.** | (deleted) |

## 2. Freestyle files, ranked (`/home/user/test/work/sources/freestyle/`)

| Rank | File | Origin | Duration | Codec | Real cutoff | Verdict |
|---|---|---|---|---|---|---|
| 1 | `fb_mouv_hd.mp4` | Mouv' official Facebook, posted 2018-10-24 20:00 UTC: https://www.facebook.com/MouvRadio/videos/juice-wrld-freestyle-sur-reine-de-dadju/114671982761102/ | 124.27 s | AAC-LC 317 kbps, 48 kHz | **~18 kHz typical, to ~20 kHz on louder frames** (meter 24.0 comes from sparse bursts; median frame above 18 kHz is under -70 dB) | **USE: master for the excerpt.** Excerpt 0.0 to 118.3 s = session 8:57.00 to 10:55.3. **118.5 to 124.3 s is a splice of the show outro (session 15:46.5 to 15:52.3)**, not "Reine". First 0.5 s faded in. |
| 2 | `sc_full_willpincince_160k.m4a` | SoundCloud fan reupload of the full session (2020-09-09): https://soundcloud.com/willpincince/juice-wrld-mouv-freestyle | 952.55 s | AAC-LC 160k, 44.1 kHz | **16.0 kHz hard** (16 to 17 kHz band at -60 dB) | **USE for context only.** It supplies the 8:53 to 8:57 lead-in, the real tail after 10:55.3 (the transition, about 10:54 to 11:05) and the other 7 beats. Same timeline as Dailymotion. NCC with the FB master is 0.99 to 1.00. Loudness-match before splicing. |
| 3 | `dm_mouv_full_session_288p.mp4` (+ `.info.json`) | Mouv' official Dailymotion x6voyn7, file uploaded 2018-10-19 15:06 UTC, published 2018-10-20 08:00 UTC: https://www.dailymotion.com/video/x6voyn7 | 952.55 s | HE-AAC 64k (SBR), 512x288 H.264 | low real bandwidth; the meter's 24.0 kHz is SBR-synthesized | **Reference only.** Official provenance, official chapter list and the only full-session video. |
| 4 | `sc_campfire_160k.m4a` | SoundCloud fan reupload (2019-12-22): https://soundcloud.com/will-tompkins-977052812/juice-wrld-freestyle-sur-reine-de-dadju-campfire-freestyle | 124.41 s | AAC-LC 160k | **~15 kHz** (15 to 16 kHz band at -52 dB) | Reference only (redundant). Same official edit, outro splice included. |
| 5 | `fb_mouv_audio.m4a` | Facebook DASH audio of the same post | 124.37 s | HE-AAC 48 kbps | SBR; meter 17.0 | **Reject.** Far worse than rank 1. Left in place (pre-existing). |

Where the "Reine" part sits (verified; H):
- Excerpt t = 0 is session 537.00 s (8:57.00). Mouv's chapter marks are 8:55 ("Reine") and 10:54 ("Comportement").
- In the excerpt, the beat starts at about 3.15 s (studio song time 0). Host talk sits over the studio intro at about 0 to 13 s: the Whisper transcript has an English intro with a "DJ Muxxa" shout-out at about 12.6 s. That fits the lyric sites crediting DJ Muxxa on the intro.
- The beat and the vocal end at about 117.5 to 118.3 s (session about 10:54.5 to 10:55.3). The beat does **not** keep running after Juice stops.

## 3. Studio "Reine" files, ranked (`/home/user/test/work/sources/reine/`)

Official reference: Dadju "Reine", *Gentleman 2.0* track 6, ISRC TCADB1727917, Deezer 429974992 (199 s, bpm 97.97), iTunes 1440904214 (199.267 s). Single released 2017-05-05.

| Rank | File | Origin | Duration | Codec | Real cutoff | Identity check | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `dm_reine_studio_shedevtv_128k.m4a` (+ `.info.json`) | Dailymotion xao6v7y "DADJU - Reine", third-party channel SHÉDEV TV, uploaded 2026-07-10: https://www.dailymotion.com/video/xao6v7y | 198.53 s (0.32 s leading silence; natural decay to below -90 dB at the end) | AAC-LC 128k, 44.1 kHz | **~15.5 kHz** (15 to 16 kHz band at -32 dB, 16k+ gone) | NCC **0.994** vs Deezer preview (starts at file 48.31 s), **0.999** vs Apple preview (57.33 s), **0.994** vs official Dadju SoundCloud snippet (0.323 s). Zero drift. | **USE: the full studio master.** Unofficial uploader, but the audio is identical to the official previews. Decoded peak 1.49: decode to float and add headroom. |
| 1a | `master_full.wav`, `master_from8.wav` | derived by the pipeline from rank 1 (03:56 to 03:57) | 198.53 s / 190.53 s | PCM f32 | same as rank 1 | NCC 0.994 vs Deezer preview at the expected offsets (from8 = rank 1 minus 8.0 s) | Derived working copies. Correct. |
| 2 | `previews/am_reine_1440904214_preview30.m4a` (+ `am_preview.wav` decode, verified identical) | Apple/iTunes official 30 s preview: https://itunes.apple.com/lookup?id=1440904214&country=fr | 30.0 s | AAC-LC ~266 kbps | **~20 kHz** | NCC 0.999 vs rank 1 at file 57.33 to 87.33 s | Reference, and a possible **high-fidelity patch** for that 30 s window, which contains the 4-bar beat-only break. |
| 3 | `dm_reine_studio_parolesfr_64k.m4a` (+ `.info.json`) | Dailymotion x6544rx "Dadju - Reine (Paroles/Lyrics)", 2017-10-18: https://www.dailymotion.com/video/x6544rx | 197.18 s | HE-AAC 64k (meter's 18.2 kHz is SBR) | low (SBR) | Same master: NCC 0.952 onset and 0.996 waveform. This file's timeline runs 0.10 s ahead of rank 1. It lacks only the near-silent last ~1.25 s, which is already below -70 dB. | Backup / cross-check only. |
| 4 | `dz_reine_preview.mp3` (byte-identical to `previews/dz_reine_429974992_preview30.mp3`, md5 f5e428a1...) | Deezer official 30 s preview of 429974992: https://api.deezer.com/track/429974992 | 29.99 s | MP3 128k | ~16 kHz (MP3 lowpass) | rank 1 at file 48.31 to 78.30 s | Reference only. One of the two copies is redundant. |
| 5 | `sc_reine_official_snippet30_128k.mp3` (+ `.info.json`) | Dadju official SoundCloud, 2017-06-27: https://soundcloud.com/dadju/reine | 29.75 s | MP3 128k | ~16 kHz | rank 1 at file 0.323 to ~30.1 s (the song intro) | Reference only (official identity of the intro). |

## 4. Instrumentals (both re-made; no official instrumental found)

| Rank | File | Origin | Duration | Codec | Real cutoff | Checks | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `dm_reine_karaoke_remake_64k.m4a` (+ `.info.json`) | Dailymotion x6dvt1c "Dadju - Reine KARAOKE / INSTRUMENTAL", Karaoke LIVE, 2018-01-29: https://www.dailymotion.com/video/x6dvt1c | 204.34 s | HE-AAC 64k (meter's 24 kHz is SBR) | low (SBR) | Same tempo (best ratio 1.000), same key and tuning (0 to -2 cents vs master), structurally aligned with `master_t ≈ karaoke_t - 5.1 s` (onset NCC 0.42; not the same audio) | Use with caution. It is the closest arrangement, but low fidelity, and nobody has checked it for guide or backing vocals. |
| 2 | `sc_reine_instr_unesxbl_remake_128k.mp3` (+ `.info.json`) | SoundCloud 1361041834 "DADJU - Reine (INSTRUMENTAL) PROD BY UNES XBL", 2022-10-11, **CC BY-NC-SA**: https://soundcloud.com/unes-xbl/dadju-reine-instrumental-prod-by-unes-xbl | 197.54 s | MP3 128k | ~16.8 kHz | Same tempo (ratio 1.000), same tuning (0 cents), best structural offset `master_t ≈ unes_t + 8.9 s` (onset NCC 0.38; ambiguous because the beat is loop-based) | Use with caution. Cleaner audio and licence-friendly for a non-commercial edit (attribution plus share-alike). Not the original sound. |

The most faithful "instrumental" of the real record will be an ML separation of `master_full.wav`, which the pipeline is running (`work/stems/master_from8`). The only official beat-only audio is the studio's 4-bar break (song about 0:58.8 to 1:08.6), which the Apple preview has at about 20 kHz.

## 5. How the DJ played "Reine" (verified here; resolves gaps in three agents' reports)

- **Source:** the studio master itself, started from the song's very first beat. Mapping:
  `master_file_t = 1.0250 * excerpt_t - 2.905 s` (song_t ≈ 1.025 * excerpt_t - 3.23 s).
  Global onset-envelope NCC is 0.58 at ratio 1.0250. Every other ratio from 1.000 to 1.045 scores ≤ 0.14. Every 6 s window from 6 to 114 s scores 0.42 to 0.82 on the single linear map, against a baseline of about -0.05, so **no cuts, loops or rewinds were detected**. This agrees independently with the pipeline's `work/analysis/align_master.json` (slope 0.97565, intercept 2.8398, which is the same map inverted). (H)
- **Coverage:** song 0:00 to about 1:57, i.e. intro, verse 1, pre-chorus 1, chorus 1, 4-bar break, verse 2, pre-chorus 2 and chorus 2. It stops right before the bridge (about 1:57.6 on the dossier's bar grid). (M-H)
- **Tempo:** 97.97 x 1.025 = **100.42 BPM** live, which matches the agents' 100.35 to 100.48 estimates and essentia's 100.68. (H)
- **Pitch:** **key-locked time-stretch, not varispeed.** The long-term spectrum shift of the live instrumental stem vs the master is **0 cents** (r = 0.885; +42 c gives r ≈ 0). As a sanity test, a varispeed copy of the master reads +42 c (r = 0.994). The freestyle_sources claim of "+0.35 to 0.4 semitone" is **wrong**. (H)
- **Bass / EQ:** the "bass-light first 1:36" comes partly from the song's own arrangement: the master's low end rises by about 5 to 8 dB at song about 1:31 to 1:40. The rest looks like DJ EQ. Compared with the studio at the mapped times, the live instrumental stem is 4 to 6 dB lighter in bass before that point, 6 to 8 dB heavier after it, and has deep low cuts at excerpt about 0:04 to 0:12 and about 1:00 to 1:08 (the break). (M; the stem has leakage and has not been checked by listening)
- **Dadju's vocal in the bed?** Still open. The Whisper transcript of the separated vocal is English throughout, with no French lines, but that is weak evidence. To check, listen to excerpt about 0:40 to 1:00 (studio chorus 1) on the instrumental stem, or look for French formants in the vocal stem.

## 6. Contradictions between agents, and how they resolve

| Topic | Conflict | Resolution | Conf. |
|---|---|---|---|
| End of the excerpt | session: a continuous cut 8:57.03 to 11:01.30 with "transition" at the end. freestyle_sources: 118.3 s of Reine plus a spliced show outro. | **freestyle_sources is right.** The splice is confirmed (section 2). session.md now carries a correction note. | H |
| Live pitch | session: same key, A440 (key-locked). freestyle_sources: "+0.35 to 0.4 semitone". | **Key-locked, 0 cents** (section 5). | H |
| Where the live beat sits in the studio song | reine: "not established". reine_sources: weak. | **Established:** from song 0:00 at 1.025x (section 5). | H |
| 8:58 to 9:10 "no steady tempo" (freestyle_sources) vs beats from 0.46 s (beat tracker) | – | That stretch is the studio's 4-bar intro, with host talk on top (transcript). The beat is present from excerpt about 3.15 s. | M-H |
| Preview positions in the song | reine.md: Deezer at 47.7, Apple at 56.7. reine_sources: 48.31 / 57.33 (file time). | The file has 0.32 s leading silence, so song time is 47.99 / 57.01. reine.md was about 0.3 s early; it now carries a correction note. | H |
| Album date | iTunes 2017-11-24 vs Deezer 2017-11-25 | Same release, time-zone or territory offset. The single is 2017-05-05. | H |
| Session date | "19 octobre" (Mouv') vs Paris show 20 Sep 2018 (Getty) | **Unresolved.** The full-session file was uploaded at 17:06 Paris time on 19 Oct 2018, which fits either a same-day recording or an earlier taping. | – |
| Full-session real bandwidth | session: DM "content to ~20 kHz". freestyle_sources: SBR above ~11 kHz. | It is HE-AAC 64k (ffprobe), so anything above the SBR crossover is synthetic. Either way it is **reference only**. | H |

## 7. Rejected / deleted files (for the record)

- `benoit_full.wav`, `benoit_tail_from94.wav`: SoundCloud 1667838315 (Benoit Toussaint), a cover or re-recording. Same tempo and key, but waveform NCC is 0.03 to 0.04 vs the Deezer, Apple and official-snippet references, and stays ≤ 0.06 across L, R, side and speed variants from 0.98 to 1.02. **Deleted by the pipeline after the switch.** Any stems or analysis built on it (`work/analysis/reine_studio_music.json`, `align_benoit_coarse.json`, `align_anchors.json`, `work/stems/reine_tail`) are stale and should not be used.
- Deleted by the sourcing agents: SoundCloud full-session duplicates (novanity, axlpwrt byte-identical; bferland equivalent; jakehelmly, borat, johnnymason worse), fan trims (cbnwiretrap, gtaismy, khaliljuwan, napal), the remake CAFFEINEKOOLAID, "Mind Games" (the Comportement section), the DM Reine excerpt (same edit, SBR), and slowed, AI, remix and silent "Reine" copies. Details are in the agents' file lists.

## 8. Open issues

1. **Audiomack official upload** (Juice WRLD's verified account, "Mouv' Live Club Freestyle", song id 5006105, 953 s, 2018-10-29): https://audiomack.com/juicewrld/song/mouv-live-club-freestyle . It could not be downloaded: yt-dlp 2026.10.21's extractor fails, and reading the site's player auth would be circumvention, which we did not do. It is the only remaining chance of a full-session copy better than 16 kHz, so the user could check it by hand. It would **not** beat the FB master for the Reine part unless it is lossless.
2. **No Mouv' Facebook post of the full session** was found (one more web search came up empty). If one exists it might carry the ~317k audio.
3. **The recording date is still unverified** (Mouv' "19 octobre" 2018 vs a September Paris visit). The Mouv' interview (https://www.dailymotion.com/video/x6vxdde) has not been transcribed. It might settle the date.
4. **Official instrumental:** none on Deezer, SoundCloud, Dailymotion or archive.org. Apple, Spotify and YouTube could not be checked (403 or blocked). For a studio-rebuild variant, rely on separating the master and use the remakes only for arrangement and key.
5. **Guide vocals in the karaoke remake**, and **Dadju's vocal in the live bed**, are both unchecked (section 5).
6. **"Campfire" origin** is still unexplained. "Ball Out", the second fan name, fits the hook (the Whisper transcript has "ball out" in the repeated hook line, `work/analysis/transcript_vocals.json`). (M)
7. YouTube dates and titles for OV9ucgzzvf8 and bqKBIgol3kM are unverified, because YouTube is blocked and we did not try to get around it.
8. Housekeeping: `reine/dz_reine_preview.mp3` and `reine/previews/dz_reine_429974992_preview30.mp3` are byte-identical, and `fb_mouv_audio.m4a` is a reject that was left in place.
