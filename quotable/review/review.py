"""
The review API (spec 013 task 008, requirements D1 to D9, E and F): queue, verdicts, drafts.

``GET /api/queue`` answers the queue screen and the queue bar: the counts, the queue, the first
unreviewed item and the statistics of section E, all computed from the stored runs and the
verdicts (:mod:`quotable.review.queue`). ``POST /api/verdicts`` validates and appends one verdict;
the cell's extracted value, status, table and file name are read from the run on the server, never
from the body. ``PUT /api/drafts`` keeps a note and half-typed value until a verdict is saved.
Nothing but ``review/verdicts.jsonl`` and ``review/drafts.json`` is ever written.
"""

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from quotable.review import sources
from quotable.review.browse import verdict_json
from quotable.review.queue import (
    STATUSES,
    Item,
    QueueSettings,
    counts_by_status,
    population,
    review_state,
    sample,
    statistics,
    suggested_size,
)
from quotable.review.routing import BadRequest, NotFound, Request, Route, ServerError
from quotable.review.verdicts import (
    CATEGORIES,
    MAX_TEXT,
    Key,
    Verdict,
    key_from_json,
    now,
    validate,
)
from quotable.runs import Run, RunSummary, list_runs

# A cell can be reviewed whatever its status.
ALL_STATUSES = (*STATUSES, "empty", "not_on_page")


# --- reading a request -------------------------------------------------------------------------
def _object(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        msg = "the body must be a JSON object"
        raise BadRequest(msg)
    return body


def _text(body: Mapping[str, Any], name: str, default: str | None = None) -> str:
    value = body.get(name, default)
    if not isinstance(value, str):
        msg = f"{name} must be text"
        raise BadRequest(msg)
    return value


def _optional_text(body: Mapping[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        msg = f"{name} must be text or null"
        raise BadRequest(msg)
    return value


def _key(body: Mapping[str, Any]) -> Key:
    try:
        return key_from_json(body.get("key"))
    except ValueError as err:
        raise BadRequest(str(err)) from None


def _settings(values: Mapping[str, str]) -> QueueSettings:
    try:
        return QueueSettings.from_query(values)
    except ValueError as err:
        raise BadRequest(str(err)) from None


def _settings_from_json(data: object) -> QueueSettings:
    """Read settings in the form ``QueueSettings.to_dict`` gives."""
    if not isinstance(data, dict):
        msg = "queue must be an object"
        raise BadRequest(msg)
    values: dict[str, str] = {}
    for name, value in data.items():
        if value is None:
            continue
        if isinstance(value, list):
            values[name] = ",".join(str(v) for v in value)
        elif isinstance(value, bool):
            values[name] = "1" if value else "0"
        else:
            values[name] = str(value)
    return _settings(values)


def _why(err: OSError) -> str:
    return err.strerror or str(err)


# --- the queue ---------------------------------------------------------------------------------
def _runs_in_scope(project: Path, settings: QueueSettings) -> list[Run]:
    """Return the chosen run, or the newest readable run of each document."""
    if settings.run is not None:
        return [sources.load(project, settings.run)]
    summaries, _ = list_runs(project)
    newest: dict[str, RunSummary] = {}
    for summary in summaries:
        best = newest.get(summary.sha256)
        if best is None or (summary.started, summary.id) > (best.started, best.id):
            newest[summary.sha256] = summary
    runs = []
    for summary in newest.values():
        with contextlib.suppress(NotFound):
            runs.append(sources.load(project, summary.id))
    return runs


def _label(state: str, found: Verdict | None) -> str:
    if state == "stale" and found is not None:
        return f"Stale · was {found.extracted}"
    return {
        "correct": "Correct",
        "changed": "Changed",
        "unsure": "Can't tell",
    }.get(state, "Not reviewed")


def _entry(item: Item, verdicts: Mapping[Key, Verdict]) -> dict[str, Any]:
    state = review_state(item, verdicts)
    return {
        "run": item.run,
        "short_run": item.run[:8],
        "name": item.name,
        "table": item.table_index,
        "table_number": item.table_index + 1,
        "table_label": item.table_label,
        "page": item.page,
        "row": item.row,
        "column": item.column,
        "extra": item.extra,
        "status": item.status,
        "key": item.key.to_json(),
        "review": {"state": state, "label": _label(state, verdicts.get(item.key))},
    }


def _first_unreviewed(
    queue: Sequence[Item], verdicts: Mapping[Key, Verdict], after: int = -1
) -> int | None:
    """Return the first item past index ``after`` that is not reviewed, wrapping to the start."""
    for step in range(1, len(queue) + 1):
        at = (after + step) % len(queue)
        if review_state(queue[at], verdicts) in ("none", "stale"):
            return at
    return None


def get_queue(request: Request) -> dict[str, Any]:
    """``GET /api/queue?<QueueSettings>``: counts, queue, first unreviewed item, statistics."""
    settings = _settings({name: values[-1] for name, values in request.query.items() if values})
    project = request.project_dir
    runs = _runs_in_scope(project, settings)
    pop = population(runs, settings)
    queue = sample(pop, settings)
    verdicts = sources.stores(project)[0].latest()
    return {
        "settings": settings.to_dict(),
        "counts": counts_by_status(runs, settings),
        "matching": len(pop),
        "suggested": suggested_size(settings.margin, settings.confidence, len(pop)),
        "queue": [_entry(item, verdicts) for item in queue],
        "first_unreviewed": _first_unreviewed(queue, verdicts),
        "stats": asdict(statistics(pop, queue, verdicts, settings)),
    }


# --- verdicts ----------------------------------------------------------------------------------
def _find(run: Run, key: Key) -> Item:
    for item in population([run], QueueSettings(statuses=ALL_STATUSES, run=run.summary.id)):
        if item.key == key:
            return item
    msg = "that cell is not in this run"
    raise NotFound(msg)


def save_verdict(request: Request) -> dict[str, Any]:
    """``POST /api/verdicts``: validate and append a verdict; return it and the next item."""
    body = _object(request.body)
    key = _key(body)
    kind = _text(body, "verdict")
    note = _text(body, "note", "")
    changed = kind == "changed"
    value, category = _optional_text(body, "value"), _optional_text(body, "category")
    if not changed:
        value = category = None
    settings = None if body.get("queue") is None else _settings_from_json(body["queue"])
    project = request.project_dir
    run = sources.load(project, _text(body, "run"))
    item = _find(run, key)
    try:
        validate(kind, extracted=item.extracted, value=value, category=category, note=note)
    except ValueError as err:
        raise BadRequest(str(err)) from None
    scope = [] if settings is None else _runs_in_scope(project, settings)
    saved = Verdict(
        time=now(),
        run=item.run,
        name=item.name,
        table_index=item.table_index,
        table_label=item.table_label,
        table_columns=item.table_columns,
        key=item.key,
        extracted=item.extracted,
        status=item.status,
        verdict=kind,
        value=value,
        category=category,
        note=note,
        queue={} if settings is None else settings.to_dict(),
    )
    verdicts, drafts = sources.stores(project)
    try:
        verdicts.append(saved)
    except OSError as err:
        msg = f"The verdict could not be saved: {_why(err)}"
        raise ServerError(msg) from err
    # The verdict is safe now; a draft that stays behind only brings the old note back.
    with contextlib.suppress(OSError):
        drafts.clear(item.key)
    return {"verdict": verdict_json(saved), "next": _next(settings, scope, item, verdicts.latest())}


def _next(
    settings: QueueSettings | None,
    scope: Sequence[Run],
    saved: Item,
    verdicts: Mapping[Key, Verdict],
) -> dict[str, Any] | None:
    """Return the next unreviewed item of the queue after ``saved``, if there is one."""
    if settings is None:
        return None
    queue = sample(population(scope, settings), settings)
    after = next((i for i, item in enumerate(queue) if item.key == saved.key), -1)
    found = _first_unreviewed(queue, verdicts, after)
    return None if found is None else {"index": found, "item": _entry(queue[found], verdicts)}


# --- drafts ------------------------------------------------------------------------------------
def put_draft(request: Request) -> dict[str, Any]:
    """``PUT /api/drafts``: keep a note and half-typed value for a cell; return ``saved_at``."""
    body = _object(request.body)
    key = _key(body)
    note = _text(body, "note", "")
    value = _optional_text(body, "value")
    category = _optional_text(body, "category")
    if len(note) > MAX_TEXT:
        msg = f"The note can have at most {MAX_TEXT:,} characters."
        raise BadRequest(msg)
    if value is not None and len(value) > MAX_TEXT:
        msg = f"The right value can have at most {MAX_TEXT:,} characters."
        raise BadRequest(msg)
    if category is not None and category not in CATEGORIES:
        msg = "Unknown error category."
        raise BadRequest(msg)
    try:
        draft = sources.stores(request.project_dir)[1].put(key, note, value, category)
    except OSError as err:
        msg = f"The draft could not be saved: {_why(err)}"
        raise ServerError(msg) from err
    return {"saved_at": draft.saved_at}


ROUTES: list[Route] = [
    Route("GET", r"/api/queue", get_queue),
    Route("POST", r"/api/verdicts", save_verdict),
    Route("PUT", r"/api/drafts", put_draft),
]
