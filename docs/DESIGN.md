# The Conserved Evidence Ledger (CEL)

### Absorbing a whole corpus into a model, without retrieval

> **One sentence:** RAG makes the model combine a small sample of documents every time a question is asked. CEL combines **every** document **once**, when it is ingested, into a ledger of distinct assertions. Each assertion carries exact stance tallies by person and over time. The total weight in the ledger always equals the number of documents ingested. At question time the model reads the **entire** ledger, not a sample. When it needs more detail, it re-reads an exact posting list (an exhaustive *census*), not similarity-search results.

This document is the result of a 24-hour iteration (rounds listed in §11):
1. A first-principles analysis.
2. A design.
3. A simulation with known ground truth.
4. Real-model experiments on two kinds of real data:
   - SemEval-2016 stance tweets, which have gold labels;
   - every public Bluesky post on two niche topics, about 6,000 posts each, X-like and uncurated.

Real-data results replaced several of my first-pass claims; where they did, the correction is stated.

---

## 0. TL;DR, what the evidence says

**Real data, real models.** Haiku 5.5 absorbs. Sonnet 5.5 consolidates and judges. Opus 5.5 reads.

| Question | RAG | CEL | Source |
|---|---|---|---|
| Is a random post's point present in what the reader receives? Equal ~31k-token budget, Bluesky, judge-scored | top-k at the same budget: 40–45%; random sample at the same budget: 51–52%; top-20: 11% | **62–63%** (points entirely absent: 12–15% vs 31–40%) | §7.3 |
| Same, with the whole ledger (every entry: 51k / 72k tokens, for 247k / 282k-token corpora) | top-k at the same budget: 54% / 66%; random sample at the same budget: 55% / 73% | **63% / 75%** (points entirely absent: **6–11%** vs 16–34%) | §7.3 |
| How many posts mention X, and by how many people? (16 questions, two Bluesky topics) | top-100: 46–58% median error; top-20: ~91% | **ledger + census: 0–1% median error**, 88–100% of answers within 20% | §7.3 |
| What share of a corpus favours or opposes the target? (SemEval, re-mixed so memorised statistics fail) | top-20: 16–18 pt error | **4.5–4.9 pt** (classifying every tweet for this question: 6.2) | §7.2 |
| Per-tweet stance recovered *through* the ledger (SemEval F_avg) | n/a | **0.801**, vs 0.749 for Haiku classifying each tweet directly | §7.2 |
| Absorber filing errors (independent judge, 199 random real posts) | n/a | **1–4% wrong**, 25–35% "minor issue" | §7.3 |

**Cost (measured).**
- **Ingest:** ~$0.60–0.70 per 1,000 posts, every post read once. 6,000 posts took about 30 minutes with 8 parallel lanes.
- **Per question, as run here:** reading the ledger cost ~$0.50, because every CLI call re-sent the 32k-token ledger uncached and Opus ran at medium effort. With the ledger as a cached prefix through the SDK, it would be ~$0.02–0.05.
- **Census:** ~$0.12 per 1,000 posts scanned.
- **At equal reading budget,** CEL and RAG cost the same per question, and CEL delivers more coverage. Against cheap top-20 RAG, CEL costs more per question but answers questions RAG structurally can't.

**Where CEL is *not* better:**
- When a narrow question can be answered by a handful of posts, RAG is cheaper and often as good.
- Ledger counts carry the absorber's error unless verified by census.
- Real topics did **not** saturate: distinct assertions grew roughly like N^0.8 or faster. Savings come from compression and a fixed reading budget, not from the ledger staying small.

---

## 1. How RAG feeds information into a model, step by step

Below is the standard pipeline, with each point where information is **lost (L)** or cost is **wasted (W)**.

**Step 1: Segmentation (chunking).** Documents are cut into pieces, or, for tweets, each post stands alone.
- **L1 Context severance.** A reply saying "this is false" means nothing without its parent. Quote-tweets, threads and coreference ("he", "the token", "this") are split from what they refer to.

**Step 2: Encoding (embedding).** Each chunk becomes a single point in vector space.
- **L2 Projection loss.** The vector is trained for *topical similarity*. Stance ("X is a scam" vs "X is not a scam"), negation, quantities, time, and *who said it* are mostly flattened away. Two opposite claims about the same thing land next to each other.

**Step 3: Indexing.** Chunks are stored independently.
- **W1 Redundancy stored, not compressed.** Four hundred posts saying the same thing become four hundred index entries. The index never learns that they agree. Nothing that relates documents to each other is ever computed.

**Step 4: Query encoding.**
- **L3 Question-type mismatch.** "What does the community think overall?", "what is rising?", "what share disputes X?" are questions about the *distribution*. A distribution can't be embedded as a point, so there is no "nearest neighbour" to such a question.

**Step 5: Selection (top-k).** This is the dominant loss.
- **L4 Sampling ceiling.** At most k/N of the corpus reaches the model: 20/21,500 ≈ 0.09%. Anything outside the top-k is invisible, however important it is.
- **L5 Redundant selection.** Near-duplicates cluster around the query, so the k slots are spent on the *most repeated* phrasing. Effective diversity is far below k. Bot spam is the extreme case: near-identical posts are maximally similar to each other.
- **L6 Confirmation bias.** Selection by similarity to the question returns text that *agrees with the question's framing*. Ask "is X a scam?" and you retrieve scam claims.
- **L7 No denominator.** The model never learns how many matching documents exist, or how many disagree. It cannot tell "the only 20 posts" from "20 of 20,000".

**Step 6: Context assembly.**
- **W2 Re-reading at full price.** The expensive model re-reads raw, duplicate-laden text on every query. Nothing learned in query 1 is kept for query 2.
- **W3 Coverage costs linearly.** The only lever for coverage is larger k, which raises cost linearly. Full coverage means k = N, i.e. long-context stuffing: about 250k tokens per question for 6,000 real posts, and no longer possible once a topic passes roughly 20k posts.

**Step 7: Generation.**
- **L8 Sample presented as population.** The model reasons from a sample but answers as if it had seen everything, with no indication of how large its blind spot is.

**Structural diagnosis.** The useful work is *integration across documents*: noticing that 300 people say A, 40 dispute it, and it started last Tuesday. RAG does that work **at query time**, **on a sample**, **with the most expensive model**, and **throws it away** afterwards. Every listed loss follows from that placement. Better embeddings, re-rankers or larger k change the sample but not the placement.

---

## 2. What "absorbing the whole corpus" actually requires

From §1, a representation that lets the model judge on *all* available information must have these properties:

- **R1 Total influence.** Every document changes the representation, or is explicitly recorded as not having changed it.
- **R2 Size ∝ distinct content, not volume.** Repeated content becomes a count rather than repeated text. (Real data, §7.3: about 4–5 posts per entry and 5× fewer tokens than the raw corpus. Redundancy helps, but less than I first assumed, and real topics kept producing new assertions.)
- **R3 Multiplicity kept.** How many, how many distinct people, how much reach, and when. Without counts there are no judgments about prevalence.
- **R4 Dissent kept.** Support and dispute are tallied separately on the same assertion.
- **R5 Known unknowns.** The model is told *how much* it could not interpret.
- **R6 Integration amortized.** Cross-document synthesis is done once and reused by every query.
- **R7 Incremental.** New posts update the representation without a rebuild.
- **R8 Exact drill-down.** When more detail is needed, the system can enumerate *exactly* the documents behind a statement, not documents that look similar.

None of chunk retrieval, embedding search, summarization, knowledge graphs or fine-tuning meets R1+R3+R4+R5 together. Summaries drop counts and dissent. Knowledge graphs drop stance and non-triple content. Fine-tuned weights can't count and can't be audited. This set of requirements is what CEL is built from.

---

## 3. The core idea

> **Invert the placement of integration.** Every document is read exactly once, by a cheap model, *against the complete current state of knowledge about the topic*. Each document is turned into a few **ledger operations** ("supports e17", "disputes e4", "new assertion: …", "noise", "can't tell"). The ledger is the only artifact. Its unit is the **assertion with a tally**, not the document, chunk, entity, vector or summary.

Two invariants make it trustworthy:

1. **Conservation of evidence.** Each document carries exactly 1 unit of mass, split across its ops.
   `Σ entry mass + residual mass + noise mass = documents absorbed`, which is checked after every operation. Merges and splits move mass but never create or destroy it. A document the absorber can't place goes to the **residual**, never into silence.
2. **Exact provenance.** Every op is logged (doc → entries). Every tally can therefore be recomputed exactly, every entry has a complete posting list, and splits and census queries are exact.

The model then reads the whole ledger, and the conservation invariant means the whole ledger is the whole corpus. A third element, added after real-data error analysis (§4.4), is the **anchor**: one literal statement of the subject's central question, with a dedicated pass recording every author's position on it. That makes subject-level stance and camp cross-tabs exact counts rather than inferences.

---


## 4. Mechanism

Reference implementation:
- [`celedger/ledger.py`](../celedger/ledger.py): data structure, invariants, views and census.
- [`real_eval/semeval.py`](../real_eval/semeval.py) and [`real_eval/bsky.py`](../real_eval/bsky.py): the real absorber, consolidation, residual escalation and lanes.
- [`real_eval/anchor_pass.py`](../real_eval/anchor_pass.py): the dedicated subject-stance pass.
- [`celedger/absorber.py`](../celedger/absorber.py): the SDK-form absorber (v1 prompt; the CLI-driven `real_eval/` code is the up-to-date pipeline).

### 4.1 Entry (the unit)
A real line from the seed-oils ledger (6,062 Bluesky posts):
```
e384 | Seed oils are reflexively blamed for problems they did not cause. | 116 authors ▲109 ▼2 ·5 | 103 docs | camp: anchor▲34 anchor▼6
```
An entry is a *proposition someone could agree or disagree with*, or an observation. It carries:
- stance masses
- author → latest stance, so counts are of **people**, not posts
- author → doc mass, which drives the ⚠ concentration flag for coordinated amplification
- reach
- a 12-bin time histogram
- one exemplar per stance
- first-seen time
- a theme
- the **camp** cross-tab (§4.4)

### 4.2 Operations and the two invariants
Each document gets typed ops: `assign(entry, support|dispute|mention)` · `new(canonical statement, stance)` · `noise` · `residual`. An id the absorber invents becomes `residual`; it is never dropped or guessed.

**Conservation.** Each document carries one unit of mass, split across its ops: `Σ entry mass + residual + noise = documents absorbed`. This is checked after every operation. Merges, splits and op replacement are all mass-conserving and tested (`tests/`).

**Provenance.** Every op is logged, so every entry has an exact posting list and every tally can be recomputed. Merges are applied incrementally, and a test proves they equal a full recompute.

### 4.3 Absorption
- **Batches** of 40–50 posts. Prompt = [instructions + frozen ledger index] (a stable, cacheable prefix) + [entries created this epoch] + [the batch].
- **Append-only within an epoch,** so the cached prefix stays valid.
- **Every post meets everything known so far.** No similarity selection decides what it is compared with.
- **Lanes (throughput).** Within an epoch, P batches are absorbed concurrently. Each lane sees the frozen index but not the other lanes' brand-new entries until the epoch's consolidation. Model calls overlap; ledger updates are serialised.
  - Simulation: P = 64 changes no quality metric (§7.4).
  - Real data: 8 lanes absorbed 6,000 posts in ~18 minutes, against an estimated ~4 hours sequentially.
- **Noise is reserved for contentless posts.** Any post expressing an opinion gets an entry. Calling stance-bearing posts "off-topic" caused 52% of v1's stance losses (§7.2).
- **Residual escalation.** Posts the cheap model can't place are re-read once by a stronger model, against the now-larger ledger. Residual fell from about 12% to about 4.3% on both Bluesky topics.

### 4.4 The anchor and camps (added after real-data error analysis)
The user states the subject as one unambiguous statement, e.g. *"Seed oils are safe and healthy to eat."* Entry e0 is that **anchor**.
- **A dedicated cheap pass** asks only one question of every post: does the author agree, disagree, or neither?
  - **v2** asked the main absorber to add anchor ops while filing assertions. The real-data audit found **54–71% of positions missing**, and the miss rate differed by camp, which biased the subject-level share by 13–16 points.
  - **v3** uses the dedicated pass at $0.31 per 6k posts. It cut missing positions to 9–17% and the bias to 4–6 points (§7.3).
- **Camp cross-tab, at no extra cost.** Every line shows how many of its authors agree or disagree with the anchor ("camp: anchor▲34 anchor▼6"). The reader can answer "what do skeptics argue that defenders don't?" directly.
- **The anchor must be a literal statement.** "In favour of seed oils" was read inconsistently, because in this debate "the topic" can mean the anti-seed-oil movement. That was caught by the audit and fixed.

### 4.5 Consolidation ("sleep")
- **Each epoch:** the same cheap model, reusing the cached prefix, merges this epoch's new entries into existing ones when they are paraphrases.
- **At the end, or periodically:** a stronger model reads only the index (no documents) for global merges.
- **Splits** re-route an entry's exact posting list.
- **The anchor is never merged.**
- **Ablation:** without consolidation the ledger is 5× larger, census error doubles, and emerging-claim recall drops 81% → 64% at ε=0.2 (§7.4).

### 4.6 What the reader sees
- **Flat view:** entries by number of distinct authors until the token budget is used. One fold line gives the exact count and share of everything not shown.
- **Theme view:** 8–15 model-proposed themes. Each theme shows its exact mass and at least its top two entries; remaining slots go by global rank; each theme's remainder folds with its exact count. At 500k simulated posts and a 32k budget it shows 98% of claims held by ≥10 people, against 72% for the flat view.
- **A legend is required.** The view's header explains the anchor and camp columns. Without it, Opus misread the anchor line: SemEval climate error was 17.9 points without the legend and 1.0 with it (§7.2).
- **Budget is a dial.** A 32k view costs a few cents per question when cached; 128k shows everything held by ≥3 people at 500k posts (simulated) for ~$0.04 per question.

### 4.7 Census (exhaustive, exact-scope verification)
- **The step:** the reader writes a yes/no predicate and a scope (all posts, or specific entries' posting lists). A cheap model checks **every** post in scope, and the exact result goes back to the reader.
- **Real accuracy:** checker precision 0.95–1.00, recall 0.99–1.00 against text-match gold.
- **Why it is needed:** the ledger stores meaning, not words. "How many posts mention tallow?" is not answerable from the ledger alone (57–88% median error), but census makes it exact.
- **Cost:** ~$0.12 per 1,000 posts scanned.
- **Reuse:** results can be written back to the ledger as a new dimension.

### 4.8 Sharding (very large ledgers)
- Above a cap, the absorber sees a table of themes plus the routed theme's entries.
- Simulation, 500k posts, cap 2k entries: 5–15% misrouting costs **13–41% more fragments** per claim and 65–85% more entries. It costs almost nothing in ranking or visibility, because repeated consolidation eventually merges cross-shard duplicates.
- So fragmentation is the price of sharding. Keep the absorber prefix unsharded as long as the context allows; ~150k tokens is about 8k entries.

---

## 5. Why it is cheaper, and where it is not

All figures are measured on real runs unless marked "projected".

| | RAG top-20 | RAG at equal budget | Long context (whole corpus) | CEL |
|---|---|---|---|---|
| One-time cost | ~0 | ~0 | 0 | **$0.60–0.70 per 1k posts** (Haiku absorb + Sonnet consolidate/escalate/label) |
| Reader tokens per question | ~1k | ~31–72k raw posts | 247–282k for 6k posts; impossible past ~4M posts' worth | ~31k (view) / 51–72k (full ledger) |
| $ per question, as run (uncached CLI) | $0.03–0.04 | ≈ CEL | ≈ 5–8× CEL | $0.50–0.53 |
| $ per question, projected with prompt caching | same | same | 0.05× input | **~$0.02–0.05** |
| Can answer "how many / what share / what's rising" | no | sample estimate only | in principle, if it fits | yes (tallies), exact with census |

What makes it cheaper:
1. **Integration is paid once,** by the cheapest model, and reused by every question.
2. **The reading cost is bounded by the view's budget, not by corpus size,** and the view never hides the denominator.
3. **5–8× fewer tokens than reading everything,** with exact counts kept.
4. **Coverage per token is higher than retrieval at the same budget** (§7.3).

Where it is not cheaper:
- If you'll ask a few narrow questions, top-20 RAG is cheaper: $0.03–0.04 per question and no ingest, against $0.50 for an uncached ledger read here (comparable once the ledger is cached).
- Real conversation keeps producing new assertions (§7.3: entries grew roughly like N^0.8 or faster, and 62% are one-off), so the ledger keeps growing. Above roughly 50k posts on one topic, the theme view's folding or a larger budget matters.
- My first-pass cost model **underestimated real ingest cost by ~30×.** It assumed Haiku-only and minimal output; the real pipeline uses Sonnet stages and wordier ops, with CLI overhead. Redoing the equal-coverage comparison in §7.4 with ~30× the ingest cost still favours CEL by roughly 20–30× at 20k–200k posts (and RAG at parity no longer fits a context window at 500k), but treat the simulated dollar figures as optimistic.

---

## 6. Why the model gets fuller coverage than with RAG
1. **Nothing is selected away.** Every document's mass is visible as an entry, a fold line or the residual.
2. **The denominator is always present:** counts of people and posts, the residual %, and noise %.
3. **Dissent and camps are kept by construction,** not lost to similarity ranking.
4. **Redundancy becomes a count,** not repeated text crowding out the long tail.
5. **Time is a dimension,** so emergence is readable.
6. **Exactness on demand** via census.

On real data this shows up most clearly as **2–3× fewer complete misses** than raw text at the same budget (§7.3).

---

## 7. Evidence

### 7.1 What was tested where
| Setting | Data | Ground truth | Absorber |
|---|---|---|---|
| Simulation | synthetic X-like feeds, 20k–500k posts | exact | parameterised error rate ε |
| SemEval-2016 Task 6 | 4,163 real tweets, 5 targets; re-mixed subsets of 173–300 | human stance labels | real Haiku 5.5 |
| Bluesky | every searchable public post on "seed oils" (6,062 posts, 4,139 authors) and "ultra-processed food" (6,042, 3,846), Jul 2025 – Nov 2026 | text-match gold for counts; an independent Sonnet judge for coverage and filing | real Haiku 5.5 (v2/v3) |

### 7.2 SemEval-2016 (real tweets, gold labels): [`results/real`](../results/real), [`results/real_remix_v1`](../results/real_remix_v1), [`results/real_remix_v2`](../results/real_remix_v2)
- **Per-tweet fidelity.** Stance predicted *through* the ledger (entry polarity × op stance) scores F_avg 0.732 (v1) against 0.738 for Haiku classifying each tweet directly. Writing tweets into the ledger preserves stance.
- **Benchmark contamination (an important negative result).**
  - On the original corpora, RAG with 20 tweets reproduced the gold stance split to within a point, which 20 tweets can't support.
  - A no-data control confirmed that the reader had memorised the benchmark's label statistics: its error with no data was 24–25 points, against the re-mixed truth.
  - **Any evaluation of corpus-level answers on public benchmarks must control for this.** I re-sampled each target to a stance mix far from the published one.
- **Contamination-free aggregate question** ("what share favours / opposes the target?"), mean absolute error in points:

| prior only (no data) | RAG top-20 | RAG top-50 | random 20 | random 50 | classify every tweet | **CEL computed** | **CEL read by Opus** |
|---|---|---|---|---|---|---|---|
| 24.0 | 16.2 | 18.2 | 15.2 | 6.9 | 6.2 | **4.5** | **4.9** (with legend) |

- **v1 → v2, after error analysis.**
  - Of the stance-bearing tweets v1 got wrong, 52% had been called noise, 16% landed in neutral-worded entries, 14% stayed residual and 17% were flipped (largely sarcasm).
  - v2 added the anchor, the strict noise rule and residual escalation. F_avg rose 0.775 → **0.801** (direct classification: 0.749), and mispredicted stance-bearing tweets fell 237 → 144.
- **Census questions** (7 questions, small *n*):

| | median count error | stance-share error |
|---|---|---|
| ledger + census | **0%** | **5.3 pts** |
| RAG top-100 | 52% | 16.9 pts |
| RAG top-20 | 75% | 27.2 pts |

### 7.3 Bluesky (real, uncurated, X-like): [`results/bsky_seedoils`](../results/bsky_seedoils), [`results/bsky_upf`](../results/bsky_upf)
**Ingest**

| | posts | authors | entries | residual (before → after escalation) | full ledger tokens / corpus tokens | ingest $ | wall time (8 lanes) |
|---|---|---|---|---|---|---|---|
| seed oils | 6,062 | 4,139 | 1,237 | 12.2% → 4.3% | 51k / 247k | $3.60 + $0.32 anchor pass | 29 min |
| ultra-processed food | 6,042 | 3,846 | 1,604 | 11.9% → 4.5% | 72k / 282k | $4.24 + $0.31 | 30 min |

**Filing audit.** An independent judge graded 100 random posts per topic:
- wrong: **4% / 1%**
- minor issue: 25% / 35%
- correct: 71% / 63%

Typical wrong filings: misread sarcasm, and posts that don't mention the topic at all. **This places the real absorber at ε ≈ 0.01–0.04 strict, or 0.25–0.35 including imprecision,** inside the range swept in simulation.

**Anchor audit** (150 posts per topic, judge labels vs ledger):

| | agreement | positions missing | inverted | spurious | agree-share bias vs judge |
|---|---|---|---|---|---|
| seed oils v2 → v3 | 57% → 75% | 54% → 9% | 9% → 10% | 4% → 34% | 16 → **4** pts |
| UPF v2 → v3 | 56% → 84% | 71% → 17% | 0% → 0% | 3% → 14% | 13 → **6** pts |

**Coverage.** For random posts that make a point (129–131 and 68 posts), the judge decided whether that point is present in the reader's input. Score = yes + ½ partly; the "absent" column is the share judged entirely missing.

| reader input | tokens | seed oils score / absent | UPF score / absent |
|---|---|---|---|
| RAG top-20 | ~1k | 11% / 82% | 11% / 79% |
| RAG top-100 | ~4–6k | 19% / 71% | 21% / 66% |
| RAG top-k at the theme view's budget | ~31k | 45% / 39% | 40% / 40% |
| random sample at the theme view's budget | ~31k | 52% / 34% | 51% / 31% |
| **CEL theme view** | ~31k | **62% / 15%** | **63% / 12%** |
| RAG top-k at the full ledger's budget | 50k / 71k | 54% / 34% | 66% / 19% |
| random sample at the full ledger's budget | 50k / 71k | 55% / 32% | 73% / 16% |
| **CEL full ledger** | 51k / 72k | **63% / 11%** | **75% / 6%** |

Reading this honestly:
- The ledger's clear, robust advantage is that it **rarely misses a point entirely**: 6–15% absent, against 16–40% for raw text at the same budget.
- On the combined score, its lead over a *random sample* shrinks at larger budgets (UPF: 75 vs 73). The ledger's canonical wordings generalise, so the judge often grades them "partly".
- Retrieval at the same budget is consistently worst among the large-budget options, because similarity ranking concentrates on near-duplicates.

**Counting questions** (16 questions; gold = text match over every post):

| method | median count error | within 20% | median author-count error | $ / question as run |
|---|---|---|---|---|
| CEL read alone | 57–88% | 0–25% | 43–86% | $0.50–0.53 |
| **CEL + census** | **0–1%** | **88–100%** | **0–1%** | $0.70–0.72 |
| RAG top-20 | 91–92% | 0% | 100% | $0.03–0.04 |
| RAG top-100 | 46–58% | 0% | 100% | $0.10–0.11 |

**Growth on real data** (replaces the assumed scaling exponent):
- Entries grew like N^0.78 (seed oils) and N^0.84 (UPF).
- Entries with ≥3 authors grew like N^0.86–1.06 over the year.
- 62–63% of entries have a single author.
- Real niche conversation is event-driven and did **not** saturate at 6k posts.
- So the ledger compresses 4–5× in tokens rather than collapsing to a small fixed size, and the fixed-budget view with exact folds is what bounds per-question cost.

### 7.4 Simulation (exact ground truth): [`results/results.md`](../results/results.md), [`results/scale.md`](../results/scale.md), [`results/ablation.md`](../results/ablation.md), [`results/lanes.md`](../results/lanes.md)
Setup: 21,500 posts, 300 latent claims, emerging and fading claims, a 6-account bot flood. RAG has a *perfect* reader, so only its selection step can fail.

| | RAG (best k=100) | CEL ε=0.1 |
|---|---|---|
| claims held by ≥3 people that are visible | 20% | **100%** |
| prevalence ranking (Spearman) | 0.38–0.46 | **0.93** |
| emerging claims, precision / recall | 67% / 3% | **88% / 92%** |
| stance share error, head / mid / tail | 0.045 / 0.011 / 0.001 | 0.052 / 0.058 / 0.060; **with census 0.019 / 0.018 / 0.031** |
| bot-flooded claim, support share (truth 12%) | 13–40% depending on k, cause invisible | 17% after discounting the ⚠-flagged accounts (all 6 bots flagged); 92% if you count posts |

**Open world** (Pitman-Yor claim stream, 20k–500k posts):
- With fair token accounting, the theme view keeps 97–100% of ≥10-person claims visible up to 200k posts at 32k tokens, and 98% at 500k.
- For 1,000 questions at ~90% coverage: **$19–36 for CEL** against $730–3,600 for RAG, which doesn't fit in a 1M context at 500k posts.
- These dollar figures use the simulated cost model. Per §5, real ingest costs ~30× more, which still leaves CEL ahead by roughly 20–30× at equal coverage.

**Ablations** (ε=0.2):

| variant | entries | census stance error | emerging recall |
|---|---|---|---|
| full CEL | 763 | 0.042 | 81% |
| no consolidation | 3,818 (5×) | 0.092 | 64% |

Without residual re-absorption, 4–9% of the corpus stays unplaced; the other metrics barely move.

**Lanes:** 1 → 64 lanes leaves every quality metric unchanged; consolidation does ~30% more merges.

---

## 8. Is it novel? An honest positioning

No vectors, embeddings, chunking pipeline, fine-tuning or knowledge graph are used; BM25 appears only as the baseline. The ingredients are generic: LLMs emitting typed output, and caching. The claimed contribution is the combination:
- **(a)** online absorption of every document against the complete current state;
- **(b)** a mass-conservation invariant with an explicit residual;
- **(c)** stance- and person-tallied assertions, cross-tabbed with a subject anchor, as the storage unit;
- **(d)** exact-scope census in place of retrieval;
- **(e)** a fixed-budget view that never hides the denominator.

| Nearest neighbour | What CEL changes |
|---|---|
| Hierarchical or community summaries (RAPTOR, GraphRAG ([Edge et al. 2024](https://arxiv.org/pdf/2404.16130))) | Summaries drop counts, dissent and the denominator, and their loss is unauditable. CEL keeps exact tallies and provenance under conservation. |
| Knowledge graphs | The unit is an assertion with stance tallies, not a triple. |
| Schema extraction ([AI Engineer 2025](https://ai.engineer/talks/rag-evaluation-is-broken-here-s-why-and-how-to-fix-it)) | No predefined schema; assertions emerge and consolidate, and census adds dimensions on demand. |
| Per-query exhaustive scanning ([Stakeholder Suite](https://arxiv.org/pdf/2512.17347), DFA/[AGGBench](https://www.alphaxiv.org/abs/2602.01355)) | CEL reads exhaustively **once**, against all prior knowledge, and every later question reuses it. |
| Per-document classification | Must know the question at ingest time. CEL was question-agnostic and still matched or beat it (§7.2). |

GlobalQA ([arXiv 2510.26205](https://arxiv.org/html/2510.26205v1)) and AGGBench document the top-k failure on counting and aggregation that CEL targets. I found no prior work combining (a)–(e). That is a search result, not proof.

---

## 9. Limitations and failure modes (updated from real data)
- **Absorber quality is the critical parameter.** Real strict error is 1–4%, but 25–35% of filings are imprecise. Ledger tallies are good for shape and ranking; for numbers that matter, run a census.
- **The anchor must be a literal statement** chosen at setup. A dedicated pass is needed for good recall, and it over-calls positions on 14–34% of posts that have none.
- **The reader must be told the semantics.** Without the legend, Opus misread the anchor line.
- **Lexical questions need census.** The ledger stores meaning, not words.
- **No saturation on real topics** at the scale tested. Ledgers grow roughly like N^0.8. Expect to fold, raise the budget, or shard.
- **Sharding costs fragmentation** (13–41% more fragments per claim in simulation).
- **Evaluation pitfalls found along the way:** benchmark memorisation (§7.2), and LLM judges for coverage, which grade generalised wording as "partly". Small *n* for the census questions (7 + 16).
- **Canonical wording drifts** as a conversation evolves. Rewording is mass-neutral but needs a periodic pass.
- **Single model family.** Every model here is Claude (Haiku / Sonnet / Opus). Judge and absorber share training lineage, so the audits are not fully independent.

---

## 10. How to use it on your own topic (e.g. everything about a subject on X)
1. Collect every post on the topic (search API, paging back in time).
2. Write one literal **anchor statement** for the subject's central question.
3. Ingest with `real_eval/bsky.py` (lanes 8), then `real_eval/anchor_pass.py`.
4. Give the reading model the theme view (or the full ledger if it fits) as a cached prefix, and let it issue **census** requests for anything it needs exactly.
5. Re-run steps 3–4 incrementally as new posts arrive. Absorption is append-only, and consolidation runs per epoch.

---

## 11. The 24 hours: rounds and what each changed
| Round | What was done | What it changed |
|---|---|---|
| 0 | First-principles analysis, design, simulation | The initial claims, several later revised |
| 1 | Real Haiku absorber on 4,163 SemEval tweets | Per-tweet stance preserved through the ledger (0.732 vs 0.738) |
| 2 | Re-mixed corpora + prior-only control; error analysis → absorber v2; ablations | Found benchmark memorisation; v2 F_avg 0.801; noise rule, anchor, escalation |
| 3 | Open-world scaling to 500k, sharding, budget sweep | Theme view fixed (it was mis-budgeted); sharding costs fragmentation |
| 4 | Census Q&A with gold answers | Exact counts (0% median error) vs RAG 52–75% |
| 5 | Every Bluesky post on two niche topics; filing, coverage and anchor audits; lanes; v3 anchor pass | Real ε; coverage at equal budget; anchor recall bug found and fixed; real growth exponent (no saturation); real costs ~30× the first estimate |
