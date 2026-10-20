"""
The model boundary: a request, a client protocol and a disk cache.

Everything that talks to a model goes through ``LLMClient.ask``; the pipeline never
imports a vendor SDK. Any object with an ``identity`` string and an async ``ask``
works, which is how the offline tests run the whole pipeline with a fake model. This
module is internal: users call ``quotable.extract_tables`` with a model.

``CachedClient`` wraps any client with a cap on new requests and an on-disk request cache
(always on, see :mod:`quotable.storage`). The key covers the client's identity, the
instructions, the output schema and every prompt part (text and image bytes), so a re-run
never pays twice for the same request.

Deliberately left out (see the original project): a dollar cost cap (``max_requests`` caps new
calls instead) and request concurrency limits. What each new request cost is recorded by the
client that makes it (see :mod:`quotable.storage`); the cache hands back answers for free and
records nothing.

``PydanticAIClient``, at the end, is the client that sends requests to a vision model through
pydantic-ai. ``model`` is anything pydantic-ai accepts: a ``"provider:model-name"`` string (the
provider's API key is read from the environment as usual) or a pydantic-ai ``Model``
instance, which is how a custom provider is plugged in.
"""

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from quotable.errors import BudgetExceededError
from quotable.storage import write_atomic


@dataclass(frozen=True)
class Image:
    """A PNG prompt part."""

    png: bytes


Part = str | Image


@dataclass
class Request:
    """One model request: everything that determines its answer."""

    stage: str  # "schema" | "extract" | "recheck"; for logs, not part of the key
    instructions: str
    output_type: type[BaseModel]
    parts: list[Part]
    page: int | None = None  # for logs and fakes, not part of the key


class LLMClient(Protocol):
    """What the pipeline needs from a model."""

    identity: str  # model name + settings; anything that changes the answers

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Return an instance of ``request.output_type``."""
        ...


def _fingerprint(part: Part) -> list[Any]:
    if isinstance(part, str):
        return ["text", part]
    return ["image", hashlib.sha256(part.png).hexdigest()]


def request_key(identity: str, request: Request) -> str:
    """Return the sha256 over everything that determines the model's answer."""
    blob = json.dumps(
        {
            "client": identity,
            "instructions": request.instructions,
            "output_schema": request.output_type.model_json_schema(),
            "parts": [_fingerprint(p) for p in request.parts],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class CachedClient:
    """Wrap a client with a disk cache and a cap on new requests."""

    def __init__(self, inner: LLMClient, cache_dir: Path, max_requests: int | None = None) -> None:
        """
        Cache ``inner``'s answers in ``cache_dir`` (it must exist); cap new requests.

        At most ``max_requests`` requests reach ``inner``; the next raises ``BudgetExceededError``.
        """
        self.inner = inner
        self.identity = inner.identity
        self.cache_dir = cache_dir
        self.max_requests = max_requests
        self.new_requests = 0

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Return the cached answer, or ask the wrapped client and cache it."""
        path = self.cache_dir / f"{request_key(self.identity, request)}.json"
        if path.exists():
            try:
                return request.output_type.model_validate(json.loads(path.read_text("utf-8")))
            except (ValueError, ValidationError) as err:
                print(f"ignoring unusable cache file {path.name}: {err}", file=sys.stderr)
        if self.max_requests is not None and self.new_requests >= self.max_requests:
            msg = f"{self.new_requests} new requests made, cap is {self.max_requests}"
            raise BudgetExceededError(msg)
        self.new_requests += 1
        answer = await self.inner.ask(request)
        write_atomic(path, answer.model_dump_json(indent=1))
        return answer


def model_name(model: Model | str) -> str:
    """Return the name that identifies ``model`` in the request cache key."""
    if isinstance(model, str):
        return model
    return f"{model.system}:{model.model_name}"


UsageCallback = Callable[[Request, str, RunUsage, Decimal | None], None]


def _price(result: AgentRunResult[Any]) -> Decimal | None:
    """Return what the request cost in US dollars, or ``None`` if its price is not known."""
    try:
        return result.response.cost().total_price
    except (LookupError, AssertionError):
        # genai-prices has no such provider or model, or pydantic-ai has no model name to look up
        return None


class PydanticAIClient:
    """Send requests to a vision model through pydantic-ai."""

    def __init__(
        self,
        model: Model | str,
        *,
        identity: str | None = None,
        model_settings: dict[str, Any] | None = None,
        on_usage: UsageCallback | None = None,
    ) -> None:
        """
        Use ``model``; ``identity`` (default: model name + settings) keys the request cache.

        ``on_usage(request, model, usage, cost)`` is called after each request that got an
        answer: ``model`` is the ``provider:model-name`` the cache key uses, ``usage`` the
        pydantic-ai ``RunUsage`` of the whole ask (retries included) and ``cost`` its price in
        dollars, ``None`` when unknown. It is not part of ``identity``.
        """
        self.model = model
        self.on_usage = on_usage
        self.model_settings: Any = model_settings or {}
        name = identity or model_name(model)
        self.identity = f"{name}:{json.dumps(self.model_settings, sort_keys=True)}"

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Run the request and return an instance of ``request.output_type``."""
        agent = Agent(
            self.model,
            output_type=request.output_type,
            instructions=request.instructions,
            model_settings=self.model_settings,
        )
        parts = [
            p
            if not isinstance(p, Image)
            else BinaryContent(
                data=p.png, media_type="image/png", vendor_metadata={"detail": "high"}
            )
            for p in request.parts
        ]
        result = await agent.run(parts)
        if self.on_usage is not None:
            self.on_usage(request, model_name(self.model), result.usage, _price(result))
        return result.output
