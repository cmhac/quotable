"""Every ``extract_tables`` call that returns saves its run (spec 013, task 003)."""

import asyncio
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path

import pymupdf
import pytest
from pydantic import BaseModel

from quotable import (
    BudgetExceededError,
    OcrConfig,
    TextLayerError,
    extract_tables,
    extract_tables_async,
)
from quotable import pipeline as pipeline_module
from quotable.llm.client import Image, Request, model_name, request_key
from quotable.pipeline import RunTrace, headers_and_bands, run_pipeline
from quotable.runs import list_runs, load_run
from quotable.steps.layout import find_header
from quotable.text.layer import load_layer
from tests.conftest import DATA
from tests.test_entrypoint import PDF, Calls
from tests.test_merge_pipeline import client_for
from tests.test_senate_tables import PDF as SENATE_PDF
from tests.test_senate_tables import recorded_model

PROJECT = Path(".quotable")
GARBLED = DATA / "senate_expenditures_garbled.pdf"


def run_folders(base: Path = PROJECT) -> list[str]:
    runs = base / "runs"
    return sorted(p.name for p in runs.iterdir()) if runs.exists() else []


def cost_runs() -> set[str]:
    path = PROJECT / "cost" / "requests.jsonl"
    return {json.loads(line)["run"] for line in path.read_text().splitlines()}


# --- one run per call ---------------------------------------------------------------------------
def test_a_call_leaves_one_run_whose_id_is_the_one_in_its_cost_records():
    extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    (run_id,) = run_folders()
    assert cost_runs() == {run_id}
    assert re.fullmatch(r"[0-9a-f]{32}", run_id)


def test_a_second_call_of_cache_hits_adds_a_run_and_no_cost_record():
    extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    lines = (PROJECT / "cost" / "requests.jsonl").read_text().splitlines()
    extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    assert len(run_folders()) == 2
    assert (PROJECT / "cost" / "requests.jsonl").read_text().splitlines() == lines


def test_the_async_twin_saves_too():
    asyncio.run(extract_tables_async(PDF, Calls().model(), recheck=False, audit=False))
    assert len(run_folders()) == 1


def test_a_named_cache_dir_does_not_move_the_run(tmp_path):
    named = tmp_path / "named"
    extract_tables(PDF, Calls().model(), cache_dir=named, recheck=False, audit=False)
    assert len(run_folders()) == 1
    assert not [p for p in named.rglob("*") if "run" in p.name.lower() and p.is_dir()]
    assert not (named / "runs").exists()


def test_a_call_that_raises_saves_nothing():
    with pytest.raises(BudgetExceededError):
        extract_tables(PDF, Calls().model(), max_requests=1, recheck=False, audit=False)
    assert not (PROJECT / "runs").exists()
    with pytest.raises(TextLayerError):
        extract_tables(GARBLED, Calls().model(), ocr=False)
    assert not (PROJECT / "runs").exists()


def test_a_failed_save_warns_once_and_still_returns_the_tables(monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pipeline_module, "write_run", refuse)
    (table,) = extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    assert table.rows()
    err = capsys.readouterr().err
    assert err.count("could not save the run") == 1
    assert err.startswith("quotable: could not save the run to ")
    assert "disk full" in err
    assert err.count("\n") == 1


# --- what is recorded ---------------------------------------------------------------------------
def test_the_document_the_settings_and_the_times_are_recorded():
    calls = Calls()
    model = calls.model()
    config = OcrConfig()
    extract_tables(
        PDF,
        model,
        discovery_pages=2,
        recheck=False,
        audit=False,
        ocr=config,
        merge_reworded=False,
        max_requests=50,
    )
    (run_id,) = run_folders()
    summary = load_run(PROJECT, run_id).summary
    assert summary.name == PDF.name
    assert summary.path == str(PDF.resolve())
    assert summary.size == PDF.stat().st_size
    assert summary.sha256 == hashlib.sha256(PDF.read_bytes()).hexdigest()
    with pymupdf.open(PDF) as document:
        assert summary.pages == len(document)
    assert summary.model == model_name(model)
    assert summary.quotable == importlib.metadata.version("quotable")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", summary.started)
    assert summary.started <= summary.ended
    settings = summary.settings
    assert (settings["discovery_pages"], settings["recheck"]) == (2, False)
    assert (settings["merge_reworded"], settings["max_requests"]) == (False, 50)
    assert settings["ocr"]["dpi"] == config.dpi


def test_the_default_settings_are_recorded_as_given():
    extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    (summary,), skipped = list_runs(PROJECT)
    assert skipped == 0
    assert summary.settings["ocr"] is True
    assert summary.settings["extra_fields"] is None
    assert summary.settings["max_requests"] is None


def test_the_saved_tables_are_the_returned_ones():
    (table,) = extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    (run_id,) = run_folders()
    run = load_run(PROJECT, run_id)
    (saved,) = run.tables
    assert saved.columns == table.columns
    assert [r.values for r in saved.rows] == [r.values for r in table.rows()]
    layer = load_layer(pymupdf.open(PDF)[0])
    assert len(run.pages[1].words) == len(layer.words)
    header = find_header(table.columns, layer)
    assert header is not None
    assert saved.layouts[0]["header"]["line"] == pytest.approx(header.line, abs=0.01)
    assert saved.bands == {}


def test_headers_and_bands_reach_write_run_per_table(monkeypatch):
    seen = {}

    def spy(_project, _info, tables, layers, _sizes, headers, bands):  # noqa: PLR0913, PLR0917
        seen.update(tables=tables, layers=layers, headers=headers, bands=bands)
        return Path("unused")

    monkeypatch.setattr(pipeline_module, "write_run", spy)
    (table,) = extract_tables(PDF, Calls().model(), recheck=False, audit=False)
    assert seen["tables"] == [table]
    assert list(seen["layers"]) == [1]
    assert seen["bands"] == [{}]
    assert seen["headers"] == [{1: find_header(table.columns, seen["layers"][1])}]


# --- the trace of run_pipeline ------------------------------------------------------------------
def test_the_trace_holds_whole_pages_and_the_bands_of_a_shared_page():
    trace = RunTrace()
    tables = asyncio.run(
        run_pipeline(SENATE_PDF, recorded_model(), recheck=False, audit=False, trace=trace)
    )
    assert sorted(trace.layers) == [1, 2, 3]
    assert len(trace.layers[1].words) > len(tables[0].layers[1].words)  # whole page, not a band
    assert sorted(trace.bands) == [1]
    ((first_layer, first), (second_layer, second)) = trace.bands[1]
    assert {id(first_layer), id(second_layer)} == {id(t.layers[1]) for t in tables}
    assert first[1] < second[0]  # the summary sits above the detail table
    for table in tables:
        words = table.layers[1].words
        top, bottom = next(b for lay, b in trace.bands[1] if lay is table.layers[1])
        assert top <= min((w.bbox[1] + w.bbox[3]) / 2 for w in words)
        assert bottom >= max((w.bbox[1] + w.bbox[3]) / 2 for w in words)


def test_headers_and_bands_are_found_per_table_and_page():
    trace = RunTrace()
    tables = asyncio.run(
        run_pipeline(SENATE_PDF, recorded_model(), recheck=False, audit=False, trace=trace)
    )
    headers, bands = headers_and_bands(tables, trace)
    assert [sorted(h) for h in headers] == [[1], [1, 2, 3]]
    assert [sorted(b) for b in bands] == [[1], [1]]
    for table, per_page in zip(tables, headers, strict=True):
        for page, header in per_page.items():
            assert header == find_header(table.columns, trace.layers[page])


def test_a_merged_tables_later_part_gets_its_header_under_the_tables_names():
    client, _ = client_for("pipe-reworded-gap1")
    trace = RunTrace()
    (table,) = asyncio.run(
        run_pipeline(
            DATA / "synthetic" / "pipe-reworded-gap1.pdf",
            client,
            discovery_pages=1,
            recheck=False,
            audit=False,
            trace=trace,
        )
    )
    assert table.merged
    (headers,), _ = headers_and_bands([table], trace)
    later = table.merged[0].pages[0]
    header = headers[later]
    assert header is not None
    assert set(header.x) <= set(table.columns)
    assert len(header.x) >= 3


def test_the_trace_is_optional():
    tables = asyncio.run(run_pipeline(SENATE_PDF, recorded_model(), recheck=False, audit=False))
    assert len(tables) == 2


# --- nothing else changes -----------------------------------------------------------------------
def test_the_request_cache_key_is_unchanged():
    class Reading(BaseModel):
        rows: list[str]

    request = Request(
        stage="extract",
        instructions="Read the table.",
        output_type=Reading,
        parts=["columns: a, b", Image(b"png-bytes")],
    )
    key = request_key("openai:gpt-test:{}", request)
    assert key == "1cfb8ed52c4f39440fce76450d1dbb248ad45426e66e040523025d70b2df33b1"
