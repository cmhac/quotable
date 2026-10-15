# 001 - Rename the package and every code reference

Spec: `../spec.md` (Requirements 1 to 5, 8; Design steps 1 to 4 and 6). Depends on: spec 002
being merged into `main`, or this work being done on a branch that contains it (spec 002
changes `recheck.py`, `text.py` and their tests; doing both in parallel conflicts).

## Goal

After this task the package is `gridkey`, the code, tests, scripts and tooling no longer
mention the old name, and `just check` passes. Prose docs are task 002; the final searches are
task 003.

## Steps

1. Work on an implementation branch (not `main`) that contains spec 002's changes; confirm with
   `git log` that `Layer.lines` exists in `src/pdf_table_extract/text.py` before starting.
2. `git mv src/pdf_table_extract src/gridkey` (moves `py.typed` and `data/trigram_counts.json`
   with it).
3. In `src/`, `tests/` and `scripts/`, replace `pdf_table_extract` with `gridkey`: `import` and
   `from` lines, `:mod:` references, docstrings, and the two plain strings
   `resources.files("pdf_table_extract")` (`ngrams.py`) and the `OUTPUT` path in
   `scripts/build_trigrams.py`. Run `ruff format` afterwards, because import order may change
   (`gridkey` sorts differently from `pdf_table_extract`).
4. `pyproject.toml`: `name = "gridkey"`. Leave the description, version and dependencies alone.
5. Replace `PDF_TABLE_EXTRACT_LIVE_MODEL` with `GRIDKEY_LIVE_MODEL` in
   `tests/live/test_live_extraction.py` (docstring, variable, skip message), `justfile` and
   `.env.example`. Do not read or edit `.env`.
6. `pip install` text in `src/gridkey/pydantic_ai_client.py`'s docstring becomes
   `pip install gridkey[openai]`.
7. `uv lock`, then `uv sync --extra openai`. Check that `git diff uv.lock` shows only the
   project's own name changing (no dependency version changes). If other lines move, stop and
   report instead of committing a wider lock change.
8. Run `just check`.

## Acceptance

- `uv run python -c "import gridkey; print(gridkey.__name__)"` prints `gridkey`.
- `uv run python -c "import pdf_table_extract"` fails with `ModuleNotFoundError`.
- `just check` passes with the same test count as before the rename (101 with spec 002).
- `tests/test_ngrams.py` and `tests/test_textcheck.py` pass, which covers the
  `resources.files("gridkey")` path.
- `git status` shows the package files as renames, and `git diff` shows no change to behaviour:
  only names, imports, strings and the lock entry.
- No live model call is made (`just test-live` is not run).
