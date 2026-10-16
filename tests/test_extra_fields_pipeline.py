"""Extra fields through the whole pipeline, driven by fake models (no claim about a real one)."""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from quotable.extra_fields import ExtraField, ExtraFields, FieldGroup
from quotable.extract import run_pipeline
from quotable.llm import BudgetExceededError, CachedClient
from quotable.models import WindowWithExtras
from tests.conftest import DATA, FakeClient, extract_tables
from tests.extra_fields_model import request_for, truth_model
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import doc_ids
from tests.test_senate_tables import PDF as SENATE_PDF
from tests.test_senate_tables import RECORDED, recorded_model

EXTRA_IDS = [i for i in doc_ids() if i.startswith("extra-")]


def run(case_id, client, extra_fields, **kwargs):
    pdf = FIXTURE / f"{case_id}.pdf"
    return asyncio.run(run_pipeline(pdf, client, extra_fields=extra_fields, **kwargs))


def truth_of(case_id):
    return json.loads((FIXTURE / f"{case_id}.json").read_text())["extra_fields"]


def got_values(tables):
    """page -> name -> (value, source page) or None, over every page of every table."""
    out: dict[int, dict[str, tuple[str, int] | None]] = {}
    for table in tables:
        for page, row in table.extra_fields.items():
            out[page] = {
                n: (r.value, r.source_page) if r.source_page is not None else None
                for n, r in row.items()
            }
    return out


def expected_values(truth, mode, pages):
    return {
        p: {n: (v["value"], v["source_page"]) if v else None for n, v in row.items()}
        for p, row in ((int(k), r) for k, r in truth["expected"][mode].items())
        if p in pages
    }


def table_pages(tables):
    return {r.page for t in tables for r in t.pages}


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_every_document_gives_the_truth_values_with_the_carry(case_id):
    truth = truth_of(case_id)
    tables = run(case_id, truth_model(case_id), request_for(truth, carry=True))
    pages = table_pages(tables)
    assert got_values(tables) == expected_values(truth, "carry", pages)


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_every_document_gives_what_each_page_prints_without_the_carry(case_id):
    truth = truth_of(case_id)
    tables = run(case_id, truth_model(case_id), request_for(truth, carry=False))
    pages = table_pages(tables)
    assert got_values(tables) == expected_values(truth, "plain", pages)


@pytest.mark.parametrize("case_id", ["extra-ungrouped-stale", "extra-group-clears"])
def test_the_same_pages_without_groups_carry_the_stale_value(case_id):
    truth = truth_of(case_id)
    tables = run(case_id, truth_model(case_id), request_for(truth, carry=True, grouped=False))
    assert got_values(tables) == expected_values(truth, "carry_ungrouped", table_pages(tables))


def test_the_carry_is_off_unless_asked_for():
    truth = truth_of("extra-section-3p")
    request = request_for(truth, carry=False)
    assert request.carry_forward is False
    tables = run("extra-section-3p", truth_model("extra-section-3p"), request)
    rows = tables[0].rows()
    assert {r.page for r in rows if r.extra["division"].value} == {1}


# --- the Senate sample ------------------------------------------------------------------------
SENATE_FIELDS: list[ExtraField | FieldGroup] = [
    ExtraField("appropriation", "The appropriation label at the top left"),
    ExtraField("year", "The funding year"),
    ExtraField("title", "The title of the appropriation"),
]
SENATE_PAGE_1 = {
    "appropriation": "APPROPRIATIONS",
    "year": "2018",
    "title": "SALARIES, OFFICERS AND EMPLOYEES, SENATE",
}


SENATE_NAMES = [f for f in SENATE_FIELDS if isinstance(f, ExtraField)]


def senate_client(extras_by_page=None):
    base = recorded_model()
    discovery = RECORDED["discovery"]
    extras = extras_by_page or {1: SENATE_PAGE_1}

    def handler(request):
        if request.stage != "schema":
            return base.handler(request)
        pages = []
        for number, entry in enumerate(discovery["pages"], 1):
            values = extras.get(number, {})
            pages.append(
                {
                    **entry,
                    "extras": [
                        {"name": f.name, "value": values.get(f.name)} for f in SENATE_FIELDS
                    ],
                }
            )
        return WindowWithExtras.model_validate({"pages": pages})

    return FakeClient(handler)


def test_the_senate_sample_carries_page_one_to_the_continuation_pages():
    client = senate_client()
    summary, detail = extract_tables_with(
        SENATE_PDF, client, ExtraFields(SENATE_FIELDS, carry_forward=True), recheck=False
    )
    assert client.stages() == ["schema"] + ["extract"] * 4  # the region check asked nothing
    for table in (summary, detail):
        for page in table.extra_fields:
            assert table.extra_fields[page]["year"].value == "2018"
            assert table.extra_fields[page]["year"].source_page == 1
            assert table.extra_fields[page]["year"].grounding.status == "exact"
    assert set(detail.extra_fields) == {1, 2, 3}
    assert detail.extra_fields[1] == summary.extra_fields[1]  # a shared page: the same entry


def test_the_senate_sample_leaves_the_continuation_pages_empty_by_default():
    client = senate_client()
    _, detail = extract_tables_with(SENATE_PDF, client, ExtraFields(SENATE_FIELDS), recheck=False)
    assert detail.extra_fields[1]["year"].value == "2018"
    for page in (2, 3):
        assert detail.extra_fields[page]["year"].source_page is None
    records = detail.records()
    assert records[-1]["year"] == "" and records[-1]["year__source_page"] is None
    assert records[0]["year"] == "2018"
    assert client.stages() == ["schema"] + ["extract"] * 4


def extract_tables_with(pdf, client, extra_fields, **kwargs):
    return asyncio.run(run_pipeline(Path(pdf), client, extra_fields=extra_fields, **kwargs))


# --- checks before and around the requests ----------------------------------------------------
def test_a_bad_request_raises_before_any_model_call():
    client = truth_model("extra-section-1p")
    with pytest.raises(ValueError, match="at least one"):
        run("extra-section-1p", client, ExtraFields([]))
    with pytest.raises(ValueError, match="'a'"):
        run("extra-section-1p", client, ExtraFields([ExtraField("a", "x"), ExtraField("a", "y")]))
    assert client.requests == []


def test_without_extra_fields_the_output_is_what_it_always_was():
    plain = extract_tables(SENATE_PDF, recorded_model(), recheck=False)
    again = asyncio.run(
        run_pipeline(SENATE_PDF, recorded_model(), recheck=False, extra_fields=None)
    )
    assert [t.records() for t in plain] == [t.records() for t in again]
    assert all(t.extra_fields == {} and t.extra_names == () for t in again)


# --- the missed-header check and its second look ----------------------------------------------
HEADER_DOC = "extra-header-in-region"
MIXED = "extra-sections-mixed"


def test_a_header_row_where_the_block_was_printed_costs_one_second_look_per_page():
    truth = truth_of(HEADER_DOC)
    client = truth_model(HEADER_DOC)
    tables = run(HEADER_DOC, client, request_for(truth, carry=True))
    looks = [r for r in client.requests if r.stage == "extras"]
    assert sorted(r.page or 0 for r in looks) == [2, 3]  # one request each, for all fields
    assert got_values(tables) == expected_values(truth, "carry", {1, 2, 3})  # nothing changed


def test_the_second_look_counts_against_max_requests(tmp_path):
    truth = truth_of(HEADER_DOC)
    request = request_for(truth, carry=True)

    def new_requests(cap):
        client = CachedClient(truth_model(HEADER_DOC), tmp_path / f"c{cap}", cap)
        (tmp_path / f"c{cap}").mkdir()
        asyncio.run(run_pipeline(FIXTURE / f"{HEADER_DOC}.pdf", client, extra_fields=request))
        return client.new_requests

    assert new_requests(None) == 6  # discovery, three extractions, two second looks
    with pytest.raises(BudgetExceededError):
        new_requests(5)


@pytest.mark.parametrize("carry", [True, False])
def test_a_missed_header_is_found_by_the_check_whatever_the_carry_says(carry):
    truth = truth_of(MIXED)
    client = truth_model(
        MIXED,
        read={5: {"division": None}},  # the model misses the third section's header
        second=lambda page, names: {"division": "Parks"} if page == 5 else {},
    )
    tables = run(MIXED, client, request_for(truth, carry=carry))
    got = got_values(tables)
    assert got[5]["division"] == ("Parks", 5)
    assert any(r.page == 5 for r in client.requests if r.stage == "extras")


def test_a_second_look_that_does_not_ground_changes_nothing():
    truth = truth_of(MIXED)
    client = truth_model(
        MIXED,
        read={5: {"division": None}},
        second=lambda page, names: {"division": "Harbors"},
    )
    tables = run(MIXED, client, request_for(truth, carry=False))
    assert got_values(tables)[5]["division"] is None


# --- the recheck of a misread value -----------------------------------------------------------
def test_a_misread_header_is_rechecked_and_the_change_is_reported():
    truth = truth_of("extra-section-3p")
    client = truth_model(
        "extra-section-3p",
        read={1: {"division": "Raods"}},
        recheck={(1, "division"): "Roads"},
    )
    (table,) = run("extra-section-3p", client, request_for(truth, carry=True))
    assert {r.extra["division"].value for r in table.rows()} == {"Roads"}
    assert {r["recheck_changes"] for r in table.records()} == {'division: "Raods" -> "Roads"'}
    assert "recheck" in client.stages()


def test_without_the_recheck_the_misread_value_stays_and_is_flagged():
    truth = truth_of("extra-section-3p")
    client = truth_model("extra-section-3p", read={1: {"division": "Raods"}})
    (table,) = run("extra-section-3p", client, request_for(truth, carry=True), recheck=False)
    assert "recheck" not in client.stages()
    assert {r.extra["division"].value for r in table.rows()} == {"Raods"}
    assert {r.status for r in table.rows()} == {"ungrounded"}
    flags = table.flagged()
    assert flags and all(f.extra and f.column == "division" for f in flags)


def test_fields_on_ocrd_pages_are_grounded_against_the_ocr_text(tmp_path):
    from quotable.ocr import OcrConfig  # noqa: PLC0415
    from tests.fake_ocr import FakeEngine, native_as_ocr  # noqa: PLC0415

    garbled = DATA / "senate_expenditures_garbled.pdf"
    answers = [native_as_ocr(SENATE_PDF, n, OcrConfig().dpi) for n in (1, 2, 3)]
    tables = asyncio.run(
        run_pipeline(
            garbled,
            senate_client(),
            recheck=False,
            ocr=FakeEngine(*answers),
            ocr_config=OcrConfig(),
            cache_dir=tmp_path / "cache",
            extra_fields=ExtraFields(SENATE_FIELDS, carry_forward=True),
        )
    )
    detail = tables[1]
    assert detail.ocr_pages == (1, 2, 3)
    assert {detail.extra_fields[p]["year"].grounding.status for p in (1, 2, 3)} == {"exact"}
    assert [detail.extra_fields[p]["year"].source_page for p in (1, 2, 3)] == [1, 1, 1]


def test_the_counts_are_logged_at_info(caplog):
    caplog.set_level(logging.INFO, logger="quotable")
    truth = truth_of(HEADER_DOC)
    run(HEADER_DOC, truth_model(HEADER_DOC), request_for(truth, carry=True))
    (message,) = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("extra fields")
    ]
    assert "4 read on 1 page(s)" in message
    assert "2 page(s) carry a value from an earlier page" in message
    assert "2 suspect page(s)" in message
