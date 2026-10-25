# Session dossier: Juice WRLD at Mouv' Live Club, Paris, October 2018

Scope: the radio session that contains the Juice WRLD freestyle on Dadju's "Reine" (the "Campfire Song" / "Campfire Freestyle").
Compiled 2026-10-25. Each claim has a source and a confidence rating (H = high, M = medium, L = low).
"Measured" means I worked it out from the audio myself (method in section 11). Nobody else has checked those numbers yet.
This file quotes no lyrics.

> **Critic corrections (2026-10-25, completeness review; details in `sources_summary.md`):**
> 1. **Section 5 is wrong about the excerpt's end.** The excerpt is **not** one continuous cut from 8:57.03 to 11:01.30. Excerpt 0.0 to 118.3 s is session 8:57.00 to 10:55.3. Windowed NCC against the SoundCloud full copy is 0.99 to 1.00 in every window, with a constant offset of 537.00 s. Excerpt **118.5 to 124.3 s is spliced from the very end of the session (15:46.5 to 15:52.3, the show outro)**, with NCC 0.89 to 0.998 there and about 0 at the continuous offset. So the excerpt has no "transition into the next beat".
> 2. **Section 9 can now say where the beat comes from.** The live beat is the studio "Reine" master (Dailymotion xao6v7y, waveform-verified), played **from the song's very start** at **1.0250x speed with key lock**. The measured pitch offset against the master is 0 cents. A varispeed test copy of the same file reads +42 cents, as expected. Map: `master_file_t = 1.0250 * excerpt_t - 2.905 s` (master has 0.32 s leading silence). It holds continuously from excerpt about 3.2 s to about 117.5 s, which is song 0:00 to about 1:57 (intro through the end of chorus 2). No cut or loop shows up at 6 s resolution. This agrees independently with `work/analysis/align_master.json` (slope 0.97565, intercept 2.8398).
> 3. **The bass-light first 1:36 comes from both the arrangement and the DJ.** The studio master's own low end rises by about 5 to 8 dB at about song 1:31 to 1:40 (pre-chorus 2 into chorus 2). The live instrumental stem is about 4 to 6 dB lighter in bass than the studio before that and about 6 to 8 dB heavier after it. It also has deep low cuts at excerpt about 0:04 to 0:12 (intro) and about 1:00 to 1:08 (the studio's 4-bar break). This suggests DJ EQ or filter moves on top of the arrangement. Confidence M: it rests on separated-stem leakage and has not been checked by listening.
> 4. Open question 6 ("Mind Games") has a probable answer: the SoundCloud fan cut "FREESTYLE MOUV' MIND GAMES" (520255587) is the *Comportement* segment (see freestyle_sources results). Confidence M.

---

## 0. Summary

- **What:** Juice WRLD was the guest of DJ Muxxa on Mouv' Live Club. Mouv' is Radio France's hip-hop station. He freestyled over 8 French rap and pop beats in a 15:53 session. "Reine" is the 6th beat, starting at **8:55** in Mouv's chapter list. The session also included an interview, which Mouv' published separately.
- **Date:** Mouv' gives the date as **19 October 2018**. The year is confirmed by Mouv's Dailymotion upload, whose file went up on 2018-10-19 at 15:06 UTC and was published on 2018-10-20. The same day, 19 Oct 2018, Epic released *WRLD ON DRUGS* with Future.
- **One date question is still open.** Getty has a photo of Juice WRLD performing in Paris (Élysée Montmartre) on **20 September 2018**, during a short European headline run. No source places him in Paris in October 2018. So "19 octobre" could be the recording date or only the broadcast or publication date. See section 3.
- **Release status:** The session is not on Spotify, Apple Music or Deezer (Deezer and iTunes catalogs checked). However, the **full 15:53 session is on Juice WRLD's verified Audiomack account**, titled "Mouv' Live Club Freestyle". It was posted on 2018-10-29, is stream-only, and has about 1.54M plays. Everything else is a Mouv' video or a fan reupload.
- **The nickname:** "Campfire" was already in fan SoundCloud titles on **2018-10-22**, which is 2 days before Mouv' posted the "Reine" excerpt. No source explains the name. Mouv's YouTube excerpt is now indexed with "Campfire Song" [official] in its title.
- **Measured: what the DJ played.** The "Reine" beat runs at about **100.4 BPM**, while the studio version is about **98.0 BPM**, so it is roughly 2.4% faster. It is in the **same key and tuning** as the studio record. That points to a key-locked tempo change, or a different instrumental file. It does not point to a vinyl-style speed-up.
- **Measured: arrangement.** For the first ~1:36 of the excerpt the beat has very little bass. The full low end comes in for about the last 20 s. The beat and the vocal both stop at about 1:57 of the excerpt.

---

## 1. Date and venue

| Claim | Source | Conf. |
|---|---|---|
| Mouv' says he was Muxxa's guest "le 19 octobre dans Mouv' Live Club". The description gives no year. | Mouv' Dailymotion description, full session: https://www.dailymotion.com/video/x6voyn7 and "Reine" excerpt: https://www.dailymotion.com/video/x6w2rv1 (API: `https://api.dailymotion.com/video/x6voyn7?fields=description,created_time,uploaded_time`) | H (for what Mouv' states) |
| The year is 2018. Mouv' uploaded the full-session file on 2018-10-19 15:06 UTC and published it at 2018-10-20 08:00 UTC (10:00 Paris time). | Dailymotion API `uploaded_time`=1539961570 and `created_time`=1540022400 for x6voyn7 | H |
| Fan and lyrics sites give 20 Oct 2018 as the "release" date. That matches the publication date, not the recording date. | readdork.com structured data, https://readdork.com/lyrics/juice-wrld-campfire-song-freestyle ; fan TikTok, https://www.tiktok.com/@999.juicewrld.com/video/7576737962407382304 | M |
| The venue is the Mouv' Live Club studio in Paris. Mouv' is part of Radio France. The exact room has not been checked. Maison de la Radio is the likely place but no source confirms it. | Mouv' descriptions above; https://hiphopcanada.com/juice-wrld-mouv-live-club-freestyles/ ; https://en.wikipedia.org/wiki/Mouv%27 | H for Paris and Mouv'; L for the room |
| Mouv's own upload pages contradict the "recorded 19 Oct, released 20 Oct" reading only lightly. The fully edited multi-camera video was already uploaded at 17:06 Paris time on the 19th, which suggests the session was taped in advance and "19 octobre" is the air date. This is my inference. | Dailymotion timestamps above | L |

## 2. Host / DJ

| Claim | Source | Conf. |
|---|---|---|
| The host and DJ is **Muxxa**. Mouv' calls him "Damien Muxxa" and the show the "#MouvLiveClub de Damien Muxxa". | Mouv' interview video description: https://www.dailymotion.com/video/x6vxdde | H |
| HipHopCanada calls him "DJ Muxxa" and says Juice WRLD freestyled "with support from DJ Muxxa". | https://hiphopcanada.com/juice-wrld-mouv-live-club-freestyles/ (11 Aug 2022) | H |
| Muxxa was a resident Mouv' DJ in 2018. He was billed with DJ First Mike and others at a Mouv' night at the Rex Club on 19 Dec 2018. | https://www.paris-friendly.fr/soiree-insolite-et-gratuite-avec-djs-a-paris.html | M |
| Lyrics sites credit "DJ MUXXA" on the intro of "Campfire Song (Freestyle)". That suggests Muxxa speaks at the start of the "Reine" clip. I have not checked this by listening. | https://lyrics.lol/artist/1237094-juice-wrld/lyrics/4040841-campfire-song-freestyle ; https://readdork.com/lyrics/juice-wrld-campfire-song-freestyle | L |

## 3. What tour or trip he was on

| Claim | Source | Conf. |
|---|---|---|
| Summer 2018: the WRLD Domination tour in North America, with YBN Cordae and Lil Mosey, announced 20 July 2018. | https://en.wikipedia.org/wiki/Juice_Wrld | H |
| **September 2018 European headline run** listed on setlist.fm: Berlin, Heimathafen Neukölln (18 Sep); London, O2 Forum Kentish Town (23 Sep); Amsterdam, Melkweg (24 Sep); Oslo, Sentrum Scene (25 Sep); Stockholm, Fryshuset (26 Sep); Copenhagen, Vega (27 Sep). | https://www.setlist.fm/search?query=juice+wrld&year=2018&page=2 | M (user-maintained but consistent) |
| **Paris show: Élysée Montmartre, 20 September 2018.** Getty photo 1037055838, caption "Juice Wrld performs at Elysee Montmartre on September 20, 2018 in Paris, France". setlist.fm does not list this show. | https://www.gettyimages.com/photos/juice-world (image id 1037055838) | H |
| A Vice NL article covers him in Amsterdam after a sold-out Melkweg show, which supports the Sept 2018 run. | https://www.vice.com/nl/article/juice-wrld-amsterdam-interview/ | M |
| In October 2018 his known shows are all in North America: Fargo (5 Oct), Charlotte (12 Oct), Red Rocks (27 Oct), Newark Powerhouse (28 Oct), Toronto (29 Oct). No European date was found for 13 to 26 October. | setlist.fm pages 1 and 2 (above); Getty (Newark, 28 Oct) | M |
| *WRLD ON DRUGS* (with Future) came out on **19 Oct 2018**, the same date Mouv' gives for the guest slot. | Deezer album date 2018-10-19 (`https://api.deezer.com/artist/14456487/albums`); https://en.wikipedia.org/wiki/Juice_Wrld | H |
| Tim Westwood sessions: there is a London session around late June 2018, and a second "Eminem beats" session covered by Hot97 on 6 Oct 2018. hiphop24x7 says the Mouv' visit came after a Westwood session. I could not open that page (HTTP 403). | https://www.capitalxtra.com/news/juice-wrld-hour-long-freestyle-watch-listen/ ; https://www.hot97.com/news/watch-juice-wrld-freestyle-for-nearly-an-hour-over-eminem-beats/ ; https://hiphop24x7.com/exclusive/watch-juice-wrld-freestyles-for-15-minutes-over-french-rap-songs/ | M |
| He did not play Paris again until the Nicki WRLD Tour: AccorHotels Arena, 7 March 2019. | https://en.wikipedia.org/wiki/The_Nicki_Wrld_Tour | H |

**My conclusion:** The best-supported context is a promo visit to Mouv' around the September 2018 European headline run, with the Paris show on 20 Sep 2018, and Mouv' airing or publishing it on 19 to 20 Oct 2018. The other possibility is a separate promo trip to Paris on 19 Oct 2018, the day *WRLD ON DRUGS* came out. That fits the gap in his US dates, but no source documents it. **No source states the recording date outright. Treat "recorded 19 Oct 2018" as unverified.**

## 4. Every beat in the session, with timestamps

The timestamps are Mouv's own chapter list from the full-session description (Dailymotion x6voyn7, which matches YouTube OV9ucgzzvf8 per the indexed description). Conf. H for the list.
The "Measured boundary" column comes from spectral-novelty peaks in the full-session audio (Dailymotion copy, 952.3 s). They agree with Mouv's chapters to within about 3 s.

| # | Mouv' chapter | Beat (as Mouv' lists it) | Approx. length | Measured boundary |
|---|---|---|---|---|
| 1 | 0:12 | Niska – "Réseaux" | ~2:12 | (intro/novelty at 0:19) |
| 2 | 2:24 | Kalash – "Koussi Koussa" ft. Niska | ~1:43 | 2:22 |
| 3 | 4:07 | Suprême NTM – "Ma Benz" ft. Lord Kossity | ~2:09 | 4:01 to 4:04 |
| 4 | 6:16 | 113 – "Tonton du bled" | ~1:07 | 6:18 |
| 5 | 7:23 | Alonzo – "La Belle Vie" | ~1:32 | 7:22 |
| **6** | **8:55** | **Dadju – "Reine"** | **~1:59** | **8:54 to 8:57; the previous beat's low end stops at about 8:52 to 8:53** |
| 7 | 10:54 | Aya Nakamura – "Comportement" | ~1:54 | 10:56; the next beat's low end comes back at about 11:02 to 11:09 |
| 8 | 12:48 | Ninho – "Roro" | ~3:05 to end (15:53) | 12:41 to 12:51 |

Notes:
- The YouTube title, as search engines index it, is "Juice WRLD freestyle sur du Niska, NTM, 113, Dadju, Ninho... / freestyles on french rap beats". The Dailymotion title also names Aya Nakamura.
- A Mouv' follow-up confirms the "Comportement" segment. On 26 Oct 2018, DJ First Mike challenged Aya Nakamura to sing "Copines" over a Juice WRLD beat, "comme il avait freestylé sur 'Comportement'". Source: https://www.dailymotion.com/video/x6w70hs (H).
- Fans have their own names for the segments. A full-session SoundCloud reupload is titled "(Campfire, Mind Games, ETC.)": https://soundcloud.com/willpincince/juice-wrld-mouv-freestyle (2020-09-09). I could not find which segment fans call "Mind Games" (L).

## 5. Where the "Reine" freestyle sits, and how the excerpt lines up

- In Mouv's chapter list it is the 6th of 8 beats, from 8:55 to 10:54 (H).
- **Measured:** the 2:04.27 excerpt (Facebook/Dailymotion, and so `fb_mouv_hd.mp4`) is a straight cut from the full session, **8:57.03 to 11:01.30**. Normalized cross-correlation in the vocal band is 0.985. Checks at 5 s, 60 s and 100 s into the excerpt all give the same offset, 537.035 s, so there is no drift and no speed difference between the uploads (H for the measurement).
- So the excerpt starts about 2 s after Mouv's 8:55 chapter mark. It ends about 7 s after the 10:54 "Comportement" mark, in the gap between beats. The last ~6 s of the excerpt are the transition, not "Reine" (M).

## 6. Where the "Campfire Song" nickname came from

Timeline of the name, from SoundCloud metadata read with yt-dlp:

| Date (upload) | Title | Link | Note |
|---|---|---|---|
| 2018-10-22 | "Juice wrld freestyle (Campfire)" – 116 s | https://soundcloud.com/mrdisconnected/juice-wrld-freestyle-campfire | earliest found; 2 days **before** Mouv's own excerpt |
| 2018-10-22 | "Juice WRLD Campfire Reine freestyle" – 105 s, about 180k plays | https://soundcloud.com/russell-van-moorsel/juice-wrld-campfire-reine | |
| 2018-10-25 | "Juice WRLD - camp fire songs 999 (Diffuse One REMIX)" | https://soundcloud.com/delano-solis/juice-wrld-camp-fire-songs-999-delano-solis-remix | |
| 2018-11-22 / 11-30 | "ballout (campfire freestyle)" / "Camp Fire/Ball Out" remix | https://soundcloud.com/beatsbydomis/juice-wrld-ballout-prod-domis ; https://soundcloud.com/lil_phil_on_the_beat/juice-wrld-freestyle-camp-fireball-out-remix-prod-by-lil-phil | "Ball Out" is a second fan name |
| 2019-12-22 | "Juice WRLD freestyle sur "Reine" de Dadju (Campfire Freestyle)" | https://soundcloud.com/will-tompkins-977052812/juice-wrld-freestyle-sur-reine-de-dadju-campfire-freestyle | this is `sc_campfire_160k.m4a`, posted after his death |
| 2020-07-03 | "Juice WRLD freestyle sur "Reine" de Dadju / "Campfire Song" [official]" | https://soundcloud.com/bob-ross-12315512/juice-wrld-freestyle-sur-reine | the title copies the retitled YouTube upload, so the retitle happened by July 2020 at the latest (L to M) |

- The Mouv' YouTube excerpt (bqKBIgol3kM) is indexed as **"Juice WRLD freestyle sur "Reine" de Dadju / "Campfire Song" [official]"** (search-engine index; I did not open YouTube). Conf. M.
- HipHopCanada (2022) says the "Reine" freestyle "is commonly referred to among Juice WRLD fans as the 'Campfire Freestyle'" but gives no reason (H for the usage).
- **Why "campfire" is not documented anywhere I could find.** My hypothesis (L) is the sound of the clip. For about the first 1:36 the beat has almost no low end, which leaves Juice singing over sparse, mostly melodic music, a bit like a campfire singalong (section 9). I did not listen to the clip, and no fan post confirms this reason. Reddit and Genius blocked automated access (HTTP 403), so fan threads were not checked.

## 7. Officially released on streaming, or radio session only?

| Platform | Finding | Source | Conf. |
|---|---|---|---|
| Deezer | No Reine, Campfire or Mouv' track in any of Juice WRLD's 42 Deezer releases. The only "freestyle" titles are "7 Am Freestyle" (*WRLD ON DRUGS*) and "Let Me Know (I Wonder Why Freestyle)". | `https://api.deezer.com/artist/14456487/albums` plus per-album track lists | H |
| Apple Music / iTunes (FR store) | No match for "juice wrld campfire / reine / dadju / freestyle mouv". | `https://itunes.apple.com/search?term=...&entity=song&country=FR` | H |
| **Audiomack** | **"Mouv' Live Club Freestyle" by Juice WRLD**: full session, 953 s (PT15M53S), uploaded 2018-10-29 16:06 UTC, `stream_only: yes`, explicit, about 1.54M plays. Posted by the account `juicewrld`, which is marked **"Verified Artist"** and links to instagram juicewrld999 and 999club.com. No credits are listed. | https://audiomack.com/juicewrld/song/mouv-live-club-freestyle (page JSON-LD and embedded data) | H for the facts; M that this was a team-authorized release |
| Genius / lyrics mirrors | Listed as "Campfire Song (Freestyle)", released 20 Oct 2018, produced by "Mouv' & Seysey", intro credited to DJ Muxxa. Seysey is probably credited because he produced the "Reine" beat: a third-party profile (https://app.artist.tools/artist/1vMCydfeqfc5BdxolssKxU) links Seysey to *Gentleman 2.0* and "Reine", but I found no track-level credit (L to M). | https://readdork.com/lyrics/juice-wrld-campfire-song-freestyle (Genius itself returned 403) | M |
| SoundCloud | Fan reuploads only, all unofficial (section 6). | as above | H |

**Bottom line:** There is no official single or album release on the major DSPs (Spotify was not checked directly, since it has no public API without a key, but Deezer and iTunes both lack it). The only artist-side release is the whole Mouv' session on Juice WRLD's verified Audiomack page. Apart from that, it is a radio session distributed as Mouv' videos.

## 8. Official Mouv' uploads

All dates below are UTC.

| Platform | ID / URL | Title (as published) | Date | Length | Conf. |
|---|---|---|---|---|---|
| YouTube | OV9ucgzzvf8 | "Juice WRLD freestyle sur du Niska, NTM, 113, Dadju, Ninho... / freestyles on french rap beats" (search-indexed title; description starts "Juice WRLD était l'invité de Muxxa le 19 octobre…") | ~Oct 2018 (index shows an age of ~2,927 days); exact date not verified because YouTube is blocked here | ~15:53 | M |
| YouTube | bqKBIgol3kM | "Juice WRLD freestyle sur "Reine" de Dadju / "Campfire Song" [official]" (search-indexed; probably retitled later) | not verified; the Dailymotion and Facebook versions are dated 24 Oct 2018 | ~2:04 | M |
| Dailymotion | https://www.dailymotion.com/video/x6voyn7 | "Juice WRLD freestyle sur du Niska, NTM, 113, Aya Nakamura, Dadju, Ninho.... !" plus the chapter list | published 2018-10-20 08:00 (file uploaded 2018-10-19 15:06) | 953 s | H |
| Dailymotion | https://www.dailymotion.com/video/x6vxdde | "JUICE WRLD : "Je suis fan de Nas et de Sting"" (interview from the same Live Club; tags include "lucid dreams") | 2018-10-22 17:00 | 530 s | H |
| Dailymotion | https://www.dailymotion.com/video/x6w2rv1 | "Juice WRLD freestyle sur "Reine" de Dadju". The description says he covered the hit "à la perfection". | listed 2018-10-24 18:00 (file timestamp 2018-10-25 10:17) | 124 s | H |
| Facebook (MouvRadio) | https://www.facebook.com/MouvRadio/videos/juice-wrld-freestyle-sur-reine-de-dadju/114671982761102/ | "Juice WRLD freestyle sur "Reine" de Dadju". The caption says he covered "Reine" and it was "tout simplement magnifique". | 2018-10-24 20:00:01 | 124.28 s | H (from `fb_mouv_hd.info.json`) |
| Dailymotion | https://www.dailymotion.com/video/x6w70hs | "AYA NAKAMURA chante "Copines" sur du Juice WRLD !" (Good Morning Cefran, DJ First Mike: a spin-off of the session) | 2018-10-26 14:00 | 112 s | H |
| Dailymotion | https://www.dailymotion.com/video/x7oyh60 | "Juice WRLD est mort" (Gossip Hop news segment) | 2019-12-09 | 135 s | H |
| Instagram (@mouv) | not found. Searches turned up no Mouv' Instagram post about the session, and Instagram can't be searched without logging in. | – | – | – | gap |
| mouv.fr / radiofrance.fr | no article found. radiofrance.fr search is rendered by JavaScript, WebFetch is blocked on that domain, and the Wayback CDX connection was reset. | – | – | – | gap |

## 9. What the DJ played (instrumental? sped up? looped?)

No published source says how Muxxa played the beat. Everything below is **my own measurement** on `fb_mouv_hd.mp4` and the full-session Dailymotion audio, compared with Deezer's 30 s preview of the studio "Reine" (Dadju, *Gentleman 2.0*, 2017-11-24, ISRC TCADB1727917, Deezer bpm field 97.97).

| Observation | Value | Conf. |
|---|---|---|
| Studio "Reine" tempo | 97.95 to 98.08 BPM (preview, two methods), matching Deezer's metadata | H |
| Live "Reine" tempo | **100.35 to 100.48 BPM**, the same across the sparse part (0:03 to 1:35) and the full-drums part (1:38 to 1:57). That is about 2.4 to 2.5% faster than studio. | M |
| Key and tuning | The chroma profile matches the studio preview with **zero transposition** (r = 0.91 for the sparse part, 0.85 for the drums part; ±1 semitone gives ≤ 0.39). The best key fit is D major / B minor. Both are tuned within about 2 cents of A440. A plain +2.4% varispeed would raise the pitch by about 41 cents, and that is **not** what I found. | M |
| What this probably means | The DJ most likely raised the tempo with key lock on (CDJ "master tempo", Serato or Rekordbox key-lock), or played a different instrumental or edit that is already about 100 BPM. It does **not** look like a vinyl-style speed-up. | L to M |
| Instrumental or the vocal version? | Can't tell yet. Waveform correlation with the studio preview (which has Dadju's vocal) is low (≤ 0.11 at all tested speeds), but time-stretching alone would cause that. Vocal separation (task 3) should show whether Dadju's voice is in the bed. | gap |
| Arrangement and filtering | Excerpt 0:00 to ~1:36 (full session 8:57 to ~10:33): the bass/kick band (<150 Hz) sits **12 to 20 dB below** the 300 Hz to 3 kHz band. In the studio preview it sits 6 to 9 dB below. From ~1:36 to ~1:57 (10:33 to 10:54) the low end comes in hard, at about 0 dB relative. At ~1:57 the beat stops. This could be a low-cut or EQ "drop" by the DJ, or the song's own arrangement (an intro or breakdown followed by the drums). Either is possible. | M for the measurement; L for the cause |
| Looping | I found no loop seam with this coarse analysis. Tempo and key stay steady through the segment. To prove or rule out a loop, compare the beat grid with the studio arrangement, bar by bar (task 2). | gap |

## 10. Musical notes on the performance

- **Melodic or rapped:** Mouv' calls it a *reprise*, saying he covered the hit "à la perfection", and Facebook calls it "magnifique". Fans call it a "song" or "campfire song". Lyrics sites list it as his own words ("written by Juice WRLD"), so it seems to be a melodic, sung freestyle with his own lyrics over the "Reine" beat, not a rap verse. Conf. M. I have **not** listened to it to confirm. Sources: Dailymotion x6w2rv1, the Facebook caption, readdork.
- **Length:** about 1:59 by the chapters (8:55 to 10:54). The excerpt is 2:04.27 including about 6 s of transition (H).
- **Does he stop while the beat keeps going?** Measured with mid/side analysis on the stereo `fb_mouv_hd.mp4`: centered (mid) content in the vocal band stays **13 to 22 dB above the side** from about 0:04 to about 1:57. This looks like a near-continuous lead vocal, with only short dips (around 0:02, 1:00 and 1:18). At **about 1:57 the centered vocal and the beat drop out together** (mid-over-side falls to 7, then 4, then 0 dB). So within the excerpt, there is no long stretch where only the beat plays. The opening ~3 s may be beat only, or Muxxa talking (M; check in task 2).
- **Interview:** Mouv' released 8:50 of interview from the same visit. Its title says he is a fan of Nas and Sting, and it is tagged "Lucid Dreams", which samples Sting's "Shape of My Heart" (H for the title).

## 11. Method notes and working files

All working files are in the scratchpad. Nothing was added to the project tree except this document.
- Full session (official Mouv' Dailymotion, HE-AAC 64 kbps, 288p video): `/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/session_research/dl/dm_mouv_full_session.mp4`, plus `.info.json`. measure_quality printed `cutoff_khz 24.0`, but its band table shows content stopping at about 20 kHz (20 to 22 kHz at −91.7 dB). Above roughly 11 to 15 kHz the content is SBR-synthesized, so use this file **for reference only** (structure and transitions), not as a master.
- Studio "Reine" 30 s preview (Deezer, 128 kbps MP3): `/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/session_research/dl/dz_reine_preview.mp3`
- Scripts: `/tmp/claude-0/-home-user-test/af0d4d95-94cf-5494-941b-b23bfca9f25a/scratchpad/session_research/scripts/` contains align.py (cross-correlation alignment and novelty boundaries), refine.py, tempo.py and tempo2.py (onset-autocorrelation comb, full band, 30 to 150 Hz and 2 to 8 kHz), speed.py (resample-and-correlate plus tuning), and chroma.py. They use numpy and scipy only, run under nice.

## 12. Open questions

1. The exact recording date: 19 Oct 2018, or during the September 2018 Paris visit (Élysée Montmartre, 20 Sep 2018)? Two ways to settle it: an @mouv or @muxxa Instagram post, a Radio France programme archive for 19 Oct 2018, or what he says in the Mouv' interview (x6vxdde, for example whether he mentions a show "tonight").
2. Exact YouTube publication dates and current titles for OV9ucgzzvf8 and bqKBIgol3kM. I could not check them because YouTube is blocked here.
3. Why fans call it "Campfire". No source gives a reason.
4. Whether Muxxa played the instrumental or the vocal version of "Reine", and whether he used a filter or EQ or the song's own arrangement for the bass-light first 1:36.
5. Audiomack audio quality. yt-dlp's Audiomack extractor failed with a JSON parse error, and I did not try to work around it. It may be a cleaner full-session source than Dailymotion. Worth a check if a fixed extractor or another route becomes available.
6. Which segment fans call "Mind Games".
