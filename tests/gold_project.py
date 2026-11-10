"""Helpers for the gold check's tests (spec 015): a sample and typed gold made from a saved run."""

from collections.abc import Callable
from pathlib import Path

from quotable.gold.sample import make_sample
from quotable.gold.store import GoldPage, GoldStore, GoldTable, Sample, SampleDoc, SampleStore
from quotable.runs import load_run

Tables = dict[int, list[GoldTable]]


def gold_from_run(project: Path, run_id: str) -> tuple[SampleDoc, Tables]:
    """Return the run's document and, for each page, the gold a perfect typist would type."""
    run = load_run(project, run_id)
    summary = run.summary
    doc = SampleDoc(summary.sha256, summary.name, summary.pages)
    tables: Tables = {page: [] for page in range(1, summary.pages + 1)}
    for table in run.tables:
        for page in table.pages:
            rows = [
                [r.values.get(c, "") for c in table.columns]
                for r in sorted(table.rows, key=lambda r: r.row)
                if r.page == page
            ]
            if rows:
                tables[page].append(GoldTable(list(table.columns), rows))
    return doc, tables


def draw_and_type(  # noqa: PLR0913
    project: Path,
    run_id: str,
    *,
    size: int | None = None,
    seed: int = 1,
    change: Callable[[int, list[GoldTable]], list[GoldTable]] | None = None,
    done: bool = True,
) -> Sample:
    """
    Save a sample of the run's document and gold typed from the run's own rows.

    ``change(page, tables)`` may return other tables for a page, to inject differences.
    """
    doc, tables = gold_from_run(project, run_id)
    sample = make_sample([doc], size or doc.pages, seed)
    SampleStore(project).save(sample)
    store = GoldStore(project)
    for sha, page in sample.pages:
        typed = tables[page] if change is None else change(page, tables[page])
        store.save(GoldPage(sha, page, typed, done, 10.0, "2026-11-10T00:00:00Z"))
    return sample


def type_sample(project: Path, run_ids: list[str], *, done: bool = True) -> Sample:
    """Type perfect gold for every page of the existing sample that belongs to these runs."""
    sample = SampleStore(project).load()
    assert sample is not None
    typed = {doc.sha256: tables for doc, tables in (gold_from_run(project, r) for r in run_ids)}
    store = GoldStore(project)
    for sha, page in sample.pages:
        store.save(GoldPage(sha, page, typed[sha][page], done, 10.0, "2026-11-10T00:00:00Z"))
    return sample
