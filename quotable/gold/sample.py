"""
Drawing the gold sample (spec 015, research 13): which pages of which documents to type.

The VRA rule without its document families: every document gets one page, and the rest go one
at a time to the document with the highest ``sqrt(pages) / (pages so far + 1)`` that still has
pages left, so long documents get more pages without crowding out short ones. Pages inside a
document are drawn with ``random.Random(seed)``; documents are taken in the order of their file
name and SHA-256, so the same documents, size and seed always give the same pages.

Standard library only.
"""

import math
import random
from collections.abc import Sequence

from quotable.gold.store import Invalid, Sample, SampleDoc, now
from quotable.runs import RunSummary


def newest_by_document(runs: Sequence[RunSummary]) -> dict[str, RunSummary]:
    """Return the newest run of each document (by SHA-256) from runs listed newest first."""
    newest: dict[str, RunSummary] = {}
    for run in runs:
        newest.setdefault(run.sha256, run)
    return newest


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Split ``n`` pages across documents: one each, then by the square root of their size."""
    if n < len(sizes) or n > sum(sizes.values()):
        msg = f"cannot draw {n} pages from {len(sizes)} documents of {sum(sizes.values())} pages"
        raise Invalid(msg)
    counts = dict.fromkeys(sizes, 1)
    for _ in range(n - len(sizes)):
        open_ = [d for d in sizes if counts[d] < sizes[d]]
        best = max(open_, key=lambda d: (math.sqrt(sizes[d]) / (counts[d] + 1), d))
        counts[best] += 1
    return counts


def draw(docs: Sequence[SampleDoc], n: int, seed: int) -> list[tuple[str, int]]:
    """Return ``n`` distinct (SHA-256, page) pairs, in document order and then page order."""
    ordered = sorted(docs, key=lambda d: (d.name, d.sha256))
    if any(d.pages < 1 for d in ordered):
        msg = "a document has no pages"
        raise Invalid(msg)
    counts = allocate({d.sha256: d.pages for d in ordered}, n)
    rng = random.Random(seed)  # noqa: S311  a sample, not a secret
    picked: list[tuple[str, int]] = []
    for doc in ordered:
        pool = list(range(1, doc.pages + 1))
        rng.shuffle(pool)
        picked.extend((doc.sha256, page) for page in sorted(pool[: counts[doc.sha256]]))
    return picked


def choose_runs(
    runs: Sequence[RunSummary], sample: Sample, run_ids: Sequence[str] = ()
) -> tuple[dict[str, RunSummary], list[str]]:
    """
    Choose the run to score for each sampled document, from runs listed newest first.

    The newest run of a document unless ``run_ids`` names one. Returns the runs by SHA-256 and
    notes for the report. Raises :class:`Invalid` for an unknown run or two runs of one
    document; a named run of a document that is not in the sample (for example a PDF that was
    edited after the gold was typed) is left out with a note.
    """
    by_id = {r.id: r for r in runs}
    chosen = {sha: r for sha, r in newest_by_document(runs).items() if sample.has_document(sha)}
    notes: list[str] = []
    named: dict[str, RunSummary] = {}
    for run_id in run_ids:
        run = by_id.get(run_id)
        if run is None:
            msg = f"no saved run {run_id}"
            raise Invalid(msg)
        if run.sha256 in named:
            msg = f"runs {named[run.sha256].id[:8]} and {run.id[:8]} are of the same document"
            raise Invalid(msg)
        named[run.sha256] = run
        if not sample.has_document(run.sha256):
            notes.append(f"run {run.id[:8]} of {run.name} was left out: its document has no gold")
    chosen.update({sha: r for sha, r in named.items() if sample.has_document(sha)})
    return chosen, notes


def make_sample(docs: Sequence[SampleDoc], n: int, seed: int) -> Sample:
    """Draw a sample and return it with the documents in drawing order."""
    ordered = sorted(docs, key=lambda d: (d.name, d.sha256))
    return Sample(seed, n, now(), ordered, draw(ordered, n, seed))
