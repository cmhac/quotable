import asyncio

import pytest
from pydantic import BaseModel

from quotable.llm import (
    BudgetExceededError,
    CachedClient,
    Image,
    Part,
    Request,
    request_key,
)


class Answer(BaseModel):
    text: str


class Other(BaseModel):
    number: int


class CountingClient:
    identity = "fake-model"

    def __init__(self, text="hello"):
        self.calls = 0
        self.text = text

    async def ask(self, request):
        self.calls += 1
        return request.output_type(text=self.text)


def _request(
    *,
    instructions: str = "do it",
    output_type: type[BaseModel] = Answer,
    parts: list[Part] | None = None,
    page: int = 1,
) -> Request:
    default: list[Part] = ["columns", Image(b"png-bytes")]
    return Request("extract", instructions, output_type, parts or default, page)


def test_the_key_covers_everything_that_decides_the_answer():
    base = request_key("m", _request())
    assert base == request_key("m", _request())
    assert base != request_key("other-model", _request())
    assert base != request_key("m", _request(instructions="do it differently"))
    assert base != request_key("m", _request(output_type=Other))
    assert base != request_key("m", _request(parts=["columns", Image(b"other-bytes")]))
    assert base != request_key("m", _request(parts=["more columns", Image(b"png-bytes")]))


def test_the_key_ignores_what_does_not_decide_the_answer():
    assert request_key("m", _request(page=1)) == request_key("m", _request(page=7))


def test_an_identical_request_is_answered_from_the_cache(tmp_path):
    inner = CountingClient()
    client = CachedClient(inner, tmp_path)
    first = asyncio.run(client.ask(_request()))
    second = asyncio.run(client.ask(_request()))
    assert first == second == Answer(text="hello")
    assert inner.calls == 1


def test_the_cache_survives_a_new_client(tmp_path):
    asyncio.run(CachedClient(CountingClient(), tmp_path).ask(_request()))
    inner = CountingClient("changed")
    answer = asyncio.run(CachedClient(inner, tmp_path).ask(_request()))
    assert answer.text == "hello"
    assert inner.calls == 0


def test_an_unusable_cache_file_is_asked_again(tmp_path):
    inner = CountingClient()
    client = CachedClient(inner, tmp_path)
    asyncio.run(client.ask(_request()))
    (path,) = tmp_path.glob("*.json")
    path.write_text("{not json")
    asyncio.run(client.ask(_request()))
    assert inner.calls == 2


def test_new_requests_stop_at_the_cap_but_cached_ones_do_not_count(tmp_path):
    inner = CountingClient()
    client = CachedClient(inner, tmp_path, max_requests=2)
    asyncio.run(client.ask(_request(parts=["a"])))
    asyncio.run(client.ask(_request(parts=["b"])))
    asyncio.run(client.ask(_request(parts=["a"])))  # cached: free
    with pytest.raises(BudgetExceededError):
        asyncio.run(client.ask(_request(parts=["c"])))
    assert inner.calls == 2


def test_the_cap_counts_only_requests_that_miss_the_cache(tmp_path):
    inner = CountingClient()
    client = CachedClient(inner, tmp_path, max_requests=1)
    asyncio.run(client.ask(_request()))
    asyncio.run(client.ask(_request()))  # the same request again is served from the cache
    with pytest.raises(BudgetExceededError):
        asyncio.run(client.ask(_request(parts=["another"])))
    assert inner.calls == 1
