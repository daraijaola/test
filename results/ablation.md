# Ablations (simulation, 3 seeds, mean)


## absorber eps = 0.1

| variant | entries | residual % | recall >=3 | Spearman | stance MAE (no census) | stance MAE (census) | emerging recall |
|---|---|---|---|---|---|---|---|
| full CEL | 435 | 0.230 | 100% | 0.931 | 0.060 | 0.030 | 92% |
| no consolidation | 2274 | 0.253 | 100% | 0.880 | 0.073 | 0.060 | 87% |
| no residual re-absorption | 311 | 4.412 | 100% | 0.930 | 0.061 | 0.033 | 91% |
| neither | 2146 | 4.447 | 100% | 0.879 | 0.076 | 0.061 | 86% |

## absorber eps = 0.2

| variant | entries | residual % | recall >=3 | Spearman | stance MAE (no census) | stance MAE (census) | emerging recall |
|---|---|---|---|---|---|---|---|
| full CEL | 763 | 0.969 | 100% | 0.883 | 0.095 | 0.042 | 81% |
| no consolidation | 3818 | 0.932 | 90% | 0.788 | 0.116 | 0.092 | 64% |
| no residual re-absorption | 357 | 9.040 | 100% | 0.880 | 0.098 | 0.049 | 77% |
| neither | 3425 | 8.897 | 92% | 0.786 | 0.115 | 0.097 | 61% |
