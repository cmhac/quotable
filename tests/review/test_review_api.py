"""The review API (spec 013 task 008): the queue, verdicts and drafts over HTTP."""

import http.client
import json
from dataclasses import asdict
from typing import Any
from urllib.parse import quote

import pytest

from quotable.review.queue import (
    STATUSES,
    Item,
    QueueSettings,
    counts_by_status,
    population,
    sample,
    statistics,
    suggested_size,
)
from quotable.review.verdicts import CATEGORIES, DraftStore, Verdict, VerdictStore
from quotable.runs import load_run
from tests.review.test_browse_api import App, edit_run, give


# --- helpers -----------------------------------------------------------------------------------
def send(app: App, method: str, path: str, payload: Any) -> tuple[int, Any]:  # noqa: ANN401
    port = app.server.server_address[1]
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def run_items(app: App, label: str, **settings: Any) -> list[Item]:  # noqa: ANN401
    run = app.id[label]
    return population([load_run(app.project, run)], QueueSettings(run=run, **settings))


def query_of(settings: QueueSettings) -> str:
    parts = []
    for name, value in settings.to_dict().items():
        if value is None:
            continue
        text = (
            ",".join(value)
            if isinstance(value, list)
            else str(int(value) if isinstance(value, bool) else value)
        )
        parts.append(f"{name}={quote(text, safe='')}")
    return "&".join(parts)


def queue_of(app: App, settings: QueueSettings) -> dict[str, Any]:
    return app.json(f"/api/queue?{query_of(settings)}")


def body_for(  # noqa: PLR0913, PLR0917
    app: App,
    label: str,
    item: Item,
    kind: str = "correct",
    settings: QueueSettings | None = None,
    **over: Any,  # noqa: ANN401
) -> dict[str, Any]:
    queue = settings or QueueSettings(run=app.id[label])
    body = {
        "key": item.key.to_json(),
        "run": app.id[label],
        "verdict": kind,
        "value": None,
        "category": None,
        "note": "",
        "queue": queue.to_dict(),
    }
    return {**body, **over}


def save(app: App, label: str, item: Item, kind: str = "correct", **over: Any):  # noqa: ANN201, ANN401
    return send(app, "POST", "/api/verdicts", body_for(app, label, item, kind, **over))


def written(app: App) -> list[dict[str, Any]]:
    path = app.project / "review" / "verdicts.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def give_item(app: App, label: str, item: Item, kind: str = "correct") -> None:
    assert item.row is not None
    give(app, label, item.table_index, item.page, item.row, item.column, kind)


def cell_path(app: App, label: str, item: Item) -> str:
    return f"{app.run(label)}/tables/{item.table_index}/cells/{item.page}/{item.row}/{item.column}"


# --- GET /api/queue ----------------------------------------------------------------------------
def test_the_queue_of_a_run_is_its_flagged_cells_in_reading_order(app):
    run = app.id["senate"]
    data = app.json(f"/api/queue?run={run}")
    items = run_items(app, "senate")
    assert data["matching"] == len(items) == 75
    assert data["settings"] == QueueSettings(run=run).to_dict()
    assert data["counts"] == counts_by_status([load_run(app.project, run)], QueueSettings(run=run))
    assert (data["counts"]["ungrounded"], data["counts"]["misplaced"]) == (74, 1)
    assert data["suggested"] == suggested_size(8.0, 95, 75)
    assert [(e["table"], e["page"], e["row"], e["column"]) for e in data["queue"]] == [
        (i.table_index, i.page, i.row, i.column) for i in items
    ]
    assert data["first_unreviewed"] == 0


def test_a_queue_entry_says_where_the_item_is_and_how_it_was_reviewed(app):
    items = run_items(app, "senate")
    entry = queue_of(app, QueueSettings(run=app.id["senate"]))["queue"][0]
    item = items[0]
    assert entry["run"] == item.run
    assert entry["short_run"] == item.run[:8]
    assert entry["name"] == item.name
    assert (entry["table"], entry["table_number"]) == (item.table_index, item.table_index + 1)
    assert entry["table_label"] == item.table_label
    assert (entry["page"], entry["row"], entry["column"]) == (item.page, item.row, item.column)
    assert entry["extra"] is False
    assert entry["status"] == item.status
    assert entry["key"] == item.key.to_json()
    assert entry["review"] == {"state": "none", "label": "Not reviewed"}


def test_the_review_state_and_label_of_each_entry(app):
    items = run_items(app, "senate")
    give_item(app, "senate", items[0], "correct")
    give_item(app, "senate", items[1], "changed")
    give_item(app, "senate", items[2], "unsure")
    row = items[3]
    give(app, "senate", row.table_index, row.page, row.row or 0, row.column, judged="old")
    data = queue_of(app, QueueSettings(run=app.id["senate"]))
    reviews = [e["review"] for e in data["queue"][:5]]
    assert [r["state"] for r in reviews] == ["correct", "changed", "unsure", "stale", "none"]
    assert [r["label"] for r in reviews[:3]] == ["Correct", "Changed", "Can't tell"]
    assert reviews[3]["label"] == "Stale · was old"
    assert data["first_unreviewed"] == 3  # a stale verdict does not count


def test_the_first_unreviewed_item_follows_the_verdicts(app):
    items = run_items(app, "senate")
    settings = QueueSettings(run=app.id["senate"])
    for item in items[:2]:
        give_item(app, "senate", item)
    assert queue_of(app, settings)["first_unreviewed"] == 2
    for item in items[2:]:
        give_item(app, "senate", item)
    assert queue_of(app, settings)["first_unreviewed"] is None


def test_a_sample_is_the_seeded_sample_of_the_population_and_repeats(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=10, seed=3)
    first, second = queue_of(app, settings), queue_of(app, settings)
    assert first == second
    expected = sample(run_items(app, "senate"), settings)
    assert [e["key"] for e in first["queue"]] == [i.key.to_json() for i in expected]
    assert (first["matching"], len(first["queue"])) == (75, 10)
    other = queue_of(
        app, QueueSettings(run=app.id["senate"], mode="sample", sample_size=10, seed=4)
    )
    assert [e["key"] for e in other["queue"]] != [e["key"] for e in first["queue"]]


def test_the_statistics_are_those_of_the_queue(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=6, seed=2)
    queue = sample(run_items(app, "senate"), settings)
    for item, kind in zip(queue[:3], ("correct", "changed", "unsure"), strict=True):
        give_item(app, "senate", item, kind)
    expected = statistics(
        run_items(app, "senate"), queue, VerdictStore(app.project).latest(), settings
    )
    stats = queue_of(app, settings)["stats"]
    assert stats == json.loads(json.dumps(asdict(expected)))
    assert (stats["reviewed"], stats["judged"], stats["changed"], stats["unsure"]) == (3, 2, 1, 1)


def test_statistics_can_be_rebuilt_from_the_verdict_file_alone(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=8, seed=5)
    queue = sample(run_items(app, "senate"), settings)
    for item, kind in zip(
        queue, ("correct", "changed", "correct", "unsure", "changed"), strict=False
    ):
        extra = {"value": "other", "category": "other"} if kind == "changed" else {}
        status, _ = save(app, "senate", item, kind, settings=settings, **extra)
        assert status == 200
    rebuilt = statistics(
        run_items(app, "senate"), queue, VerdictStore(app.project).latest(), settings
    )
    assert queue_of(app, settings)["stats"] == json.loads(json.dumps(asdict(rebuilt)))


def test_all_runs_take_the_newest_run_of_each_document(app):
    data = queue_of(app, QueueSettings(statuses=("exact",)))
    runs = {e["run"] for e in data["queue"]}
    assert app.id["simple_new"] in runs
    assert app.id["simple_old"] not in runs
    assert runs <= set(app.id.values())
    assert len(runs) == 5


def test_an_unreadable_run_does_not_stop_the_all_runs_queue(app):
    bad = app.project / "runs" / ("ab" * 16)
    bad.mkdir()
    (bad / "run.json").write_text("{not json")
    assert queue_of(app, QueueSettings(statuses=("exact",)))["matching"] > 0


def test_extra_fields_are_queue_entries_without_a_row(app):
    items = run_items(app, "extras", statuses=STATUSES)
    extra = next(i for i in items if i.extra)
    data = queue_of(app, QueueSettings(run=app.id["extras"], statuses=STATUSES))
    entry = next(e for e in data["queue"] if e["key"] == extra.key.to_json())
    assert entry["extra"] is True
    assert entry["row"] is None
    assert entry["column"] == extra.column


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("statuses=nonsense", "unknown status 'nonsense'"),
        ("confidence=97", "confidence must be one of 80, 90, 95, 99"),
        ("mode=everything", "mode must be one of all, sample"),
        ("sample_size=0", "sample_size must be at least 1"),
    ],
)
def test_bad_settings_are_a_400_with_the_message(app, query, message):
    assert app.error(f"/api/queue?{query}", 400) == message


def test_an_unknown_run_is_a_404(app):
    assert app.error(f"/api/queue?run={'0' * 32}", 404)
    assert app.error("/api/queue?run=nonsense", 404)


# --- POST /api/verdicts ------------------------------------------------------------------------
def test_a_verdict_is_appended_with_every_field_of_the_format(app):
    run = load_run(app.project, app.id["senate"])
    settings = QueueSettings(run=run.summary.id, mode="sample", sample_size=7, seed=9)
    item = sample(run_items(app, "senate"), settings)[0]
    status, data = save(app, "senate", item, "unsure", settings=settings, note="hard to read")
    assert status == 200
    (line,) = written(app)
    assert line["v"] == 1
    assert line["time"].endswith("Z")
    assert line["run"] == run.summary.id
    assert line["name"] == run.summary.name
    table = run.tables[item.table_index]
    assert line["table"] == {
        "index": item.table_index,
        "label": table.label,
        "columns": table.columns,
    }
    assert line["key"] == item.key.to_json()
    assert (line["extracted"], line["status"]) == (item.extracted, item.status)
    assert (line["verdict"], line["value"], line["category"]) == ("unsure", None, None)
    assert line["note"] == "hard to read"
    assert line["queue"] == settings.to_dict()
    saved = Verdict.from_line(json.dumps(line))
    assert saved.key == item.key
    assert data["verdict"]["verdict"] == "unsure"
    assert data["verdict"]["note"] == "hard to read"
    assert data["verdict"]["extracted"] == item.extracted


def test_the_extracted_value_and_status_come_from_the_run_not_the_body(app):
    item = run_items(app, "senate")[0]
    status, _ = save(
        app, "senate", item, extracted="forged", status="exact", name="forged.pdf", time="x"
    )
    assert status == 200
    (line,) = written(app)
    assert line["extracted"] == item.extracted != "forged"
    assert line["status"] == item.status != "exact"
    assert line["name"] != "forged.pdf"
    assert line["time"] != "x"


def test_a_changed_verdict_keeps_the_right_value_and_the_category(app):
    item = run_items(app, "senate")[0]
    status, data = save(app, "senate", item, "changed", value="Right Value", category="spacing")
    assert status == 200
    (line,) = written(app)
    assert (line["verdict"], line["value"], line["category"]) == (
        "changed",
        "Right Value",
        "spacing",
    )
    assert data["verdict"]["value"] == "Right Value"
    assert data["verdict"]["category"] == "spacing"


def test_value_and_category_are_dropped_unless_the_verdict_is_changed(app):
    item = run_items(app, "senate")[0]
    assert save(app, "senate", item, "correct", value="x", category="other")[0] == 200
    (line,) = written(app)
    assert (line["value"], line["category"]) == (None, None)


def test_a_changed_verdict_can_have_a_blank_right_value(app):
    item = run_items(app, "senate")[0]
    assert item.extracted
    status, _ = save(app, "senate", item, "changed", value="", category="hallucination")
    assert status == 200
    assert written(app)[0]["value"] == ""


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"verdict": "changed", "value": "x"}, "Choose why the model was wrong."),
        (
            {"verdict": "changed", "value": "x", "category": "invented"},
            "Choose why the model was wrong.",
        ),
        (
            {"verdict": "changed", "category": "other"},
            "Give the right value (blank means the cell should be empty).",
        ),
        ({"verdict": "correct", "note": "n" * 5001}, "The note can have at most 5,000 characters."),
        (
            {"verdict": "changed", "category": "other", "value": "v" * 5001},
            "The right value can have at most 5,000 characters.",
        ),
        ({"verdict": "approved"}, "The verdict must be one of correct, changed, unsure."),
    ],
)
def test_a_verdict_that_cannot_be_saved_is_a_400_with_the_message(app, over, message):
    item = run_items(app, "senate")[0]
    status, data = send(app, "POST", "/api/verdicts", body_for(app, "senate", item, **over))
    assert (status, data["error"]) == (400, message)
    assert written(app) == []


def test_changed_to_the_same_value_is_refused(app):
    item = run_items(app, "senate")[0]
    status, data = save(app, "senate", item, "changed", value=item.extracted, category="other")
    assert (status, data["error"]) == (
        400,
        "The right value is the same as the extracted one.",
    )
    assert written(app) == []


def test_a_note_of_5000_characters_is_accepted(app):
    item = run_items(app, "senate")[0]
    assert save(app, "senate", item, note="n" * 5000)[0] == 200


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.pop("key"),
        lambda b: b.update(key={"sha256": 1}),
        lambda b: b.update(key="a string"),
        lambda b: b.pop("run"),
        lambda b: b.update(run=5),
        lambda b: b.pop("verdict"),
        lambda b: b.update(note=5),
        lambda b: b.update(value=5),
        lambda b: b.update(category=5),
        lambda b: b.update(queue="everything"),
        lambda b: b.update(queue={"confidence": 97}),
    ],
)
def test_a_malformed_body_is_a_400(app, mutate):
    item = run_items(app, "senate")[0]
    body = body_for(app, "senate", item)
    mutate(body)
    status, data = send(app, "POST", "/api/verdicts", body)
    assert status == 400
    assert data["error"]
    assert written(app) == []


def test_a_body_that_is_not_an_object_is_a_400(app):
    assert send(app, "POST", "/api/verdicts", [1, 2])[0] == 400


def test_a_cell_that_is_not_in_the_run_is_a_404(app):
    item = run_items(app, "senate")[0]
    other = app.id["simple_new"]  # another document
    status, _ = send(app, "POST", "/api/verdicts", body_for(app, "senate", item, run=other))
    assert status == 404
    status, _ = send(app, "POST", "/api/verdicts", body_for(app, "senate", item, run="0" * 32))
    assert status == 404
    bad_row = {**item.key.to_json(), "row": 9999}
    status, _ = send(app, "POST", "/api/verdicts", body_for(app, "senate", item, key=bad_row))
    assert status == 404
    assert written(app) == []


def test_without_a_queue_the_verdict_has_empty_settings_and_no_next_item(app):
    item = run_items(app, "senate")[0]
    status, data = save(app, "senate", item, queue=None)
    assert status == 200
    assert written(app)[0]["queue"] == {}
    assert data["next"] is None


def test_an_extra_field_verdict_is_keyed_by_name_and_printing_page(app):
    item = next(i for i in run_items(app, "extras", statuses=STATUSES) if i.extra)
    settings = QueueSettings(run=app.id["extras"], statuses=STATUSES)
    status, _ = save(app, "extras", item, settings=settings)
    assert status == 200
    key = written(app)[0]["key"]
    assert key == {"sha256": item.sha256, "extra": item.column, "page": item.page}
    entry = next(e for e in queue_of(app, settings)["queue"] if e["key"] == item.key.to_json())
    assert entry["review"]["state"] == "correct"


def test_the_latest_verdict_of_a_cell_counts(app):
    items = run_items(app, "senate")
    settings = QueueSettings(run=app.id["senate"])
    save(app, "senate", items[0], "unsure")
    save(app, "senate", items[0], "changed", value="x", category="other")
    assert len(written(app)) == 2
    assert queue_of(app, settings)["queue"][0]["review"]["state"] == "changed"


# --- next unreviewed ---------------------------------------------------------------------------
def test_the_next_unreviewed_item_comes_after_the_saved_one(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=5, seed=7)
    queue = sample(run_items(app, "senate"), settings)
    give_item(app, "senate", queue[0])
    give_item(app, "senate", queue[1])
    give_item(app, "senate", queue[3])
    status, data = save(app, "senate", queue[2], settings=settings)
    assert status == 200
    assert data["next"]["index"] == 4
    assert data["next"]["item"]["key"] == queue[4].key.to_json()
    assert data["next"]["item"]["review"]["state"] == "none"


def test_the_next_unreviewed_item_wraps_to_the_start_and_ends_with_none(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=5, seed=7)
    queue = sample(run_items(app, "senate"), settings)
    for item in queue[1:4]:
        give_item(app, "senate", item)
    _, data = save(app, "senate", queue[4], settings=settings)
    assert data["next"]["index"] == 0
    assert data["next"]["item"]["key"] == queue[0].key.to_json()
    _, data = save(app, "senate", queue[0], settings=settings)
    assert data["next"] is None


def test_a_stale_item_counts_as_unreviewed_for_the_next_item(app):
    settings = QueueSettings(run=app.id["senate"], mode="sample", sample_size=4, seed=1)
    queue = sample(run_items(app, "senate"), settings)
    give_item(app, "senate", queue[0])
    row = queue[2]
    give(app, "senate", row.table_index, row.page, row.row or 0, row.column, judged="old")
    _, data = save(app, "senate", queue[1], settings=settings)
    assert data["next"]["index"] == 2


# --- verdicts across runs ----------------------------------------------------------------------
def test_a_verdict_counts_on_a_rerun_with_the_same_value_and_is_stale_with_another(app):
    old, new = app.id["simple_old"], app.id["simple_new"]
    items = run_items(app, "simple_old", statuses=STATUSES)
    first, second = items[0], items[1]
    old_settings = QueueSettings(run=old, statuses=STATUSES)
    assert save(app, "simple_old", first, settings=old_settings)[0] == 200
    assert save(app, "simple_old", second, settings=old_settings)[0] == 200

    def change(data: dict) -> None:
        for row in data["tables"][0]["rows"]:
            if (row["page"], row["row"]) == (second.page, second.row):
                row["values"][second.column] = "a different value"

    edit_run(app.project, new, big=change)
    entries = {
        (e["row"], e["column"]): e["review"]
        for e in queue_of(app, QueueSettings(run=new, statuses=STATUSES))["queue"]
    }
    assert entries[first.row, first.column]["state"] == "correct"
    assert entries[second.row, second.column]["state"] == "stale"
    assert entries[second.row, second.column]["label"].startswith("Stale · was ")


# --- drafts ------------------------------------------------------------------------------------
def draft_body(item: Item, **over: Any) -> dict[str, Any]:  # noqa: ANN401
    body = {"key": item.key.to_json(), "note": "check the scan", "value": "half", "category": None}
    return {**body, **over}


def test_a_draft_round_trips_through_the_cell(app):
    item = run_items(app, "senate")[0]
    status, data = send(app, "PUT", "/api/drafts", draft_body(item, category="spacing"))
    assert status == 200
    assert data["saved_at"].endswith("Z")
    shown = app.json(cell_path(app, "senate", item))["review"]["draft"]
    assert shown == {
        "note": "check the scan",
        "value": "half",
        "category": "spacing",
        "saved_at": data["saved_at"],
    }


def test_a_later_draft_replaces_the_earlier_one(app):
    item = run_items(app, "senate")[0]
    send(app, "PUT", "/api/drafts", draft_body(item))
    send(app, "PUT", "/api/drafts", draft_body(item, note="second", value=None))
    shown = app.json(cell_path(app, "senate", item))["review"]["draft"]
    assert (shown["note"], shown["value"]) == ("second", None)


def test_saving_a_verdict_clears_the_draft(app):
    items = run_items(app, "senate")
    send(app, "PUT", "/api/drafts", draft_body(items[0]))
    send(app, "PUT", "/api/drafts", draft_body(items[1]))
    assert save(app, "senate", items[0])[0] == 200
    assert DraftStore(app.project).get(items[0].key) is None
    assert DraftStore(app.project).get(items[1].key) is not None
    assert app.json(cell_path(app, "senate", items[0]))["review"]["draft"] is None


@pytest.mark.parametrize(
    "over",
    [
        {"note": "n" * 5001},
        {"value": "v" * 5001},
        {"category": "invented"},
        {"note": 5},
        {"value": 5},
        {"category": 5},
        {"key": {"sha256": 1}},
        {"key": None},
    ],
)
def test_a_draft_that_cannot_be_kept_is_a_400(app, over):
    item = run_items(app, "senate")[0]
    status, data = send(app, "PUT", "/api/drafts", draft_body(item, **over))
    assert status == 400
    assert data["error"]
    assert DraftStore(app.project).get(item.key) is None


def test_a_draft_may_have_every_category_and_a_note_at_the_limit(app):
    item = run_items(app, "senate")[0]
    for category in (*CATEGORIES, None):
        over = {"category": category, "note": "n" * 5000}
        assert send(app, "PUT", "/api/drafts", draft_body(item, **over))[0] == 200


def test_a_body_that_is_not_an_object_is_a_400_for_drafts(app):
    assert send(app, "PUT", "/api/drafts", "text")[0] == 400


def test_drafts_only_take_put(app):
    status, response, _ = app.get("/api/drafts")
    assert status == 405


def test_a_draft_that_cannot_be_written_is_a_500_with_a_message(app, monkeypatch):
    def fail(self, key, note, value, category):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(DraftStore, "put", fail)
    status, data = send(app, "PUT", "/api/drafts", draft_body(run_items(app, "senate")[0]))
    assert status == 500
    assert "draft could not be saved" in data["error"]
    assert "No space left on device" in data["error"]


# --- failures ----------------------------------------------------------------------------------
def test_a_failed_append_is_a_500_with_a_message_and_writes_nothing(app, monkeypatch):
    item = run_items(app, "senate")[0]
    send(app, "PUT", "/api/drafts", draft_body(item))

    def fail(self, verdict):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(VerdictStore, "append", fail)
    status, data = save(app, "senate", item)
    assert status == 500
    assert "verdict could not be saved" in data["error"]
    assert "No space left on device" in data["error"]
    assert not (app.project / "review" / "verdicts.jsonl").exists()
    assert DraftStore(app.project).get(item.key) is not None  # nothing is lost


def test_a_draft_that_cannot_be_cleared_does_not_undo_the_saved_verdict(app, monkeypatch):
    item = run_items(app, "senate")[0]

    def fail(self, key):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(DraftStore, "clear", fail)
    status, _ = save(app, "senate", item)
    assert status == 200
    assert len(written(app)) == 1
