import copy
import inspect
import json

import pytest

from quotable import ExtractionError, TextLayerError, extract_tables_async
from quotable import extract_tables as public_extract_tables
from quotable.extract import run_pipeline
from quotable.llm import Image
from quotable.models import PageRows
from tests.conftest import (
    DATA,
    FakeClient,
    extract_tables,
    load_sample,
    one_table,
    replay,
    window_of,
)


def test_the_sample_documents_come_back_as_the_rows_the_model_gave(sample):
    client = replay(sample["columns"], sample["pages"])
    (table,) = extract_tables(sample["pdf"], client, recheck=False)
    assert table.columns == sample["columns"]
    for number, rows in sample["pages"].items():
        assert [r.values for r in table.page_rows(number)] == rows


def test_it_asks_for_the_tables_once_then_for_each_page(sample):
    client = replay(sample["columns"], sample["pages"])
    extract_tables(sample["pdf"], client, recheck=False)
    assert client.stages() == ["schema"] + ["extract"] * len(sample["pages"])


def test_discovery_sees_every_page_in_windows():
    four_pages = load_sample("fy22_ag_house_original")
    client = replay(four_pages["columns"], four_pages["pages"])
    extract_tables(four_pages["pdf"], client, discovery_pages=2, recheck=False)
    discovery = [r for r in client.requests if r.stage == "schema"]
    assert [sum(isinstance(p, Image) for p in r.parts) for r in discovery] == [2, 2]


def test_discovery_sees_all_four_pages_in_one_request_by_default():
    four_pages = load_sample("fy22_ag_house_original")
    client = replay(four_pages["columns"], four_pages["pages"])
    extract_tables(four_pages["pdf"], client, recheck=False)
    discovery = [r for r in client.requests if r.stage == "schema"]
    assert [sum(isinstance(p, Image) for p in r.parts) for r in discovery] == [4]


def test_each_page_request_has_the_columns_and_that_pages_image(sample):
    client = replay(sample["columns"], sample["pages"])
    extract_tables(sample["pdf"], client, recheck=False)
    request = client.requests[1]
    assert request.page == 1
    assert sum(isinstance(p, Image) for p in request.parts) == 1
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    assert all(column in text for column in sample["columns"])


def test_every_cell_carries_a_grounding_status_and_coverage(sample):
    client = replay(sample["columns"], sample["pages"])
    (table,) = extract_tables(sample["pdf"], client, recheck=False)
    record = table.records()[0]
    for column in sample["columns"]:
        assert record[column] == sample["pages"][1][0][column]
        assert record[f"{column}__grounding"] in {
            "exact",
            "fuzzy",
            "ungrounded",
            "misplaced",
            "empty",
        }
        assert f"{column}__coverage" in record
    assert {"page", "row", "grounding_status"} <= set(record)


def test_a_clean_sample_has_nothing_flagged():
    recorded = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
    pages = {int(p): rows for p, rows in recorded["pages"].items()}
    client = replay(recorded["columns"], pages)
    (table,) = extract_tables(DATA / "fy22_milcon_house_original.pdf", client, recheck=False)
    assert table.flagged() == []
    assert {r["grounding_status"] for r in table.records()} == {"exact"}


def test_a_value_moved_to_another_row_is_caught_by_the_position_check():
    recorded = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
    rows = copy.deepcopy(recorded["pages"]["1"])
    rows[1]["Project"], rows[8]["Project"] = rows[8]["Project"], rows[1]["Project"]
    client = replay(recorded["columns"], {1: rows})
    (table,) = extract_tables(DATA / "fy22_milcon_house_original.pdf", client, recheck=False)
    assert table.position["misplaced"] == 2
    assert {(f.row, f.column, f.status) for f in table.flagged()} == {
        (2, "Project", "misplaced"),
        (9, "Project", "misplaced"),
    }


def test_rows_with_the_wrong_keys_are_sent_back_once(make_pdf):
    path = make_pdf([[(72, 60, "Alpha"), (182, 60, "Beta")]])
    answers = iter(
        [
            PageRows(rows=[{"A": "Alpha", "Extra": "x"}]),  # wrong keys
            PageRows(rows=[{"A": "Alpha", "B": "Beta"}]),
        ]
    )

    def handler(request):
        if request.stage == "schema":
            return window_of(request, [one_table(["A", "B"])])
        return next(answers)

    client = FakeClient(handler)
    (table,) = extract_tables(path, client, recheck=False)
    assert [r.values for r in table.page_rows(1)] == [{"A": "Alpha", "B": "Beta"}]
    retry = client.requests[-1]
    assert any("Extra" in p for p in retry.parts if isinstance(p, str))  # the problem is named


def test_rows_that_are_still_wrong_after_the_retry_abort(make_pdf):
    path = make_pdf([[(72, 60, "Alpha")]])

    def handler(request):
        if request.stage == "schema":
            return window_of(request, [one_table(["A"])])
        return PageRows(rows=[{"Nope": "Alpha"}])

    with pytest.raises(ExtractionError, match="page 1"):
        extract_tables(path, FakeClient(handler), recheck=False)


def test_a_column_the_page_does_not_print_is_not_asked_for_and_stays_blank(make_pdf):
    header = ["Account", "Location", "Project", "Amount"]
    page1 = [(72 + 110 * i, 60, n) for i, n in enumerate(header)] + [
        (72, 90, "Army"),
        (182, 90, "Bragg"),
        (292, 90, "Barracks"),
        (402, 90, "$100"),
    ]
    page2 = [(72 + 110 * i, 60, n) for i, n in enumerate(header[:3])] + [
        (72, 90, "Navy"),
        (182, 90, "Norfolk"),
        (292, 90, "Pier"),
    ]
    path = make_pdf([page1, page2])
    rows = {
        1: [{"Account": "Army", "Location": "Bragg", "Project": "Barracks", "Amount": "$100"}],
        2: [{"Account": "Navy", "Location": "Norfolk", "Project": "Pier"}],  # no Amount asked
    }

    def handler(request):
        if request.stage == "schema":
            return window_of(request, [one_table(header)])
        return PageRows(rows=rows[request.page])

    client = FakeClient(handler)
    (table,) = extract_tables(path, client, recheck=False)
    asked = "\n".join(p for p in client.requests[2].parts if isinstance(p, str))
    assert "Amount" not in asked
    (row,) = table.records()[1:]
    assert row["Amount"] == "" and row["Amount__grounding"] == "not_on_page"
    assert table.flagged() == []


def test_a_garbled_text_layer_is_rejected_before_any_request():
    client = replay(["A"], {1: [{"A": "x"}]})
    with pytest.raises(TextLayerError, match="garbled"):
        extract_tables(DATA / "senate_expenditures_garbled.pdf", client)
    assert client.requests == []


def test_a_pdf_with_no_text_is_rejected_before_any_request(make_pdf):
    client = replay(["A"], {1: [{"A": "x"}]})
    with pytest.raises(TextLayerError, match="no text layer"):
        extract_tables(make_pdf([[]]), client)
    assert client.requests == []


def test_the_text_layer_check_has_no_off_switch():
    parameters = set(inspect.signature(public_extract_tables).parameters)
    assert parameters == {
        "pdf",
        "model",
        "cache_dir",
        "max_requests",
        "model_settings",
        "discovery_pages",
        "recheck",
        "ocr",  # chooses whether bad pages are OCR'd; the text-layer check itself has no switch
        "merge_reworded",  # spec 007: the merge step's switch
    }
    assert set(inspect.signature(extract_tables_async).parameters) == parameters
    assert set(inspect.signature(run_pipeline).parameters) == {
        "pdf",
        "client",
        "discovery_pages",
        "recheck",
        "merge_reworded",
        "ocr",
        "ocr_config",
        "cache_dir",
    }
