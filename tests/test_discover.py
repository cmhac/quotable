import asyncio

import pytest

from quotable.discover import (
    CARRY_PROMPT,
    DISCOVER_PROMPT,
    DISCOVERY_PAGES,
    PageCountError,
    discover,
    match_pages,
    merge,
    signature,
    validate_found,
)
from quotable.llm import Image, Request
from quotable.models import Column, PageTables, TableInfo, WindowTables
from quotable.schema import ExtractionError


def info(columns, label="t", first="", last=""):
    return TableInfo(
        label=label,
        columns=[Column(name=c, description="") for c in columns],
        first_row=first,
        last_row=last,
    )


def window(*pages):
    """A window answer: each argument is the list of tables on one page."""
    return WindowTables(pages=[PageTables(tables=list(tables)) for tables in pages])


class Recorder:
    """A fake model that answers from a list and records when each request starts and ends."""

    identity = "fake"

    def __init__(self, answers):
        self.answers = iter(answers)
        self.requests: list[Request] = []
        self.events: list[str] = []

    async def ask(self, request):
        self.requests.append(request)
        self.events.append(f"start {len(self.requests)}")
        await asyncio.sleep(0)
        self.events.append(f"end {len(self.requests)}")
        return next(self.answers)


def images(n):
    return [bytes([i]) for i in range(n)]


def n_images(request):
    return sum(isinstance(p, Image) for p in request.parts)


def texts(request):
    return "\n".join(p for p in request.parts if isinstance(p, str))


def run(client, count, **kwargs):
    return asyncio.run(discover(images(count), client, **kwargs))


def test_signature_ignores_case_and_punctuation_and_keeps_order():
    assert signature(["Requestor(s)", "Amount ($)"]) == signature(["REQUESTOR S", "amount"])
    assert signature(["A", "B"]) != signature(["B", "A"])


def test_match_pages_goes_by_order_not_by_the_numbers_the_model_wrote():
    answer = window([info(["A"])], [info(["B"])])
    assert [len(p.tables) for p in match_pages(answer, [7, 8])] == [1, 1]


def test_match_pages_rejects_the_wrong_number_of_entries():
    with pytest.raises(PageCountError, match="expected one entry per page image"):
        match_pages(window([info(["A"])]), [1, 2])


def test_the_same_columns_on_two_pages_are_one_table():
    found = []
    merge(found, 1, [info(["Agency", "Amount"], "first", "a", "b")])
    merge(found, 2, [info(["AGENCY", "amount"], "second", "c", "d")])
    (table,) = found
    assert table.label == "first"
    assert table.columns == ["Agency", "Amount"]
    assert table.rows == {1: ("a", "b"), 2: ("c", "d")}


def test_different_columns_are_two_tables_in_order_of_first_appearance():
    found = []
    merge(found, 1, [info(["A", "B"], "summary"), info(["A", "B", "C"], "detail")])
    merge(found, 2, [info(["A", "B", "C"], "detail")])
    assert [(f.label, f.pages) for f in found] == [("summary", [1]), ("detail", [1, 2])]


def test_a_table_listed_twice_on_a_page_covers_both_pieces():
    found = []
    merge(found, 1, [info(["A"], "t", "top", "mid"), info(["A"], "t", "next", "bottom")])
    assert found[0].rows == {1: ("top", "bottom")}


def test_unusable_discovery_results_raise():
    with pytest.raises(ExtractionError, match="no table"):
        validate_found([])
    for columns, problem in [([], "no columns"), (["A", " "], "blank"), (["A", "A"], "duplicate")]:
        found = []
        merge(found, 1, [info(columns)])
        with pytest.raises(ExtractionError, match=problem):
            validate_found(found)


def test_a_page_with_no_table_is_fine():
    client = Recorder([window([], [info(["A"])])])
    (table,) = run(client, 2)
    assert table.pages == [2]


def test_the_default_window_is_four_pages_in_one_request():
    assert DISCOVERY_PAGES == 4
    client = Recorder([window(*[[info(["A"])]] * 4)])
    run(client, 4)
    assert len(client.requests) == 1 and n_images(client.requests[0]) == 4


def test_windows_are_asked_one_after_the_other_with_the_tables_found_so_far():
    client = Recorder(
        [
            window([info(["A", "B"], "first")], [info(["A", "B"], "first")]),
            window([info(["A", "B"], "first")], [info(["A", "B"], "first")]),
        ]
    )
    (table,) = run(client, 4, discovery_pages=2)
    assert [n_images(r) for r in client.requests] == [2, 2]
    assert client.events == ["start 1", "end 1", "start 2", "end 2"]
    assert "Known tables" not in texts(client.requests[0])
    second = texts(client.requests[1])
    assert "Known tables" in second and '"A", "B"' in second and "pages [1, 2]" in second
    assert client.requests[0].instructions == DISCOVER_PROMPT
    assert client.requests[1].instructions == DISCOVER_PROMPT + CARRY_PROMPT
    assert table.pages == [1, 2, 3, 4]


def test_a_page_without_a_header_joins_the_table_it_continues():
    client = Recorder(
        [window([info(["Agency", "Account"])]), window([info(["Agency", "Account"])])]
    )
    (table,) = run(client, 2, discovery_pages=1)
    assert table.pages == [1, 2]


def test_the_prompts_say_what_was_tested():
    for phrase in ["EVERY distinct table", "no separators and no placeholders", "last row"]:
        assert phrase in DISCOVER_PROMPT
    for phrase in ["WITHOUT printing its column header again", "Never invent columns"]:
        assert phrase in CARRY_PROMPT


def test_a_count_mismatch_is_retried_once():
    client = Recorder([window([info(["A"])]), window([info(["A"])], [info(["A"])])])
    (table,) = run(client, 2)
    assert len(client.requests) == 2 and table.pages == [1, 2]
    assert "expected one entry per page image (2), got 1" in texts(client.requests[1])


def test_a_count_mismatch_that_persists_raises():
    client = Recorder([window([info(["A"])])] * 2)
    with pytest.raises(ExtractionError, match="still invalid"):
        run(client, 2)


def test_a_window_smaller_than_one_page_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        run(Recorder([]), 1, discovery_pages=0)
