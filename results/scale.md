# Scaling on an open world (claims keep arriving)

Pitman-Yor claim stream (sigma=0.6), claims grouped into themes, absorber eps=0.1. Reading budget 32,000 tokens. Fitted growth: true claims K ~ N^0.55, ledger entries D ~ N^0.62.

## Size and fragmentation

| N posts | true claims | claims >=10 people | config | entries D | entries per >=10-person claim | residual % | ingest $ (Batches) |
|---|---|---|---|---|---|---|---|
| 20,000 | 1,409 | 207 | flat index | 1,470 | 1.08 | 0.21 | $0.28 |
| 20,000 | 1,409 | 207 | sharded >2k entries, 5% misroute | 1,470 | 1.08 | 0.21 | $0.28 |
| 20,000 | 1,409 | 207 | sharded >2k entries, 15% misroute | 1,470 | 1.08 | 0.21 | $0.28 |
| 50,000 | 1,974 | 298 | flat index | 2,147 | 1.07 | 0.21 | $0.66 |
| 50,000 | 1,974 | 298 | sharded >2k entries, 5% misroute | 2,545 | 1.18 | 0.21 | $0.68 |
| 50,000 | 1,974 | 298 | sharded >2k entries, 15% misroute | 2,649 | 1.25 | 0.22 | $0.69 |
| 100,000 | 3,679 | 584 | flat index | 4,080 | 1.03 | 0.23 | $1.68 |
| 100,000 | 3,679 | 584 | sharded >2k entries, 5% misroute | 5,555 | 1.27 | 0.21 | $1.96 |
| 100,000 | 3,679 | 584 | sharded >2k entries, 15% misroute | 6,004 | 1.41 | 0.21 | $2.06 |
| 200,000 | 5,161 | 836 | flat index | 6,024 | 1.02 | 0.22 | $3.92 |
| 200,000 | 5,161 | 836 | sharded >2k entries, 5% misroute | 8,537 | 1.21 | 0.23 | $4.69 |
| 200,000 | 5,161 | 836 | sharded >2k entries, 15% misroute | 9,486 | 1.29 | 0.23 | $4.99 |
| 500,000 | 7,693 | 1,299 | flat index | 10,166 | 1.02 | 0.21 | $12.76 |
| 500,000 | 7,693 | 1,299 | sharded >2k entries, 5% misroute | 16,772 | 1.13 | 0.22 | $16.59 |
| 500,000 | 7,693 | 1,299 | sharded >2k entries, 15% misroute | 18,687 | 1.19 | 0.22 | $17.80 |

## What the reading model can see within 32k tokens

Entry-level visibility of claims held by >= m people (every claim's mass is always counted in a theme or fold line).

| N | config | view | >=3 | >=10 | >=30 | >=100 | prevalence Spearman | tokens |
|---|---|---|---|---|---|---|---|---|
| 20,000 | flat index | flat | 100% | 100% | 100% | 100% | 0.970 | 31,482 |
| 20,000 | flat index | multires | 100% | 100% | 100% | 100% | 0.970 | 23,491 |
| 20,000 | sharded >2k entries, 5% misroute | flat | 100% | 100% | 100% | 100% | 0.970 | 31,482 |
| 20,000 | sharded >2k entries, 5% misroute | multires | 100% | 100% | 100% | 100% | 0.970 | 23,491 |
| 20,000 | sharded >2k entries, 15% misroute | flat | 100% | 100% | 100% | 100% | 0.970 | 31,482 |
| 20,000 | sharded >2k entries, 15% misroute | multires | 100% | 100% | 100% | 100% | 0.970 | 23,491 |
| 50,000 | flat index | flat | 100% | 100% | 100% | 100% | 0.945 | 31,546 |
| 50,000 | flat index | multires | 100% | 100% | 100% | 100% | 0.945 | 30,936 |
| 50,000 | sharded >2k entries, 5% misroute | flat | 100% | 100% | 100% | 100% | 0.945 | 31,539 |
| 50,000 | sharded >2k entries, 5% misroute | multires | 100% | 100% | 100% | 100% | 0.945 | 30,938 |
| 50,000 | sharded >2k entries, 15% misroute | flat | 100% | 100% | 100% | 100% | 0.948 | 31,529 |
| 50,000 | sharded >2k entries, 15% misroute | multires | 100% | 100% | 100% | 100% | 0.948 | 30,951 |
| 100,000 | flat index | flat | 77% | 100% | 100% | 100% | 0.968 | 31,525 |
| 100,000 | flat index | multires | 97% | 100% | 100% | 100% | 0.968 | 30,889 |
| 100,000 | sharded >2k entries, 5% misroute | flat | 76% | 100% | 100% | 100% | 0.973 | 31,541 |
| 100,000 | sharded >2k entries, 5% misroute | multires | 94% | 100% | 100% | 100% | 0.973 | 30,846 |
| 100,000 | sharded >2k entries, 15% misroute | flat | 77% | 100% | 100% | 100% | 0.975 | 31,525 |
| 100,000 | sharded >2k entries, 15% misroute | multires | 94% | 100% | 100% | 100% | 0.975 | 30,830 |
| 200,000 | flat index | flat | 56% | 98% | 100% | 100% | 0.972 | 31,538 |
| 200,000 | flat index | multires | 79% | 100% | 100% | 100% | 0.972 | 30,722 |
| 200,000 | sharded >2k entries, 5% misroute | flat | 56% | 97% | 100% | 100% | 0.969 | 31,524 |
| 200,000 | sharded >2k entries, 5% misroute | multires | 77% | 100% | 100% | 100% | 0.969 | 30,657 |
| 200,000 | sharded >2k entries, 15% misroute | flat | 55% | 98% | 100% | 100% | 0.971 | 31,525 |
| 200,000 | sharded >2k entries, 15% misroute | multires | 77% | 100% | 100% | 100% | 0.971 | 30,665 |
| 500,000 | flat index | flat | 36% | 72% | 100% | 100% | 0.941 | 31,554 |
| 500,000 | flat index | multires | 58% | 98% | 100% | 100% | 0.948 | 30,841 |
| 500,000 | sharded >2k entries, 5% misroute | flat | 37% | 74% | 100% | 100% | 0.946 | 31,552 |
| 500,000 | sharded >2k entries, 5% misroute | multires | 57% | 97% | 100% | 100% | 0.952 | 30,850 |
| 500,000 | sharded >2k entries, 15% misroute | flat | 37% | 74% | 100% | 100% | 0.949 | 31,544 |
| 500,000 | sharded >2k entries, 15% misroute | multires | 58% | 97% | 100% | 100% | 0.953 | 30,873 |

## Reading budget vs visibility at N=500,000

| budget (tokens) | view | >=3 | >=10 | >=30 | Opus 5.5 cached read $/query |
|---|---|---|---|---|---|
| 32,000 | flat | 36% | 72% | 100% | $0.019 |
| 32,000 | multires | 58% | 98% | 100% | $0.019 |
| 64,000 | flat | 70% | 100% | 100% | $0.025 |
| 64,000 | multires | 90% | 100% | 100% | $0.025 |
| 128,000 | flat | 97% | 100% | 100% | $0.038 |
| 128,000 | multires | 100% | 100% | 100% | $0.038 |
| 256,000 | flat | 100% | 100% | 100% | $0.064 |
| 256,000 | multires | 100% | 100% | 100% | $0.064 |

## Stance accuracy (MAE of support share, best entry for the claim)

| N | config | head | mid | tail (10-29 people) |
|---|---|---|---|---|
| 20,000 | flat index | 0.027 | 0.040 | 0.073 |
| 20,000 | sharded >2k entries, 5% misroute | 0.027 | 0.040 | 0.073 |
| 20,000 | sharded >2k entries, 15% misroute | 0.027 | 0.040 | 0.073 |
| 50,000 | flat index | 0.029 | 0.030 | 0.084 |
| 50,000 | sharded >2k entries, 5% misroute | 0.029 | 0.033 | 0.082 |
| 50,000 | sharded >2k entries, 15% misroute | 0.027 | 0.032 | 0.082 |
| 100,000 | flat index | 0.027 | 0.026 | 0.140 |
| 100,000 | sharded >2k entries, 5% misroute | 0.027 | 0.028 | 0.125 |
| 100,000 | sharded >2k entries, 15% misroute | 0.028 | 0.031 | 0.136 |
| 200,000 | flat index | 0.023 | 0.028 | 0.110 |
| 200,000 | sharded >2k entries, 5% misroute | 0.028 | 0.028 | 0.102 |
| 200,000 | sharded >2k entries, 15% misroute | 0.026 | 0.034 | 0.126 |
| 500,000 | flat index | 0.025 | 0.022 | 0.086 |
| 500,000 | sharded >2k entries, 5% misroute | 0.026 | 0.020 | 0.103 |
| 500,000 | sharded >2k entries, 15% misroute | 0.026 | 0.021 | 0.095 |

## RAG at equal coverage

Fraction of claims held by >=10 people seen by an ideal uniform random sample of the corpus.

| N | 1% sample | 2% sample | 5% sample | 10% sample | 20% sample | 40% sample |
|---|---|---|---|---|---|---|
| 20,000 | 40% | 59% | 81% | 90% | 99% | 100% |
| 50,000 | 48% | 62% | 82% | 97% | 98% | 100% |
| 100,000 | 44% | 60% | 81% | 94% | 98% | 100% |
| 200,000 | 46% | 63% | 85% | 95% | 99% | 100% |
| 500,000 | 48% | 61% | 84% | 95% | 99% | 100% |

## Cost of 1,000 questions at roughly equal coverage

| N | ledger: ingest + 1,000 cached reads | RAG reading the sample that reaches ~90% of >=10-person claims, x1,000 |
|---|---|---|
| 20,000 | $19.32 | $733.70 (k=4,000) |
| 50,000 | $19.72 | $913.73 (k=5,000) |
| 100,000 | $20.99 | $1,813.77 (k=10,000) |
| 200,000 | $23.72 | $3,613.86 (k=20,000) |
| 500,000 | $35.62 | does not fit in 1M context (k=50,000) |
