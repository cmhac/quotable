"""
``ocr_pages``: OCR the bad pages of a PDF, reading the OCR cache before anything else.

For each page asked for, the cache (see :mod:`quotable.ocr_cache`) is read first; only a miss
renders the page at ``config.dpi`` and calls the engine, and the result is written to the
cache before it is used. This is blocking work: the async entrypoint runs it in a thread.
"""

import logging
import time
from collections.abc import Iterable
from pathlib import Path

import pymupdf

from quotable.ocr import OcrConfig, OcrEngine, words_to_layer
from quotable.ocr_cache import file_sha256, fingerprint, ocr_key, read_page, write_page
from quotable.text import Layer

log = logging.getLogger("quotable.ocr")


def ocr_pages(
    pdf: Path,
    pages: Iterable[int],
    config: OcrConfig,
    engine: OcrEngine,
    cache_dir: Path,
) -> dict[int, Layer]:
    """
    Return a replacement ``Layer`` for each page number (1-based) in ``pages``.

    Pages not in ``pages`` are never rendered or recognised. A page that comes back with no
    words still gets an (empty) layer and a cache file, so a blank page is not OCR'd again.
    """
    digest = file_sha256(pdf)
    settings = fingerprint(config)
    layers: dict[int, Layer] = {}
    from_cache = recognised = 0
    started = time.perf_counter()
    with pymupdf.open(pdf) as document:
        for number in pages:
            key = ocr_key(digest, number, settings)
            page = document[number - 1]
            words = read_page(cache_dir, key)
            if words is None:
                png = page.get_pixmap(dpi=config.dpi).tobytes("png")
                words = engine.recognize(png)
                write_page(cache_dir, key, words, settings)
                recognised += 1
            else:
                from_cache += 1
            size = (page.rect.width, page.rect.height)  # upright, as load_layer's coordinates
            layers[number] = words_to_layer(words, config.dpi, size, config.min_confidence)
    log.info(
        "OCR: %d page(s) from the cache, %d recognised, %.1f s",
        from_cache,
        recognised,
        time.perf_counter() - started,
    )
    return layers
