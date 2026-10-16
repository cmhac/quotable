"""
The extra-field requests of the live tests (spec 010), and the check that keeps them unbiased.

A live test measures what a real model reads from a page's header. If the caller's field names
or descriptions printed any word of that header ("division", "funding year"), the model would
be handed the answer, and the measurement would say nothing about documents it has not seen. So
the live tests describe each field only by where it sits (``neutral_request``): line k of the
block printed at the top left of the page. ``overlap`` is the check that no word of the
header (its labels, values and captions) appears in what the caller supplies, or in the
library's own extra-fields instructions; ``tests/test_extra_fields_live_prompts.py`` runs it
offline over the whole fixture and the Senate sample, so a description that leaks fails
``just test`` before any money is spent.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pymupdf

from quotable.extra_fields import ExtraField, ExtraFields, FieldGroup, extras_prompt
from quotable.text import tokenize

# Function words that no header is expected to be about; everything else must not overlap.
STOPWORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "from", "if", "in", "is", "it", "its", "of", "on", "or"}
    | {"the", "to", "with"}
)
SENATE_HEADER_BOX = (0.0, 0.0, 215.0, 112.0)  # top left of the sample's page 1 (pt)


DEFAULT_LIVE_RUNS = 3


def live_runs(value: str | None) -> tuple[int, ...]:
    """
    Return the run numbers of a live case from ``QUOTABLE_LIVE_RUNS`` (unset or blank: three).

    One run is the cheap first look; the default of three is what shows run-to-run flakiness.
    """
    text = (value or "").strip()
    if not text:
        return tuple(range(1, DEFAULT_LIVE_RUNS + 1))
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        raise ValueError(f"QUOTABLE_LIVE_RUNS must be a positive whole number, not {value!r}")
    return tuple(range(1, int(text) + 1))


def field_description(line: int) -> str:
    """Describe a field by its position only: no word of any header may appear here."""
    return (
        f"The text on line {line} of the block of lines printed at the top left of the page, "
        "above the tables. If the line starts with a label followed by a value, give only the "
        "value."
    )


def neutral_fields(count: int) -> list[ExtraField]:
    """Return ``count`` position-only fields, ``heading_1`` to ``heading_<count>``."""
    return [ExtraField(f"heading_{k}", field_description(k)) for k in range(1, count + 1)]


def neutral_request(truth: dict[str, Any], *, carry: bool) -> ExtraFields:
    """
    Return the request for a fixture document's truth, with positional names and descriptions.

    The k-th field of the truth is the k-th line of its block; a group of the truth is a group
    here, described by position only.
    """
    names = [f["name"] for f in truth["fields"]]
    neutral = dict(zip(names, neutral_fields(len(names)), strict=True))
    items: list[ExtraField | FieldGroup] = []
    placed: set[str] = set()
    for f in truth["fields"]:
        group = f["group"]
        if group is None:
            items.append(neutral[f["name"]])
        elif group not in placed:
            placed.add(group)
            members = [neutral[g["name"]] for g in truth["fields"] if g["group"] == group]
            label = f"group_{len(placed)}"
            text = "Lines of the block at the top left of the page that are printed together."
            items.append(FieldGroup(label, text, members))
    return ExtraFields(items, carry_forward=carry)


def caller_text(request: ExtraFields) -> str:
    """Return everything the caller supplies in a request: names, descriptions, prompt."""
    parts = [request.prompt]
    for item in request.fields:
        fields = item.fields if isinstance(item, FieldGroup) else [item]
        if isinstance(item, FieldGroup):
            parts += [item.name, item.description]
        for field in fields:
            parts += [field.name, field.description]
    return "\n".join(parts)


def words_in_box(pdf: Path, page: int, box: Iterable[float], margin: float = 2.0) -> set[str]:
    """Return the tokens of the text-layer words centred in the box (grown by ``margin``)."""
    x0, y0, x1, y1 = box
    with pymupdf.open(pdf) as document:
        words = document[page - 1].get_text("words")
    tokens: set[str] = set()
    for wx0, wy0, wx1, wy1, text, *_ in words:
        cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        if x0 - margin <= cx <= x1 + margin and y0 - margin <= cy <= y1 + margin:
            tokens |= set(tokenize(text))
    return tokens


def header_words(pdf: Path, truth: dict[str, Any]) -> set[str]:
    """Return every word printed in a fixture document's blocks: labels, values and captions."""
    tokens: set[str] = set()
    for page, box in truth["block_boxes"].items():
        tokens |= words_in_box(pdf, int(page), box)
    return tokens


def overlap(header: set[str], request: ExtraFields, *, library: bool = True) -> set[str]:
    """
    Return the words of the header that the request would hand to the model.

    Checks what the caller supplies and, with ``library``, the library's own extra-fields
    instructions. Function words (``STOPWORDS``) are ignored.
    """
    text = caller_text(request) + ("\n" + extras_prompt(request) if library else "")
    return (header - STOPWORDS) & set(tokenize(text))
