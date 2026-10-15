"""
Tests that call a real model. They cost money and need credentials, so they are
deselected by default (``addopts = -m 'not live'``) and skip themselves unless both
environment variables are set:

    OPENAI_API_KEY                   the provider's API key
    GRIDKEY_LIVE_MODEL     a pydantic-ai model string, e.g. "openai:<model-name>"

Run them with:  uv run pytest -m live

Answers are cached under ``tests/live/.cache`` (git-ignored), so a second run costs
nothing, and ``max_requests`` caps what one run can spend.
"""

import json
import os
from pathlib import Path

import pytest

from gridkey import CachedClient, extract_table
from gridkey.pydantic_ai_client import PydanticAIClient
from tests.conftest import DATA

MODEL = os.environ.get("GRIDKEY_LIVE_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and GRIDKEY_LIVE_MODEL to run live tests",
    ),
]

MAX_NEW_REQUESTS = 6  # one document page: schema + extract (+ recheck)
CACHE = Path(__file__).parent / ".cache"


def test_a_one_page_document_is_extracted_and_grounded_by_a_real_model():
    name = "fy22_milcon_house_original"
    recorded = json.loads((DATA / f"{name}.rows.json").read_text())
    client = CachedClient(PydanticAIClient(MODEL), CACHE / name, max_requests=MAX_NEW_REQUESTS)

    table = extract_table(DATA / f"{name}.pdf", client)

    assert len(table.columns) == len(recorded["columns"])
    expected_rows = len(recorded["pages"]["1"])
    assert abs(len(table.rows()) - expected_rows) <= 2
    cells = [c for row in table.rows() for c in row.cells.values() if c.status != "empty"]
    grounded = [c for c in cells if c.status in {"exact", "fuzzy"}]
    assert len(grounded) / len(cells) >= 0.9
