"""What an API function of the review app is given, may raise, and how it is registered."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class NotFound(Exception):  # noqa: N818
    """Raised by an API function for something that does not exist (HTTP 404)."""


class BadRequest(Exception):  # noqa: N818
    """Raised by an API function for a request it cannot use (HTTP 400)."""


@dataclass(frozen=True)
class Request:
    """A checked request: ``params`` are the route's groups, ``body`` the JSON or ``None``."""

    project_dir: Path
    params: tuple[str, ...] = ()
    query: dict[str, list[str]] = field(default_factory=dict)
    body: Any = None


@dataclass(frozen=True)
class Route:
    """``func(request)`` handles ``method`` on every path that fully matches ``pattern``."""

    method: str
    pattern: str
    func: Callable[[Request], Any]

    def match(self, path: str) -> tuple[str, ...] | None:
        """Return the pattern's groups if ``path`` matches it, else ``None``."""
        found = re.fullmatch(self.pattern, path)
        return None if found is None else found.groups()
