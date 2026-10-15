"""The pydantic-ai adapter, run against pydantic-ai's offline FunctionModel (no network)."""

import asyncio
from typing import Any, cast

import pytest
from pydantic import BaseModel

pytest.importorskip("pydantic_ai")

from pydantic_ai import BinaryContent  # noqa: E402
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from pdf_table_extract.llm import Image, Request  # noqa: E402
from pdf_table_extract.pydantic_ai_client import PydanticAIClient  # noqa: E402


class Answer(BaseModel):
    text: str


def test_the_request_reaches_the_model_and_its_answer_comes_back_typed():
    seen: list[tuple[list[ModelMessage], str | None]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append((messages, info.instructions))
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"text": "hi"})]
        )

    client = PydanticAIClient(FunctionModel(respond), identity="function-model")
    request = Request("extract", "be exact", Answer, ["columns", Image(b"png-bytes")], page=3)
    answer = asyncio.run(client.ask(request))

    assert answer == Answer(text="hi")
    (messages, instructions), *_ = seen
    assert instructions == "be exact"
    content = cast("list[Any]", getattr(messages[0].parts[0], "content"))  # noqa: B009
    assert content[0] == "columns"
    assert isinstance(content[1], BinaryContent)
    assert content[1].data == b"png-bytes" and content[1].media_type == "image/png"


def test_the_identity_names_the_model_and_its_settings():
    one = PydanticAIClient("openai:some-model", model_settings={"temperature": 0})
    other = PydanticAIClient("openai:some-model", model_settings={"temperature": 1})
    assert one.identity != other.identity
    assert "openai:some-model" in one.identity
