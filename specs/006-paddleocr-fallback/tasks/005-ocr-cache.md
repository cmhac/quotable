# 005 - The OCR cache

Spec: `../spec.md` (Requirement 11, the OCR part; Limits, results may differ by device).
Depends on: tasks 003 (`cache.py`), 004 (`OcrConfig`, `OcrWord`), 001 (resolved model names).

## Goal

One OCR result per page is stored under `<cache_dir>/ocr/` and read back before anything else,
without importing PaddleOCR.

## Steps

1. New `src/gridkey/ocr_cache.py`:
   - `ocr_key(pdf_sha256, page, fingerprint) -> str`, SHA-256 hex. The fingerprint covers
     `dpi`, `lang`, `ocr_version`, the resolved detection and recognition model names,
     `min_confidence`, `paddleocr_options`, `predict_options` and the PaddleOCR version, as
     canonical JSON (sorted keys). The device is not in it. `engine` and `model_dir` are in it
     (they can change the output).
   - Resolved model names and the PaddleOCR version must be available without importing
     PaddleOCR: use the names from the config when given; otherwise a small table of the names
     each `ocr_version` and `lang` resolves to (from `probe.md`); the version from
     `importlib.metadata.version("paddleocr")`, or the string `"unknown"` when it is not
     installed. State this limitation in the module docstring: a cache written with a
     different install than the reader's is a miss, never a wrong hit.
   - `file_sha256(path)`: hashes the file in chunks; computed once per run.
   - `read_page(cache_dir, key) -> list[OcrWord] | None` and `write_page(cache_dir, key,
     words, settings)`. The file is JSON: format version, the settings that produced it, and
     the words (text, box in pixels, score). Store pixels, not points, so a reader can convert
     with its own `dpi` check. Read returns `None` for a missing, unreadable, wrong-version or
     mismatched file (a miss). Write uses `cache.write_atomic` and creates `ocr/` if missing.
2. Tests in `tests/test_ocr_cache.py`: write then read round-trips; changing `dpi`, `lang`,
   `ocr_version`, a model name, `min_confidence`, `paddleocr_options` or `predict_options`
   changes the key; changing `device` does not; two different PDFs never share a key; a corrupt
   file, a truncated file and a wrong format version are misses; a miss does not delete the
   file until a new write replaces it; no temp file is left behind.
3. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The tests pass with PaddleOCR not installed in the test's view (import blocked), and the key
changes for exactly the settings the spec lists.
