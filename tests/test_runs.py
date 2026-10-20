"""The run format (spec 013, task 002): write a run to `.quotable/runs/<id>/` and read it back."""

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from quotable import runs, storage
from quotable.ocr.config import OcrConfig
from quotable.runs import RunInfo, list_runs, load_run, write_run
from quotable.steps.extra_fields import ExtraField, ExtraFields, FieldGroup
from quotable.steps.layout import find_header
from quotable.table import Table
from quotable.text.layer import load_layer
from tests.conftest import extract_tables
from tests.extra_fields_model import request_for, truth_model
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import load_doc
from tests.test_extra_fields_pipeline import run as run_extra_fields
from tests.test_extra_fields_pipeline import truth_of
from tests.test_merge_pipeline import run as run_merge
from tests.test_merge_pipeline import truth_rows
from tests.test_senate_tables import PDF as SENATE_PDF
from tests.test_senate_tables import recorded_model

STARTED = "2026-10-20T14:14:07Z"
ENDED = "2026-10-20T14:31:52Z"


def new_id() -> str:
    return uuid.uuid4().hex


def make_info(pdf: Path, run_id: str | None = None, **changes) -> RunInfo:
    fields: dict[str, Any] = {
        "id": run_id or new_id(),
        "started": STARTED,
        "ended": ENDED,
        "quotable": "0.1.0",
        "model": "test:fake",
        "discovery_pages": 3,
        "recheck": True,
        "ocr": True,
        "merge_reworded": True,
        "max_requests": None,
        "extra_fields": None,
        "name": pdf.name,
        "path": str(pdf.resolve()),
        "size": pdf.stat().st_size,
        "sha256": "ab" * 32,
        "pages": 3,
    }
    return RunInfo(**{**fields, **changes})


def page_data(pdf: Path):
    with pymupdf.open(pdf) as document:
        layers = {i + 1: load_layer(p) for i, p in enumerate(document)}
        sizes = {i + 1: (p.rect.width, p.rect.height) for i, p in enumerate(document)}
    return layers, sizes


def save(project: Path, tables: list[Table], pdf: Path, bands=None, **changes):
    layers, sizes = page_data(pdf)
    headers = [{r.page: find_header(t.columns, layers[r.page]) for r in t.pages} for t in tables]
    info = make_info(pdf, **changes)
    where = write_run(project, info, tables, layers, sizes, headers, bands or [{} for _ in tables])
    return where, info, headers, sizes


def band_of(table: Table, page: int) -> tuple[float, float]:
    words = table.layers[page].words
    return min(w.bbox[1] for w in words), max(w.bbox[3] for w in words)


@pytest.fixture(scope="module")
def senate_tables() -> list[Table]:
    return extract_tables(SENATE_PDF, recorded_model(), recheck=False)


def approx(box):
    return pytest.approx(list(box), abs=0.01)


# --- storage ----------------------------------------------------------------------------------
def test_runs_dir_is_the_runs_folder_of_the_project(tmp_path):
    assert storage.RUNS_DIR_NAME == "runs"
    assert storage.runs_dir(tmp_path / ".quotable") == tmp_path / ".quotable" / "runs"


# --- writing ----------------------------------------------------------------------------------
def test_a_written_run_is_two_json_files_in_a_folder_named_by_its_id(tmp_path, senate_tables):
    project = tmp_path / "project"
    where, info, _, _ = save(project, senate_tables, SENATE_PDF)
    assert where == project / "runs" / info.id
    assert sorted(p.name for p in where.iterdir()) == ["run.json", "tables.json"]
    assert [p.name for p in (project / "runs").iterdir()] == [info.id]
    for name in ("run.json", "tables.json"):
        data = json.loads((where / name).read_text())
        assert data["v"] == 1


def test_the_files_are_valid_json_without_infinity(tmp_path, senate_tables):
    where, *_ = save(tmp_path / "p", senate_tables, SENATE_PDF)

    def refuse(name):
        raise AssertionError(f"not valid JSON: {name}")

    for name in ("run.json", "tables.json"):
        json.loads((where / name).read_text(), parse_constant=refuse)


def test_a_write_that_fails_half_way_leaves_nothing_in_runs(tmp_path, senate_tables, monkeypatch):
    real = runs.write_atomic
    calls = []

    def second_fails(path, text):
        calls.append(path.name)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, text)

    monkeypatch.setattr(runs, "write_atomic", second_fails)
    project = tmp_path / "p"
    with pytest.raises(OSError, match="disk full"):
        save(project, senate_tables, SENATE_PDF)
    assert len(calls) == 2
    assert list((project / "runs").iterdir()) == []


# --- reading: the run's header ----------------------------------------------------------------
def test_a_run_reads_back_with_its_run_document_and_settings(tmp_path, senate_tables):
    project = tmp_path / "p"
    extra = ExtraFields(
        [
            ExtraField("year", "The funding year"),
            FieldGroup("block", "The title block", [ExtraField("title", "The title")]),
        ],
        prompt="Look at the top.",
        carry_forward=True,
    )
    config = OcrConfig(dpi=200, model_dir=tmp_path / "models")
    _, info, _, _ = save(
        project,
        senate_tables,
        SENATE_PDF,
        ocr=config,
        discovery_pages=2,
        recheck=False,
        merge_reworded=False,
        max_requests=40,
        extra_fields=extra,
        model="openai:gpt-test",
        sha256="9c" * 32,
        pages=3,
    )
    run = load_run(project, info.id)
    summary = run.summary
    assert (summary.id, summary.started, summary.ended) == (info.id, STARTED, ENDED)
    assert (summary.quotable, summary.model) == ("0.1.0", "openai:gpt-test")
    assert (summary.name, summary.path, summary.size) == (info.name, info.path, info.size)
    assert (summary.sha256, summary.pages) == ("9c" * 32, 3)
    settings = summary.settings
    assert (settings["discovery_pages"], settings["recheck"]) == (2, False)
    assert (settings["merge_reworded"], settings["max_requests"]) == (False, 40)
    assert settings["ocr"]["dpi"] == 200
    assert settings["ocr"]["model_dir"] == str(tmp_path / "models")
    assert settings["extra_fields"] == {
        "fields": [
            {"name": "year", "description": "The funding year", "group": None},
            {"name": "title", "description": "The title", "group": "block"},
        ],
        "prompt": "Look at the top.",
        "carry_forward": True,
    }


def test_ocr_and_extra_fields_settings_can_be_plain_values(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, _ = save(project, senate_tables, SENATE_PDF, ocr=False)
    settings = load_run(project, info.id).summary.settings
    assert settings["ocr"] is False
    assert settings["extra_fields"] is None


def test_the_summary_counts_tables_rows_cells_flagged_and_ocr_pages(tmp_path, senate_tables):
    project = tmp_path / "p"
    tables = [replace(t, ocr_pages=(1,)) for t in senate_tables]
    _, info, _, _ = save(project, tables, SENATE_PDF)
    summary = load_run(project, info.id).summary
    rows = sum(len(t.rows()) for t in senate_tables)
    assert len(summary.tables) == 2
    assert summary.rows == rows
    assert summary.cells == sum(len(r.cells) for t in senate_tables for r in t.rows())
    expected: dict[str, int] = {}
    for t in senate_tables:
        for flag in t.flagged():
            expected[flag.status] = expected.get(flag.status, 0) + 1
    assert summary.flagged == expected
    assert summary.ocr_pages == [1]
    for entry, table in zip(summary.tables, senate_tables, strict=True):
        assert entry.columns == table.columns
        assert entry.pages == [r.page for r in table.pages]
        assert entry.rows == len(table.rows())
        assert entry.label == table.label
    assert [e.index for e in summary.tables] == [0, 1]
    assert [e.ocr_pages for e in summary.tables] == [[1], [1]]


# --- reading: tables --------------------------------------------------------------------------
def test_every_value_status_box_and_candidate_survives(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, _ = save(project, senate_tables, SENATE_PDF)
    run = load_run(project, info.id)
    assert [t.label for t in run.tables] == [t.label for t in senate_tables]
    for got, table in zip(run.tables, senate_tables, strict=True):
        assert got.columns == table.columns
        assert got.pages == [r.page for r in table.pages]
        assert got.position == table.position
        rows = table.rows()
        assert len(got.rows) == len(rows)
        for read, row in zip(got.rows, rows, strict=True):
            assert (read.page, read.row, read.values) == (row.page, row.row, row.values)
            assert list(read.cells) == list(row.cells)
            for column, cell in row.cells.items():
                back = read.cells[column]
                assert back.status == cell.status
                assert back.matched_text == cell.matched_text
                assert back.n_candidates == cell.n_candidates
                assert back.coverage == (
                    None if cell.coverage is None else pytest.approx(cell.coverage, abs=1e-4)
                )
                assert back.density == (
                    None if cell.density is None else pytest.approx(cell.density, abs=1e-4)
                )
                assert back.bbox == (None if cell.bbox is None else approx(cell.bbox))
                layer = table.layers[row.page]
                boxes = [layer.bbox(c.start, c.end) for c in cell.candidates]
                assert len(back.candidates) == len(boxes)
                for box, expected in zip(back.candidates, boxes, strict=True):
                    assert box == approx(expected)


def test_some_cell_of_the_fixture_has_a_box_and_a_candidate(senate_tables):
    cells = [c for t in senate_tables for r in t.rows() for c in r.cells.values()]
    assert any(c.bbox and c.candidates for c in cells)


def test_pages_hold_the_full_page_words_and_size(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, sizes = save(project, senate_tables, SENATE_PDF)
    run = load_run(project, info.id)
    layers, _ = page_data(SENATE_PDF)
    assert sorted(run.pages) == [1, 2, 3]
    for number, page in run.pages.items():
        assert page.size == approx(sizes[number])
        assert len(page.words) == len(layers[number].words)
        text, *box = page.words[0]
        first = layers[number].words[0]
        assert text == first.text
        assert box == approx(first.bbox)
    # a table's band layer is a part of the page: the stored words are the whole page
    assert len(senate_tables[0].layers[1].words) < len(run.pages[1].words)


def test_pages_are_only_those_any_table_is_on(tmp_path, senate_tables):
    project = tmp_path / "p"
    only_summary = senate_tables[:1]
    _, info, _, _ = save(project, only_summary, SENATE_PDF)
    assert sorted(load_run(project, info.id).pages) == [1]


def test_layouts_and_headers_survive(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, headers, _ = save(project, senate_tables, SENATE_PDF)
    run = load_run(project, info.id)
    for got, table, header in zip(run.tables, senate_tables, headers, strict=True):
        assert [lay["page"] for lay in got.layouts] == [r.page for r in table.pages]
        for lay, source in zip(got.layouts, table.layouts, strict=True):
            assert lay["columns"] == list(source.columns)
            assert lay["source"] == source.source
            expected = header[lay["page"]]
            if expected is None:
                assert lay["header"] is None
                continue
            assert lay["header"]["line"] == pytest.approx(expected.line, abs=0.01)
            assert lay["header"]["bottom"] == pytest.approx(expected.bottom, abs=0.01)
            assert lay["header"]["x"] == {
                c: pytest.approx(x, abs=0.01) for c, x in expected.x.items()
            }
    assert any(lay["header"] for t in run.tables for lay in t.layouts)


def test_bands_are_kept_as_given_for_shared_pages(tmp_path, senate_tables):
    project = tmp_path / "p"
    summary, detail = senate_tables
    bands = [{1: band_of(summary, 1)}, {1: band_of(detail, 1)}]
    _, info, _, _ = save(project, senate_tables, SENATE_PDF, bands=bands)
    run = load_run(project, info.id)
    assert run.tables[0].bands == {1: approx(bands[0][1])}
    assert run.tables[1].bands == {1: approx(bands[1][1])}
    _, other, _, _ = save(project, senate_tables, SENATE_PDF)
    assert [t.bands for t in load_run(project, other.id).tables] == [{}, {}]


def test_areas_are_kept_with_the_open_edges_clamped_to_the_page(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, sizes = save(project, senate_tables, SENATE_PDF)
    run = load_run(project, info.id)
    seen_rows = seen_columns = 0
    for got, table in zip(run.tables, senate_tables, strict=True):
        for page, grounding in table.grounded.items():
            area = got.areas[page]
            width, height = sizes[page]
            # row windows are stored by 1-based row number, as `RunRow.row`
            assert sorted(area.rows) == [i + 1 for i in sorted(grounding.row_windows)]
            for i, window in grounding.row_windows.items():
                assert area.rows[i + 1] == approx(window)
            assert sorted(area.columns) == sorted(grounding.column_ranges)
            for column, (x0, x1) in grounding.column_ranges.items():
                low, high = area.columns[column]
                assert low == pytest.approx(0.0 if x0 == float("-inf") else x0, abs=0.01)
                assert high == pytest.approx(width if x1 == float("inf") else x1, abs=0.01)
            seen_rows += len(area.rows)
            seen_columns += len(area.columns)
            assert height > 0
    assert seen_rows
    assert seen_columns


# --- reading: merged parts, proposals ---------------------------------------------------------
def merged_with_a_recheck():
    truth = load_doc("pipe-reworded-gap1")
    names = truth["parts"][0]["columns"]
    b_names = truth["parts"][1]["columns"]
    correct = truth["parts"][1]["rows"]["5"][2][0]
    wrong = correct.split()[0] + " Zzyzx"

    def recheck(request):
        from quotable.llm.answers import PageRecheck  # noqa: PLC0415

        return PageRecheck(cells=[{"row": 3, "column": names[0], "value": correct}])

    tables, _ = run_merge("pipe-reworded-gap1", typos={(5, 3, b_names[0]): wrong}, recheck=recheck)
    return tables, FIXTURE / "pipe-reworded-gap1.pdf"


def test_merged_parts_with_their_evidence_survive(tmp_path):
    tables, pdf = merged_with_a_recheck()
    (table,) = tables
    assert table.merged
    project = tmp_path / "p"
    _, info, _, _ = save(project, tables, pdf)
    run = load_run(project, info.id)
    (got,) = run.tables
    assert len(got.merged) == len(table.merged)
    assert run.summary.tables[0].merged == len(table.merged)
    for read, part in zip(got.merged, table.merged, strict=True):
        assert read["pages"] == list(part.pages)
        assert read["columns"] == list(part.columns)
        evidence = part.evidence
        assert read["evidence"]["token_sets"] == [
            [list(a), list(b)] for a, b in evidence.token_sets
        ]
        assert read["evidence"]["equal_positions"] == evidence.equal_positions
        assert read["evidence"]["max_x_difference"] == pytest.approx(
            evidence.max_x_difference, abs=0.01
        )
        assert read["evidence"]["shapes"] == list(evidence.shapes)
        assert read["evidence"]["cells"] == [list(c) for c in evidence.cells]


def test_recheck_proposals_survive_with_every_field(tmp_path):
    tables, pdf = merged_with_a_recheck()
    (table,) = tables
    assert [p.outcome for p in table.proposals] == ["accepted"]
    project = tmp_path / "p"
    _, info, _, _ = save(project, tables, pdf)
    (got,) = load_run(project, info.id).tables
    assert got.proposals == [
        {
            "page": p.page,
            "row": p.row,
            "column": p.column,
            "original": p.original,
            "proposed": p.proposed,
            "status_before": p.status_before,
            "status_after": p.status_after,
            "outcome": p.outcome,
        }
        for p in table.proposals
    ]


def test_a_merged_table_still_reads_back_row_for_row(tmp_path):
    tables, pdf = merged_with_a_recheck()
    truth = load_doc("pipe-reworded-gap1")
    project = tmp_path / "p"
    _, info, _, _ = save(project, tables, pdf)
    (got,) = load_run(project, info.id).tables
    assert len(got.rows) == len(truth_rows(truth, 0)) + len(truth_rows(truth, 1))


# --- reading: extra fields --------------------------------------------------------------------
def extra_tables():
    truth = truth_of("extra-section-3p")
    request = request_for(truth, carry=True)
    tables = run_extra_fields("extra-section-3p", truth_model("extra-section-3p"), request)
    return tables, FIXTURE / "extra-section-3p.pdf"


def test_extra_fields_with_their_grounding_and_source_page_survive(tmp_path):
    tables, pdf = extra_tables()
    (table, *_) = tables
    assert table.extra_names
    project = tmp_path / "p"
    _, info, _, _ = save(project, tables, pdf)
    run = load_run(project, info.id)
    got = run.tables[0]
    assert got.extra_names == list(table.extra_names)
    assert sorted(got.extra_fields) == sorted(table.extra_fields)
    sources = set()
    for page, row in table.extra_fields.items():
        assert sorted(got.extra_fields[page]) == sorted(row)
        for name, result in row.items():
            read = got.extra_fields[page][name]
            assert read.value == result.value
            assert read.source_page == result.source_page
            assert read.cell.status == result.grounding.status
            assert read.cell.matched_text == result.grounding.matched_text
            assert read.cell.bbox == (
                None if result.grounding.bbox is None else approx(result.grounding.bbox)
            )
            sources.add((page, result.source_page))
    assert any(source not in (None, page) for page, source in sources)  # carried from earlier


def test_extra_change_records_survive(tmp_path):
    tables, pdf = extra_tables()
    changed = replace(tables[0], extra_changes={(1, "division"): ("old", "new")})
    project = tmp_path / "p"
    _, info, _, _ = save(project, [changed], pdf)
    (got,) = load_run(project, info.id).tables
    assert got.extra_changes == [[1, "division", "old", "new"]]


def test_extra_fields_count_once_per_printing_page_in_the_flagged_totals(tmp_path):
    tables, pdf = extra_tables()
    (table, *_) = tables
    carried = [
        r
        for row in table.extra_fields.values()
        for n, r in row.items()
        if n == "division" and r.source_page == 1
    ]
    assert len(carried) >= 2  # printed on page 1, carried onto later pages
    for result in carried:
        result.grounding = replace(result.grounding, status="fuzzy")
    project = tmp_path / "p"
    _, info, _, _ = save(project, tables, pdf)
    summary = load_run(project, info.id).summary
    cells = sum(1 for flag in table.flagged() if not flag.extra)
    assert summary.flagged["fuzzy"] == 1 + sum(
        1 for flag in table.flagged() if not flag.extra and flag.status == "fuzzy"
    )
    assert sum(summary.flagged.values()) == cells + 1


# --- listing and loading ----------------------------------------------------------------------
def test_list_runs_gives_the_newest_first_and_skips_the_unreadable(tmp_path, senate_tables):
    project = tmp_path / "p"
    ids = {}
    for label, started in (("old", "2026-10-18T09:00:00Z"), ("new", "2026-10-20T09:00:00Z")):
        _, info, _, _ = save(project, senate_tables, SENATE_PDF, started=started)
        ids[label] = info.id
    _, middle, _, _ = save(project, senate_tables, SENATE_PDF, started="2026-10-19T09:00:00Z")
    base = project / "runs"
    damaged = base / new_id()
    damaged.mkdir()
    (damaged / "run.json").write_text("{not json")
    future = base / new_id()
    future.mkdir()
    (future / "run.json").write_text(json.dumps({"v": 2}))
    empty = base / new_id()
    empty.mkdir()
    (base / f".{new_id()}.tmp").mkdir()
    (base / "not-a-run-id").mkdir()
    found, skipped = list_runs(project)
    assert [r.id for r in found] == [ids["new"], middle.id, ids["old"]]
    assert skipped == 3
    assert len(found[0].tables) == 2
    assert [t.label for t in found[0].tables] == [t.label for t in senate_tables]


def test_list_runs_without_a_runs_folder_is_empty(tmp_path):
    assert list_runs(tmp_path / "nothing") == ([], 0)


def test_a_leftover_temporary_folder_is_ignored_not_counted(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, _ = save(project, senate_tables, SENATE_PDF)
    leftover = project / "runs" / f".{new_id()}.tmp"
    leftover.mkdir()
    (leftover / "run.json").write_text("{}")
    found, skipped = list_runs(project)
    assert [r.id for r in found] == [info.id]
    assert skipped == 0


def test_load_run_refuses_a_path_an_unknown_id_and_capitals(tmp_path, senate_tables):
    project = tmp_path / "p"
    _, info, _, _ = save(project, senate_tables, SENATE_PDF)
    for bad in ("../x", "..", "", new_id(), info.id.upper(), info.id[:-1], info.id + "0"):
        with pytest.raises(KeyError):
            load_run(project, bad)
    assert load_run(project, info.id).summary.id == info.id


def test_load_run_refuses_an_id_whose_folder_is_a_file(tmp_path):
    project = tmp_path / "p"
    (project / "runs").mkdir(parents=True)
    run_id = new_id()
    (project / "runs" / run_id).write_text("")
    with pytest.raises(KeyError):
        load_run(project, run_id)
