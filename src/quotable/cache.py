"""
Where quotable keeps what it has already computed, and how it writes it.

Everything quotable keeps for a project lives in ``.quotable/`` in the current working
directory: ``cache/`` holds model answers and OCR results, and the cost log has a folder of
its own beside it (see :mod:`quotable.costs`), so clearing the cache leaves the costs alone.
A caller may pass a ``cache_dir`` instead; the cache then goes there as given. There is no
in-memory mode: ``None`` means "use the default". quotable never expires or deletes cache
files; deleting ``.quotable/cache/`` starts over.
"""

import re
import sys
import uuid
from pathlib import Path

DEFAULT_DIR_NAME = ".quotable"
CACHE_DIR_NAME = "cache"
COST_DIR_NAME = "cost"
IGNORE_ALL = "*\n"
_OCR_DIR_NAME = "ocr"
_ANSWER_FILE = re.compile(r"[0-9a-f]{64}\.json")


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def resolve_project_dir() -> Path:
    """
    Return ``.quotable/`` in the current working directory, creating it if it is missing.

    When quotable creates the folder itself it also writes ``.quotable/.gitignore`` containing
    ``*``, so what it holds (content derived from the PDF) is never committed by accident. An
    existing ``.quotable/`` is left as it is. Raises ``OSError`` naming the path if the folder
    cannot be created.
    """
    path = Path.cwd() / DEFAULT_DIR_NAME
    created = not path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if created:
            write_atomic(path / ".gitignore", IGNORE_ALL)
    except OSError as err:
        msg = f"cannot use {str(path)!r} as the quotable project folder ({err})"
        raise OSError(msg) from err
    return path


def _adopt_old_cache(project: Path, cache: Path) -> None:
    """Move a cache laid out loose in ``.quotable/`` (quotable 0.1) into ``cache``."""
    loose = [
        entry
        for entry in project.iterdir()
        if (entry.is_file() and _ANSWER_FILE.fullmatch(entry.name))
        or (entry.is_dir() and entry.name == _OCR_DIR_NAME)
    ]
    stuck = 0
    for entry in loose:
        try:
            entry.replace(cache / entry.name)
        except FileNotFoundError:
            continue  # another run moved it first
        except OSError:
            stuck += 1
    if stuck:
        print(
            f"quotable: could not move {stuck} old cache entries into {cache}; "
            "they will be requested again",
            file=sys.stderr,
        )


def resolve_cache_dir(cache_dir: str | Path | None) -> Path:
    """
    Return the cache directory, creating it if it is missing.

    ``cache_dir`` if given (used as it is), otherwise ``.quotable/cache/`` in the current
    working directory; the default's parent is made by :func:`resolve_project_dir`. The first
    time the default folder is made, a cache that quotable 0.1 left loose in ``.quotable/``
    is moved into it. Raises ``OSError`` naming the path if the folder cannot be created or
    written.
    """
    path = Path(cache_dir) if cache_dir is not None else None
    if path is None:
        project = resolve_project_dir()
        path = project / CACHE_DIR_NAME
        fresh = not path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if cache_dir is None and fresh:
            _adopt_old_cache(project, path)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("", encoding="utf-8")  # a real write: os.access lies on some mounts
        probe.unlink()
    except OSError as err:
        msg = (
            f"cannot use {str(path)!r} as the quotable cache directory ({err}); "
            "pass cache_dir=<a writable folder>"
        )
        raise OSError(msg) from err
    return path
