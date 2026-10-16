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

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf

from quotable.extra_fields import ExtraField, ExtraFields, FieldGroup, extras_prompt
from quotable.text import tokenize
from tests.extra_fields_model import request_for

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


def field_description(line: int, label: bool | None = None, span: int = 1) -> str:
    """
    Describe a field by its position only: no word of any header may appear here.

    ``label`` says whether the line starts with a label that is not part of the value: ``True``
    (leave it out), ``False`` (the value is the whole line), ``None`` (not known: the model is
    told to decide). A caller who wants the label in the value has to say so, as the real
    ``ExtraField`` docs advise. ``span`` is the number of lines the value is printed over.
    """
    where = (
        f"The text on line {line} of the block of lines printed at the top left of the page, "
        "above the tables. Count the lines from the first line below any title that is printed "
        "at the very top of every page; that title is not a line of the block. "
    )
    if span > 1:
        where += (
            f"The value is printed over {span} lines, lines {line} to {line + span - 1}: "
            "give all of them on one line, joined by single spaces. "
        )
    if label is True:
        return where + "The first line starts with a label: leave the label out of the value."
    if label is False:
        return where + (
            "The value starts at the first word of the line, even if that word looks like a "
            "label: keep every word."
        )
    return where + (
        "If the line starts with a label, leave the label out of the value; "
        "if the line has no label, give it whole."
    )


def neutral_fields(
    count: int,
    labels: Sequence[bool | None] | None = None,
    spans: Sequence[int] | None = None,
) -> list[ExtraField]:
    """Return ``count`` position-only fields, ``heading_1`` to ``heading_<count>``."""
    marks = list(labels) if labels is not None else [None] * count
    sizes = list(spans) if spans is not None else [1] * count
    fields: list[ExtraField] = []
    line = 1
    for k in range(count):
        fields.append(ExtraField(f"heading_{k + 1}", field_description(line, marks[k], sizes[k])))
        line += sizes[k]
    return fields


def value_lines(pdf: Path, truth: dict[str, Any]) -> list[tuple[bool, int]]:
    """
    Return, per field of the truth, (starts with a label, number of lines it is printed over).

    Read from the fixture, on the first page that prints the field. A line starts with a label
    when the leftmost word on the top line of the value's box is not the first word of the
    value. The number of lines is the number of distinct line tops inside the box (a value
    that wraps has a box over several lines; only its top line can start with a label).
    """
    page = min(int(p) for p in truth["boxes"])
    with pymupdf.open(pdf) as document:
        words = document[page - 1].get_text("words")
    facts: list[tuple[bool, int]] = []
    for field in truth["fields"]:
        name = field["name"]
        x0, y0, x1, y1 = truth["boxes"][str(page)][name]
        inside = [
            w
            for w in words
            if x0 - 60 <= (w[0] + w[2]) / 2 <= x1 + 2 and y0 - 2 <= (w[1] + w[3]) / 2 <= y1 + 2
        ]
        tops = sorted({round(w[1]) for w in inside})
        lines = 1 + sum(1 for a, b in zip(tops, tops[1:], strict=False) if b - a > 4)
        first = sorted(
            (w for w in inside if abs(w[1] - min(w[1] for w in inside)) < 2), key=lambda w: w[0]
        )
        first_word = truth["printed"][str(page)][name].split()[0]
        facts.append((first[0][4] != first_word, lines))
    return facts


def label_marks(pdf: Path, truth: dict[str, Any]) -> list[bool]:
    """Return, per field of the truth, whether its line starts with words not in the value."""
    return [label for label, _ in value_lines(pdf, truth)]


def neutral_request(truth: dict[str, Any], *, carry: bool, pdf: Path | None = None) -> ExtraFields:
    """
    Return the request for a fixture document's truth, with positional names and descriptions.

    The k-th field of the truth is the k-th line of its block; a group of the truth is a group
    here, described by position only. With ``pdf``, each description also says whether the
    line starts with a label to leave out (``label_marks``).
    """
    names = [f["name"] for f in truth["fields"]]
    facts = value_lines(pdf, truth) if pdf is not None else None
    marks = [label for label, _ in facts] if facts else None
    spans = [lines for _, lines in facts] if facts else None
    neutral = dict(zip(names, neutral_fields(len(names), marks, spans), strict=True))
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


def label_hint(label: bool, lines: int) -> str:
    """Return what a caller adds to a description about the label and the lines of a value."""
    text = (
        "Leave the label printed before the value out of it."
        if label
        else "The value is the whole line, from its first word: keep every word."
    )
    if lines > 1:
        text += (
            f" The value is printed over {lines} lines: give all of them on one line,"
            " joined by single spaces."
        )
    return text


def described_request(truth: dict[str, Any], pdf: Path, *, carry: bool) -> ExtraFields:
    """
    Return the request a caller would write for a fixture document: the truth's own names and
    descriptions (which name what each field is), plus a sentence about its label.
    """
    base = request_for(truth, carry=carry)
    facts = dict(zip((f["name"] for f in truth["fields"]), value_lines(pdf, truth), strict=True))

    def hinted(field: ExtraField) -> ExtraField:
        label, lines = facts[field.name]
        hint = label_hint(label, lines)
        return ExtraField(
            field.name,
            f"{field.description}. The title printed at the very top of every page is not part "
            f"of any header block. {hint}",
        )

    items: list[ExtraField | FieldGroup] = []
    for item in base.fields:
        if isinstance(item, FieldGroup):
            items.append(FieldGroup(item.name, item.description, [hinted(f) for f in item.fields]))
        else:
            items.append(hinted(item))
    return replace(base, fields=items)


# --- comparing two model readings of the same scan (the Senate regression) ----------------------
def _word_parts(text: str) -> list[str]:
    """Return a value's words, lower case, with the punctuation between them dropped."""
    return re.findall(r"[a-z0-9]+", text.lower())


def same_reading(one: str, other: str) -> bool:
    """
    Return whether two readings of one cell agree, allowing one to be a cut-off of the other.

    Comma against period and case never matter. A reading also agrees with a longer one that
    contains it word for word (``STAFF`` in ``PROFESSIONAL STAFF``), where a word may itself be
    cut short at its end (``GALLEGO`` for ``GALLEGOS``). Anything else, a different letter or a
    different word, is a difference.
    """
    a, b = _word_parts(one), _word_parts(other)
    if not a or not b:
        return a == b  # a blank cell agrees only with a blank one
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return any(
        all(
            x.startswith(y) or y.startswith(x)
            for x, y in zip(long[at : at + len(short)], short, strict=True)
        )
        for at in range(len(long) - len(short) + 1)
    )


def same_rows(one: Sequence[Sequence[str]], other: Sequence[Sequence[str]]) -> bool:
    """Return whether two lists of rows agree cell by cell, in order, under ``same_reading``."""
    return len(one) == len(other) and all(
        len(x) == len(y) and all(same_reading(p, q) for p, q in zip(x, y, strict=True))
        for x, y in zip(one, other, strict=True)
    )
