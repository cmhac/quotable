# 011 - Docs

Spec: `../spec.md` (Docs). Depends on: tasks 001 to 010.

## Steps

1. `README.md`: replace "Requires a readable text layer" with the new behaviour (a document
   with a garbled or missing layer has its bad pages OCR'd). Add: the two extras and install
   recipes (CPU, NVIDIA) taken from `probe.md`, and when the default install is enough; the
   `ocr=` argument and `OcrConfig` with its defaults; `Table.ocr_pages` and the caution about OCR
   errors (the comma-read-as-period example from the fixture); the `.gridkey/` folder, its
   `.gitignore`, and `cache_dir`; that the first OCR run downloads models through PaddleOCR
   (`model_dir` for offline); that Intel Macs, Linux ARM and Python 3.14 have no OCR; the
   limits that matter to a user (orientation not corrected, English/Latin script, CPU speed).
   Change the example comment "optional: cache model answers on disk", since caching is no
   longer optional. Update the "Not carried over yet" / "Not handled" lists only if they
   mention OCR.
2. `AGENTS.md`: project state (spec 006 implemented; update the test count and the Spec 001
   sentence "OCR is required"); file tree (`ocr.py`, `cache.py`, `ocr_cache.py`,
   `ocr_device.py`, `_paddle.py`, `tests/ocr/`); commands table (`just test-ocr`, including that
   it downloads models and makes no paid call).
3. Module docstrings: `llm.py`, `textcheck.py`, `extract.py` (caching always on; rejection after
   OCR). Check that none still says OCR is the user's job or that the cache is optional.
4. Spec status: set `spec.md`'s status line to "implemented" and record anything in
   `probe.md` that differed from the spec under a short "Differences found in implementation"
   heading at the end of `spec.md`. Specs 001, 002 and 005 are history; do not edit them.
5. `ruff check`, `ruff format`, `ty check`, `just test`, `just hooks` (stage new files first so
   the hooks see them; stage specific files only).

## Done when

A reader of the README can install, run, and configure OCR without opening the spec; `grep -rn
"OCR the PDF yourself" src/ README.md` finds only the `ocr=False` and unsupported-platform
messages; all checks pass.
