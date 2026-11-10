"""The omission audit's pure parts: unexplained words, furniture, judging, applying (spec 014)."""

import pytest

from quotable.llm.answers import FilledCell, MissingRow, Omissions
from quotable.llm.client import Image
from quotable.llm.images import ImagePolicy
from quotable.steps import audit as A  # noqa: N812
from quotable.steps.grounding import FieldGrounding
from quotable.steps.position import PageGrounding
from quotable.table import PageResult
from quotable.text.layer import Layer

NAMES = ["A", "B"]


def layer_of(*words: str) -> Layer:
    """A text layer with these words, left to right on one line, 20 pt apart."""
    layer = Layer()
    for i, word in enumerate(words):
        layer.add(word, (20.0 * i, 0.0, 20.0 * i + 15, 10.0))
    return layer


def page_of(layer: Layer, rows: list[dict[str, str]], furniture: set[str] | None = None):
    """The `AuditPage` of a layer and its listed rows, as `audit_table` builds it."""
    words, evidence = A.audit_words(layer, rows, NAMES, furniture or set())
    return A.AuditPage(NAMES, layer, evidence), words


# --- unexplained words ---------------------------------------------------------------------
def test_unexplained_matches_cell_tokens_to_page_tokens_one_for_one():
    layer = layer_of("alpha", "x", "x", "beta")
    rows = [{"A": "alpha", "B": "x"}]
    left = A.unexplained(layer, rows, NAMES)
    assert [token for token, _ in left] == ["x", "beta"]  # one x is accounted for, one is not


def test_a_cell_of_only_dots_or_dashes_makes_no_token_and_explains_nothing():
    layer = layer_of("alpha", ".....", "---")
    rows = [{"A": "alpha", "B": "....."}]
    assert A.unexplained(layer, rows, NAMES) == []


def test_audit_words_come_once_each_in_layer_order_without_furniture():
    layer = layer_of("alpha", "page", "beta", "page", "gamma")
    words, evidence = A.audit_words(layer, [{"A": "alpha", "B": ""}], NAMES, {"gamma"})
    assert words == ["page", "beta", "page"]  # a word is listed once per occurrence on the page
    assert evidence == {"page", "beta"}


# --- furniture ---------------------------------------------------------------------------------
def test_a_word_unexplained_on_30_percent_of_five_pages_is_furniture():
    pages = [{"header"}, {"header"}, set(), set(), set()]  # 2 of 5 = 40%
    assert A.furniture(pages) == {"header"}


def test_a_word_unexplained_on_one_of_five_pages_is_not():
    assert A.furniture([{"page1"}, set(), set(), set(), set()]) == set()  # 20%


def test_with_fewer_than_five_pages_nothing_is_furniture():
    assert A.furniture([{"header"}] * 4) == set()


# --- near spelling -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a", "b", "close"),
    [
        ("bennett", "bennet", True),  # one deletion
        ("bennte", "bennet", True),  # one adjacent swap
        ("garcia", "garsia", True),  # one substitution
        ("abcdefg", "abxdxfg", True),  # two substitutions
        ("abcdefg", "abxdxfx", False),  # three
        ("abcde", "abcdefgh", False),  # length differs by more than two
    ],
)
def test_two_edits_are_close_three_are_not(a, b, close):
    assert A.within_edits(a, b, 2) is close


def test_a_near_word_takes_the_pages_spelling_for_the_check():
    page, _ = page_of(layer_of("bennet", "100"), [])
    assert A.near_word("bennett", page) == "bennet"
    assert A.near_word("bennet", page) == "bennet"  # already on the page


def test_a_short_word_a_number_or_a_far_word_is_left_alone():
    page, _ = page_of(layer_of("ben", "12346", "unrelated"), [])
    assert A.near_word("bon", page) == "bon"  # fewer than five letters
    assert A.near_word("12345", page) == "12345"  # numbers must match exactly
    assert A.near_word("something", page) == "something"


def test_two_equally_near_page_words_are_ambiguous_and_left_alone():
    page, _ = page_of(layer_of("bennet", "bennit"), [])
    assert A.near_word("bennat", page) == "bennat"


def test_an_unexplained_near_word_wins_a_tie():
    page, _ = page_of(layer_of("bennet", "bennit"), [{"A": "bennit", "B": ""}])
    assert A.near_word("bennat", page) == "bennet"  # only "bennet" is unexplained


# --- judging -----------------------------------------------------------------------------------
LISTED = [{"A": "alpha", "B": "100"}, {"A": "gamma", "B": ""}]
PAGE_WORDS = ("alpha", "100", "gamma", "delta", "200", "epsilon")


def judge_row(values: dict[str, str], after_row: int = 1, rows=None):
    page, _ = page_of(layer_of(*PAGE_WORDS), LISTED)
    return A.judge_row(
        MissingRow(after_row=after_row, values=values), len(LISTED), rows or LISTED, page
    )


def test_a_row_the_text_layer_confirms_and_that_uses_unexplained_words_is_accepted():
    outcome, row = judge_row({"A": "delta", "B": "200"})
    assert (outcome, row) == ("accepted", {"A": "delta", "B": "200"})


def test_a_row_is_judged_with_its_values_stripped_and_missing_columns_empty():
    outcome, row = judge_row({"A": " delta "})
    assert (outcome, row) == ("accepted", {"A": "delta", "B": ""})


@pytest.mark.parametrize("after_row", [-1, 3])
def test_a_position_that_does_not_exist_is_invalid(after_row):
    assert judge_row({"A": "delta", "B": "200"}, after_row)[0] == "invalid_row"


def test_a_row_with_no_text_is_invalid():
    assert judge_row({"A": "", "B": "..."})[0] == "invalid_row"


def test_a_row_that_repeats_a_listed_row_is_a_duplicate():
    assert judge_row({"A": "alpha", "B": "100"})[0] == "duplicate"
    assert judge_row({"A": "alpha"})[0] == "duplicate"  # every cell it fills repeats a row


def test_a_row_with_a_value_not_on_the_page_is_ungrounded():
    assert judge_row({"A": "delta", "B": "999"})[0] == "ungrounded"
    assert judge_row({"A": "delta qqq", "B": "200"})[0] == "ungrounded"  # nothing in a row matches


def test_a_row_the_text_layer_matches_only_in_part_is_accepted_for_the_recheck():
    # one word of the cell is not on the page (the layer split or misread it): grounds `fuzzy`
    outcome, row = judge_row({"A": "delta 200 zzz epsilon", "B": ""})
    assert (outcome, row["A"]) == ("accepted", "delta 200 zzz epsilon")


def test_a_row_made_of_words_already_explained_has_no_evidence():
    # "gamma" is on the page and exact, but the listed row 2 already accounts for it
    assert judge_row({"A": "gamma", "B": "100"})[0] == "no_evidence"


def test_a_row_may_be_a_little_off_the_page_spelling_and_keeps_the_models():
    page, _ = page_of(layer_of("alpha", "100", "bennet", "200"), LISTED)
    proposal = MissingRow(after_row=2, values={"A": "bennett", "B": "200"})
    outcome, row = A.judge_row(proposal, 2, LISTED, page)
    assert (outcome, row["A"]) == ("accepted", "bennett")


def judge_cell(row: int, column: str, value: str, taken=frozenset()):
    page, _ = page_of(layer_of(*PAGE_WORDS), LISTED)
    return A.judge_cell(FilledCell(row=row, column=column, value=value), LISTED, page, set(taken))


def test_an_empty_cell_filled_with_a_confirmed_value_is_accepted():
    assert judge_cell(2, "B", "200") == "accepted"


@pytest.mark.parametrize(("row", "column"), [(0, "B"), (3, "B"), (2, "C")])
def test_a_cell_that_does_not_exist_is_invalid(row, column):
    assert judge_cell(row, column, "200") == "invalid_cell"


def test_a_cell_the_text_layer_matches_only_in_part_is_accepted():
    assert judge_cell(2, "B", "delta 200 zzz epsilon") == "accepted"


def test_the_other_cell_outcomes():
    assert judge_cell(2, "B", "...") == "empty"
    assert judge_cell(1, "B", "200") == "not_empty"
    assert judge_cell(2, "B", "200", taken={(2, "B")}) == "repeated"
    assert judge_cell(2, "B", "999") == "ungrounded"
    assert judge_cell(2, "B", "alpha") == "no_evidence"  # on the page, but already explained


# --- applying ----------------------------------------------------------------------------------
def applied(found: Omissions, rows=None, absent=()):
    rows = rows or [{"A": "alpha", "B": "100"}, {"A": "gamma", "B": ""}, {"A": "omega", "B": ""}]
    layer = layer_of(
        "alpha", "100", "gamma", "omega", "delta", "200", "epsilon", "300", "zeta", "400"
    )
    page, _ = page_of(layer, rows)
    return A.apply(PageResult(4, rows, tuple(absent)), page, found)


def test_accepted_rows_and_cells_are_applied_and_numbered_by_position():
    found = Omissions(
        missing_rows=[
            MissingRow(after_row=1, values={"A": "delta", "B": "200"}),
            MissingRow(after_row=0, values={"A": "epsilon", "B": "300"}),
            MissingRow(after_row=1, values={"A": "zeta"}),  # a second row after row 1, in order
        ],
        filled_cells=[FilledCell(row=2, column="B", value="400")],
    )
    result, items = applied(found)
    assert [r["A"] for r in result.rows] == ["epsilon", "alpha", "delta", "zeta", "gamma", "omega"]
    assert result.rows[4]["B"] == "400"  # row 2 got its cell, whatever its new number
    by_kind = {(i.kind, tuple(i.values.values())): i for i in items}
    assert by_kind["row", ("epsilon", "300")].row == 1
    assert by_kind["row", ("delta", "200")].row == 3
    assert by_kind["row", ("zeta", "")].row == 4
    assert by_kind["cell", ("400",)].row == 5
    assert all(i.outcome == "accepted" for i in items)


def test_nothing_accepted_returns_the_page_itself_and_every_proposal_recorded():
    found = Omissions(
        missing_rows=[MissingRow(after_row=1, values={"A": "nowhere", "B": "9"})],
        filled_cells=[FilledCell(row=1, column="B", value="200")],
    )
    page_in = PageResult(4, [{"A": "alpha", "B": "100"}])
    layer = layer_of("alpha", "100", "200")
    audit_page, _ = page_of(layer, page_in.rows)
    result, items = A.apply(page_in, audit_page, found)
    assert result is page_in
    assert [(i.kind, i.outcome) for i in items] == [("cell", "not_empty"), ("row", "ungrounded")]


def test_no_value_already_extracted_ever_changes():
    rows = [{"A": "alpha", "B": "100"}, {"A": "gamma", "B": ""}]
    before = [dict(r) for r in rows]
    found = Omissions(
        missing_rows=[MissingRow(after_row=2, values={"A": "delta", "B": "200"})],
        filled_cells=[
            FilledCell(row=1, column="A", value="delta"),  # a non-empty cell: refused
            FilledCell(row=2, column="B", value="200"),
        ],
    )
    result, _ = applied(found, rows)
    kept = [r for r in result.rows if r["A"] in ("alpha", "gamma")]
    assert [r["A"] for r in kept] == ["alpha", "gamma"]
    assert kept[0] == before[0]
    assert kept[1] == {"A": "gamma", "B": "200"}  # only the empty cell changed


def test_an_added_row_gets_an_empty_value_for_every_column_the_page_does_not_print():
    rows = [{"A": "alpha", "B": "100", "C": ""}]
    layer = layer_of("alpha", "100", "delta", "200")
    page, _ = page_of(layer, rows)
    page.names = NAMES
    found = Omissions(
        missing_rows=[MissingRow(after_row=1, values={"A": "delta", "B": "200", "C": "ignored"})],
        filled_cells=[],
    )
    result, _ = A.apply(PageResult(1, rows, ("C",)), page, found)
    assert result.rows[1] == {"A": "delta", "B": "200", "C": ""}
    assert result.absent == ("C",)


# --- hints -------------------------------------------------------------------------------------
def grounding_of(layer: Layer, rows: list[dict[str, str]]) -> PageGrounding:
    cells = [{n: FieldGrounding("empty" if not r[n] else "exact") for n in NAMES} for r in rows]
    return PageGrounding(
        rows,
        cells,
        layer,
        row_windows={0: (0.0, 20.0), 1: (20.0, 40.0)},
        column_ranges={"A": (0.0, 50.0), "B": (50.0, 100.0)},
    )


def test_a_word_inside_an_empty_cell_is_named_with_its_row_and_column():
    layer = Layer()
    layer.add("alpha", (5, 5, 30, 15))
    layer.add("lost", (55, 25, 80, 35))  # row 2, column B, which is empty
    layer.add("beta", (5, 25, 30, 35))
    rows = [{"A": "alpha", "B": ""}, {"A": "beta", "B": ""}]
    assert A.hints(grounding_of(layer, rows), NAMES) == ["Row 2, B: lost"]


def test_a_word_in_a_filled_cell_or_outside_every_cell_is_not_a_hint():
    layer = Layer()
    layer.add("inside", (55, 5, 80, 15))  # row 1, column B, filled
    layer.add("outside", (200, 5, 230, 15))  # no column there
    rows = [{"A": "", "B": "inside"}, {"A": "", "B": ""}]
    assert A.hints(grounding_of(layer, rows), NAMES) == []


def test_hints_stop_at_the_limit():
    layer = Layer()
    wide = PageGrounding(
        [{"A": "", "B": ""}] * 50,
        [{n: FieldGrounding("empty") for n in NAMES}] * 50,
        layer,
        row_windows={i: (20.0 * i, 20.0 * i + 20) for i in range(50)},
        column_ranges={"A": (0.0, 50.0), "B": (50.0, 100.0)},
    )
    for i in range(50):
        layer.add(f"w{i}", (55, 20.0 * i + 5, 80, 20.0 * i + 15))
    assert len(A.hints(wide, NAMES)) == A.CELL_HINT_MAX == 40


# --- the request -------------------------------------------------------------------------------
def test_the_request_has_the_numbered_columns_the_image_and_the_listing():
    words = [f"w{i}" for i in range(55)]
    request = A.build_request(
        7,
        b"png",
        ImagePolicy(300, "original", None, None),
        NAMES,
        LISTED,
        words,
        ["Row 2, B: lost"],
    )
    assert (request.stage, request.page, request.output_type) == ("audit", 7, Omissions)
    structure, image, text = request.parts
    assert isinstance(structure, str) and "2 columns" in structure and "1. A" in structure
    assert isinstance(image, Image) and image.png == b"png" and image.detail == "original"
    assert isinstance(text, str)
    assert 'Row 1: {"A": "alpha", "B": "100"}' in text
    assert "w39" in text and "w40" not in text  # at most 40 words
    assert "Row 2, B: lost" in text
    assert "OMITTED" in request.instructions and "horizontal position" in request.instructions


def test_without_cell_hints_the_request_does_not_mention_them():
    request = A.build_request(
        1, b"p", ImagePolicy(150, "high", None, None), NAMES, LISTED, ["x"], []
    )
    assert "EMPTY in the list" not in str(request.parts[2])
