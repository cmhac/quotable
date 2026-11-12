"""Cost estimates (spec 017): the image rules and the discovery estimate."""

import asyncio
import contextlib
from decimal import Decimal

import pymupdf

from quotable.estimate import (
    DISCOVERY_OUTPUT_PER_PAGE,
    KNOWN_TABLES_ALLOWANCE,
    cached_discovery_requests,
    estimate_discovery,
    image_rule,
    text_tokens,
)
from quotable.llm.client import CachedClient
from quotable.meter import CostModel
from quotable.steps.discover import CARRY_PROMPT, DISCOVER_PROMPT, discover
from quotable.steps.extract import render_png
from tests.conftest import DATA, FakeClient, replay

D = Decimal


def tokens(provider: str, model: str, width: int, height: int, detail: str = "high"):
    rule, _ = image_rule(provider, model)
    return rule(width, height, detail)


# --- the image rules, pinned to the providers' documentation ------------------------------------
def test_openai_patch_rule_reproduces_the_documented_examples():
    assert tokens("openai", "gpt-6-astra", 1024, 1024) == 1229
    assert tokens("openai", "gpt-6-astra", 2048, 2048) == 3000  # the 2,500 patch budget shrinks it
    assert tokens("openai", "gpt-6-astra", 4096, 512) == 2458


def test_openai_original_detail_keeps_the_size():
    # a 300 dpi letter page: 2550 x 3300 is 80 x 104 patches
    assert tokens("openai", "gpt-5.6-luna", 2550, 3300, "original") == 9984  # ceil(8320 * 1.2)
    # high is capped at 2,500 patches
    assert tokens("openai", "gpt-5.6-luna", 2550, 3300, "high") <= 3000
    # gpt-5.5 caps original at 10,000 patches and 6000 px: 8,320 patches fit
    assert tokens("openai", "gpt-5.5", 2550, 3300, "original") == 9984


def test_a_detail_level_the_model_does_not_take_has_no_rule():
    assert tokens("openai", "gpt-5.2", 1000, 1000, "original") is None


def test_openai_tile_rule():
    # 1275 x 1650 fits 2048; the shortest side is cut to 768 (-> 768 x 994); 2 x 2 tiles
    assert tokens("openai", "gpt-4o", 1275, 1650) == 85 + 170 * 4
    assert tokens("openai", "gpt-4o", 1275, 1650, "low") == 85


def test_a_dated_name_matches_its_family_but_a_longer_family_name_does_not_match_a_shorter_one():
    assert tokens("openai", "gpt-5.5-2026-01-01", 1024, 1024) == tokens(
        "openai", "gpt-5.5", 1024, 1024
    )
    assert tokens("openai", "gpt-5", 1024, 1024) is None
    assert tokens("openai", "gpt-5.4-mini", 1024, 1024) == 1229


def test_models_without_a_rule_get_none():
    assert tokens("openai", "gpt-5-mini", 1024, 1024) is None  # deprecated, left out
    assert tokens("openai", "a-new-model", 1024, 1024) is None
    assert tokens("groq", "llama", 1024, 1024) is None
    assert image_rule("groq", "llama")[1] == ""


def test_anthropic_rule_is_the_high_resolution_tier_upper_bound():
    assert tokens("anthropic", "claude-x", 1000, 1000) == 1296
    assert tokens("anthropic", "claude-x", 1920, 1080) == 2691
    assert tokens("anthropic", "claude-x", 2000, 1500) == 3888
    assert tokens("anthropic", "claude-x", 3840, 2160) == 4784
    assert "upper bound" in image_rule("anthropic", "claude-x")[1]


def test_text_tokens_is_four_characters_a_token():
    assert text_tokens("a" * 400) == 100
    assert text_tokens("") == 1


# --- the discovery estimate ---------------------------------------------------------------------
def fake_model(price_per_token: str = "0.000001") -> CostModel:
    return CostModel(
        "fake:model",
        lambda i, o: D(i + o) * D(price_per_token),
        lambda w, h, detail: 1000,
        image_basis="a fixed 1000 tokens an image",
    )


LETTER = (612.0, 792.0)


def test_discovery_estimate_counts_windows_images_instructions_and_the_output_allowance():
    estimate = estimate_discovery([LETTER] * 6, fake_model(), discovery_pages=2)
    first = text_tokens(DISCOVER_PROMPT) + 2000
    later = text_tokens(DISCOVER_PROMPT + CARRY_PROMPT) + KNOWN_TABLES_ALLOWANCE + 2000
    assert estimate.requests == 3
    assert estimate.cached == 0
    assert estimate.input_tokens == first + 2 * later
    assert estimate.output_tokens == 6 * DISCOVERY_OUTPUT_PER_PAGE
    assert estimate.cost == D(estimate.input_tokens + estimate.output_tokens) * D("0.000001")
    assert estimate.unavailable is None
    assert "150 dpi" in estimate.basis and "1000 tokens an image" in estimate.basis


def test_cached_windows_are_left_out_of_the_estimate():
    full = estimate_discovery([LETTER] * 6, fake_model(), discovery_pages=2)
    rest = estimate_discovery([LETTER] * 6, fake_model(), discovery_pages=2, cached=2)
    assert (rest.requests, rest.cached) == (1, 2)
    assert rest.cost is not None and full.cost is not None and rest.cost < full.cost
    done = estimate_discovery([LETTER] * 6, fake_model(), discovery_pages=2, cached=3)
    assert (done.requests, done.cost) == (0, D(0))


def test_an_unknown_image_rule_gives_no_figure_and_says_why():
    model = CostModel("x:y", lambda i, o: D(1), image_basis="")
    estimate = estimate_discovery([LETTER] * 2, model, discovery_pages=2)
    assert estimate.cost is None and estimate.input_tokens is None
    assert estimate.requests == 1
    assert 'no image-size rule is known for "x:y"' in (estimate.unavailable or "")


def test_an_unknown_price_gives_tokens_and_no_dollars():
    model = CostModel("x:y", lambda i, o: None, lambda w, h, d: 1000)
    estimate = estimate_discovery([LETTER] * 2, model, discovery_pages=2)
    assert estimate.cost is None
    assert (estimate.input_tokens or 0) > 2000
    assert 'no price is known for "x:y"' in (estimate.unavailable or "")


def sample_images() -> list[bytes]:
    with pymupdf.open(DATA / "fy22_ag_house_original.pdf") as document:
        return [render_png(page) for page in document]


def cached_client(tmp_path, answer_first: int) -> CachedClient:
    """A client whose cache holds the answers to the first ``answer_first`` discovery requests."""
    handler = replay(["A", "B"], {}).handler
    count = [0]

    def limited(request):
        count[0] += 1
        if count[0] > answer_first:
            raise RuntimeError("stop")
        return handler(request)

    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    client = CachedClient(FakeClient(limited), cache)
    with contextlib.suppress(RuntimeError):
        asyncio.run(discover(sample_images(), client, discovery_pages=1))
    return client


def test_cached_windows_are_found_by_running_discovery_against_the_cache(tmp_path):
    client = cached_client(tmp_path, answer_first=2)
    files = sorted(p.name for p in (tmp_path / "cache").iterdir())
    found = asyncio.run(
        cached_discovery_requests(
            sample_images(), client.peek, discovery_pages=1, extra_fields=None
        )
    )
    assert found == 2
    assert (
        sorted(p.name for p in (tmp_path / "cache").iterdir()) == files
    )  # the probe wrote nothing


def test_nothing_cached_and_everything_cached(tmp_path):
    empty = CachedClient(FakeClient(lambda r: None), tmp_path)
    assert (
        asyncio.run(
            cached_discovery_requests(
                sample_images(), empty.peek, discovery_pages=1, extra_fields=None
            )
        )
        == 0
    )
    full = cached_client(tmp_path / "full", answer_first=4)
    assert (
        asyncio.run(
            cached_discovery_requests(
                sample_images(), full.peek, discovery_pages=1, extra_fields=None
            )
        )
        == 4
    )
