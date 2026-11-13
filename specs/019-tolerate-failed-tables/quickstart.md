# Quickstart: seeing each story work

How to check the feature by hand once it is built. Commands are run in the repo root. Contracts: [contracts/](contracts/). Nothing here calls a model unless it says so.

## 0. Prerequisites

```bash
just setup          # uv sync (brings PaddleOCR on a supported platform) and the git hook
just test           # offline suite, no network or key
```

## 1. Stories 1 to 4: a failed table does not cost the others

The offline tests drive the pipeline with scripted models and a generated three-table PDF.

```bash
just test tests/test_failed_tables.py tests/test_table_warnings.py tests/test_replay_failed_run.py
```

What to see:

- A call whose model answers `columns: []` twice for one table returns 3 tables, 2 sound and 1 failed, with exactly one `TableFailedWarning`.
- The 2 sound tables equal what the same call returns with the third table removed.
- `records()` on the failed table returns a list and warns once; the same call on a sound table does not warn.
- The replay test feeds the recorded bad answers (`tests/data/discovery_empty_columns/answer_*.json`) and a scripted retry, and gets tables back instead of an error.

By hand, in a Python session:

```python
import warnings

from quotable import TableFailedWarning, extract_tables

tables = extract_tables("report.pdf", "openai:<model>")  # a real call: costs money
for table in tables:
    print(table.label, table.failed, [p.message for p in table.problems])

warnings.simplefilter("error", TableFailedWarning)  # turn reading a failed table into an error
```

## 2. Story 5: OCR of every page without text

```bash
just test tests/ocr/test_empty_pages.py      # a fake engine: only the empty pages are OCR'd
just test-ocr                                # real PaddleOCR on the CPU, slow, no model cost
```

What to see:

- A 20-page PDF with text on 2 pages: the fake engine is asked for the other 18 and for no others, and `Table.ocr_pages` lists them.
- `ocr=False` on a PDF with more than 10% empty pages raises `TextLayerError` before any request, naming how many pages have no text.
- On Linux x86_64, macOS arm64 or Windows x86_64 with Python 3.11 to 3.13, `uv pip install .` brings PaddleOCR with no extra. Not checked on other platforms until someone does.

## 3. Story 6: what a cache entry says

```bash
just test tests/llm/test_cache_entries.py
python -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))['_quotable'], indent=1))" .quotable/cache/<key>.json
```

What to see: `stage`, `pages`, `model`, `written`, `run`; and for a retry, `retry_of` (the key of the first request) and `problem`. An entry written by the previous version is still read and has no `_quotable`.

## 4. The saved run and the review app

```bash
just review-demo    # the demo project now includes a run with one failed table
```

Open the runs list and that run's table screen. They open without error. Not checked in a real browser until someone does it.

## 5. The live check (SC-004): only with the owner's go-ahead

```bash
just test-live tests/live/test_live_discovery_columns.py
```

About 12 minutes and a few cents. The empty answers are rare (6 of 6 windows were fine on the old code), so a pass does not prove the fix; the replay in section 1 does.

## 6. Before finishing

```bash
just lint && just typecheck && just test
```
