"""The omission audit inside the pipeline, with fake models (spec 014).

The fake models only drive the wiring: they return the rows a perfect model would, or leave one
out and return it when audited. Whether a real model reports omissions is the live check,
`tests/live/test_live_audit.py`.
"""

import asyncio
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from quotable import BudgetExceededError, extract_tables
from quotable.llm.answers import CellRecheck, MissingRow, Omissions, PageRecheck
from quotable.llm.client import CachedClient
from quotable.llm.images import TODAY
from quotable.pipeline import run_pipeline
from quotable.steps.audit import audit_table
from quotable.table import Table, ground_document
from tests.conftest import DATA, FakeClient, replay
from tests.conftest import extract_tables as run_with_fake
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import doc_ids, tables_of
from tests.test_entrypoint import PDF, Calls

RECORDED = json.loads((DATA / "fy22_milcon_house_original.rows.json").read_text())
COLUMNS = RECORDED["columns"]
TRUTH = {int(p): rows for p, rows in RECORDED["pages"].items()}
DROPPED = 6  # 1-based row the model leaves out in the first pass
TYPO_ROW = 5  # 1-based row whose Project the model misspells


def omitting_model(*, typo: bool = False, answer_audit: bool = True) -> FakeClient:
    """A model that leaves out row 6 on the first pass, returns it when audited, and may typo."""
    pages = copy.deepcopy(TRUTH)
    true_project = pages[1][TYPO_ROW - 1]["Project"]
    missing = pages[1].pop(DROPPED - 1)
    if typo:
        words = true_project.split()
        words[1] = "Zzyzx"
        pages[1][TYPO_ROW - 1]["Project"] = " ".join(words)
    base = replay(COLUMNS, pages).handler

    def handler(request):
        if request.stage == "audit":
            rows = [MissingRow(after_row=DROPPED - 1, values=missing)] if answer_audit else []
            return Omissions(missing_rows=rows, filled_cells=[])
        if request.stage == "recheck":
            cell = CellRecheck(row=TYPO_ROW, column="Project", value=true_project)
            return PageRecheck(cells=[cell])
        return base(request)

    return FakeClient(handler)


def test_the_audit_restores_the_dropped_row_between_extraction_and_recheck():
    client = omitting_model(typo=True)
    (table,) = run_with_fake(PDF, client, audit=True)
    assert client.stages() == ["schema", "extract", "audit", "recheck"]
    assert [r.values for r in table.page_rows(1)] == TRUTH[1]
    assert table.page_rows(1)[DROPPED - 1].status == "exact"
    assert [(a.kind, a.outcome, a.row) for a in table.audit] == [("row", "accepted", DROPPED)]
    assert [p.outcome for p in table.proposals] == ["accepted"]  # the recheck ran on the new rows
    marks = [r["audit_added"] for r in table.records()]
    assert marks.count("row") == 1 and marks[DROPPED - 1] == "row"


def test_a_partly_matched_row_the_audit_adds_is_corrected_by_the_recheck():
    row_number = TYPO_ROW  # a row whose Project has several words
    pages = copy.deepcopy(TRUTH)
    missing = pages[1].pop(row_number - 1)
    words = missing["Project"].split()
    words[1] = "Zzyzx"  # the audit's reading has one wrong word, so it grounds only fuzzy
    off = {**missing, "Project": " ".join(words)}
    base = replay(COLUMNS, pages).handler

    def handler(request):
        if request.stage == "audit":
            row = MissingRow(after_row=row_number - 1, values=off)
            return Omissions(missing_rows=[row], filled_cells=[])
        if request.stage == "recheck":
            cell = CellRecheck(row=row_number, column="Project", value=missing["Project"])
            return PageRecheck(cells=[cell])
        return base(request)

    client = FakeClient(handler)
    (table,) = run_with_fake(PDF, client, audit=True)
    assert client.stages() == ["schema", "extract", "audit", "recheck"]
    assert [r.values for r in table.page_rows(1)] == TRUTH[1]  # the recheck put the right word in
    assert table.page_rows(1)[row_number - 1].status == "exact"
    assert [(p.row, p.status_before, p.outcome) for p in table.proposals] == [
        (row_number, "fuzzy", "accepted")
    ]
    assert table.records()[row_number - 1]["audit_added"] == "row"


def test_without_the_audit_the_row_stays_missing_and_no_audit_request_is_made():
    client = omitting_model()
    (table,) = run_with_fake(PDF, client, recheck=False, audit=False)
    assert client.stages() == ["schema", "extract"]
    assert len(table.page_rows(1)) == len(TRUTH[1]) - 1
    assert table.audit == []


def test_the_internal_function_leaves_the_audit_off_unless_asked():
    client = omitting_model()
    run_with_fake(PDF, client, recheck=False)
    assert "audit" not in client.stages()


def test_audit_requests_count_toward_the_request_cap(tmp_path):
    capped = CachedClient(omitting_model(), tmp_path, max_requests=2)
    with pytest.raises(BudgetExceededError):
        asyncio.run(run_pipeline(PDF, capped, recheck=False, audit=True))


def test_cells_of_only_dots_or_dashes_come_through_the_whole_pipeline_unchanged():
    pages = copy.deepcopy(TRUTH)
    pages[1][1]["Location"] = "....................."
    pages[1][2]["Amount"] = "---"
    base = replay(COLUMNS, pages).handler

    def handler(request):
        if request.stage == "audit":
            return Omissions(missing_rows=[], filled_cells=[])
        if request.stage == "recheck":
            return PageRecheck(cells=[])
        return base(request)

    client = FakeClient(handler)
    (table,) = run_with_fake(PDF, client, audit=True)
    rows = table.page_rows(1)
    assert (rows[1].values["Location"], rows[2].values["Amount"]) == (
        ".....................",
        "---",
    )
    assert [r["audit_added"] for r in table.records()] == [""] * len(rows)
    audit = next(r for r in client.requests if r.stage == "audit")
    text = "\n".join(p for p in audit.parts if isinstance(p, str))
    assert "Row 2, Location" not in text and "Row 3, Amount" not in text  # not empty cells


# --- through the public function ---------------------------------------------------------------
class AuditCalls(Calls):
    """The entrypoint test's FunctionModel, which also answers an audit request with nothing."""

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        if "missing_rows" in tool.parameters_json_schema["properties"]:
            self.count += 1
            args = {"missing_rows": [], "filled_cells": []}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])
        return super().respond(messages, info)

    def model(self) -> FunctionModel:
        return FunctionModel(self.respond, model_name="audit-test")


def test_the_public_function_audits_by_default_and_records_the_stage():
    calls = AuditCalls()
    (table,) = extract_tables(PDF, calls.model(), recheck=False)
    assert calls.count == 3  # discovery, the page, and the audit (the title is unexplained)
    assert table.audit == []  # nothing proposed
    records = [
        json.loads(line)
        for line in (Path.cwd() / ".quotable" / "cost" / "requests.jsonl").read_text().splitlines()
    ]
    assert sorted(r["stage"] for r in records) == ["audit", "extract", "schema"]


def test_audit_false_turns_it_off_in_the_public_function():
    calls = AuditCalls()
    extract_tables(PDF, calls.model(), recheck=False, audit=False)
    assert calls.count == 2


# --- the synthetic fixture ---------------------------------------------------------------------
def with_last_row_dropped(table: Table) -> tuple[Table, dict[int, dict[str, str]]]:
    """The table as a model that dropped each page's last row would give it, and those rows."""
    dropped = {r.page: r.rows[-1] for r in table.pages}
    pages = [replace(r, rows=r.rows[:-1]) for r in table.pages]
    grounded, position = ground_document(table.columns, pages, table.layers)
    return replace(table, pages=pages, grounded=grounded, position=position), dropped


def asks_for_the_dropped_rows(shown: Table, dropped: dict[int, dict[str, str]]) -> FakeClient:
    """A model that, asked about a page, reports the row dropped from it (after the last shown)."""

    def answer(request):
        listed = len(next(r for r in shown.pages if r.page == request.page).rows)
        row = MissingRow(after_row=listed, values=dropped[request.page])
        return Omissions(missing_rows=[row], filled_cells=[])

    return FakeClient(answer)


@pytest.mark.parametrize("doc_id", doc_ids())
def test_every_dropped_last_row_of_the_fixture_comes_back_and_nothing_else_is_added(doc_id):
    pdf = FIXTURE / f"{doc_id}.pdf"
    gate = asyncio.Semaphore(4)
    for table in tables_of(doc_id).values():
        if any(len(r.rows) < 2 for r in table.pages):  # noqa: PLR2004
            continue  # a page of one row has nothing left to show the model
        cut, dropped = with_last_row_dropped(table)
        restored = asyncio.run(
            audit_table(cut, pdf, asks_for_the_dropped_rows(cut, dropped), TODAY, gate)
        )
        for page in table.pages:
            assert restored.grounded[page.page].rows == page.rows, (doc_id, page.page)
        assert all(a.outcome == "accepted" for a in restored.audit), doc_id

        # nothing dropped: the same answers are all rejected, and no row is added
        again = asyncio.run(
            audit_table(table, pdf, asks_for_the_dropped_rows(table, dropped), TODAY, gate)
        )
        assert again.pages == table.pages, doc_id
        assert all(a.outcome != "accepted" for a in again.audit), doc_id
