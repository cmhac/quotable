"""extract_tables: several tables in one document, on different pages and on the same page."""

import pytest

from quotable import BudgetExceededError, ExtractionError
from quotable.llm.answers import CellRecheck, Column, PageRecheck, PageRows, PageTables, TableInfo
from quotable.llm.client import CachedClient, Image
from quotable.steps.discover import DISCOVER_PROMPT
from quotable.steps.extract import EXTRACT_PROMPT, MULTI_TABLE_SENTENCE
from tests.conftest import FakeClient, extract_tables, window_of

HEADER_B = [(72, 60, "Name"), (182, 60, "Amount"), (292, 60, "Note")]
A_ROWS = [{"Item": "Alpha", "Amount": "$100"}, {"Item": "Beta", "Amount": "$250"}]
B_ROWS = [
    {"Name": "Gamma", "Amount": "$100", "Note": "red"},
    {"Name": "Delta", "Amount": "$900", "Note": "blue"},
]
# Two stacked tables on one page; they share the word "Amount" and the amount "$100".
STACKED_A = [
    (72, 70, "Item"),
    (200, 70, "Amount"),
    (72, 90, "Alpha"),
    (200, 90, "$100"),
    (72, 104, "Beta"),
    (200, 104, "$250"),
]
STACKED_B = [
    (72, 150, "Name"),
    (200, 150, "Amount"),
    (300, 150, "Note"),
    (72, 170, "Gamma"),
    (200, 170, "$100"),
    (300, 170, "red"),
    (72, 184, "Delta"),
    (200, 184, "$900"),
    (300, 184, "blue"),
]


def info(columns, label, first="", last=""):
    cols = [Column(name=c, description="") for c in columns]
    return TableInfo(label=label, columns=cols, first_row=first, last_row=last)


def model(discovery, rows, recheck=None):
    """
    A fake model. ``discovery`` is a list of windows' answers (one list of tables per page);
    ``rows`` maps (first column name, page) to the rows for the extract request.
    """
    pages = iter(discovery)

    def handler(request):
        if request.stage == "schema":
            return window_of(request, [PageTables(tables=t) for t in next(pages)])
        if request.stage == "extract":
            first_column = request.parts[0].splitlines()[1].split(":")[0].removeprefix("- ")
            return PageRows(rows=[dict(r) for r in rows[first_column, request.page]])
        assert recheck is not None, "unexpected recheck request"
        return recheck(request)

    return FakeClient(handler)


def texts(request):
    return "\n".join(p for p in request.parts if isinstance(p, str))


def stacked_client(a_rows=A_ROWS, b_rows=B_ROWS, first_b="Gamma $100 red", recheck=None):
    tables = [
        info(["Item", "Amount"], "A", "Alpha $100", "Beta $250"),
        info(["Name", "Amount", "Note"], "B", first_b, "Delta $900 blue"),
    ]
    return model([[tables]], {("Item", 1): a_rows, ("Name", 1): b_rows}, recheck)


def test_tables_on_different_pages_come_back_as_separate_tables(make_pdf):
    path = make_pdf(
        [[(72, 60, "Item"), (182, 60, "Amount"), (72, 90, "Alpha"), (182, 90, "$100")], HEADER_B]
    )
    a, b = info(["Item", "Amount"], "A"), info(["Name", "Amount", "Note"], "B")
    rows = {("Item", 1): A_ROWS[:1], ("Name", 2): []}
    client = model([[[a], [b]]], rows)
    first, second = extract_tables(path, client, recheck=False)
    assert (first.label, second.label) == ("A", "B")
    assert [r.page for r in first.pages] == [1] and [r.page for r in second.pages] == [2]
    assert set(first.layers) == set(first.grounded) == {1}
    assert set(second.layers) == set(second.grounded) == {2}
    assert first.columns == ["Item", "Amount"] and second.columns == ["Name", "Amount", "Note"]


def test_a_page_without_a_header_joins_its_table_with_an_inherited_layout(make_pdf):
    page2 = [(72, 90, "Gamma"), (182, 90, "$100"), (292, 90, "red")]
    path = make_pdf([[*HEADER_B, (72, 90, "Delta"), (182, 90, "$900"), (292, 90, "blue")], page2])
    b = info(["Name", "Amount", "Note"], "B")
    client = model([[[b], [b]]], {("Name", 1): B_ROWS[1:], ("Name", 2): B_ROWS[:1]})
    (table,) = extract_tables(path, client, recheck=False)
    assert [r.page for r in table.pages] == [1, 2]
    assert [lay.source for lay in table.layouts] == ["header", "inherited"]


def test_a_document_with_no_table_raises(make_pdf):
    client = model([[[], []]], {})
    with pytest.raises(ExtractionError, match="no table"):
        extract_tables(make_pdf([[(72, 60, "Hello")], [(72, 60, "World")]]), client)


def test_discovery_requests_count_toward_the_request_cap(make_pdf, tmp_path):
    path = make_pdf([[(72, 60, "Item")], [(72, 60, "Item")]])
    a = info(["Item"], "A")
    client = CachedClient(model([[[a]], [[a]]], {}), tmp_path / "cache", max_requests=1)
    with pytest.raises(BudgetExceededError):
        extract_tables(path, client, discovery_pages=1, recheck=False)
    assert client.new_requests == 1


def test_each_table_on_a_shared_page_is_checked_against_its_own_text_only(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    a, b = extract_tables(path, stacked_client(), recheck=False)
    assert [w.text for w in a.layers[1].words] == ["Alpha", "$100", "Beta", "$250"]
    assert "Delta" not in [w.text for w in a.layers[1].words]
    assert [w.text for w in b.layers[1].words][:3] == ["Gamma", "$100", "red"]
    assert a.flagged() == [] and b.flagged() == []
    assert a.position["misplaced"] == 0 and b.position["misplaced"] == 0


def test_a_value_that_only_the_other_table_prints_is_ungrounded(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    wrong = [{"Item": "Alpha", "Amount": "$100"}, {"Item": "Delta", "Amount": "$250"}]
    a, _ = extract_tables(path, stacked_client(a_rows=wrong), recheck=False)
    assert [(f.row, f.column, f.status) for f in a.flagged()] == [(2, "Item", "ungrounded")]


def test_extract_requests_name_the_other_tables_only_on_shared_pages(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    client = stacked_client()
    extract_tables(path, client, recheck=False)
    requests = [r for r in client.requests if r.stage == "extract"]
    assert len(requests) == 2
    for request, other in zip(requests, ["B: Name, Amount, Note", "A: Item, Amount"], strict=True):
        assert request.instructions == f"{EXTRACT_PROMPT} {MULTI_TABLE_SENTENCE}"
        assert "Other tables on this page:" in texts(request) and other in texts(request)

    single = make_pdf([HEADER_B])
    client = model([[[info(["Name", "Amount", "Note"], "B")]]], {("Name", 1): []})
    extract_tables(single, client, recheck=False)
    request = client.requests[-1]
    assert request.instructions == EXTRACT_PROMPT
    assert "Other tables" not in texts(request)
    assert sum(isinstance(p, Image) for p in request.parts) == 1


def test_the_recheck_of_a_table_sees_only_its_own_band_of_text(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    wrong = [dict(B_ROWS[0], Note="Zzzz"), B_ROWS[1]]

    def recheck(request):
        return PageRecheck(cells=[CellRecheck(row=1, column="Note", value="red")])

    client = stacked_client(b_rows=wrong, recheck=recheck)
    _, b = extract_tables(path, client)
    (request,) = [r for r in client.requests if r.stage == "recheck"]
    text = texts(request)
    assert "Gamma $100 red" in text and "Delta $900 blue" in text
    assert "Alpha" not in text and "Beta" not in text and "Quarterly" not in text
    assert b.page_rows(1)[0].values["Note"] == "red"


def test_a_band_that_cannot_be_isolated_fails_before_any_extract_request(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    client = stacked_client(first_b="Omega 1")
    with pytest.raises(ExtractionError, match=r"page 1: table 'B': its first row was not found"):
        extract_tables(path, client)
    assert client.stages() == ["schema"]


def test_the_discovery_prompt_is_what_the_model_is_given(make_pdf):
    path = make_pdf([STACKED_A + STACKED_B])
    client = stacked_client()
    extract_tables(path, client, recheck=False)
    assert client.requests[0].instructions == DISCOVER_PROMPT
