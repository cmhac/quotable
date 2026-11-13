"""What a cache entry says about itself (spec 019, story 6)."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from quotable import TableFailedWarning
from quotable.llm.answers import (
    Column,
    PageRows,
    PageTables,
    TableInfo,
    TableSchema,
    WindowTables,
)
from quotable.llm.client import CachedClient, Image, Request, request_key
from quotable.steps.discover import discover
from quotable.steps.extract import extract_page
from tests.conftest import FakeClient, extract_tables
from tests.test_failed_tables import HEADER_A, HEADER_C, PAGE_B, ROWS, a, bad, c
from tests.test_tables import model

RUN = "ab" * 16
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class Answer(BaseModel):
    text: str


def client_in(folder: Path, run_id: str | None = RUN, handler=None) -> CachedClient:
    inner = FakeClient(handler or (lambda r: Answer(text="hello")))
    return CachedClient(inner, folder, run_id=run_id)


def entry_of(folder: Path, request: Request) -> dict:
    return json.loads((folder / f"{request_key('fake', request)}.json").read_text("utf-8"))


def ask(client: CachedClient, request: Request) -> None:
    asyncio.run(client.ask(request))


def test_an_entry_holds_the_answer_unchanged_and_the_details_beside_it(tmp_path):
    request = Request("extract", "do it", Answer, ["columns", Image(b"png")], 7)
    ask(client_in(tmp_path), request)
    entry = entry_of(tmp_path, request)
    assert entry["text"] == "hello"
    details = entry["_quotable"]
    assert set(details) == {"stage", "pages", "model", "written", "run"}
    assert (details["stage"], details["pages"], details["model"], details["run"]) == (
        "extract",
        [7],
        "fake",
        RUN,
    )
    assert TIME.fullmatch(details["written"])
    assert Answer.model_validate(entry) == Answer(text="hello")  # the key is ignored on reading


def test_a_discovery_window_records_all_its_pages(tmp_path):
    request = Request("schema", "do it", Answer, ["x"], pages=(357, 358, 359, 360))
    ask(client_in(tmp_path), request)
    assert entry_of(tmp_path, request)["_quotable"]["pages"] == [357, 358, 359, 360]


def test_a_request_with_no_page_records_none_and_no_run_id_records_null(tmp_path):
    request = Request("extras", "do it", Answer, ["x"])
    ask(client_in(tmp_path, run_id=None), request)
    details = entry_of(tmp_path, request)["_quotable"]
    assert details["pages"] == [] and details["run"] is None


def test_a_retry_names_its_original_and_the_problem_and_the_original_does_not(tmp_path):
    first = Request("extract", "do it", Answer, ["x"], 3)
    retry = Request("extract", "do it", Answer, ["x", "again"], 3, retry_of="9" * 64, problem="p")
    client = client_in(tmp_path)
    ask(client, first)
    ask(client, retry)
    assert "retry_of" not in entry_of(tmp_path, first)["_quotable"]
    assert "problem" not in entry_of(tmp_path, first)["_quotable"]
    details = entry_of(tmp_path, retry)["_quotable"]
    assert (details["retry_of"], details["problem"]) == ("9" * 64, "p")


def test_the_new_fields_are_not_part_of_the_key():
    plain = Request("extract", "do it", Answer, ["x"], 3)
    detailed = Request("extract", "do it", Answer, ["x"], 3, (3,), "9" * 64, "p")
    assert request_key("fake", plain) == request_key("fake", detailed)


def test_an_entry_written_before_the_details_existed_is_used_and_not_rewritten(tmp_path):
    request = Request("extract", "do it", Answer, ["x"], 1)
    path = tmp_path / f"{request_key('fake', request)}.json"
    path.write_text('{\n "text": "old"\n}', encoding="utf-8")
    before = path.read_bytes()
    client = client_in(tmp_path, handler=lambda r: Answer(text="new"))
    assert asyncio.run(client.ask(request)).text == "old"
    assert path.read_bytes() == before
    assert not [p for p in tmp_path.glob("*.json") if p != path]


def test_an_entry_holds_no_prompt_image_or_path(tmp_path):
    request = Request("extract", "SECRET-INSTRUCTIONS", Answer, ["SECRET-TEXT", Image(b"PNG")], 1)
    ask(client_in(tmp_path), request)
    text = (tmp_path / f"{request_key('fake', request)}.json").read_text("utf-8")
    for leaked in ("SECRET-INSTRUCTIONS", "SECRET-TEXT", "PNG", str(tmp_path), "sk-"):
        assert leaked not in text


# --- the retries the pipeline makes -------------------------------------------------------------
def info(columns):
    cols = [Column(name=n, description="") for n in columns]
    return TableInfo(label="t", columns=cols, first_row="", last_row="")


def test_the_discovery_retry_points_to_the_first_request(tmp_path):
    answers = iter(
        [
            WindowTables(pages=[PageTables(tables=[info([])])]),
            WindowTables(pages=[PageTables(tables=[info(["A"])])]),
        ]
    )
    client = client_in(tmp_path, handler=lambda r: next(answers))
    asyncio.run(discover([b"\x00"], client))
    entries = [json.loads(p.read_text("utf-8")) for p in tmp_path.glob("*.json")]
    (first,) = [e for e in entries if "retry_of" not in e["_quotable"]]
    (retry,) = [e for e in entries if "retry_of" in e["_quotable"]]
    assert first["_quotable"]["pages"] == retry["_quotable"]["pages"] == [1]
    assert (tmp_path / f"{retry['_quotable']['retry_of']}.json").exists()
    assert "no columns" in retry["_quotable"]["problem"]


def test_the_extraction_retry_points_to_the_first_request(tmp_path):
    answers = iter([PageRows(rows=[{"Nope": "x"}]), PageRows(rows=[{"A": "x"}])])
    client = client_in(tmp_path, handler=lambda r: next(answers))
    schema = TableSchema(columns=[Column(name="A", description="")])
    asyncio.run(extract_page(4, b"png", schema, client))
    entries = [json.loads(p.read_text("utf-8")) for p in tmp_path.glob("*.json")]
    (retry,) = [e for e in entries if "retry_of" in e["_quotable"]]
    assert retry["_quotable"]["pages"] == [4]
    assert (tmp_path / f"{retry['_quotable']['retry_of']}.json").exists()
    assert "missing keys" in retry["_quotable"]["problem"]


def test_every_entry_of_a_pipeline_run_has_its_details(make_pdf, tmp_path):
    path = make_pdf([HEADER_A, PAGE_B, HEADER_C])
    window = [[a()], [bad("B")], [c()]]
    cache = tmp_path / "cache"
    cache.mkdir()
    client = CachedClient(model([window, window], ROWS), cache, run_id=RUN)
    with pytest.warns(TableFailedWarning):
        extract_tables(path, client, recheck=False)
    entries = {p.stem: json.loads(p.read_text("utf-8")) for p in cache.glob("*.json")}
    assert entries and all("_quotable" in e for e in entries.values())
    assert {e["_quotable"]["stage"] for e in entries.values()} == {"schema", "extract"}
    assert all(e["_quotable"]["run"] == RUN for e in entries.values())
    (retry,) = [e for e in entries.values() if "retry_of" in e["_quotable"]]
    assert retry["_quotable"]["retry_of"] in entries


def test_an_entry_is_still_written_without_details_when_they_cannot_be_built(tmp_path):
    request = Request("extract", "do it", Answer, ["x"], pages=5)  # ty: ignore[invalid-argument-type]
    ask(client_in(tmp_path), request)
    entry = entry_of(tmp_path, request)
    assert entry == {"text": "hello"}
