"""The Conserved Evidence Ledger (CEL).

A CEL is the *whole* body of a corpus, integrated once, at a size that scales
with the number of distinct things said rather than the number of documents.

Unit of storage: an Entry = one assertion (something a person could agree or
disagree with) or one observation (an event, artifact, question).  Each entry
carries a tally of every document that touched it: stance masses, the set of
distinct authors and their latest stance, reach, a time histogram, and up to one
exemplar per stance.

The central invariant (conservation of evidence):

    sum(entry.mass) + residual.mass + noise.mass == number of documents absorbed

Every document carries exactly 1 unit of mass, split across the ops it produced.
Nothing is ever silently dropped: what the absorber could not place goes to the
*residual*, whose size the reading model is always shown.  Merges and splits move
mass; they never create or destroy it.  A provenance log (doc -> ops) makes
every tally exactly recomputable and every entry exactly enumerable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

SUPPORT, DISPUTE, MENTION = "support", "dispute", "mention"
STANCES = (SUPPORT, DISPUTE, MENTION)
N_TIME_BINS = 12
SPARK = " ▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class DocMeta:
    doc_id: int
    author: str
    t: float          # normalised time in [0, 1]
    reach: float      # e.g. log(1 + likes + reposts)


@dataclass(frozen=True)
class Op:
    """One absorber decision about one document."""
    kind: str                 # "assign" | "new" | "residual" | "noise"
    entry_id: int | None = None
    stance: str = MENTION
    text: str | None = None   # for "new": canonical wording of the assertion
    label: object = None      # simulation only: hidden ground-truth tag, never read by logic


@dataclass
class Entry:
    eid: int
    text: str
    epoch_created: int
    mass: dict = field(default_factory=lambda: {s: 0.0 for s in STANCES})
    author_stance: dict = field(default_factory=dict)  # author -> latest stance
    author_docs: dict = field(default_factory=dict)    # author -> doc mass (concentration signal)
    reach: float = 0.0
    time_bins: list = field(default_factory=lambda: [0.0] * N_TIME_BINS)
    exemplar: dict = field(default_factory=dict)       # stance -> doc_id
    first_t: float = 1.0
    label: object = None                               # simulation only

    @property
    def total(self) -> float:
        return sum(self.mass.values())

    def concentration(self, top: int = 5) -> float:
        """Share of this entry's documents produced by its `top` most active accounts."""
        v = sorted(self.author_docs.values(), reverse=True)
        return sum(v[:top]) / self.total if self.total else 0.0

    def authors_by_stance(self, exclude: set | None = None) -> dict:
        out = {s: 0 for s in STANCES}
        for a, st in self.author_stance.items():
            if not exclude or a not in exclude:
                out[st] += 1
        return out


class ConservationError(AssertionError):
    pass


class Ledger:
    def __init__(self) -> None:
        self.entries: dict[int, Entry] = {}
        self.docs: dict[int, DocMeta] = {}
        self.log: dict[int, list[tuple[int | None, str, float]]] = {}  # doc -> [(eid|None, stance|bucket, w)]
        self.residual: set[int] = set()   # doc ids (wholly or partly) unplaced
        self.residual_mass = 0.0
        self.noise_mass = 0.0
        self.alias: dict[int, int] = {}   # merged-away id -> surviving id
        self.post: dict[int, set[int]] = {}  # eid -> doc ids (exact posting list)
        self.epoch = 0
        self._next = 0

    # ------------------------------------------------------------------ ingest
    def resolve(self, eid: int) -> int:
        while eid in self.alias:
            eid = self.alias[eid]
        return eid

    def new_entry(self, text: str, label=None) -> Entry:
        e = Entry(eid=self._next, text=text, epoch_created=self.epoch, label=label)
        self.entries[e.eid] = e
        self._next += 1
        return e

    def absorb(self, doc: DocMeta, ops: list[Op]) -> list[int]:
        """Apply the absorber's ops for one document. Returns ids of new entries."""
        if doc.doc_id in self.docs:
            raise ValueError(f"doc {doc.doc_id} absorbed twice")
        if not ops:                       # the absorber said nothing: that is residual, not silence
            ops = [Op("residual")]
        self.docs[doc.doc_id] = doc
        w = 1.0 / len(ops)
        created, rows = [], []
        for op in ops:
            if op.kind == "noise":
                self.noise_mass += w
                rows.append((None, "noise", w))
            elif op.kind == "residual":
                self.residual_mass += w
                self.residual.add(doc.doc_id)
                rows.append((None, "residual", w))
            else:
                if op.kind == "new":
                    e = self.new_entry(op.text or "(unnamed)", op.label)
                    created.append(e.eid)
                else:
                    e = self.entries[self.resolve(op.entry_id)]
                self._credit(e, doc, op.stance, w)
                rows.append((e.eid, op.stance, w))
        self._set_rows(doc.doc_id, rows)
        return created

    def _set_rows(self, d: int, rows) -> None:
        for eid, _, _ in self.log.get(d, []):
            if eid is not None and eid in self.post:
                self.post[eid].discard(d)
        self.log[d] = rows
        for eid, _, _ in rows:
            if eid is not None:
                self.post.setdefault(eid, set()).add(d)

    def _credit(self, e: Entry, doc: DocMeta, stance: str, w: float) -> None:
        e.mass[stance] += w
        if stance != MENTION or doc.author not in e.author_stance:
            e.author_stance[doc.author] = stance
        e.author_docs[doc.author] = e.author_docs.get(doc.author, 0.0) + w
        e.reach += w * doc.reach
        e.time_bins[min(N_TIME_BINS - 1, int(doc.t * N_TIME_BINS))] += w
        e.exemplar.setdefault(stance, doc.doc_id)
        e.first_t = min(e.first_t, doc.t)

    def reabsorb_residual(self, doc_id: int, ops: list[Op]) -> None:
        """Replace a document's residual share with new ops (second-chance pass)."""
        rows = self.log[doc_id]
        res_w = sum(w for eid, b, w in rows if b == "residual")
        if res_w == 0 or not ops or all(o.kind == "residual" for o in ops):
            return
        doc = self.docs[doc_id]
        keep = [r for r in rows if r[1] != "residual"]
        self.residual_mass -= res_w
        self.residual.discard(doc_id)
        w = res_w / len(ops)
        for op in ops:
            if op.kind == "noise":
                self.noise_mass += w
                keep.append((None, "noise", w))
            elif op.kind == "residual":
                self.residual_mass += w
                self.residual.add(doc_id)
                keep.append((None, "residual", w))
            else:
                e = self.new_entry(op.text or "(unnamed)", op.label) if op.kind == "new" \
                    else self.entries[self.resolve(op.entry_id)]
                self._credit(e, doc, op.stance, w)
                keep.append((e.eid, op.stance, w))
        self._set_rows(doc_id, keep)

    # ----------------------------------------------------------- consolidation
    def merge(self, keep: int, gone: int) -> None:
        """Paraphrase merge. Mass-conserving; provenance rewritten exactly."""
        keep, gone = self.resolve(keep), self.resolve(gone)
        if keep == gone:
            return
        self.alias[gone] = keep
        del self.entries[gone]
        for d in list(self.post.get(gone, ())):
            self._set_rows(d, [(keep if eid == gone else eid, s, w) for eid, s, w in self.log[d]])
        self.post.pop(gone, None)
        self.recompute(keep)

    def split(self, eid: int, router: Callable[[int], str], texts: dict[str, str]) -> dict[str, int]:
        """Split an overloaded entry. `router(doc_id) -> key` re-routes every doc of
        the entry exactly (the provenance log is the complete posting list)."""
        new_ids = {k: self.new_entry(t).eid for k, t in texts.items()}
        for d in self.postings(eid):
            key = router(d)
            self._set_rows(d, [(new_ids[key] if e == eid else e, s, w) for e, s, w in self.log[d]])
        del self.entries[eid]
        self.post.pop(eid, None)
        for i in new_ids.values():
            self.recompute(i)
        return new_ids

    def recompute(self, eid: int) -> None:
        old = self.entries[eid]
        e = Entry(eid=eid, text=old.text, epoch_created=old.epoch_created, label=old.label)
        for d in sorted(self.postings(eid), key=lambda d: self.docs[d].t):
            for e2, s, w in self.log[d]:
                if e2 == eid:
                    self._credit(e, self.docs[d], s, w)
        self.entries[eid] = e

    def postings(self, eid: int) -> list[int]:
        return sorted(self.post.get(eid, ()))

    # --------------------------------------------------------------- invariant
    def check_conservation(self, tol: float = 1e-6) -> float:
        total = sum(e.total for e in self.entries.values()) + self.residual_mass + self.noise_mass
        if abs(total - len(self.docs)) > tol:
            raise ConservationError(f"mass {total} != docs {len(self.docs)}")
        for d, rows in self.log.items():
            if abs(sum(w for _, _, w in rows) - 1.0) > tol:
                raise ConservationError(f"doc {d} carries mass {sum(w for _, _, w in rows)}")
        return total

    # ----------------------------------------------------------------- reading
    def index_lines(self, since_epoch: int | None = None) -> list[str]:
        """Compact id+wording list the absorber sees (append-only within an epoch,
        so the cached prompt prefix stays valid while new entries are appended)."""
        es = sorted(self.entries.values(), key=lambda e: e.eid)
        if since_epoch is not None:
            es = [e for e in es if e.epoch_created >= since_epoch]
        return [f"e{e.eid}: {e.text}" for e in es]

    def render(self, budget_tokens: int = 32000, line_tokens: int = 30) -> tuple[str, list[int]]:
        """The full corpus as the reading model sees it.  Entries are listed by
        mass; whatever does not fit the budget is folded into a single line that
        still reports its exact mass, so the denominator is never hidden."""
        n = len(self.docs)
        es = sorted(self.entries.values(), key=lambda e: -len(e.author_stance))
        n_authors = len({m.author for m in self.docs.values()})
        header = [
            f"CORPUS: {n} documents, {n_authors} distinct authors.",
            f"Placed in entries: {100 * sum(e.total for e in es) / max(n, 1):.1f}%  "
            f"residual (unplaced): {100 * self.residual_mass / max(n, 1):.1f}%  "
            f"noise/off-topic: {100 * self.noise_mass / max(n, 1):.1f}%",
            "Each line: id | assertion | authors ▲support ▼dispute ·mention | docs | trend (old→new) | first seen",
        ]
        max_lines = max(0, (budget_tokens - 120) // line_tokens)
        shown, lines = [], []
        for e in es[:max_lines]:
            a = e.authors_by_stance()
            peak = max(e.time_bins) or 1
            spark = "".join(SPARK[round(8 * b / peak)] for b in e.time_bins)
            conc = e.concentration()
            flag = f" ⚠ top-5 accounts wrote {100 * conc:.0f}% of docs" if conc > 0.5 and e.total >= 50 else ""
            lines.append(f"e{e.eid} | {e.text} | {len(e.author_stance)} authors "
                         f"▲{a[SUPPORT]} ▼{a[DISPUTE]} ·{a[MENTION]} | {e.total:.0f} docs{flag} | {spark} | t={e.first_t:.2f}")
            shown.append(e.eid)
        rest = es[max_lines:]
        if rest:
            lines.append(f"(+{len(rest)} smaller entries folded: {sum(e.total for e in rest):.0f} docs, "
                         f"{100 * sum(e.total for e in rest) / max(n, 1):.1f}% of corpus; expand by id range)")
        return "\n".join(header + lines), shown

    # ------------------------------------------------------------------ census
    def census(self, predicate: Callable[[int], bool], scope: Iterable[int] | None = None) -> dict:
        """Exhaustive, exact count of a new property over every document in scope.
        Scope is an exact posting list from provenance (not a similarity search).
        In production `predicate` is a cheap-model yes/no call per document."""
        docs = list(self.docs) if scope is None else sorted({d for eid in scope for d in self.postings(self.resolve(eid))})
        hits = [d for d in docs if predicate(d)]
        return {"scope_docs": len(docs), "hits": len(hits),
                "hit_authors": len({self.docs[d].author for d in hits}), "doc_ids": hits}
