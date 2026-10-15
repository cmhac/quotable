"""The pydantic-ai adapter, run against pydantic-ai's offline FunctionModel (no network)."""

import asyncio
from typing import Any, cast

from pydantic import BaseModel
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from gridkey._model import PydanticAIClient
from gridkey.llm import Image, Request


class Answer(BaseModel):
    text: str


def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"text": "hi"})]
    )


def test_the_request_reaches_the_model_and_its_answer_comes_back_typed():
    seen: list[tuple[list[ModelMessage], str | None]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append((messages, info.instructions))
        return _respond(messages, info)

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


def test_a_string_model_keeps_the_identity_format_of_the_cache_keys():
    assert PydanticAIClient("openai:some-model").identity == "openai:some-model:{}"


def test_two_model_instances_with_different_names_have_different_identities():
    one = PydanticAIClient(FunctionModel(_respond, model_name="model-a"))
    other = PydanticAIClient(FunctionModel(_respond, model_name="model-b"))
    assert one.identity != other.identity
    assert "model-a" in one.identity
