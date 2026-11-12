"""Choosing the sample run's pages, and the estimate for the rest of the run (spec 017)."""

from decimal import Decimal
from types import SimpleNamespace

from pydantic import BaseModel

from quotable.estimate import estimate_rest
from quotable.llm.client import Request
from quotable.meter import RunMeter
from quotable.pipeline import SAMPLE_PAGES, choose_sample

D = Decimal


def jobs(count: int, tables: int = 1) -> list[tuple[int, int]]:
    per = count // tables
    return [(t, p) for t in range(tables) for p in range(1, per + 1)]


def test_a_small_table_is_not_sampled():
    for count in range(0, SAMPLE_PAGES + 1):
        assert choose_sample(jobs(count)) == []


def test_the_first_the_middle_and_the_last_table_page_are_chosen():
    assert choose_sample(jobs(9)) == [(0, 1), (0, 5), (0, 9)]  # positions 0, 4, 8
    assert choose_sample(jobs(180)) == [(0, 1), (0, 91), (0, 180)]  # round(89.5) is 90


def test_four_pages_give_three_different_ones():
    picked = choose_sample(jobs(4))
    assert len(set(picked)) == 3
    assert picked[0] == (0, 1) and picked[-1] == (0, 4)


def test_the_choice_is_the_same_every_time():
    assert choose_sample(jobs(50)) == choose_sample(jobs(50))


def test_with_two_tables_the_sample_can_hold_pages_of_both():
    picked = choose_sample(jobs(10, tables=2))  # table 0 pages 1-5, table 1 pages 1-5
    assert {table for table, _ in picked} == {0, 1}


# --- the estimate for the rest ------------------------------------------------------------------
def paid(meter: RunMeter, stage: str, cost: str, *, unpriced: bool = False) -> None:
    request = Request(stage, "", BaseModel, [])
    usage = SimpleNamespace(input_tokens=10, output_tokens=1)
    meter.add(request, usage, None if unpriced else D(cost))


def test_the_rest_is_the_sample_cost_a_page_times_the_pages_left_plus_the_audit_and_recheck_again():
    meter = RunMeter()
    meter.phase = "discovery"
    paid(meter, "schema", "0.5")
    meter.phase = "sample"
    for _ in range(3):  # three table pages: 0.30 extraction, 0.06 audit, 0.03 recheck each
        paid(meter, "extract", "0.30")
        paid(meter, "audit", "0.06")
        paid(meter, "recheck", "0.03")
    estimate = estimate_rest(meter, total_pages=30, sample_pages=3)
    per_page = D("0.39")
    assert estimate.cost is not None
    assert estimate.per_page == per_page
    assert estimate.cost == 27 * per_page + 3 * (D("0.09"))  # (T - N) c + N (c - e)
    assert estimate.expected_total == meter.total + estimate.cost
    assert meter.total == D("0.5") + 3 * per_page
    assert estimate.possibly_low is False
    assert estimate.by_stage is not None and estimate.by_stage["extract"] == D("0.30")
    assert estimate.sample_pages == 3 and estimate.pages == 27


def test_a_sample_served_from_the_cache_is_marked_as_possibly_low():
    meter = RunMeter()
    meter.phase = "sample"
    paid(meter, "extract", "0.30")
    meter.hit("k", "extract")
    meter.hit("k2", "audit")
    estimate = estimate_rest(meter, total_pages=10, sample_pages=3)
    assert estimate.possibly_low and estimate.cached == 2


def test_an_all_cached_sample_estimates_nothing_and_says_it_may_be_low():
    meter = RunMeter()
    meter.phase = "sample"
    meter.hit("k", "extract")
    estimate = estimate_rest(meter, total_pages=10, sample_pages=3)
    assert estimate.cost == D(0) and estimate.possibly_low


def test_a_sample_with_an_unpriced_request_has_no_figure():
    meter = RunMeter()
    meter.phase = "sample"
    paid(meter, "extract", "0", unpriced=True)
    estimate = estimate_rest(meter, total_pages=10, sample_pages=3)
    assert estimate.cost is None and estimate.expected_total is None
    assert estimate.unavailable
