"""
How a page image is made for the stages that read cell text (spec 014).

``ImagePolicy`` says the resolution and detail value of the image sent with a page extraction, a
recheck and an audit request. ``TODAY`` is what quotable did before spec 014. ``policy_for`` picks
the policy from the model's provider, and ``check_page_sizes`` refuses a document whose pages
would be too large for the provider before any request is made.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pydantic_ai.models import Model

from quotable.errors import ExtractionError
from quotable.llm.client import model_name

PATCH_PX = 32  # OpenAI counts an image in patches of this many pixels a side
POINTS_PER_INCH = 72


@dataclass(frozen=True)
class ImagePolicy:
    """The resolution and detail of a page image, and the largest image the provider accepts."""

    dpi: int
    detail: str
    max_patches: int | None  # largest image in 32 px patches; None = no check
    max_side: int | None  # largest side in pixels; None = no check


TODAY = ImagePolicy(150, "high", None, None)

OPENAI_PROVIDERS = ("openai", "openai-chat", "openai-responses")  # pydantic-ai's prefixes
OPENAI = ImagePolicy(300, "original", 30_000, None)  # OpenAI rejects an image over 30,000 patches
ANTHROPIC = ImagePolicy(300, "high", None, 8_000)  # Anthropic has no detail value; 8,000 px a side


def policy_for(model: Model | str, *, sharp: bool) -> ImagePolicy:
    """
    Return the image policy for ``model``: sharp for OpenAI and Anthropic, else ``TODAY``.

    The provider is the text before the colon of ``provider:model-name`` (a ``Model`` instance
    gives the same through its ``system``). Only these two providers are known to take a 300-dpi
    page, and only OpenAI is documented to take the ``original`` detail value, which the other
    providers pydantic-ai passes it to may reject. A model reached through a gateway counts as any
    other provider.
    """
    if not sharp:
        return TODAY
    provider = model_name(model).partition(":")[0]
    if provider in OPENAI_PROVIDERS:
        return OPENAI
    if provider == "anthropic":
        return ANTHROPIC
    return TODAY


def check_page_sizes(pdf: Path, policy: ImagePolicy) -> None:
    """
    Raise ``ExtractionError`` for the first page whose image would be too large for the provider.

    The size is that of the page rendered at ``policy.dpi`` (rotation included), taken from the
    page rectangle, so nothing is rendered. A policy without a limit checks nothing.
    """
    if policy.max_patches is None and policy.max_side is None:
        return
    scale = policy.dpi / POINTS_PER_INCH
    with pymupdf.open(pdf) as document:
        for number, page in enumerate(document, 1):
            width, height = math.ceil(page.rect.width * scale), math.ceil(page.rect.height * scale)
            patches = math.ceil(width / PATCH_PX) * math.ceil(height / PATCH_PX)
            if policy.max_patches is not None and patches > policy.max_patches:
                limit = f"{patches} patches of {PATCH_PX} px, over {policy.max_patches}"
            elif policy.max_side is not None and max(width, height) > policy.max_side:
                limit = f"over {policy.max_side} px on a side"
            else:
                continue
            msg = (
                f"page {number}: its {policy.dpi}-dpi image would be {width} x {height} px "
                f"({limit}), more than the provider accepts. Pass sharp_images=False to send "
                f"{TODAY.dpi}-dpi images instead."
            )
            raise ExtractionError(msg)
