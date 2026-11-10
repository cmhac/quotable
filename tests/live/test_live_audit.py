"""
Live check of the omission audit and sharp page images (spec 014, success criterion SC-005).

It runs one real multi-page document four ways (audit off or on, sharp images off or on) with a
real model and prints what each setting cost and found. It costs money and needs credentials, so
it is deselected by default and skips itself unless both variables are set:

    OPENAI_API_KEY             the provider's API key
    QUOTABLE_LIVE_TEST_MODEL    a pydantic-ai model string, e.g. "openai:<model-name>"

Run it with ``just test-live tests/live/test_live_audit.py -s`` and read the table it prints (it
is also written to ``tests/live/.cache/audit_results.json``). The document is
``QUOTABLE_LIVE_AUDIT_PDF`` if set, else the 4-page sample in ``tests/data/``.

Runs with the same image setting share one cache folder, so the extraction and the recheck are
paid for once per setting and the audit variants add only their own requests. The numbers printed
for a variant are the requests it actually made.
"""

import asyncio
import json
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from quotable import extract_tables
from quotable.llm.client import CachedClient, PydanticAIClient
from quotable.llm.images import policy_for
from quotable.steps.audit import audit_table
from quotable.steps.recheck import recheck_table
from quotable.storage import CostLog, CostRecord
from quotable.table import ground_document
from quotable.text.layer import tokenize
from tests.conftest import DATA

MODEL = os.environ.get("QUOTABLE_LIVE_TEST_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and QUOTABLE_LIVE_TEST_MODEL to run live tests",
    ),
]

CACHE = Path(__file__).parent / ".cache"
PDF = Path(os.environ.get("QUOTABLE_LIVE_AUDIT_PDF", DATA / "fy22_ag_house_original.pdf"))
MAX_NEW_REQUESTS = 40  # per call: discovery, one request per page, rechecks, audits
# (label, audit, sharp_images). The plain pair runs first so its extraction fills the cache.
VARIANTS = [
    ("old", False, False),
    ("audit", True, False),
    ("sharp", False, True),
    ("audit+sharp", True, True),
]


def new_records(seen: int) -> list[CostRecord]:
    """Return the cost records written since the first ``seen`` lines of this run's log."""
    log = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
    lines = log.read_text().splitlines() if log.exists() else []
    return [CostRecord.from_line(line) for line in lines[seen:]]


def test_the_audit_and_sharp_images_on_a_real_document():
    rows = []
    for label, audit, sharp in VARIANTS:
        log = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
        seen = len(log.read_text().splitlines()) if log.exists() else 0
        tables = extract_tables(
            PDF,
            MODEL,
            cache_dir=CACHE / ("sharp" if sharp else "plain") / PDF.stem,
            max_requests=MAX_NEW_REQUESTS,
            audit=audit,
            sharp_images=sharp,
        )
        paid = new_records(seen)
        items = [a for t in tables for a in t.audit]
        kept = [a for a in items if a.outcome == "accepted"]
        rows.append(
            {
                "variant": label,
                "tables": len(tables),
                "rows": sum(len(t.rows()) for t in tables),
                "flagged_cells": sum(len(t.flagged()) for t in tables),
                "new_requests": dict(Counter(r.stage for r in paid)),
                "input_tokens": sum(r.input_tokens for r in paid),
                "output_tokens": sum(r.output_tokens for r in paid),
                "cost_usd": sum(r.cost_usd or 0 for r in paid),
                "pages": sum(len(t.pages) for t in tables),
                # audit requests actually paid for (an audit answered from the cache is not counted)
                "audit_requests": sum(r.stage == "audit" for r in paid),
                "kept_rows": sum(a.kind == "row" for a in kept),
                "kept_cells": sum(a.kind == "cell" for a in kept),
                "rejected": dict(Counter(a.outcome for a in items if a.outcome != "accepted")),
            }
        )
        # FR-006: whatever the audit kept is found in the page's text layer
        for table in tables:
            for item in (a for a in table.audit if a.outcome == "accepted"):
                assert item.row is not None
                row = table.page_rows(item.page)[item.row - 1]
                for column in item.values:
                    assert row.cells[column].status in {"exact", "fuzzy"}, (label, item)
        if not audit:
            assert items == [], label
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "audit_results.json").write_text(json.dumps(rows, indent=1))
    for row in rows:
        print(json.dumps(row))  # noqa: T201


def test_the_audit_finds_rows_and_cells_removed_from_a_real_extraction():
    """Remove each page's last row and one cell of its second row, and ask the real model."""
    (table,) = extract_tables(
        PDF, MODEL, cache_dir=CACHE / "plain" / PDF.stem, audit=False, sharp_images=False
    )  # answered from the cache after the test above
    pages, dropped, blanked = [], {}, {}
    for result in table.pages:
        rows = [dict(r) for r in result.rows]
        dropped[result.page] = rows.pop()
        column = next(c for c in reversed(table.columns) if rows[1][c].strip())
        blanked[result.page] = (column, rows[1][column])
        rows[1][column] = ""
        pages.append(replace(result, rows=rows))
    grounded, position = ground_document(table.columns, pages, table.layers)
    cut = replace(table, pages=pages, grounded=grounded, position=position)

    folder = CACHE / "inject" / PDF.stem
    folder.mkdir(parents=True, exist_ok=True)
    log = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
    seen = len(log.read_text().splitlines()) if log.exists() else 0
    client = CachedClient(
        PydanticAIClient(MODEL, on_usage=CostLog().record_usage), folder, MAX_NEW_REQUESTS
    )
    images = policy_for(MODEL, sharp=True)
    audited = asyncio.run(audit_table(cut, PDF, client, images, asyncio.Semaphore(4)))
    # what the rest of the pipeline then does with the added rows: the recheck
    final = asyncio.run(recheck_table(audited, PDF, client, images, asyncio.Semaphore(4)))

    def text(values) -> list[str]:
        return tokenize(" ".join(values))

    kept = [a for a in audited.audit if a.outcome == "accepted"]
    rows_back = sum(
        any(
            a.kind == "row" and a.page == p and text(a.values.values()) == text(row.values())
            for a in kept
        )
        for p, row in dropped.items()
    )
    cells_back = sum(
        any(
            a.kind == "cell" and a.page == p and text(a.values.get(column, "")) == text(value)
            for a in kept
        )
        for p, (column, value) in blanked.items()
    )
    paid = new_records(seen)
    added = [a for a in kept if a.kind == "row"]

    def status(table, item) -> str:
        assert item.row is not None
        return table.page_rows(item.page)[item.row - 1].status

    summary = {
        "pages": len(dropped),
        "rows_removed": len(dropped),
        "rows_restored": rows_back,
        "cells_removed": len(blanked),
        "cells_restored": cells_back,
        "kept_in_all": len(kept),
        "added_rows_status_after_audit": [status(audited, a) for a in added],
        "added_rows_status_after_recheck": [status(final, a) for a in added],
        "added_rows_equal_the_removed_row": sum(
            text(final.page_rows(a.page)[a.row - 1].values.values())
            == text(dropped[a.page].values())
            for a in added
            if a.row is not None
        ),
        "rejected": dict(Counter(a.outcome for a in audited.audit if a.outcome != "accepted")),
        "audit_requests_paid": sum(r.stage == "audit" for r in paid),
        "recheck_requests_paid": sum(r.stage == "recheck" for r in paid),
        "input_tokens": sum(r.input_tokens for r in paid),
        "cost_usd": sum(r.cost_usd or 0 for r in paid),
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "audit_injected.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))  # noqa: T201
    for item in kept:  # whatever was kept is confirmed by the text layer (FR-006)
        assert item.row is not None
        row = audited.page_rows(item.page)[item.row - 1]
        assert all(row.cells[c].status in {"exact", "fuzzy"} for c in item.values)
