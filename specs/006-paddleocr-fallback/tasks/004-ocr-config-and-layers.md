# 004 - `OcrConfig`, OCR words, and turning them into a `Layer`

Spec: `../spec.md` (Requirements 3, 5, 6; Design / `OcrConfig`, Coordinates, Words). Depends on:
task 001 (the word-box facts in `probe.md`).

## Goal

The pure parts of OCR exist and are tested with no PaddleOCR installed: the configuration, the
word type, the engine protocol, and the conversion from OCR words in pixels to a `Layer` in
points.

## Steps

1. New `src/gridkey/ocr.py` with:
   - `OcrUnavailableError(TextLayerError)`.
   - `OcrWord` (frozen: `text`, `box` as `(x0, y0, x1, y1)` in pixels, `score`).
   - `OcrEngine` protocol: `recognize(png: bytes) -> list[OcrWord]`.
   - `OcrConfig`, a frozen dataclass with the fields, types and defaults in the spec's table
     (`lang="en"`, `ocr_version="PP-OCRv6"`, `dpi=300`, `device="auto"`, `engine=None`,
     `cpu_threads=None`, `min_confidence=0.0`, `text_detection_model=None`,
     `text_recognition_model=None`, `model_dir=None`, `paddleocr_options={}`,
     `predict_options={}`). Use `field(default_factory=dict)` for the dicts and keep the config
     hashable-irrelevant (it is never used as a dict key).
   - `__post_init__` validation, raising `ValueError` with the reason: `dpi` outside 72 to 600;
     `min_confidence` outside 0 to 1; `paddleocr_options` that turn on
     `use_doc_orientation_classify` or `use_doc_unwarping` (use the argument names from
     `probe.md`); an option named in both an `OcrConfig` field and `paddleocr_options` /
     `predict_options` (the config field would be silently overridden otherwise).
2. In `ocr.py`, `words_to_layer(words, dpi, page_size) -> Layer`:
   - points = pixels * 72 / dpi; build the `Layer` through `Layer.add(text, bbox)` the way
     `load_layer` does, in upright page space. Read `text.py` first and match its tokenisation
     (one `Layer` entry per word as `load_layer` would produce) rather than inventing one.
   - A word with whitespace inside (a line returned instead of words) is split on whitespace
     and its box divided in proportion to the character counts of the pieces.
   - Drop words below `min_confidence`, empty words, and words with a degenerate box.
3. Tests in `tests/test_ocr.py`: defaults; every validation error; a known pixel box at 300 dpi
   becomes the expected point box; at 150 dpi the same pixels give twice the points; a line
   box splits into words whose boxes tile the line and keep order; a rotated page (use a
   `Layer` expectation built from the page's upright size, as `test_text.py` does for rotated
   pages) gets the expected box; low-confidence and empty words are dropped.
4. `ruff check`, `ruff format`, `ty check`, `just test`. Do not export anything from
   `__init__.py` yet (task 009).

## Done when

The tests pass without PaddleOCR importable and `ocr.py` imports nothing outside the standard
library, `pymupdf` and gridkey.
