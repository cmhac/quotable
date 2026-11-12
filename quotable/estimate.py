"""
Cost estimates made before the money is spent (spec 017).

Two estimates: one for discovery, worked out before the first request from the page sizes and the
model's published image-token rule; and one for the rest of the run, worked out from what the
sample run measured. Neither changes a request, a prompt or a cache key.

The image-token rules are a table, because they differ by provider and model and change between
model generations (see ``specs/017-cost-estimate-progress/research.md``, section 2). A model that
is not in the table gets no estimate; it is never guessed. Adding a model is adding a row and a
test that pins the provider's documented example.
"""

import contextlib
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from quotable.errors import ExtractionError
from quotable.llm.client import Request
from quotable.steps.discover import CARRY_PROMPT, DISCOVER_PROMPT, discover
from quotable.steps.extra_fields import ExtraFields, extras_prompt

if TYPE_CHECKING:
    from quotable.meter import CostModel, RunMeter

DISCOVERY_DPI = 150  # discovery sends every page at this resolution, detail "high"
# shortcut: guesses, not measurements. The answer to a window is a few hundred tokens a page and
# "known tables" grows with the document; replace with measured values once live runs show them.
DISCOVERY_OUTPUT_PER_PAGE = 300
KNOWN_TABLES_ALLOWANCE = 200
POINTS_PER_INCH = 72

ImageRule = Callable[[int, int, str], int | None]


def text_tokens(text: str) -> int:
    """
    Guess the tokens of ``text``.

    shortcut: four characters a token, a rule of thumb for English; use the provider's tokenizer
    if estimates prove low.
    """
    return max(1, len(text) // 4)


# --- image-token rules ------------------------------------------------------------------------
@dataclass(frozen=True)
class Limits:
    """How an OpenAI patch model resizes an image at one detail level."""

    box: int  # the longest side, in pixels, the image is fitted into
    budget: int | None  # patches, when the model has a patch budget at this detail level


@dataclass(frozen=True)
class PatchModel:
    """An OpenAI model that counts 32 px patches; ``None`` for a detail level it does not take."""

    multiplier: Decimal
    low: Limits | None
    high: Limits | None
    original: Limits | None


OPENAI_PATCH_SIZE = 32
_AUTO = {"high": "high", "auto": "high"}  # `auto` sizes like `high` for these models
_ORIGINAL = Limits(65_535, None)
# Read 2026-11-12 from https://developers.openai.com/api/docs/guides/images-vision
_P12 = Decimal("1.2")
OPENAI_PATCH_MODELS: dict[str, PatchModel] = {
    "gpt-6-astra": PatchModel(_P12, Limits(512, None), Limits(65_535, 2500), _ORIGINAL),
    **dict.fromkeys(
        ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        PatchModel(_P12, Limits(512, None), Limits(2048, 2500), _ORIGINAL),
    ),
    "gpt-5.5": PatchModel(_P12, Limits(512, None), Limits(2048, 2500), Limits(6000, 10_000)),
    **dict.fromkeys(
        ("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"),
        PatchModel(_P12, Limits(2048, 6144), Limits(2048, 2500), Limits(6000, 10_000)),
    ),
    "gpt-5.2": PatchModel(_P12, Limits(2048, 6144), Limits(2048, 6144), None),
    "gpt-4.1-mini": PatchModel(Decimal("1.62"), Limits(2048, 6144), Limits(2048, 6144), None),
}
# model -> (base tokens, tokens a 512 px tile)
OPENAI_TILE_MODELS = {"gpt-5.1": (70, 140), "gpt-4.1": (85, 170), "gpt-4o": (85, 170)}
OPENAI_PATCH_LIMIT = 30_000  # the API rejects an image above this many patches

# Read 2026-11-12 from https://platform.claude.com/docs/en/build-with-claude/vision
ANTHROPIC_PATCH = 28
ANTHROPIC_LONG_EDGE = 2576  # the high-resolution tier (Claude 4.7 and later)
ANTHROPIC_MAX_TOKENS = 4784


def _patches(width: int, height: int) -> int:
    return math.ceil(width / OPENAI_PATCH_SIZE) * math.ceil(height / OPENAI_PATCH_SIZE)


def openai_patch_tokens(model: PatchModel, width: int, height: int, detail: str) -> int | None:
    """Return the billable image tokens of an OpenAI patch model, or ``None`` for a bad detail."""
    limits = {"low": model.low, "high": model.high, "original": model.original}.get(
        _AUTO.get(detail, detail)
    )
    if limits is None:
        return None
    scale = min(1.0, limits.box / width, limits.box / height)
    width, height = round(width * scale), round(height * scale)
    patches = _patches(width, height)
    if limits.budget is not None and patches > limits.budget:
        shrink = math.sqrt(OPENAI_PATCH_SIZE**2 * limits.budget / (width * height))
        fit = min(
            math.floor(width * shrink / OPENAI_PATCH_SIZE) / (width * shrink / OPENAI_PATCH_SIZE),
            math.floor(height * shrink / OPENAI_PATCH_SIZE) / (height * shrink / OPENAI_PATCH_SIZE),
        )
        shrink *= fit
        patches = _patches(math.floor(width * shrink), math.floor(height * shrink))
    if patches > OPENAI_PATCH_LIMIT:
        return None  # the API would reject the image; check_page_sizes says so before a request
    return math.ceil(Decimal(patches) * model.multiplier)


def openai_tile_tokens(base: int, tile: int, width: int, height: int, detail: str) -> int:
    """Return the billable image tokens of an OpenAI tile model."""
    if detail == "low":
        return base
    scale = min(1.0, 2048 / width, 2048 / height)
    wide, high = width * scale, height * scale
    if min(wide, high) > 768:  # noqa: PLR2004
        scale = 768 / min(wide, high)
        wide, high = wide * scale, high * scale
    return base + tile * math.ceil(wide / 512) * math.ceil(high / 512)


def anthropic_tokens(width: int, height: int) -> int:
    """
    Return an upper bound of the visual tokens of an Anthropic image.

    The high-resolution tier is used for every model, because the model name alone does not tell
    the tier. Older models cap lower, so this can only overestimate.
    """
    scale = min(1.0, ANTHROPIC_LONG_EDGE / max(width, height))
    width, height = math.floor(width * scale), math.floor(height * scale)
    tokens = math.ceil(width / ANTHROPIC_PATCH) * math.ceil(height / ANTHROPIC_PATCH)
    return min(tokens, ANTHROPIC_MAX_TOKENS)


def image_rule(provider: str, model: str) -> tuple[ImageRule, str]:
    """
    Return the image-token rule of ``provider``'s ``model`` and a sentence that names it.

    A model with no rule gets one that returns ``None`` and an empty sentence.
    """
    name = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model.lower())
    if provider == "openai":
        if name in OPENAI_PATCH_MODELS:
            patch = OPENAI_PATCH_MODELS[name]
            return (
                lambda w, h, detail: openai_patch_tokens(patch, w, h, detail),
                f"OpenAI patch rule, {patch.multiplier} tokens a patch, for {name}",
            )
        if name in OPENAI_TILE_MODELS:
            base, tile = OPENAI_TILE_MODELS[name]
            return (
                lambda w, h, detail: openai_tile_tokens(base, tile, w, h, detail),
                f"OpenAI tile rule, {base} base and {tile} a tile, for {name}",
            )
    if provider == "anthropic":
        return (
            lambda w, h, _detail: anthropic_tokens(w, h),
            "Anthropic patch rule, 28 px squares, an upper bound",
        )
    return (lambda _w, _h, _detail: None), ""


# --- estimates --------------------------------------------------------------------------------
@dataclass
class Estimate:
    """A cost figure with what it is based on; ``cost`` is ``None`` when it cannot be worked out."""

    label: str  # "discovery" or "rest"
    requests: int
    cached: int  # requests left out because their answers are in the cache
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None
    basis: str
    unavailable: str | None = None
    per_page: Decimal | None = None  # "rest": the sample's measured cost per table page
    expected_total: Decimal | None = None  # "rest": spent so far plus the rest
    possibly_low: bool = False  # "rest": part of the sample came from the cache
    pages: int = 0
    sample_pages: int = 0  # "rest": the table pages of the sample
    by_stage: dict[str, Decimal] | None = None  # "rest": the sample's cost a page, by stage


class NotCached(Exception):
    """A request the cache probe could not answer."""


class CacheProbe:
    """An ``LLMClient`` that answers only from the cache; used to find the cached windows."""

    identity = "probe"

    def __init__(self, peek: Callable[[Request], Any], identity: str = "probe") -> None:
        """Answer from ``peek`` (``CachedClient.peek``)."""
        self.peek = peek
        self.identity = identity
        self.answered = 0

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Return the cached answer or raise ``NotCached``."""
        answer = self.peek(request)
        if answer is None:
            raise NotCached
        self.answered += 1
        return answer


async def cached_discovery_requests(
    images: list[bytes],
    peek: Callable[[Request], Any],
    *,
    discovery_pages: int,
    extra_fields: ExtraFields | None,
) -> int:
    """
    Return how many discovery requests are in the cache, in order from the first window.

    The real ``discover`` runs against a probe that answers only from the cache and stops at the
    first miss, so how a window depends on the ones before it is exactly what a run does.
    """
    probe = CacheProbe(peek)
    with contextlib.suppress(NotCached, ExtractionError):
        await discover(images, probe, discovery_pages=discovery_pages, extra_fields=extra_fields)
    return probe.answered


def estimate_discovery(  # noqa: PLR0913
    page_sizes: Sequence[tuple[float, float]],
    cost_model: "CostModel",
    *,
    discovery_pages: int,
    extra_fields: ExtraFields | None = None,
    cached: int = 0,
) -> Estimate:
    """
    Estimate what discovery will cost, from the page sizes (in points) and the model's rules.

    ``cached`` is the number of discovery requests whose answers are already in the cache: they
    are left out. Pages are taken at the resolution and image detail discovery sends.
    """
    pages = len(page_sizes)
    windows = [page_sizes[i : i + discovery_pages] for i in range(0, pages, discovery_pages)]
    left = windows[min(cached, len(windows)) :]
    prompt = DISCOVER_PROMPT + (f"\n\n{extras_prompt(extra_fields)}" if extra_fields else "")
    inputs = 0
    unknown_image = False
    for index, window in enumerate(left, len(windows) - len(left)):
        text = prompt + (CARRY_PROMPT if index else "")
        inputs += text_tokens(text) + (KNOWN_TABLES_ALLOWANCE if index else 0)
        for width, height in window:
            px = (
                math.ceil(width * DISCOVERY_DPI / POINTS_PER_INCH),
                math.ceil(height * DISCOVERY_DPI / POINTS_PER_INCH),
            )
            tokens = cost_model.image_tokens(*px, "high")
            if tokens is None:
                unknown_image = True
            else:
                inputs += tokens
    outputs = DISCOVERY_OUTPUT_PER_PAGE * sum(len(w) for w in left)
    basis = (
        f"page images at {DISCOVERY_DPI} dpi ({cost_model.image_basis or 'no rule known'}), "
        f"the instructions, and an allowance of {DISCOVERY_OUTPUT_PER_PAGE} output tokens a page"
    )
    price = None if unknown_image else (cost_model.price(inputs, outputs) if left else Decimal(0))
    if unknown_image:
        why = f'no image-size rule is known for "{cost_model.name}"'
    elif price is None:
        why = f'no price is known for "{cost_model.name}"'
    else:
        why = None
    return Estimate(
        label="discovery",
        requests=len(left),
        cached=min(cached, len(windows)),
        input_tokens=None if unknown_image else inputs,
        output_tokens=None if unknown_image else outputs,
        cost=price,
        basis=basis,
        unavailable=why,
        pages=pages,
    )


def estimate_rest(meter: "RunMeter", total_pages: int, sample_pages: int) -> Estimate:
    """
    Estimate the rest of the run from what the sample measured.

    Per table page the sample cost ``c``, of which ``e`` was extraction. The rest is
    ``(T - N) * c + N * (c - e)``: the sample pages' audit and recheck are counted again, because
    those requests depend on the whole table and may not be reused. It errs high, the safe side
    for a limit. ``possibly_low`` is set when part of the sample came from the cache.
    """
    sample = {stage: t for (phase, stage), t in meter.tallies.items() if phase == "sample"}
    cost = sum((t.cost for t in sample.values()), Decimal(0))
    hits = sum(t.cache_hits for t in sample.values())
    requests = sum(t.requests for t in sample.values())
    by_stage = {stage: t.cost / sample_pages for stage, t in sample.items() if t.cost}
    per_page = cost / sample_pages
    extraction = by_stage.get("extract", Decimal(0))
    rest = (total_pages - sample_pages) * per_page + sample_pages * (per_page - extraction)
    unpriced = any(t.unpriced for t in sample.values())
    return Estimate(
        label="rest",
        requests=round(requests * (total_pages - sample_pages) / sample_pages),
        cached=hits,
        input_tokens=None,
        output_tokens=None,
        cost=None if unpriced else rest,
        basis="the sample's measured cost per table page, all stages",
        unavailable="the price is not known for some sample requests" if unpriced else None,
        per_page=None if unpriced else per_page,
        expected_total=None if unpriced else meter.total + rest,
        possibly_low=hits > 0,
        pages=total_pages - sample_pages,
        sample_pages=sample_pages,
        by_stage=by_stage,
    )
