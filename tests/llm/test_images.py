"""Page images: the detail value on `Image`, and how it keys the cache (spec 014)."""

import asyncio
from typing import Any, cast

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from quotable.llm.answers import PageRows
from quotable.llm.client import Image, PydanticAIClient, Request, request_key

KEY_BEFORE_SPEC_014 = "d2c04ff8e6d5120c87f436b049908f68b3f79b0e385bad24376855b744201eb6"


def _request(image: Image) -> Request:
    return Request("extract", "x", PageRows, ["text", image])


def test_an_image_with_the_default_detail_keeps_the_key_it_had_before():
    assert request_key("fake", _request(Image(b"png-bytes"))) == KEY_BEFORE_SPEC_014
    assert request_key("fake", _request(Image(b"png-bytes", "high"))) == KEY_BEFORE_SPEC_014


def test_another_detail_is_part_of_the_key():
    original = request_key("fake", _request(Image(b"png-bytes", "original")))
    assert original != KEY_BEFORE_SPEC_014


def test_the_client_sends_the_detail_of_the_image():
    seen: list[ModelMessage] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.extend(messages)
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"rows": []})]
        )

    client = PydanticAIClient(FunctionModel(respond), identity="function-model")
    for detail in ("high", "original"):
        seen.clear()
        asyncio.run(client.ask(_request(Image(b"png-bytes", detail))))
        content = cast("list[Any]", getattr(seen[0].parts[0], "content"))  # noqa: B009
        image = next(c for c in content if isinstance(c, BinaryContent))
        assert image.vendor_metadata == {"detail": detail}
