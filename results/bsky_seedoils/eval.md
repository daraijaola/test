# Real X-like corpus: every public Bluesky post on 'seed oils' (6,062 posts)

## 1. Absorber audit (independent judge, 100 random posts)

Verdicts: {'minor_issue': 25, 'correct': 71, 'wrong': 4}. Strict error rate (wrong): **4%**; including minor issues: 29%. Anchor op: {'no': 20, 'na': 50, 'yes': 30}.

Judge notes on wrong filings (sample):

- 'Healthy respect' means wariness, not safety. The anchor support is a misreading, and the entry 'respect rather than fear' inverts the meaning.
- The post never mentions seed oils. It is about RFK and vaccines and should be noise, not a filed claim.
- The post is mockery of anti-seed-oil people. Filing it as support for 'avoid for health' reverses the stance.
- The mock-outrage tone reads as satire of seed-oil fear. Supporting an 'objectionable' entry and disputing the anchor reverses the stance.

## 2. Coverage: is a random post's point present in what the reader receives? (131 posts with a point)

| reader input | tokens | yes | partly | no | score (yes + ½ partly) |
|---|---|---|---|---|---|
| ledger (theme view) | 31,435 | 38% | 47% | 15% | **62%** |
| RAG top-20 | 977 | 4% | 14% | 82% | **11%** |
| RAG top-100 | 4,160 | 8% | 21% | 71% | **19%** |
| RAG top-k, same tokens as ledger | 30,829 | 29% | 32% | 39% | **45%** |
| random sample, same tokens as ledger | 30,773 | 37% | 28% | 34% | **52%** |

## 3. Counting questions (gold: text match over all posts)

| method | posts: median rel. error | posts: within 20% | authors: median rel. error | $ / question |
|---|---|---|---|---|
| ledger | 57% | 25% | 43% | $0.534 |
| ledger+census | 0% | 88% | 1% | $0.719 |
| rag20 | 91% | 0% | 100% | $0.034 |
| rag100 | 58% | 0% | 100% | $0.096 |

Census checker vs text match: precision 0.95, recall 0.99.

| entity | gold posts / authors | ledger | ledger+census | rag20 | rag100 |
|---|---|---|---|---|---|
| tallow | 530 / 429 | 330 / 290 | 528 / 426 | 20 / 0 | 100 / 0 |
| rfk | 341 / 297 | 400 / 340 | 340 / 296 | 20 / 0 | 100 / 0 |
| maha | 267 / 232 | 250 / 210 | 267 / 232 | 20 / 0 | 100 / 0 |
| processed | 242 / 195 | 104 / 120 | 255 / 207 | 20 / 0 | 100 / 93 |
| olive | 192 / 167 | 49 / 57 | 193 / 167 | 20 / 0 | 100 / 0 |
| butter | 163 / 125 | 70 / 65 | 163 / 125 | 20 / 17 | 90 / 77 |
| heart | 153 / 107 | 35 / 54 | 151 / 105 | 20 / 0 | 87 / 0 |
| inflammation | 151 / 100 | 10 / 19 | 207 / 139 | 20 / 18 | 64 / 0 |

Evaluation spend: $15.62
