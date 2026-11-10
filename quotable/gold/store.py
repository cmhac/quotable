"""
The gold check's files (spec 015): the sample and the hand-typed tables, in ``.quotable/gold/``.

``sample.json`` is the drawn sample. ``pages.json`` holds one record per typed page, keyed
``<sha256>:<page>``, rewritten whole and atomically under a lock with sorted keys, so a commit
shows only the pages that changed (research 2). Both are version 1 JSON; see
``specs/015-gold-quality-check/contracts/gold-files.md``.

The gold is hours of hand work and cannot be rebuilt, so a file that exists but cannot be read
raises :class:`StoreError` and is never replaced. A single record that fails validation is
skipped when reading but kept as it is when another page is saved.

Standard library only.
"""

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quotable.storage import gold_dir, write_atomic

FORMAT_VERSION = 1
PAGES_FILE = "pages.json"
SAMPLE_FILE = "sample.json"
MAX_TABLES = 10
MAX_COLUMNS = 40
MAX_ROWS = 400
MAX_TEXT = 2000
MAX_SECONDS = 7 * 24 * 3600
_SHA = re.compile(r"[0-9a-f]{64}")


class GoldError(Exception):
    """Base of the gold check's errors; the message says what is wrong."""


class Invalid(GoldError, ValueError):  # noqa: N818
    """A page or sample the user sent that cannot be stored (the message names the limit)."""


class StoreError(GoldError):
    """A gold file that exists but cannot be read; nothing is written over it."""


def now() -> str:
    """Return the current UTC time as ISO 8601 with a trailing ``Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def key(sha256: str, page: int) -> str:
    """Return the storage key of a page."""
    return f"{sha256}:{page}"


# --- the records ------------------------------------------------------------------------------
@dataclass(frozen=True)
class GoldTable:
    """The correct contents of one printed table on one page."""

    columns: list[str]
    rows: list[list[str]]

    def to_json(self) -> dict[str, Any]:
        """Return the stored form."""
        return {"columns": list(self.columns), "rows": [list(r) for r in self.rows]}


@dataclass(frozen=True)
class GoldPage:
    """A typed page: zero or more tables, and whether the typist is finished with it."""

    sha256: str
    page: int
    tables: list[GoldTable]
    done: bool
    seconds: float | None
    updated: str

    @property
    def status(self) -> str:
        """Return ``done``, ``started`` (anything typed or a named column) or ``new``."""
        if self.done:
            return "done"
        typed = any(
            any(c.strip() for c in t.columns) or any(v for r in t.rows for v in r)
            for t in self.tables
        )
        return "started" if typed else "new"

    def to_json(self) -> dict[str, Any]:
        """Return the stored form (without the key, which is ``sha256:page``)."""
        return {
            "tables": [t.to_json() for t in self.tables],
            "done": self.done,
            "seconds": self.seconds,
            "updated": self.updated,
        }


@dataclass(frozen=True)
class SampleDoc:
    """A document in the sample, as it was when the sample was drawn."""

    sha256: str
    name: str
    pages: int


@dataclass(frozen=True)
class Sample:
    """The drawn sample: its documents and the sampled pages."""

    seed: int
    size: int
    drawn: str
    documents: list[SampleDoc]
    pages: list[tuple[str, int]] = field(default_factory=list)

    def has_document(self, sha256: str) -> bool:
        """Say whether the document is in the sample."""
        return any(d.sha256 == sha256 for d in self.documents)

    def has(self, sha256: str, page: int) -> bool:
        """Say whether ``page`` of the document is in the sample."""
        return (sha256, page) in self.pages

    def to_json(self) -> dict[str, Any]:
        """Return the stored form."""
        return {
            "v": FORMAT_VERSION,
            "seed": self.seed,
            "size": self.size,
            "drawn": self.drawn,
            "documents": [
                {"sha256": d.sha256, "name": d.name, "pages": d.pages} for d in self.documents
            ],
            "pages": [{"sha256": s, "page": p} for s, p in self.pages],
        }

    @classmethod
    def from_json(cls, data: Any) -> "Sample":  # noqa: ANN401
        """Parse a stored sample; ``ValueError`` if it is not a version 1 sample."""
        if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
            msg = "not a version 1 sample"
            raise ValueError(msg)
        try:
            docs = [SampleDoc(d["sha256"], d["name"], d["pages"]) for d in data["documents"]]
            pages = [(p["sha256"], p["page"]) for p in data["pages"]]
            sample = cls(data["seed"], data["size"], data["drawn"], docs, pages)
        except (KeyError, TypeError) as err:
            msg = f"damaged sample: {err!r}"
            raise ValueError(msg) from err
        ok = (
            all(_is_int(v) for v in (sample.seed, sample.size))
            and all(
                _SHA.fullmatch(d.sha256) and isinstance(d.name, str) and _is_int(d.pages)
                for d in docs
            )
            and all(_SHA.fullmatch(s) and _is_int(p) for s, p in pages)
        )
        if not ok:
            msg = "damaged sample"
            raise ValueError(msg)
        return sample


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --- validation -------------------------------------------------------------------------------
def _texts(value: object, limit: int, what: str) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        msg = f"{what} must be a list of at most {limit}"
        raise Invalid(msg)
    if not all(isinstance(v, str) and len(v) <= MAX_TEXT for v in value):
        msg = f"{what} must be text of at most {MAX_TEXT} characters per cell"
        raise Invalid(msg)
    return value


def _table(raw: object, number: int, done: bool) -> GoldTable:  # noqa: FBT001
    if not isinstance(raw, dict):
        msg = f"table {number} must be an object with columns and rows"
        raise Invalid(msg)
    columns = _texts(raw.get("columns"), MAX_COLUMNS, f"the columns of table {number}")
    if not columns:
        msg = f"table {number} needs at least one column"
        raise Invalid(msg)
    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) > MAX_ROWS:
        msg = f"the rows of table {number} must be a list of at most {MAX_ROWS}"
        raise Invalid(msg)
    rows = [_texts(r, MAX_COLUMNS, f"a row of table {number}") for r in raw_rows]
    if any(len(r) != len(columns) for r in rows):
        msg = f"every row of table {number} must have one cell per column"
        raise Invalid(msg)
    while rows and not any(rows[-1]):  # untouched empty rows at the bottom are not saved
        rows.pop()
    names = [c.strip() for c in columns]
    if done and (not all(names) or len(set(names)) != len(names)):
        msg = f"name every column of table {number}, each name once, before marking the page done"
        raise Invalid(msg)
    return GoldTable(list(columns), rows)


def validate_page(payload: object, sha256: str, page: int, sample: Sample | None) -> GoldPage:
    """
    Check a posted page and return the record to store.

    ``sha256`` and ``page`` come from the address. Raises :class:`Invalid` with a message that
    names the problem and the limit.
    """
    if sample is None or not sample.has(sha256, page):
        msg = "page is not in the sample"
        raise Invalid(msg)
    if not isinstance(payload, dict):
        msg = "the body must be an object"
        raise Invalid(msg)
    done = payload.get("done")
    if not isinstance(done, bool):
        msg = "done must be true or false"
        raise Invalid(msg)
    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, list) or len(raw_tables) > MAX_TABLES:
        msg = f"tables must be a list of at most {MAX_TABLES}"
        raise Invalid(msg)
    tables = [_table(t, i + 1, done) for i, t in enumerate(raw_tables)]
    seconds = payload.get("seconds")
    if seconds is not None and (
        isinstance(seconds, bool)
        or not isinstance(seconds, int | float)
        or not 0 <= seconds < MAX_SECONDS
    ):
        msg = "seconds must be a number of seconds, or null"
        raise Invalid(msg)
    return GoldPage(sha256, page, tables, done, seconds, now())


def _page_from_json(sha256: str, page: int, data: Any) -> GoldPage:  # noqa: ANN401
    """Parse a stored record; ``ValueError`` if it is damaged."""
    try:
        tables = [
            GoldTable(list(t["columns"]), [list(r) for r in t["rows"]]) for t in data["tables"]
        ]
        record = GoldPage(sha256, page, tables, data["done"], data["seconds"], data["updated"])
    except (KeyError, TypeError) as err:
        msg = f"damaged record: {err!r}"
        raise ValueError(msg) from err
    texts = all(
        isinstance(v, str) for t in tables for v in (*t.columns, *(c for r in t.rows for c in r))
    )
    if not (
        texts
        and isinstance(record.done, bool)
        and isinstance(record.updated, str)
        and (record.seconds is None or isinstance(record.seconds, int | float))
    ):
        msg = "damaged record"
        raise ValueError(msg)
    return record


# --- the stores -------------------------------------------------------------------------------
def _read_json(path: Path) -> Any:  # noqa: ANN401
    """Return the parsed file, or ``None`` when it does not exist; ``StoreError`` if unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as err:
        msg = f"cannot read {path}: {err.strerror or err}"
        raise StoreError(msg) from err
    try:
        return json.loads(text)
    except ValueError as err:
        msg = f"{path} is not valid JSON ({err}); it was left as it is"
        raise StoreError(msg) from err


def _write(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    try:
        write_atomic(path, text)
    except OSError as err:
        msg = f"cannot write {path}: {err.strerror or err}"
        raise StoreError(msg) from err


class GoldStore:
    """The typed pages of a project, in ``pages.json``."""

    def __init__(self, project_dir: Path) -> None:
        """Use the gold folder of the project folder ``project_dir``; nothing is created yet."""
        self.path = gold_dir(project_dir) / PAGES_FILE
        self.skipped: list[str] = []  # keys of records the last read left out
        self._lock = threading.Lock()

    def _raw(self) -> dict[str, Any]:
        data = _read_json(self.path)
        if data is None:
            return {}
        if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
            msg = f"{self.path} is not a version {FORMAT_VERSION} gold file; it was left as it is"
            raise StoreError(msg)
        pages = data.get("pages")
        if not isinstance(pages, dict):
            msg = f"{self.path} has no pages object; it was left as it is"
            raise StoreError(msg)
        return pages

    def pages(self) -> dict[str, GoldPage]:
        """Return every readable record by key; damaged ones are skipped (see ``skipped``)."""
        with self._lock:
            raw = self._raw()
        found: dict[str, GoldPage] = {}
        skipped = []
        for k, data in raw.items():
            sha, _, number = k.partition(":")
            try:
                if not _SHA.fullmatch(sha) or not number.isdigit():
                    msg = "bad key"
                    raise ValueError(msg)  # noqa: TRY301
                found[k] = _page_from_json(sha, int(number), data)
            except ValueError:
                skipped.append(k)
        self.skipped = skipped
        return found

    def get(self, sha256: str, page: int) -> GoldPage | None:
        """Return the record of a page, if it has one."""
        return self.pages().get(key(sha256, page))

    def save(self, record: GoldPage) -> GoldPage:
        """Store a validated record, replacing that page's previous one; ``StoreError`` if not."""
        with self._lock:
            raw = self._raw()
            raw[key(record.sha256, record.page)] = record.to_json()
            _write(self.path, {"v": FORMAT_VERSION, "pages": raw})
        return record


class SampleStore:
    """The drawn sample of a project, in ``sample.json``."""

    def __init__(self, project_dir: Path) -> None:
        """Use the gold folder of the project folder ``project_dir``; nothing is created yet."""
        self.path = gold_dir(project_dir) / SAMPLE_FILE
        self._lock = threading.Lock()

    def load(self) -> Sample | None:
        """Return the sample, or ``None`` if none was drawn; ``StoreError`` if it is unreadable."""
        data = _read_json(self.path)
        if data is None:
            return None
        try:
            return Sample.from_json(data)
        except ValueError as err:
            msg = f"{self.path} cannot be used ({err}); it was left as it is"
            raise StoreError(msg) from err

    def save(self, sample: Sample) -> Sample:
        """Replace the sample; ``StoreError`` if it cannot be written."""
        with self._lock:
            _write(self.path, sample.to_json())
        return sample
