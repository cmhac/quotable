# 012 - Flat layout and subpackages

Status: approved; open questions resolved; tasks written (`tasks/001` to `006`), awaiting approval.

## Summary

Move the package from `src/quotable/` to `quotable/` at the repository root, and replace the 27
flat modules with four subpackages (`text/`, `ocr/`, `llm/`, `steps/`) and a few top-level
modules, merging the pairs of modules that only exist to serve each other. `tests/` mirrors the
same subpackages. Behaviour, the public API, prompts and cache keys do not change.

## Motivation

The user finds the package hard to navigate: 27 modules side by side (4,705 lines on `main` at
`a5713ba`), several of them small helpers of one other module (`ngrams.py`, 36 lines, used only
by `textcheck.py`; `schema.py`, 23 lines; `ocr_cache.py` and `ocr_device.py`, used only by
`ocr_pages.py` and `_paddle.py`; `regions.py`), and the `src/` level adds a folder that holds
only one other folder.

## Requirements

1. **Flat layout.** The package lives at `quotable/` in the repository root; `src/` is removed.
   `pyproject.toml` gets
   ```toml
   [tool.uv.build-backend]
   module-root = ""
   ```
   (the uv build backend's documented setting for a module outside `src/`). Distribution and
   import name stay `quotable`.
2. **New structure.** Every current module moves as below. "+" means the files are joined into
   one module; nothing else is rewritten.

   ```
   quotable/
   ├── __init__.py          unchanged exports
   ├── __main__.py          __main__.py + cli.py (the `quotable` command)
   ├── errors.py            the four public exceptions: BudgetExceededError (llm.py),
   │                        ExtractionError (schema.py), TextLayerError (textcheck.py),
   │                        OcrUnavailableError (ocr.py)
   ├── pipeline.py          extract.py minus per-page extraction: extract_tables,
   │                        extract_tables_async, run_pipeline, usable_layers,
   │                        table_page_layers, the extra-field orchestration
   ├── table.py             table.py (results: Table, Row, Flag, ground_document, records)
   ├── storage.py           cache.py + costs.py (the .quotable/ folder: cache and cost log)
   ├── py.typed
   ├── text/                the PDF's own text layer
   │   ├── layer.py         text.py
   │   ├── quality.py       textcheck.py + ngrams.py
   │   └── trigram_counts.json   (was data/trigram_counts.json)
   ├── ocr/                 the fallback for a bad text layer
   │   ├── config.py        ocr.py (OcrConfig, OcrWord, OcrEngine, words_to_layer)
   │   ├── pages.py         ocr_pages.py + ocr_cache.py
   │   └── paddle.py        _paddle.py + ocr_device.py
   ├── llm/                 talking to the model
   │   ├── client.py        llm.py + _model.py (Request, CachedClient, PydanticAIClient)
   │   └── answers.py       models.py + validate_schema from schema.py
   └── steps/               the pipeline's stages; its __init__.py lists their order
       ├── discover.py      discover.py
       ├── layout.py        layout.py + regions.py
       ├── extract.py       per-page extraction from extract.py (prompts, validate_rows,
       │                    extract_page, render_png, DPI)
       ├── grounding.py     grounding.py
       ├── position.py      position.py
       ├── merge.py         merge.py
       ├── extra_fields.py  extra_fields.py
       └── recheck.py       recheck.py
   ```

   21 modules instead of 27, plus one `__init__.py` per subpackage. Subpackage `__init__.py`
   files re-export nothing, so each name has one import path; `text/`, `ocr/` and `llm/` get a
   one-line docstring. `steps/__init__.py` has a docstring that lists the stages in the order
   `run_pipeline` runs them, one line each, with what runs concurrently inside it (the modules
   are not numbered: a name cannot start with a digit, the order is not a straight line, and
   `run_pipeline` is the one source of truth for it):
   1. `discover`: windows of pages, one after the other (each gets the tables found so far).
   2. `layout`: page headers and a table's band of a shared page; no model request.
   3. `extract`: one request per (table, page), at most 4 at a time.
   4. `grounding`, then `position` (both through `ground_document` in `table.py`); no request.
   5. `extra_fields`, only when asked for: field recheck, then second looks (at most 4 at a time).
   6. `merge`; no request.
   7. `recheck`: one request per page, all at once.

   The text-layer check and OCR run before step 1 and live in `text/` and `ocr/`. The leading
   underscore of `_model.py` and `_paddle.py` goes: inside the package everything except
   `quotable/__init__.py`'s exports is internal (`AGENTS.md` says this; the README does not
   discuss internals and needs no change for it).

3. **Public API unchanged.** `from quotable import ...` gives exactly the names it gives today
   (`__all__` unchanged), and `quotable cost-report` / `python -m quotable cost-report` work as
   before. `[project.scripts]` becomes `quotable = "quotable.__main__:main"`. The exceptions'
   `__module__` changes to `quotable.errors`, which shows in tracebacks only; code that catches
   `quotable.TextLayerError` and the others is unaffected, and `OcrUnavailableError` stays a
   subclass of `TextLayerError`.
4. **No renames inside modules.** Functions, classes, constants and their signatures keep their
   names. The merged pairs were checked for clashing top-level names on `a5713ba`: there are
   none. Pydantic classes keep their names and fields, so `model_json_schema()` and with it
   every model-answer cache key is unchanged; the OCR cache key does not involve module paths
   either. Existing `.quotable/` caches stay valid.
5. **One rendering setting.** `recheck.py` renders pages with its own literal `dpi=150`, a copy
   of `extract.py`'s `DPI`. It uses `render_png` from `steps/extract.py` instead. The image
   bytes, and so the cache keys, are the same; the point is that the two cannot drift apart.
   This is the only code change beyond moving and joining files.
6. **Logger names unchanged:** `quotable` and `quotable.ocr` (now also the OCR subpackage's
   name).
7. **Every reference is updated:** imports and docstring references (`:mod:` and plain
   mentions such as `quotable.merge`) in `quotable/`, `tests/` and `scripts/`; the string
   targets `"quotable._model._price"` in `tests/test_costs.py` (becomes
   `"quotable.llm.client._price"`); `resources.files(...)` for the trigram counts; the output
   path in `scripts/build_trigrams.py`; `scripts/README.md`; the file tree and module mentions
   in `AGENTS.md`. `tests/test_merge_checks.py` asserts `"quotable.extract" not in {...}`
   (merge must not import the pipeline): it becomes a check for `"quotable.pipeline"` and
   `"quotable.steps.extract"`, and is shown to fail once by temporarily adding such an import,
   because a stale module name would pass silently.
8. **History follows the files.** Moves use `git mv`. For a joined pair, the larger file is
   moved with `git mv` in a commit of its own and the smaller one is appended in the next
   commit, so `git log --follow` keeps working for the larger one. Specs 001 to 011 keep the
   paths they were written with.
9. **No leftovers.** After the change, a search for `src/quotable` and for the old module paths
   (`quotable.extract` as the pipeline, `quotable.textcheck`, `quotable.ngrams`,
   `quotable.ocr_pages`, `quotable.ocr_cache`, `quotable.ocr_device`, `quotable._paddle`,
   `quotable._model`, `quotable.llm`, `quotable.models`, `quotable.schema`, `quotable.cache`,
   `quotable.costs`, `quotable.regions`, `quotable.text` as a module, `quotable.cli`) finds
   nothing outside `specs/001`-`011`, `.git/`, `.venv/` and caches. The leftover `src/` folder
   (only git-ignored `__pycache__`) is deleted, and `just setup` reinstalls the editable
   package so the environment no longer points at `src/`.
10. **Tests mirror the package** (user's decision). Test files keep their names and move with
    `git mv`; helpers, fixtures and data stay at the top of `tests/`:

    ```
    tests/
    ├── conftest.py, table_builder.py, fixture_tables.py, fake_ocr.py, fake_paddle.py,
    │   extra_fields_model.py, extra_fields_live.py, synthetic*.py, score_*.py, data/   (stay)
    ├── test_entrypoint, test_extract, test_tables, test_senate_tables, test_ocr_pipeline,
    │   test_merge_pipeline, test_extra_fields_pipeline, test_extra_fields_live_prompts,
    │   test_extra_fields_output, test_frames, test_merged_field        pipeline.py, table.py
    ├── test_cache, test_costs, test_cli                                storage.py, __main__.py
    ├── test_fixture_tables, test_synthetic, test_score_extra_fields     the fixture and scorers
    ├── text/    test_text, test_textcheck, test_textcheck_calibration, test_ngrams
    ├── ocr/     test_ocr, test_ocr_cache, test_ocr_device, test_ocr_pages,
    │            test_paddle_adapter, test_real_ocr   (the opt-in real-OCR test, already here)
    ├── llm/     test_llm, test_model
    ├── steps/   test_discover, test_layout, test_regions, test_grounding, test_position,
    │            test_merge, test_merge_checks, test_extra_fields, test_extra_fields_recheck,
    │            test_recheck
    └── live/    (stays; imports updated)
    ```

    Each new folder has an empty `__init__.py`, like `tests/live/`. Two tests find the data
    folder with `Path(__file__).parent / "data"` (`test_extra_fields.py`,
    `test_textcheck_calibration.py`); once they move that points at the wrong folder, so they
    use `DATA` from `tests/conftest.py` instead. Tests that import names from other test
    modules (`tests.test_entrypoint`, `tests.test_senate_tables`, `tests.test_merge_checks`)
    keep doing so with the new paths; untangling that is out of scope. The test count and the
    set of test names do not change.

## Design

Order, so each state can be checked on its own:

1. `git mv src/quotable quotable`, delete `src/`, add `module-root = ""`, fix the trigram path
   in `scripts/build_trigrams.py`, `just setup`, `just check`. Nothing else changes yet.
2. Create the subpackages and move the unjoined modules (`git mv`), updating imports.
3. Join the pairs (requirement 8), move the exceptions into `errors.py`, split `extract.py`
   into `pipeline.py` and `steps/extract.py`, fold `cli.py` into `__main__.py`.
4. Requirement 5 (the shared `render_png`).
5. Mirror the subpackages in `tests/` (requirement 10).
6. Docs (`AGENTS.md`, `scripts/README.md`) and the leftover searches; `uv build` and a check of
   the wheel's contents.

Ruff's import sorting changes with the new paths; `ruff check --fix` and `ruff format` run after
each step.

## Risks

- **The working tree is importable without installing.** With `src/` gone, `import quotable`
  from the repository root finds the folder directly, so the tests can pass while the wheel is
  broken (a missing `trigram_counts.json` or subpackage). The wheel check in Tests covers it.
- **Stale editable install.** The `.pth` file in `.venv` points at `src/` until `uv sync`
  rebuilds it; outside the repository root `import quotable` then fails. `just setup` in step 1.
- **Hidden string paths.** Module paths in strings (monkeypatch targets, the import check in
  `test_merge_checks.py`, `resources.files`) are not caught by ty. The suite and the leftover
  search in requirement 9 cover them.
- **Conflicts.** The change touches every module and most tests; nothing else should be in
  flight on another branch while it is implemented.

## Alternatives considered

- **Only drop `src/`, keep 27 flat modules.** Rejected: it does not address the main complaint.
- **Fewer, larger modules without subfolders** (for example one `ocr.py` of about 730 lines).
  Rejected: long files are as hard to navigate as many small ones.
- **Re-export from each subpackage's `__init__.py`.** Rejected: two import paths per name.
- **Join `grounding.py` and `position.py`** (480 lines). Rejected: they are separate pipeline
  steps with separate tests.

## Out of scope

- Behaviour, defaults, prompts, thresholds, public names, cache layout, dependencies.
- Splitting or rewriting the logic inside modules (for example `extra_fields.py`, 402 lines,
  or `merge.py`), beyond the `extract.py` split and requirement 5.
- Rewriting or splitting test files, or removing the imports between test modules; tests only
  move.
- Running the pipeline's stages concurrently where they now run one after the other (for
  example the extra-fields stage alongside extraction), or capping the concurrent requests in
  `recheck.py` (it has no semaphore, unlike extract and second looks). Both change behaviour;
  note for a later spec.

## Tests

All offline; no live or OCR test is run.

- `just check` passes with the same test count as `main` at `a5713ba` (1,442), changed only in
  imports, string module paths, the two `DATA` lookups and the test directory layout. The sorted
  list of test names (`uv run pytest --collect-only -q`, file paths stripped) is identical
  before and after; `-m live` and `-m ocr` collect the same tests as before (131 deselected).
- The hard-coded request keys in `tests/test_discover.py` and `tests/test_costs.py` still match,
  which shows the cache keys did not change.
- `uv build`, then the wheel's file list: `quotable/__init__.py`, every subpackage,
  `quotable/text/trigram_counts.json` and `quotable/py.typed` are present; `tests/`, `scripts/`
  and `specs/` are not. A fresh virtual environment with the wheel installed runs
  `python -c "import quotable"` and `quotable cost-report --dir <empty dir>` from outside the
  repository.

## Decisions (were open questions)

1. **Tests folder:** mirror the subpackages (requirement 10), not keep it flat.
2. **Grouping:** as in requirement 2, including `storage.py`, `errors.py` and `layout`,
   `grounding`, `position` under `steps/`.
3. **Order of the stages:** listed in `steps/__init__.py`, not by numbering the files.
