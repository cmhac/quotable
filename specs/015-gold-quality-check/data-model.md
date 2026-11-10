# Data model: gold check

Python names are internal (`quotable/gold/`). JSON shapes are the stored and HTTP forms; see
[contracts/gold-files.md](contracts/gold-files.md) and [contracts/gold-api.md](contracts/gold-api.md).

## Stored

### `GoldTable`

| Field | Type | Rule |
| --- | --- | --- |
| `columns` | list of text | 1 to 40; at most 2,000 characters each; on a done page every name non-empty and distinct within the table |
| `rows` | list of list of text | at most 400; each row has exactly one text per column; at most 2,000 characters per cell; untouched empty rows at the bottom are dropped before storing |

### `GoldPage` (one entry of `pages.json`, key `<sha256>:<page>`)

| Field | Type | Rule |
| --- | --- | --- |
| `sha256` | text | 64 hex digits, a document in the current sample |
| `page` | int | 1 to the document's page count, in the current sample |
| `tables` | list of `GoldTable` | at most 10; empty on a done page means "no table here" |
| `done` | bool | |
| `seconds` | number or null | 0 up to 7 days; null for a page finished before timing (shows `--`) |
| `updated` | text | UTC ISO 8601, set by the server on each save |

State: `new` (no record or nothing typed), `started` (a record with any text or named column, not done),
`done`. Opening a done page and editing it keeps it done; unticking "Page done" makes it `started`.
Typed text never changes state by itself; only the done flag does (VRA rule).

### `Sample` (`sample.json`)

| Field | Type | Meaning |
| --- | --- | --- |
| `seed` | int | the seed shown to the user |
| `size` | int | number of pages drawn |
| `drawn` | text | UTC time |
| `documents` | list of `SampleDoc` | `{sha256, name, pages}` as of the draw (name and page count from the newest run) |
| `pages` | list of `{sha256, page}` | sorted by document order, then page |

Only one sample exists. Drawing a new one replaces `sample.json`; `pages.json` is never touched by a draw.
Gold for a page outside the current sample stays stored and is not scored.

## Computed

### `ExtractedTable` (from a saved run)

| Field | Type | Source |
| --- | --- | --- |
| `index` | int | run table index (0-based) |
| `label` | text | run table label |
| `columns` | list of text | run table columns |
| `pages` | dict page -> list of rows (list of text, in column order) | the run's rows of that page in row order, missing values as `""` |

`extracted_from_run(run)` is the only code that reads the run format.

### `Counts` (added up per page, table, document and overall)

`cells`, `hits` (exact, normal, fuzzy), `missed`, `extra`, `cells_correct`, `gold_rows`, `pred_rows`,
`matched_rows`, `rows`, `rows_correct`. Same meanings as `PageScore` in the VRA scorer.

### `PageScore`

`sha256`, `page`, `counts`, `gold_tables`, `pred_tables`, `pairs` (a list of `TablePair`), `unmatched_gold`
(gold table numbers with no partner), `unmatched_extracted` (extracted table indexes with rows on the page
and no partner), `details` (non-exact cells).
`counted` is true when the gold has at least one row or the extraction has at least one row on the page
(as the VRA scorer counts pages; a gold table with named columns and no rows against an extraction with
no rows does not count).
`correct` is `counts.rows_correct == counts.rows` (a missed or extra row makes `rows` larger than
`rows_correct`, as in VRA).

### `TablePair`

`gold` (table number on the page, 1-based), `extracted` (run table index), `columns` (a list of
`ColumnPair`), `counts`.

### `ColumnPair`

`gold` (name), `extracted` (name or null), `how` (`name`, `values` or `none`), plus the same for extracted
columns that no gold column took (`gold` null).

### `Report`

| Field | Meaning |
| --- | --- |
| `runs` | the run used for each document: id, started, model, file name |
| `sample` | seed, size, documents, pages |
| `not_scored` | documents with no usable run |
| `pages` | list of `PageScore` |
| `total` | `Counts` for everything |
| `units` | rows of the headline table: cell, row, page with correct, gold, extracted, in either, recall, precision, accuracy |
| `per_document` | `Counts` and page counts by SHA-256 |
| `per_table` | `Counts` by (SHA-256, extracted table index), plus a "no extracted match" line per document for unmatched gold tables |
| `interval` | for a one-document sample: `{share, low, high, confidence, n, sampled, pages}`; else null |
| `cells` | every non-exact cell: document, page, table, column, gold row, gold, extracted, best level |

## Rules that tie the pieces together

- A done page is scored against the chosen run of its document. The score exists only when every page of
  the sample is done (FR-023).
- A document's gold is found by SHA-256; a run whose document has another hash has no gold (FR-035).
- Counts add: `total = sum(page.counts)`; `per_document` and `per_table` partition `total`.
- `units` use the benchmark level `normal`; `hits` keep all three levels (FR-030).

## Nothing changes in

`Table`, `Row`, `records()`, the DataFrames, the saved-run format (version 1), the cache, the cost log,
the review verdict files and the prompts.
