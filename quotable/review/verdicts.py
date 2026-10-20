"""
Verdicts and drafts in ``.quotable/review/`` (spec 013, sections D and F).

``verdicts.jsonl`` takes one appended JSON line per verdict; the latest line for a key wins.
``drafts.json`` holds the unsaved note and corrected value of each key and is rewritten whole.
A key says which cell a verdict is about without naming a run: a cell is the document's SHA-256,
its table's columns, the page, the 1-based row and the column; an extra field is the SHA-256,
the field's name and the page that prints it. So a verdict applies to every run of the same
document, whatever order that run returned its tables in. A key is written as a JSON object,
never as a joined string. Standard library only.
"""

import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeGuard

from quotable.storage import review_dir, write_atomic

FORMAT_VERSION = 1
VERDICTS_FILE = "verdicts.jsonl"
DRAFTS_FILE = "drafts.json"
MAX_TEXT = 5000
VERDICT_KINDS = ("correct", "changed", "unsure")

# Why the model was wrong, in the spec's order (it gives the keys 1 to 9).
CATEGORIES: dict[str, str] = {
    "misspelling": "Letters wrong",
    "spacing": "Spaces or line breaks wrong",
    "dropped_word": "Words of the cell left out",
    "added_word": "Words added that the cell does not have (often from a neighbouring cell)",
    "hallucination": "A value that is not on the page at all",
    "wrong_cell": "The value of another row or column",
    "wrong_number": "Digits, sign or decimal point wrong",
    "corrected_source": (
        "The model fixed an error that is printed in the PDF; the PDF's text is the right value"
    ),
    "other": "Anything else; the note should say what",
}


# --- keys -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CellKey:
    """A table cell: ``columns`` are the table's column names, ``row`` is 1-based."""

    sha256: str
    columns: tuple[str, ...]
    page: int
    row: int
    column: str

    def to_json(self) -> dict[str, Any]:
        """Return the key as a JSON object."""
        return {
            "sha256": self.sha256,
            "columns": list(self.columns),
            "page": self.page,
            "row": self.row,
            "column": self.column,
        }


@dataclass(frozen=True)
class ExtraKey:
    """An extra field's value, shared by every table and row that carries it."""

    sha256: str
    name: str
    page: int  # the page that prints the value

    def to_json(self) -> dict[str, Any]:
        """Return the key as a JSON object."""
        return {"sha256": self.sha256, "extra": self.name, "page": self.page}


Key = CellKey | ExtraKey


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def key_from_json(data: object) -> Key:
    """Return the key in ``data``; ``ValueError`` if it is not a key."""
    if not isinstance(data, dict) or not isinstance(data.get("sha256"), str):
        msg = "not a verdict key"
        raise ValueError(msg)  # noqa: TRY004
    sha, page = data["sha256"], data.get("page")
    if not _is_int(page):
        msg = "a verdict key needs an integer page"
        raise ValueError(msg)
    if "extra" in data:
        if not isinstance(data["extra"], str):
            msg = "a verdict key's extra field name must be a string"
            raise ValueError(msg)  # noqa: TRY004
        return ExtraKey(sha, data["extra"], page)
    columns, row, column = data.get("columns"), data.get("row"), data.get("column")
    if (
        not isinstance(columns, list)
        or not all(isinstance(c, str) for c in columns)
        or not _is_int(row)
        or not isinstance(column, str)
    ):
        msg = "not a verdict key"
        raise ValueError(msg)
    return CellKey(sha, tuple(columns), page, row, column)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- verdicts ---------------------------------------------------------------------------------
def validate(
    verdict: str,
    *,
    extracted: str,
    value: str | None,
    category: str | None,
    note: str,
) -> None:
    """Raise ``ValueError`` with a message the app can show if the verdict cannot be saved."""
    if verdict not in VERDICT_KINDS:
        msg = f"The verdict must be one of {', '.join(VERDICT_KINDS)}."
        raise ValueError(msg)
    if len(note) > MAX_TEXT:
        msg = f"The note can have at most {MAX_TEXT:,} characters."
        raise ValueError(msg)
    if verdict != "changed":
        return
    if category not in CATEGORIES:
        msg = "Choose why the model was wrong."
        raise ValueError(msg)
    if value is None:
        msg = "Give the right value (blank means the cell should be empty)."
        raise ValueError(msg)
    if len(value) > MAX_TEXT:
        msg = f"The right value can have at most {MAX_TEXT:,} characters."
        raise ValueError(msg)
    if value == extracted:
        msg = "The right value is the same as the extracted one."
        raise ValueError(msg)


@dataclass(frozen=True)
class Verdict:
    """One reviewer's judgement of one extracted value, as one line of ``verdicts.jsonl``."""

    time: str  # UTC, ISO 8601 with a trailing Z
    run: str
    name: str  # the PDF's file name
    table_index: int
    table_label: str
    table_columns: tuple[str, ...]
    key: Key
    extracted: str
    status: str  # the cell's grounding status at review time
    verdict: str  # correct | changed | unsure
    value: str | None  # the right value, for changed
    category: str | None  # a key of CATEGORIES, for changed
    note: str
    queue: Mapping[str, Any] = field(default_factory=dict)  # the settings it was reviewed under

    def to_line(self) -> str:
        """Return the verdict as one compact JSON line, newline included."""
        data = {
            "v": FORMAT_VERSION,
            "time": self.time,
            "run": self.run,
            "name": self.name,
            "table": {
                "index": self.table_index,
                "label": self.table_label,
                "columns": list(self.table_columns),
            },
            "key": self.key.to_json(),
            "extracted": self.extracted,
            "status": self.status,
            "verdict": self.verdict,
            "value": self.value,
            "category": self.category,
            "note": self.note,
            "queue": dict(self.queue),
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"

    @classmethod
    def from_line(cls, line: str) -> "Verdict":
        """Parse one line; raise ``ValueError`` if it is not a verdict this version wrote."""
        data = json.loads(line)  # JSONDecodeError is a ValueError
        if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
            msg = "not a version 1 verdict"
            raise ValueError(msg)
        try:
            table = data["table"]
            fields: dict[str, Any] = {
                "time": data["time"],
                "run": data["run"],
                "name": data["name"],
                "table_index": table["index"],
                "table_label": table["label"],
                "table_columns": tuple(table["columns"]),
                "key": key_from_json(data["key"]),
                "extracted": data["extracted"],
                "status": data["status"],
                "verdict": data["verdict"],
                "value": data["value"],
                "category": data["category"],
                "note": data["note"],
                "queue": data["queue"],
            }
        except (KeyError, TypeError) as err:
            msg = f"damaged verdict: {err!r}"
            raise ValueError(msg) from err
        texts = ("time", "run", "name", "table_label", "extracted", "status", "note")
        if (
            not all(isinstance(fields[n], str) for n in texts)
            or not _is_int(fields["table_index"])
            or fields["verdict"] not in VERDICT_KINDS
            or not all(
                v is None or isinstance(v, str) for v in (fields["value"], fields["category"])
            )
            or not isinstance(fields["queue"], dict)
        ):
            msg = "damaged verdict"
            raise ValueError(msg)
        return cls(**fields)


class VerdictStore:
    """Appends verdicts to ``verdicts.jsonl`` and reads the latest one of each key."""

    def __init__(self, project_dir: Path) -> None:
        """Use the review folder of the project folder ``project_dir``; nothing is created yet."""
        self.path = review_dir(project_dir) / VERDICTS_FILE
        self.skipped = 0  # damaged lines the last read left out
        self._seen: tuple[int, int] | None = None
        self._latest: dict[Key, Verdict] = {}
        self._lock = threading.Lock()

    def append(self, verdict: Verdict) -> None:
        """Write one line; ``OSError`` if the file cannot be written."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One O_APPEND write of the whole line: concurrent writers cannot interleave inside it.
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, verdict.to_line().encode("utf-8"))
        finally:
            os.close(fd)

    def latest(self) -> dict[Key, Verdict]:
        """Return the latest verdict of every key, by file order; damaged lines are skipped."""
        with self._lock:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                self._seen, self._latest, self.skipped = None, {}, 0
                return {}
            seen = (stat.st_size, stat.st_mtime_ns)
            if seen != self._seen:
                latest: dict[Key, Verdict] = {}
                skipped = 0
                with self.path.open(encoding="utf-8", errors="replace") as handle:
                    for text in handle:
                        if not text.strip():
                            continue
                        try:
                            verdict = Verdict.from_line(text)
                        except ValueError:
                            skipped += 1
                            continue
                        latest[verdict.key] = verdict
                self._seen, self._latest, self.skipped = seen, latest, skipped
            return dict(self._latest)

    def apply(
        self, key: Key, value: str
    ) -> tuple[Literal["reviewed", "stale", "none"], Verdict | None]:
        """Say which verdict applies to ``key`` now showing ``value``, and whether it is stale."""
        found = self.latest().get(key)
        if found is None:
            return "none", None
        return ("reviewed" if found.extracted == value else "stale"), found


# --- drafts -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Draft:
    """A note and half-typed corrected value, kept until a verdict is saved."""

    note: str
    value: str | None
    category: str | None
    saved_at: str  # UTC, ISO 8601 with a trailing Z


class DraftStore:
    """Keeps one draft per key in ``drafts.json``, rewritten whole on each change."""

    def __init__(self, project_dir: Path) -> None:
        """Use the review folder of the project folder ``project_dir``; nothing is created yet."""
        self.path = review_dir(project_dir) / DRAFTS_FILE
        self._lock = threading.Lock()

    def get(self, key: Key) -> Draft | None:
        """Return the draft of ``key``, if there is one."""
        with self._lock:
            return self._read().get(key)

    def all(self) -> dict[Key, Draft]:
        """Return every draft, by key."""
        with self._lock:
            return self._read()

    def put(self, key: Key, note: str, value: str | None, category: str | None) -> Draft:
        """Save the draft of ``key`` and return it; ``OSError`` if the file cannot be written."""
        draft = Draft(note, value, category, _now())
        with self._lock:
            drafts = self._read()
            drafts[key] = draft
            self._write(drafts)
        return draft

    def clear(self, key: Key) -> None:
        """Drop the draft of ``key``; a key without one is left alone."""
        with self._lock:
            drafts = self._read()
            if drafts.pop(key, None) is not None:
                self._write(drafts)

    def _read(self) -> dict[Key, Draft]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
                msg = "not a version 1 drafts file"
                raise ValueError(msg)  # noqa: TRY301
            drafts: dict[Key, Draft] = {}
            for entry in data["drafts"]:
                note, value, category = entry["note"], entry["value"], entry["category"]
                if not isinstance(note, str) or not all(
                    v is None or isinstance(v, str) for v in (value, category)
                ):
                    msg = "damaged draft"
                    raise ValueError(msg)  # noqa: TRY301
                drafts[key_from_json(entry["key"])] = Draft(
                    note, value, category, str(entry["saved_at"])
                )
        except (ValueError, KeyError, TypeError):
            self.path.replace(self.path.with_name(f"{DRAFTS_FILE}.bad"))
            return {}
        return drafts

    def _write(self, drafts: Mapping[Key, Draft]) -> None:
        data = {
            "v": FORMAT_VERSION,
            "drafts": [
                {
                    "key": key.to_json(),
                    "note": d.note,
                    "value": d.value,
                    "category": d.category,
                    "saved_at": d.saved_at,
                }
                for key, d in drafts.items()
            ],
        }
        write_atomic(self.path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
