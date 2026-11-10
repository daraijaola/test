import random

import pytest

from celedger.ledger import ConservationError, DocMeta, Ledger, Op


def doc(i, a="u1", t=0.5):
    return DocMeta(i, a, t, 1.0)


def test_mass_conserved_through_absorb_merge_split_reabsorb():
    L = Ledger()
    rng = random.Random(0)
    L.absorb(doc(0), [Op("new", text="A"), Op("new", text="B")])
    L.absorb(doc(1), [Op("new", text="A'")])
    for i in range(2, 400):
        kind = rng.choice(["assign", "assign", "noise", "residual", "new"])
        ops = [Op(kind, rng.choice(list(L.entries)) if kind == "assign" else None,
                  rng.choice(["support", "dispute", "mention"]), text=f"x{i}")]
        if rng.random() < 0.3:
            ops.append(Op("assign", rng.choice(list(L.entries)), "support"))
        L.absorb(doc(i, f"u{rng.randrange(50)}", rng.random()), ops)
        L.check_conservation()
    L.merge(0, 2)
    L.check_conservation()
    big = max(L.entries.values(), key=lambda e: e.total).eid
    L.split(big, lambda d: "even" if d % 2 == 0 else "odd", {"even": "E", "odd": "O"})
    L.check_conservation()
    for d in sorted(L.residual):
        L.reabsorb_residual(d, [Op("assign", next(iter(L.entries)), "mention")])
    assert L.residual_mass == pytest.approx(0)
    assert L.check_conservation() == pytest.approx(400)


def test_empty_ops_become_residual_not_silence():
    L = Ledger()
    L.absorb(doc(0), [])
    assert L.residual_mass == 1.0 and 0 in L.residual


def test_merge_rewrites_provenance_and_tallies():
    L = Ledger()
    L.absorb(doc(0, "a"), [Op("new", text="X")])
    L.absorb(doc(1, "b"), [Op("new", text="X again", stance="dispute")])
    L.merge(0, 1)
    e = L.entries[0]
    assert e.total == 2 and len(e.author_stance) == 2
    assert L.postings(0) == [0, 1] and L.resolve(1) == 0
    assert 1 not in L.entries


def test_double_absorb_rejected_and_tamper_detected():
    L = Ledger()
    L.absorb(doc(0), [Op("new", text="X")])
    with pytest.raises(ValueError):
        L.absorb(doc(0), [Op("noise")])
    L.noise_mass += 0.5
    with pytest.raises(ConservationError):
        L.check_conservation()


def test_render_never_hides_the_denominator():
    L = Ledger()
    for i in range(200):
        L.absorb(doc(i, f"u{i}"), [Op("new", text=f"claim {i}")])
    text, shown = L.render(budget_tokens=600)
    assert len(shown) < 200
    assert "folded" in text and "200 documents" in text


def test_census_scope_is_exact_posting_list():
    L = Ledger()
    L.absorb(doc(0, "a"), [Op("new", text="X")])
    L.absorb(doc(1, "b"), [Op("assign", 0, "support")])
    L.absorb(doc(2, "c"), [Op("new", text="Y")])
    r = L.census(lambda d: d != 1, scope=[0])
    assert r["scope_docs"] == 2 and r["hits"] == 1


def test_incremental_merge_equals_full_recompute():
    rng = random.Random(3)
    L = Ledger()
    for i in range(300):
        ops = [Op("new", text=f"c{i}")] if i < 6 else [
            Op("assign", rng.choice(list(L.entries)), rng.choice(["support", "dispute", "mention"]))]
        L.absorb(doc(i, f"u{rng.randrange(40)}", rng.random()), ops)
    L.merge(0, 1)
    L.merge(2, 3)
    L.merge(0, 2)
    snap = {a: (e.total, dict(e.author_stance), dict(e.author_docs), list(e.time_bins), e.first_t)
            for a, e in L.entries.items()}
    for eid in list(L.entries):
        L.recompute(eid)
    for eid, e in L.entries.items():
        tot, ast, adoc, bins, ft = snap[eid]
        assert e.total == pytest.approx(tot)
        assert e.author_stance == ast
        assert e.author_docs == pytest.approx(adoc)
        assert e.time_bins == pytest.approx(bins)
        assert e.first_t == ft


def test_camp_crosstab_with_anchor():
    L = Ledger()
    L.new_entry("ANCHOR: X is good")
    L.absorb(doc(0, "a"), [Op("assign", 0, "support"), Op("new", text="claim P")])
    L.absorb(doc(1, "b"), [Op("assign", 0, "dispute"), Op("assign", 1, "support")])
    L.absorb(doc(2, "c"), [Op("assign", 1, "dispute")])
    assert L.camp(L.entries[1]) == (1, 1)
    assert "camp: anchor▲1 anchor▼1" in L.render(4000)[0]


def test_replace_ops_conserves_mass_and_rebuilds_tallies():
    L = Ledger()
    L.new_entry("ANCHOR: X is good")
    L.absorb(doc(0, "a"), [Op("new", text="P")])
    L.absorb(doc(1, "b"), [Op("noise")])
    L.absorb(doc(2, "c"), [Op("assign", 1, "support"), Op("assign", 0, "dispute")])
    touched = L.replace_ops(0, [(1, "support"), (0, "support")])
    touched |= L.replace_ops(1, [(0, "dispute")])
    touched |= L.replace_ops(2, [(1, "support")])
    for e in touched:
        L.recompute(e)
    assert L.check_conservation() == pytest.approx(3)
    assert L.noise_mass == pytest.approx(0)
    assert L.entries[0].authors_by_stance()["support"] == 1 and L.entries[0].authors_by_stance()["dispute"] == 1
    assert L.entries[1].total == pytest.approx(1.5)


def test_refine_creates_child_and_family_rollup_survives_merge():
    L = Ledger()
    L.absorb(doc(0, "a"), [Op("new", text="seed oils harm health")])
    L.absorb(doc(1, "b"), [Op("refine", 0, "support", text="seed oils cause acne")])
    L.absorb(doc(2, "c"), [Op("refine", 0, "support", text="seed oils give you acne")])
    assert L.entries[1].parent == 0 and L.entries[2].parent == 0
    assert L.family_authors(0) == 3
    L.merge(1, 2)
    assert L.family_authors(0) == 3 and L.children() == {0: [1]}
    assert "e1 ↳e0" in L.render(4000)[0]
    L.check_conservation()


def test_family_union_counts_distinct_authors_once():
    L = Ledger()
    L.absorb(doc(0, "a"), [Op("new", stance="support", text="X is bad for health")])
    L.absorb(doc(1, "a"), [Op("new", stance="support", text="X causes inflammation")])
    L.absorb(doc(2, "b"), [Op("assign", 1, "support")])
    L.absorb(doc(3, "c"), [Op("assign", 0, "dispute")])
    for e in L.entries.values():
        e.family = 7
    line = L.family_lines({7: "X is harmful"})[0]
    assert "3 distinct authors across 2 entries" in line and "▲2 ▼1" in line and "camp" not in line
