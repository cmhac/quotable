"""
The model client: sends requests to a vision model through pydantic-ai.

``model`` is anything pydantic-ai accepts: a ``"provider:model-name"`` string (the
provider's API key is read from the environment as usual) or a pydantic-ai ``Model``
instance, which is how a custom provider is plugged in.
"""

import json
from typing import Any

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models import Model

from quotable.llm import Image, Request


def model_name(model: Model | str) -> str:
    """Return the name that identifies ``model`` in the request cache key."""
    if isinstance(model, str):
        return model
    return f"{model.system}:{model.model_name}"


class PydanticAIClient:
    """Send requests to a vision model through pydantic-ai."""

    def __init__(
        self,
        model: Model | str,
        *,
        identity: str | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> None:
        """Use ``model``; ``identity`` (default: model name + settings) keys the request cache."""
        self.model = model
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
        return result.output
