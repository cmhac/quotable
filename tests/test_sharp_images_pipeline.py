"""Sharp page images inside the pipeline: which stage sends which image (spec 014)."""

import asyncio

import pymupdf
import pytest

import quotable.pipeline as pipeline_module
from quotable import ExtractionError, extract_tables
from quotable.llm.client import Image
from quotable.llm.images import TODAY, ImagePolicy
from quotable.pipeline import run_pipeline
from quotable.steps.extract import render_png
from tests.conftest import FakeClient
from tests.test_audit_pipeline import omitting_model
from tests.test_entrypoint import PDF

OPENAI = ImagePolicy(300, "original", 30_000, None)
ANTHROPIC = ImagePolicy(300, "high", None, 8_000)


def images_of(client: FakeClient) -> dict[str, Image]:
    """The page image each stage sent (the first request of the stage)."""
    seen: dict[str, Image] = {}
    for request in client.requests:
        image = next(p for p in request.parts if isinstance(p, Image))
        seen.setdefault(request.stage, image)
    return seen


def width(image: Image) -> int:
    return pymupdf.Pixmap(image.png).width


def run(client: FakeClient, policy: ImagePolicy) -> None:
    asyncio.run(run_pipeline(PDF, client, audit=True, images=policy))


def test_the_openai_policy_sharpens_extraction_audit_and_recheck_but_not_discovery():
    client = omitting_model(typo=True)
    run(client, OPENAI)
    sent = images_of(client)
    assert set(sent) == {"schema", "extract", "audit", "recheck"}
    assert (width(sent["schema"]), sent["schema"].detail) == (width(sent["extract"]) // 2, "high")
    for stage in ("extract", "audit", "recheck"):
        assert sent[stage].detail == "original", stage
        assert abs(width(sent[stage]) - 2 * width(sent["schema"])) <= 2, stage


def test_the_anthropic_policy_sharpens_the_same_stages_and_sends_no_new_detail():
    client = omitting_model(typo=True)
    run(client, ANTHROPIC)
    sent = images_of(client)
    for stage in ("extract", "audit", "recheck"):
        assert sent[stage].detail == "high", stage
        assert abs(width(sent[stage]) - 2 * width(sent["schema"])) <= 2, stage


def test_todays_policy_sends_the_150_dpi_image_everywhere():
    client = omitting_model(typo=True)
    run(client, TODAY)
    with pymupdf.open(PDF) as document:
        page = render_png(document[0])
    for stage, image in images_of(client).items():
        assert (image.png, image.detail) == (page, "high"), stage


def test_a_page_over_the_limit_stops_the_run_before_any_request():
    def refuse(request):
        raise AssertionError("a request was made")

    client = FakeClient(refuse)
    tiny = ImagePolicy(300, "original", 100, None)  # a Letter page at 300 dpi is 8,320 patches
    with pytest.raises(ExtractionError, match="page 1"):
        run(client, tiny)
    assert client.requests == []


# --- the public function picks the policy from the model ---------------------------------------
@pytest.fixture
def captured(monkeypatch) -> dict:
    """Stand in for `run_pipeline` and the run saving, and record what `extract_tables` passes."""
    seen: dict = {}

    async def fake_pipeline(pdf, client, **options):
        seen.update(options)
        return []

    monkeypatch.setattr(pipeline_module, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(pipeline_module, "_save_run", lambda *a, **k: seen.update(saved=k))
    return seen


@pytest.mark.parametrize(
    ("model", "policy"),
    [
        ("openai:gpt-x", OPENAI),
        ("anthropic:claude-x", ANTHROPIC),
        ("google-gla:gemini-x", TODAY),
    ],
)
def test_sharp_images_are_on_by_default_and_follow_the_provider(captured, model, policy):
    extract_tables(PDF, model)
    assert captured["images"] == policy
    assert captured["saved"]["sharp_images"] is True


@pytest.mark.parametrize("model", ["openai:gpt-x", "anthropic:claude-x"])
def test_sharp_images_false_gives_todays_image_and_is_recorded(captured, model):
    extract_tables(PDF, model, sharp_images=False)
    assert captured["images"] == TODAY
    assert captured["saved"]["sharp_images"] is False
