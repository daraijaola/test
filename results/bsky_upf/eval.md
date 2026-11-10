# Real X-like corpus: every public Bluesky post on 'ultra-processed food' (6,042 posts)

## 1. Absorber audit (independent judge, 100 random posts)

Verdicts: {'minor_issue': 31, 'correct': 67, 'wrong': 2}. Strict error rate (wrong): **2%**; including minor issues: 33%. Anchor op: {'na': 62, 'no': 21, 'yes': 17}.

Judge notes on wrong filings (sample):

- Not about UPF. It is a satirical or unrelated post and should be noise, not a support claim.
- A sarcastic joke about McDonald's pricing with a crude insult. It makes no real claim of UPF harm, so the anchor support is unjustified.

## 2. Coverage: is a random post's point present in what the reader receives? (133 posts with a point)

| reader input | tokens | yes | partly | no | score (yes + ½ partly) |
|---|---|---|---|---|---|
| ledger (theme view) | 31,534 | 35% | 54% | 11% | **62%** |
| RAG top-20 | 967 | 2% | 14% | 83% | **9%** |
| RAG top-100 | 5,299 | 7% | 20% | 74% | **17%** |
| RAG top-k, same tokens as ledger | 30,997 | 32% | 33% | 35% | **49%** |
| random sample, same tokens as ledger | 30,956 | 31% | 32% | 37% | **47%** |

## 3. Counting questions (gold: text match over all posts)

| method | posts: median rel. error | posts: within 20% | authors: median rel. error | $ / question |
|---|---|---|---|---|
| ledger | 80% | 12% | 74% | $0.506 |
| ledger+census | 0% | 100% | 0% | $0.696 |
| rag20 | 80% | 0% | 100% | $0.036 |
| rag100 | 37% | 0% | 100% | $0.102 |

Census checker vs text match: precision 0.98, recall 1.00.

| entity | gold posts / authors | ledger | ledger+census | rag20 | rag100 |
|---|---|---|---|---|---|
| cancer | 189 / 141 | 74 / 75 | 191 / 143 | 20 / 0 | 100 / 0 |
| rfk | 165 / 143 | 150 / 140 | 165 / 143 | 20 / 0 | 100 / 0 |
| obesity | 165 / 144 | 46 / 55 | 165 / 144 | 20 / 0 | 98 / 0 |
| heart | 103 / 79 | 10 / 13 | 104 / 79 | 20 / 0 | 81 / 0 |
| diabetes | 94 / 81 | 19 / 22 | 103 / 85 | 20 / 0 | 35 / 35 |
| maha | 92 / 86 | 14 / 16 | 92 / 86 | 20 / 0 | 61 / 0 |
| kennedy | 66 / 57 | 120 / 100 | 66 / 57 | 20 / 0 | 52 / 0 |
| trump | 66 / 62 | 13 / 14 | 67 / 63 | 20 / 0 | 52 / 50 |

Evaluation spend: $15.28
