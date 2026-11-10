"""
The review app's gold check routes (spec 016): the sample, the typed pages and the score.

See ``specs/016-gold-quality-check/contracts/gold-api.md``. A page is reached by the SHA-256 of a
document in the current sample and a page number, never by a path; the PDF is found through the
newest saved run of that document whose file is still there and unchanged. Nothing here calls a
model, and the only files written are the gold files (and the gold exception in
``.quotable/.gitignore``).
"""

import random
from pathlib import Path
from typing import Any

from quotable.gold.project import score_project
from quotable.gold.report import cells_csv, pages_csv, to_json
from quotable.gold.sample import make_sample
from quotable.gold.score import Progress, Report
from quotable.gold.store import (
    GoldError,
    GoldStore,
    Invalid,
    Sample,
    SampleDoc,
    SampleStore,
    StoreError,
    key,
    validate_page,
)
from quotable.review import sources
from quotable.review.routing import BadRequest, NotFound, Raw, Request, Route, ServerError
from quotable.runs import RunSummary
from quotable.storage import ensure_gold_trackable, gold_ignore_note

PAGE_SAVE_LIMIT = 2 * 1024 * 1024
DEFAULT_SIZE = 20
LEFT_SHOWN = 50
_SHA = r"([0-9a-f]{64})"
_PAGE = r"([0-9]+)"


def _fail(err: GoldError) -> Exception:
    """Return the HTTP error for a gold error: 500 for a file that cannot be used, else 400."""
    return ServerError(str(err)) if isinstance(err, StoreError) else BadRequest(str(err))


def _sample(project: Path) -> Sample | None:
    try:
        return SampleStore(project).load()
    except GoldError as err:
        raise _fail(err) from None


def _documents(project: Path) -> dict[str, RunSummary]:
    """Return, for each document with a saved run, the run to read it through."""
    by_document: dict[str, list[RunSummary]] = {}
    for run in sources.saved_runs(project):
        by_document.setdefault(run.sha256, []).append(run)
    found: dict[str, RunSummary] = {}
    for sha, runs in by_document.items():
        run = sources.usable_run(runs)
        if run is not None:
            found[sha] = run
    return found


def _page_in_sample(request: Request) -> tuple[str, int, Sample]:
    sha, number = request.params[0], int(request.params[1])
    sample = _sample(request.project_dir)
    if sample is None or not sample.has(sha, number):
        raise NotFound("no such page")
    return sha, number, sample


def _document_page(request: Request) -> tuple[str, int]:
    """Any page of a document in the sample: the whole-PDF view shows pages that were not drawn."""
    sha, number = request.params[0], int(request.params[1])
    sample = _sample(request.project_dir)
    doc = None if sample is None else next((d for d in sample.documents if d.sha256 == sha), None)
    if doc is None or not 1 <= number <= doc.pages:
        raise NotFound("no such page")
    return sha, number


def _state(project: Path) -> dict[str, Any]:
    sample = _sample(project)
    store = GoldStore(project)
    try:
        records = store.pages()
    except GoldError as err:
        raise _fail(err) from None
    documents = [
        {
            "sha256": sha,
            "name": run.name,
            "pages": run.pages,
            "run": run.id,
            "pdf": sources.pdf_status(run)["status"],
        }
        for sha, run in sorted(_documents(project).items(), key=lambda item: item[1].name)
    ]
    pages: list[dict[str, Any]] = []
    done = 0
    if sample is not None:
        names = {d.sha256: d.name for d in sample.documents}
        for sha, number in sample.pages:
            record = records.get(key(sha, number))
            status = record.status if record else "new"
            done += status == "done"
            pages.append(
                {
                    "sha256": sha,
                    "name": names[sha],
                    "page": number,
                    "status": status,
                    "seconds": record.seconds if record else None,
                }
            )
    return {
        "sample": None if sample is None else _sample_json(sample),
        "documents": documents,
        "pages": pages,
        "done": done,
        "total": len(pages),
        "skipped": store.skipped,
        "tracked": {"ok": True}
        if sample is None or (note := gold_ignore_note(project)) is None
        else {"ok": False, "note": note},
    }


def _sample_json(sample: Sample) -> dict[str, Any]:
    return {
        "seed": sample.seed,
        "size": sample.size,
        "drawn": sample.drawn,
        "documents": [
            {"sha256": d.sha256, "name": d.name, "pages": d.pages} for d in sample.documents
        ],
    }


def gold_state(request: Request) -> dict[str, Any]:
    """``GET /api/gold``: the sample, the documents that could be sampled and the page list."""
    return _state(request.project_dir)


def _int(value: Any, what: str) -> int:  # noqa: ANN401
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{what} must be a whole number"
        raise BadRequest(msg)
    return value


def draw_sample(request: Request) -> dict[str, Any]:
    """``POST /api/gold/sample``: draw a sample of the chosen documents' pages."""
    body, project = request.body, request.project_dir
    if not isinstance(body, dict):
        raise BadRequest("the body must be an object")
    shas = body.get("documents")
    if not isinstance(shas, list) or not shas or not all(isinstance(s, str) for s in shas):
        raise BadRequest("choose at least one document")
    available = _documents(project)
    chosen: list[SampleDoc] = []
    for sha in dict.fromkeys(shas):
        run = available.get(sha)
        if run is None:
            raise BadRequest("no saved run of a chosen document")
        if sources.pdf_status(run)["status"] != "ok":
            raise BadRequest(f"the PDF of {run.name} is missing or has changed")
        chosen.append(SampleDoc(sha, run.name, run.pages))
    if _sample(project) is not None and body.get("replace") is not True:
        raise BadRequest("a sample exists; draw again with replace to replace it")
    total = sum(d.pages for d in chosen)
    size = _int(body["size"], "size") if body.get("size") is not None else min(DEFAULT_SIZE, total)
    seed = (
        _int(body["seed"], "seed")
        if body.get("seed") is not None
        else random.SystemRandom().randrange(2**31)
    )
    try:
        sample = make_sample(chosen, size, seed)
        SampleStore(project).save(sample)
    except GoldError as err:
        raise _fail(err) from None
    ensure_gold_trackable(project)
    return _state(project)


def page_record(request: Request) -> dict[str, Any]:
    """``GET /api/gold/pages/<sha>/<n>``: the typed page, if any, and what the document is."""
    sha, number, sample = _page_in_sample(request)
    try:
        record = GoldStore(request.project_dir).get(sha, number)
    except GoldError as err:
        raise _fail(err) from None
    run = sources.newest_run_for(request.project_dir, sha)
    doc = next(d for d in sample.documents if d.sha256 == sha)
    return {
        "name": doc.name,
        "pages": doc.pages,
        "pdf": sources.pdf_status(run)["status"] if run else "missing",
        "record": None if record is None else record.to_json(),
    }


def _summary(request: Request, sha: str) -> RunSummary:
    run = sources.newest_run_for(request.project_dir, sha)
    if run is None:
        raise NotFound("no saved run of this document, so its PDF cannot be found")
    return run


def page_words(request: Request) -> dict[str, Any]:
    """``GET /api/gold/pages/<sha>/<n>/words``: the page's selectable text."""
    sha, number = _document_page(request)
    return sources.text_words(request.project_dir, _summary(request, sha), number)


def page_image(request: Request) -> Raw:
    """``GET /api/gold/pages/<sha>/<n>.png``: the page, turned by ``rot`` degrees."""
    sha, number = _document_page(request)
    raw = request.query.get("rot", ["0"])[0]
    if not raw.isdigit():
        raise BadRequest("rot must be 0, 90, 180 or 270")
    png = sources.render_gold_page(_summary(request, sha), number, int(raw))
    return Raw(png, "image/png")


def save_page(request: Request) -> dict[str, Any]:
    """``PUT /api/gold/pages/<sha>/<n>``: store one page's tables, replacing the old record."""
    sha, number, sample = _page_in_sample(request)
    try:
        record = validate_page(request.body, sha, number, sample)
        run = sources.newest_run_for(request.project_dir, sha)
        if record.done and (run is None or sources.pdf_status(run)["status"] != "ok"):
            # a page cannot be typed from a page nobody can see, so it cannot be finished
            msg = "the PDF is missing or has changed, so this page cannot be marked done"
            raise Invalid(msg)
        GoldStore(request.project_dir).save(record)
    except GoldError as err:
        raise _fail(err) from None
    ensure_gold_trackable(request.project_dir)
    return record.to_json()


def _runs(request: Request) -> list[str]:
    return request.query.get("run", [])


def _scored(request: Request) -> Report | Progress:
    try:
        return score_project(request.project_dir, _runs(request))
    except Invalid as err:
        raise BadRequest(str(err)) from None
    except GoldError as err:
        raise _fail(err) from None


def _choices(project: Path, report: Report) -> dict[str, list[dict[str, str]]]:
    """Return the runs that could be scored for each document of the sample, newest first."""
    wanted = {d.sha256 for d in report.sample.documents}
    found: dict[str, list[dict[str, str]]] = {sha: [] for sha in wanted}
    for run in sources.saved_runs(project):
        if run.sha256 in wanted:
            found[run.sha256].append({"id": run.id, "started": run.started, "model": run.model})
    return found


def score(request: Request) -> dict[str, Any]:
    """``GET /api/gold/score``: what is left to do, or the report (nothing is stored)."""
    result = _scored(request)
    if isinstance(result, Progress):
        sample = _sample(request.project_dir)
        names = {d.sha256: d.name for d in sample.documents} if sample else {}
        return {
            "complete": False,
            "done": result.done,
            "total": result.total,
            "left": [
                {"sha256": s, "name": names.get(s, ""), "page": p}
                for s, p in result.left[:LEFT_SHOWN]
            ],
        }
    report = to_json(result)
    report["choices"] = _choices(request.project_dir, result)
    return {"complete": True, "report": report}


def score_csv(request: Request) -> Raw:
    """``GET /api/gold/score.csv?kind=pages|cells``: the same report as a CSV file."""
    kind = request.query.get("kind", [""])[0]
    if kind not in {"pages", "cells"}:
        raise BadRequest("kind must be pages or cells")
    result = _scored(request)
    if isinstance(result, Progress):
        raise BadRequest(f"{result.done} of {result.total} sampled pages are done")
    text = pages_csv(result) if kind == "pages" else cells_csv(result)
    name = f"gold_{kind}.csv"
    return Raw(
        text.encode("utf-8"),
        "text/csv; charset=utf-8",
        {"Content-Disposition": f'attachment; filename="{name}"'},
    )


_PAGE_PATH = rf"/api/gold/pages/{_SHA}/{_PAGE}"
ROUTES: list[Route] = [
    Route("GET", r"/api/gold", gold_state),
    Route("POST", r"/api/gold/sample", draw_sample),
    Route("GET", _PAGE_PATH, page_record),
    Route("PUT", _PAGE_PATH, save_page, max_body=PAGE_SAVE_LIMIT),
    Route("GET", _PAGE_PATH + r"/words", page_words),
    Route("GET", _PAGE_PATH + r"\.png", page_image),
    Route("GET", r"/api/gold/score", score),
    Route("GET", r"/api/gold/score\.csv", score_csv),
]
