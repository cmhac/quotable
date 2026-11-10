# Quickstart: checking the gold check

Prerequisites: `just setup` done. Nothing here calls a model or needs a key.

## 1. Offline tests (every change)

```console
$ just test tests/gold tests/review/test_gold_api.py tests/test_cli.py
$ just test                      # the whole offline suite
$ just lint && just typecheck
```

Expected: all pass. `tests/review/test_static_js.py` runs the node tests of `grid.js`, `textlayer.js`,
`clock.js` and `gold.js` when node is installed.

## 2. Score without a browser (the command)

The scorer works before any screen exists, so this is the first end-to-end check.

```console
$ uv run python -m tests.review_demo build/review-demo     # a project with runs and a typed sample
$ uv run quotable gold-report --dir build/review-demo/.quotable
```

Expected: the headline table (cell, row, page: correct, gold, extracted, recall, precision, accuracy), the
definitions, per-document and per-table lines, the column pairing of every page, and
`build/review-demo/.quotable/reports/gold_pages.csv` and `gold_cells.csv`. With the sample not finished,
exit code 1 and "N of M pages are done".

## 3. Gold folder is trackable, the rest is not

```console
$ cd build/review-demo && git init -q && git add -A -n | grep quotable
```

Expected: `.quotable/.gitignore` and `.quotable/gold/pages.json` are listed; nothing else under
`.quotable/` is.

## 4. The app, by hand (Chrome)

```console
$ just review-demo
```

The shell hook blocks long-running servers for the agent, so start this in your own terminal. Then:

1. Open `#/gold`. Choose the documents, a size of 6, draw. The page list shows 6 pages, the seed, "0 of 6".
2. Open a page. The editor is empty with 20 rows and one unnamed column. Nothing from the extraction is
   shown anywhere. The clock runs; switch to another window and it pauses.
3. Drag across words on the page: the cleaned text is copied and a "Copied" note appears over the toolbar's
   right end, not over the page. Turn on lock column, select words, and the selection moves down.
4. Press ⌘Z, ⌘D, ⌘R, Tab, Enter, F2, arrows with ⌘ and Shift, Delete. They behave as in the VRA app.
5. Rotate the page right; the text layer still lines up with the print.
6. Stop the server while the page is open and type. A red bar appears, page changes are refused, and
   when the server is back the page saves.
7. Mark every page done. Open `#/gold/score`: the report appears. With one page left not done, it
   shows "N of 6" and no figures.

## 5. Spot checks of the numbers

- Score a run against gold typed from the fixture's own truth file: every figure is 100%.
- Drop one row from the gold of a page: that page shows one extra row and is wrong.
- Rename the gold columns: the scores do not change, and the report shows the pairing by values.
