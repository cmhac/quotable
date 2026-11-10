"""
The review queue, its sampling and the statistics of the review (spec 013, sections D1-D3, E).

Pure functions over the runs ``quotable.runs.load_run`` reads and the verdicts
``VerdictStore.latest`` returns; nothing here touches the disk. The population is the cells
(and extra fields) of the runs in scope whose status the settings ask for, in the order a
reviewer reads them; the queue is all of it or a seeded random sample of it, kept in that
order. Shares and margins are fractions (0.171 is 17.1%); the settings' target margin is in
percentage points, as the app shows it. Standard library only.
"""

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Literal

from quotable.review.verdicts import CATEGORIES, CellKey, ExtraKey, Key, Verdict
from quotable.runs import Run

FLAGGED = ("fuzzy", "misplaced", "ungrounded", "untokenized")
STATUSES = (*FLAGGED, "exact")
CONFIDENCES = (80, 90, 95, 99)
MODES = ("all", "sample")

ReviewState = Literal["correct", "changed", "unsure", "stale", "none"]


# --- settings ---------------------------------------------------------------------------------
def _number(
    query: Mapping[str, str], name: str, kind: Callable[[str], Any], default: Any, minimum: Any
) -> Any:
    text = query.get(name)
    if text is None:
        return default
    try:
        value = kind(text)
    except ValueError:
        msg = f"{name} must be a number"
        raise ValueError(msg) from None
    if not value >= minimum:
        msg = f"{name} must be at least {minimum}"
        raise ValueError(msg)
    return value


@dataclass(frozen=True)
class QueueSettings:
    """
    What to review and how to sample it.

    ``run`` is a run id, or ``None`` for the newest run of each document. ``table`` is a table
    index and ``column`` a column name, ``None`` for all. ``margin`` is the target margin of
    error in percentage points and ``confidence`` a percentage.
    """

    statuses: tuple[str, ...] = FLAGGED
    run: str | None = None
    table: int | None = None
    column: str | None = None
    extra_fields: bool = True
    mode: Literal["all", "sample"] = "all"
    sample_size: int = 100
    confidence: int = 95
    margin: float = 8.0
    seed: int = 1

    @classmethod
    def from_query(cls, query: Mapping[str, str]) -> "QueueSettings":
        """Read settings from query-string values; missing keys keep their defaults."""
        default = cls()
        statuses = default.statuses
        if "statuses" in query:
            statuses = tuple(s for s in query["statuses"].split(",") if s)
            if bad := [s for s in statuses if s not in STATUSES]:
                msg = f"unknown status {bad[0]!r}"
                raise ValueError(msg)
        flag = query.get("extra_fields", "1" if default.extra_fields else "0")
        if flag not in ("0", "1", "true", "false"):
            msg = "extra_fields must be 0 or 1"
            raise ValueError(msg)
        mode = query.get("mode", default.mode)
        if mode not in MODES:
            msg = f"mode must be one of {', '.join(MODES)}"
            raise ValueError(msg)
        confidence = _number(query, "confidence", int, default.confidence, 0)
        if confidence not in CONFIDENCES:
            msg = f"confidence must be one of {', '.join(map(str, CONFIDENCES))}"
            raise ValueError(msg)
        table = query.get("table")
        return cls(
            statuses=statuses,
            run=query.get("run") or None,
            table=None if table in (None, "") else _number(query, "table", int, 0, 0),
            column=query.get("column") or None,
            extra_fields=flag in ("1", "true"),
            mode=mode,
            sample_size=_number(query, "sample_size", int, default.sample_size, 1),
            confidence=confidence,
            margin=_number(query, "margin", float, default.margin, 1e-9),
            seed=_number(query, "seed", int, default.seed, -(2**63)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the settings as JSON-friendly values, as the verdict line keeps them."""
        return {
            "statuses": list(self.statuses),
            "run": self.run,
            "table": self.table,
            "column": self.column,
            "extra_fields": self.extra_fields,
            "mode": self.mode,
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "margin": self.margin,
            "seed": self.seed,
        }


# --- the population ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Item:
    """One thing to review: a cell, or an extra field's value on its printing page."""

    run: str
    name: str  # the PDF's file name
    sha256: str
    table_index: int
    table_label: str
    table_columns: tuple[str, ...]
    page: int  # for an extra field, the page that prints it
    row: int | None  # 1-based; ``None`` for an extra field
    column: str  # for an extra field, its name
    status: str
    extracted: str
    key: Key

    @property
    def extra(self) -> bool:
        """Whether this is an extra field rather than a table cell."""
        return isinstance(self.key, ExtraKey)


def _newest_per_document(runs: Sequence[Run]) -> list[Run]:
    newest: dict[str, Run] = {}
    for run in runs:
        info = run.summary
        best = newest.get(info.sha256)
        if best is None or (info.started, info.id) > (best.summary.started, best.summary.id):
            newest[info.sha256] = run
    return list(newest.values())


def scoped_items(runs: Sequence[Run], settings: QueueSettings) -> list[Item]:
    """Return every item in scope, of any status, in population order."""
    if settings.run is None:
        chosen = _newest_per_document(runs)
    else:
        chosen = [r for r in runs if r.summary.id == settings.run]
    found: list[tuple[tuple[Any, ...], Item]] = []
    for run in chosen:
        info = run.summary
        seen: set[tuple[int, str]] = set()
        for table in run.tables:
            if settings.table is not None and table.index != settings.table:
                continue
            columns = tuple(table.columns)
            for row in table.rows:
                for position, column in enumerate(columns):
                    if settings.column not in (None, column) or column not in row.cells:
                        continue
                    key = CellKey(info.sha256, columns, row.page, row.row, column)
                    item = Item(
                        info.id,
                        info.name,
                        info.sha256,
                        table.index,
                        table.label,
                        columns,
                        row.page,
                        row.row,
                        column,
                        row.cells[column].status,
                        row.values.get(column, ""),
                        key,
                    )
                    order = (info.name, info.id, 0, table.index, row.page, row.row, position)
                    found.append((order, item))
            if not settings.extra_fields or settings.column is not None:
                continue
            for results in table.extra_fields.values():
                for name, result in results.items():
                    printed = result.source_page
                    if printed is None or (printed, name) in seen:
                        continue
                    seen.add((printed, name))
                    item = Item(
                        info.id,
                        info.name,
                        info.sha256,
                        table.index,
                        table.label,
                        columns,
                        printed,
                        None,
                        name,
                        result.cell.status,
                        result.value,
                        ExtraKey(info.sha256, name, printed),
                    )
                    names = table.extra_names
                    position = names.index(name) if name in names else 0
                    order = (info.name, info.id, 1, table.index, printed, 0, position)
                    found.append((order, item))
    found.sort(key=lambda pair: pair[0])
    return [item for _, item in found]


def population(runs: Sequence[Run], settings: QueueSettings) -> list[Item]:
    """Return the items in scope whose status is one of ``settings.statuses``, in reading order."""
    return [i for i in scoped_items(runs, settings) if i.status in settings.statuses]


def counts_by_status(runs: Sequence[Run], settings: QueueSettings) -> dict[str, int]:
    """Count the items in scope by status, whatever statuses the settings choose."""
    counts: dict[str, int] = {}
    for item in scoped_items(runs, settings):
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def sample(items: Sequence[Item], settings: QueueSettings) -> list[Item]:
    """Return all ``items``, or ``sample_size`` of them drawn with ``seed``, in population order."""
    if settings.mode == "all":
        return list(items)
    size = min(settings.sample_size, len(items))
    positions = sorted(random.Random(settings.seed).sample(range(len(items)), size))
    return [items[p] for p in positions]


# --- statistics -------------------------------------------------------------------------------
def z(confidence: int) -> float:
    """Return the two-sided normal quantile of ``confidence`` percent."""
    return NormalDist().inv_cdf(1 - (1 - confidence / 100) / 2)


def suggested_size(target: float, confidence: int, population_size: int) -> int:
    r"""
    Return the sample size that gives a margin of ``target`` percentage points, at worst case.

    $n_0 = z^2 \cdot 0.25 / e^2$, corrected for a population of ``population_size``, rounded up
    and never more than the population.
    """
    if population_size <= 0:
        return 0
    e = target / 100
    n0 = z(confidence) ** 2 * 0.25 / e**2
    n = n0 / (1 + (n0 - 1) / population_size)
    return min(population_size, max(1, math.ceil(n - 1e-9)))


def wilson(changed: int, judged: int, confidence: int) -> tuple[float, float]:
    """Return the Wilson score interval of ``changed`` of ``judged`` (``judged`` above 0)."""
    zz = z(confidence)
    p = changed / judged
    denominator = 1 + zz**2 / judged
    centre = (p + zz**2 / (2 * judged)) / denominator
    half = zz * math.sqrt(p * (1 - p) / judged + zz**2 / (4 * judged**2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _correction(population_size: int, n: int) -> float:
    r"""Return $\sqrt{(N - n)/(N - 1)}$, 0 when everything was looked at."""
    if n >= population_size:
        return 0.0
    return math.sqrt((population_size - n) / max(population_size - 1, 1))


def _margin(zz: float, p: float, n: int, correction: float) -> float:
    return zz * math.sqrt(p * (1 - p) / n) * correction


def review_state(item: Item, verdicts: Mapping[Key, Verdict]) -> ReviewState:
    """Return the verdict that counts for ``item``, ``stale`` when the value changed since."""
    found = verdicts.get(item.key)
    if found is None:
        return "none"
    if found.extracted != item.extracted:
        return "stale"
    return found.verdict  # ty: ignore[invalid-return-type]


@dataclass(frozen=True)
class StatusStats:
    """One line of the by-status table; ``share`` is ``None`` when nothing is judged."""

    status: str
    population: int
    sampled: int
    reviewed: int
    judged: int
    changed: int
    share: float | None


@dataclass(frozen=True)
class Stats:
    """
    Every number of section E; ``None`` where there is nothing to compute it from.

    ``reviewed`` counts every verdict that applies (``unsure`` too), ``judged`` leaves out
    ``unsure``. The two corrections are the finite-population factors under the margins.
    """

    confidence: int
    population: int
    sample: int
    reviewed: int
    judged: int
    unsure: int
    changed: int
    share: float | None
    interval: tuple[float, float] | None
    estimated: float | None
    estimated_interval: tuple[float, float] | None
    margin_before: float | None
    correction_before: float
    margin_so_far: float | None
    correction_so_far: float
    by_status: list[StatusStats]
    total: StatusStats
    categories: list[tuple[str, int]]


def _status_stats(
    status: str,
    pop: Sequence[Item],
    queue: Sequence[Item],
    states: Mapping[int, ReviewState],
) -> StatusStats:
    reviewed = judged = changed = 0
    for item in queue:
        state = states[id(item)]
        if state in ("none", "stale"):
            continue
        reviewed += 1
        if state != "unsure":
            judged += 1
            changed += state == "changed"
    return StatusStats(
        status,
        len(pop),
        len(queue),
        reviewed,
        judged,
        changed,
        changed / judged if judged else None,
    )


def statistics(
    pop: Sequence[Item],
    queue: Sequence[Item],
    verdicts: Mapping[Key, Verdict],
    settings: QueueSettings,
) -> Stats:
    """Compute section E for ``queue``, drawn from the population ``pop``, under ``verdicts``."""
    zz = z(settings.confidence)
    n_pop, n_queue = len(pop), len(queue)
    states = {id(i): review_state(i, verdicts) for i in queue}
    total = _status_stats("All", pop, queue, states)
    by_status = [
        _status_stats(
            s, [i for i in pop if i.status == s], [i for i in queue if i.status == s], states
        )
        for s in settings.statuses
        if any(i.status == s for i in pop)
    ]
    unsure = sum(1 for s in states.values() if s == "unsure")
    categories: dict[str, int] = {}
    for item in queue:
        found = verdicts.get(item.key)
        if states[id(item)] == "changed" and found is not None and found.category is not None:
            categories[found.category] = categories.get(found.category, 0) + 1
    order = list(CATEGORIES)
    ranked = sorted(categories.items(), key=lambda kv: (-kv[1], order.index(kv[0])))
    share = total.share
    interval = estimated = estimated_interval = margin_so_far = None
    if share is not None:
        interval = wilson(total.changed, total.judged, settings.confidence)
        estimated = share * n_pop
        estimated_interval = (interval[0] * n_pop, interval[1] * n_pop)
    correction_before = _correction(n_pop, n_queue)
    correction_so_far = _correction(n_pop, total.judged)
    if share is not None:
        margin_so_far = _margin(zz, share, total.judged, correction_so_far)
    return Stats(
        confidence=settings.confidence,
        population=n_pop,
        sample=n_queue,
        reviewed=total.reviewed,
        judged=total.judged,
        unsure=unsure,
        changed=total.changed,
        share=share,
        interval=interval,
        estimated=estimated,
        estimated_interval=estimated_interval,
        margin_before=_margin(zz, 0.5, n_queue, correction_before) if n_queue else None,
        correction_before=correction_before,
        margin_so_far=margin_so_far,
        correction_so_far=correction_so_far,
        by_status=by_status,
        total=total,
        categories=ranked,
    )
