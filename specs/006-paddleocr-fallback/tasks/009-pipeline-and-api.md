# 009 - OCR in the pipeline, the `ocr=` argument, and `Table.ocr_pages`

Spec: `../spec.md` (Requirements 1 to 5, 9, 10, 12, 13, 15; Design / Flow; Tests, pipeline and
API cases). Depends on: tasks 002, 003, 004, 008.

## Goal

A rejected document is OCR'd on its bad pages, checked again, and carried on; the public API
has the new argument and exports; the result says which pages came from OCR.

## Steps

1. `extract.py`, `run_pipeline(pdf, client, *, discovery_pages, recheck, ocr=None,
   cache_dir=...)`: `ocr` is an `OcrEngine | None` plus the `OcrConfig` (pass both; keep the
   internal signature small and documented). Flow:
   1. Load layers; `assess_text_layers`.
   2. If rejected and OCR is enabled: `ocr_pages` for `bad_pages` only, replace those pages'
      layers, assess again.
   3. If still rejected: raise `TextLayerError` (or the right subclass, step 2). No model
      request has been made on any path.
   4. Continue exactly as now. An accepted document never touches the engine, the cache's
      `ocr/` folder, or PaddleOCR.
2. `textcheck.py`: `REMEDY` becomes three messages chosen by the outcome: OCR disabled
   (`ocr=False`: enable OCR or OCR the PDF yourself), OCR not installed (the
   `OcrUnavailableError` message from task 007 is used as is), OCR ran but the result is still
   unreadable (the existing advice, plus engine, device, the pages OCR'd and what the OCR'd text
   looked like). Update module docstrings: the rejection is now "after OCR".
3. `table.py`/`extract.py`: `Table.ocr_pages: tuple[int, ...] = ()`, filled with the OCR'd
   pages that belong to the table (the table's pages intersected with the OCR'd set, page
   numbers as `Table.pages` numbers them). Check how `Table` is built before adding the field,
   and keep existing positional construction working.
4. `extract_tables_async(..., ocr: OcrConfig | bool = True)` and `extract_tables(...)`, keyword
   only, after the existing arguments: `True` is `OcrConfig()`, `False` is never OCR, an
   `OcrConfig` configures it. Build a `PaddleEngine(config)` (no import happens yet) and run
   the OCR step in a worker thread with `asyncio.to_thread`; the layer loading and checks can
   stay where they are. The cache directory resolved in task 003 is passed to the OCR step.
5. `__init__.py`: `__all__` gains `OcrConfig` and `OcrUnavailableError` (sorted as the list is).
6. Existing tests: rejection tests pass `ocr=False` (they are about the old path). Update
   `test_entrypoint.py`'s `__all__` test.
7. Tests (`tests/test_ocr_pipeline.py`, fake engine, fake client, no PaddleOCR):
   - the garbled Senate PDF (`senate_expenditures_garbled.pdf`) with a fake engine returning
     the words of the OCR'd fixture (`senate_expenditures_paddleocr.pdf`'s native words,
     scaled to pixels) is accepted, the
     fake client gets its first request only after OCR, and `Table.ocr_pages` lists the OCR'd
     pages;
   - a PDF with no text is rescued the same way;
   - a mixed PDF (good native pages plus garbled ones, garbled share above 10%) OCRs only the bad
     pages and keeps the others' native layers;
   - an accepted PDF never calls the engine and never imports PaddleOCR (assert on
     `sys.modules`);
   - noise from the engine gives `TextLayerError` mentioning OCR with zero client requests;
     `ocr=False` gives the old message; PaddleOCR not importable (blocked in the test) gives
     `OcrUnavailableError`, which is also a `TextLayerError`, whose message contains
     `gridkey[ocr]`;
   - a populated OCR cache rescues the document with the engine and PaddleOCR absent;
   - `extract_tables_async` does not block the loop (the fake engine sleeps; a concurrent task
     keeps ticking);
   - `ocr=True`, `ocr=False` and an `OcrConfig` are all accepted by both entrypoints and a wrong
     type raises `TypeError`.
8. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass, an accepted document's behaviour is byte-for-byte unchanged (the
existing pipeline tests pass without edits other than step 6), and `python -c "import gridkey,
sys; assert 'paddleocr' not in sys.modules"` succeeds.
