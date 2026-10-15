import copy
import inspect
import json

import pytest

from gridkey import (
    ExtractionError,
    TextLayerError,
    extract_table,
    extract_table_async,
)
from gridkey.llm import Image
from gridkey.models import Column, PageRows, TableSchema
from tests.conftest import DATA, FakeClient, load_sample, replay


def test_the_sample_documents_come_back_as_the_rows_the_model_gave(sample):
    client = replay(sample["columns"], sample["pages"])
    table = extract_table(sample["pdf"], client, recheck=False)
    assert table.columns == sample["columns"]
    for number, rows in sample["pages"].items():
        assert [r.values for r in table.page_rows(number)] == rows


def test_it_asks_for_the_schema_once_then_for_each_page(sample):
    client = replay(sample["columns"], sample["pages"])
    extract_table(sample["pdf"], client, recheck=False)
    assert client.stages() == ["schema"] + ["extract"] * len(sample["pages"])


def test_schema_discovery_sees_only_the_first_pages():
    four_pages = load_sample("fy22_ag_house_original")
    client = replay(four_pages["columns"], four_pages["pages"])
    extract_table(four_pages["pdf"], client, schema_pages=2, recheck=False)
    images = [p for p in client.requests[0].parts if isinstance(p, Image)]
    assert len(images) == 2


def test_each_page_request_has_the_columns_and_that_pages_image(sample):
    client = replay(sample["columns"], sample["pages"])
    extract_table(sample["pdf"], client, recheck=False)
    request = client.requests[1]
    assert request.page == 1
    assert sum(isinstance(p, Image) for p in request.parts) == 1
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    assert all(column in text for column in sample["columns"])


def test_every_cell_carries_a_grounding_status_and_coverage(sample):
    client = replay(sample["columns"], sample["pages"])
    table = extract_table(sample["pdf"], client, recheck=False)
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
    table = extract_table(DATA / "fy22_milcon_house_original.pdf", client, recheck=False)
    assert table.flagged() == []
    assert {r["grounding_status"] for r in table.records()} == {"exact"}


def test_a_value_moved_to_another_row_is_caught_by_the_position_check():
    recorded = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
    rows = copy.deepcopy(recorded["pages"]["1"])
    rows[1]["Project"], rows[8]["Project"] = rows[8]["Project"], rows[1]["Project"]
    client = replay(recorded["columns"], {1: rows})
    table = extract_table(DATA / "fy22_milcon_house_original.pdf", client, recheck=False)
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
            return TableSchema(
                columns=[Column(name="A", description=""), Column(name="B", description="")]
            )
        return next(answers)

    client = FakeClient(handler)
    table = extract_table(path, client, recheck=False)
    assert [r.values for r in table.page_rows(1)] == [{"A": "Alpha", "B": "Beta"}]
    retry = client.requests[-1]
    assert any("Extra" in p for p in retry.parts if isinstance(p, str))  # the problem is named


def test_rows_that_are_still_wrong_after_the_retry_abort(make_pdf):
    path = make_pdf([[(72, 60, "Alpha")]])

    def handler(request):
        if request.stage == "schema":
            return TableSchema(columns=[Column(name="A", description="")])
        return PageRows(rows=[{"Nope": "Alpha"}])

    with pytest.raises(ExtractionError, match="page 1"):
        extract_table(path, FakeClient(handler), recheck=False)


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
            return TableSchema(columns=[Column(name=c, description="") for c in header])
        return PageRows(rows=rows[request.page])

    client = FakeClient(handler)
    table = extract_table(path, client, recheck=False)
    asked = "\n".join(p for p in client.requests[2].parts if isinstance(p, str))
    assert "Amount" not in asked
    (row,) = table.records()[1:]
    assert row["Amount"] == "" and row["Amount__grounding"] == "not_on_page"
    assert table.flagged() == []


def test_a_garbled_text_layer_is_rejected_before_any_request():
    client = replay(["A"], {1: [{"A": "x"}]})
    with pytest.raises(TextLayerError, match="garbled"):
        extract_table(DATA / "senate_expenditures_garbled.pdf", client)
    assert client.requests == []


def test_a_pdf_with_no_text_is_rejected_before_any_request(make_pdf):
    client = replay(["A"], {1: [{"A": "x"}]})
    with pytest.raises(TextLayerError, match="no text layer"):
        extract_table(make_pdf([[]]), client)
    assert client.requests == []


def test_the_text_layer_check_has_no_off_switch():
    parameters = set(inspect.signature(extract_table).parameters)
    assert parameters == {"pdf", "client", "schema_pages", "recheck"}
    assert set(inspect.signature(extract_table_async).parameters) == parameters
