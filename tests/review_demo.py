"""
A demo project for working on the review app (spec 013, task 009): ``just review-demo``.

``python -m tests.review_demo [DIR]`` builds a ``.quotable/`` folder in ``DIR`` (default
``build/review-demo/``) by running ``extract_tables`` on a handful of documents with fake models
(no network, no key, no cost; answers come from the fixture's truth files and recorded rows, with
faults put in on purpose so every status shows). It holds:

* ``senate_expenditures_paddleocr.pdf``: two tables, one sharing page 1 with the other;
* ``senate_expenditures_garbled.pdf``: the same report with a bad text layer, OCR'd by a fake
  engine;
* ``section-headers.pdf``: an extra field printed on page 1 and carried to pages 2 and 3;
* ``reworded-headers.pdf``: a table merged from two parts, with a cell the recheck corrected;
* ``large-table.pdf``: one table of several thousand rows;
* ``fy22_milcon_house_original.pdf``: run twice, the second time with one answer changed, so the
  verdict given to the first run is stale in the second;
* ``dropped-column.pdf``: a column the second page does not print (``not_on_page``).

A gold check (spec 015) too: a sample of every page of the Senate report and the extras report,
typed as a careful person would, except that one page has a wrong word, one is typed as having no
table and one page holds two tables. The score screen has something to show right away.

Then a few verdicts and cost records (one run with no price known, three free), one PDF moved away
(``missing``) and one edited (``changed``). The folder is made fresh each time; a folder that is
not a demo is never deleted.
"""

import argparse
import contextlib
import json
import shutil
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

import pymupdf

from quotable import extract_tables, pipeline
from quotable.gold.sample import make_sample
from quotable.gold.store import GoldPage, GoldStore, GoldTable, SampleStore
from quotable.llm.answers import PageRecheck
from quotable.ocr.config import OcrConfig
from quotable.review.queue import FLAGGED
from quotable.review.verdicts import CellKey, Verdict, VerdictStore, now
from quotable.runs import Run, RunRow, load_run
from quotable.storage import CostLog, ensure_gold_trackable, runs_dir
from tests.conftest import FakeClient, load_sample, replay
from tests.extra_fields_model import request_for, truth_model
from tests.fake_ocr import ExplodingEngine, FakeEngine, native_as_ocr
from tests.fixture_tables import DATA as FIXTURE
from tests.fixture_tables import load_doc
from tests.gold_project import gold_from_run
from tests.synthetic import Doc, render
from tests.synthetic_cases import part
from tests.test_merge_pipeline import client_for
from tests.test_senate_tables import PDF as SENATE
from tests.test_senate_tables import recorded_model

DEFAULT_DIR = Path("build/review-demo")
MARKER = ".review-demo"
LARGE_ROWS_PER_PAGE = 36
LARGE_PAGES = 84  # 3,024 rows

TWO_TABLES_PDF = "senate_expenditures_paddleocr.pdf"
OCR_PDF = "senate_expenditures_garbled.pdf"
EXTRAS_PDF = "section-headers.pdf"
MERGED_PDF = "reworded-headers.pdf"
LARGE_PDF = "large-table.pdf"
STALE_PDF = "fy22_milcon_house_original.pdf"
DROPPED_PDF = "dropped-column.pdf"
# the document of every run, in the order the demo makes them
RUNS = (
    TWO_TABLES_PDF,
    OCR_PDF,
    EXTRAS_PDF,
    MERGED_PDF,
    LARGE_PDF,
    STALE_PDF,
    STALE_PDF,
    DROPPED_PDF,
)

OCR_DPI = OcrConfig().dpi
DROPPED_COLUMNS = ["Project", "County", "Amount", "Year"]
DROPPED_ROWS = [
    ("Harbor Dredging", "Marion", "$125,000", "2019"),
    ("Water Main Repair", "Clark", "$410,000", "2020"),
    ("Library Roof", "Adams", "$98,500", "2021"),
    ("Bridge Painting", "Jasper", "$267,000", "2019"),
    ("School Gym Lighting", "Marion", "$76,000", "2022"),
    ("Fire Station Door", "Clark", "$33,250", "2020"),
]


# --- the folder ---------------------------------------------------------------------------------
def _fresh(root: Path) -> None:
    """Empty ``root``; refuse when it holds anything that is not an earlier demo."""
    if root.exists() and any(root.iterdir()):
        if not (root / MARKER).exists():
            msg = f"{root} is not a demo folder (no {MARKER} file in it), so it is not deleted"
            raise SystemExit(msg)
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("built by tests/review_demo.py; deleted and rebuilt each time\n")


@contextlib.contextmanager
def _models(client: FakeClient, engine: object) -> Generator[None]:
    """Make ``extract_tables`` use ``client`` for the model and ``engine`` for OCR."""
    with (
        mock.patch.object(pipeline, "PydanticAIClient", lambda *_a, **_k: client),
        mock.patch.object(pipeline, "PaddleEngine", lambda _config: engine),
    ):
        yield


class Demo:
    """The project being built: its PDFs, its runs (by label) and what is done to them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pdfs = root / "pdfs"
        self.pdfs.mkdir()
        self.project = root / ".quotable"
        self.runs: dict[str, str] = {}

    def pdf(self, source: Path, name: str) -> Path:
        """Copy a PDF into the demo (the runs name this copy, never a file of the repository)."""
        return Path(shutil.copy(source, self.pdfs / name))

    def run(  # noqa: PLR0913
        self,
        label: str,
        pdf: Path,
        client: FakeClient,
        *,
        age: timedelta,
        engine: object | None = None,
        **options: Any,  # noqa: ANN401
    ) -> None:
        """Run ``extract_tables`` with the fake model; ``age`` is how long ago the run started."""
        before = self._ids()
        options.setdefault("ocr", False)
        options.setdefault("audit", False)  # the fake models know no audit request
        with _models(client, engine or ExplodingEngine()):
            extract_tables(pdf, f"demo:{label}", **options)
        (run_id,) = self._ids() - before
        self.runs[label] = run_id
        started = (datetime.now(UTC) - age).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = runs_dir(self.project) / run_id / "run.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["run"]["started"] = data["run"]["ended"] = started
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _ids(self) -> set[str]:
        folder = runs_dir(self.project)
        return {p.name for p in folder.iterdir()} if folder.exists() else set()

    def load(self, label: str) -> Run:
        return load_run(self.project, self.runs[label])

    def pay(self, label: str, *prices: str | None) -> None:
        """Write one cost record per price (``None``: a model whose price is not known)."""
        log = CostLog(self.runs[label])
        for price in prices:
            log.record(
                "extract",
                f"demo:{label}",
                input_tokens=1800,
                output_tokens=420,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost=None if price is None else Decimal(price),
            )

    def judge(  # noqa: PLR0913
        self,
        label: str,
        table: int,
        row: RunRow,
        column: str,
        kind: str,
        *,
        value: str | None = None,
        category: str | None = None,
        note: str = "",
    ) -> Verdict:
        """Record a verdict on one cell of a run, as the review app would."""
        run = self.load(label)
        shown = run.tables[table]
        verdict = Verdict(
            time=now(),
            run=run.summary.id,
            name=run.summary.name,
            table_index=shown.index,
            table_label=shown.label,
            table_columns=tuple(shown.columns),
            key=CellKey(run.summary.sha256, tuple(shown.columns), row.page, row.row, column),
            extracted=row.values[column],
            status=row.cells[column].status,
            verdict=kind,
            value=value,
            category=category,
            note=note,
        )
        VerdictStore(self.project).append(verdict)
        return verdict


# --- the documents ------------------------------------------------------------------------------
def _damage(rows: list[dict[str, str]], columns: list[str], page: int) -> None:
    """Put one fault of each kind into a page of rows (a page of 23 rows or more)."""
    text, word, amount = columns[0], columns[1], columns[2]
    first = rows[2][text]
    rows[2][text] = first[: len(first) // 2] + first[len(first) // 2 + 1 :]  # a letter lost
    rows[6][word] = "Zzyzx"  # not on the page: ungrounded
    rows[11][amount], rows[21][amount] = rows[21][amount], rows[11][amount]  # misplaced
    rows[14][word] = "—"  # nothing to look up: untokenized
    rows[17][text] = ""  # empty
    rows[19][text] = f"{rows[19][text]} {rows[19][word]} Annex"  # a neighbour's word added


def _large_pdf(path: Path, pages: int) -> tuple[list[str], dict[int, list[dict[str, str]]]]:
    doc = Doc(
        "demo-large",
        "one table of several thousand rows",
        [],
        [part("A", "projects6", pages=pages, rows_per_page=LARGE_ROWS_PER_PAGE)],
    )
    truth = render(doc, path)
    (table,) = truth["parts"]
    columns = table["columns"]
    rows = {
        int(page): [dict(zip(columns, row, strict=True)) for row in values]
        for page, values in table["rows"].items()
    }
    for page in range(1, pages + 1, 3):  # every third page has faults
        _damage(rows[page], columns, page)
    return columns, rows


def _dropped_pdf(path: Path) -> dict[int, list[dict[str, str]]]:
    """A table whose second page does not print the last column."""
    pages: dict[int, list[dict[str, str]]] = {}
    with pymupdf.open() as document:
        for number, rows in ((1, DROPPED_ROWS[:3]), (2, DROPPED_ROWS[3:])):
            page = document.new_page(width=612, height=792)
            page.insert_text((50, 60), "Annual funding report for rural communities", fontsize=12)
            page.insert_text(
                (50, 76), "The committee reviewed the community requests of each county", fontsize=9
            )
            shown = DROPPED_COLUMNS if number == 1 else DROPPED_COLUMNS[:-1]
            xs = (50, 230, 340, 450)
            for x, name in zip(xs, shown, strict=False):
                page.insert_text((x, 110), name, fontsize=9, fontname="hebo")
            pages[number] = []
            for i, row in enumerate(rows):
                for x, value in zip(xs, row[: len(shown)], strict=False):
                    page.insert_text((x, 130 + i * 16), value, fontsize=9)
                pages[number].append(dict(zip(shown, row, strict=False)))
            page.insert_text((50, 740), f"Page {number}. Amounts are in US dollars.", fontsize=8)
        document.save(path)
    return pages


def build(root: Path, *, large_pages: int = LARGE_PAGES) -> Path:  # noqa: PLR0915
    """Build the demo project in ``root`` and return its ``.quotable`` folder."""
    root = root.resolve()
    _fresh(root)
    demo = Demo(root)
    day = timedelta(days=1)
    with contextlib.chdir(root):
        # two tables, one sharing a page with the other
        two = demo.pdf(SENATE, TWO_TABLES_PDF)
        demo.run("two-tables", two, recorded_model(), age=6 * day, recheck=False)
        demo.pay("two-tables", "0.2134", "0.0871")

        # the same report with a garbled text layer: OCR'd by a fake engine
        garbled = demo.pdf(SENATE.with_name(OCR_PDF), OCR_PDF)
        engine = FakeEngine(*[native_as_ocr(SENATE, n, OCR_DPI) for n in (1, 2, 3)])
        demo.run(
            "ocr", garbled, recorded_model(), age=5 * day, engine=engine, ocr=True, recheck=False
        )

        # an extra field printed on page 1, carried over to pages 2 and 3; its value misread
        case = "extra-section-3p"
        extras = demo.pdf(FIXTURE / f"{case}.pdf", EXTRAS_PDF)
        model = truth_model(case, read={1: {"division": "Raods"}})
        request = request_for(load_doc(case)["extra_fields"], carry=True)
        demo.run("extras", extras, model, age=4 * day, recheck=False, extra_fields=request)
        demo.pay("extras", None)

        # a table put together from two reworded parts, a cell of which the recheck corrected
        truth = load_doc("pipe-reworded-gap1")
        names, reworded = truth["parts"][0]["columns"], truth["parts"][1]["columns"]
        right = truth["parts"][1]["rows"]["5"][2][0]
        wrong = right.split()[0] + " Zzyzx"
        merged_pdf = demo.pdf(FIXTURE / "pipe-reworded-gap1.pdf", MERGED_PDF)

        def recheck(_request: object) -> PageRecheck:
            return PageRecheck(cells=[{"row": 3, "column": names[0], "value": right}])

        client, _ = client_for(
            "pipe-reworded-gap1", typos={(5, 3, reworded[0]): wrong}, recheck=recheck
        )
        demo.run("merged", merged_pdf, client, age=3 * day, discovery_pages=1)
        demo.pay("merged", "0.0412")

        # a large table
        large = demo.pdfs / LARGE_PDF
        columns, pages = _large_pdf(large, large_pages)
        demo.run("large", large, replay(columns, pages), age=2 * day, recheck=False)
        demo.pay("large", "0.7311", "0.6902", "0.7088", "0.6755")

        # one document run twice: the second time one answer differs
        sample = load_sample("fy22_milcon_house_original")
        stale = demo.pdf(sample["pdf"], STALE_PDF)
        first_rows = {p: [dict(r) for r in rows] for p, rows in sample["pages"].items()}
        demo.run("first", stale, replay(sample["columns"], first_rows), age=2 * day, recheck=False)
        demo.pay("first", "0.0123")
        second_rows = {p: [dict(r) for r in rows] for p, rows in sample["pages"].items()}
        column = sample["columns"][1]  # the third row's location loses the word "Air": fuzzy
        second_rows[1][2][column] = second_rows[1][2][column].replace(" Air", "", 1)
        again = replay(sample["columns"], second_rows)
        again.identity = "demo-second-run"  # else the cache answers with the first run's rows
        demo.run("second", stale, again, age=timedelta(hours=3), recheck=False)

        # a column the second page does not print
        dropped = demo.pdfs / DROPPED_PDF
        dropped_pages = _dropped_pdf(dropped)
        demo.run(
            "dropped",
            dropped,
            replay(DROPPED_COLUMNS, dropped_pages),
            age=timedelta(hours=20),
            recheck=False,
        )

        _judge(demo, column)
        _gold(demo)

        # an edited PDF, and one moved away
        with dropped.open("ab") as handle:
            handle.write(b"\n% edited after the run\n")
        away = demo.root / "moved-away"
        away.mkdir()
        shutil.move(demo.pdfs / MERGED_PDF, away / MERGED_PDF)
    return demo.project


def _gold(demo: Demo) -> None:
    """Draw every page of two documents and type them, with three deliberate differences."""
    docs, typed = [], {}
    for label in ("two-tables", "extras"):
        doc, tables = gold_from_run(demo.project, demo.runs[label])
        docs.append(doc)
        typed[doc.sha256] = tables
    sample = make_sample(docs, sum(d.pages for d in docs), 20261110)
    SampleStore(demo.project).save(sample)
    ensure_gold_trackable(demo.project)
    store = GoldStore(demo.project)
    for n, (sha, page) in enumerate(sample.pages):
        tables = [GoldTable(list(t.columns), [list(r) for r in t.rows]) for t in typed[sha][page]]
        if n == 1:  # one wrong word
            tables[0].rows[0][0] += " (misread)"
        if n == len(sample.pages) - 1:  # typed as a page with no table
            tables = []
        store.save(GoldPage(sha, page, tables, True, 80.0 + 7 * n, now()))


def _judge(demo: Demo, column: str) -> None:
    """A few verdicts: some flagged cells of the Senate report, and the one that goes stale."""
    run = demo.load("two-tables")
    flagged = [
        (t.index, r, c)
        for t in run.tables
        for r in t.rows
        for c, cell in r.cells.items()
        if cell.status in FLAGGED
    ]
    (t0, r0, c0), (t1, r1, c1), (t2, r2, c2) = flagged[:3]
    demo.judge("two-tables", t0, r0, c0, "correct", note="The page prints it just so.")
    demo.judge(
        "two-tables",
        t1,
        r1,
        c1,
        "changed",
        value=f"{r1.values[c1]} (corrected)",
        category="misspelling",
        note="Two letters swapped.",
    )
    demo.judge("two-tables", t2, r2, c2, "unsure")
    first = demo.load("first").tables[0]
    row = next(r for r in first.rows if (r.page, r.row) == (1, 3))
    demo.judge("first", first.index, row, column, "correct")


def main(argv: list[str] | None = None) -> int:
    """Build the demo; print how to look at it."""
    parser = argparse.ArgumentParser(
        prog="python -m tests.review_demo",
        description="Build a demo project (fake models, no network) for working on the review app.",
    )
    parser.add_argument(
        "dir", nargs="?", type=Path, default=DEFAULT_DIR, help=f"default: {DEFAULT_DIR}"
    )
    args = parser.parse_args(argv)
    project = build(args.dir)
    print(f"Demo project built in {project}")
    print(f"Start the app with: uv run quotable review --dir {project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
