"""Page images: the detail value on `Image`, and how it keys the cache (spec 014)."""

import asyncio
from pathlib import Path
from typing import Any, cast

import pymupdf
import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from quotable.errors import ExtractionError
from quotable.llm.answers import PageRows
from quotable.llm.client import Image, PydanticAIClient, Request, request_key
from quotable.llm.images import TODAY, ImagePolicy, check_page_sizes, policy_for

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


# --- the policy by provider --------------------------------------------------------------------
OPENAI = ImagePolicy(300, "original", 30_000, None)
ANTHROPIC = ImagePolicy(300, "high", None, 8_000)


def _echo(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={})])


@pytest.mark.parametrize(
    "model",
    [
        "openai:gpt-x",
        "openai-chat:gpt-x",
        "openai-responses:gpt-x",
        OpenAIChatModel("gpt-x", provider=OpenAIProvider(api_key="k")),
        OpenAIResponsesModel("gpt-x", provider=OpenAIProvider(api_key="k")),
    ],
)
def test_an_openai_model_gets_300_dpi_and_the_original_detail(model):
    assert policy_for(model, sharp=True) == OPENAI


@pytest.mark.parametrize(
    "model",
    ["anthropic:claude-x", AnthropicModel("claude-x", provider=AnthropicProvider(api_key="k"))],
)
def test_an_anthropic_model_gets_300_dpi_and_no_detail_of_its_own(model):
    assert policy_for(model, sharp=True) == ANTHROPIC


@pytest.mark.parametrize(
    "model",
    ["bedrock:anthropic.claude-x", "google-gla:gemini-x", "groq:x", FunctionModel(_echo)],
)
def test_any_other_provider_keeps_todays_image(model):
    assert policy_for(model, sharp=True) == TODAY


@pytest.mark.parametrize("model", ["openai:gpt-x", "anthropic:claude-x"])
def test_with_sharp_images_off_every_provider_keeps_todays_image(model):
    assert policy_for(model, sharp=False) == TODAY


# --- the size check ----------------------------------------------------------------------------
def _pdf(tmp_path: Path, inches: float) -> Path:
    path = tmp_path / "page.pdf"
    document = pymupdf.open()
    document.new_page(width=inches * 72, height=inches * 72)
    document.save(path)
    document.close()
    return path


def test_a_letter_page_passes_both_providers(tmp_path):
    path = tmp_path / "letter.pdf"
    document = pymupdf.open()
    document.new_page(width=612, height=792)
    document.save(path)
    document.close()
    check_page_sizes(path, OPENAI)
    check_page_sizes(path, ANTHROPIC)


def test_a_page_over_a_side_limit_stops_anthropic_and_a_page_over_the_patch_limit_stops_openai(
    tmp_path,
):
    big = _pdf(tmp_path, 40)  # 12,000 px a side, 140,625 patches
    for policy in (OPENAI, ANTHROPIC):
        with pytest.raises(ExtractionError) as stopped:
            check_page_sizes(big, policy)
        assert "page 1" in str(stopped.value) and "sharp_images=False" in str(stopped.value)
        assert "12000 x 12000" in str(stopped.value)


def test_the_two_limits_are_different_limits(tmp_path):
    middle = _pdf(tmp_path, 25)  # 7,500 px a side: inside 8,000, but 55,225 patches
    check_page_sizes(middle, ANTHROPIC)
    with pytest.raises(ExtractionError, match="patches"):
        check_page_sizes(middle, OPENAI)


def test_todays_policy_checks_nothing(tmp_path):
    check_page_sizes(_pdf(tmp_path, 40), TODAY)
