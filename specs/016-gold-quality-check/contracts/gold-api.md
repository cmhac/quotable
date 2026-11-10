# Contract: gold check routes and command

Internal to the review app (nothing here is public API, constitution IV), written down so the browser
modules, the server and the tests agree. Every route follows spec 013 section B: 127.0.0.1 only, `Host`
and `Origin` checks, JSON in and out, errors as `{"error": "..."}`, security headers on every response.
A body is accepted only with `Origin` and `Content-Type: application/json`.

`<sha>` is a 64-digit lower-case SHA-256 of a document in the current sample; `<n>` is a 1-based page
number of it. The record routes (`GET` and `PUT` of `/pages/<sha>/<n>`) take only pages that were drawn;
the image and words routes take any page of a sampled document, for the whole-PDF view. Anything else
is 404 ("no such page"). The browser never sends a file path.

## Routes

| Method and path | Body or query | Answer |
| --- | --- | --- |
| `GET /api/gold` | | `{sample, documents, pages, done, total, tracked}` (below) |
| `POST /api/gold/sample` | `{documents: [sha...], size, seed?, replace?}` | the same as `GET /api/gold` after the draw |
| `GET /api/gold/pages/<sha>/<n>` | | `{record, name, pages, pdf}` |
| `GET /api/gold/pages/<sha>/<n>/words` | | `{width, height, words: [[text, x0, y0, x1, y1, line_end]]}` |
| `GET /api/gold/pages/<sha>/<n>.png` | `rot=0\|90\|180\|270` (default 0) | the page as a PNG (`Raw`) |
| `PUT /api/gold/pages/<sha>/<n>` | `{tables: [{columns, rows}], done, seconds}` | the stored record (`max_body` 2 MiB) |
| `GET /api/gold/score` | `run=<id>` repeated, optional | `{complete: false, done, total, left}` or the report |
| `GET /api/gold/score.csv` | `kind=pages\|cells`, `run=<id>` repeated | the CSV (`Raw`, `text/csv`) |

### `GET /api/gold`

- `sample`: `null`, or `{seed, size, drawn, documents: [{sha256, name, pages}]}`.
- `documents`: one entry per document with a saved run, for the draw: `{sha256, name, pages, run,
  pdf}`, where `run` is the newest run's id and `pdf` is `ok`, `missing` or `changed` (as spec 013's
  `pdf_status`). Offered for choosing only when `pdf` is `ok`.
- `pages`: the sample's pages in order: `{sha256, name, page, status, seconds}` with `status` of `new`,
  `started` or `done`.
- `done`, `total`: counts of done and sampled pages.
- `tracked`: `{ok: true}` or `{ok: false, note}` when `.quotable/.gitignore` could not be made to leave
  the gold folder trackable (FR-036); the app shows the note.

### `POST /api/gold/sample`

- 400 if `documents` is empty or names an unknown or unusable document, if `size` is below the number of
  documents or above the total pages, or if a sample exists and `replace` is not `true`.
- A missing `seed` is chosen by the server and returned in `sample.seed`.
- Stored gold is not touched. `ensure_gold_trackable` runs here.

### `GET /api/gold/pages/<sha>/<n>`

- `record`: the stored page `{tables, done, seconds, updated}` or `null`. `pdf`: `ok`, `missing` or
  `changed`. The size of the page comes with its words.
- A page of a document whose PDF is missing or changed still answers (with `pdf` set) so the editor can
  show the typed gold; its image and words answer 404 with the reason.

### `PUT /api/gold/pages/<sha>/<n>`

- Validation (all 400, message names the problem and the limit): the limits of FR-022; every row has one
  text per column; `done` is true or false; `seconds` is null or a number from 0 to 7 days; on a done
  page every column of every table is named, names distinct within a table.
- The server sets `updated`, drops untouched empty rows at the bottom of each table, and replaces the page's
  record. A file it cannot read is 500 with the reason, and nothing is written (FR-038).
- Last save of a page wins.

### `GET /api/gold/score`

- Incomplete: `{complete: false, done, total, left: [{sha256, name, page}]}` (up to 50 listed).
- Complete: `{complete: true, report}` where `report` has the fields of the data model's `Report`, plus
  `choices`: for each document, the runs that could be scored, newest first (`{id, started, model}`).
  A `run` that is unknown or whose document has no gold is 400 naming it. Two `run` values for one
  document are 400.
- Nothing is stored.

## Command

```text
quotable gold-report [--dir PATH] [--run ID]... [--out DIR]
```

| Option | Meaning |
| --- | --- |
| `--dir PATH` | the project's `.quotable/` folder (default `.quotable` in the current directory) |
| `--run ID` | score this run; repeat for other documents (at most one per document; default: the newest run of each) |
| `--out DIR` | where to write `gold_pages.csv` and `gold_cells.csv` (default `<project>/reports/`) |

Prints the report (definitions included) to stdout and writes the two CSV files. Creates nothing
else and calls no model.

| Exit | When |
| --- | --- |
| 0 | the sample is complete and the report was printed |
| 1 | no sample; not every sampled page is done (the message says how many are); `gold/pages.json` cannot be read; `--run` names no saved run or two runs of one document; a file cannot be written |
| 2 | a usage error (argparse) |
