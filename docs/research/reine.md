# Research dossier: the beat, Dadju "Reine" (2017)

Compiled 2026-10-25 for the Juice WRLD "Campfire Freestyle" fan edit, which is a freestyle over this beat.
Every claim has a source and a confidence (H = high, M = medium, L = low).
"Own analysis" means numpy/scipy measurements on the official 30 s previews, done in this session
(scripts: `/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/scripts/`).
No lyrics are reproduced here.

> **Critic corrections (2026-10-25, completeness review; details in `sources_summary.md`):**
> - **Section 10 is now resolved.** The freestyle beat *is* this studio master, started from the song's first beat and played at **1.0250x with key lock**. The measured pitch offset is 0 cents (a varispeed would read +42 c). Map: `master_file_t = 1.0250 * excerpt_t - 2.905 s`, valid from excerpt about 3.2 s to 117.5 s, which is song 0:00 to about 1:57 (end of chorus 2, just before the bridge). 97.97 x 1.025 = 100.42 BPM live, which matches the live tempo estimates.
> - **Section 9: the preview positions given there are about 0.3 s too early.** On the waveform-verified full master (`work/sources/reine/dm_reine_studio_shedevtv_128k.m4a`, 0.32 s leading silence) the Deezer preview starts at file 48.31 s (song about 47.99 s) and the Apple preview at file 57.33 s (song about 57.01 s). The section 9 figures of 47.7 / 56.7 came from the LRC estimate and are about 0.3 s early. Use the waveform figures.
> - The 207 s "Reine - Edit" remains unexplained. The full studio copy we hold is the 199 s album/single master.

---

## 1. Identity and identifiers

| Field | Value | Source | Conf. |
|---|---|---|---|
| Title / artist | "Reine", Dadju (Djuna Nsungula) | https://en.wikipedia.org/wiki/Reine_(song) | H |
| ISRC | `TCADB1727917` (same ISRC on the original album and the reissue) | https://api.deezer.com/track/429974992 , https://musicbrainz.org/ws/2/recording/cc76391e-e8a4-4b03-aa89-8a7267563a24?fmt=json&inc=isrcs | H |
| Album | *Gentleman 2.0*, track 6 of 19 | https://api.deezer.com/album/51831522 , https://fr.wikipedia.org/wiki/Gentleman_2.0 | H |
| Album UPC | 602567165156 | https://api.deezer.com/album/51831522 | H |
| Deezer track id (original album) | **429974992** (album 51831522) | https://api.deezer.com/track/429974992 | H |
| Deezer track id (reissue) | 634773332 (album 87792032, "Gentleman 2.0 (Réédition)"), same ISRC, same 199 s | https://api.deezer.com/track/634773332 | H |
| Apple Music / iTunes | track 1440904214, album 1440904018 | https://itunes.apple.com/lookup?id=1440904214&country=fr | H |
| Spotify track id | 1bxP4M9ICllcg7mel8kH89 | https://songbpm.com/@dadju/reine (outbound link) | M |
| MusicBrainz recording | cc76391e-e8a4-4b03-aa89-8a7267563a24 | https://musicbrainz.org/recording/cc76391e-e8a4-4b03-aa89-8a7267563a24 | H |
| Official SoundCloud | https://soundcloud.com/dadju/reine (a 30 s snippet only, uploaded 2017-06-27) | yt-dlp metadata of that URL | H |

Note on the ISRC: the "TC" prefix looks like an ISRC issued by TuneCore, which would mean the single was first
distributed independently before the Polydor deal. Seysey's own self-released tracks on Deezer also carry TCA* ISRCs.
**This is not verified (L).**

## 2. Release dates

| Event | Date | Source | Conf. |
|---|---|---|---|
| Single release ("debut single" of the album) | **5 May 2017** | https://en.wikipedia.org/wiki/Reine_(song) ; https://fr.wikipedia.org/wiki/Gentleman_2.0 (singles list); iTunes track `releaseDate` 2017-05-05T12:00:00Z (https://itunes.apple.com/lookup?id=1440904214&country=fr) | H |
| Official music video ("DADJU - Reine (clip officiel)") | 5 May 2017, same day as the single (YouTube cannot be checked from this machine) | https://en.wikipedia.org/wiki/Reine_(song) | M |
| Origin | First heard as a short Instagram/YouTube clip in Dadju's "G 2.0 Live" series. It was the fans' favourite, they asked for a full version, and it became the first single. A French mirror says the full version came out "en avril 2017", which conflicts with 5 May. | https://areq.net/lang/fr/Dadju.html (mirror of fr.wikipedia "Dadju") | M |
| Album *Gentleman 2.0* | 24 Nov 2017 (Deezer gives 2017-11-25, probably a time-zone or territory offset) | https://itunes.apple.com/lookup?id=1440904018&country=fr ; https://fr.wikipedia.org/wiki/Gentleman_2.0 ; https://api.deezer.com/album/51831522 | H |
| Album reissue | 5 Oct 2018 (fr.wikipedia, MusicBrainz FR release). The Deezer "Réédition" album is dated 2019-02-20, which matches a MusicBrainz release coded AF. | https://fr.wikipedia.org/wiki/Gentleman_2.0 ; https://musicbrainz.org/ws/2/recording/cc76391e-e8a4-4b03-aa89-8a7267563a24?inc=releases&fmt=json ; https://api.deezer.com/album/87792032 | M |
| Charts and certification | FR (SNEP) peak #2; BE Wallonia #36; CH #84; SNEP Diamond | https://en.wikipedia.org/wiki/Reine_(song) | M |

## 3. Label

| Field | Value | Source | Conf. |
|---|---|---|---|
| ℗ line (Apple) | "℗ 2017 Amaterasu" | https://itunes.apple.com/lookup?id=1440904018&country=fr | H |
| Label (Deezer) | Universal Music Division Capitol Music France | https://api.deezer.com/album/51831522 | H |
| Label (fr.wikipedia) | Polydor / Universal Music France | https://fr.wikipedia.org/wiki/Gentleman_2.0 | M |
| Context | Dadju self-produces through his company **Amaterasu Prod**, and the album was signed to Polydor | https://fr.billboard.com/?p=661 (Billboard France, 8 Dec 2020) | M |

## 4. Producer, composer, writers

| Role | Name | Source | Conf. |
|---|---|---|---|
| Composer / beat producer | **Seysey** (real name Yohann Doumbia, b. 1988 Suresnes, conservatoire-trained multi-instrumentalist) | Composer column in the track table at https://fr.wikipedia.org/wiki/Gentleman_2.0 ; "Composer: Seysey" at https://www.karaoke-version.com/mp3-backingtrack/dadju/reine.html ; real name from https://www.nrj.fr/artistes/seysey/biographie (seen only in search snippets: the page returns 403 to fetchers) | M-H |
| Producer tag | Two independent community LRC timings have a "(Seysey)" tag line at about 0:05.4, so the beat seems to open with an audible producer tag | https://lrclib.net/api/get/2490537 , https://lrclib.net/api/get/7100155 | M |
| Lyricist | Dadju (Djuna Nsungula) | https://fr.wikipedia.org/wiki/Gentleman_2.0 (auteur); https://www.karaoke-version.com/mp3-backingtrack/dadju/reine.html | H |
| Songwriters (en.wikipedia) | Djuna Nsungula, Yohann Doumbia, i.e. Dadju and Seysey | https://en.wikipedia.org/wiki/Reine_(song) | H |
| **Disagreement** | en.wikipedia's infobox gives the producer as "Dadju". This probably means executive or self-production through Amaterasu. Every other credit source names Seysey as composer of the beat. | https://en.wikipedia.org/wiki/Reine_(song) | M |
| Not checked | Genius, Qobuz, Tidal and Discogs credits (Genius and Musixmatch cannot be fetched here; no Discogs page was found) | n/a | n/a |

## 5. Official duration

| Source | Duration | Conf. |
|---|---|---|
| iTunes `trackTimeMillis` | **199.267 s (3:19.27)** | H (https://itunes.apple.com/lookup?id=1440904214&country=fr) |
| MusicBrainz | 199.266 s | H (https://musicbrainz.org/recording/cc76391e-e8a4-4b03-aa89-8a7267563a24) |
| Deezer | 199 s, both ids | H (https://api.deezer.com/track/429974992) |
| Wikipedia / SongBPM / Karaoke-Version | 3:19 | H |

There is also a MusicBrainz recording called **"Reine - Edit", 206.786 s (3:26.8)**, on a FR *Gentleman 2.0* release dated 2018-03-16
(https://musicbrainz.org/recording/b9e4e6fe-213b-4bac-bdab-00d8c61d63c4). An LRCLIB entry of 207 s
(https://lrclib.net/api/search?track_name=Reine&artist_name=Dadju, id 36783460) may be the same version. Its contents are unknown (L).
Karaoke-Version says the song "ends without fade out" (M).

## 6. Tempo and key: every source

| Source | BPM | Key | Notes | How obtained | Conf. |
|---|---|---|---|---|---|
| Deezer API `bpm` | **97.97** | n/a | `gain` -12.4 | https://api.deezer.com/track/429974992 (fetched) | H that this is the stated value |
| SongBPM (Spotify data) | **98** (double time 196) | **D major** | 4/4, 3:19 | https://songbpm.com/@dadju/reine (fetched) | H |
| Tunebat | 98 | D major, Camelot **10B** | album date 24 Nov 2017 | https://tunebat.com/Info/Reine-Dadju/1bxP4M9ICllcg7mel8kH89 (page 403; values from search-engine snippet) | M |
| Songdata.io | 98 (half 49, double 196) | D major, 10B | | https://songdata.io/track/1bxP4M9ICllcg7mel8kH89/Reine-by-Dadju (page 403; snippet) | M |
| Musicstax | BPM not seen | D major | | https://musicstax.com/track/reine/1bxP4M9ICllcg7mel8kH89 (page 403; snippet) | L-M |
| GetSongBPM | 98, 4/4 | key not seen | | https://getsongbpm.com/song/reine/834Xn2 (page 403; snippet) | L-M |
| Chordify | 97 | not seen | | https://chordify.net/chords/dadju-songs/reine-2-chords (page 403; snippet) | L |
| Karaoke-Version (re-recorded by session musicians) | 98 | **E minor** ("same key as the original: Em") | | https://www.karaoke-version.com/mp3-backingtrack/dadju/reine.html (fetched) | M |
| **Own analysis**, Apple 30 s preview (AAC, full band) | **98.00** (top candidates 97.90 to 98.10) | Pitch-class set is D major / B minor / E dorian: C# present (0.05), C natural absent (0.01), G# absent (0.02). Bass energy peaks on **E** (0.29), then D (0.23) and F# (0.14). | tuning **A440** (-0.4 cents) | `key_tempo.py` | M |
| **Own analysis**, Deezer 30 s preview (MP3 128k) | 195.05, which is double time (~97.5; this estimator is less precise on that clip) | Same pitch set. Krumhansl correlation: D major 0.825 > A major 0.803 > B minor 0.642 > E minor 0.585 | tuning -0.1 cents | `key_tempo.py` | M |
| Not found | AcousticBrainz (no submissions for either MBID); findsongtempo.com (DNS failure) | | | https://acousticbrainz.org/api/v1/cc76391e-e8a4-4b03-aa89-8a7267563a24/count | n/a |

**Reconciliation**
- **Tempo: 98 BPM, 4/4.** All sources agree to within ±1 BPM: 97 from Chordify, 97.97 from Deezer, 98 from everyone else and from our analysis.
  The half and double-time readings (49 and 196) are the same tempo. The beat has a half-time R&B/afro-pop feel, so a DJ tool may report 196 or 49.
  One bar is 2.449 s and one beat is 0.612 s. (H)
- **Key: D major and E minor are two readings of the same notes.** The material uses D major's key signature (2 sharps, C#, no C natural).
  The bass sits mostly on E and D, so the music can be heard either as D major (Spotify-derived sites) or as an E-centred minor mode with a raised 6th, i.e.
  **E dorian** (Karaoke-Version's "Em"). Natural E minor (Camelot 9A) is wrong because it needs C natural, which is absent.
  **For harmonic matching, treat it as the D major / B minor pitch set, Camelot 10B.** (M)

## 7. Song structure with timestamps

Method: two independently timed community LRC files on LRCLIB (ids 2490537 and 7100155, both 199 s) agree within about 0.2 s on every line.
I combined them with the block layout on a lyric site (https://www.paroles.net/dadju/paroles-reine: intro 1 line, then 11, 9, 5+3, 9, 1+11, 9, 5 lines)
and with a 98 BPM bar grid (bar = 2.449 s) that starts at t ≈ 0. Section names are my labels: no labelled source such as Genius could be fetched.
The grid predicts the outro start at bar 72 = 176.33 s and the LRC says 176.32 s. Most sung lines begin 0.5 to 0.9 s *before* the downbeat (pickups).
Confidence: section boundaries M; exact seconds ±0.5 s; labels M/L.

| # | Section | Bars | Grid time (downbeat) | First sung line in LRC | Notes |
|---|---|---|---|---|---|
| 1 | Intro (beat + "Seysey" tag ~0:05.4) | 4 | 0:00.0 – 0:09.8 | — | |
| 2 | Verse 1 | 8 | 0:09.8 – 0:29.4 | 0:09.1 | about one line per bar; Dadju name-drop ~0:21.5 |
| 3 | Pre-chorus 1 | 4 | 0:29.4 – 0:39.2 | 0:28.5 | |
| 4 | Chorus 1 | 8 | 0:39.2 – 0:58.8 | 0:38.5 | 8-line hook, repeated identically later |
| 5 | **Instrumental break (no lead vocal)** | 4 | 0:58.8 – 1:08.6 | (vocals end 0:58.6) | the cleanest beat-only stretch of the studio track |
| 6 | Verse 2 | 8 | 1:08.6 – 1:28.2 | 1:08.2 | sparser: one line per 2 bars |
| 7 | Pre-chorus 2 | 4 | 1:28.2 – 1:38.0 | 1:27.3 | |
| 8 | Chorus 2 | 8 | 1:38.0 – 1:57.6 | 1:37.4 | |
| 9 | Bridge (6-line block sung twice) | 16 (2×8) | 1:57.6 – 2:36.7 | 1:56.7 / 2:16.1 | |
| 10 | Chorus 3 | 8 | 2:36.7 – 2:56.3 | 2:35.8 | |
| 11 | Outro (vocal tag on the hook) | 4 | 2:56.3 – 3:06.1 | 2:56.3 | last sung line ~3:04, LRC end mark 3:05.9 |
| 12 | Instrumental tail | ~5.4 | 3:06.1 – 3:19.3 | — | no fade-out (Karaoke-Version) |

Total: 72 bars to the outro, plus about 9.4 bars of outro and tail, which gives about 81.4 bars = 199.3 s. This matches the official duration.

## 8. Official instrumental?

**No official instrumental was found (M).**
- Deezer: no instrumental version among Dadju's albums and singles, and searches for "reine instrumental", "dadju instrumental",
  "gentleman 2.0 instrumental" and "seysey" return none (https://api.deezer.com/artist/4803754/albums?limit=200 ; https://api.deezer.com/search?q=reine%20instrumental). (H for Deezer)
- Dadju's official SoundCloud has only the 30 s vocal snippet (https://soundcloud.com/dadju/reine). (H)
- Apple and iTunes search returned HTTP 403 from this machine, and YouTube is blocked, so neither could be checked. **Gap.**
- Unofficial options:
  - **Karaoke-Version**: a paid instrumental re-recorded by session musicians, with or without backing vocals, 98 BPM, Em, 3:19. It contains none of the original recording and no stem separation
    (https://www.karaoke-version.com/mp3-backingtrack/dadju/reine.html). This is a **remake, not the original beat**. (H)
  - SoundCloud remakes: "DADJU - Reine (INSTRUMENTAL) PROD BY UNES XBL", 197.5 s, 2022, CC BY-NC-SA
    (https://soundcloud.com/unes-xbl/dadju-reine-instrumental-prod-by-unes-xbl); "Dadju-Reine Instrumental-Remix" by TheAyGirl Beatz, 203.1 s, 2017
    (https://soundcloud.com/theaygirl_beatz/dadju-reine-instrumental-remix). Neither is official. (H that they exist)
- The only official beat-only audio in public reach is the **4-bar break at about 0:58.8–1:08.6** of the studio track. Both previews contain it:
  about 0:11–0:21 of the Deezer preview and about 0:02.2–0:11.3 of the Apple preview (own analysis, M).

## 9. 30 s previews

| Store | Id | Preview URL | Notes |
|---|---|---|---|
| Deezer (original album) | 429974992 | `https://cdnt-preview.dzcdn.net/api/1/1/f/5/e/0/f5e428a18064fc927f432371f3c2fcb9.mp3?hdnea=exp=1792896915~acl=/api/1/1/f/5/e/0/f5e428a18064fc927f432371f3c2fcb9.mp3*~data=user_id=0,application_id=42~hmac=dd06606acdcda29a1f0b98cf67405188e321daa0e5c3b832c56c3e0b2c7833be` | **The signed token expires about 15 minutes after issue** (this one at 2026-10-25 02:55 UTC). Get a fresh one from `https://api.deezer.com/track/429974992`, field `preview`. The file's MD5 is `f5e428a18064fc927f432371f3c2fcb9`, the same as the hash in its URL path. MP3 128 kbps, 29.99 s; real cutoff 16.7 kHz. |
| Deezer (reissue) | 634773332 | `https://cdnt-preview.dzcdn.net/api/1/1/7/a/b/0/7ab82c76dcf82538d14091b2463e5a1b.mp3?hdnea=exp=1792896915~acl=/api/1/1/7/a/b/0/7ab82c76dcf82538d14091b2463e5a1b.mp3*~data=user_id=0,application_id=42~hmac=1756e98414cf69e4944dee92a198f963f255d509d1b6a7c3fb557ee0ce4967e8` | same expiry rule, from `https://api.deezer.com/track/634773332` |
| Apple / iTunes | 1440904214 | `https://audio-ssl.itunes.apple.com/itunes-assets/AudioPreview221/v4/8e/94/58/8e945825-0dea-d6f7-e97a-ad5f7fe33bc8/mzaf_15212222777220609975.plus.aac.p.m4a` | unsigned. AAC about 268 kbps, 30.0 s, **real cutoff 20.9 kHz**: the best-quality official excerpt |

**Where the previews sit in the song (own analysis, M):** cross-correlating the two previews puts the Apple preview **9.02 s later** than the Deezer one
(normalised correlation 0.997 over 21 s of overlap). Matching the low-vocal stretch of each preview to the LRC break, and the moments where vocals stop and start again, gives:
- Deezer preview ≈ song **0:47.7 → 1:17.7**: end of chorus 1, the 4-bar instrumental break, then the start of verse 2.
- Apple preview ≈ song **0:56.7 → 1:26.7**: chorus tail, the break, then verse 2.

Local copies, for reference only and kept outside the project tree:
`/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/dl/dz_reine_429974992_preview30.mp3`,
`/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/dl/am_reine_1440904214_preview30.m4a`.

## 10. Notes for the freestyle pipeline (low confidence, check in the analysis step)

- The same tempo estimator gave 98.00 BPM on the Apple preview and **≈100.35 BPM** on the Mouv' freestyle audio
  (`/home/user/test/work/sources/freestyle/fb_mouv_hd.mp4`), consistently across four 28 s segments (one segment read 200 = double time).
  Measured tuning stayed within ±3 cents of A440. One explanation is that the DJ played the beat about +2.4% faster with key-lock (time-stretched, not pitched).
  The rap vocal could also bias the estimate. **Unverified (L).**
- Raw-waveform cross-correlation between preview chunks and the freestyle gave only weak, inconsistent matches (r ≤ 0.25). The loop-based beat and the live mix
  make this method unreliable, so **the alignment is not established here**.

## 11. Gaps and things I could not verify

- Genius, Musixmatch, lescharts.com, Tunebat, Musicstax, GetSongBPM, Songdata, Chordify and NRJ pages return 403 or are blocked for fetchers. Their values come from
  search-engine snippets only and are marked M or L. I did not try to bypass this.
- YouTube is blocked: I could not check the official clip's date, length or timings, or any instrumental uploads there.
- iTunes Search returned 403, so I could not check for an "instrumental" product on Apple.
- I found no official liner notes or Discogs credits. Mixing and mastering engineers are unknown.
- The "Reine - Edit" (3:26.8) recording on MusicBrainz is unexplained.
- The TuneCore origin of the ISRC is an inference.
- Section labels are inferred from LRC timing and line repetition, not taken from an official or labelled source.
