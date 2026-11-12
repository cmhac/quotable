"""Shared fixtures: the sample PDFs, their recorded rows, a synthetic PDF builder, a fake model."""

import asyncio
import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pymupdf
import pytest

from quotable.llm.answers import Column, PageRows, PageTables, TableInfo, WindowTables
from quotable.llm.client import Image, LLMClient, Request
from quotable.pipeline import run_pipeline
from quotable.table import Table

DATA = Path(__file__).parent / "data"
SAMPLES = ["fy22_milcon_house_original", "fy24_milcon_house_original", "fy22_ag_house_original"]

Word = tuple[float, float, str]  # x, y (baseline), text


def extract_tables(  # noqa: PLR0913
    pdf: Path,
    client: LLMClient,
    *,
    discovery_pages: int | None = None,
    recheck: bool = True,
    merge_reworded: bool | None = None,
    audit: bool = False,
) -> list[Table]:
    """Run the pipeline with a fake client (the public function takes a model instead)."""
    options: dict[str, Any] = (
        {} if discovery_pages is None else {"discovery_pages": discovery_pages}
    )
    if merge_reworded is not None:
        options["merge_reworded"] = merge_reworded
    return asyncio.run(run_pipeline(Path(pdf), client, recheck=recheck, audit=audit, **options))


@pytest.fixture(autouse=True)
def _run_in_a_temp_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test in an empty working directory, so no test writes ``.quotable/`` here."""
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)


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


class OverlapClient:
    """Wrap a client and record the most ``ask`` calls that were in flight at the same moment."""

    def __init__(self, inner: FakeClient) -> None:
        self.inner = inner
        self.identity = inner.identity
        self.now = 0
        self.most = 0

    async def ask(self, request: Request) -> object:
        self.now += 1
        self.most = max(self.most, self.now)
        try:
            await asyncio.sleep(0.01)  # give the other tasks a chance to start
            return await self.inner.ask(request)
        finally:
            self.now -= 1

    def stages(self) -> list[str]:
        return self.inner.stages()


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


class PricedClient:
    """
    Wrap a client and report a cost for every request to a ``RunMeter`` (spec 017).

    ``cost`` is one price for every request or a price per stage; a stage in ``no_usage`` reports
    no token counts. ``asyncio.sleep(0)`` lets requests in flight overlap. ``started`` records the
    meter's total at the moment each request began.
    """

    def __init__(
        self,
        inner: FakeClient,
        meter: Any,
        cost: Decimal | dict[str, Decimal] = Decimal("0.01"),
        no_usage: tuple[str, ...] = (),
    ) -> None:
        self.inner = inner
        self.meter = meter
        self.cost = cost
        self.no_usage = no_usage
        self.identity = inner.identity
        self.started: list[tuple[str, Decimal]] = []

    async def ask(self, request: Request) -> object:
        self.started.append((request.stage, self.meter.total))
        answer = await self.inner.ask(request)
        await asyncio.sleep(0)
        price = self.cost[request.stage] if isinstance(self.cost, dict) else self.cost
        tokens = (0, 0) if request.stage in self.no_usage else (1000, 100)
        usage = SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1])
        self.meter.add(request, usage, price)
        return answer

    def stages(self) -> list[str]:
        return self.inner.stages()


@pytest.fixture
def fake_ipython(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Make ``IPython`` look loaded in a notebook; ``calls`` records display and update calls."""
    calls: list[tuple[str, dict[str, Any], str | None]] = []

    class ZMQInteractiveShell:  # the class name is how a notebook kernel is recognised
        pass

    shell = ZMQInteractiveShell()
    display_module = ModuleType("IPython.display")
    vars(display_module).update(
        display=lambda data, raw=False, display_id=None: calls.append(
            ("display", data, display_id)
        ),
        update_display=lambda data, raw=False, display_id=None: calls.append(
            ("update", data, display_id)
        ),
    )
    module = ModuleType("IPython")
    vars(module).update(get_ipython=lambda: shell, display=display_module)
    monkeypatch.setitem(sys.modules, "IPython", module)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)
    return SimpleNamespace(calls=calls)
