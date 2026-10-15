"""Shared fixtures: the sample PDFs, their recorded rows, a synthetic PDF builder, a fake model."""

import json
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from gridkey.llm import Image, Request
from gridkey.models import Column, PageRows, PageTables, TableInfo, WindowTables

DATA = Path(__file__).parent / "data"
SAMPLES = ["fy22_milcon_house_original", "fy24_milcon_house_original", "fy22_ag_house_original"]

Word = tuple[float, float, str]  # x, y (baseline), text


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[list[list[Word]]], Path]:
    """Return a builder: one list of (x, y, text) words per page -> a PDF path."""

    def build(pages: list[list[Word]]) -> Path:
        document = pymupdf.open()
        for words in pages:
            page = document.new_page(width=612, height=792)
            for x, y, text in words:
                page.insert_text((x, y), text, fontsize=9)
        path = tmp_path / "synthetic.pdf"
        document.save(path)
        document.close()
        return path

    return build


def load_sample(name: str) -> dict:
    """A sample PDF with the rows a model gave for it (recorded in an earlier project)."""
    recorded = json.loads((DATA / f"{name}.rows.json").read_text())
    return {
        "name": name,
        "pdf": DATA / f"{name}.pdf",
        "columns": recorded["columns"],
        "pages": {int(p): rows for p, rows in recorded["pages"].items()},
    }


@pytest.fixture(params=SAMPLES)
def sample(request: pytest.FixtureRequest) -> dict:
    """Each sample document in turn."""
    return load_sample(request.param)


class FakeClient:
    """A model that answers every request with ``handler(request)`` and records them."""

    identity = "fake"

    def __init__(self, handler: Callable[[Request], object]) -> None:
        self.handler = handler
        self.requests: list[Request] = []

    async def ask(self, request: Request) -> object:
        self.requests.append(request)
        return self.handler(request)

    def stages(self) -> list[str]:
        return [r.stage for r in self.requests]


def window_of(request: Request, tables: list[PageTables]) -> WindowTables:
    """Return a discovery answer with ``tables`` repeated for each page image in ``request``."""
    images = sum(isinstance(p, Image) for p in request.parts)
    return WindowTables(pages=[tables[min(i, len(tables) - 1)] for i in range(images)])


def one_table(columns: list[str], label: str = "table") -> PageTables:
    """A page that holds one table with these columns (first and last row text left blank)."""
    info = TableInfo(
        label=label,
        columns=[Column(name=c, description="") for c in columns],
        first_row="",
        last_row="",
    )
    return PageTables(tables=[info])


def replay(columns: list[str], pages: dict[int, list[dict[str, str]]]) -> FakeClient:
    """
    A fake model that answers discovery and extract requests with recorded rows.

    Discovery reports one table with ``columns`` on every page; the first and last row text
    is blank because it is only used on pages that hold several tables.
    """

    def handler(request: Request) -> object:
        if request.stage == "schema":
            return window_of(request, [one_table(columns)])
        if request.stage == "extract":
            assert request.page is not None
            return PageRows(rows=[dict(r) for r in pages[request.page]])
        msg = f"unexpected stage {request.stage}"
        raise AssertionError(msg)

    return FakeClient(handler)
