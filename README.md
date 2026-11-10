# Conserved Evidence Ledger (CEL)

A retrieval-free way to have a language model absorb **everything** a corpus says about a niche topic (for example, every post about a subject on X) and reason from the full distribution, not a top-k sample.

- **Design, first-principles analysis of RAG, and all evidence:** [`docs/DESIGN.md`](docs/DESIGN.md)
- **What the reading model actually sees** (a real ledger of 6,062 Bluesky posts): [`results/bsky_seedoils/ledger_multires.txt`](results/bsky_seedoils/ledger_multires.txt)
- **Real-data results:**
  - SemEval-2016 tweets: [`results/real`](results/real), [`results/real_remix_v1`](results/real_remix_v1), [`results/real_remix_v2`](results/real_remix_v2)
  - Bluesky: [`results/bsky_seedoils/eval.md`](results/bsky_seedoils/eval.md), [`results/bsky_upf/eval.md`](results/bsky_upf/eval.md)
- **Simulation results:** [`results/results.md`](results/results.md), [`results/scale.md`](results/scale.md), [`results/ablation.md`](results/ablation.md), [`results/lanes.md`](results/lanes.md)

## Layout
| path | what |
|---|---|
| `celedger/ledger.py` | the ledger: entries, ops, conservation invariant, merge/split/replace, anchor and camp cross-tab, flat and theme views, census |
| `celedger/llm.py` | model-call backend (the `claude` CLI with structured outputs; spend tracking) |
| `celedger/cli.py` | the tool: `ingest`, `ask` (with reader-triggered census), `update`, `census`, `view` |
| `celedger/absorber.py` | SDK-form absorber (v1 prompt) |
| `real_eval/semeval.py`, `remix.py`, `errors.py`, `reread.py`, `qa.py` | SemEval-2016 experiments: fidelity, contamination-free remix, error analysis, census Q&A |
| `real_eval/bsky_fetch.py`, `bsky.py`, `anchor_pass.py`, `bsky_eval.py`, `anchor_audit.py`, `coverage_full.py` | Bluesky pipeline: fetch (authors pseudonymised), ingest with lanes, v3 anchor pass, audits, coverage, counting Q&A |
| `sim/` | synthetic worlds with ground truth, RAG baseline, cost model, scaling, ablations, lanes |
| `tests/` | invariant tests (conservation, merges, op replacement, camps, census scope) |

Raw post text is never committed: ledger pickles are git-ignored.

## Use it on your own topic
```bash
python -m celedger.cli ingest posts.jsonl --topic "seed oils" --anchor "Seed oils are safe and healthy to eat." --out ledgers/seedoils
python -m celedger.cli ask ledgers/seedoils "What do skeptics argue, and how many people make each argument?"
python -m celedger.cli update ledgers/seedoils new_posts.jsonl
```
`posts.jsonl`: one JSON object per line with `text`, and optionally `author`, `created`, `likes` and `reposts`.

## Reproduce the experiments
```bash
pip install numpy pydantic pytest
python -m pytest -q tests
python -m sim.experiment && python -m sim.scale_experiment && python -m sim.ablation && python -m sim.lanes
# real data (uses the `claude` CLI):
python -m real_eval.bsky_fetch "seed oils" DATA_DIR
python -m real_eval.bsky DATA_DIR/posts.json results/bsky_seedoils --topic "seed oils" \
    --anchor "Seed oils (canola, soybean, sunflower etc.) are safe and healthy to eat." --lanes 8 --epoch-batches 8
python -m real_eval.anchor_pass results/bsky_seedoils
python -m real_eval.bsky_eval results/bsky_seedoils
```
