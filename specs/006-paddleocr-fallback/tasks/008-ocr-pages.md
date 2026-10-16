# 008 - `ocr_pages`: cache, render, recognise, build layers

Spec: `../spec.md` (Requirements 2, 3, 11, 13; Design / Flow, Coordinates). Depends on:
tasks 003, 004, 005, 007.

## Goal

One function takes the list of bad pages and returns replacement `Layer`s, reading the cache
first and calling the engine only for pages that miss.

## Steps

1. In `ocr.py` add `ocr_pages(pdf, pages, config, engine, cache_dir) -> dict[int, Layer]`
   (blocking; no async here):
   - Hash the PDF file once (`ocr_cache.file_sha256`).
   - For each page in `pages`, in order: compute the key, read the cache; on a hit use the
     words; on a miss render the page with `page.get_pixmap(dpi=config.dpi)` (PNG bytes), call
     `engine.recognize`, then `write_page`. Pages are done one after another; the engine is
     created by the caller, once.
   - Convert each page's words with `words_to_layer` using the page's upright size from the
     same source `load_layer` uses.
   - A page that comes back with no words still gets a (empty) layer and a cache file, so a
     blank page is not OCR'd again.
   - Log at INFO on `gridkey.ocr`: pages from cache, pages OCR'd, time spent.
   - Open the PDF with PyMuPDF and close it on exit, also on error.
2. Tests in `tests/test_ocr_pages.py` with a fake engine (a class with a `recognize` counter
   that returns words for a given rendered page, keyed by a page marker the test controls):
   - a second call makes zero engine calls and returns equal layers;
   - changing `dpi` misses; the device (not part of this function's inputs) is irrelevant;
   - pages not in `pages` are never rendered or recognised;
   - the render uses `config.dpi` (check the PNG size);
   - the points conversion lands on the native words' boxes for a born-digital page when the
     fake engine returns that page's native words scaled to pixels (the offline stand-in for
     the real alignment test in task 010);
   - a rotated page keeps upright coordinates;
   - an engine error propagates and leaves no partial cache file.
3. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The tests pass with PaddleOCR absent, and a fully cached run constructs no engine work (the fake
engine's counter stays at zero).
