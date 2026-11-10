# Contract: gold files

Version 1. Plain JSON and CSV, readable without quotable. A reader ignores keys it does not know.

## `.quotable/gold/sample.json`

```json
{
  "v": 1,
  "seed": 20261110,
  "size": 20,
  "drawn": "2026-11-10T21:15:00Z",
  "documents": [{"sha256": "<64 hex>", "name": "report.pdf", "pages": 120}],
  "pages": [{"sha256": "<64 hex>", "page": 7}]
}
```

Replaced whole and atomically on each draw.

## `.quotable/gold/pages.json`

```json
{
  "v": 1,
  "pages": {
    "<64 hex>:7": {
      "tables": [
        {"columns": ["Recipient", "Amount"], "rows": [["Town of Sandwich", "1,650,000"]]}
      ],
      "done": true,
      "seconds": 131.4,
      "updated": "2026-11-10T21:20:05Z"
    }
  }
}
```

- Keys sorted, indent 1, a final newline, so a commit's diff shows only the pages that changed.
- Replaced whole and atomically on each save, under a lock.
- A page with `done: true` and `tables: []` says the page has no table.
- A file that is not version 1 JSON is never replaced; the app and command say which file and why.

## `.quotable/.gitignore`

Exactly `*\n` becomes `*\n!.gitignore\n!gold/\n!gold/**\n` the first time the gold check writes gold. A
missing file gets that content. Any other content is left alone and the app and command report it.
Nothing is committed for the user.

## Report CSV files (written by `gold-report` and offered for download in the app)

`gold_pages.csv`, one line per counted page:

`document, page, correct, gold_tables, extracted_tables, gold_rows, extracted_rows, matched_rows, rows, rows_correct, cells, gold_cells, extracted_cells, cells_correct, missed, extra, exact, normal, fuzzy`

`gold_cells.csv`, one line per cell that is not an exact match:

`document, page, table, column, gold_row, gold, extracted, best`

`document` is the file name, `table` is the extracted table's label (`(no match)` for a gold table with
no partner), `gold_row` is the 1-based row in the gold table (empty for an extra row), and `best` is
`normal`, `fuzzy` or `none`. Quoting follows RFC 4180; text starting with `=`, `+`, `-` or `@` is
prefixed with `'` so a spreadsheet does not run it as a formula.
