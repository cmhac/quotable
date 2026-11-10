"""The recheck follows the run's limit on requests in flight, like the other stages (spec 015)."""

import asyncio
import copy

from quotable import pipeline
from quotable.llm.answers import CellRecheck, Omissions, PageRecheck
from tests.conftest import DATA, FakeClient, OverlapClient, load_sample, replay

PDF = DATA / "fy22_ag_house_original.pdf"  # four pages
SAMPLE = load_sample("fy22_ag_house_original")


def corrupted() -> tuple[dict, dict]:
    """The recorded rows with one wrong word in row 1 of every page, and the true values."""
    pages = copy.deepcopy(SAMPLE["pages"])
    truth = {}
    for page, rows in pages.items():
        column = max(SAMPLE["columns"], key=lambda c: len(rows[0][c].split()))
        words = rows[0][column].split()
        assert len(words) >= 3
        truth[page] = (1, column, rows[0][column])
        words[1] = "Zzyzx"
        rows[0][column] = " ".join(words)
    return pages, truth


def test_every_stage_of_a_run_shares_one_limit(monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_CONCURRENT_REQUESTS", 1)
    pages, truth = corrupted()
    base = replay(SAMPLE["columns"], pages).handler

    def handler(request):
        if request.stage == "recheck":
            row, column, value = truth[request.page]
            return PageRecheck(cells=[CellRecheck(row=row, column=column, value=value)])
        if request.stage == "audit":
            return Omissions(missing_rows=[], filled_cells=[])
        return base(request)

    client = OverlapClient(FakeClient(handler))
    asyncio.run(pipeline.run_pipeline(PDF, client, audit=True))
    assert client.stages().count("recheck") >= 2  # the recheck really ran on several pages
    assert client.most == 1
