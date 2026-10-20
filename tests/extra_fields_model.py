"""
A fake model that answers from a fixture document's truth file (spec 010; no model, no cost).

It answers discovery with the tables of each page and the extra fields' values the truth says
are printed there, extraction with the truth rows, and (when asked) the recheck and the second
look. Faults are injected by overriding what it reads (``read``), what a second look answers
(``second``) or what a recheck answers (``recheck``).
"""

from collections.abc import Callable
from typing import Any

from quotable.llm.answers import (
    Column,
    ExtrasRecheck,
    ExtraValue,
    PageExtras,
    PageRows,
    PageWithExtras,
    TableInfo,
    WindowTables,
    WindowWithExtras,
)
from quotable.llm.client import Image, Request
from quotable.steps.extra_fields import ExtraField, ExtraFields, FieldGroup
from tests.conftest import FakeClient
from tests.fixture_tables import load_doc

Reads = dict[int, dict[str, str | None]]


def _row_text(row: list[str]) -> str:
    return " ".join(v for v in row if v)


def truth_model(  # noqa: PLR0915
    case_id: str,
    *,
    read: Reads | None = None,
    second: Callable[[int, list[str]], dict[str, str | None]] | None = None,
    recheck: dict[tuple[int, str], str] | None = None,
    rename: dict[str, str] | None = None,
) -> FakeClient:
    """Return a fake client for the fixture document ``case_id`` (see the module docstring)."""
    truth = load_doc(case_id)
    names = rename or {}
    printed = {int(p): dict(v) for p, v in truth["extra_fields"]["printed"].items()}
    for page, values in (read or {}).items():
        printed[page] = {**printed[page], **values}
    parts = truth["parts"]
    state = {"next": 1}

    def tables_on(page: int) -> list[TableInfo]:
        out = []
        for part in parts:
            if page in part["pages"]:
                rows = part["rows"][str(page)]
                columns = [Column(name=c, description="") for c in part["columns"]]
                out.append(
                    TableInfo(
                        label=part["id"],
                        columns=columns,
                        first_row=_row_text(rows[0]),
                        last_row=_row_text(rows[-1]),
                    )
                )
        return out

    def discovery(request: Request) -> Any:  # noqa: ANN401
        images = sum(isinstance(p, Image) for p in request.parts)
        pages = list(range(state["next"], state["next"] + images))
        state["next"] += images
        if request.output_type is WindowTables:
            return WindowTables.model_validate(
                {"pages": [{"tables": [t.model_dump() for t in tables_on(p)]} for p in pages]}
            )
        entries = [
            PageWithExtras(
                tables=tables_on(p),
                extras=[ExtraValue(name=names.get(n, n), value=v) for n, v in printed[p].items()],
            )
            for p in pages
        ]
        return WindowWithExtras(pages=entries)

    def extract(request: Request) -> PageRows:
        first_column = str(request.parts[0]).splitlines()[1].split(":")[0].removeprefix("- ")
        assert request.page is not None
        for part in parts:
            if request.page in part["pages"] and part["columns"][0].strip() == first_column:
                rows = part["rows"][str(request.page)]
                return PageRows(rows=[dict(zip(part["columns"], row, strict=True)) for row in rows])
        msg = f"no table starting with {first_column!r} on page {request.page}"
        raise AssertionError(msg)

    def handler(request: Request) -> Any:  # noqa: ANN401
        if request.stage == "schema":
            return discovery(request)
        if request.stage == "extract":
            return extract(request)
        assert request.page is not None
        listed = [
            line.split(":")[0].removeprefix("- ")
            for part in request.parts
            if isinstance(part, str)
            for line in part.splitlines()
            if line.startswith("- ")
        ]
        if request.stage == "extras":
            answers = (second or (lambda _page, _names: {}))(request.page, listed)
            return PageExtras(
                extras=[ExtraValue(name=n, value=answers.get(n)) for n in listed],
            )
        if request.stage == "recheck" and request.output_type is ExtrasRecheck:
            answers = recheck or {}
            return ExtrasRecheck(
                extras=[
                    ExtraValue(name=n, value=answers.get((request.page, n), "")) for n in listed
                ]
            )
        msg = f"unexpected request {request.stage}"
        raise AssertionError(msg)

    return FakeClient(handler)


def request_for(truth, *, carry, grouped=True):
    """The caller's request that matches a document's truth."""
    fields = truth["fields"]
    groups = {g["name"]: g for g in truth["groups"]} if grouped else {}
    items: list[ExtraField | FieldGroup] = []
    placed: set[str] = set()
    for f in fields:
        field = ExtraField(f["name"], f["description"])
        group = groups.get(f["group"]) if f["group"] else None
        if group is None:
            items.append(field)
        elif group["name"] not in placed:
            placed.add(group["name"])
            members = [
                ExtraField(m["name"], m["description"])
                for m in fields
                if m["group"] == group["name"]
            ]
            items.append(FieldGroup(group["name"], group["description"], members))
    return ExtraFields(items, carry_forward=carry)
