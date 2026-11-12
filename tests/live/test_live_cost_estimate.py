"""
Live check of the cost estimates and the cost limit (spec 017, success criteria SC-001 to SC-003).

It costs money and needs credentials, so it is deselected by default and skips itself unless both
variables are set:

    OPENAI_API_KEY             the provider's API key
    QUOTABLE_LIVE_TEST_MODEL    a pydantic-ai model string, e.g. "openai:<model-name>"

Do not run it without the owner's go-ahead. Run it with
``just test-live tests/live/test_live_cost_estimate.py -s`` and read what it prints: the discovery
estimate, the estimate for the rest and what the run really cost, side by side. SC-003 sets the
target (each within 25% of the actual cost); this test records the numbers and asserts only what
is certain: a limit below the discovery estimate stops before any request, and the final total
equals the cost log's sum.

The document is ``QUOTABLE_LIVE_COST_PDF`` if set, else the 4-page sample in ``tests/data/``.
"""

import json
import os
import re
from decimal import Decimal
from pathlib import Path

import pytest

from quotable import CostLimitExceededError, extract_tables
from tests.conftest import DATA

MODEL = os.environ.get("QUOTABLE_LIVE_TEST_MODEL", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (MODEL and os.environ.get("OPENAI_API_KEY")),
        reason="set OPENAI_API_KEY and QUOTABLE_LIVE_TEST_MODEL to run live tests",
    ),
]

PDF = Path(os.environ.get("QUOTABLE_LIVE_COST_PDF", DATA / "fy22_ag_house_original.pdf"))
CACHE = Path(__file__).parent / ".cache" / "cost_estimate"


def logged_total() -> Decimal:
    log = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    return sum(
        (Decimal(str(r["cost_usd"])) for r in records if r["cost_usd"] is not None), Decimal(0)
    )


def test_the_estimates_beside_the_actual_cost(capsys):
    CACHE.mkdir(parents=True, exist_ok=True)
    with pytest.raises(CostLimitExceededError) as stopped:  # a limit below any estimate
        extract_tables(PDF, MODEL, cache_dir=CACHE / "stopped", max_cost=0.000001)
    assert stopped.value.reason in ("estimate", "unpriced")
    assert not (Path.cwd() / ".quotable" / "cost").exists()  # no request was made

    extract_tables(PDF, MODEL, cache_dir=CACHE / "run", max_cost=5)
    err = capsys.readouterr().err
    print(err)
    total = Decimal(re.findall(r"total cost \$([\d,.]+)", err)[-1].replace(",", ""))
    assert round(total, 2) == round(logged_total(), 2)
    estimates = re.findall(r"estimated cost \$([\d,.]+)|about \$([\d,.]+)", err)
    print("estimates found in the messages:", estimates, "actual total:", total)
