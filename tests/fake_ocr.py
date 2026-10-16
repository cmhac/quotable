"""Fake OCR engines for the offline tests: scripted answers, no PaddleOCR."""

import time
from pathlib import Path

import pymupdf

from quotable.ocr import OcrWord
from quotable.text import load_layer


class FakeEngine:
    """Answers each recognised page with the next prepared list of words; records the pages."""

    def __init__(self, *answers: list[OcrWord], delay: float = 0.0) -> None:
        self.answers = list(answers)
        self.delay = delay
        self.png_sizes: list[tuple[int, int]] = []

    @property
    def calls(self) -> int:
        return len(self.png_sizes)

    def recognize(self, png: bytes) -> list[OcrWord]:
        pixmap = pymupdf.Pixmap(png)
        self.png_sizes.append((pixmap.width, pixmap.height))
        if self.delay:
            time.sleep(self.delay)  # blocking, like the real thing
        return self.answers[len(self.png_sizes) - 1]


class ExplodingEngine:
    """An engine that must never be called."""

    def recognize(self, png: bytes) -> list[OcrWord]:
        msg = "the engine must not be called"
        raise AssertionError(msg)


def native_as_ocr(pdf: Path, number: int, dpi: int) -> list[OcrWord]:
    """The page's own words as an OCR engine would report them: boxes in pixels."""
    with pymupdf.open(pdf) as document:
        layer = load_layer(document[number - 1])
    scale = dpi / 72
    return [
        OcrWord(
            w.text,
            (w.bbox[0] * scale, w.bbox[1] * scale, w.bbox[2] * scale, w.bbox[3] * scale),
            0.99,
        )
        for w in layer.words
    ]
