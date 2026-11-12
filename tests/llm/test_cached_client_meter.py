"""CachedClient with a run meter (spec 017): the stop, the cache and the keys."""

import asyncio
from decimal import Decimal

import pytest
from pydantic import BaseModel

from quotable.errors import BudgetExceededError, CostLimitExceededError
from quotable.llm.client import CachedClient, Request, request_key
from quotable.meter import RunMeter
from tests.conftest import FakeClient, PricedClient

D = Decimal
HALF = D("0.5")


class Answer(BaseModel):
    text: str


def ask(text: str, stage: str = "extract") -> Request:
    return Request(stage, "instructions", Answer, [text])


def build(tmp_path, limit=None, cost=HALF, max_requests=None):
    meter = RunMeter(limit)
    inner = FakeClient(lambda r: Answer(text=str(r.parts[0])))
    priced = PricedClient(inner, meter, cost)
    return CachedClient(priced, tmp_path, max_requests, meter), meter, inner


def test_the_request_keys_do_not_depend_on_the_meter():
    # three keys pinned: the meter must never reach a prompt or a key (FR-010)
    keys = [request_key("fake", ask(t)) for t in ("a", "b", "c")]
    assert len(set(keys)) == 3
    assert all(len(k) == 64 for k in keys)
    assert keys[0] == request_key("fake", ask("a"))


def test_after_the_meter_trips_no_request_starts_and_cache_hits_stop_too(tmp_path):
    client, meter, inner = build(tmp_path, limit=D("0.4"))
    asyncio.run(client.inner.inner.ask(ask("warm")))  # not cached: just to have a request
    with pytest.raises(CostLimitExceededError):
        asyncio.run(client.ask(ask("one")))  # costs 0.5 > 0.4
    before = len(inner.requests)
    with pytest.raises(CostLimitExceededError):
        asyncio.run(client.ask(ask("two")))
    with pytest.raises(CostLimitExceededError):
        asyncio.run(client.ask(ask("one")))  # cached, but the run is over
    assert len(inner.requests) == before


def test_the_answer_that_crossed_the_limit_is_cached(tmp_path):
    client, meter, inner = build(tmp_path, limit=D("0.4"))
    with pytest.raises(CostLimitExceededError):
        asyncio.run(client.ask(ask("crossing")))
    fresh, _, fresh_inner = build(tmp_path)  # a rerun with no limit
    answer = asyncio.run(fresh.ask(ask("crossing")))
    assert answer.text == "crossing"
    assert fresh_inner.requests == []


def test_max_requests_still_raises_its_own_error(tmp_path):
    client, _, _ = build(tmp_path, limit=D("100"), max_requests=1)
    asyncio.run(client.ask(ask("a")))
    with pytest.raises(BudgetExceededError) as caught:
        asyncio.run(client.ask(ask("b")))
    assert not isinstance(caught.value, CostLimitExceededError)


def test_peek_returns_the_cached_answer_or_none_and_writes_nothing(tmp_path):
    client, _, _ = build(tmp_path)
    assert client.peek(ask("a")) is None
    asyncio.run(client.ask(ask("a")))
    files = sorted(p.name for p in tmp_path.iterdir())
    assert client.peek(ask("a")).text == "a"
    assert client.peek(ask("zzz")) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == files


def test_hits_and_paid_requests_are_counted_and_tick_the_stage(tmp_path):
    client, meter, _ = build(tmp_path)
    meter.stage("extract", 2)
    asyncio.run(client.ask(ask("a")))
    asyncio.run(client.ask(ask("a")))
    assert meter.tally("extract").requests == 1
    assert meter.tally("extract").cache_hits == 1
    assert meter.progress["extract"].done == 2


def test_requests_in_flight_when_the_limit_is_crossed_finish_and_are_counted(tmp_path):
    client, meter, inner = build(tmp_path, limit=D("0.9"), cost=D("0.5"))

    async def scenario():
        return await asyncio.gather(
            *(client.ask(ask(str(i))) for i in range(4)), return_exceptions=True
        )

    results = asyncio.run(scenario())
    assert all(isinstance(r, CostLimitExceededError) or hasattr(r, "text") for r in results)
    assert meter.total == D("2.0")  # all four were in flight, all four are billed
    assert len(inner.requests) == 4
