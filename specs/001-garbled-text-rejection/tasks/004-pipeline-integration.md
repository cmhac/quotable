# 004 - Run the check first in the pipeline

Spec: `../spec.md` (Requirements 1, 6, 8). Depends on: tasks 002 and 003.

## Goal

`extract_table_async` / `extract_table` reject unreadable documents before rendering or any
model request, with no way to turn the check off.

## Steps

1. In `extract.py`, load the layers first, call `check_text_layers`, then render PNGs. Keep the
   rest of the pipeline unchanged. Do not add any argument, flag or environment variable that
   skips the check.
2. Export `TextLayerError` from `pdf_table_extract/__init__.py` (and `__all__`).
3. Update the module docstring in `extract.py` to list the text-layer check as step 0.
4. Tests in `tests/test_extract.py`:
   - the Senate fixture raises `TextLayerError` and the fake client received zero requests;
   - a PDF with no text raises `TextLayerError` and the client received zero requests;
   - existing end-to-end tests still pass.
5. If existing tests that build PDFs with `make_pdf` trip the check, change their words to
   plausible text. Do not loosen the check.

## Acceptance

- Zero client requests on every rejection path (asserted).
- `extract_table`'s signature has no new parameters.
- `just check` passes (all offline tests).
