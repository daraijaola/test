# Experiment results

Synthetic niche-topic feed: 21500 posts (incl. 1,500 bot posts), 300 latent claims, 3 seeds, mean shown. Ledger view budget: 32,000 tokens. RAG = BM25 top-k with a *perfect* reader (best case for RAG). Ledger eps = absorber error rate.

## 1. Landscape: what fraction of claims held by >= m distinct people is visible to the model at all?

| method | >=3 people | >=10 people | >=30 people |
|---|---|---|---|
| RAG k=10 (topic query) | 5% | 6% | 12% |
| RAG k=10 (ideal unbiased sample) | 2% | 3% | 8% |
| RAG k=20 (topic query) | 7% | 10% | 21% |
| RAG k=20 (ideal unbiased sample) | 6% | 8% | 18% |
| RAG k=50 (topic query) | 13% | 18% | 34% |
| RAG k=50 (ideal unbiased sample) | 9% | 13% | 30% |
| RAG k=100 (topic query) | 20% | 25% | 46% |
| RAG k=100 (ideal unbiased sample) | 16% | 22% | 44% |
| Ledger eps=0.0 | 100% | 100% | 100% |
| Ledger eps=0.05 | 100% | 100% | 100% |
| Ledger eps=0.1 | 100% | 100% | 100% |
| Ledger eps=0.2 | 100% | 100% | 100% |
| Ledger eps=0.3 | 100% | 100% | 100% |

## 2. Prevalence ranking (Spearman vs truth, claims with >=10 people)

| method | Spearman |
|---|---|
| RAG k=10 (topic query) | 0.200 |
| RAG k=10 (ideal sample) | 0.231 |
| RAG k=20 (topic query) | 0.280 |
| RAG k=20 (ideal sample) | 0.313 |
| RAG k=50 (topic query) | 0.337 |
| RAG k=50 (ideal sample) | 0.371 |
| RAG k=100 (topic query) | 0.383 |
| RAG k=100 (ideal sample) | 0.455 |
| Ledger eps=0.0 | 1.000 |
| Ledger eps=0.05 | 0.958 |
| Ledger eps=0.1 | 0.931 |
| Ledger eps=0.2 | 0.883 |
| Ledger eps=0.3 | 0.835 |

## 3. Stance: mean absolute error of 'what share of people support claim X' (organic authors)

Query names the claim using its own vocabulary (best case for retrieval). 'unknown' = model saw no stance-bearing evidence.

| method | head MAE | mid MAE | tail MAE | tail unknown |
|---|---|---|---|---|
| RAG k=10 | 0.135 | 0.124 | 0.115 | 0% |
| RAG k=20 | 0.085 | 0.077 | 0.045 | 0% |
| RAG k=50 | 0.056 | 0.040 | 0.001 | 0% |
| RAG k=100 | 0.045 | 0.011 | 0.001 | 0% |
| Ledger eps=0.0 | 0.000 | 0.002 | 0.000 | 0% |
| Ledger eps=0.05 | 0.031 | 0.033 | 0.037 | 0% |
| Ledger eps=0.1 | 0.052 | 0.058 | 0.060 | 0% |
| Ledger eps=0.2 | 0.084 | 0.097 | 0.092 | 0% |
| Ledger eps=0.3 | 0.110 | 0.139 | 0.132 | 0% |
| Ledger eps=0.0 + census verify (<=300 docs from exact posting list) | 0.008 | 0.003 | 0.000 | avg docs read: 258 head / 25 tail |
| Ledger eps=0.05 + census verify (<=300 docs from exact posting list) | 0.015 | 0.016 | 0.016 | avg docs read: 260 head / 25 tail |
| Ledger eps=0.1 + census verify (<=300 docs from exact posting list) | 0.019 | 0.018 | 0.031 | avg docs read: 258 head / 25 tail |
| Ledger eps=0.2 + census verify (<=300 docs from exact posting list) | 0.023 | 0.025 | 0.059 | avg docs read: 250 head / 24 tail |
| Ledger eps=0.3 + census verify (<=300 docs from exact posting list) | 0.027 | 0.040 | 0.097 | avg docs read: 242 head / 23 tail |

## 4. Trend: which claims are emerging? (precision / recall)

| method | precision | recall |
|---|---|---|
| RAG k=10 (ideal sample) | 0% | 0% |
| RAG k=20 (ideal sample) | 33% | 1% |
| RAG k=50 (ideal sample) | 33% | 1% |
| RAG k=100 (ideal sample) | 67% | 3% |
| Ledger eps=0.0 | 97% | 100% |
| Ledger eps=0.05 | 95% | 93% |
| Ledger eps=0.1 | 88% | 92% |
| Ledger eps=0.2 | 87% | 81% |
| Ledger eps=0.3 | 81% | 66% |

## 5. Coordinated bot flood (6 accounts, 1,500 near-identical posts supporting one claim)

True organic support share: **12%**

| method | estimated support share | bots among evidence |
|---|---|---|
| RAG k=10, reader dedups authors | 24% | 0% of posts |
| RAG k=10, reader counts posts | 24% | |
| RAG k=20, reader dedups authors | 13% | 0% of posts |
| RAG k=20, reader counts posts | 13% | |
| RAG k=50, reader dedups authors | 17% | 6% of posts |
| RAG k=50, reader counts posts | 20% | |
| RAG k=100, reader dedups authors | 21% | 27% of posts |
| RAG k=100, reader counts posts | 40% | |
| Ledger eps=0.0, author tally | 22% | 6 of the entry's authors, visible |
| Ledger eps=0.05, author tally | 28% | 6 of the entry's authors, visible |
| Ledger eps=0.1, author tally | 26% | 6 of the entry's authors, visible |
| Ledger eps=0.2, author tally | 36% | 6 of the entry's authors, visible |
| Ledger eps=0.3, author tally | 37% | 6 of the entry's authors, visible |
| Ledger eps=0.0, reader discounts accounts behind the ⚠ concentration flag | 12% | flagged 6.0 accts (6.0 true bots); false flags on other entries: 0.0 |
| Ledger eps=0.05, reader discounts accounts behind the ⚠ concentration flag | 19% | flagged 6.0 accts (6.0 true bots); false flags on other entries: 0.3 |
| Ledger eps=0.1, reader discounts accounts behind the ⚠ concentration flag | 17% | flagged 6.0 accts (6.0 true bots); false flags on other entries: 0.7 |
| Ledger eps=0.2, reader discounts accounts behind the ⚠ concentration flag | 30% | flagged 6.0 accts (6.0 true bots); false flags on other entries: 1.0 |
| Ledger eps=0.3, reader discounts accounts behind the ⚠ concentration flag | 29% | flagged 6.0 accts (6.0 true bots); false flags on other entries: 1.0 |
| Ledger eps=0.1, raw doc mass (what a post-counting view would say) | 92% | |

## 5b. How much would RAG have to read to match the ledger's coverage?

Ideal unbiased random sample of k posts (better than any query-driven top-k for coverage).

| k | >=3 people | >=10 people | >=30 people | Opus 5.5 $/query | fits 1M window? |
|---|---|---|---|---|---|
| 200 | 26% | 35% | 66% | $0.05 | yes |
| 500 | 47% | 58% | 85% | $0.10 | yes |
| 1,000 | 60% | 73% | 97% | $0.19 | yes |
| 2,000 | 81% | 93% | 100% | $0.37 | yes |
| 5,000 | 95% | 99% | 100% | $0.91 | yes |
| 10,000 | 100% | 100% | 100% | $1.81 | yes |
| 20,000 | 100% | 100% | 100% | $3.61 | yes |

## 6. Size, residual, conservation

| eps | entries | rendered tokens | residual % | merges | conservation (mass == docs) |
|---|---|---|---|---|---|
| 0.0 | 300 | 7,893 | 0.00 | 0 | 21500.0000 == 21500 |
| 0.05 | 341 | 8,822 | 0.06 | 1015 | 21500.0000 == 21500 |
| 0.1 | 435 | 10,880 | 0.23 | 1832 | 21500.0000 == 21500 |
| 0.2 | 763 | 18,093 | 0.97 | 3010 | 21500.0000 == 21500 |
| 0.3 | 1118 | 25,959 | 2.09 | 3519 | 21500.0000 == 21500 |

## 7. Cost (USD, list prices; see sim/cost.py for assumptions)

Ledger ingest at eps=0.1 (Haiku 5.5 absorber + consolidation, every post read once): **$0.46** standard, **$0.23** via Message Batches (one-time; 3.1M tokens processed). Rendered ledger: 10,660 tokens.

| queries | Ledger (ingest + Opus 5.5 reads full ledger, cached) | RAG k=20 (Opus 5.5) | RAG k=100 | Long-context: whole corpus in window (cached) |
|---|---|---|---|---|
| 1 | $0.52 | $0.04 | $0.05 | $4.85 (968k tok) |
| 10 | $0.65 | $0.19 | $0.34 | $6.70 (968k tok) |
| 100 | $1.97 | $1.75 | $3.19 | $25.24 (968k tok) |
| 1,000 | $15.12 | $17.30 | $31.70 | $210.62 (968k tok) |
| 10,000 | $146.63 | $172.82 | $316.82 | $2,064.44 (968k tok) |

Per-query marginal: ledger $0.0146, RAG k=20 $0.0173, RAG k=100 $0.0317.


## 8. Scaling projection (assumption-driven, not measured)

Distinct assertions D are assumed to grow as D = 2 * N^beta (Heaps-like). Ingest uses Message Batches pricing; absorber prefix sharded above 150k tokens; render capped at 32k tokens with exact folding below the cap. 'RAG k=20' is the cheap, low-coverage baseline; 'RAG at parity' reads 10% of the corpus per query, roughly what section 5b shows is needed (~93%) to approach the ledger's coverage of >=10-person claims.

| posts N | beta | entries D | ingest $ | 1,000 queries: ledger | 1,000 queries: RAG k=20 | 1,000 queries: RAG at parity (k=10% of N) | long-context |
|---|---|---|---|---|---|---|---|
| 20,000 | 0.6 | 761 | $0.30 | $17.48 | $17.30 | $373.70 | $196.80 |
| 20,000 | 0.8 | 5,518 | $1.01 | $20.05 | $17.30 | $373.70 | $196.80 |
| 200,000 | 0.6 | 3,031 | $5.71 | $24.75 | $17.46 | $3,613.86 | does not fit |
| 200,000 | 0.8 | 34,822 | $25.77 | $44.80 | $17.46 | $3,613.86 | does not fit |
| 2,000,000 | 0.6 | 12,068 | $117.60 | $136.64 | $19.08 | does not fit | does not fit |
| 2,000,000 | 0.8 | 219,712 | $333.24 | $352.28 | $19.08 | does not fit | does not fit |
