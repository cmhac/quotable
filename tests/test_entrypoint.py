"""The public entrypoint, run end to end against pydantic-ai's offline FunctionModel."""

import asyncio

import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import quotable
from quotable import BudgetExceededError, extract_tables, extract_tables_async
from quotable.extract import run_pipeline
from tests.conftest import load_sample, one_table, replay

SAMPLE = load_sample("fy22_milcon_house_original")  # one page
PDF = SAMPLE["pdf"]


class Calls:
    """A FunctionModel that answers discovery and extract requests with the sample's rows."""

    def __init__(self) -> None:
        self.count = 0

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.count += 1
        tool = info.output_tools[0]
        properties = tool.parameters_json_schema["properties"]
        if "rows" in properties:
            args = {"rows": SAMPLE["pages"][1]}
        else:  # discovery: the same table on each page image in the request
            prompt = next(p for p in messages[0].parts if isinstance(p, UserPromptPart))
            images = sum(isinstance(c, BinaryContent) for c in prompt.content)
            page = one_table(SAMPLE["columns"]).model_dump()
            args = {"pages": [page] * images}
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])

    def model(self) -> FunctionModel:
        return FunctionModel(self.respond, model_name="entrypoint-test")


def test_a_model_is_required_and_no_environment_variable_supplies_it(monkeypatch):
    for name in ("QUOTABLE_MODEL", "QUOTABLE_LIVE_TEST_MODEL", "OPENAI_MODEL", "MODEL"):
        monkeypatch.setenv(name, "openai:some-model")
    with pytest.raises(TypeError, match="model"):
        extract_tables(PDF)  # ty: ignore[missing-argument]


def test_the_public_function_runs_the_pipeline_with_a_pydantic_ai_model():
    calls = Calls()
    (table,) = extract_tables(PDF, calls.model(), recheck=False)
    assert table.columns == SAMPLE["columns"]
    assert [r.values for r in table.page_rows(1)] == SAMPLE["pages"][1]
    assert calls.count == 2  # discovery, then the one page

    # the same result as the internal function with the recorded-rows fake
    (expected,) = asyncio.run(
        run_pipeline(PDF, replay(SAMPLE["columns"], SAMPLE["pages"]), recheck=False)
    )
    assert [r.values for r in table.rows()] == [r.values for r in expected.rows()]


def test_the_pdf_can_be_a_string_and_the_async_twin_works():
    calls = Calls()
    (table,) = asyncio.run(extract_tables_async(str(PDF), calls.model(), recheck=False))
    assert table.columns == SAMPLE["columns"]


@pytest.mark.parametrize("explicit", [False, True])
def test_a_second_run_makes_no_model_request_with_or_without_a_cache_dir(tmp_path, explicit):
    cache = str(tmp_path / "cache") if explicit else None
    first = Calls()
    extract_tables(PDF, first.model(), cache_dir=cache, recheck=False)
    second = Calls()
    extract_tables(PDF, second.model(), cache_dir=cache, recheck=False)
    assert first.count == 2
    assert second.count == 0


@pytest.mark.parametrize("explicit", [False, True])
def test_max_requests_caps_new_requests_with_the_default_or_an_explicit_directory(
    tmp_path, explicit
):
    calls = Calls()
    cache = tmp_path / "cache" if explicit else None
    with pytest.raises(BudgetExceededError):
        extract_tables(PDF, calls.model(), cache_dir=cache, max_requests=1, recheck=False)
    assert calls.count == 1


def test_the_public_names_are_the_entrypoint_and_its_results():
    assert sorted(quotable.__all__) == sorted(
        [
            "BudgetExceededError",
            "ExtraField",
            "ExtraFields",
            "ExtractionError",
            "FieldGroup",
            "Flag",
            "MergeEvidence",
            "MergedPart",
            "OcrConfig",
            "OcrUnavailableError",
            "Row",
            "Table",
            "TextLayerError",
            "extract_tables",
            "extract_tables_async",
        ]
    )
    for removed in ("CachedClient", "LLMClient", "Request", "Image", "PydanticAIClient"):
        assert not hasattr(quotable, removed)
