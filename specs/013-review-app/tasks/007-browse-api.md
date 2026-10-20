# 007 - The browsing API: runs, tables, cells, pages, PDF, CSV

Spec: `../spec.md` (Requirements B3, B5, C1 to C6). Depends on: tasks 004 and 006.

## Goal

Every piece of data the runs list, run, table and cell screens show comes from one JSON
endpoint each, computed in Python (testable without a browser). The browser only draws.

## Endpoints

- `GET /api/runs?document=&model=`: the C1 groups: per document (SHA-256) its name, short
  SHA-256, pages, size, and its runs newest first with tables, rows, cells, flagged by status,
  OCR pages, cost and review progress; the list of models for the filter; the project path;
  the number of unreadable runs.
- `GET /api/runs/<id>`: the C2 data: run and document fields, settings, tables with their
  numbers and their **note** (merged parts with pages and original columns, accepted recheck
  changes, pages shared with another table), and `pdf`: `ok`, `missing` (with the path) or
  `changed` (expected and found short SHA-256).
- `GET /api/runs/<id>/tables/<n>/rows?status=&column=&page=&review=&flagged=&recheck=&ocr=&merged=&q=&sort=&desc=&offset=`:
  100 rows from `offset`, the matching count, the table's count, the C3 summary (status
  counts, per-column status counts, position counts, accepted recheck changes), which columns
  are numeric (most non-empty values parse as numbers after removing `,`, `$`, `%` and
  brackets), and each row's **review label** (C3 Review column, with the order of the spec).
- `GET /api/runs/<id>/tables/<n>/rows.csv?...`: the same filters, every matching row, the
  columns of `records()` (header names from `output_names`), `Content-Disposition` naming the
  file `<pdf stem>-table<n>.csv`.
- `GET /api/runs/<id>/tables/<n>/cells/<page>/<row>/<column>` (and `.../extra/<name>` for an
  extra field): the C4 data: status, value, matched text, coverage, density, places, the whole
  row with statuses, the recheck proposal if any, OCR, merge and extra-field facts, the
  verdict and draft (task 004), and the highlights for C5 (matched box, candidate boxes, row
  window, column range, cell area, band, header line and centres, page size). "Cell n of N"
  and previous / next cell and row are computed for the filter in the query string.
- `GET /api/runs/<id>/pages/<page>`: the page's size and words (text layer overlay, and the
  drawing when the PDF is unavailable).
- `GET /api/runs/<id>/pages/<page>.png`: the page rendered with `render_png`; 404 with a reason
  when the PDF is missing or changed. Cache rendered pages in memory (a small LRU keyed by
  SHA-256 and page).
- `GET /api/runs/<id>/pdf`: the PDF itself, `application/pdf`, only when its SHA-256 matches;
  the browser viewer appends `#page=n`.

The PDF check hashes the file once per (path, size, modification time) and caches the answer.
Run costs come from the cost log: the sum of the records with that run id, `free` when there is
none, `unknown` when one has no price.

## Steps

1. Red first: tests in `tests/review/test_browse_api.py`, against a project built in a
   temporary folder by `extract_tables` with a fake model (`Calls` and a two-table fixture),
   plus hand-written cost records.
2. `quotable/review/browse.py`: the functions behind the endpoints (filters, sort with numbers
   as numbers and text case-insensitively, paging, labels, notes, highlights), wired into the
   route table of task 006.
3. Tests: each endpoint's fields; every filter alone and combined; the status filter with and
   without a column; sorting both ways and numeric columns; paging bounds; the review label
   order (stale before changed before can't tell before correct before not reviewed, and the
   suffixes); notes for a merged table and a shared page; CSV columns equal `records()`'s;
   missing PDF gives `missing` and a 404 image; a modified PDF gives `changed`; `free` and
   `unknown` costs; an unknown run id, table, page, row or column is 404 and `../` anywhere is
   404; the server writes nothing to `.quotable/` while browsing (compare the folder before and
   after).
4. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

Every number and fact the browsing screens of the mockup show has an endpoint and a test, and
the project folder is unchanged by browsing.
