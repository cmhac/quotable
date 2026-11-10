"""The gold check's routes over HTTP (spec 016 tasks 012 and 018), on a built project."""

import http.client
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pymupdf

from quotable.gold.store import GoldStore, GoldTable
from quotable.review import sources
from quotable.review.sources import line_ends
from quotable.runs import load_run
from quotable.storage import GOLD_IGNORE
from tests.gold_project import draw_and_type, gold_from_run, type_sample
from tests.review.test_browse_api import App, edit_run, snapshot


def send(app: App, method: str, path: str, body: Any = None, *, origin: bool = True):
    conn = http.client.HTTPConnection("127.0.0.1", app.server.server_address[1], timeout=10)
    headers = {}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if origin and method != "GET":
        headers["Origin"] = f"http://127.0.0.1:{app.server.server_address[1]}"
    try:
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        return response.status, response, response.read()
    finally:
        conn.close()


def call(app: App, method: str, path: str, body: Any = None, status: int = 200) -> Any:
    got, response, raw = send(app, method, path, body)
    assert got == status, (method, path, got, raw[:300])
    if response.getheader("Content-Type", "").startswith("application/json"):
        return json.loads(raw)
    return raw


def summary(app: App, label: str):
    return load_run(app.project, app.id[label]).summary


def draw(app: App, label: str = "simple_new", **options: Any) -> dict:
    sha = summary(app, label).sha256
    return call(app, "POST", "/api/gold/sample", {"documents": [sha], **options})


def table(columns=("Name", "Amount"), rows=(("Ann", "1"),)) -> dict:
    return {"columns": list(columns), "rows": [list(r) for r in rows]}


def put(app: App, sha: str, page: int, tables: list[dict], *, done: bool = True, **extra: Any):
    body = {"tables": tables, "done": done, "seconds": 5.0, **extra}
    return call(app, "PUT", f"/api/gold/pages/{sha}/{page}", body)


# --- the state and the draw -------------------------------------------------------------------
def test_before_a_sample_the_documents_are_offered_with_their_pdf_status(app: App):
    state = call(app, "GET", "/api/gold")
    assert state["sample"] is None
    assert state["pages"] == []
    names = {d["name"]: d for d in state["documents"]}
    simple = summary(app, "simple_new")
    assert names[simple.name]["pdf"] == "ok"
    assert names[simple.name]["sha256"] == simple.sha256
    assert names[simple.name]["pages"] == simple.pages
    assert state["tracked"] == {"ok": True}


def test_a_draw_is_seeded_repeatable_and_counts_progress(app: App):
    state = draw(app, seed=5)
    one = summary(app, "simple_new")
    assert state["sample"]["seed"] == 5
    assert state["total"] == min(20, one.pages) == len(state["pages"])
    assert state["done"] == 0
    assert {p["status"] for p in state["pages"]} == {"new"}
    again = draw(app, seed=5, replace=True)
    assert again["pages"] == state["pages"]


def test_the_seed_is_chosen_when_none_is_given_and_shown(app: App):
    assert isinstance(draw(app)["sample"]["seed"], int)


def test_a_draw_refuses_bad_requests(app: App):
    sha = summary(app, "simple_new").sha256
    bad = [
        ({"documents": []}, "at least one document"),
        ({"documents": ["f" * 64]}, "no saved run"),
        ({"documents": [sha], "size": 0}, "cannot draw"),
        ({"documents": [sha], "size": 10**6}, "cannot draw"),
        ({"documents": [sha], "size": "x"}, "whole number"),
        ({"documents": [sha], "seed": 1.5}, "whole number"),
    ]
    for body, message in bad:
        error = call(app, "POST", "/api/gold/sample", body, status=400)["error"]
        assert message in error, (body, error)


def test_a_second_draw_needs_replace(app: App):
    draw(app)
    sha = summary(app, "simple_new").sha256
    error = call(app, "POST", "/api/gold/sample", {"documents": [sha]}, status=400)["error"]
    assert "replace" in error


def test_the_first_draw_makes_the_gold_folder_trackable(app: App):
    draw(app)
    assert (app.project / ".gitignore").read_text() == GOLD_IGNORE


def test_a_draw_keeps_the_gold_already_typed(app: App):
    state = draw(app, seed=2)
    page = state["pages"][0]
    put(app, page["sha256"], page["page"], [table()])
    draw(app, seed=3, replace=True)
    assert GoldStore(app.project).get(page["sha256"], page["page"]) is not None


def test_a_missing_pdf_cannot_be_drawn_from(app: App):
    run = summary(app, "simple_new")
    edit_run(
        app.project,
        app.id["simple_new"],
        lambda d: d["document"].update(path="/nowhere.pdf"),
    )
    edit_run(
        app.project,
        app.id["simple_old"],
        lambda d: d["document"].update(path="/nowhere.pdf"),
    )
    error = call(app, "POST", "/api/gold/sample", {"documents": [run.sha256]}, status=400)["error"]
    assert "missing or has changed" in error


# --- a page -----------------------------------------------------------------------------------
def test_a_page_saves_and_reads_back_and_the_state_shows_it_done(app: App):
    state = draw(app, seed=1)
    page = state["pages"][0]
    sha, number = page["sha256"], page["page"]
    before = call(app, "GET", f"/api/gold/pages/{sha}/{number}")
    assert before["record"] is None
    assert before["pdf"] == "ok"
    saved = put(app, sha, number, [table()])
    assert saved["done"] is True
    assert saved["updated"].endswith("Z")
    again = call(app, "GET", f"/api/gold/pages/{sha}/{number}")
    assert again["record"]["tables"] == [table()]
    assert again["name"] == page["name"]
    done = call(app, "GET", "/api/gold")
    assert done["pages"][0]["status"] == "done"
    assert done["pages"][0]["seconds"] == 5.0
    assert done["done"] == 1


def test_every_limit_and_rule_is_a_400_with_a_message(app: App):
    page = draw(app)["pages"][0]
    sha, number = page["sha256"], page["page"]
    path = f"/api/gold/pages/{sha}/{number}"
    cases = [
        ({"tables": [table()] * 11, "done": True}, "at most 10"),
        ({"tables": [table(columns=["A"] * 41, rows=[])], "done": True}, "at most 40"),
        ({"tables": [table(columns=["A"], rows=[["x"]] * 401)], "done": True}, "at most 400"),
        ({"tables": [table(columns=["A"], rows=[["x" * 2001]])], "done": True}, "2000"),
        ({"tables": [table(columns=["A", ""], rows=[["1", "2"]])], "done": True}, "name every"),
        ({"tables": [table(columns=["A", "A"], rows=[])], "done": True}, "name every"),
        ({"tables": [], "done": "yes"}, "true or false"),
        ({"tables": [], "done": True, "seconds": -3}, "seconds"),
    ]
    for body, message in cases:
        error = call(app, "PUT", path, body, status=400)["error"]
        assert message in error, (body, error)
    assert GoldStore(app.project).get(sha, number) is None


def test_a_save_over_two_mebibytes_is_refused_and_a_big_one_is_accepted(app: App):
    page = draw(app)["pages"][0]
    path = f"/api/gold/pages/{page['sha256']}/{page['page']}"
    rows = [["x" * 1900 for _ in range(40)] for _ in range(5)]  # about 380 KiB
    big = {"tables": [table(columns=[f"C{i}" for i in range(40)], rows=rows)], "done": True}
    assert send(app, "PUT", path, big)[0] == 200
    conn = http.client.HTTPConnection("127.0.0.1", app.server.server_address[1], timeout=10)
    try:
        conn.putrequest("PUT", path)
        conn.putheader("Origin", f"http://127.0.0.1:{app.server.server_address[1]}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(2 * 1024 * 1024 + 1))  # declared, never sent
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()


def test_a_page_outside_the_sample_or_a_document_not_in_it_is_404(app: App):
    state = draw(app)
    sha = state["pages"][0]["sha256"]
    beyond = summary(app, "simple_new").pages + 5
    for suffix in (f"{sha}/{beyond}", f"{'e' * 64}/1"):
        assert send(app, "GET", f"/api/gold/pages/{suffix}")[0] == 404
        assert send(app, "GET", f"/api/gold/pages/{suffix}/words")[0] == 404
        assert send(app, "GET", f"/api/gold/pages/{suffix}.png")[0] == 404
        assert send(app, "PUT", f"/api/gold/pages/{suffix}", {"tables": [], "done": True})[0] == 404


def test_words_come_with_a_line_end_flag_and_the_page_size(app: App):
    page = draw(app)["pages"][0]
    data = call(app, "GET", f"/api/gold/pages/{page['sha256']}/{page['page']}/words")
    assert data["width"] > 0
    assert data["height"] > 0
    assert data["words"]
    text, x0, y0, x1, y1, end = data["words"][0]
    assert isinstance(text, str)
    assert x1 > x0
    assert y1 > y0
    assert isinstance(end, bool)
    assert data["words"][-1][5] is True


def test_the_page_image_can_be_turned_and_only_by_right_angles(app: App):
    page = draw(app)["pages"][0]
    path = f"/api/gold/pages/{page['sha256']}/{page['page']}.png"

    def size(png: bytes) -> tuple[int, int]:
        assert png.startswith(b"\x89PNG")
        return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")

    upright = size(call(app, "GET", path))
    turned = size(call(app, "GET", path + "?rot=90"))
    assert turned == (upright[1], upright[0])
    assert size(call(app, "GET", path + "?rot=180")) == upright
    for bad in ("45", "x", "-90"):
        assert send(app, "GET", path + f"?rot={bad}")[0] == 400


def test_the_whole_pdf_view_can_read_pages_that_were_not_drawn(app: App):
    run = summary(app, "senate")
    assert run.pages > 1
    state = draw(app, "senate", size=1)
    drawn = state["pages"][0]["page"]
    other = next(p for p in range(1, run.pages + 1) if p != drawn)
    sha = run.sha256
    assert call(app, "GET", f"/api/gold/pages/{sha}/{other}/words")["words"]
    assert call(app, "GET", f"/api/gold/pages/{sha}/{other}.png").startswith(b"\x89PNG")
    assert send(app, "GET", f"/api/gold/pages/{sha}/{other}")[0] == 404  # but it has no record
    assert (
        send(app, "PUT", f"/api/gold/pages/{sha}/{other}", {"tables": [], "done": True})[0] == 404
    )


def test_a_changed_pdf_gives_404_for_its_image_and_words_but_keeps_the_record(app: App):
    page = draw(app)["pages"][0]
    sha, number = page["sha256"], page["page"]
    put(app, sha, number, [table()])
    for label in ("simple_new", "simple_old"):
        edit_run(app.project, app.id[label], lambda d: d["document"].update(sha256="d" * 64))
    sources.clear_caches()
    # the document is now unknown to every run, so there is nothing to read it through
    assert send(app, "GET", f"/api/gold/pages/{sha}/{number}.png")[0] == 404
    assert send(app, "GET", f"/api/gold/pages/{sha}/{number}/words")[0] == 404
    assert call(app, "GET", f"/api/gold/pages/{sha}/{number}")["record"]["done"] is True


def test_line_ends_are_found_from_geometry():
    words = [
        ["Plan-", 10, 10, 40, 20],
        ["ning", 10, 30, 40, 40],  # next line: starts at the same x, lower
        ["of", 45, 30, 60, 40],
        ["it", 5, 31, 20, 41],  # starts further left: a new line
    ]
    assert line_ends(words) == [True, False, True, True]
    assert line_ends([]) == []


def test_ocr_text_comes_from_the_run_on_a_page_it_ocrd(app: App):
    page = draw(app)["pages"][0]
    label = "simple_new"
    edit_run(app.project, app.id[label], lambda d: d["summary"].update(ocr_pages=[page["page"]]))
    sources.clear_caches()
    run = load_run(app.project, app.id[label])
    saved = run.pages[page["page"]]
    data = call(app, "GET", f"/api/gold/pages/{page['sha256']}/{page['page']}/words")
    assert [w[0] for w in data["words"]] == [w[0] for w in saved.words]
    assert data["width"] == saved.size[0]


# --- the score --------------------------------------------------------------------------------
def test_the_score_is_refused_until_every_page_is_done_and_then_computed(app: App):
    run_id = app.id["simple_new"]
    sample = draw_and_type(app.project, run_id, done=False)
    incomplete = call(app, "GET", "/api/gold/score")
    assert incomplete["complete"] is False
    assert (incomplete["done"], incomplete["total"]) == (0, len(sample.pages))
    assert incomplete["left"][0]["page"] == sample.pages[0][1]
    assert incomplete["left"][0]["name"]
    draw_and_type(app.project, run_id)
    done = call(app, "GET", "/api/gold/score")
    assert done["complete"] is True
    units = {u["name"]: u for u in done["report"]["units"]}
    assert units["cell"]["accuracy"] == 1.0
    assert done["report"]["runs"][summary(app, "simple_new").sha256]["id"] == run_id
    assert call(app, "GET", "/api/gold/score", status=200)["report"]["cells"] == []


def test_score_without_a_sample_is_a_400(app: App):
    assert "no sample" in call(app, "GET", "/api/gold/score", status=400)["error"]


def test_run_chooses_which_run_is_scored_and_bad_choices_are_400(app: App):
    draw_and_type(app.project, app.id["simple_old"])
    older, newer = app.id["simple_old"], app.id["simple_new"]
    assert list(call(app, "GET", "/api/gold/score")["report"]["runs"].values())[0]["id"] == newer
    chosen = call(app, "GET", f"/api/gold/score?run={older}")
    assert list(chosen["report"]["runs"].values())[0]["id"] == older
    both = call(app, "GET", f"/api/gold/score?run={older}&run={newer}", status=400)
    assert "same document" in both["error"]
    assert (
        "no saved run" in call(app, "GET", f"/api/gold/score?run={'f' * 32}", status=400)["error"]
    )


def test_the_csv_matches_the_report_and_a_bad_kind_is_400(app: App):
    draw_and_type(app.project, app.id["simple_new"])
    raw = call(app, "GET", "/api/gold/score.csv?kind=pages")
    assert raw.decode().splitlines()[0].startswith("document,page,correct")
    cells = call(app, "GET", "/api/gold/score.csv?kind=cells")
    assert cells.decode().splitlines() == [
        "document,page,table,column,gold_row,gold,extracted,best"
    ]
    assert "kind" in call(app, "GET", "/api/gold/score.csv?kind=x", status=400)["error"]
    assert "kind" in call(app, "GET", "/api/gold/score.csv", status=400)["error"]


def test_the_gold_check_never_changes_runs_cache_cost_or_reviews(app: App):
    watched = ("runs", "cache", "cost", "review")
    before = {n: snapshot(app.project / n) for n in watched if (app.project / n).exists()}
    state = draw(app, seed=4)
    for page in state["pages"]:
        put(app, page["sha256"], page["page"], [table()])
    call(app, "GET", "/api/gold/score")
    after = {n: snapshot(app.project / n) for n in watched if (app.project / n).exists()}
    assert before == after


def test_an_unreadable_gold_file_is_a_500_and_is_not_overwritten(app: App):
    state = draw(app)
    page = state["pages"][0]
    store = GoldStore(app.project)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    got, _, raw = send(
        app, "PUT", f"/api/gold/pages/{page['sha256']}/{page['page']}", {"tables": [], "done": True}
    )
    assert got == 500
    assert "not valid JSON" in json.loads(raw)["error"]
    assert store.path.read_text(encoding="utf-8") == "{not json"


def test_a_put_needs_an_origin_like_every_other_change(app: App):
    page = draw(app)["pages"][0]
    path = f"/api/gold/pages/{page['sha256']}/{page['page']}"
    got, _, _ = send(app, "PUT", path, {"tables": [], "done": True}, origin=False)
    assert got == 403


def test_the_score_lists_the_runs_that_could_be_scored_for_each_document(app: App):
    draw_and_type(app.project, app.id["simple_old"])
    report = call(app, "GET", "/api/gold/score")["report"]
    [(sha, options)] = report["choices"].items()
    assert [o["id"] for o in options] == [
        app.id["simple_new"],
        app.id["simple_old"],
    ]  # newest first
    assert sha == summary(app, "simple_new").sha256
    assert {"id", "started", "model"} <= set(options[0])


def test_three_documents_give_pooled_counts_a_line_each_and_no_interval(app: App):
    labels = ["simple_new", "senate", "merged"]
    shas = [summary(app, label).sha256 for label in labels]
    total_pages = sum(summary(app, label).pages for label in labels)
    size = min(total_pages, 6)
    first = call(
        app, "POST", "/api/gold/sample", {"documents": shas, "size": size, "seed": 9}, status=200
    )
    assert first["total"] == size
    per_doc = {sha: [p for p in first["pages"] if p["sha256"] == sha] for sha in shas}
    assert all(len(pages) >= 1 for pages in per_doc.values())  # every document has a page
    again = call(
        app,
        "POST",
        "/api/gold/sample",
        {"documents": shas, "size": size, "seed": 9, "replace": True},
    )
    assert again["pages"] == first["pages"]  # the same seed draws the same pages
    type_sample(app.project, [app.id[label] for label in labels])
    report = call(app, "GET", "/api/gold/score")["report"]
    assert report["interval"] is None
    assert {d["sha256"] for d in report["documents"]} == set(shas)
    assert sum(d["counts"]["cells"] for d in report["documents"]) == report["total"]["cells"]
    assert report["total"]["cells"] > 0


def test_a_sampled_document_whose_runs_are_gone_is_listed_as_not_scored(app: App):
    labels = ["simple_new", "senate"]
    shas = [summary(app, label).sha256 for label in labels]
    gone = summary(app, "simple_new").name
    call(app, "POST", "/api/gold/sample", {"documents": shas, "size": 3, "seed": 1})
    type_sample(app.project, [app.id[label] for label in labels])
    for label in ("simple_new", "simple_old"):
        shutil.rmtree(app.project / "runs" / app.id[label])
    sources.clear_caches()
    report = call(app, "GET", "/api/gold/score")["report"]
    assert report["not_scored"] == [gone]
    assert {d["name"] for d in report["documents"]} == {summary(app, "senate").name}
    assert report["interval"] is None


def test_a_page_cannot_be_marked_done_when_its_pdf_is_missing_but_can_still_be_saved(app: App):
    page = draw(app)["pages"][0]
    sha, number = page["sha256"], page["page"]
    for label in ("simple_new", "simple_old"):
        edit_run(app.project, app.id[label], lambda d: d["document"].update(path="/nowhere.pdf"))
    path = f"/api/gold/pages/{sha}/{number}"
    error = call(app, "PUT", path, {"tables": [], "done": True}, status=400)["error"]
    assert "cannot be marked done" in error
    saved = call(app, "PUT", path, {"tables": [table()], "done": False})
    assert saved["done"] is False
    assert call(app, "GET", path)["pdf"] == "missing"
    assert call(app, "GET", "/api/gold/score")["complete"] is False


def test_the_whole_path_over_http_draw_type_every_page_and_score(app: App):
    run_id = app.id["simple_new"]
    state = draw(app, seed=3)
    doc, tables = gold_from_run(app.project, run_id)
    for page in state["pages"]:
        typed = [{"columns": t.columns, "rows": t.rows} for t in tables[page["page"]]]
        put(app, page["sha256"], page["page"], typed)
    assert call(app, "GET", "/api/gold")["done"] == state["total"]
    report = call(app, "GET", "/api/gold/score")["report"]
    assert all(u["accuracy"] in (1.0, None) for u in report["units"])
    assert report["interval"]["low"] == report["interval"]["high"] == report["interval"]["share"]
    assert report["cells"] == []
    # one wrong word in one saved page: exactly one difference is listed
    page = state["pages"][0]
    edited = [GoldTable(list(t.columns), [list(r) for r in t.rows]) for t in tables[page["page"]]]
    edited[0].rows[0][0] = "#### " + edited[0].rows[0][0]
    put(app, page["sha256"], page["page"], [{"columns": t.columns, "rows": t.rows} for t in edited])
    changed = call(app, "GET", "/api/gold/score")["report"]
    assert len(changed["cells"]) == 1
    assert changed["cells"][0]["gold"].startswith("#### ")
    assert doc.name == changed["cells"][0]["document"]


def test_the_run_list_is_read_once_until_a_run_changes(app: App, monkeypatch):
    calls = []
    real = sources.list_runs

    def counting(project):
        calls.append(1)
        return real(project)

    monkeypatch.setattr(sources, "list_runs", counting)
    sources.clear_caches()
    first = sources.saved_runs(app.project)
    again = sources.saved_runs(app.project)
    assert again is first
    assert len(calls) == 1
    edit_run(app.project, app.id["simple_new"], lambda d: d["run"].update(model="other-model"))
    changed = sources.saved_runs(app.project)
    assert len(calls) == 2
    assert {r.id: r.model for r in changed}[app.id["simple_new"]] == "other-model"


def test_many_gold_requests_read_the_run_list_once(app: App, monkeypatch):
    calls = []
    real = sources.list_runs
    monkeypatch.setattr(sources, "list_runs", lambda p: (calls.append(1), real(p))[1])
    sources.clear_caches()
    page = draw(app)["pages"][0]
    base = f"/api/gold/pages/{page['sha256']}/{page['page']}"
    for suffix in ("", "/words", ".png", "/words", ".png"):
        call(app, "GET", base + suffix)
    call(app, "GET", "/api/gold")
    assert len(calls) == 1


def test_gold_images_and_words_requested_together_never_use_pymupdf_at_the_same_time(
    app: App, monkeypatch
):
    real = pymupdf.open
    state = {"now": 0, "most": 0}
    guard = threading.Lock()

    class Counted:
        def __init__(self, *args):
            with guard:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.02)  # long enough for the other requests to arrive
            self.document = real(*args)

        def __enter__(self):
            return self.document.__enter__()

        def __exit__(self, *exc):
            try:
                return self.document.__exit__(*exc)
            finally:
                with guard:
                    state["now"] -= 1

    page = draw(app)["pages"][0]
    base = f"/api/gold/pages/{page['sha256']}/{page['page']}"
    sources.clear_caches()
    monkeypatch.setattr(pymupdf, "open", Counted)
    paths = [base + suffix for suffix in ("/words", ".png", ".png?rot=90", "/words") * 3]
    with ThreadPoolExecutor(6) as pool:
        answers = list(pool.map(lambda path: send(app, "GET", path)[0], paths))
    assert answers == [200] * len(paths)
    assert state["most"] == 1
