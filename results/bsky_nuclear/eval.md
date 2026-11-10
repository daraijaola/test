# Real X-like corpus: every public Bluesky post on 'nuclear power' (27,536 posts)

## 1. Absorber audit (independent judge, 100 random posts)

Verdicts: {'correct': 68, 'minor_issue': 28, 'wrong': 4}. Strict error rate (wrong): **4%**; including minor issues: 32%. Anchor op: {'na': 81, 'no': 11, 'yes': 8}.

Judge notes on wrong filings (sample):

- Post is about a Trump–Kim summit, not nuclear power. The entry text about drills isn't in the post, so it was filed against an unrelated or unsupported entry.
- The post is about Zaporizhzhia relying on emergency diesel. The entry about a US base getting a 1MW microreactor doesn't match it.
- The post says the Greens dropped their opposition. The entry says the Greens oppose nuclear power, which is the opposite. A better entry was available in the Green Party phase-out reversal.
- The poster opposes nuclear power, so the anchor op should be dispute, not support. The poster also doesn't deny that the party dropped its phase-out. They lament it, so dispute on that entry is wrong.

## 2. Coverage: is a random post's point present in what the reader receives? (119 posts with a point)

| reader input | tokens | yes | partly | no | score (yes + ½ partly) |
|---|---|---|---|---|---|
| ledger (theme view) | 31,604 | 19% | 39% | 42% | **38%** |
| RAG top-20 | 1,082 | 3% | 7% | 91% | **6%** |
| RAG top-100 | 4,829 | 6% | 15% | 79% | **13%** |
| RAG top-k, same tokens as ledger | 31,061 | 15% | 17% | 68% | **24%** |
| random sample, same tokens as ledger | 31,015 | 14% | 21% | 65% | **25%** |

(no counting questions: no candidate entity in the frequency range)
