# Real X-like corpus: every public Bluesky post on 'four-day work week' (4,189 posts)

## 1. Absorber audit (independent judge, 100 random posts)

Verdicts: {'minor_issue': 22, 'correct': 73, 'wrong': 5}. Strict error rate (wrong): **5%**; including minor issues: 27%. Anchor op: {'yes': 29, 'na': 65, 'no': 6}.

Judge notes on wrong filings (sample):

- A single four-day weekend taken off is not a four-day work week stance; entry is a personal-event, and 'support' is misfiled; should be noise/mention.
- Post is about a short week after a holiday weekend, not a real four-day work week; support of a 'being on a four-day work week' entry is misfiled. Should be mention/noise.
- Link about flexible working in teaching with no stated stance on a four-day week; anchor support is unwarranted.
- A four-day weekend is a holiday gap, not a four-day work week. It is a personal anecdote that should be noise or residual, not a supporting entry.
- About self-employed workers' autonomy and not about the 4-day week. It should be noise, not a support claim.

## 2. Coverage: is a random post's point present in what the reader receives? (118 posts with a point)

| reader input | tokens | yes | partly | no | score (yes + ½ partly) |
|---|---|---|---|---|---|
| ledger (theme view) | 31,342 | 34% | 44% | 22% | **56%** |
| RAG top-20 | 914 | 3% | 19% | 79% | **12%** |
| RAG top-100 | 4,629 | 7% | 26% | 67% | **20%** |
| RAG top-k, same tokens as ledger | 30,775 | 35% | 29% | 36% | **49%** |
| random sample, same tokens as ledger | 30,719 | 37% | 27% | 36% | **51%** |

(no counting questions: no candidate entity in the frequency range)
