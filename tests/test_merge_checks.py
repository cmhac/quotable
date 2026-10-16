"""The checks that decide whether two tables are parts of one (spec 007), as pure functions."""

import pytest

from gridkey import merge
from gridkey.merge import (
    DEFAULT_RULES,
    GRID_TOLERANCE,
    MIN_CELLS,
    SHAPE_SHARE,
    Rules,
    cell_shape,
    column_facts,
    compatible,
    dominant_shape,
    grid_ok,
    grid_positions,
    half_equal_ok,
    header_check,
    name_tokens,
    pair_verdict,
)
from gridkey.table import Table
from tests.table_builder import build_table

XS = [60.0, 200.0, 340.0]
A_COLUMNS = ["Project Name", "Requested Local Match", "Status"]
B_COLUMNS = ["Project Name", "Requested Match", "Status"]
NAMES = ["Alder Hall", "Birch Lane", "Cedar Row", "Dune Park", "Elm Court", "Fir Walk", "Gum Yard"]


def rows(columns: list[str], n: int, start: int = 0, *, money: bool = True) -> list[dict]:
    """``n`` rows: a name, an amount and a status word, all different, so all ground."""
    out = []
    for i in range(start, start + n):
        amount = f"${(i + 1) * 1000 + 250:,}" if money else f"{i * 3 + 11}.5"
        out.append(dict(zip(columns, [NAMES[i % 7] + f" {i}", amount, "Funded"], strict=True)))
    return out


def table(  # noqa: PLR0913
    tmp_path, columns, *, first_page=1, xs=XS, n=6, name="t", money=True, start=0
):
    return build_table(
        tmp_path,
        columns,
        [rows(columns, n, start, money=money)],
        xs=xs,
        first_page=first_page,
        name=name,
    )


def test_the_constants_have_the_spec_values():
    assert (GRID_TOLERANCE, MIN_CELLS, SHAPE_SHARE) == (10.0, 5, 0.8)
    assert DEFAULT_RULES.grid_tolerance == GRID_TOLERANCE
    assert DEFAULT_RULES.min_cells == MIN_CELLS
    assert DEFAULT_RULES.shape_share == SHAPE_SHARE
    assert DEFAULT_RULES.equal_share == 0.0  # the half-equal rule is off (spec 007, Results)
    assert not DEFAULT_RULES.word_text_apart


# --- header words -------------------------------------------------------------------


def test_name_tokens_lowercase_and_stem_and_split_multilevel_names():
    assert name_tokens("Requested Local Match") == {"requested", "local", "match"}
    assert name_tokens("Funding.Requested Amount") == {"funding", "requested", "amount"}
    assert name_tokens("") == frozenset()


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ({"amount"}, {"amount"}, True),
        ({"amount"}, {"requested", "amount"}, True),
        ({"requested", "amount"}, {"amount"}, True),
        ({"requested"}, {"recommended"}, False),
        ({"requested", "amount"}, {"recommended", "amount"}, False),
        (set(), {"amount"}, False),
        ({"amount"}, set(), False),
        (set(), set(), False),
    ],
)
def test_compatible_means_one_token_set_contains_the_other(a, b, expected):
    assert compatible(frozenset(a), frozenset(b)) is expected


def test_word_order_only_is_equal():
    check = header_check(["Amount Requested"], ["Requested Amount"])
    assert check.equal == 1
    assert check.all_compatible


def test_header_check_counts_equal_positions_and_compatibility():
    check = header_check(A_COLUMNS, B_COLUMNS)
    assert check.same_count
    assert check.equal == 2
    assert check.all_compatible
    assert not check.cross_compatible


def test_header_check_differing_column_counts():
    check = header_check(A_COLUMNS, B_COLUMNS[:2])
    assert not check.same_count
    assert not check.all_compatible


def test_header_check_incompatible_position():
    check = header_check(["Name", "Requested Amount"], ["Name", "Recommended Amount"])
    assert check.equal == 1
    assert not check.all_compatible


def test_a_bare_amount_is_cross_compatible_with_both_amounts():
    a = ["Name", "Requested Amount", "Recommended Amount"]
    b = ["Name", "Amount", "Amount Granted"]
    assert header_check(a, b).cross_compatible


def test_equal_share_is_a_setting():
    one_of_three = header_check(["a", "b", "c"], ["a", "b x", "c x"])
    assert not half_equal_ok(one_of_three, 0.5)
    assert half_equal_ok(one_of_three, 1 / 3)
    assert half_equal_ok(one_of_three, 0.0)
    assert half_equal_ok(header_check(["a"], ["a x"]), 0.0)  # off: even with none equal


def test_half_equal_ok_at_the_edges():
    two_of_four = header_check(["a", "b", "c", "d"], ["a", "b", "c x", "d x"])
    one_of_four = header_check(["a", "b", "c", "d"], ["a", "b x", "c x", "d x"])
    two_of_three = header_check(["a", "b", "c"], ["a", "b", "c x"])
    one_of_three = header_check(["a", "b", "c"], ["a", "b x", "c x"])
    assert half_equal_ok(two_of_four)
    assert not half_equal_ok(one_of_four)
    assert half_equal_ok(two_of_three)
    assert not half_equal_ok(one_of_three)


# --- shapes -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "shape"),
    [
        ("$1,250", "currency"),
        ("$1,250.50", "currency"),
        ("12.5%", "percent"),
        ("98,000", "integer"),
        ("42", "integer"),
        ("33.5", "decimal"),
        ("Mar 5, 2021", "date"),
        ("03/05/2021", "date"),
        ("2021-03-05", "date"),
        ("Windham", "text"),
        ("Cedar Harbor", "text"),
        ("Late filing", "text"),
        ("A12-3", "other"),
        ("--", "other"),
    ],
)
def test_cell_shape(value, shape):
    assert cell_shape(value) == shape


def test_a_single_word_is_a_word_when_words_and_text_are_told_apart():
    assert cell_shape("Windham", word_text_apart=True) == "word"
    assert cell_shape("Cedar Harbor", word_text_apart=True) == "text"


def test_word_and_text_count_as_one_shape_by_default():
    mixed = ["Merged", "Late filing", "Revised", "On hold", "See memo"]
    assert dominant_shape(mixed, 0.8) == "text"
    assert dominant_shape(mixed, 0.8, word_text_apart=True) is None


def test_dominant_shape_needs_the_share():
    def values(n_money, n_word):
        return ["$1,000"] * n_money + ["Cedar"] * n_word

    assert dominant_shape(values(8, 2), 0.8) == "currency"  # exactly 80%
    assert dominant_shape(values(79, 21), 0.8) is None
    assert dominant_shape(values(81, 19), 0.8) == "currency"
    assert dominant_shape([], 0.8) is None


# --- grid ---------------------------------------------------------------------------


def test_grid_positions_are_the_median_x_centre_of_the_cells(tmp_path):
    positions = grid_positions(table(tmp_path, A_COLUMNS))
    for position, x in zip(positions, XS, strict=True):
        assert position is not None
        assert x < position < x + 70  # the centre of a word that starts at x
    assert sorted(p for p in positions if p is not None) == positions


def test_grid_positions_are_none_for_a_column_without_cells(tmp_path):
    columns = ["Name", "Amount", "Note"]
    data = [
        dict(zip(columns, [f"Name {i} Hall", f"${i + 2},000", ""], strict=True)) for i in range(6)
    ]
    positions = grid_positions(build_table(tmp_path, columns, [data], xs=XS))
    assert positions[2] is None
    assert positions[0] is not None


def test_grid_ok_at_the_tolerance_edge():
    assert grid_ok([10.0, 100.0], [20.0, 110.0], 10.0)
    assert not grid_ok([10.0, 100.0], [20.01, 100.0], 10.0)
    assert not grid_ok([10.0, None], [10.0, 100.0], 10.0)


def test_grid_ok_needs_the_same_order_of_columns():
    assert not grid_ok([10.0, 12.0], [12.0, 10.0], 10.0)


# --- cells and facts ----------------------------------------------------------------


def test_column_facts_hold_position_count_and_shape(tmp_path):
    facts = column_facts(table(tmp_path, A_COLUMNS, n=6), DEFAULT_RULES)
    assert [f.cells for f in facts] == [6, 6, 6]
    assert [f.shape for f in facts] == ["text", "currency", "text"]
    assert all(f.position is not None for f in facts)


# --- the pair verdict ---------------------------------------------------------------


def test_a_reworded_pair_on_one_grid_passes(tmp_path):
    a = table(tmp_path, A_COLUMNS, first_page=1, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6)
    verdict = pair_verdict(a, b, rules=DEFAULT_RULES)
    assert verdict.ok, verdict.failed
    assert verdict.failed == ""
    assert verdict.evidence.equal_positions == 2
    assert verdict.evidence.shapes == ("text", "currency", "text")
    assert verdict.evidence.max_x_difference <= GRID_TOLERANCE


def test_a_shared_page_fails(tmp_path):
    a = table(tmp_path, A_COLUMNS, first_page=1, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=1, name="b", start=6)
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "shared_page"


def test_different_column_counts_fail(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = build_table(
        tmp_path,
        B_COLUMNS[:2],
        [[{k: v for k, v in r.items() if k in B_COLUMNS[:2]} for r in rows(B_COLUMNS, 6, 6)]],
        xs=XS[:2],
        first_page=7,
        name="b",
    )
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "count"


def test_incompatible_header_words_fail(tmp_path):
    a = table(tmp_path, ["Project Name", "Requested Amount", "Status"], name="a")
    b = table(
        tmp_path, ["Project Name", "Recommended Amount", "Status"], first_page=7, name="b", start=6
    )
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "header"


def test_fewer_than_half_equal_fails_only_when_the_rule_is_on(tmp_path):
    a_cols = ["Project Name", "Requested Local Match", "Funding Status"]
    b_cols = ["Project Name Full", "Requested Match", "Status"]
    a = table(tmp_path, a_cols, name="a")
    b = table(tmp_path, b_cols, first_page=7, name="b", start=6)
    assert pair_verdict(a, b, rules=Rules(equal_share=0.5)).failed == "half_equal"
    assert pair_verdict(a, b, rules=Rules(equal_share=0.0)).ok


def test_cross_compatible_positions_fail(tmp_path):
    a_cols = ["Project Name", "Requested Amount", "Amount Status"]
    b_cols = ["Project Name", "Amount", "Amount Status"]
    # position 1: "amount" is inside both of A's columns 1 and 2, so B's column 1 is ambiguous
    a = table(tmp_path, a_cols, name="a")
    b = table(tmp_path, b_cols, first_page=7, name="b", start=6)
    assert pair_verdict(a, b, rules=Rules(equal_share=0.0)).failed == "ambiguity"


def test_a_shifted_grid_fails(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, xs=[x + 25 for x in XS])
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "grid"


def test_a_shift_inside_the_tolerance_passes(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, xs=[x + 6 for x in XS])
    assert pair_verdict(a, b, rules=DEFAULT_RULES).ok


def test_different_value_shapes_fail(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, money=False)
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "shape"


def test_too_few_cells_fail(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a", n=MIN_CELLS - 1)
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6)
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "min_cells"


def test_exactly_min_cells_passes(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a", n=MIN_CELLS)
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, n=MIN_CELLS)
    assert pair_verdict(a, b, rules=DEFAULT_RULES).ok


def test_min_cells_is_a_rule_setting(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a", n=3)
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, n=3)
    assert not pair_verdict(a, b, rules=DEFAULT_RULES).ok
    assert pair_verdict(a, b, rules=Rules(min_cells=3)).ok


def test_no_dominant_shape_fails(tmp_path):
    columns = A_COLUMNS
    mixed = []
    for i in range(6):
        value = f"${i + 2},000" if i % 2 else f"{i + 3}.5%"
        mixed.append({columns[0]: f"Name {i} Hall", columns[1]: value, columns[2]: "Funded"})
    mixed = [
        {**r, columns[1]: ["$2,000", "3.5%", "$4,100", "5.5%", "$6,200", "7.5%"][i]}
        for i, r in enumerate(mixed)
    ]
    a = build_table(tmp_path, columns, [mixed], xs=XS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6)
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "no_shape"


def test_a_column_empty_throughout_fails(tmp_path):
    columns = ["Name", "Amount", "Note"]
    data = [
        dict(zip(columns, [f"Name {i} Hall", f"${i + 2},000", ""], strict=True)) for i in range(6)
    ]
    a = build_table(tmp_path, columns, [data], xs=XS, name="a")
    b = build_table(tmp_path, columns, [data], xs=XS, first_page=7, name="b")
    assert pair_verdict(a, b, rules=DEFAULT_RULES).failed == "min_cells"


def test_a_table_with_no_pages_fails(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    empty = Table(B_COLUMNS, [], {}, {}, {})
    assert pair_verdict(a, empty, rules=DEFAULT_RULES).failed == "min_cells"


def test_the_module_imports_nothing_from_extract():
    assert "gridkey.extract" not in {
        getattr(v, "__module__", "") for v in vars(merge).values() if callable(v)
    }
