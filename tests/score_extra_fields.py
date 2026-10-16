"""
Score the extra-fields checks on the golden fixture, with injected faults (spec 010).

No model and no cost: a fake model (``tests/extra_fields_model.py``) answers from each ``extra-*``
document's truth, and one fault at a time is injected into what it reads. The library's own
steps then run (grounding, the field recheck, the region check, the second look, the carry
rule), and for each fault kind the scorer prints how often the final values were right, how
many missed headers the region check caught, how many second looks were false alarms and how
many requests the checks cost. The fake model answers a second look and a recheck faithfully,
so the numbers measure the library's checks, not any real model. Run it with
``just score-extra-fields``.

Faults: ``none`` (a faithful model); ``missed`` (a block the model does not report, tried on
each block page in turn, where every field of that block is printed on some other page too, so the
region check has a place to look); ``missed_only`` (the same for a block with a field printed
nowhere else: nothing shows the check where that header would be, so it cannot be caught, by
design);
``invented`` (a value reported on a page that prints none, for a field
that has a place); ``misread`` (a block value with one letter changed); ``wrong_page`` (a block
value reported on the page before it is printed).

A run is ``right`` when every final value and source page equal the truth. Otherwise it is
``flagged`` when each wrong field at least shows a status that ``flagged()`` reports
(``ungrounded`` and the like), or ``silent`` when some wrong field looks fine (``exact``) or is
simply missing: the failure that matters.
"""

import asyncio
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from quotable.extract import run_pipeline
from quotable.grounding import UNFLAGGED
from tests.extra_fields_model import request_for, truth_model
from tests.fixture_tables import DATA, doc_ids

KINDS = ("none", "missed", "missed_only", "invented", "misread", "wrong_page")
Reads = dict[int, dict[str, str | None]]


@dataclass
class Tally:
    """Counts for one fault kind over every document and every injection."""

    runs: int = 0
    right: int = 0  # runs whose final values equal the truth
    flagged: int = 0  # wrong runs in which every wrong field is flagged
    silent: int = 0  # wrong runs with a wrong field that looks fine, or is missing
    injected: int = 0  # faults injected
    caught: int = 0  # missed headers recovered through the region check and the second look
    false_alarms: int = 0  # second looks on pages where the model had missed nothing
    second_looks: int = 0
    pages: int = 0
    wrong: list[str] = field(default_factory=list)


def _truth(case_id: str) -> dict[str, Any]:
    return json.loads((DATA / f"{case_id}.json").read_text())["extra_fields"]


def _faithful_second_look(
    truth: dict[str, Any],
) -> Callable[[int, list[str]], dict[str, str | None]]:
    """A second look that answers from the truth: the page's printed values, else nothing."""
    printed = {int(p): v for p, v in truth["printed"].items()}

    def answer(page: int, names: list[str]) -> dict[str, str | None]:
        return {n: printed[page].get(n) for n in names}

    return answer


def _mangle(text: str) -> str:
    """Change one character, so the value no longer grounds exactly."""
    i = next((k for k, c in enumerate(text) if c.isalpha()), len(text) - 1)
    return text[:i] + ("q" if text[i] != "q" else "z") + text[i + 1 :]


def injections(truth: dict[str, Any], kind: str) -> list[Reads]:
    """Return what the model reads instead of the truth, one dict per injection."""
    printed = {int(p): v for p, v in truth["printed"].items()}
    names = [f["name"] for f in truth["fields"]]
    block_pages = [p for p, row in printed.items() if any(v is not None for v in row.values())]
    out: list[Reads] = []
    if kind == "none":
        out.append({})
    elif kind in ("missed", "missed_only"):
        for p in block_pages:
            elsewhere = {n for q in block_pages if q != p for n in names if printed[q][n]}
            seen_before = all(printed[p][n] is None or n in elsewhere for n in names)
            if seen_before == (kind == "missed"):
                out.append({p: dict.fromkeys(names)})
    elif kind == "misread":
        for p in block_pages:
            name = next(n for n in names if printed[p][n] is not None)
            out.append({p: {name: _mangle(str(printed[p][name]))}})
    elif kind == "wrong_page":
        for p in block_pages:
            if p > 1 and p - 1 not in block_pages:
                out.append({p - 1: dict(printed[p]), p: dict.fromkeys(names)})
    elif kind == "invented":
        placed = [n for n in names if any(row[n] is not None for row in printed.values())]
        empty = [p for p in printed if p not in block_pages]
        if placed and empty:
            out.append({empty[0]: {placed[0]: "Zebra"}})
    return out


Final = dict[int, dict[str, tuple[str, int | None, str]]]


def final_values(tables: list[Any]) -> Final:
    """page -> field -> (value, source page, grounding status) over every page of every table."""
    return {
        page: {n: (r.value, r.source_page, r.grounding.status) for n, r in row.items()}
        for table in tables
        for page, row in table.extra_fields.items()
    }


def score_one(case_id: str, kind: str, read: Reads, tally: Tally) -> None:
    """Run one document with one injected fault and add the result to ``tally``."""
    truth = _truth(case_id)
    recheck = {(int(p), n): v for p, row in truth["printed"].items() for n, v in row.items() if v}
    client = truth_model(case_id, read=read, second=_faithful_second_look(truth), recheck=recheck)
    request = request_for(truth, carry=True)
    tables = asyncio.run(run_pipeline(DATA / f"{case_id}.pdf", client, extra_fields=request))
    expected = {
        int(p): {n: (v["value"], v["source_page"]) if v else None for n, v in row.items()}
        for p, row in truth["expected"]["carry"].items()
    }
    got = final_values(tables)
    pages = {r.page for t in tables for r in t.pages}
    looks = sorted(r.page or 0 for r in client.requests if r.stage == "extras")
    missed = {p for p, row in read.items() if kind.startswith("missed") and not any(row.values())}
    wrong = [
        got[p][n]
        for p in pages
        for n, want in expected[p].items()
        if (got[p][n][0], got[p][n][1]) != (want if want else ("", None))
    ]
    tally.runs += 1
    tally.injected += len(read) if kind != "none" else 0
    tally.second_looks += len(looks)
    tally.pages += max(pages)
    tally.right += not wrong
    tally.silent += any(status in UNFLAGGED for _, _, status in wrong)
    tally.flagged += bool(wrong) and all(status not in UNFLAGGED for _, _, status in wrong)
    if wrong:
        tally.wrong.append(case_id)
    tally.caught += len(missed & set(looks))
    tally.false_alarms += len([p for p in looks if p not in missed and p not in read])


def main() -> None:
    """Print the table of results."""
    ids = [i for i in doc_ids() if i.startswith("extra-")]
    tallies: dict[str, Tally] = defaultdict(Tally)
    for kind in KINDS:
        for case_id in ids:
            truth = _truth(case_id)
            if truth["expect_stale"] or truth["expect_blind"]:
                continue  # documented limits: scored by neither side
            for read in injections(truth, kind):
                score_one(case_id, kind, read, tallies[kind])
    head = f"{'fault':<12}{'runs':>5}{'right':>7}{'flagged':>8}{'silent':>7}"
    print(head + f"{'caught':>7}{'false alarms':>13}{'looks/100p':>11}")  # noqa: T201
    for kind in KINDS:
        t = tallies[kind]
        per_100 = 100 * t.second_looks / t.pages if t.pages else 0.0
        row = f"{kind:<12}{t.runs:>5}{t.right:>7}{t.flagged:>8}{t.silent:>7}{t.caught:>7}"
        print(row + f"{t.false_alarms:>13}{per_100:>11.1f}")  # noqa: T201
        if t.wrong:
            print(f"  not right: {sorted(set(t.wrong))}")  # noqa: T201


if __name__ == "__main__":
    main()
