"""
`Table`s rebuilt from the golden fixture, without a model (spec 007).

For every part in a truth file: the `PageResult`s are the truth rows (what a perfect model
would extract), the text layers are the real ones read from the fixture PDF, and grounding and
the position check run exactly as in the pipeline (`ground_document`). A part that shares its
pages with another gets its own band of the layer from `regions.table_layers`, as
`extract.table_page_layers` does, using its first and last row as the bounds.
"""

import json
from pathlib import Path
from typing import Any

import pymupdf

from quotable.discover import signature
from quotable.layout import page_layouts
from quotable.regions import table_layers
from quotable.table import PageResult, Table, ground_document
from quotable.text import Layer, load_layer

DATA = Path(__file__).parent / "data" / "synthetic"


def doc_ids() -> list[str]:
    """Return the ids of the fixture documents, in manifest order."""
    return [entry["id"] for entry in json.loads((DATA / "manifest.json").read_text())]


def load_doc(doc_id: str) -> dict[str, Any]:
    """Return a document's truth file."""
    return json.loads((DATA / f"{doc_id}.json").read_text())


def relations(doc_id: str) -> list[dict[str, Any]]:
    """Return the truth relations of a document."""
    return load_doc(doc_id)["relations"]


def _row_text(row: list[str]) -> str:
    return " ".join(v for v in row if v)


def tables_of(doc_id: str) -> dict[str, Table]:
    """Return the `Table` of every part of a document, by part id."""
    truth = load_doc(doc_id)
    with pymupdf.open(DATA / f"{doc_id}.pdf") as document:
        layers: dict[int, Layer] = {i + 1: load_layer(p) for i, p in enumerate(document)}
    parts = truth["parts"]
    bands: dict[str, dict[int, Layer]] = {p["id"]: {} for p in parts}
    for page, layer in layers.items():
        on_page = [p for p in parts if page in p["pages"]]
        specs = [
            (
                p["id"],
                _row_text(p["rows"][str(page)][0]),
                _row_text(p["rows"][str(page)][-1]),
            )
            for p in on_page
        ]
        for part, band in zip(on_page, table_layers(page, layer, specs), strict=True):
            bands[part["id"]][page] = band
    tables: dict[str, Table] = {}
    for part in parts:
        columns = list(part["columns"])
        results = [
            PageResult(
                page,
                [dict(zip(columns, row, strict=True)) for row in part["rows"][str(page)]],
            )
            for page in part["pages"]
        ]
        part_layers = bands[part["id"]]
        grounded, position = ground_document(columns, results, part_layers)
        layouts = page_layouts(columns, [part_layers[r.page] for r in results])
        tables[part["id"]] = Table(columns, results, part_layers, grounded, position, layouts)
    return tables


def discovered(doc_id: str) -> tuple[list[Table], dict[str, int]]:
    """
    Return the tables as discovery would group them, and the group index of every part.

    Discovery joins pages whose column names have the same signature (case and punctuation
    ignored); the parts of such a group are one `Table` when the merge step starts.
    """
    parts = tables_of(doc_id)
    groups: dict[tuple[str, ...], list[str]] = {}
    for part_id, table in parts.items():
        groups.setdefault(signature(table.columns), []).append(part_id)
    tables: list[Table] = []
    member: dict[str, int] = {}
    for part_ids in groups.values():
        first = parts[part_ids[0]]
        pages = sorted((p for i in part_ids for p in parts[i].pages), key=lambda r: r.page)
        layers = {k: v for i in part_ids for k, v in parts[i].layers.items()}
        grounded, position = ground_document(first.columns, pages, layers)
        layouts = page_layouts(first.columns, [layers[r.page] for r in pages])
        tables.append(Table(first.columns, pages, layers, grounded, position, layouts))
        member.update(dict.fromkeys(part_ids, len(tables) - 1))
    return tables, member
