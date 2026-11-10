# Real X-like corpus: every public Bluesky post on 'seed oils' (6,042 posts)

## 1. Absorber audit (independent judge, 100 random posts)

Verdicts: {'minor_issue': 35, 'correct': 63, 'wrong': 1}. Strict error rate (wrong): **1%**; including minor issues: 36%. Anchor op: {'na': 54, 'no': 27, 'yes': 18}.

Judge notes on wrong filings (sample):

- Almost certainly a sarcastic or quoted headline. Filing it as sincere support of the claim is the wrong stance, and the post is off-topic for this ledger.

## 2. Coverage: is a random post's point present in what the reader receives? (68 posts with a point)

| reader input | tokens | yes | partly | no | score (yes + ½ partly) |
|---|---|---|---|---|---|
| ledger (theme view) | 31,534 | 37% | 51% | 12% | **62%** |
| RAG top-20 | 1,081 | 1% | 19% | 79% | **11%** |
| RAG top-100 | 5,824 | 7% | 26% | 66% | **21%** |
| RAG top-k, same tokens as ledger | 30,985 | 21% | 40% | 40% | **40%** |
| random sample, same tokens as ledger | 30,956 | 34% | 35% | 31% | **51%** |

## 3. Counting questions (gold: text match over all posts)

| method | posts: median rel. error | posts: within 20% | authors: median rel. error | $ / question |
|---|---|---|---|---|
| ledger | 88% | 0% | 86% | $0.502 |
| ledger+census | 1% | 100% | 0% | $0.697 |
| rag20 | 92% | 0% | 100% | $0.038 |
| rag100 | 46% | 0% | 100% | $0.111 |

Census checker vs text match: precision 1.00, recall 0.99.

| entity | gold posts / authors | ledger | ledger+census | rag20 | rag100 |
|---|---|---|---|---|---|
| cancer | 189 / 141 | 0 / 0 | 188 / 140 | 8 / 0 | 71 / 0 |
| rfk | 165 / 143 | 84 / 93 | 164 / 142 | 4 / 0 | 71 / 0 |
| obesity | 165 / 144 | 0 / 0 | 165 / 144 | 7 / 0 | 71 / 0 |
| heart | 103 / 79 | -1 / -1 | 102 / 79 | 10 / 6 | 73 / 0 |
| diabetes | 94 / 81 | 19 / 22 | 94 / 81 | 7 / 7 | 35 / 0 |
| maha | 92 / 86 | 14 / 16 | 92 / 86 | 8 / 0 | 59 / 0 |
| kennedy | 66 / 57 | 6 / 5 | 64 / 55 | 8 / 8 | 52 / 45 |
| trump | 66 / 62 | 13 / 14 | 67 / 63 | 8 / 0 | 50 / 48 |

Evaluation spend: $13.22
