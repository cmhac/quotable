"""
Scoring a project's gold (spec 016): the one entry point the review app and the command share.

``score_project`` reads the sample, the typed pages and the saved runs of a project folder,
chooses a run for each sampled document (the newest, or the ones named) and returns either the
:class:`~quotable.gold.score.Report` or, while pages are not done, the
:class:`~quotable.gold.score.Progress`. It writes nothing and calls no model.
"""

from collections.abc import Sequence
from pathlib import Path

from quotable.gold.sample import choose_runs
from quotable.gold.score import (
    ExtractedTable,
    Progress,
    Report,
    RunRef,
    evaluate,
    extracted_from_run,
    progress,
)
from quotable.gold.store import GoldError, GoldStore, SampleStore
from quotable.runs import list_runs, load_run


def score_project(project_dir: Path, run_ids: Sequence[str] = ()) -> Report | Progress:
    """
    Score the project's gold, or say how much of the sample is still to do.

    Raises :class:`GoldError` when no sample was drawn, when a gold file cannot be read, or when
    ``run_ids`` names an unknown run or two runs of one document.
    """
    sample = SampleStore(project_dir).load()
    if sample is None:
        msg = "no sample has been drawn yet; draw one in the review app (Gold check)"
        raise GoldError(msg)
    pages = GoldStore(project_dir).pages()
    status = progress(sample, pages)
    if not status.complete:
        return status
    summaries, _ = list_runs(project_dir)
    chosen, notes = choose_runs(summaries, sample, run_ids)
    extracted: dict[str, tuple[RunRef, list[ExtractedTable]]] = {}
    for sha, summary in chosen.items():
        try:
            run = load_run(project_dir, summary.id)
        except (KeyError, ValueError):
            notes.append(f"run {summary.id[:8]} of {summary.name} cannot be read")
            continue
        ref = RunRef(summary.id, summary.started, summary.model, summary.name)
        extracted[sha] = (ref, extracted_from_run(run))
    report = evaluate(sample, pages, extracted)
    report.notes = notes
    return report
