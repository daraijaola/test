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
    kind: str                 # "assign" | "new" | "refine" | "residual" | "noise"
    entry_id: int | None = None
    stance: str = MENTION
    text: str | None = None   # for "new"/"refine": canonical wording of the assertion
    label: object = None      # simulation only: hidden ground-truth tag, never read by logic


@dataclass
class Entry:
    eid: int
    text: str
    epoch_created: int
    mass: dict = field(default_factory=lambda: {s: 0.0 for s in STANCES})
    author_stance: dict = field(default_factory=dict)  # author -> latest stance
    author_docs: dict = field(default_factory=dict)    # author -> doc mass (concentration signal)
    author_t: dict = field(default_factory=dict)       # author -> time of the stance kept
    theme: object = None                               # section for sharding / multi-resolution view
    parent: int | None = None                          # set by "refine": a more specific child of parent
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

    def new_entry(self, text: str, label=None, theme=None, parent: int | None = None) -> Entry:
        e = Entry(eid=self._next, text=text, epoch_created=self.epoch, label=label, theme=theme, parent=parent)
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
                if op.kind in ("new", "refine"):
                    par = None
                    if op.kind == "refine" and op.entry_id is not None and self.resolve(op.entry_id) in self.entries:
                        par = self.resolve(op.entry_id)
                    e = self.new_entry(op.text or "(unnamed)", op.label, parent=par)
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
        self._set_author(e, doc.author, stance, doc.t)
        e.author_docs[doc.author] = e.author_docs.get(doc.author, 0.0) + w
        e.reach += w * doc.reach
        e.time_bins[min(N_TIME_BINS - 1, int(doc.t * N_TIME_BINS))] += w
        e.exemplar.setdefault(stance, doc.doc_id)
        e.first_t = min(e.first_t, doc.t)

    @staticmethod
    def _set_author(e: Entry, a: str, stance: str, t: float) -> None:
        """Keep each author's latest non-mention stance (mention only if nothing else)."""
        cur = e.author_stance.get(a)
        if stance != MENTION:
            if cur is None or cur == MENTION or t >= e.author_t[a]:
                e.author_stance[a], e.author_t[a] = stance, t
        elif cur is None:
            e.author_stance[a], e.author_t[a] = MENTION, t

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
                if op.kind in ("new", "refine"):
                    par = self.resolve(op.entry_id) if op.kind == "refine" and op.entry_id is not None else None
                    e = self.new_entry(op.text or "(unnamed)", op.label,
                                       parent=par if par in self.entries else None)
                else:
                    e = self.entries[self.resolve(op.entry_id)]
                self._credit(e, doc, op.stance, w)
                keep.append((e.eid, op.stance, w))
        self._set_rows(doc_id, keep)

    # ----------------------------------------------------------- consolidation
    def merge(self, keep: int, gone: int) -> None:
        """Paraphrase merge. Mass-conserving; provenance rewritten exactly."""
        keep, gone = self.resolve(keep), self.resolve(gone)
        if keep == gone:
            return
        k, g = self.entries[keep], self.entries[gone]
        for c in self.entries.values():
            if c.parent == gone:
                c.parent = keep if c.eid != keep else None
        if k.parent == gone:
            k.parent = g.parent if g.parent != keep else None
        self.alias[gone] = keep
        del self.entries[gone]
        for d in list(self.post.get(gone, ())):
            self._set_rows(d, [(keep if eid == gone else eid, s, w) for eid, s, w in self.log[d]])
        self.post.pop(gone, None)
        # exact incremental combination (equivalent to recompute(keep), without re-reading postings)
        for st in STANCES:
            k.mass[st] += g.mass[st]
        for a, st in g.author_stance.items():
            self._set_author(k, a, st, g.author_t[a])
        for a, m in g.author_docs.items():
            k.author_docs[a] = k.author_docs.get(a, 0.0) + m
        k.reach += g.reach
        k.time_bins = [x + y for x, y in zip(k.time_bins, g.time_bins)]
        for st, d in g.exemplar.items():
            k.exemplar.setdefault(st, d)
        k.first_t = min(k.first_t, g.first_t)

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

    def replace_ops(self, d: int, ops: list[tuple[int | None, str]]) -> set[int]:
        """Replace document d's ops with `ops` = [(entry_id | None, stance | 'noise' | 'residual')],
        re-splitting its unit of mass equally (conservation holds). Returns the entries whose
        tallies must be rebuilt; call recompute() on them once after a bulk update."""
        old = {e for e, _, _ in self.log[d] if e is not None}
        w = 1.0 / max(1, len(ops))
        rows = [(e, s, w) for e, s in ops] or [(None, "residual", 1.0)]
        for e, s, ww in self.log[d]:
            if e is None and s == "noise":
                self.noise_mass -= ww
            elif e is None and s == "residual":
                self.residual_mass -= ww
        for e, s, ww in rows:
            if e is None and s == "noise":
                self.noise_mass += ww
            elif e is None and s == "residual":
                self.residual_mass += ww
        if any(e is None and s == "residual" for e, s, _ in rows):
            self.residual.add(d)
        else:
            self.residual.discard(d)
        self._set_rows(d, rows)
        return old | {e for e, _, _ in rows if e is not None}

    def recompute(self, eid: int) -> None:
        old = self.entries[eid]
        e = Entry(eid=eid, text=old.text, epoch_created=old.epoch_created, label=old.label, theme=old.theme,
                  parent=old.parent)
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

    @staticmethod
    def est_tokens(text: str) -> int:
        """Rough token estimate used for all budgets: UTF-8 bytes / 4."""
        return len(text.encode("utf-8")) // 4

    def camp(self, e: Entry) -> tuple[int, int] | None:
        """Cross-tab with the anchor: how many of this entry's authors agree / disagree with
        the anchor statement (their position on the subject as a whole)."""
        if e.eid == 0 or 0 not in self.entries or not self.entries[0].text.startswith("ANCHOR"):
            return None
        an = self.entries[0].author_stance
        pro = sum(1 for a in e.author_stance if an.get(a) == SUPPORT)
        con = sum(1 for a in e.author_stance if an.get(a) == DISPUTE)
        return pro, con

    def children(self) -> dict[int, list[int]]:
        ch: dict[int, list[int]] = {}
        for e in self.entries.values():
            if e.parent is not None and self.resolve(e.parent) in self.entries and self.resolve(e.parent) != e.eid:
                ch.setdefault(self.resolve(e.parent), []).append(e.eid)
        return ch

    def family_authors(self, eid: int, ch: dict | None = None) -> int:
        """Distinct authors across an entry and all its refinements (descendants)."""
        ch = self.children() if ch is None else ch
        seen, stack, authors = set(), [eid], set()
        while stack:
            x = stack.pop()
            if x in seen or x not in self.entries:
                continue
            seen.add(x)
            authors |= self.entries[x].author_stance.keys()
            stack += ch.get(x, [])
        return len(authors)

    def _entry_line(self, e: Entry, spark: bool = True, ch: dict | None = None) -> str:
        a = e.authors_by_stance()
        c = self.camp(e)
        camp = f" | camp: anchor▲{c[0]} anchor▼{c[1]}" if c and (c[0] or c[1]) else ""
        conc = e.concentration()
        flag = f" ⚠ top-5 accounts wrote {100 * conc:.0f}% of docs" if conc > 0.5 and e.total >= 50 else ""
        tail = ""
        if spark:
            peak = max(e.time_bins) or 1
            tail = " | " + "".join(SPARK[round(8 * b / peak)] for b in e.time_bins) + f" | t={e.first_t:.2f}"
        par = self.resolve(e.parent) if e.parent is not None else None
        ref = f" ↳e{par}" if par is not None and par in self.entries else ""
        fam = ""
        if ch is not None and ch.get(e.eid):
            fam = f" | family incl. {len(ch[e.eid])} refinements: {self.family_authors(e.eid, ch)} authors"
        return (f"e{e.eid}{ref} | {e.text} | {len(e.author_stance)} authors ▲{a[SUPPORT]} ▼{a[DISPUTE]} "
                f"·{a[MENTION]} | {e.total:.0f} docs{fam}{flag}{camp}{tail}")

    ANCHOR_NOTE = ("e0 is the ANCHOR: it tallies every author whose position on the anchor statement is "
                   "discernible (▲ agrees, ▼ disagrees). Authors not counted on e0 expressed no discernible position. "
                   "'camp: anchor▲x anchor▼y' on a line = how many of that line's authors agree / disagree with the anchor.")

    def render(self, budget_tokens: int = 32000) -> tuple[str, list[int]]:
        """The full corpus as the reading model sees it.  Entries are listed by number of
        distinct authors until the budget is used; the rest is folded into one line that
        still reports its exact mass, so the denominator is never hidden."""
        n = len(self.docs)
        es = sorted(self.entries.values(), key=lambda e: -len(e.author_stance))
        n_authors = len({m.author for m in self.docs.values()})
        header = [
            f"CORPUS: {n} documents, {n_authors} distinct authors.",
            f"Placed in entries: {100 * sum(e.total for e in es) / max(n, 1):.1f}%  "
            f"residual (unplaced): {100 * self.residual_mass / max(n, 1):.1f}%  "
            f"noise/off-topic: {100 * self.noise_mass / max(n, 1):.1f}%",
            "Each line: id | assertion | authors ▲support ▼dispute ·mention | docs | trend (old→new) | first seen. "
            "'e12 ↳e4' = e12 is a more specific refinement of e4.",
        ]
        if 0 in self.entries and self.entries[0].text.startswith("ANCHOR"):
            header.append(self.ANCHOR_NOTE)
        used = self.est_tokens("\n".join(header)) + 40       # reserve room for the fold line
        shown, lines = [], []
        ch = self.children()
        for e in es:
            ln = self._entry_line(e, ch=ch)
            t = self.est_tokens(ln) + 1
            if used + t > budget_tokens:
                break
            lines.append(ln); shown.append(e.eid); used += t
        rest = es[len(shown):]
        if rest:
            lines.append(f"(+{len(rest)} smaller entries folded: {sum(e.total for e in rest):.0f} docs, "
                         f"{100 * sum(e.total for e in rest) / max(n, 1):.1f}% of corpus; expand by id range)")
        return "\n".join(header + lines), shown

    def render_multires(self, budget_tokens: int = 32000, quotes: dict | None = None,
                        quote_chars: int = 140) -> tuple[str, list[int]]:
        """Theme-grouped view for ledgers larger than the reading budget.  Every theme is
        always shown with its exact mass.  Entry lines are chosen by global rank (distinct
        authors) after a floor of the top two entries of every theme, until the measured
        budget is used; the rest of each theme folds into one line with its exact count."""
        n = max(1, len(self.docs))
        groups: dict = {}
        for e in self.entries.values():
            groups.setdefault(e.theme, []).append(e)
        for es in groups.values():
            es.sort(key=lambda e: -len(e.author_stance))
        order = sorted(groups, key=lambda th: -sum(e.total for e in groups[th]))
        head = [f"CORPUS: {len(self.docs)} documents, {len({m.author for m in self.docs.values()})} distinct authors, "
                f"{len(self.entries)} distinct assertions in {len(groups)} themes.",
                f"residual (unplaced): {100 * self.residual_mass / n:.1f}%  noise: {100 * self.noise_mass / n:.1f}%"]
        if 0 in self.entries and self.entries[0].text.startswith("ANCHOR"):
            head.append(self.ANCHOR_NOTE)
        used = self.est_tokens("\n".join(head)) + 45 * len(groups)   # theme header + fold line per theme
        cand = [e for th in order for e in groups[th][:2]]
        cand += sorted((e for es in groups.values() for e in es[2:]), key=lambda e: -len(e.author_stance))
        chosen, lines_of = set(), {}
        ch = self.children()
        for e in cand:
            ln = self._entry_line(e, spark=False, ch=ch)
            if quotes is not None:                 # one verbatim exemplar, found by provenance
                d = e.exemplar.get(SUPPORT, next(iter(e.exemplar.values()), None))
                if d is not None and d in quotes:
                    q = " ".join(quotes[d].split())[:quote_chars]
                    ln += f"\n    e.g. \"{q}\""
            t = self.est_tokens(ln) + 1
            if used + t > budget_tokens:
                break
            chosen.add(e.eid); lines_of[e.eid] = ln; used += t
        lines, shown = list(head), []
        for th in order:
            es = groups[th]
            m = sum(e.total for e in es)
            lines.append(f"## theme {th}: {len(es)} assertions, {m:.0f} docs ({100 * m / n:.1f}%)")
            for e in es:
                if e.eid in chosen:
                    lines.append(lines_of[e.eid]); shown.append(e.eid)
            rest = [e for e in es if e.eid not in chosen]
            if rest:
                lines.append(f"   (+{len(rest)} more in this theme: {sum(e.total for e in rest):.0f} docs; "
                             f"largest folded has {len(rest[0].author_stance)} authors)")
        return "\n".join(lines), shown

    # ------------------------------------------------------------------ census
    def census(self, predicate: Callable[[int], bool], scope: Iterable[int] | None = None) -> dict:
        """Exhaustive, exact count of a new property over every document in scope.
        Scope is an exact posting list from provenance (not a similarity search).
        In production `predicate` is a cheap-model yes/no call per document."""
        docs = list(self.docs) if scope is None else sorted({d for eid in scope for d in self.postings(self.resolve(eid))})
        hits = [d for d in docs if predicate(d)]
        return {"scope_docs": len(docs), "hits": len(hits),
                "hit_authors": len({self.docs[d].author for d in hits}), "doc_ids": hits}
