# Conserved Evidence Ledger (CEL)

A retrieval-free way to have a language model absorb **everything** a corpus says about a niche topic (for example, all posts about a subject on X) and reason from the full distribution instead of a top-k sample.

- **Design and first-principles analysis of RAG:** [`docs/DESIGN.md`](docs/DESIGN.md)
- **Experiment results (CEL vs RAG, synthetic feed with ground truth):** [`results/results.md`](results/results.md)
- **What the reading model actually sees:** [`results/sample_ledger_view.txt`](results/sample_ledger_view.txt)

## Layout
| path | what |
|---|---|
| `celedger/ledger.py` | the ledger: entries, ops, conservation invariant, merge/split, residual re-absorption, rendering, census |
| `celedger/absorber.py` | production absorber (Claude Haiku 5.5, cached append-only index) and consolidation; needs an API key, not exercised here |
| `sim/world.py` | synthetic niche-topic feed with full ground truth (Zipf claims, stances, emerging claims, bot flood) |
| `sim/sim_absorber.py` | absorber stand-in with an explicit error rate `eps` |
| `sim/baseline.py` | RAG baseline: BM25 top-k with a perfect reader |
| `sim/cost.py` | token and dollar model (Nov 2026 list prices) |
| `sim/experiment.py` | runs everything and writes `results/` |
| `tests/` | invariant tests |

## Run
```bash
pip install numpy pydantic pytest
python -m pytest -q tests
python -m sim.experiment     # ~1 min, rewrites results/
```
