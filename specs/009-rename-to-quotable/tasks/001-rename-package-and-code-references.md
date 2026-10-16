# 001 - Rename the package and every code reference

Spec: `../spec.md` (Requirements 1 to 5 and 8; Design steps 1 to 5 and 7). Depends on: every spec
ahead of this one being merged into `main`.

## Goal

After this task the package is `quotable`, `src/`, `tests/`, `scripts/` and the tooling files no
longer mention `gridkey`, and `just check` passes. Prose docs are task 002; the final searches are
task 003.

## Steps

1. `git checkout main`, update it, and confirm `git status` is clean. Create
   `spec/009-rename-to-quotable-impl` from it. Re-run the reference count from the spec
   (`git grep -i -o gridkey -- . ':!specs' | wc -l`; 282 occurrences in 69 files at `44ce9a1`) and
   note any change. Record the offline test count (969 at `44ce9a1`) as the baseline.
2. `git mv src/gridkey src/quotable` (moves `py.typed` and `data/trigram_counts.json` with it).
   Then remove the leftover `src/gridkey/` folder: it holds only git-ignored `__pycache__` files,
   and left in place it lets `import gridkey` succeed as an empty namespace package.
3. In `src/`, `tests/` and `scripts/`, replace `gridkey` with `quotable`: `import` and `from`
   lines, `:mod:`/`:class:`/`:func:` references, docstrings and comments, and the plain strings:
   - `resources.files("gridkey")` (`ngrams.py`) and `OUTPUT` in `scripts/build_trigrams.py`;
   - `logging.getLogger("gridkey.ocr")` in `ocr.py`, `_paddle.py`, `ocr_pages.py`, and the
     `logger="gridkey.ocr"` in `tests/test_paddle_adapter.py`;
   - `DEFAULT_DIR_NAME = ".gridkey"` and the messages in `cache.py`; the messages in `ocr.py`,
     `textcheck.py`, `_paddle.py` (`INSTALL`, the `ocr-core` text) and `ocr_device.py`;
   - test names and assertions: `test_cache.py` (`.gridkey` paths and test names),
     `test_ocr_pipeline.py`, `test_ocr_device.py`, `test_paddle_adapter.py`, `test_frames.py`,
     `conftest.py` and the rest of the list in the spec.
   Use a scripted replace if you like, but read the whole diff afterwards: it is how you find
   names that were split across lines or built from parts.
4. `tests/test_merge_checks.py`: the assertion `"gridkey.extract" not in {...}` becomes
   `"quotable.extract"`. Then prove it still tests something: temporarily add
   `from quotable.extract import run_pipeline  # noqa` to `src/quotable/merge.py`, run
   `just test -k test_the_module_imports_nothing_from_extract`, see it fail, and remove the line.
   Report that you did.
5. `pyproject.toml`: `name = "quotable"` and the comment that says "gridkey is installed into
   its own environment". Leave the description, version, dependencies and extras alone.
6. Rename the live-test variable `GRIDKEY_LIVE_TEST_MODEL` to `QUOTABLE_LIVE_TEST_MODEL` in
   `tests/live/test_live_extraction.py`, `tests/live/test_live_merge.py` (docstring, variable,
   skip message), `tests/test_entrypoint.py` (the list of names the library must not read becomes
   `QUOTABLE_MODEL`, `QUOTABLE_LIVE_TEST_MODEL`, `OPENAI_MODEL`, `MODEL`), `justfile` and
   `.env.example`. Do not read or edit `.env`.
7. `.gitignore`: the comment and the line become `.quotable/`.
8. `uv lock`, then `just setup`. Check `git diff uv.lock`: only the project's own
   `[[package]] name = "gridkey"` entry changes. If anything else moves, stop and report instead
   of keeping a wider lock change.
9. `uv run ruff check --fix .` and `uv run ruff format .` (import order may change), then
   `just check`. Do not commit unless the user asks.

## Acceptance

- `uv run python -c "import quotable; print(quotable.__name__)"` prints `quotable`.
- `uv run python -c "import gridkey"` fails with `ModuleNotFoundError`.
- `just check` passes with the baseline test count from step 1.
- `tests/test_ngrams.py`, `tests/test_textcheck.py` (trigram data) and `tests/test_cache.py`
  (default folder `.quotable/`) pass.
- `git status` shows the package files as renames; `git diff` shows only names, imports, strings,
  test names and the lock entry, with no change in behaviour.
- No live or OCR test was run (`just test-live` and `just test-ocr` are not run).
