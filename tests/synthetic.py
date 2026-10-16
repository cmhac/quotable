"""
Synthetic multi-page reports with ground truth, for testing how table parts are merged.

A document is a list of items: table parts, gaps (prose or look-alike pages) and stacks (two
parts printed on the same pages). ``render`` draws it with pymupdf, so the PDF has a real text
layer, and returns the truth: for every part its pages, the header names as discovery would
report them, and every row; for every pair of parts whether they are really one table and what
the merge step must do. Seeds come from the document id, so the output is reproducible.

Nothing here calls a model. See ``tests/synthetic_cases.py`` for the case matrix and
``specs/007-merge-reworded-headers/spec.md`` for how the truth files are used.
"""

import random
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import pymupdf

from quotable.grounding import ground_rows
from quotable.text import load_layer, tokenize
from quotable.textcheck import assess_text_layers

PAGE_W = 612.0
LEFT, WIDTH = 40.0, 520.0
BODY, BOLD = "helv", "hebo"
_ID = re.compile(rb"/ID\[.*?\]>>(?=\s*startxref)", re.DOTALL)  # hex or literal strings
FIRST_Y, SECOND_Y = 100.0, 400.0  # top of a table; of the second table of a stack
NUMERIC = ("integer", "decimal", "currency", "percent")

WORDS = [
    "Essex",
    "Windham",
    "Addison",
    "Orange",
    "Franklin",
    "Caledonia",
    "Rutland",
    "Bennington",
    "Lamoille",
    "Orleans",
    "Chittenden",
    "Grand Isle",
    "Washington",
    "Cedar",
    "Willow",
    "Granite",
    "Maple",
    "Summit",
    "Lantern",
    "Harbor",
    "Birch",
    "Alder",
    "Aspen",
    "Spruce",
    "Hickory",
    "Juniper",
    "Poplar",
    "Laurel",
    "Sorrel",
    "Tamarack",
]
TEXT_A = ["Cedar", "Harbor", "Willow", "Granite", "Maple", "Summit", "Riverside", "Lantern"]
TEXT_B = ["Bridge", "Trail", "Library", "Wharf", "Clinic", "Market", "Orchard", "Depot"]
NOTES = ["Late filing", "Revised", "See memo", "On hold", "New site", "Merged", "Pending review"]
MONTHS = ["Jan", "Mar", "May", "Jul", "Sep", "Nov"]
PROSE = [
    "This section of the report explains the review process in plain words. The committee "
    "met several times during the year and discussed how each request should be judged. "
    "Members agreed that every proposal needs a clear budget and a named person in charge.",
    "Staff visited a number of the sites and spoke with local residents about what they "
    "needed most. Many people said that safe walking routes and reliable water were their "
    "main concerns, and they asked that future funding follow those priorities.",
    "The next pages describe the background of the program. It began several years ago as a "
    "small pilot and has since grown into a regular part of the annual budget. Reports from "
    "earlier years are available on request from the office.",
]
LOOKALIKE = [
    "Summary of the review period",
    "",
    "  \u2022 Total requests received: 214",
    "  \u2022 Requests recommended for funding: 96",
    "  \u2022 Median recommended award: $48,000",
    "  \u2022 Largest single award: $750,000",
    "",
    "Key dates",
    "",
    "  Applications opened ........ March 1",
    "  Applications closed ........ April 30",
    "  Committee review ........... June 15",
    "  Awards announced ........... August 2",
]


def value(kind: str, rng: random.Random) -> str:  # noqa: PLR0911
    """Return a random cell value of the given kind."""
    if kind == "word":
        return rng.choice(WORDS)
    if kind == "text":
        return f"{rng.choice(TEXT_A)} {rng.choice(TEXT_B)}"
    if kind == "note":  # short multi-word text, for narrow columns
        return rng.choice(NOTES)
    if kind == "integer":
        return f"{rng.randrange(120, 98000):,}"
    if kind == "decimal":
        return f"{rng.uniform(21, 58):.1f}"
    if kind == "currency":
        return f"${rng.randrange(20, 990) * 1000:,}"
    if kind == "percent":
        return f"{rng.uniform(2, 31):.1f}%"
    if kind == "date":
        return f"{rng.choice(MONTHS)} {rng.randrange(1, 28)}, 20{rng.randrange(15, 24)}"
    msg = f"unknown kind {kind!r}"
    raise ValueError(msg)


@dataclass(frozen=True)
class Col:
    """A column of a schema, and the ways its header can be reworded."""

    name: str
    kind: str
    sup: str | None = None  # a header that contains this one's words, plus more
    sub: str | None = None  # a header whose words are contained in this one's
    reorder: str | None = None  # the same words in another order
    disj: str | None = None  # an unrelated header
    fill: float = 1.0  # share of rows that have a value


@dataclass
class Part:
    """One table, printed over ``pages`` consecutive pages."""

    id: str
    cols: tuple[Col, ...]
    names: tuple[str, ...]  # header as printed, and as discovery would report it
    pages: int = 2
    rows_per_page: int = 10
    last_rows: int | None = None  # rows on the last page, if different
    header: str = "all"  # "all" pages, or "first" page of the part only
    shift: float = 0.0  # the whole table moved right (pt)
    drift: dict[int, float] = field(default_factory=dict)  # extra shift of single columns
    font: float = 8.0
    align: dict[int, str] = field(default_factory=dict)  # column -> "r" (default left)
    kinds: dict[int, str] = field(default_factory=dict)  # column -> kind, replacing the schema's
    mix: dict[int, tuple[str, float]] = field(default_factory=dict)  # column -> (kind, share)
    nonempty: dict[int, int] = field(default_factory=dict)  # column -> exact number of values

    @property
    def n_rows(self) -> int:
        """Return the number of rows over all pages."""
        last = self.rows_per_page if self.last_rows is None else self.last_rows
        return self.rows_per_page * (self.pages - 1) + last


@dataclass
class Gap:
    """Pages without a table."""

    pages: int
    kind: str = "prose"  # "prose" | "lookalike"


@dataclass
class Stack:
    """Two parts printed on the same pages, one above the other."""

    top: Part
    bottom: Part


@dataclass
class Relation:
    """What is true of a pair of parts, and what the merge step must do with them."""

    a: str
    b: str
    same_table: bool | None  # really one table? None: a judgement call
    expect_merge: bool | None  # None: depends on a rule or threshold still being decided
    probes: list[str] = field(default_factory=list)
    stage: str = "merge"  # "merge", or "discovery" (the headers already match)
    note: str = ""
    isolate: bool = True  # the header rules must all pass, so one other rule decides


@dataclass
class Doc:
    """A document: items in page order, and the relations between its parts."""

    id: str
    description: str
    tags: list[str]
    items: list[Part | Gap | Stack]
    relations: list[Relation] = field(default_factory=list)

    def parts(self) -> list[Part]:
        """Return every part in page order (a stack's top part first)."""
        out: list[Part] = []
        for item in self.items:
            if isinstance(item, Part):
                out.append(item)
            elif isinstance(item, Stack):
                out += [item.top, item.bottom]
        return out


# --- header word checks (the rules of the spec, used to label the cases) ---------------------
def token_set(name: str) -> frozenset[str]:
    """Return the comparison tokens of a column name."""
    return frozenset(tokenize(name))


def compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    """Say whether one set of words contains the other (both non-empty)."""
    return bool(a) and bool(b) and (a <= b or b <= a)


def names_check(names_a: tuple[str, ...], names_b: tuple[str, ...]) -> dict[str, object]:
    """Return the facts about two headers that the merge rules look at."""
    ta = [token_set(x) for x in names_a]
    tb = [token_set(x) for x in names_b]
    out: dict[str, object] = {
        "columns_a": len(ta),
        "columns_b": len(tb),
        "same_signature": [" ".join(tokenize(x)) for x in names_a]
        == [" ".join(tokenize(x)) for x in names_b],
    }
    if len(ta) == len(tb):
        n = len(ta)
        out["equal_positions"] = sum(a == b for a, b in zip(ta, tb, strict=True))
        out["compatible_all"] = all(compatible(a, b) for a, b in zip(ta, tb, strict=True))
        out["cross_compatible"] = any(
            compatible(ta[i], tb[j]) for i in range(n) for j in range(n) if i != j
        )
    return out


# --- drawing ---------------------------------------------------------------------------------
@cache
def _width(text: str, font_name: str, size: float) -> float:
    return pymupdf.get_text_length(text, fontname=font_name, fontsize=size)


def _wrap(text: str, max_width: float, size: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and _width(f"{lines[-1]} {word}", BOLD, size) <= max_width:
            lines[-1] += f" {word}"
        elif _width(word, BOLD, size) <= max_width:
            lines.append(word)
        else:
            msg = f"header word {word!r} does not fit a column of {max_width:.0f} pt"
            raise ValueError(msg)
    if len(lines) > 3:  # noqa: PLR2004
        msg = f"header {text!r} needs more than 3 lines"
        raise ValueError(msg)
    return lines


def make_rows(doc_id: str, part: Part) -> list[list[str]]:
    """Return every row of the part (cell values, empty string for an empty cell)."""
    rng = random.Random(f"{doc_id}/{part.id}")  # noqa: S311
    n = part.n_rows
    columns: list[list[str]] = []
    for c, col in enumerate(part.cols):
        kind = part.kinds.get(c, col.kind)
        cells = [value(kind, rng) for _ in range(n)]
        if c in part.mix:
            other, share = part.mix[c]
            replaced = set(rng.sample(range(n), n - round(n * share)))
            cells = [value(other, rng) if i in replaced else v for i, v in enumerate(cells)]
        keep = part.nonempty.get(c, round(n * col.fill))
        kept = set(rng.sample(range(n), keep))
        columns.append([v if i in kept else "" for i, v in enumerate(cells)])
    return [[columns[c][i] for c in range(len(part.cols))] for i in range(n)]


def _draw_table(page: pymupdf.Page, part: Part, index: int, rows: list[list[str]], y0: float):
    n = len(part.cols)
    w = WIDTH / n
    size = part.font
    shape = page.new_shape()  # one shape per table: much faster than a call per cell
    xs = [LEFT + i * w + part.shift + part.drift.get(i, 0.0) for i in range(n)]
    y = y0
    if part.header == "all" or index == 0:
        wrapped = [_wrap(name, w - 8, size) for name in part.names]
        depth = max(len(lines) for lines in wrapped)
        line_height = size + 2.5
        for x, lines in zip(xs, wrapped, strict=True):
            top = y + (depth - len(lines)) * line_height
            for k, line in enumerate(lines):
                shape.insert_text((x, top + k * line_height), line, fontsize=size, fontname=BOLD)
        y += depth * line_height + 8
    for row in rows:
        for i, (cell, x) in enumerate(zip(row, xs, strict=True)):
            if not cell:
                continue
            width = _width(cell, BODY, size)
            if width > w - 8:
                msg = f"value {cell!r} does not fit a column of {w:.0f} pt"
                raise ValueError(msg)
            px = x + w - 6 - width if part.align.get(i) == "r" else x
            if px < 10 or px + width > PAGE_W - 10:  # noqa: PLR2004
                msg = f"value {cell!r} would leave the page"
                raise ValueError(msg)
            shape.insert_text((px, y), cell, fontsize=size, fontname=BODY)
        y += size * 2
    shape.commit()


def _furniture(page: pymupdf.Page, number: int) -> None:
    page.insert_text((40, 40), f"Annual Funding Report  |  Section {number}", fontsize=10)
    page.insert_text((290, 760), f"- {number} -", fontsize=9)


def render(doc: Doc, pdf_path: Path) -> dict[str, Any]:
    """Draw the document to ``pdf_path`` and return its truth (JSON-ready)."""
    rng = random.Random(doc.id)  # noqa: S311
    pdf = pymupdf.open()
    parts: dict[str, dict[str, Any]] = {}
    number = 0

    def record(part: Part, first_page: int) -> list[list[list[str]]]:
        rows = make_rows(doc.id, part)
        pages = [first_page + j for j in range(part.pages)]
        per_page: list[list[list[str]]] = []
        start = 0
        for j in range(part.pages):
            count = part.rows_per_page if j < part.pages - 1 else part.n_rows - start
            per_page.append(rows[start : start + count])
            start += count
        parts[part.id] = {
            "id": part.id,
            "pages": pages,
            "columns": list(part.names),
            "schema_columns": [c.name for c in part.cols],
            "header_pages": [p for j, p in enumerate(pages) if part.header == "all" or j == 0],
            "rows": {str(p): per_page[j] for j, p in enumerate(pages)},
        }
        return per_page

    for item in doc.items:
        if isinstance(item, Gap):
            for _ in range(item.pages):
                number += 1
                page = pdf.new_page()
                _furniture(page, number)
                if item.kind == "lookalike":
                    for k, line in enumerate(LOOKALIKE):
                        page.insert_text((50, 100 + k * 16), line, fontsize=11)
                else:
                    y = 90.0
                    for para in rng.sample(PROSE, 2):
                        page.insert_textbox(pymupdf.Rect(40, y, 570, y + 110), para, fontsize=11)
                        y += 120
            continue
        tables = (
            [(item, FIRST_Y)]
            if isinstance(item, Part)
            else [
                (item.top, FIRST_Y),
                (item.bottom, SECOND_Y),
            ]
        )
        first = number + 1
        per_part = [record(part, first) for part, _ in tables]
        for j in range(max(part.pages for part, _ in tables)):
            number += 1
            page = pdf.new_page()
            _furniture(page, number)
            for (part, y0), per_page in zip(tables, per_part, strict=True):
                _draw_table(page, part, j, per_page[j], y0)
            page.insert_text((40, 730), "Source: program files. Amounts in US dollars.", fontsize=7)
    pdf.save(pdf_path, deflate=True, garbage=4, clean=True)  # garbage=4 merges duplicate fonts
    pdf.close()
    # MuPDF writes a random file ID; fix it to keep the bytes stable. It sits in the trailer,
    # after the cross-reference table, so a change of length moves no offset.
    data = pdf_path.read_bytes()
    fixed = b"/ID[<" + b"0" * 32 + b"><" + b"0" * 32 + b">]>>"
    pdf_path.write_bytes(_ID.sub(fixed, data))

    by_id = {p.id: p for p in doc.parts()}
    relations = []
    for rel in doc.relations:
        check = names_check(by_id[rel.a].names, by_id[rel.b].names)
        _guard(doc.id, rel, check)
        relations.append({**rel.__dict__, "names_check": check})
    return {
        "id": doc.id,
        "description": doc.description,
        "tags": doc.tags,
        "pages": number,
        "parts": list(parts.values()),
        "relations": relations,
    }


def _guard(doc_id: str, rel: Relation, check: dict[str, object]) -> None:
    """Refuse a case whose label does not fit its header words."""
    if rel.stage == "merge" and check["same_signature"]:
        msg = f"{doc_id}: {rel.a}/{rel.b} have the same signature, discovery would join them"
        raise ValueError(msg)
    if rel.stage == "discovery" and not check["same_signature"]:
        msg = f"{doc_id}: {rel.a}/{rel.b} are labelled discovery but the signatures differ"
        raise ValueError(msg)
    if rel.isolate and rel.stage == "merge":
        ok = check.get("compatible_all") and not check.get("cross_compatible")
        if not ok or check["columns_a"] != check["columns_b"]:
            msg = f"{doc_id}: {rel.a}/{rel.b} are meant to isolate one rule but the headers fail"
            raise ValueError(msg)


# --- checking a rendered case ----------------------------------------------------------------
def validate(case: dict[str, Any], pdf_path: Path) -> list[str]:
    """Return what is wrong with a rendered case (empty if it is sound)."""
    problems: list[str] = []
    with pymupdf.open(pdf_path) as pdf:
        layers = {i + 1: load_layer(p) for i, p in enumerate(pdf)}
    assessment = assess_text_layers(layers)
    if assessment.reason is not None:
        problems.append(f"text layer rejected: {assessment.reason}")
    for part in case["parts"]:
        names = part["columns"]
        for page, rows in part["rows"].items():
            dict_rows = [dict(zip(names, row, strict=True)) for row in rows]
            for r, cells in enumerate(ground_rows(dict_rows, names, layers[int(page)]), 1):
                bad = {c: g.status for c, g in cells.items() if g.status not in ("exact", "empty")}
                if bad:
                    problems.append(f"part {part['id']} page {page} row {r}: {bad}")
    return problems
