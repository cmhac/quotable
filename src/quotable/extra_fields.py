"""
Extra fields: values read from outside the tables, such as a page header (spec 010).

The caller names the fields (``ExtraField``), optionally groups the ones that are printed
together (``FieldGroup``), and passes them as ``ExtraFields`` to ``extract_tables``. Each field
becomes a column on every row of every table. This module holds the request types and the
steps that need no model: validation, grounding the values, the region check, the carry rule
and attaching the results to tables. Each is a separate function so it is tested alone.
"""

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from quotable.grounding import Candidate, FieldGrounding, find_candidates
from quotable.llm import Image, LLMClient, Request
from quotable.models import PageExtras
from quotable.regions import BAND_MARGIN, locate
from quotable.text import Bbox, Layer, tokenize


@dataclass(frozen=True)
class ExtraField:
    """One value to read from each page: its column name and what it is (shown to the model)."""

    name: str
    description: str


@dataclass(frozen=True)
class FieldGroup:
    """
    Fields that are printed together in one block, with a description of the block.

    The description goes to the model. A group has no column of its own; it decides only that
    when a page prints some of its fields, the ones it does not print are cleared (with
    ``carry_forward``).
    """

    name: str
    description: str
    fields: Sequence[ExtraField]


@dataclass(frozen=True)
class ExtraFields:
    """
    The extra fields to read.

    ``fields`` mixes ``ExtraField`` and ``FieldGroup`` items, in column order (groups are
    flattened in place). ``prompt`` is free text for the model, e.g. where the blocks are.
    ``carry_forward`` (off unless asked for) copies a value to the pages after the one that
    prints it, until a page prints another.
    """

    fields: Sequence[ExtraField | FieldGroup]
    prompt: str = ""
    carry_forward: bool = False


EXTRAS_PROMPT = (
    "Extra fields. Besides the tables, report the fields listed below for EVERY page image. "
    "They are text printed OUTSIDE the tables, such as a page header or a section caption: the "
    "page titles and captions that were to be ignored above are exactly what to report here. "
    "Judge each page on its own. Report a field only if it is printed on that page; never infer "
    "it from another page of this window or from the known tables. Copy its value exactly as "
    "printed, without reformatting. If the page does not print the field, its value is null. "
    "Text inside a table's cells is not an extra field unless the field's description says so. "
    "In each page's extras give one entry per field, named exactly as listed, once each."
)
GROUPS_PROMPT = (
    "Some fields are listed under a group. A group is one block of text printed together: report "
    "its fields as printed on this page, each null if this page does not print it. Do not report "
    "the group itself."
)


def extras_prompt(extra_fields: ExtraFields) -> str:
    """Return the text added to the discovery instructions when extra fields are requested."""
    lines = [EXTRAS_PROMPT]
    if any(isinstance(item, FieldGroup) for item in extra_fields.fields):
        lines.append(GROUPS_PROMPT)
    lines.append("Fields:")
    for item in extra_fields.fields:
        if isinstance(item, FieldGroup):
            lines.append(f"- group {item.name.strip()}: {item.description.strip()}")
            lines += [f"    {f.name.strip()}: {f.description.strip()}" for f in item.fields]
        else:
            lines.append(f"- {item.name.strip()}: {item.description.strip()}")
    if extra_fields.prompt.strip():
        lines.append(extra_fields.prompt.strip())
    return "\n".join(lines)


def validate_extra_fields(extra_fields: ExtraFields) -> None:
    """
    Raise if the request is unusable; called before any request is made.

    ``TypeError`` for an item that is not an ``ExtraField`` or a ``FieldGroup`` (a group inside a
    group included); ``ValueError`` for an empty list, a blank or repeated name (field names are
    unique across the whole request, grouped or not), a blank description, or an empty group.
    """
    if not extra_fields.fields:
        msg = "extra_fields.fields must hold at least one field"
        raise ValueError(msg)
    names: set[str] = set()
    groups: set[str] = set()

    def check_field(item: object, where: str) -> None:
        if not isinstance(item, ExtraField):
            msg = f"{where}: expected an ExtraField, got {type(item).__name__}"
            raise TypeError(msg)
        name = item.name.strip()
        if not name:
            msg = f"{where}: a field name is blank"
            raise ValueError(msg)
        if name in names:
            msg = f"{where}: field name {name!r} is used twice"
            raise ValueError(msg)
        names.add(name)
        if not item.description.strip():
            msg = f"{where}: field {name!r} has a blank description"
            raise ValueError(msg)

    for item in extra_fields.fields:
        if isinstance(item, FieldGroup):
            label = item.name.strip()
            if not label:
                msg = "a field group has a blank name"
                raise ValueError(msg)
            if label in groups:
                msg = f"group name {label!r} is used twice"
                raise ValueError(msg)
            groups.add(label)
            if not item.description.strip():
                msg = f"group {label!r} has a blank description"
                raise ValueError(msg)
            if not item.fields:
                msg = f"group {label!r} has no fields"
                raise ValueError(msg)
            for inner in item.fields:
                check_field(inner, f"group {label!r}")
        else:
            check_field(item, "extra_fields")


def flatten(extra_fields: ExtraFields) -> list[tuple[ExtraField, str | None]]:
    """Return the fields in column order (names stripped), each with its group name or ``None``."""
    out: list[tuple[ExtraField, str | None]] = []
    for item in extra_fields.fields:
        if isinstance(item, FieldGroup):
            out += [
                (ExtraField(f.name.strip(), f.description), item.name.strip()) for f in item.fields
            ]
        else:
            out.append((ExtraField(item.name.strip(), item.description), None))
    return out


@dataclass
class ExtraResult:
    """
    One field's value on one page of a table, and where it came from.

    ``value`` is ``""`` and ``source_page`` ``None`` when the field is missing there (nothing
    printed it yet); ``grounding`` is then ``empty``. Otherwise ``source_page`` is the page that
    printed the value (a later page can carry it) and ``grounding`` is how that page's text layer
    holds it.
    """

    value: str = ""
    source_page: int | None = None
    grounding: FieldGrounding = field(default_factory=lambda: FieldGrounding("empty"))


def _centre(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def ground_fields(layer: Layer, values: Mapping[str, str | None]) -> dict[str, FieldGrounding]:
    """
    Ground each field's value on one page against the page's whole text layer.

    The statuses and the coverage are those of a table cell (``exact``, ``fuzzy``,
    ``ungrounded``, ``untokenized``), except that ``misplaced`` cannot occur: a field has no row
    or column. A field with no value is ``empty``. A value found in several places (``2018``
    is also a number in a table) takes the place nearest the centre of the fields that were
    found exactly once; with no such field the value has no place (``bbox`` is ``None``).
    """
    found: dict[str, list[Candidate]] = {}
    out: dict[str, FieldGrounding] = {}
    for name, value in values.items():
        if value is None or not value.strip():
            out[name] = FieldGrounding("empty")
            continue
        tokens = tokenize(value)
        if not tokens:
            out[name] = FieldGrounding("untokenized")
            continue
        found[name] = find_candidates(layer, tokens)
        if not found[name]:
            out[name] = FieldGrounding("ungrounded", coverage=0.0)
    single = [layer.bbox(c[0].start, c[0].end) for c in found.values() if len(c) == 1]
    centre = (
        None
        if not single
        else (
            statistics.fmean(_centre(b)[0] for b in single),
            statistics.fmean(_centre(b)[1] for b in single),
        )
    )
    for name, candidates in found.items():
        if not candidates:
            continue
        pick: Candidate | None = None
        if len(candidates) == 1:
            pick = candidates[0]
        elif centre is not None:

            def distance(c: Candidate, centre: tuple[float, float] = centre) -> tuple[float, int]:
                x, y = _centre(layer.bbox(c.start, c.end))
                return (x - centre[0]) ** 2 + (y - centre[1]) ** 2, c.start

            pick = min(candidates, key=distance)
        first = pick or candidates[0]
        out[name] = FieldGrounding(
            first.status,
            first.coverage,
            first.density,
            len(candidates),
            None if pick is None else layer.text(pick.start, pick.end),
            None if pick is None else layer.bbox(pick.start, pick.end),
            candidates,
        )
    return {name: out[name] for name in values}


TRIGGERS = ("exact", "fuzzy")  # a grounded value; an ungrounded one must not clear its siblings


def propagate(
    pages: Sequence[int],
    printed: Mapping[int, Mapping[str, ExtraResult]],
    fields: Sequence[tuple[ExtraField, str | None]],
    *,
    carry_forward: bool,
) -> dict[int, dict[str, ExtraResult]]:
    """
    Return each page's value of each field, from what the pages print (a pure function).

    ``pages`` is every page of the document in order (pages without a table too); ``printed``
    holds, per page, the results of the fields that page prints; ``fields`` is the column
    order with each field's group name. Without ``carry_forward`` a page has only what it
    prints. With it, a field takes the nearest earlier printed value, never a later one, with
    its grounding; and a page that prints some field of a group with a grounded value
    (``exact`` or ``fuzzy``) clears the group's other fields it does not print, until a page
    prints them. A field in no group is never cleared.
    """
    members: dict[str, list[str]] = {}
    for item, group in fields:
        if group is not None:
            members.setdefault(group, []).append(item.name)
    state: dict[str, ExtraResult] = {}
    out: dict[int, dict[str, ExtraResult]] = {}
    for page in pages:
        now = printed.get(page, {})
        if carry_forward:
            for names in members.values():
                if any(n in now and now[n].grounding.status in TRIGGERS for n in names):
                    for n in names:
                        if n not in now:
                            state.pop(n, None)
            state.update(now)
            current = state
        else:
            current = dict(now)
        out[page] = {
            item.name: replace(current[item.name]) if item.name in current else ExtraResult()
            for item, _ in fields
        }
    return out


REGION_MARGIN = 6.0  # pt added on every side of the places where a field was printed
SECOND_LOOK_PROMPT = (
    "A first look at this page found none of the fields listed below, but the page has text "
    "where those fields are printed on other pages of the same PDF. For each listed field, say "
    "whether it is printed on THIS page: copy its value exactly as printed, or answer null if this "
    "page does not print it. The words found where the field is usually printed are listed; they "
    "may belong to a table, and then the field is not printed here. Never infer a value from "
    "another page."
)


def field_regions(places: Mapping[str, Sequence[Bbox]]) -> dict[str, Bbox]:
    """Return, per field, the union of its places grown by ``REGION_MARGIN``; none if no place."""
    out: dict[str, Bbox] = {}
    for name, boxes in places.items():
        if boxes:
            out[name] = (
                min(b[0] for b in boxes) - REGION_MARGIN,
                min(b[1] for b in boxes) - REGION_MARGIN,
                max(b[2] for b in boxes) + REGION_MARGIN,
                max(b[3] for b in boxes) + REGION_MARGIN,
            )
    return out


def table_bands(layer: Layer, rows: Iterable[tuple[str, str]]) -> list[tuple[float, float]]:
    """
    Return the vertical band of each table on a page, from its first and last row text.

    A table whose rows are not found in the layer has no band, so no words are taken out for
    it: the check then errs towards a false alarm, never towards a miss.
    """
    bands: list[tuple[float, float]] = []
    for first, last in rows:
        top = locate(layer, first, "first")
        bottom = locate(layer, last, "last")
        if top is not None and bottom is not None:
            bands.append((top[0] - BAND_MARGIN, bottom[1] + BAND_MARGIN))
    return bands


def find_suspects(
    layers: Mapping[int, Layer],
    printed: Mapping[int, Mapping[str, FieldGrounding]],
    bands: Mapping[int, Sequence[tuple[float, float]]],
) -> dict[int, dict[str, list[str]]]:
    """
    Return the pages that may hold a header the model said was not there.

    ``printed`` has, per page, the groundings of the fields the page prints. For a page that
    does not print a field, the words of its text layer centred in the field's region (the union
    of its places on the pages that print it) and outside every table band of that page are
    the evidence: page -> field -> words. A field with no place anywhere has no region and is
    never checked.
    """
    places: dict[str, list[Bbox]] = {}
    for row in printed.values():
        for name, grounding in row.items():
            if grounding.bbox is not None:
                places.setdefault(name, []).append(grounding.bbox)
    regions = field_regions(places)
    out: dict[int, dict[str, list[str]]] = {}
    for page, layer in layers.items():
        for name, (x0, y0, x1, y1) in regions.items():
            if name in printed.get(page, {}):
                continue
            inside = layer.crop(y0, y1, x0, x1).words
            outside = [
                w
                for w in inside
                if not any(
                    top <= (w.bbox[1] + w.bbox[3]) / 2 <= bottom
                    for top, bottom in bands.get(page, ())
                )
            ]
            if outside:
                out.setdefault(page, {})[name] = [w.text for w in outside]
    return out


async def second_look(  # noqa: PLR0913, PLR0917
    page: int,
    png: bytes,
    layer: Layer,
    fields: Mapping[str, ExtraField],
    evidence: Mapping[str, list[str]],
    client: LLMClient,
) -> dict[str, ExtraResult]:
    """
    Ask once whether a suspect page prints the fields; return those whose answer grounds.

    Only an answer that grounds (``exact`` or ``fuzzy``) in the page's text layer counts; a null
    or ungrounded answer changes nothing, so a noisy check costs a request and never a value.
    """
    listing = "\n".join(
        f"- {name}: {field.description}. Words found where it is usually printed: "
        f"{' '.join(evidence.get(name, []))}"
        for name, field in fields.items()
    )
    request = Request(
        "extras", SECOND_LOOK_PROMPT, PageExtras, [Image(png), f"Fields:\n{listing}"], page
    )
    answer = await client.ask(request)
    values = {e.name: e.value for e in answer.extras if e.name in fields}
    grounded = ground_fields(layer, values)
    return {
        name: ExtraResult(values[name] or "", page, g)
        for name, g in grounded.items()
        if g.status in TRIGGERS
    }
