"""The gold files (spec 016 task 004): validation, limits, safe writes."""

import json
import threading
from pathlib import Path

import pytest

from quotable.gold.store import (
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_TABLES,
    MAX_TEXT,
    GoldPage,
    GoldStore,
    Invalid,
    Sample,
    SampleDoc,
    SampleStore,
    StoreError,
    validate_page,
)

SHA = "a" * 64
OTHER = "b" * 64


def sample() -> Sample:
    return Sample(
        1, 3, "2026-11-10T00:00:00Z", [SampleDoc(SHA, "a.pdf", 10)], [(SHA, 3), (SHA, 4), (SHA, 5)]
    )


def body(**changes):
    base = {
        "tables": [{"columns": ["Name", "Amount"], "rows": [["Ann", "1"]]}],
        "done": True,
        "seconds": 12.5,
    }
    return base | changes


def test_a_valid_page_is_accepted():
    record = validate_page(body(), SHA, 3, sample())
    assert record.tables[0].rows == [["Ann", "1"]]
    assert record.done
    assert record.seconds == 12.5
    assert record.updated.endswith("Z")


def test_a_page_outside_the_sample_is_refused():
    with pytest.raises(Invalid, match="not in the sample"):
        validate_page(body(), SHA, 9, sample())
    with pytest.raises(Invalid, match="not in the sample"):
        validate_page(body(), OTHER, 3, sample())
    with pytest.raises(Invalid, match="not in the sample"):
        validate_page(body(), SHA, 3, None)


def test_untouched_empty_rows_at_the_bottom_are_dropped_but_a_blank_middle_row_stays():
    rows = [["a", "b"], ["", ""], ["c", ""], ["", ""], ["", ""]]
    record = validate_page(body(tables=[{"columns": ["X", "Y"], "rows": rows}]), SHA, 3, sample())
    assert record.tables[0].rows == [["a", "b"], ["", ""], ["c", ""]]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"tables": [{"columns": ["A"], "rows": []}] * (MAX_TABLES + 1)}, "at most 10"),
        ({"tables": [{"columns": ["A"] * (MAX_COLUMNS + 1), "rows": []}]}, "at most 40"),
        ({"tables": [{"columns": ["A"], "rows": [["x"]] * (MAX_ROWS + 1)}]}, "at most 400"),
        ({"tables": [{"columns": ["A"], "rows": [["x" * (MAX_TEXT + 1)]]}]}, "2000 characters"),
        ({"tables": [{"columns": ["A", "B"], "rows": [["x"]]}]}, "one cell per column"),
        ({"tables": [{"columns": [], "rows": []}]}, "at least one column"),
        ({"done": "yes"}, "true or false"),
        ({"seconds": -1}, "seconds"),
        ({"seconds": 7 * 24 * 3600}, "seconds"),
        ({"seconds": True}, "seconds"),
        ({"tables": "x"}, "list of at most"),
    ],
)
def test_every_limit_is_refused_with_a_message_that_names_it(changes, message):
    with pytest.raises(Invalid, match=message):
        validate_page(body(**changes), SHA, 3, sample())


def test_naming_every_column_once_is_needed_only_to_mark_the_page_done():
    unnamed = [{"columns": ["A", ""], "rows": [["1", "2"]]}]
    repeated = [{"columns": ["A", "A "], "rows": []}]
    with pytest.raises(Invalid, match="name every column"):
        validate_page(body(tables=unnamed), SHA, 3, sample())
    with pytest.raises(Invalid, match="name every column"):
        validate_page(body(tables=repeated), SHA, 3, sample())
    assert validate_page(body(tables=unnamed, done=False), SHA, 3, sample()).done is False


def test_a_done_page_with_no_table_means_no_table_here():
    assert validate_page(body(tables=[]), SHA, 3, sample()).tables == []


def test_status_is_new_started_or_done():
    empty = validate_page(
        body(tables=[{"columns": [""], "rows": []}], done=False), SHA, 3, sample()
    )
    assert empty.status == "new"
    named = validate_page(
        body(tables=[{"columns": ["A"], "rows": []}], done=False), SHA, 3, sample()
    )
    assert named.status == "started"
    assert validate_page(body(), SHA, 3, sample()).status == "done"


def test_round_trip_and_last_save_wins(tmp_path: Path):
    store = GoldStore(tmp_path)
    assert store.pages() == {}
    first = store.save(validate_page(body(), SHA, 3, sample()))
    again = validate_page(body(tables=[{"columns": ["N"], "rows": [["z"]]}]), SHA, 3, sample())
    store.save(again)
    pages = store.pages()
    assert list(pages) == [f"{SHA}:3"]
    assert pages[f"{SHA}:3"].tables[0].rows == [["z"]]
    assert first.updated  # the first record was a real record
    assert store.get(SHA, 3) == pages[f"{SHA}:3"]
    assert store.get(SHA, 4) is None


def test_the_file_is_stable_text(tmp_path: Path):
    store = GoldStore(tmp_path)
    store.save(validate_page(body(), SHA, 4, sample()))
    store.save(validate_page(body(), SHA, 3, sample()))
    text = store.path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert text.startswith('{\n "pages": {\n  "' + SHA + ':3"')  # sorted keys, indent 1
    assert json.loads(text)["v"] == 1


def test_two_threads_saving_two_pages_both_survive(tmp_path: Path):
    store = GoldStore(tmp_path)
    s = sample()

    def save(page: int) -> None:
        for _ in range(20):
            store.save(validate_page(body(), SHA, page, s))

    threads = [threading.Thread(target=save, args=(p,)) for p in (3, 4, 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(store.pages()) == [f"{SHA}:3", f"{SHA}:4", f"{SHA}:5"]


def test_an_unreadable_file_is_not_overwritten(tmp_path: Path):
    store = GoldStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreError, match="not valid JSON"):
        store.pages()
    with pytest.raises(StoreError, match="not valid JSON"):
        store.save(validate_page(body(), SHA, 3, sample()))
    assert store.path.read_text(encoding="utf-8") == "{not json"


def test_a_file_of_another_version_is_not_overwritten(tmp_path: Path):
    store = GoldStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text('{"v": 2, "pages": {}}', encoding="utf-8")
    with pytest.raises(StoreError, match="version 1"):
        store.save(validate_page(body(), SHA, 3, sample()))
    assert json.loads(store.path.read_text(encoding="utf-8"))["v"] == 2


def test_a_damaged_record_is_skipped_but_kept_when_another_page_is_saved(tmp_path: Path):
    store = GoldStore(tmp_path)
    store.save(validate_page(body(), SHA, 3, sample()))
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["pages"][f"{SHA}:4"] = {"tables": "oops"}
    store.path.write_text(json.dumps(data), encoding="utf-8")
    assert list(store.pages()) == [f"{SHA}:3"]
    assert store.skipped == [f"{SHA}:4"]
    store.save(validate_page(body(), SHA, 5, sample()))
    assert f"{SHA}:4" in json.loads(store.path.read_text(encoding="utf-8"))["pages"]


def test_the_sample_round_trips_and_an_unreadable_one_is_left_alone(tmp_path: Path):
    store = SampleStore(tmp_path)
    assert store.load() is None
    store.save(sample())
    assert store.load() == sample()
    store.path.write_text('{"v": 1, "seed": "x"}', encoding="utf-8")
    with pytest.raises(StoreError, match="left as it is"):
        store.load()
    assert "seed" in store.path.read_text(encoding="utf-8")


def test_gold_page_is_json_serializable():
    record = validate_page(body(), SHA, 3, sample())
    assert isinstance(record, GoldPage)
    json.dumps(record.to_json())
