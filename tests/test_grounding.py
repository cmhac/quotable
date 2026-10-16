import json

import pymupdf

from quotable.grounding import ground_rows
from quotable.text import load_layer
from tests.conftest import DATA


def _ground(make_pdf, words, rows, columns):
    with pymupdf.open(make_pdf([words])) as document:
        layer = load_layer(document[0])
    return ground_rows(rows, columns, layer)


def test_a_value_printed_on_the_page_is_exact(make_pdf):
    words = [(72, 100, "Army"), (200, 100, "$1,250,000")]
    (row,) = _ground(make_pdf, words, [{"A": "Army", "B": "$1,250,000"}], ["A", "B"])
    assert row["A"].status == row["B"].status == "exact"
    assert row["A"].coverage == 1.0
    assert row["A"].matched_text == "Army"


def test_a_value_with_a_wrong_word_is_fuzzy_with_partial_coverage(make_pdf):
    words = [
        (72, 100, "Rehabilitation"),
        (160, 100, "of"),
        (180, 100, "Main"),
        (220, 100, "Street"),
    ]
    (row,) = _ground(make_pdf, words, [{"A": "Rehabilitation of Maine Street"}], ["A"])
    assert row["A"].status == "fuzzy"
    assert 0.75 <= row["A"].coverage < 1.0


def test_a_value_that_is_not_on_the_page_is_ungrounded(make_pdf):
    (row,) = _ground(make_pdf, [(72, 100, "Army")], [{"A": "Completely invented"}], ["A"])
    assert row["A"].status == "ungrounded"
    assert row["A"].coverage == 0.0


def test_empty_and_untokenizable_values_are_not_searched(make_pdf):
    (row,) = _ground(make_pdf, [(72, 100, "Army")], [{"A": "", "B": "—"}], ["A", "B"])
    assert row["A"].status == "empty"
    assert row["B"].status == "untokenized"


def test_a_repeated_value_takes_the_occurrence_in_its_own_row(make_pdf):
    words = [
        (72, 100, "FEMA"),
        (200, 100, "Alpha"),
        (72, 140, "FEMA"),
        (200, 140, "Bravo"),
    ]
    rows = [{"A": "FEMA", "B": "Alpha"}, {"A": "FEMA", "B": "Bravo"}]
    first, second = _ground(make_pdf, words, rows, ["A", "B"])
    assert first["A"].n_candidates == second["A"].n_candidates == 2
    assert first["A"].bbox[1] < 110  # the FEMA beside Alpha
    assert second["A"].bbox[1] > 130  # the FEMA beside Bravo


def test_recorded_rows_of_a_clean_sample_are_all_exact():
    # fy22_milcon_house_original: every recorded cell is printed verbatim.
    recorded = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
    with pymupdf.open(DATA / "fy22_milcon_house_original.pdf") as document:
        layer = load_layer(document[0])
    rows = recorded["pages"]["1"]
    grounded = ground_rows(rows, recorded["columns"], layer)
    statuses = {g.status for row in grounded for g in row.values()}
    assert statuses <= {"exact", "empty"}
