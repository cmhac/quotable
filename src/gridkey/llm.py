"""
The model boundary: a request, a client protocol and a disk cache.

Everything that talks to a model goes through ``LLMClient.ask``; the pipeline never
imports a vendor SDK. Any object with an ``identity`` string and an async ``ask``
works, which is how the offline tests run the whole pipeline with a fake model.

``CachedClient`` wraps any client with a request cache under ``cache_dir``. The key
covers the client's identity, the instructions, the output schema and every prompt
part (text and image bytes), so a re-run never pays twice for the same request.

Deliberately left out (see the original project): dollar pricing and a cost cap
(``max_requests`` caps new calls instead) and request concurrency limits.
"""

import hashlib
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


class BudgetExceededError(RuntimeError):
    """The cap on new (uncached) model requests was reached."""


@dataclass(frozen=True)
class Image:
    """A PNG prompt part."""

    png: bytes


Part = str | Image


@dataclass
class Request:
    """One model request: everything that determines its answer."""

    stage: str  # "schema" | "extract" | "recheck"; for logs, not part of the key
    instructions: str
    output_type: type[BaseModel]
    parts: list[Part]
    page: int | None = None  # for logs and fakes, not part of the key


class LLMClient(Protocol):
    """What the pipeline needs from a model."""

    identity: str  # model name + settings; anything that changes the answers

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Return an instance of ``request.output_type``."""
        ...


def _fingerprint(part: Part) -> list[Any]:
    if isinstance(part, str):
        return ["text", part]
    return ["image", hashlib.sha256(part.png).hexdigest()]


def request_key(identity: str, request: Request) -> str:
    """Return the sha256 over everything that determines the model's answer."""
    blob = json.dumps(
        {
            "client": identity,
            "instructions": request.instructions,
            "output_schema": request.output_type.model_json_schema(),
            "parts": [_fingerprint(p) for p in request.parts],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class CachedClient:
    """Wrap a client with a disk cache and a cap on new requests."""

    def __init__(self, inner: LLMClient, cache_dir: Path, max_requests: int | None = None) -> None:
        """Cache ``inner``'s answers in ``cache_dir``; stop after ``max_requests`` new ones."""
        self.inner = inner
        self.identity = inner.identity
        self.cache_dir = cache_dir
        self.max_requests = max_requests
        self.new_requests = 0

    async def ask(self, request: Request) -> Any:  # noqa: ANN401
        """Return the cached answer, or ask the wrapped client and cache it."""
        path = self.cache_dir / f"{request_key(self.identity, request)}.json"
        if path.exists():
            try:
                return request.output_type.model_validate(json.loads(path.read_text("utf-8")))
            except (ValueError, ValidationError) as err:
                print(f"ignoring unusable cache file {path.name}: {err}", file=sys.stderr)
        if self.max_requests is not None and self.new_requests >= self.max_requests:
            msg = f"{self.new_requests} new requests made, cap is {self.max_requests}"
            raise BudgetExceededError(msg)
        self.new_requests += 1
        answer = await self.inner.ask(request)
        _write_atomic(path, answer.model_dump_json(indent=1))
        return answer
