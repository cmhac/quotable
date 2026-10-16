"""
Where gridkey keeps what it has already computed, and how it writes it.

Model answers and OCR results are always cached on disk. The directory is the ``cache_dir``
the caller passes, or else ``.gridkey/`` in the current working directory. There is no
in-memory mode: ``None`` means "use the default". gridkey never expires or deletes cache
files; deleting the folder starts over.
"""

import uuid
from pathlib import Path

DEFAULT_DIR_NAME = ".gridkey"
IGNORE_ALL = "*\n"


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def resolve_cache_dir(cache_dir: str | Path | None) -> Path:
    """
    Return the cache directory, creating it if it is missing.

    ``cache_dir`` if given, otherwise ``.gridkey/`` in the current working directory. When
    gridkey creates the default folder itself it also writes ``.gridkey/.gitignore``
    containing ``*``, so the cache (which holds content derived from the PDF) is never
    committed by accident. A folder the caller named, or an existing ``.gridkey/``, is left
    as it is. Raises ``OSError`` naming the path if the folder cannot be created or written.
    """
    default = cache_dir is None
    path = Path.cwd() / DEFAULT_DIR_NAME if cache_dir is None else Path(cache_dir)
    created = default and not path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if created:
            write_atomic(path / ".gitignore", IGNORE_ALL)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("", encoding="utf-8")  # a real write: os.access lies on some mounts
        probe.unlink()
    except OSError as err:
        msg = (
            f"cannot use {str(path)!r} as the gridkey cache directory ({err}); "
            "pass cache_dir=<a writable folder>"
        )
        raise OSError(msg) from err
    return path
