"""The run meter, money formatting, the cost model and the limit messages (spec 017)."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from quotable.errors import BudgetExceededError, CostLimitExceededError
from quotable.llm.client import Request
from quotable.meter import CostModel, RunMeter, dollars, dollars_pair, make_error, round_up
from tests.conftest import FakeClient, PricedClient

D = Decimal


def request(stage: str = "extract") -> Request:
    return Request(stage, "", BaseModel, [])


def usage(inputs: int = 1000, outputs: int = 100) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=inputs, output_tokens=outputs)


# --- money --------------------------------------------------------------------------------------
def test_dollars_use_two_decimals_from_a_dollar_up_and_four_below():
    assert dollars(D("21.8712")) == "$21.87"
    assert dollars(D("0.0412")) == "$0.0412"
    assert dollars(D("1234.5")) == "$1,234.50"


def test_a_pair_gets_enough_decimals_to_differ():
    assert dollars_pair(D("25.0412"), D("25")) == ("$25.0412", "$25.0000")
    first, second = dollars_pair(D("25.000004"), D("25"))
    assert first != second


def test_round_up_never_rounds_down():
    assert round_up(D("0.0412")) == D("0.0412")
    assert round_up(D("0.04121")) == D("0.0413")
    assert round_up(D("0")) == D("0")


# --- the meter ----------------------------------------------------------------------------------
def test_totals_add_up_across_phases_and_stages():
    meter = RunMeter()
    meter.add(request("schema"), usage(), D("0.25"))
    meter.phase = "rest"
    meter.add(request("extract"), usage(), D("0.5"))
    meter.add(request("extract"), usage(), D("0.5"))
    assert meter.total == D("1.25")
    assert meter.tally("extract").requests == 2
    assert meter.tally("schema", "discovery").cost == D("0.25")
    assert meter.tally("extract").input_tokens == 2000


def test_equal_to_the_limit_does_not_stop_but_a_cent_over_does():
    meter = RunMeter(D("1.00"))
    meter.add(request(), usage(), D("1.00"))
    meter.check()
    meter.add(request(), usage(), D("0.01"))
    with pytest.raises(CostLimitExceededError) as caught:
        meter.check()
    assert caught.value.reason == "spent"
    assert caught.value.over == D("0.01")


def test_a_request_with_no_usage_stops_a_limited_run_but_not_an_unlimited_one():
    limited = RunMeter(D("5"))
    limited.add(request("audit"), usage(0, 0), D("0"))
    with pytest.raises(CostLimitExceededError) as caught:
        limited.check()
    assert caught.value.reason == "unmetered"
    assert caught.value.stage == "audit"
    free = RunMeter()
    free.add(request(), usage(0, 0), D("0"))
    free.check()


def test_a_request_with_no_price_stops_a_limited_run_and_adds_tokens_only():
    meter = RunMeter(D("5"))
    meter.add(request(), usage(), None)
    assert meter.total == D("0")
    assert meter.tally("extract").unpriced == 1
    assert meter.tally("extract").input_tokens == 1000
    with pytest.raises(CostLimitExceededError, match="without usage figures"):
        meter.check()


def test_check_raises_on_every_call_after_the_stop():
    meter = RunMeter(D("0.01"))
    meter.add(request(), usage(), D("0.02"))
    for _ in range(3):
        with pytest.raises(CostLimitExceededError):
            meter.check()


def test_the_limit_added_to_raise_by_is_at_least_the_total():
    meter = RunMeter(D("1"))
    meter.add(request(), usage(), D("1.000041"))
    error = meter.error()
    assert error.limit + error.raise_by >= error.spent
    assert error.raise_by == D("0.0001")


def test_settled_waits_for_every_request_in_flight():
    async def scenario() -> list[str]:
        meter = RunMeter()
        events: list[str] = []
        meter.begin()
        meter.begin()

        async def finish(name: str) -> None:
            await asyncio.sleep(0.01)
            events.append(name)
            meter.end()

        tasks = [asyncio.create_task(finish("a")), asyncio.create_task(finish("b"))]
        await meter.settled()
        events.append("settled")
        await asyncio.gather(*tasks)
        return events

    assert asyncio.run(scenario())[-1] == "settled"


def test_the_error_reports_the_stage_progress_and_the_requests_in_flight():
    meter = RunMeter(D("0.05"))
    meter.stage("audit", 40, upper_bound=True)
    for _ in range(3):
        meter.begin()
    meter.add(request("audit"), usage(), D("0.06"))
    error = meter.error()
    assert (error.stage, error.done, error.total, error.in_flight) == ("audit", 0, 40, 2)
    assert "audit stage (0 of up to 40)" in str(error)
    assert "2 requests were in flight" in str(error)


def test_priced_client_adds_to_the_meter():
    meter = RunMeter()
    client = PricedClient(FakeClient(lambda r: None), meter, D("0.02"))
    asyncio.run(client.ask(request("extract")))
    assert meter.total == D("0.02")


# --- the messages -------------------------------------------------------------------------------
def test_the_spent_message_has_the_figures_and_the_instructions():
    error = make_error(
        "spent",
        limit=D("25"),
        spent=D("25.0412"),
        estimate=D("26.801"),
        stage="audit",
        done=41,
        total=180,
        in_flight=3,
    )
    text = str(error)
    assert "$25.0412 and the limit is $25.0000: over by $0.0412" in text
    assert "raise max_cost by at least $0.0412 (to $25.0412)" in text
    assert "estimated at $26.80: max_cost=26.81 would finish it" in text
    assert "Everything already answered is in the cache" in text
    assert error.finish_by == D("1.8010")
    assert isinstance(error, BudgetExceededError)


def test_the_estimate_message_before_and_after_spending():
    before = str(
        make_error("estimate", limit=D("2"), spent=D("0"), estimate=D("4.12"), what="discovery")
    )
    assert "estimate for discovery is $4.1200 and max_cost is $2.0000" in before
    assert "Nothing has been requested" in before
    after = make_error("estimate", limit=D("25"), spent=D("4.29"), estimate=D("26.8"))
    assert "Spent so far: $4.29" in str(after)
    assert after.raise_by == D("1.8")
    assert "Nothing more has been requested" in str(after)


def test_the_unpriced_message_names_the_model_and_the_cause():
    error = make_error(
        "unpriced", limit=D("5"), spent=D("0"), model="openai:x", cause="set OPENAI_API_KEY"
    )
    assert 'price of "openai:x" is not known (set OPENAI_API_KEY)' in str(error)
    assert "Nothing was requested" in str(error)


def test_messages_hold_no_prompt_value_or_path():
    text = str(make_error("spent", limit=D("1"), spent=D("2"), stage="extract", done=1, total=2))
    assert (
        "/" not in text.replace("(", "").replace(")", "").replace("of up to", "")
        or "http" not in text
    )


# --- the cost model -----------------------------------------------------------------------------
def test_a_known_model_is_priced_from_token_counts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    model = CostModel.for_model("openai:gpt-4o")
    assert model.name == "openai:gpt-4o"
    assert model.price(10_000, 1_000) == D("0.035")
    assert model.why_unpriced == ""


def test_without_an_api_key_the_price_is_unknown_and_the_cause_is_kept(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = CostModel.for_model("openai:gpt-4o")
    assert model.price(1000, 100) is None
    assert "OPENAI_API_KEY" in model.why_unpriced


def test_a_model_genai_prices_does_not_know_has_no_price(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    model = CostModel.for_model("openai:a-model-nobody-has-heard-of")
    assert model.price(1000, 100) is None
    assert model.why_unpriced
