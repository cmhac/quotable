"""
The OCR cache: one JSON file per OCR'd page, in ``<cache_dir>/ocr/``.

A file holds the page's words in pixels of the rendered page (not points, so a reader can
convert with its own ``dpi``) and the settings that produced them. The file name is a hash of
the PDF's bytes, the page number and a fingerprint of everything that changes the output:
``dpi``, ``lang``, ``ocr_version``, the model names the config sets, ``min_confidence``,
``engine``, ``model_dir``, ``paddleocr_options``, ``predict_options`` and the installed
PaddleOCR version. The device is not part of it (a cached result is reused across devices).

Nothing here imports PaddleOCR, so a populated cache works without the OCR extra. The
default models PaddleOCR picks are decided by ``lang``, ``ocr_version`` and its own version,
which are all in the fingerprint, so the key needs no model-name table. The PaddleOCR version
is read from the installed package's metadata, or is ``"unknown"`` when it is not installed:
a cache written under a different install than the reader's is a miss, never a wrong hit.
"""

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Any

from quotable.cache import write_atomic
from quotable.ocr import OcrConfig, OcrWord

FORMAT = 1
SUBDIR = "ocr"
CHUNK = 1 << 20


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def paddleocr_version() -> str:
    """Return the installed PaddleOCR version, or ``"unknown"`` (without importing it)."""
    try:
        return metadata.version("paddleocr")
    except metadata.PackageNotFoundError:
        return "unknown"


def fingerprint(config: OcrConfig, version: str | None = None) -> dict[str, Any]:
    """Return every setting that changes the OCR output (the device is left out)."""
    return {
        "dpi": config.dpi,
        "lang": config.lang,
        "ocr_version": config.ocr_version,
        "text_detection_model": config.text_detection_model,
        "text_recognition_model": config.text_recognition_model,
        "min_confidence": config.min_confidence,
        "engine": config.engine,
        "model_dir": None if config.model_dir is None else str(config.model_dir),
        "paddleocr_options": dict(config.paddleocr_options),
        "predict_options": dict(config.predict_options),
        "paddleocr_version": paddleocr_version() if version is None else version,
    }


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def ocr_key(pdf_sha256: str, page: int, settings: dict[str, Any]) -> str:
    """Return the cache key (SHA-256 hex) for one page of one PDF under these settings."""
    blob = _canonical({"pdf": pdf_sha256, "page": page, "settings": settings})
    return hashlib.sha256(blob.encode()).hexdigest()


def _path(cache_dir: Path, key: str) -> Path:
    return cache_dir / SUBDIR / f"{key}.json"


def read_page(cache_dir: Path, key: str) -> list[OcrWord] | None:
    """Return the cached words, or ``None`` for a missing, unreadable or mismatched file."""
    path = _path(cache_dir, key)
    try:
        data = json.loads(path.read_text("utf-8"))
        if data["format"] != FORMAT or data["key"] != key:
            return None
        return [
            OcrWord(w["text"], tuple(float(v) for v in w["box"]), float(w["score"]))  # ty: ignore[invalid-argument-type]
            for w in data["words"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_page(cache_dir: Path, key: str, words: list[OcrWord], settings: dict[str, Any]) -> None:
    """Write one page's words (atomically); an existing file is replaced."""
    data = {
        "format": FORMAT,
        "key": key,
        "settings": settings,
        "words": [{"text": w.text, "box": list(w.box), "score": w.score} for w in words],
    }
    write_atomic(_path(cache_dir, key), json.dumps(data, ensure_ascii=False, default=str))
