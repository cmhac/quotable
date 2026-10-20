"""Verdicts and drafts in `.quotable/review/` (spec 013, task 004)."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from quotable.review import verdicts
from quotable.review.verdicts import (
    CATEGORIES,
    CellKey,
    DraftStore,
    ExtraKey,
    Verdict,
    VerdictStore,
    key_from_json,
    validate,
)
from quotable.storage import REVIEW_DIR_NAME, review_dir

SHA = "ab" * 32
COLUMNS = ("Project", "Amount")


def cell_key(row: int = 1, column: str = "Amount", columns: tuple[str, ...] = COLUMNS) -> CellKey:
    return CellKey(SHA, columns, 3, row, column)


def make_verdict(key: CellKey | ExtraKey | None = None, **changes) -> Verdict:
    fields: dict[str, Any] = {
        "time": "2026-10-20T14:14:07Z",
        "run": "r" * 32,
        "name": "doc.pdf",
        "table_index": 0,
        "table_label": "Projects",
        "table_columns": COLUMNS,
        "key": key or cell_key(),
        "extracted": "1,200",
        "status": "fuzzy",
        "verdict": "correct",
        "value": None,
        "category": None,
        "note": "",
        "queue": {"statuses": ["fuzzy"], "seed": 7, "sample": 20},
    }
    return Verdict(**{**fields, **changes})


def test_review_dir(tmp_path: Path):
    assert REVIEW_DIR_NAME == "review"
    assert review_dir(tmp_path) == tmp_path / "review"


def test_categories_in_the_specs_order():
    assert list(CATEGORIES) == [
        "misspelling",
        "spacing",
        "dropped_word",
        "added_word",
        "hallucination",
        "wrong_cell",
        "wrong_number",
        "corrected_source",
        "other",
    ]
    assert all(CATEGORIES.values())


# --- keys and lines ---------------------------------------------------------------------------
def test_keys_are_json_objects_that_round_trip():
    cell, extra = cell_key(), ExtraKey(SHA, "Fiscal year", 5)
    assert cell.to_json() == {
        "sha256": SHA,
        "columns": ["Project", "Amount"],
        "page": 3,
        "row": 1,
        "column": "Amount",
    }
    assert extra.to_json() == {"sha256": SHA, "extra": "Fiscal year", "page": 5}
    assert key_from_json(cell.to_json()) == cell
    assert key_from_json(extra.to_json()) == extra
    assert len({cell, cell_key(), extra}) == 2


@pytest.mark.parametrize("data", [{}, {"sha256": SHA}, {"sha256": SHA, "extra": 1, "page": 5}, []])
def test_key_from_json_refuses_what_is_not_a_key(data):
    with pytest.raises(ValueError, match="key"):
        key_from_json(data)


@pytest.mark.parametrize(
    "verdict",
    [
        make_verdict(),
        make_verdict(
            verdict="changed", value="1,250", category="wrong_number", note="ünï \u2028 cödé"
        ),
        make_verdict(ExtraKey(SHA, "Fiscal year", 5), extracted="FY2025"),
    ],
)
def test_a_verdict_line_round_trips(verdict: Verdict):
    line = verdict.to_line()
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert Verdict.from_line(line) == verdict
    assert json.loads(line)["v"] == 1


@pytest.mark.parametrize("line", ["", "not json", "[]", "{}", '{"v": 2}'])
def test_from_line_refuses_damage(line: str):
    with pytest.raises(ValueError):  # noqa: PT011
        Verdict.from_line(line)


# --- the verdict store ------------------------------------------------------------------------
def test_nothing_is_created_before_the_first_write(tmp_path: Path):
    store = VerdictStore(tmp_path)
    assert store.latest() == {}
    assert not (tmp_path / "review").exists()
    store.append(make_verdict())
    assert (tmp_path / "review" / "verdicts.jsonl").is_file()


def test_the_later_verdict_for_a_key_wins_and_damage_is_counted(tmp_path: Path):
    store = VerdictStore(tmp_path)
    first = make_verdict(verdict="correct")
    second = make_verdict(verdict="unsure", note="blurry")
    other = make_verdict(cell_key(row=2))
    store.append(first)
    path = tmp_path / "review" / "verdicts.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("this line is damaged\n")
    store.append(second)
    store.append(other)
    latest = store.latest()
    assert latest == {cell_key(): second, cell_key(row=2): other}
    assert store.skipped == 1


def test_a_new_store_reads_what_an_old_one_wrote(tmp_path: Path):
    VerdictStore(tmp_path).append(make_verdict())
    assert VerdictStore(tmp_path).latest() == {cell_key(): make_verdict()}


def test_latest_sees_an_append_made_after_it_was_read(tmp_path: Path):
    store = VerdictStore(tmp_path)
    store.append(make_verdict())
    assert store.latest()[cell_key()].verdict == "correct"
    store.append(make_verdict(verdict="unsure"))
    assert store.latest()[cell_key()].verdict == "unsure"


def test_apply_reviewed_stale_none(tmp_path: Path):
    store = VerdictStore(tmp_path)
    judged = make_verdict(extracted="FY2025")
    store.append(judged)
    assert store.apply(cell_key(), "FY2025") == ("reviewed", judged)
    assert store.apply(cell_key(), "FY2026") == ("stale", judged)
    assert store.apply(cell_key(row=9), "FY2025") == ("none", None)


def test_apply_uses_the_latest_verdict(tmp_path: Path):
    store = VerdictStore(tmp_path)
    store.append(make_verdict(extracted="old"))
    newer = make_verdict(extracted="new", verdict="unsure")
    store.append(newer)
    assert store.apply(cell_key(), "new") == ("reviewed", newer)
    assert store.apply(cell_key(), "old") == ("stale", newer)


def test_an_extra_field_verdict_applies_to_every_row_and_table_of_the_run(tmp_path: Path):
    store = VerdictStore(tmp_path)
    key = ExtraKey(SHA, "Fiscal year", 5)
    judged = make_verdict(key, extracted="FY2025")
    store.append(judged)
    # The key names neither a table nor a row, so every holder of the value builds the same one.
    for _table, _row in [(0, 1), (0, 2), (1, 1)]:
        assert store.apply(ExtraKey(SHA, "Fiscal year", 5), "FY2025") == ("reviewed", judged)
    assert store.apply(ExtraKey(SHA, "Fiscal year", 6), "FY2025") == ("none", None)


def test_a_rerun_with_the_tables_in_another_order_finds_the_verdicts(tmp_path: Path):
    store = VerdictStore(tmp_path)
    first_run = make_verdict(table_index=0, run="a" * 32)
    store.append(first_run)
    # The second run returned this table second; its key is built from its columns only.
    again = CellKey(SHA, ("Project", "Amount"), 3, 1, "Amount")
    status, found = store.apply(again, "1,200")
    assert status == "reviewed"
    assert found == first_run
    assert store.apply(CellKey(SHA, ("Amount", "Project"), 3, 1, "Amount"), "1,200")[0] == "none"
    assert store.apply(CellKey("cd" * 32, COLUMNS, 3, 1, "Amount"), "1,200")[0] == "none"


def test_two_threads_appending_give_whole_lines(tmp_path: Path):
    store = VerdictStore(tmp_path)

    def work(thread: int) -> None:
        for i in range(200):
            store.append(make_verdict(cell_key(row=thread * 1000 + i), note="x" * 300))

    threads = [threading.Thread(target=work, args=(n,)) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = (tmp_path / "review" / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 400
    assert all(Verdict.from_line(line + "\n") for line in lines)
    assert len(store.latest()) == 400
    assert store.skipped == 0


# --- validate ---------------------------------------------------------------------------------
def test_validate_accepts_each_kind():
    validate("correct", extracted="a", value=None, category=None, note="")
    validate("unsure", extracted="a", value=None, category=None, note="n" * 5000)
    validate("changed", extracted="a", value="b", category="other", note="")
    validate("changed", extracted="a", value="", category="dropped_word", note="")
    validate("changed", extracted="a", value="b" * 5000, category="other", note="")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"verdict": "maybe"}, "verdict"),
        ({"verdict": "changed", "value": "b"}, "wrong"),
        ({"verdict": "changed", "value": "b", "category": "nope"}, "wrong"),
        ({"verdict": "changed", "category": "other"}, "right value"),
        ({"verdict": "changed", "value": "a", "category": "other"}, "same"),
        ({"verdict": "changed", "value": "b" * 5001, "category": "other"}, "5,000"),
        ({"verdict": "correct", "note": "n" * 5001}, "5,000"),
    ],
)
def test_validate_refuses_each_bad_input(args: dict, message: str):
    full: dict[str, Any] = {
        "verdict": "correct",
        "extracted": "a",
        "value": None,
        "category": None,
        "note": "",
    }
    with pytest.raises(ValueError, match=message):
        validate(**{**full, **args})


# --- drafts -----------------------------------------------------------------------------------
def test_drafts_round_trip_and_clear(tmp_path: Path):
    drafts = DraftStore(tmp_path)
    assert drafts.get(cell_key()) is None
    assert not (tmp_path / "review").exists()
    saved = drafts.put(cell_key(), "a note", "1,250", "wrong_number")
    assert (saved.note, saved.value, saved.category) == ("a note", "1,250", "wrong_number")
    assert saved.saved_at.endswith("Z")
    assert DraftStore(tmp_path).get(cell_key()) == saved
    extra = ExtraKey(SHA, "Fiscal year", 5)
    drafts.put(extra, "", None, None)
    newer = drafts.put(cell_key(), "newer", None, None)
    assert drafts.get(cell_key()) == newer
    assert newer.note == "newer"
    assert drafts.get(extra) is not None
    drafts.clear(cell_key())
    assert drafts.get(cell_key()) is None
    assert drafts.get(extra) is not None
    drafts.clear(cell_key())  # clearing what is not there is not an error


def test_a_damaged_drafts_file_is_empty_and_kept_aside(tmp_path: Path):
    folder = tmp_path / "review"
    folder.mkdir()
    (folder / "drafts.json").write_text("{not json", encoding="utf-8")
    drafts = DraftStore(tmp_path)
    assert drafts.get(cell_key()) is None
    assert (folder / "drafts.json.bad").read_text(encoding="utf-8") == "{not json"
    assert not (folder / "drafts.json").exists()
    fresh = drafts.put(cell_key(), "fresh", None, None)
    assert drafts.get(cell_key()) == fresh


def test_threads_putting_drafts_lose_none(tmp_path: Path):
    drafts = DraftStore(tmp_path)

    def work(thread: int) -> None:
        for i in range(25):
            drafts.put(cell_key(row=thread * 100 + i), "n", None, None)

    threads = [threading.Thread(target=work, args=(n,)) for n in (1, 2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(drafts.get(cell_key(row=n * 100 + i)) for n in (1, 2, 3) for i in range(25))


def test_the_module_imports_only_the_standard_library_and_storage():
    source = Path(verdicts.__file__ or "").read_text(encoding="utf-8")
    for name in ("pandas", "polars", "pymupdf", "fitz", "http", "pydantic"):
        assert f"import {name}" not in source
        assert f"from {name}" not in source
