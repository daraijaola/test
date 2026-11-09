"""Token and dollar cost model.

Prices are Anthropic first-party list prices per million tokens as of 2026-11
(input / cache-read / output).  Haiku 5.5 cache-read is assumed at 0.1x input;
cache writes at 1.25x input (5-minute TTL).  Embedding price for the RAG
baseline is an assumption (Anthropic does not sell embeddings) - set to a typical
third-party rate; it is a negligible term either way.
"""
from __future__ import annotations

from dataclasses import dataclass

PRICE = {  # $/MTok: (input, cache_read, output)
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 0.10, 10.00),
    "claude-opus-5-5": (4.00, 0.20, 20.00),
}
EMBED_PER_MTOK = 0.02
WRITE_MULT = 1.25


@dataclass
class Tok:
    post: int = 45          # average tweet incl. author/time metadata
    index_line: int = 18    # "e123: canonical assertion" in the absorber's index
    render_line: int = 30   # full tallied line in the reader's view
    op_out: int = 15        # absorber output per document
    instructions: int = 450
    question: int = 120
    answer: int = 600


def usd(model: str, inp=0, cache_read=0, cache_write=0, out=0) -> float:
    i, r, o = PRICE[model]
    return (inp * i + cache_read * r + cache_write * i * WRITE_MULT + out * o) / 1e6


PREFIX_CAP = 150_000   # beyond this the index is sharded into sections (see DESIGN.md §4.6)


def absorber_prefix(n_entries: int, T: Tok = Tok()) -> int:
    full = T.instructions + n_entries * T.index_line
    if full <= PREFIX_CAP:
        return full
    # sharded: section table (one line per ~40 entries) + one routed shard at the cap
    return PREFIX_CAP + (n_entries // 40) * 12


def ledger_ingest_cost(n_docs: int, frozen: list[int], fresh: list[int], epochs: int, final_entries: int,
                       batch: int = 100, T: Tok = Tok(), absorber="claude-haiku-5-5",
                       consolidator="claude-sonnet-5-5", global_every: int = 10, discount: float = 1.0) -> dict:
    """discount=0.5 models the Message Batches API (ingest is not latency-sensitive)."""
    cost, tok = 0.0, 0
    last_frozen = -1
    for fz, fr in zip(frozen, fresh):
        prefix = absorber_prefix(fz, T)
        write = fz != last_frozen          # first batch after an epoch re-freezes the prefix
        last_frozen = fz
        fresh_in = fr * T.index_line + batch * (T.post + 8)
        out = batch * T.op_out
        cost += usd(absorber, inp=fresh_in, cache_read=0 if write else prefix,
                    cache_write=prefix if write else 0, out=out)
        tok += prefix + fresh_in + out
    # local consolidation each epoch: same model + same cached prefix, so the frozen
    # index is a cache read; only the entries created this epoch are fresh input
    per_epoch_new = final_entries / max(1, epochs + 1)
    pre = absorber_prefix(final_entries // 2, T)
    for _ in range(epochs + 1):
        cost += usd(absorber, cache_read=pre, inp=per_epoch_new * T.index_line + 300, out=1500)
        tok += pre + per_epoch_new * T.index_line + 1800
    # occasional global pass by the stronger model over the whole index
    for _ in range(epochs // global_every + 1):
        cost += usd(consolidator, inp=min(final_entries * T.index_line, 900_000) + 300, out=4000)
        tok += min(final_entries * T.index_line, 900_000) + 4300
    return {"usd": cost * discount, "tokens": tok}


def ledger_query_cost(render_tokens: int, n_queries: int, T: Tok = Tok(), reader="claude-opus-5-5") -> float:
    first = usd(reader, cache_write=render_tokens, inp=T.question, out=T.answer)
    rest = usd(reader, cache_read=render_tokens, inp=T.question, out=T.answer)
    return first + rest * max(0, n_queries - 1)


def rag_cost(n_docs: int, k: int, n_queries: int, T: Tok = Tok(), reader="claude-opus-5-5") -> dict:
    ingest = n_docs * T.post * EMBED_PER_MTOK / 1e6
    per_q = usd(reader, inp=k * T.post + T.question + 300, out=T.answer)
    return {"ingest": ingest, "per_query": per_q, "total": ingest + per_q * n_queries}


def long_context_cost(n_docs: int, n_queries: int, T: Tok = Tok(), reader="claude-opus-5-5",
                      window: int = 1_000_000) -> dict | None:
    ctx = n_docs * T.post
    if ctx + T.question > window:
        return None
    first = usd(reader, cache_write=ctx, inp=T.question, out=T.answer)
    rest = usd(reader, cache_read=ctx, inp=T.question, out=T.answer)
    return {"ctx_tokens": ctx, "total": first + rest * max(0, n_queries - 1)}
