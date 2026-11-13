import asyncio

import pytest

from quotable.errors import ExtractionError
from quotable.llm.answers import (
    Column,
    ExtraValue,
    PageTables,
    PageWithExtras,
    TableInfo,
    WindowTables,
    WindowWithExtras,
)
from quotable.llm.client import Image, Request, request_key
from quotable.steps.discover import (
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
from quotable.steps.extra_fields import ExtraField, ExtraFields, FieldGroup
from tests.conftest import DATA


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
    return asyncio.run(discover(images(count), client, **kwargs)).tables


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


def test_no_table_in_the_document_raises():
    with pytest.raises(ExtractionError, match="no table"):
        validate_found([])


def test_an_unusable_table_is_kept_as_a_failed_one_with_the_problem():
    for columns, problem in [([], "no columns"), (["A", " "], "blank"), (["A", "A"], "duplicate")]:
        found = []
        merge(found, 1, [info(columns, "bad")])
        merge(found, 2, [info(columns, "bad")])
        (table,) = found
        assert table.failed and table.pages == [1, 2] and table.label == "bad"
        assert problem in " ".join(table.problems)
        validate_found(found)  # a failed table is not a reason to raise


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


RECORDED = DATA / "discovery_empty_columns"


@pytest.mark.parametrize("window_pages", ["357_360", "889_892"])
def test_a_recorded_answer_with_no_columns_is_retried_with_the_problem_named(window_pages):
    # the model's real answers to these windows of the Trump annual report: tables with
    # `columns: []` (copied from the request cache); the second answer is made up here
    bad = WindowTables.model_validate_json((RECORDED / f"answer_{window_pages}.json").read_text())
    assert all(not t.columns for p in bad.pages for t in p.tables)
    good = bad.model_copy(deep=True)
    for page in good.pages:
        for table in page.tables:
            table.columns = [Column(name="A", description=""), Column(name="B", description="")]
    client = Recorder([bad, good])

    (table,) = run(client, 4)

    assert table.columns == ["A", "B"] and table.pages == [1, 2, 3, 4]
    assert len(client.requests) == 2
    retry = texts(client.requests[1])
    assert "page 1" in retry and "no columns" in retry and "header" in retry


def window_answers(first, last):
    return WindowTables.model_validate_json((RECORDED / f"answer_{first}_{last}.json").read_text())


def test_an_answer_with_no_columns_that_persists_fails_that_table_only():
    both = window([info(["A", "B"], "good"), info([], "bad")])
    client = Recorder([both, both])
    good, bad = run(client, 1)
    assert len(client.requests) == 2
    assert not good.failed and good.columns == ["A", "B"]
    assert bad.failed and bad.label == "bad" and bad.pages == [1]
    assert "no columns" in " ".join(bad.problems)


def test_a_window_level_problem_still_raises_when_it_persists():
    client = Recorder([window([info(["A"])])] * 2)  # one entry for two pages
    with pytest.raises(ExtractionError, match="still invalid"):
        run(client, 2)
    bad_table_too = Recorder([window([info([], "bad")])] * 2)  # and the table is unusable as well
    with pytest.raises(ExtractionError, match="expected one entry per page image"):
        run(bad_table_too, 2)


def test_failed_entries_are_grouped_by_label_and_never_with_a_sound_table():
    answer = window([info([], "one"), info(["A"], "sound")], [info([], "one"), info([], "two")])
    client = Recorder([answer, answer])
    one, sound, two = run(client, 2)
    assert (one.label, one.pages, one.failed) == ("one", [1, 2], True)
    assert (sound.label, sound.pages, sound.failed) == ("sound", [1], False)
    assert (two.label, two.pages, two.failed) == ("two", [2], True)
    assert signature(one.columns) != signature(sound.columns)


def test_a_failed_table_is_not_shown_to_the_next_window():
    bad = window([info([], "bad")])
    client = Recorder([bad, bad, window([info(["A"], "good")]), window([info(["A"], "good")])])
    run(client, 3, discovery_pages=1)
    # nothing sound is known after the failed first window: no known-tables part, no carry prompt
    assert client.requests[2].instructions == DISCOVER_PROMPT
    assert "Known tables" not in texts(client.requests[2])
    # once a sound table is known, the failed one is still left out of the list
    known = texts(client.requests[3])
    assert "Known tables" in known and '"A"' in known
    assert "columns: []" not in known and "pages [1]" not in known
    assert client.requests[3].instructions == DISCOVER_PROMPT + CARRY_PROMPT


def test_the_four_recorded_windows_of_the_failed_run_end_as_four_failed_tables():
    # The model's own answers to pages 357-360, 421-424, 545-548 and 889-892 of the Trump annual
    # report (copied from the request cache of the failed run): tables with no columns. Each is
    # given twice, as the answer and as the answer to the retry. No model is called.
    recorded = [window_answers(a, b) for a, b in [(357, 360), (421, 424), (545, 548), (889, 892)]]
    client = Recorder([answer for each in recorded for answer in (each, each)])
    tables = run(client, 16)
    assert len(client.requests) == 8
    assert all(t.failed for t in tables) and len(tables) == 4
    assert [t.pages for t in tables] == [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10, 11, 12],
        [13, 14, 15, 16],
    ]
    assert [t.label for t in tables] == [
        "Investment Account #6 transactions",
        "Investment Account #7 transactions",
        "Investment Account #7 Transactions",
        "Trademark registrations",
    ]


def test_a_window_smaller_than_one_page_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        run(Recorder([]), 1, discovery_pages=0)


# --- extra fields (spec 010) ------------------------------------------------------------------
# keys of the two discovery requests for six one-byte images (windows of four and two pages),
# computed with the code before extra fields existed: they must never change
KEY_FIRST_WINDOW = "1746eb132258c08b5fe69ee2a36ba4a5b043160575ade368b18e5ae448e9c24c"
KEY_SECOND_WINDOW = "5ac43b8e162336389c176061dc76c319bee6b7567f0fcb71b034ea4bc9d023e8"

DIVISION = ExtraField("division", "The division named at the top left")
YEAR = ExtraField("year", "The funding year")


def page_with(names_values, tables=None):
    return PageWithExtras(
        tables=tables if tables is not None else [info(["A"], "t", "x", "y")],
        extras=[ExtraValue(name=n, value=v) for n, v in names_values.items()],
    )


class Script:
    """A fake model that answers each request with ``answer(request, n)``."""

    identity = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.requests: list[Request] = []

    async def ask(self, request):
        self.requests.append(request)
        return self.answer(request, len(self.requests))


def run_extra(client, count, extra_fields, **kwargs):
    return asyncio.run(discover(images(count), client, extra_fields=extra_fields, **kwargs))


def test_without_extra_fields_the_requests_are_what_they_always_were():
    def answer(request, _n):
        return window(*[[info(["A"], "t", "x", "y")]] * n_images(request))

    client = Script(answer)
    asyncio.run(discover(images(6), client))
    first, second = client.requests
    assert first.instructions == DISCOVER_PROMPT
    assert first.output_type is WindowTables
    assert second.instructions == DISCOVER_PROMPT + CARRY_PROMPT
    assert request_key("fake", first) == KEY_FIRST_WINDOW
    assert request_key("fake", second) == KEY_SECOND_WINDOW


def test_extra_fields_none_is_the_same_as_leaving_it_out():
    def answer(request, _n):
        return window(*[[info(["A"], "t", "x", "y")]] * n_images(request))

    left, right = Script(answer), Script(answer)
    asyncio.run(discover(images(6), left))
    asyncio.run(discover(images(6), right, extra_fields=None))
    assert [request_key("fake", r) for r in left.requests] == [
        request_key("fake", r) for r in right.requests
    ]


def test_the_fields_are_asked_for_and_returned_per_page():
    def answer(request, _n):
        count = n_images(request)
        return WindowWithExtras(
            pages=[
                page_with(
                    {"division": "Roads" if i == 0 else None, "year": "2018" if i == 0 else ""}
                )
                for i in range(count)
            ]
        )

    client = Script(answer)
    result = run_extra(client, 6, ExtraFields([DIVISION, YEAR]))
    assert result.extras == {
        1: {"division": "Roads", "year": "2018"},
        2: {"division": None, "year": None},
        3: {"division": None, "year": None},
        4: {"division": None, "year": None},
        5: {"division": "Roads", "year": "2018"},
        6: {"division": None, "year": None},
    }
    assert result.tables[0].pages == [1, 2, 3, 4, 5, 6]
    first = client.requests[0]
    assert first.output_type is WindowWithExtras
    assert first.instructions.startswith(DISCOVER_PROMPT)
    assert "division: The division named at the top left" in first.instructions
    assert "year: The funding year" in first.instructions


def test_the_callers_text_is_in_the_prompt():
    def answer(request, _n):
        return WindowWithExtras(pages=[page_with({"division": None})] * n_images(request))

    client = Script(answer)
    run_extra(client, 1, ExtraFields([DIVISION], prompt="Blocks are at the top left."))
    assert "Blocks are at the top left." in client.requests[0].instructions


def test_groups_are_listed_with_their_fields_and_do_not_change_the_output_type():
    def answer(request, _n):
        return WindowWithExtras(
            pages=[page_with({"division": "A", "year": "1"})] * n_images(request)
        )

    grouped, flat = Script(answer), Script(answer)
    group = FieldGroup("heading", "Division and year, printed together", [DIVISION, YEAR])
    run_extra(grouped, 1, ExtraFields([group]))
    run_extra(flat, 1, ExtraFields([DIVISION, YEAR]))
    text = grouped.requests[0].instructions
    assert "heading: Division and year, printed together" in text
    assert "  division: The division named at the top left" in text
    assert "  year: The funding year" in text
    assert grouped.requests[0].output_type is flat.requests[0].output_type


def test_known_tables_text_never_carries_a_field_value():
    def answer(request, _n):
        return WindowWithExtras(pages=[page_with({"division": "SECRET-VALUE"})] * n_images(request))

    client = Script(answer)
    run_extra(client, 6, ExtraFields([DIVISION]))
    assert "SECRET-VALUE" not in texts(client.requests[1])


def test_a_wrong_set_of_names_is_sent_back_once_with_the_problem():
    def answer(request, n):
        names = {"division": "A"} if n > 1 else {"wrong": "A"}
        return WindowWithExtras(pages=[page_with(names)] * n_images(request))

    client = Script(answer)
    result = run_extra(client, 1, ExtraFields([DIVISION]))
    assert len(client.requests) == 2
    assert "division" in texts(client.requests[1])
    assert "wrong" in texts(client.requests[1])
    assert result.extras == {1: {"division": "A"}}


def test_a_name_asked_for_twice_or_missing_is_a_problem():
    def answer(request, _n):
        entry = PageWithExtras(
            tables=[info(["A"])], extras=[ExtraValue(name="division", value="A")] * 2
        )
        return WindowWithExtras(pages=[entry] * n_images(request))

    with pytest.raises(ExtractionError, match="still invalid"):
        run_extra(Script(answer), 1, ExtraFields([DIVISION]))


def test_the_page_count_and_the_names_share_one_retry():
    def answer(request, n):
        if n == 1:  # one page too few, and a wrong name
            return WindowWithExtras(pages=[page_with({"wrong": "A"})])
        return WindowWithExtras(pages=[page_with({"division": "A"})] * n_images(request))

    client = Script(answer)
    run_extra(client, 2, ExtraFields([DIVISION]))
    assert len(client.requests) == 2
    retry = texts(client.requests[1])
    assert "expected one entry per page image" in retry
    assert "wrong" in retry


def test_a_second_failure_raises():
    def answer(request, _n):
        return WindowWithExtras(pages=[page_with({"wrong": "A"})] * n_images(request))

    client = Script(answer)
    with pytest.raises(ExtractionError, match="still invalid after one retry"):
        run_extra(client, 1, ExtraFields([DIVISION]))
    assert len(client.requests) == 2
