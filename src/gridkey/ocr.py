"""
OCR for pages whose text layer is garbled or missing: configuration, words, and layers.

This module holds the parts that need no OCR engine: ``OcrConfig``, the ``OcrWord`` an engine
returns, the ``OcrEngine`` protocol, the conversion of OCR words (pixels of a rendered page)
into a ``Layer`` (points, upright page space, the units ``load_layer`` produces).
:mod:`gridkey.ocr_pages` runs it over a PDF's bad pages with the OCR cache, and PaddleOCR
itself is only touched by :mod:`gridkey._paddle`.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gridkey.text import Bbox, Layer
from gridkey.textcheck import TextLayerError

log = logging.getLogger("gridkey.ocr")

POINTS_PER_INCH = 72
MIN_DPI = 72
MAX_DPI = 600
TEXTLINE_ORIENTATION_MODEL = "PP-LCNet_x1_0_textline_ori"

# Model names PaddleOCR 3.7.0 picks for lang="en" (read from PaddleOCR._get_ocr_model_names).
# Needed only to find the model folders inside ``OcrConfig.model_dir``.
DEFAULT_MODELS: dict[tuple[str, str], tuple[str, str]] = {
    ("en", "PP-OCRv6"): ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
    ("en", "PP-OCRv5"): ("PP-OCRv5_server_det", "en_PP-OCRv5_mobile_rec"),
    ("en", "PP-OCRv4"): ("PP-OCRv4_mobile_det", "en_PP-OCRv4_mobile_rec"),
    ("en", "PP-OCRv3"): ("PP-OCRv3_mobile_det", "en_PP-OCRv3_mobile_rec"),
}

# PaddleOCR argument names that an OcrConfig field sets; naming one in the passthrough
# options as well would silently override the field, so it is an error.
OWNED_BY_FIELD = {
    "lang": "lang",
    "ocr_version": "ocr_version",
    "device": "device",
    "engine": "engine",
    "cpu_threads": "cpu_threads",
    "text_rec_score_thresh": "min_confidence",
    "text_detection_model_name": "text_detection_model",
    "text_recognition_model_name": "text_recognition_model",
    "text_detection_model_dir": "model_dir",
    "text_recognition_model_dir": "model_dir",
    "textline_orientation_model_dir": "model_dir",
    "return_word_box": "(always on: gridkey needs word boxes)",
}
# These change the image geometry, so OCR boxes would not match the page the model sees.
GEOMETRY_OPTIONS = ("use_doc_orientation_classify", "use_doc_unwarping")


class OcrUnavailableError(TextLayerError):
    """The document needs OCR, but OCR cannot run (not installed, or the device is missing)."""


@dataclass(frozen=True)
class OcrWord:
    """One word recognised on a rendered page: text, box ``(x0, y0, x1, y1)`` in pixels, score."""

    text: str
    box: Bbox
    score: float


class OcrEngine(Protocol):
    """What the pipeline needs from an OCR engine."""

    def recognize(self, png: bytes) -> list[OcrWord]:
        """Return the words on a rendered page (PNG bytes), in reading order."""
        ...


@dataclass(frozen=True)
class OcrConfig:
    """
    How bad pages are OCR'd; every field has a default.

    ``paddleocr_options`` and ``predict_options`` pass anything else PaddleOCR accepts to its
    constructor and to ``predict``. An option that a field above already sets, and the ones
    that rotate or unwarp the page (they would misalign the boxes), are rejected.
    ``model_dir`` is a folder with one subfolder per model, named like the model (the layout
    of ``~/.paddlex/official_models``), for use without a download.
    """

    lang: str = "en"
    ocr_version: str = "PP-OCRv6"
    dpi: int = 300
    device: str = "auto"
    engine: str | None = None
    cpu_threads: int | None = None
    min_confidence: float = 0.0
    text_detection_model: str | None = None
    text_recognition_model: str | None = None
    model_dir: str | Path | None = None
    paddleocr_options: Mapping[str, Any] = field(default_factory=dict)
    predict_options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject settings that cannot work, with the reason."""
        if not MIN_DPI <= self.dpi <= MAX_DPI:
            msg = f"dpi must be between {MIN_DPI} and {MAX_DPI}, got {self.dpi}"
            raise ValueError(msg)
        if not 0 <= self.min_confidence <= 1:
            msg = f"min_confidence must be between 0 and 1, got {self.min_confidence}"
            raise ValueError(msg)
        for label, options in (
            ("paddleocr_options", self.paddleocr_options),
            ("predict_options", self.predict_options),
        ):
            for name in GEOMETRY_OPTIONS:
                if options.get(name):
                    msg = (
                        f"{label}[{name!r}] is not allowed: it changes the image geometry, so "
                        "the OCR boxes would no longer match the page the model sees"
                    )
                    raise ValueError(msg)
            for name in options:
                if name in OWNED_BY_FIELD:
                    msg = (
                        f"{label}[{name!r}] is set by OcrConfig.{OWNED_BY_FIELD[name]}; "
                        "use that field instead of passing it through"
                    )
                    raise ValueError(msg)
        named = self.model_dir or self.text_detection_model or self.text_recognition_model
        if named and None in self.model_names():
            msg = (
                "model_dir, text_detection_model and text_recognition_model need both model "
                "names: set text_detection_model and text_recognition_model "
                f"(lang={self.lang!r}, ocr_version={self.ocr_version!r} has no default names "
                "gridkey knows)"
            )
            raise ValueError(msg)

    def model_names(self) -> tuple[str | None, str | None]:
        """Return the (detection, recognition) names: the configured ones, else the defaults."""
        known = DEFAULT_MODELS.get((self.lang, self.ocr_version), (None, None))
        return (self.text_detection_model or known[0], self.text_recognition_model or known[1])


def _split_words(text: str, box: Bbox) -> list[tuple[str, Bbox]]:
    """Split a line on whitespace, dividing its box in proportion to the characters."""
    pieces = text.split()
    if len(pieces) <= 1:
        return [(pieces[0], box)] if pieces else []
    x0, y0, x1, y1 = box
    unit = (x1 - x0) / (sum(len(p) for p in pieces) + len(pieces) - 1)  # one gap = one char
    out: list[tuple[str, Bbox]] = []
    left = x0
    for i, piece in enumerate(pieces):
        right = x1 if i == len(pieces) - 1 else left + len(piece) * unit
        out.append((piece, (left, y0, right, y1)))
        left = right + unit
    return out


def words_to_layer(
    words: Sequence[OcrWord],
    dpi: int,
    page_size: tuple[float, float],
    min_confidence: float = 0.0,
) -> Layer:
    """
    Build a ``Layer`` from OCR words given in pixels of a page rendered at ``dpi``.

    ``points = pixels * 72 / dpi``. The page was rendered with ``page.get_pixmap``, which
    applies the page's rotation, so no rotation is needed: the result is in the upright page
    space ``load_layer`` uses. ``page_size`` is the upright page size in points; boxes are
    clipped to it. Words below ``min_confidence``, empty words and boxes with no area are
    dropped; a word with whitespace inside (a whole line) is split into words.
    """
    scale = POINTS_PER_INCH / dpi
    width, height = page_size
    layer = Layer()
    for word in words:
        if word.score < min_confidence:
            continue
        x0, y0, x1, y1 = (v * scale for v in word.box)
        box = (max(x0, 0.0), max(y0, 0.0), min(x1, width), min(y1, height))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        for text, piece_box in _split_words(word.text, box):
            layer.add(text, piece_box)
    return layer
