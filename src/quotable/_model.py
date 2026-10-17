"""
The model client: sends requests to a vision model through pydantic-ai.

``model`` is anything pydantic-ai accepts: a ``"provider:model-name"`` string (the
provider's API key is read from the environment as usual) or a pydantic-ai ``Model``
instance, which is how a custom provider is plugged in.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from quotable.llm import Image, Request


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
