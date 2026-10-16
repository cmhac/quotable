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
    live_runs,
    neutral_fields,
    neutral_request,
    overlap,
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
        assert overlap(header, neutral_request(truth, carry=carry)) == set()


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
