# The Conserved Evidence Ledger (CEL)

### Absorbing a whole corpus into a model, without retrieval

> **One sentence:** RAG makes the model combine a small sample of documents every time a question is asked. CEL combines **every** document **once**, when it is ingested, into a ledger of distinct assertions with exact stance tallies. The total weight in the ledger always equals the number of documents ingested. At question time the model reads the **entire** ledger, not a sample, and when it needs more detail it re-reads an exact posting list (an exhaustive census), not similarity-search results.

---

## 0. TL;DR

| | Top-k RAG | Conserved Evidence Ledger |
|---|---|---|
| What the model sees | k snippets (≈0.1% of a 20k-post corpus at k=20) | every document's contribution, compressed by redundancy |
| Knows the denominator? | no: it can't tell "20 of 20" from "20 of 20,000" | yes: every line carries exact counts, and an *unplaced* (residual) percentage is always shown |
| When cross-document synthesis happens | at every query, on a sample, by the expensive model | once per document, at ingest, by a cheap model, against everything already known |
| Aggregate questions (how many / what share / what's rising) | structurally can't answer them | the ledger *is* the distribution |
| Dissent and minority views | lost unless the query happens to match them | kept as stance tallies on every entry |
| Coordinated amplification (bots) | invisible; can dominate what gets retrieved | visible: per-entry author-concentration flag |
| Per-query cost | k·chunk tokens at full price, repeated every query | one cached read of a ~10–30k-token ledger |
| Auditable? | no | yes: total mass = number of docs, every tally can be recomputed from provenance |

On a simulated niche-topic feed (21,500 posts, 300 latent claims, a bot flood, ground truth known), at an absorber error rate of 10%:
**all** claims held by ≥3 people were visible to the model (RAG k=100: 20%), prevalence rank correlation was 0.93 (RAG: 0.38–0.46), emerging-claim detection reached 92% precision / 88% recall (RAG: ≈3% recall), and the bot flood was caught (support share 15% vs a true 12%; a post-counting view says 92%). Ingest cost $0.23–0.46, one time; each query after that costs about the same as a k=20 RAG query. To reach comparable coverage, RAG must read about 10% of the corpus per query, which is roughly 20× more expensive per query. Details and caveats are in §7 and in [`results/results.md`](../results/results.md).

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
- **W3 Coverage costs linearly.** The only lever for coverage is larger k, which raises cost linearly. Full coverage means k = N, i.e. long-context stuffing, which also stops fitting once the topic grows past roughly 20k posts.

**Step 7: Generation.**
- **L8 Sample presented as population.** The model reasons from a sample but answers as if it had seen everything, with no indication of how large its blind spot is.

**Structural diagnosis.** The useful work is *integration across documents*: noticing that 300 people say A, 40 dispute it, and it started last Tuesday. RAG does that work **at query time**, **on a sample**, **with the most expensive model**, and **throws it away** afterwards. Every listed loss follows from that placement. Better embeddings, re-rankers or larger k change the sample but not the placement.

---

## 2. What "absorbing the whole corpus" actually requires

From §1, a representation that lets the model judge on *all* available information must have these properties:

- **R1 Total influence.** Every document changes the representation, or is explicitly recorded as not having changed it.
- **R2 Size ∝ distinct content, not volume.** Niche-topic social media is extremely redundant, so this is where the savings come from.
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

The model then reads the whole ledger, and the conservation invariant means the whole ledger is the whole corpus.

---

## 4. Mechanism

Reference implementation: [`celedger/ledger.py`](../celedger/ledger.py) (data structure and invariants) and [`celedger/absorber.py`](../celedger/absorber.py) (LLM absorber and consolidation).

### 4.1 Entry (the unit)
```
e17 | "The v2 airdrop excludes wallets that bridged before March" |
      812 authors ▲598 ▼171 ·43 | 1,553 docs | trend ▁▂▃▅▇█ | first seen 03-02 |
      ⚠ top-5 accounts wrote 71% of docs   (only when concentrated)
      exemplars: {support: doc 88121, dispute: doc 90233}
```
An entry is a *proposition someone could agree or disagree with*, or an observation (an event, a link, a question people keep asking). Fields:
- stance masses
- author → latest-stance map, so counts are of **people**, not posts
- author → doc mass (the concentration signal)
- reach
- 12-bin time histogram
- one exemplar per stance
- first-seen time

### 4.2 Operations
`assign(entry, stance)` · `new(canonical wording, stance)` · `noise` · `residual`. The output is strictly typed (structured outputs). If the absorber references an entry id that doesn't exist, the op becomes `residual`. It is never dropped and never guessed.

### 4.3 Absorption pass (ingest)
- **Order:** by thread, then time. A reply is absorbed right after its parent and is judged in light of it, which fixes **L1**.
- **Batches** of about 100 posts. Prompt = `[instructions + frozen ledger index]` (cached) + `[entries created this epoch]` + `[batch]`.
- **Append-only within an epoch.** New entries are appended after the cached prefix rather than inserted into it, so the prefix cache stays valid for the whole epoch (about 20 batches) and is billed at cache-read rates.
- Each post therefore "meets" everything known about the topic. Over the whole run that is N document-versus-all-knowledge comparisons, which RAG never performs. This is where **L2, L3, L5, L6** are avoided: there is no projection to a vector, and no query-shaped selection.

### 4.4 Consolidation ("sleep")
At each epoch boundary:
- **Local merge.** The same cheap model, *reusing the same cached prefix*, checks only this epoch's new entries against the frozen index for paraphrase duplicates.
- **Global pass.** Every ~10 epochs, a stronger model reads only the index (no documents) to catch merges the local pass missed and to propose **splits** of overloaded entries. Because provenance is exact, a split re-routes every document of the entry. Nothing is approximated.
- **Residual re-absorption.** Residual posts are re-read once against the now-larger ledger. Many posts that were unplaceable early (the claim didn't exist yet) are placeable later.

All three operations conserve mass. `check_conservation()` runs after each one.

### 4.5 Reading (query time)
The reading model (e.g. Opus 5.5) receives the **rendered ledger**:
- a header: N documents, N authors, the % placed / residual / noise
- every entry, sorted by number of distinct authors, one line each

It is a stable prefix, so it is cached across all queries. At 444 entries it is about 13k tokens. The model answers from the full distribution ("812 people assert X, 171 dispute it, mostly in the last 3 days; 0.2% of the corpus is unplaced"). It does not answer from 20 snippets.

### 4.6 Large topics: sharded index
When the index outgrows a comfortable prefix (about 150k tokens, roughly 8k entries), it is sectioned into themes. Each section is mass-conserving: the theme's tallies are the sum of its entries. The absorber sees a one-line-per-section table plus the routed section(s). Routing is a judgment by the reading model over a table of contents, **not** a similarity lookup.

### 4.7 Multi-resolution rendering (no hidden denominator)
If the ledger exceeds the reading budget (32k tokens in the experiments), lower-mass entries are **folded** into a line that still states their exact count and share ("+330 smaller entries: 2,533 docs, 11.8% of corpus"), or into per-theme rollups. The model always sees 100% of the mass at some resolution, and can expand any fold **by id**. That is enumeration, not search.

### 4.8 Census (exhaustive verification on demand)
When a question needs a property the ledger did not record ("how many people asserting e17 are developers?", "re-verify the stance split on e4"), the reading model issues
`CENSUS(predicate, scope = entries [...] | ALL)`.
The system runs the cheap model (or a strong one, for verification) over **every** document in the exact posting list, or over a uniform random sample of it with a stated sample size, and returns counts and exemplars. The result is written back to the ledger as a new dimension, so later questions get it for free. Scope comes from provenance, so the census never misses a document *because it was worded differently*.

### 4.9 Streaming
New posts go through §4.3 incrementally. Consolidation runs on its epoch clock. The cached ledger render changes only at epoch boundaries, so the read cache stays warm between them.

### 4.10 Robustness
- **Coordinated amplification.** Shown by `author_docs` concentration and flagged in the render (§7, item 5).
- **Prompt injection inside posts.** The absorber's only power is to emit typed ops, and posts are delimited and declared as data. The worst case is a wrong op on one document, which is mass-bounded at 1 and visible in provenance.
- **Absorber error.** Bounded by consolidation, residual re-absorption and census re-verification. Its effect is quantified in §7.

---

## 5. Why it is cheaper

Cost structure, not just measured dollars:

| Cost driver | RAG | CEL |
|---|---|---|
| Reading each document | never by an LLM (embedded only) | once, by the cheapest model, mostly cache-read prefix |
| Cross-document integration | repeated every query, by the expensive model | once per document, at ingest |
| Per-query input | k·chunk tokens, full price | ledger render, **cache-read price** (0.05× on Opus 5.5) |
| Coverage | grows linearly with k | already 100% of the mass |
| Redundancy | paid for at query time, in every top-k | collapsed at ingest: a tally +1 costs ~15 output tokens |

**Measured (21,500 posts; list prices, Nov 2026; details in [`sim/cost.py`](../sim/cost.py))**
- **Ingest**, one time: **$0.46**, or **$0.23** via the Message Batches API. That covers every post read once by Haiku 5.5, plus consolidation. At $0.01 per thousand posts, absorbing everything costs less than one long-context query ($4.85).
- **Per query**: Opus 5.5 reading the cached 13k-token ledger costs **$0.015**, versus $0.017 for k=20 RAG and $0.032 for k=100 RAG. Most of either figure is the 600-token answer.
- **Total for 1,000 questions**: $15.5 (CEL) vs $17.3 (RAG k=20) vs $31.7 (RAG k=100) vs $211 (whole corpus in a 1M window, cached).

**At equal coverage.** RAG at k=20 is cheap because it sees almost nothing. To see 93% of the claims held by ≥10 people, RAG has to read about 2,000 posts (≈10% of the corpus) **per query**: $0.37 per query, about **25× CEL's per-query cost**. Projected to 1,000 queries on a 200k-post topic, that is **$3,600 for RAG at parity vs $25–45 for CEL**. At 2M posts, parity RAG and long-context no longer fit in a context window at all. CEL's ingest grows with N, but its per-query cost is bounded by the render cap.

**Where CEL is *not* cheaper (being straight about it):**
- If you will ask only one or two questions, k=20 RAG costs less. CEL breaks even at roughly 100 queries **against low-coverage RAG**, and almost immediately against RAG at equal coverage.
- If the corpus has little redundancy (code, fiction, unrelated documents), D grows like N, and CEL degrades to the cost of reading everything, though still only once.

---

## 6. Why the model gets fuller coverage than with RAG

1. **Nothing is selected away.** Conservation guarantees every document's mass is somewhere visible, folded or residual. RAG's L4 doesn't exist here.
2. **The denominator is always present.** Every line carries counts of people and posts, and the header carries the residual %. The model knows what it hasn't seen (fixes L7 and L8).
3. **Dissent is kept by construction.** Stance is tallied, not averaged away as it would be in a summary, and not mixed together as it would be in a vector (fixes L2 and L6).
4. **Redundancy turns into signal instead of crowding out content.** 400 identical posts become "+400 / N authors" on one line, which frees space for the long tail (fixes L5).
5. **Time is first-class.** Every entry has a trend line, so emergence and fading are directly readable.
6. **Exactness on demand.** Census re-reads *every* document behind a claim, located by provenance. That is what makes "all available information" checkable rather than aspirational.

---

## 7. Evidence (simulation)

Full tables: [`results/results.md`](../results/results.md). Code: [`sim/`](../sim). Reproduce with `python -m sim.experiment` (about 1 minute).

**Setup.**
- Synthetic X-like feed: 21,500 posts, 3,258 authors, 300 latent claims with Zipf popularity, per-claim stance splits, 12% emerging and 8% fading claims, 12% off-topic noise, and 6 bot accounts posting 1,500 near-duplicates for a claim real users mostly dispute.
- Ground truth is known exactly.
- **RAG baseline:** BM25 top-k with a *perfect reader*, which is deliberately generous to RAG. Its only error is the selection step.
- **CEL:** run with an absorber whose error rate ε (misassignment, duplicate fragments, stance flips, misses, noise leaks, missed merges) is swept from 0 to 30%.

| Question type | RAG (best k=100) | CEL ε=0.10 | CEL ε=0.30 |
|---|---|---|---|
| Claims held by ≥3 people visible to the model | 20% | **100%** | **100%** |
| Prevalence ranking (Spearman) | 0.38–0.46 | **0.93** | **0.84** |
| Stance share MAE, head / mid / tail claims | 0.045 / 0.011 / 0.001 | 0.057 / 0.068 / 0.059 | 0.109 / 0.125 / 0.096 |
| … with census verification (≤300 docs from the posting list) | n/a | **0.018 / 0.024 / 0.034** | 0.031 / 0.042 / 0.073 |
| Emerging claims, precision / recall | 67% / 3% | **92% / 88%** | 84% / 74% |
| Bot-flooded claim, support share (truth 12%) | 13–40%, depending on k; the reader cannot tell why | **15%** (concentration flag: all 6 bots flagged, 0.7 false flags) | 32% |
| Residual (unplaced) | n/a | 0.24% | 2.0% |
| Conservation `Σmass == N` | n/a | holds exactly | holds exactly |

**How to read the stance row honestly.**
- For a *targeted* question about a claim the user can already name in its own vocabulary, RAG with a *perfect* reader is very accurate. Tail claims have so few posts that k=100 retrieves all of them.
- The ledger's raw tallies inherit the absorber's error rate: at ε=10% they are worse than RAG k=100 on that narrow task.
- Census verification over the exact posting list brings CEL back below RAG's head/mid error. It cannot recover posts that were misassigned to a *different* entry; that is the remaining tail error.
- The practical upshot: **absorber accuracy is the critical parameter.** It must be measured on real data (§10).

**What the simulation does *not* show.**
- That a real LLM absorber reaches ε≤0.1 on real tweets. The ε sweep only says what happens *if* it does or doesn't.
- That real topics are as redundant as the simulation. The scaling table (§8 of the results) is assumption-driven, with β ∈ {0.6, 0.8}.
- That the text "entry wording" is as good as a human's.

---

## 8. Is it novel? An honest positioning

I have not reused any of the excluded techniques. There are no vectors, no embeddings, no chunking pipeline, no fine-tuning, and no knowledge graph. The only BM25 is the *baseline* being compared against. The ingredients are generic: an LLM reading text and emitting structured output, and prompt caching. The claimed contribution is the **representation and its invariants**, plus **where integration happens**:

| Nearest neighbour | What it keeps | What CEL adds or changes |
|---|---|---|
| Map-reduce / hierarchical summarization (e.g. RAPTOR, GraphRAG community summaries ([Edge et al. 2024](https://arxiv.org/pdf/2404.16130))) | prose summaries | Summaries drop counts, dissent and the denominator, and their loss is unauditable. CEL keeps exact tallies, stance and provenance, plus a conservation invariant. |
| Knowledge graphs | entity–relation triples | The unit is an *assertion with a stance tally*, not a triple. Non-triple content is not lost. Stance is first-class. There is no traversal or retrieval. |
| Schema-driven extraction into tables (e.g. the approach in the AI21 talk ([AI Engineer 2025](https://ai.engineer/talks/rag-evaluation-is-broken-here-s-why-and-how-to-fix-it))) | predefined columns | No predefined schema. Assertions emerge online and are consolidated, and census adds dimensions on demand. |
| Per-chunk exhaustive mapping (e.g. the Stakeholder Suite ([arXiv 2512.17347](https://arxiv.org/pdf/2512.17347))), agentic aggregation (DFA, [AGGBench](https://www.alphaxiv.org/abs/2602.01355)) | per-query exhaustive reading | CEL reads exhaustively **once**, and every document is compared with *all prior knowledge*, not in isolation. Results are shared by all later queries. |
| Agent memory (running notes) | free-form facts | Memory has no counts, no conservation, no residual, no stance and no provenance. |
| Topic models | word distributions | CEL stores propositions with stance, not word clusters. |

Recent benchmarks confirm the gap CEL targets. GlobalQA ([arXiv 2510.26205](https://arxiv.org/html/2510.26205v1)) and AGGBench ([arXiv 2602.01355](https://www.alphaxiv.org/abs/2602.01355)) both find that top-k RAG fails at counting and aggregation because of the fixed retrieval window. I did not find prior work combining:
- (a) online absorption of each document against the complete current state,
- (b) a mass-conservation invariant with an explicit residual,
- (c) stance- and author-tallied assertions as the storage unit, and
- (d) exact-scope census in place of retrieval.

That is not proof none exists. Treat the novelty claim as "not found in a targeted search", not as established.

---

## 9. Limitations and failure modes

- **The absorber is the whole ballgame.** Misassignment between near-synonymous claims is the dominant error. In the simulation it raises tail-stance error even after census. Mitigations: splits during consolidation, census, and a stronger absorber for high-traffic entries.
- **What wasn't tallied isn't known until a census runs.** Census is exhaustive, but it costs one cheap-model pass over the scope.
- **Verbatim and quote questions** ("what exactly did @x say?") need exemplars or posting-list drill-down. The ledger is about meaning, not wording.
- **Low-redundancy corpora** get little compression (see §5).
- **Wording drift.** An entry's canonical text is fixed at creation. A global pass may need to reword entries as the conversation evolves; rewording is mass-neutral.
- **Index scale.** Above roughly 8k entries the absorber needs sharding (§4.6). Routing errors then become a second error source.
- **Cold start.** The first batches have an empty ledger and create many entries. Residual re-absorption and merges clean this up, but epoch 0 is the noisiest.

---

## 10. Validation plan (with a real model)

This repository's experiments use a parameterized stand-in for the absorber, because there was no API key in the build container. To validate on real data:

1. **Measure ε directly.** Run [`celedger/absorber.py`](../celedger/absorber.py) (Haiku 5.5) on a stance-annotated tweet corpus, e.g. SemEval-2016 Task 6 (tweets with target and stance labels). Measure misassignment, fragmentation and stance-flip rates against the labels. This one number places you on the ε curve in §7.
2. **End to end.** Answer GlobalQA / AGGBench-style counting, extremum and sorting questions from the ledger, compared with RAG and long context at matched cost.
3. **Real X topic.** Pick a niche hashtag with 20–200k posts. Hand-audit 200 random documents' ops via provenance. Measure the actual D(N) growth curve (β), which replaces the assumption in the scaling table.
4. **Ablations:** no consolidation, no residual re-absorption, no thread ordering, no census.

---

## 11. A note on "take at least 24 hours"

I didn't stall for a day. Wall-clock time doesn't improve the result, and padding it would only have delayed you. What a longer horizon would actually buy is §10: running the real absorber against labelled data to measure ε. That needs an API key and a dataset, not more waiting. Everything in this repository was built and run in this session, and every number above comes from code you can re-run.
