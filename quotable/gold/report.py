"""
The gold report as text, JSON-able data and CSV (spec 016).

``format_text`` is what ``quotable gold-report`` prints and ``to_json`` is what the review app
shows; both come from the same :class:`~quotable.gold.score.Report`. The CSV files follow
``specs/016-gold-quality-check/contracts/gold-files.md``. Standard library only.
"""

import csv
import io
from typing import Any

from quotable.gold.score import (
    BENCHMARK,
    LEVELS,
    Counts,
    Interval,
    PageScore,
    Report,
    Unit,
)

PAGE_COLUMNS = (
    "document",
    "page",
    "correct",
    "gold_tables",
    "extracted_tables",
    "gold_rows",
    "extracted_rows",
    "matched_rows",
    "rows",
    "rows_correct",
    "cells",
    "gold_cells",
    "extracted_cells",
    "cells_correct",
    "missed",
    "extra",
    "exact",
    "normal",
    "fuzzy",
)
CELL_COLUMNS = ("document", "page", "table", "column", "gold_row", "gold", "extracted", "best")
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def rate(n: int, d: int) -> str:
    """Format a share as a percentage."""
    return f"{n / d:6.1%}" if d else "   n/a"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _unit_line(unit: Unit) -> str:
    return (
        f"  {unit.name:<5} {unit.correct:>8} {unit.gold:>8} {unit.extracted:>10}  "
        f"{rate(unit.correct, unit.gold)}     {rate(unit.correct, unit.extracted)}"
        f"    {rate(unit.correct, unit.either)}"
    )


def _interval_line(interval: Interval) -> str:
    return (
        f"pages correct: {interval.share:.1%} of {interval.n} counted pages, "
        f"{interval.confidence}% interval {interval.low:.1%} to {interval.high:.1%} "
        f"({interval.sampled} of the document's {interval.pages} pages were sampled; "
        "an estimate for this document only. Cell and row figures have no interval: "
        "cells on one page are not independent)"
    )


def _counts_line(label: str, counts: Counts) -> str:
    return (
        f"  {label}: cells correct {counts.cells_correct} of {counts.cells - counts.extra} gold "
        f"({rate(counts.cells_correct, counts.cells - counts.extra).strip()}), "
        f"rows correct {counts.rows_correct} of {counts.gold_rows} gold / {counts.pred_rows} "
        f"extracted, missed cells {counts.missed}, extra cells {counts.extra}"
    )


def _pairing_lines(report: Report) -> list[str]:
    names = {d.sha256: d.name for d in report.sample.documents}
    lines = []
    for page in report.pages:
        for pair in page.pairs:
            parts = []
            for c in pair.columns:
                if c.gold is None:
                    parts.append(f"(extra column {c.extracted})")
                elif c.extracted is None:
                    parts.append(f"{c.gold} (no partner)")
                else:
                    parts.append(f"{c.gold} = {c.extracted} [{c.how}]")
            where = f"{names[page.sha256]} p{page.page} gold table {pair.gold} = {pair.label}"
            lines.append(f"  {where}: " + "; ".join(parts))
        for number in page.unmatched_gold:
            lines.append(
                f"  {names[page.sha256]} p{page.page} gold table {number}: no extracted table"
            )
    return lines


def format_text(report: Report) -> str:
    """Return the report as the text ``gold-report`` prints."""
    total = report.total
    out = [
        f"{len(report.pages)} gold pages from {len(report.runs)} documents, scored at the "
        f"{BENCHMARK!r} cell level",
        "",
    ]
    for ref in report.runs.values():
        out.append(f"  {ref.name}: run {ref.id[:8]} ({ref.model}, {ref.started})")
    if report.not_scored:
        out.append("  NOT SCORED (no usable run): " + ", ".join(report.not_scored))
    out += [f"  NOTE: {note}" for note in report.notes]
    out += ["", "  unit   correct     gold  extracted  recall  precision  accuracy"]
    out += [_unit_line(u) for u in report.units]
    out += [
        "",
        "  cell:  a cell with text in the gold or the extraction. It is correct if the",
        f"         gold has text and the extraction passes {BENCHMARK!r}.",
        "  row:   a gold row or an extracted row. It is correct if it pairs with a row",
        "         on the other side and every cell in it is correct.",
        "  page:  a page where the gold or the extraction has rows. It is correct if",
        "         every row on it is correct, with no missed or extra rows.",
        "",
        "  recall = correct / gold, precision = correct / extracted,",
        "  accuracy = correct / units in either the gold or the extraction",
        "",
        f"rows: gold {total.gold_rows}, extracted {total.pred_rows}",
        f"  paired {total.matched_rows}",
        f"  missed gold rows {total.gold_rows - total.matched_rows}",
        f"  extra extracted rows {total.pred_rows - total.matched_rows}",
        "",
        "cell accuracy at every level:",
    ]
    out += [f"  {level:<6} {rate(total.hits[level], total.cells).strip()}" for level in LEVELS]
    out += [
        f"  missed (gold has text, extraction blank) {total.missed}",
        f"  extra  (extraction has text, gold blank) {total.extra}",
        "",
    ]
    if report.interval is not None:
        out += [_interval_line(report.interval), ""]
    if len(report.documents) > 1 or report.tables:
        out.append("by document:")
        out += [_counts_line(d.name, d.counts) for d in report.documents]
        out += ["", "by extracted table:"]
        out += [_counts_line(f"{t.name} / {t.label}", t.counts) for t in report.tables]
        out.append("")
    pairings = _pairing_lines(report)
    if pairings:
        out += ["column pairing (how: name, or values when the names differ):", *pairings, ""]
    return "\n".join(out) + "\n"


def _page_json(page: PageScore) -> dict[str, Any]:
    return {
        "sha256": page.sha256,
        "page": page.page,
        "counted": page.counted,
        "correct": page.correct,
        "gold_tables": page.gold_tables,
        "extracted_tables": page.pred_tables,
        "counts": _counts_json(page.counts),
        "pairs": [
            {
                "gold": p.gold,
                "extracted": p.extracted,
                "label": p.label,
                "columns": [
                    {"gold": c.gold, "extracted": c.extracted, "how": c.how} for c in p.columns
                ],
            }
            for p in page.pairs
        ],
        "unmatched_gold": page.unmatched_gold,
        "unmatched_extracted": page.unmatched_extracted,
    }


def _counts_json(c: Counts) -> dict[str, Any]:
    return {
        "cells": c.cells,
        "hits": dict(c.hits),
        "missed": c.missed,
        "extra": c.extra,
        "cells_correct": c.cells_correct,
        "gold_rows": c.gold_rows,
        "pred_rows": c.pred_rows,
        "matched_rows": c.matched_rows,
        "rows": c.rows,
        "rows_correct": c.rows_correct,
    }


def to_json(report: Report) -> dict[str, Any]:
    """Return the report as plain data for the review app."""
    return {
        "runs": {
            sha: {"id": r.id, "started": r.started, "model": r.model, "name": r.name}
            for sha, r in report.runs.items()
        },
        "not_scored": report.not_scored,
        "notes": report.notes,
        "benchmark": BENCHMARK,
        "total": _counts_json(report.total),
        "units": [
            {
                "name": u.name,
                "correct": u.correct,
                "gold": u.gold,
                "extracted": u.extracted,
                "either": u.either,
                "recall": u.recall,
                "precision": u.precision,
                "accuracy": u.accuracy,
            }
            for u in report.units
        ],
        "documents": [
            {
                "sha256": d.sha256,
                "name": d.name,
                "pages": d.pages,
                "counted": d.counted,
                "correct": d.correct,
                "counts": _counts_json(d.counts),
            }
            for d in report.documents
        ],
        "tables": [
            {
                "sha256": t.sha256,
                "name": t.name,
                "index": t.index,
                "label": t.label,
                "counts": _counts_json(t.counts),
            }
            for t in report.tables
        ],
        "interval": None
        if report.interval is None
        else {
            "share": report.interval.share,
            "low": report.interval.low,
            "high": report.interval.high,
            "confidence": report.interval.confidence,
            "n": report.interval.n,
            "sampled": report.interval.sampled,
            "pages": report.interval.pages,
        },
        "pages": [_page_json(p) for p in report.pages],
        "cells": report.cells,
    }


def _safe(value: object) -> str:
    """Return ``value`` as text that a spreadsheet will not run as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def _csv(header: tuple[str, ...], rows: list[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([[_safe(v) for v in row] for row in rows])
    return buffer.getvalue()


def pages_csv(report: Report) -> str:
    """Return one line per counted page."""
    names = {d.sha256: d.name for d in report.sample.documents}
    rows: list[list[object]] = []
    for p in report.pages:
        if not p.counted:
            continue
        c = p.counts
        rows.append(
            [
                names[p.sha256],
                p.page,
                p.correct,
                p.gold_tables,
                p.pred_tables,
                c.gold_rows,
                c.pred_rows,
                c.matched_rows,
                c.rows,
                c.rows_correct,
                c.cells,
                c.cells - c.extra,
                c.cells - c.missed,
                c.cells_correct,
                c.missed,
                c.extra,
                *(c.hits[level] for level in LEVELS),
            ]
        )
    return _csv(PAGE_COLUMNS, rows)


def cells_csv(report: Report) -> str:
    """Return one line per cell that is not an exact match."""
    rows: list[list[object]] = [[cell[name] for name in CELL_COLUMNS] for cell in report.cells]
    return _csv(CELL_COLUMNS, rows)
