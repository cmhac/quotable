import asyncio
import copy
import json

import pymupdf

from quotable.llm.answers import CellRecheck, PageRecheck
from quotable.llm.client import Image
from quotable.llm.images import TODAY
from quotable.steps.extract import render_page
from quotable.steps.recheck import RECHECK_PROMPT, _regrounded, recheck_table
from quotable.text.layer import load_layer
from tests.conftest import DATA, FakeClient, OverlapClient, extract_tables, replay
from tests.table_builder import build_table

PDF = DATA / "fy22_milcon_house_original.pdf"
RECORDED = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
COLUMNS = RECORDED["columns"]
TRUTH = {int(p): rows for p, rows in RECORDED["pages"].items()}
ROW = 5  # 1-based row whose (long) Project the tests corrupt
TRUE_VALUE = TRUTH[1][ROW - 1]["Project"]


def _with_typo():
    """The recorded rows with one wrong word in one Project cell."""
    pages = copy.deepcopy(TRUTH)
    words = TRUE_VALUE.split()
    words[1] = "Zzyzx"
    pages[1][ROW - 1]["Project"] = " ".join(words)
    return pages


def _client(answer_value, *, row=ROW, column="Project"):
    base = replay(COLUMNS, _with_typo())
    schema_or_extract = base.handler

    def handler(request):
        if request.stage == "recheck":
            return PageRecheck(cells=[CellRecheck(row=row, column=column, value=answer_value)])
        return schema_or_extract(request)

    return FakeClient(handler)


def _cell(table):
    return table.page_rows(1)[ROW - 1].cells["Project"], table.page_rows(1)[ROW - 1].values[
        "Project"
    ]


def test_the_typo_is_flagged_before_the_recheck():
    (table,) = extract_tables(PDF, _client(TRUE_VALUE), recheck=False)
    assert [(f.row, f.column, f.status) for f in table.flagged()] == [(ROW, "Project", "fuzzy")]


def test_a_flagged_cell_is_sent_back_with_its_image_row_and_reason():
    client = _client(TRUE_VALUE)
    extract_tables(PDF, client)
    assert client.stages() == ["schema", "extract", "recheck"]
    request = client.requests[-1]
    assert request.page == 1
    assert sum(isinstance(p, Image) for p in request.parts) == 1
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    assert "Zzyzx" in text  # the previous value
    assert "only a partial match" in text  # why it was flagged
    assert f"row {ROW}" in text and "Project" in text


def test_the_whole_text_layer_of_the_page_is_sent_with_the_recheck():
    client = _client(TRUE_VALUE)
    extract_tables(PDF, client)
    request = client.requests[-1]
    with pymupdf.open(PDF) as document:
        lines = load_layer(document[0]).lines()
    header = "Text layer of the whole page, one visual line per line:\n"
    sent = [p for p in request.parts if isinstance(p, str) and p.startswith(header)]
    assert len(sent) == 1
    assert sent[0].removeprefix(header).split("\n") == lines
    # words of rows that were not flagged are there too
    other = TRUTH[1][0]["Project"].split()[0]
    assert other in sent[0]
    # the text part sits before the list of cells to re-check
    texts = [p for p in request.parts if isinstance(p, str)]
    assert texts[-1].startswith("Cells to re-check:")
    assert texts.index(sent[0]) < len(texts) - 1
    assert [s.stage for s in client.requests].count("recheck") == 1


def test_the_prompt_makes_the_text_layer_the_reference():
    assert "The text layer is the reference" in RECHECK_PROMPT
    assert "copied character for character" in RECHECK_PROMPT
    assert "NOT a reason to keep your own value" in RECHECK_PROMPT
    assert "no text for that cell" in RECHECK_PROMPT
    client = _client(TRUE_VALUE)
    extract_tables(PDF, client)
    assert client.requests[-1].instructions == RECHECK_PROMPT


def test_an_answer_that_grounds_better_is_accepted():
    (table,) = extract_tables(PDF, _client(TRUE_VALUE))
    cell, value = _cell(table)
    assert value == TRUE_VALUE and cell.status == "exact"
    assert table.flagged() == []
    (proposal,) = table.proposals
    assert (proposal.outcome, proposal.original) == (
        "accepted",
        _with_typo()[1][ROW - 1]["Project"],
    )
    record = {k: str(v) for k, v in table.records()[ROW - 1].items()}
    assert "Project" in record["recheck_changes"] and "Zzyzx" in record["recheck_changes"]


def test_an_answer_that_does_not_ground_better_keeps_the_original():
    other_typo = TRUE_VALUE.split()[0] + " Qqq Qqq"
    (table,) = extract_tables(PDF, _client(other_typo))
    cell, value = _cell(table)
    assert "Zzyzx" in value and cell.status == "fuzzy"
    assert [p.outcome for p in table.proposals] == ["not_improved"]


def test_a_blank_answer_is_ignored():
    (table,) = extract_tables(PDF, _client(""))
    assert "Zzyzx" in _cell(table)[1]
    assert [p.outcome for p in table.proposals] == ["blank_ignored"]


def test_an_answer_with_the_same_tokens_is_not_applied():
    same = _with_typo()[1][ROW - 1]["Project"].upper() + "."
    (table,) = extract_tables(PDF, _client(same))
    assert "Zzyzx" in _cell(table)[1]
    assert [p.outcome for p in table.proposals] == ["same_tokens"]


def test_answers_for_cells_that_were_not_listed_are_ignored():
    other = TRUTH[1][0]["Account"] + " changed"
    (table,) = extract_tables(PDF, _client(other, row=1, column="Account"))
    assert table.page_rows(1)[0].values["Account"] == TRUTH[1][0]["Account"]
    assert table.proposals == []


def test_the_rechecked_table_carries_the_areas_of_its_pages():
    (table,) = extract_tables(PDF, _client(TRUE_VALUE))
    assert [p.outcome for p in table.proposals] == ["accepted"]
    page = table.grounded[1]
    assert sorted(page.row_windows) == list(range(len(page.rows)))
    assert page.column_ranges


def test_a_clean_document_is_never_rechecked():
    client = replay(COLUMNS, TRUTH)
    (table,) = extract_tables(PDF, client)
    assert client.stages() == ["schema", "extract"]
    assert table.proposals == []


# --- the run's limit on requests in flight (spec 015) ------------------------------------------
PAGES = 20
RIGHT = "Harbor dredging and channel repair"
WRONG = "Harbor dredging and channal repair"


def _long_table(tmp_path, name="t"):
    """A 20-page table with a misspelled Project cell on every page, and the PDF's path."""
    rows = [[{"Name": f"Alpha {p}", "Project": RIGHT}] for p in range(PAGES)]
    table = build_table(tmp_path, ["Name", "Project"], rows, xs=[72, 250], name=name)
    table = _regrounded(table, {(p, 1, "Project"): WRONG for p in range(1, PAGES + 1)})
    assert len(table.flagged()) == PAGES
    return table, tmp_path / f"{name}.pdf"


def _answering(value):
    return FakeClient(
        lambda request: PageRecheck(cells=[CellRecheck(row=1, column="Project", value=value)])
    )


def test_the_recheck_keeps_to_the_limit_it_is_given(tmp_path):
    table, pdf = _long_table(tmp_path)
    client = OverlapClient(_answering(RIGHT))
    out = asyncio.run(recheck_table(table, pdf, client, TODAY, asyncio.Semaphore(4)))
    assert client.stages() == ["recheck"] * PAGES
    assert client.most == 4
    assert [p.outcome for p in out.proposals] == ["accepted"] * PAGES


def test_the_recheck_sends_the_same_page_image_as_before(tmp_path):
    table, pdf = _long_table(tmp_path)
    client = _answering(RIGHT)
    asyncio.run(recheck_table(table, pdf, client, TODAY, asyncio.Semaphore(4)))
    for request in client.requests:
        (image,) = (p for p in request.parts if isinstance(p, Image))
        assert image.png == render_page(pdf, request.page, TODAY.dpi)
        assert image.detail == TODAY.detail


def test_two_tables_rechecked_together_share_one_limit(tmp_path):
    (one, pdf_one), (two, pdf_two) = _long_table(tmp_path, "one"), _long_table(tmp_path, "two")
    client = OverlapClient(_answering(RIGHT))
    gate = asyncio.Semaphore(4)

    async def both():
        return await asyncio.gather(
            recheck_table(one, pdf_one, client, TODAY, gate),
            recheck_table(two, pdf_two, client, TODAY, gate),
        )

    asyncio.run(both())
    assert client.stages() == ["recheck"] * (2 * PAGES)
    assert client.most == 4  # not 4 for each table
