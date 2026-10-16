"""The live tests' extra-field requests never print a word of the headers they ask about."""

import json

import pymupdf
import pytest

from quotable.text import tokenize
from tests.conftest import DATA
from tests.extra_fields_live import (
    SENATE_HEADER_BOX,
    field_description,
    header_words,
    label_marks,
    live_runs,
    neutral_fields,
    neutral_request,
    overlap,
    value_lines,
    words_in_box,
)
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import doc_ids

EXTRA_IDS = [i for i in doc_ids() if i.startswith("extra-")]


def truth_of(case_id):
    return json.loads((FIXTURE / f"{case_id}.json").read_text())["extra_fields"]


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_no_word_of_the_header_is_in_what_the_live_tests_send(case_id):
    truth = truth_of(case_id)
    header = header_words(FIXTURE / f"{case_id}.pdf", truth)
    assert header  # the check has something to compare with
    for carry in (True, False):
        request = neutral_request(truth, carry=carry, pdf=FIXTURE / f"{case_id}.pdf")
        assert overlap(header, request) == set()


@pytest.mark.parametrize(
    ("case_id", "marks"),
    [
        ("extra-section-1p", [True]),  # "<label> Roads": the value is the second word
        ("extra-number-case", [False, True]),  # a line with no label, then "<label> <label> 2018"
        ("extra-wrapped-value", [True]),  # "<label> Department of Roads" wraps to a second line
        ("extra-senate-geometry", [False, True, False, False]),  # the account line is kept whole
    ],
)
def test_the_label_marks_come_from_where_the_value_starts_on_its_line(case_id, marks):
    pdf = FIXTURE / f"{case_id}.pdf"
    assert label_marks(pdf, truth_of(case_id)) == marks


@pytest.mark.parametrize(
    ("case_id", "spans"),
    [("extra-wrapped-value", [2]), ("extra-section-1p", [1]), ("extra-senate-geometry", [1] * 4)],
)
def test_a_value_that_wraps_is_described_as_printed_over_several_lines(case_id, spans):
    facts = value_lines(FIXTURE / f"{case_id}.pdf", truth_of(case_id))
    assert [lines for _, lines in facts] == spans


def test_a_wrapped_value_makes_the_next_field_start_below_it():
    first, second = neutral_fields(2, [True, False], [2, 1])
    assert "lines 1 to 2" in first.description
    assert "line 3 of the block" in second.description


def test_the_description_tells_the_model_what_to_do_with_the_label_of_a_line():
    assert "leave the label out" in field_description(1, True)
    assert "keep every word" in field_description(1, False)
    assert "leave the label out" in field_description(1)  # unknown: the model decides
    assert field_description(1, True) != field_description(1, False) != field_description(1)


def test_the_senate_header_is_not_in_what_the_live_tests_send():
    header = words_in_box(DATA / "senate_expenditures_paddleocr.pdf", 1, SENATE_HEADER_BOX)
    assert set(tokenize("APPROPRIATIONS SALARIES SENATE")) <= header  # the box holds the header
    request = neutral_request({"fields": [{"name": n, "group": None} for n in "abc"]}, carry=True)
    assert overlap(header, request) == set()


def test_the_check_catches_a_description_that_prints_a_header_word():
    from quotable.extra_fields import ExtraField, ExtraFields  # noqa: PLC0415

    leaky = ExtraFields([ExtraField("year", "The funding year printed at the top")])
    assert overlap({"funding", "year", "2018"}, leaky) == {"funding", "year"}
    assert overlap({"funding"}, ExtraFields([ExtraField("a", "The second line")])) == set()


def test_the_fields_are_described_by_position_only():
    fields = neutral_fields(3)
    assert [f.name for f in fields] == ["heading_1", "heading_2", "heading_3"]
    assert "line 2 of the block" in field_description(2)
    assert len({f.description for f in fields}) == 3


def test_the_fixture_blocks_hold_real_header_words():
    case_id = "extra-senate-geometry"
    with pymupdf.open(FIXTURE / f"{case_id}.pdf") as pdf:
        assert pdf.page_count == 3
    assert {"appropriation", "year", "2018"} <= header_words(
        FIXTURE / f"{case_id}.pdf", truth_of(case_id)
    )


# --- the live tests' bookkeeping, driven by a fake model ---------------------------------------
def _live_run(case_id, **faults):
    import asyncio  # noqa: PLC0415

    from quotable.extract import run_pipeline  # noqa: PLC0415
    from tests.extra_fields_model import truth_model  # noqa: PLC0415
    from tests.live.test_live_extra_fields import Recording, numbers  # noqa: PLC0415

    truth = truth_of(case_id)
    request = neutral_request(truth, carry=True)
    rename = {f["name"]: f"heading_{k + 1}" for k, f in enumerate(truth["fields"])}
    fake = truth_model(case_id, rename=rename, **faults)
    client = Recording(fake)
    tables = asyncio.run(
        run_pipeline(FIXTURE / f"{case_id}.pdf", client, extra_fields=request, recheck=False)
    )
    pages = max(r.page for t in tables for r in t.pages)
    return numbers(truth, tables, client, pages), tables


def test_the_live_report_counts_a_missed_header_before_and_after_the_second_look():
    found, _ = _live_run(
        "extra-sections-mixed",
        read={5: {"division": None}},
        second=lambda page, names: {"heading_1": "Parks"} if page == 5 else {},
    )
    assert found["missed_before_the_region_check"] == [(5, "division")]
    assert found["missed_after_the_second_look"] == []
    assert found["second_look_pages"] == [5]
    assert found["false_alarm_pages"] == []


def test_the_live_report_counts_a_missed_header_that_stays_missed():
    found, _ = _live_run("extra-sections-mixed", read={5: {"division": None}})
    assert found["missed_before_the_region_check"] == [(5, "division")]
    assert found["missed_after_the_second_look"] == [(5, "division")]


def test_the_live_report_counts_false_alarms():
    found, _ = _live_run("extra-header-in-region")
    assert found["false_alarm_pages"] == [2, 3]
    assert found["missed_before_the_region_check"] == []
    assert found["second_looks_per_100_pages"] == pytest.approx(66.7)


# --- how many times a live case runs (QUOTABLE_LIVE_RUNS) ---------------------------------------
@pytest.mark.parametrize(
    ("value", "runs"),
    [(None, (1, 2, 3)), ("", (1, 2, 3)), ("1", (1,)), ("2", (1, 2)), (" 5 ", (1, 2, 3, 4, 5))],
)
def test_live_runs_defaults_to_three_and_takes_a_count(value, runs):
    assert live_runs(value) == runs


@pytest.mark.parametrize("value", ["0", "-1", "two", "1.5"])
def test_live_runs_rejects_anything_but_a_positive_whole_number(value):
    with pytest.raises(ValueError, match="QUOTABLE_LIVE_RUNS"):
        live_runs(value)


# --- the running title above the block (first live run: the model read it as line 1) ------------
def top_line(page):
    """Return the text of the topmost block of a page, digits removed."""
    blocks = sorted(page.get_text("blocks"), key=lambda b: b[1])
    return "".join(c for c in blocks[0][4] if not c.isdigit()).strip()


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_every_fixture_page_starts_with_a_title_that_is_not_part_of_the_block(case_id):
    with pymupdf.open(FIXTURE / f"{case_id}.pdf") as document:
        tops = {top_line(page) for page in document}
    assert len(tops) == 1  # the same title tops every page, so it is not a header block line


def test_the_field_description_counts_lines_from_below_the_title_printed_on_every_page():
    text = field_description(1)
    assert "every page" in text
    assert "title" in text


def test_the_field_description_says_to_leave_a_label_out_of_the_value():
    text = field_description(1)
    assert "leave the label out" in text
    assert "no label" in text  # a line without one is given whole
