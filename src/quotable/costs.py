"""
The cost log: one JSON line per model request that was paid for.

Every request that reaches a model appends a record to ``.quotable/cost/requests.jsonl`` in the
project's ``.quotable/`` folder (never in a ``cache_dir`` the caller named), so clearing the
cache leaves the costs alone. A record holds the tokens and the price at the time; it never
holds a prompt, an answer or a path. Writing is best effort: a failure prints one warning per
run and never breaks an extraction.

This module imports only the standard library and :mod:`quotable.cache`, so the report command
can use it without loading a model SDK of its own.
"""

import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from quotable.cache import COST_DIR_NAME, resolve_project_dir

COST_FILE_NAME = "requests.jsonl"
VERSION = 1


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class CostRecord:
    """One paid model request."""

    v: int
    time: str  # UTC, ISO 8601
    run: str  # one ``extract_tables`` call
    stage: str  # "schema" | "extract" | "recheck"
    model: str  # ``provider:model-name``
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float | None  # None when the model has no known price

    def to_line(self) -> str:
        """Return the record as one compact JSON line, newline included."""
        return json.dumps(asdict(self), separators=(",", ":")) + "\n"

    @classmethod
    def from_line(cls, line: str) -> "CostRecord":
        """Parse one line; raise ``ValueError`` if it is not a record this version wrote."""
        data = json.loads(line)  # JSONDecodeError is a ValueError
        if not isinstance(data, dict):
            msg = "a cost record is a JSON object"
            raise ValueError(msg)  # noqa: TRY004
        try:
            fields = {name: data[name] for name in cls.__dataclass_fields__}
        except KeyError as err:
            msg = f"cost record without {err.args[0]!r}"
            raise ValueError(msg) from err
        if fields["v"] != VERSION or not _is_int(fields["v"]):
            msg = f"unknown cost record version {fields['v']!r}"
            raise ValueError(msg)
        for name in ("time", "run", "stage", "model"):
            if not isinstance(fields[name], str):
                msg = f"cost record field {name!r} must be a string"
                raise ValueError(msg)  # noqa: TRY004
        for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            if not _is_int(fields[name]):
                msg = f"cost record field {name!r} must be an integer"
                raise ValueError(msg)  # noqa: TRY004
        cost = fields["cost_usd"]
        if cost is not None and (isinstance(cost, bool) or not isinstance(cost, int | float)):
            msg = "cost record field 'cost_usd' must be a number or null"
            raise ValueError(msg)
        return cls(**fields)


class CostLog:
    """Appends the cost records of one run; every method is safe to call and never raises."""

    def __init__(self, run_id: str | None = None) -> None:
        """Start a log for one run; ``run_id`` defaults to a fresh random id."""
        self.run_id = run_id or uuid.uuid4().hex
        self._warned = False

    def record(  # noqa: PLR0913
        self,
        stage: str,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        cost: Decimal | None,
    ) -> None:
        """Append one record; a failure is a one-time warning."""
        entry = CostRecord(
            v=VERSION,
            time=datetime.now(UTC).isoformat(timespec="seconds"),
            run=self.run_id,
            stage=stage,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=None if cost is None else float(cost),
        )
        try:
            self._append(entry.to_line())
        except OSError as err:
            self._warn_once(f"could not record the cost of a request ({err})")

    def skip(self, reason: str) -> None:
        """Say once that a request's cost was not recorded, and why."""
        self._warn_once(f"a request's cost was not recorded: {reason}")

    def _append(self, text: str) -> None:
        folder = resolve_project_dir() / COST_DIR_NAME
        folder.mkdir(exist_ok=True)
        # One O_APPEND write of the whole line: concurrent runs cannot interleave inside a line.
        fd = os.open(folder / COST_FILE_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            print(f"quotable: {message}", file=sys.stderr)


def cost_file(project_dir: Path) -> Path:
    """Return where the cost records of the project folder ``project_dir`` are kept."""
    return project_dir / COST_DIR_NAME / COST_FILE_NAME
