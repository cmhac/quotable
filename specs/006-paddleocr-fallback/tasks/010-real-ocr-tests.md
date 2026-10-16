# 010 - Real-OCR tests and the NVIDIA checklist

Spec: `../spec.md` (Tests, opt-in real-OCR tests; Limits, no GPU on this machine). Depends on:
task 009. Runs real models (a first-run download of about 130 MB) but no paid API: no model
client is called. Tell the user before the first run because of the download.

## Goal

The pieces that fakes cannot prove are checked against a real PaddleOCR on the CPU, behind an
opt-in marker.

## Steps

1. `pyproject.toml`: add the marker `ocr: runs the real PaddleOCR models (slow, downloads
   models, no API cost)` and extend `addopts` to `-m 'not live and not ocr'`.
2. `justfile`: `test-ocr` running `uv run pytest -m ocr -rs`, with a comment.
3. `tests/ocr/` (like `tests/live/`), with a fake model client and a temp cache directory:
   - the garbled Senate PDF (`senate_expenditures_garbled.pdf`): OCR rescues it, the second
     check passes, no client request before OCR, `Table.ocr_pages` is set;
   - the same pages rasterised into an image-only PDF built in the test (PyMuPDF): rescued;
   - alignment on `fy22_ag_house_original.pdf`: OCR'd word boxes land on the native words'
     boxes within a stated tolerance in points (choose it from the data, write it in the test,
     and say why), checking the points conversion on a real page;
   - word boxes: the keys `probe.md` recorded exist in a real result;
   - a second run is served from the cache with PaddleOCR not called (assert on the engine or
     log).
4. `tests/data/README.md`: a "NVIDIA GPU check (manual)" section: what to run (`pip install
   "gridkey[ocr-core]"`, the GPU wheel recipe from `probe.md`, then `just test-ocr` with
   `OcrConfig(device="gpu")` or the auto choice), what to record (date, card, driver, CUDA
   wheel, PaddlePaddle version, result, time per page), and a table with an empty row to fill
   in. Do not claim a GPU result.
5. Run `just test-ocr` on this machine and report: pass/fail per test, time per page on the CPU,
   the download size. Run `just test` and confirm the OCR tests are deselected.
6. `ruff check`, `ruff format`, `ty check`.

## Done when

`just test-ocr` passes on the CPU (or each failure is reported with its cause), `just test`
does not run the OCR tests, and the checklist is in `tests/data/README.md`.
