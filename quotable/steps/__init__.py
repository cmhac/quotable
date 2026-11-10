"""
The pipeline's stages, in the order `run_pipeline` runs them.

1. `discover`: windows of pages, one after the other (each gets the tables found so far).
2. `layout`: page headers and a table's band of a shared page; no model request.
3. `extract`: one request per (table, page), at most 4 at a time.
4. `grounding`, then `position` (both through `ground_document` in `table.py`); no request.
5. `audit` (spec 014, on by default): one request per page with words no cell accounts for, at
   most 4 at a time; the table is grounded again if a row or cell was kept.
6. `extra_fields`, only when asked for: field recheck, then second looks (at most 4 at a time).
7. `merge`; no request.
8. `recheck`: one request per page, all at once.

The text-layer check and OCR (`text/`, `ocr/`) run before step 1.
"""
