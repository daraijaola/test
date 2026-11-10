# Parallel absorption lanes (simulation, 21.5k posts, eps=0.1, 3 seeds)

Epoch = 20 batches of 100 posts; with P lanes, wall-clock time is ~1/P of sequential.

| lanes | entries | residual % | recall >=3 | Spearman | stance MAE (no census) | stance MAE (census) | emerging recall | merges |
|---|---|---|---|---|---|---|---|---|
| 1 | 435 | 0.230 | 100% | 0.931 | 0.060 | 0.030 | 92% | 1832 |
| 4 | 440 | 0.246 | 100% | 0.932 | 0.064 | 0.032 | 94% | 2087 |
| 16 | 445 | 0.254 | 100% | 0.931 | 0.062 | 0.030 | 91% | 2363 |
| 64 | 445 | 0.239 | 100% | 0.934 | 0.063 | 0.035 | 93% | 2421 |
