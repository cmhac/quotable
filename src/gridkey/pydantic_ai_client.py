"""
A client backed by pydantic-ai (``pip install gridkey[openai]``).

``model`` is anything pydantic-ai accepts: a ``"provider:model-name"`` string (the
provider's API key is read from the environment as usual) or a model instance.
The import is deferred so the rest of the package does not need pydantic-ai.
"""

import json
from typing import Any

from gridkey.llm import Image, Request


class PydanticAIClient:
    """Send requests to a vision model through pydantic-ai."""

    def __init__(
        self,
        model: Any,  # noqa: ANN401
        *,
        identity: str | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> None:
        """Use ``model``; ``identity`` (default: model name + settings) keys the request cache."""
        self.model = model
        self.model_settings: Any = model_settings or {}
        name = identity or (model if isinstance(model, str) else type(model).__name__)
        self.identity = f"{name}:{json.dumps(self.model_settings, sort_keys=True)}"

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Run the request and return an instance of ``request.output_type``."""
        from pydantic_ai import Agent, BinaryContent  # noqa: PLC0415

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
