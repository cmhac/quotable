# 009 - A demo project for working on the app

Spec: `../spec.md` (all screens). Depends on: task 003. Tasks 010 to 013 use it for their
browser checks.

## Goal

`just review-demo` builds a `.quotable/` folder with realistic runs, offline and free, and
starts the app on it. It is for people working on the app, not for users.

## Steps

1. `tests/review_demo.py` (a module, like `tests/score_merge.py`): in a folder given on the
   command line (default `build/review-demo/`, git-ignored), run `extract_tables` with fake
   models (pydantic-ai `FunctionModel`, answers taken from fixture truth files) on:
   - a document with two tables, one sharing a page with the other (spec 004);
   - a document with extra fields carried forward (spec 010);
   - a merged table (spec 007);
   - a large table of several thousand rows (generated with `tests/synthetic.py`);
   - a document run twice, the second time with one answer changed, to make a stale verdict;
   - an OCR'd page, using the fake OCR engine of `tests/fake_ocr.py`.
     Some answers are wrong on purpose so every status appears. Add a few verdicts and cost
     records (one run free, one with an unknown price). Finally move one PDF away so the
     "missing" alert shows.
2. `justfile`: `review-demo` runs the module, then `uv run quotable review --dir
build/review-demo/.quotable`. Add `build/` to `.gitignore` if it is not there.
3. A test that the module builds the folder in a temporary path and that `list_runs` sees every
   run (so the demo cannot rot).
4. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

`just review-demo` opens the app on runs that show every screen, status, highlight and alert
of the spec, with no network and no API key.
