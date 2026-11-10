"""Pairing and scoring a page (spec 015 tasks 008 and 009)."""

import random
import time
from types import SimpleNamespace

import pytest

from quotable.gold.score import (
    TableRows,
    assign,
    extracted_from_run,
    normal,
    pair_columns,
    pair_rows,
    pair_tables,
    score_page,
    similarity,
)
from quotable.gold.store import GoldTable

SHA = "a" * 64


def gold(columns, rows) -> GoldTable:
    return GoldTable(list(columns), [list(r) for r in rows])


def table(columns, rows, index=0, label="Table 1") -> TableRows:
    return TableRows(index, label, list(columns), [list(r) for r in rows])


def score(golds, preds):
    return score_page(SHA, 1, golds, preds)


# --- the VRA cases ----------------------------------------------------------------------------
def test_unpaired_rows_and_columns_count_as_missed_or_extra():
    g = gold(
        ["Recipient", "Amount"], [["Pine County", "5,576,250"], ["Town of Sandwich", "1,650,000"]]
    )
    p = table(
        ["Recipient", "Amount", "State"],
        [["Town of Sandwich.", "$1,650,000", "NH"], ["Somewhere Else", "9", ""]],
    )
    page = score([g], [p])
    c = page.counts
    assert (c.matched_rows, c.cells) == (1, 7)
    assert c.hits["normal"] == c.cells_correct == 2  # both Sandwich cells
    assert (c.missed, c.extra) == (2, 3)  # Pine County; NH and the bad row
    assert (c.rows, c.rows_correct, page.correct) == (3, 0, False)


def test_row_and_page_accuracy_use_the_normal_level():
    g = gold(
        ["Recipient", "Amount"], [["Town of Sandwich", "1,650,000"], ["Pine County", "5,576,250"]]
    )
    right = table(
        ["Recipient", "Amount"], [["Town of Sandwich.", "$1,650,000"], ["Pine County", "5576250"]]
    )
    page = score([g], [right])
    assert (page.counts.rows, page.counts.rows_correct, page.correct) == (2, 2, True)
    wrong = table(["Recipient", "Amount"], [right.rows[0], ["Pine County", "5,576,251"]])
    page = score([g], [wrong])
    assert (page.counts.rows, page.counts.rows_correct, page.correct) == (2, 1, False)


def test_a_page_with_no_table_on_either_side_is_not_counted_and_is_correct():
    page = score([], [])
    assert not page.counted
    assert page.correct


def test_dots_in_the_extraction_against_a_blank_gold_are_extra():
    """Spec 014 keeps such cells as extracted; the VRA scorer called them blank."""
    page = score(
        [gold(["Budget", "Amount"], [["", "5"]])], [table(["Budget", "Amount"], [["---", "5"]])]
    )
    c = page.counts
    assert (c.cells, c.extra, c.rows_correct) == (2, 1, 0)


# --- columns ----------------------------------------------------------------------------------
def test_columns_pair_by_name_first():
    pairs = pair_columns(["Name", "Amount ($)"], [["a", "1"]], ["amount", "name"], [["1", "a"]])
    assert [(p.gold, p.extracted, p.how) for p in pairs] == [
        ("Name", "name", "name"),
        ("Amount ($)", "amount", "name"),
    ]


def test_columns_with_other_names_pair_by_their_values_and_say_so():
    rows_g = [["Sandwich", "1650000"], ["Pine", "5576250"], ["Oak", "10"]]
    rows_p = [["1650000", "Sandwich"], ["5576250", "Pine"], ["10", "Oak"]]
    pairs = pair_columns(["Town", "Money"], rows_g, ["Funding", "Place"], rows_p)
    assert [(p.gold, p.extracted, p.how) for p in pairs] == [
        ("Town", "Place", "values"),
        ("Money", "Funding", "values"),
    ]
    page = score([gold(["Town", "Money"], rows_g)], [table(["Funding", "Place"], rows_p)])
    assert page.correct
    assert [p.how for p in page.pairs[0].columns] == ["values", "values"]


def test_columns_that_share_nothing_stay_unpaired():
    pairs = pair_columns(["A"], [["x"], ["y"]], ["B"], [["p"], ["q"]])
    assert [(p.gold, p.extracted, p.how) for p in pairs] == [
        ("A", None, "none"),
        (None, "B", "none"),
    ]


def test_two_columns_with_the_same_values_pair_left_to_right():
    rows = [["2020", "2020"], ["2021", "2021"]]
    pairs = pair_columns(["A", "B"], rows, ["X", "Y"], rows)
    assert [(p.gold, p.extracted) for p in pairs] == [("A", "X"), ("B", "Y")]


# --- rows -------------------------------------------------------------------------------------
def test_equal_rows_pair_first_and_a_blank_row_never_pairs():
    cols = {0: 0, 1: 1}
    pairs = pair_rows([["a", "1"], ["", ""]], [["", ""], ["a", "1"]], cols)
    assert [(a, b) for a, b, _ in pairs] == [(0, 1)]


def test_a_row_under_the_threshold_is_not_a_match():
    assert pair_rows([["abcdef"]], [["uvwxyz"]], {0: 0}) == []


def test_equal_first_gives_the_same_total_as_a_full_assignment():
    rng = random.Random(5)
    words = ["red", "green", "blue", "gray", "teal", "gold"]
    for _ in range(200):
        n, m = rng.randint(1, 5), rng.randint(1, 5)
        g = [[rng.choice(words), rng.choice(words)] for _ in range(n)]
        p = [[rng.choice(words), rng.choice(words)] for _ in range(m)]
        cols = {0: 0, 1: 1}
        fast = pair_rows(g, p, cols)
        full = pair_rows(g, p, cols, equal_first=False)
        assert sum(s for *_, s in fast) == pytest.approx(sum(s for *_, s in full))
        assert len(fast) == len(full)


def test_a_page_of_400_rows_and_20_columns_scores_in_ten_seconds():
    columns = [f"C{i}" for i in range(20)]
    rows = [[f"value {r} {c}" for c in range(20)] for r in range(400)]
    altered = [list(r) for r in rows]
    for r in range(0, 400, 20):
        altered[r][3] = "changed " + altered[r][3]
    started = time.monotonic()
    page = score([gold(columns, rows)], [table(columns, altered)])
    assert time.monotonic() - started < 10
    assert page.counts.matched_rows == 400
    assert page.counts.rows_correct == 380


# --- tables -----------------------------------------------------------------------------------
def test_two_tables_pair_by_their_values_in_either_order():
    a = gold(["Name", "Amount"], [["Ann", "1"], ["Bob", "2"]])
    b = gold(["City", "Votes"], [["Rome", "900"], ["Oslo", "800"]])
    pa = table(["Name", "Amount"], a.rows, index=0, label="People")
    pb = table(["City", "Votes"], b.rows, index=1, label="Cities")
    for golds in ([a, b], [b, a]):
        page = score(golds, [pa, pb])
        assert page.correct
        assert page.unmatched_gold == page.unmatched_extracted == []
        assert {(p.label) for p in page.pairs} == {"People", "Cities"}


def test_a_table_cut_short_still_pairs_with_its_gold():
    rows = [[f"row {i}", str(i)] for i in range(10)]
    page = score([gold(["N", "V"], rows)], [table(["N", "V"], rows[:2])])
    assert page.unmatched_gold == []
    assert (page.counts.matched_rows, page.counts.rows_correct, page.counts.rows) == (2, 2, 10)
    assert not page.correct


def test_a_gold_table_with_no_partner_is_missed_and_an_extracted_one_is_extra():
    g = gold(["Name"], [["Ann"], ["Bob"]])
    other = table(["Thing"], [["zzz"], ["yyy"]], index=3, label="Other")
    page = score([g], [other])
    assert page.unmatched_gold == [1]
    assert page.unmatched_extracted == [3]
    assert (page.counts.missed, page.counts.extra) == (2, 2)
    assert set(page.by_table) == {None, 3}


def test_a_gold_table_without_rows_makes_every_extracted_row_extra():
    page = score([gold(["Name"], [])], [table(["Name"], [["Ann"], ["Bob"]])])
    assert page.unmatched_gold == [1]
    assert page.counts.extra == 2
    assert page.counted
    assert not page.correct


def test_a_done_page_with_no_table_makes_extracted_rows_extra_and_wrong():
    page = score([], [table(["Name"], [["Ann"]])])
    assert page.counts.extra == 1
    assert page.counted
    assert not page.correct


def test_a_table_the_pipeline_never_found_is_all_missed():
    page = score([gold(["Name", "V"], [["Ann", "1"], ["Bob", "2"]])], [])
    assert page.counts.missed == 4
    assert page.counted
    assert not page.correct


def test_two_printed_tables_merged_into_one_leave_the_second_as_missed():
    a = gold(["Name", "V"], [["Ann", "1"], ["Bob", "2"]])
    b = gold(["Name", "V"], [["Cy", "3"], ["Di", "4"]])
    merged = table(["Name", "V"], a.rows + b.rows)
    page = score([a, b], [merged])
    assert len(page.pairs) == 1
    assert page.unmatched_gold == [2]
    assert page.counts.missed == 4  # the second table's cells
    assert page.counts.extra == 4  # the merged table's rows from the second table
    assert not page.correct


def test_pair_tables_needs_at_least_one_paired_row():
    g = gold(["N"], [["alpha"]])
    p = table(["N"], [["omega"]])
    assert pair_tables([g], [p]) == []
    assert pair_tables([], [p]) == []


def test_similarity_and_assign_are_the_ones_tested_elsewhere():
    assert similarity(normal("A"), normal("a")) == 1.0
    assert assign([[1.0]]) == [(0, 0)]


# --- the adapter ------------------------------------------------------------------------------
def run_row(page, row, **values):
    return SimpleNamespace(page=page, row=row, values=values)


def test_extracted_from_run_orders_rows_and_fills_missing_values():
    run = SimpleNamespace(
        tables=[
            SimpleNamespace(
                index=2,
                label="Table 3",
                columns=["A", "B"],
                rows=[
                    run_row(5, 2, A="x2", B="y2"),
                    run_row(5, 1, A="x1"),
                    run_row(6, 1, A="z", B="w"),
                ],
            )
        ]
    )
    [one] = extracted_from_run(run)  # ty: ignore[invalid-argument-type]
    assert (one.index, one.label, one.columns) == (2, "Table 3", ["A", "B"])
    assert one.pages == {5: [["x1", ""], ["x2", "y2"]], 6: [["z", "w"]]}
    assert (one.on(5) or SimpleNamespace(rows=None)).rows == [["x1", ""], ["x2", "y2"]]
    assert one.on(7) is None
