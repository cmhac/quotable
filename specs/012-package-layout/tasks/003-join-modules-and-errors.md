# 003 - Join the module pairs, gather the exceptions, split `pipeline.py`

Spec: `../spec.md` (Requirements 2 to 4, 7, 8; Design step 3). Depends on: task 002.

## Goal

After this task the module count is 21 plus the `__init__.py` files, the four public exceptions
live in `errors.py`, per-page extraction is `steps/extract.py`, and `just check` passes. No
function, class or constant changes its name or signature.

## Steps

Do the joins one at a time, running `just test` after each, so a failure points at one join.
Append the smaller file's content below the larger file's (merge the module docstrings into one,
combine the import blocks, drop imports that became internal to the joined module), then
`git rm` the smaller file.

1. `ngrams.py` into `text/quality.py`. The `resources.files(...)` call moves with it; its
   path (`"text", "trigram_counts.json"`) was fixed in task 002.
2. `ocr_pages.py` into `ocr/pages.py` (the OCR cache key and per-page files, then `ocr_pages`).
3. `ocr_device.py` into `ocr/paddle.py`.
4. `_model.py` into `llm/client.py`; in `tests/test_costs.py` the two
   `"quotable._model._price"` targets become `"quotable.llm.client._price"`, and `PydanticAIClient`
   imports change. The `on_usage` callback and everything else in `_model.py` stay as they are.
5. `validate_schema` from `schema.py` into `llm/answers.py`. `ExtractionError` is not moved here
   (step 8).
6. `regions.py` into `steps/layout.py`.
7. `cache.py` into `storage.py` (the `.quotable/` layout, `resolve_cache_dir`, `write_atomic`,
   then the cost log). `cache.py` and `costs.py` are both standard-library-only; keep
   `storage.py` free of `pydantic_ai` and `pymupdf` imports.
8. `errors.py`: new file holding `BudgetExceededError` (from `llm/client.py`),
   `ExtractionError` (from `schema.py`, which is now empty and removed), `TextLayerError` (from
   `text/quality.py`) and `OcrUnavailableError` (from `ocr/config.py`, still a subclass of
   `TextLayerError`). The modules that raise or catch them import from `quotable.errors`;
   `quotable/__init__.py` takes them from there too, with `__all__` unchanged. Check for an
   import cycle: `errors.py` imports nothing from the package.
9. `cli.py` into `__main__.py`: `__main__.py` becomes the content of `cli.py` plus
   `if __name__ == "__main__": raise SystemExit(main())` (the old `__main__.py` raised on import,
   which would break the `quotable.__main__:main` script entry). `pyproject.toml`:
   `[project.scripts] quotable = "quotable.__main__:main"`. `tests/test_cli.py` imports and its
   subprocess or `-m` calls follow.
10. `pipeline.py` split: move the per-page extraction code to a new `steps/extract.py`:
    `DPI`, `MAX_PROBLEMS`, `MAX_PREVIOUS_OUTPUT_CHARS`, `EXTRACT_PROMPT`, `MULTI_TABLE_SENTENCE`,
    `validate_rows`, `column_structure`, `retry_prompt`, `render_png`, `page_schema`,
    `other_tables_text`, `extract_page`. `pipeline.py` keeps `MAX_CONCURRENT_REQUESTS`,
    `usable_layers`, `table_page_layers`, `printed_fields`, `resolve_extra_fields`,
    `attach_extra_fields`, `run_pipeline`, `_ocr_config`, `extract_tables_async`,
    `extract_tables`, and imports the rest from `quotable.steps.extract`. Update the pipeline
    module docstring (its stage list stays; it refers to `quotable.steps.*` modules) and the
    imports in `tests/test_tables.py` (`EXTRACT_PROMPT`, `MULTI_TABLE_SENTENCE`).
11. `tests/test_merge_checks.py`: the import check now also names `"quotable.steps.extract"`
    (task 002 could only name `quotable.pipeline`). Show it fails for both, once each, by
    temporarily adding an import from each to `quotable/steps/merge.py`; remove the lines.
12. `uv run ruff check --fix .`, `uv run ruff format .`, `just check`. Do not commit unless the
    user asks.

## Acceptance

- `find quotable -name "*.py" ! -name "__init__.py" | wc -l` prints 20 (`__main__.py`,
  `errors.py`, `pipeline.py`, `storage.py`, `table.py`, and 15 in the subpackages); with
  `quotable/__init__.py` that is the spec's 21 modules, plus one `__init__.py` per subpackage.
- `from quotable import ...` gives the same names as at `a5713ba` (`__all__` identical, compare
  with `git diff a5713ba -- quotable/__init__.py`, which shows only import lines).
- `issubclass(quotable.OcrUnavailableError, quotable.TextLayerError)` is true.
- The hard-coded request keys in `tests/test_discover.py` and `tests/test_costs.py` pass
  unchanged (cache keys did not move).
- `uv run quotable cost-report --dir /tmp/empty` and `uv run python -m quotable cost-report --dir
/tmp/empty` both print the "no records" report and exit 0.
- `just check` passes with the baseline count; sorted test names match
  `/tmp/spec012-names.txt`.
- For each join, `git diff --stat -M a5713ba -- <joined module>` shows the larger file as a
  rename (similarity at least 50%) or report the exceptions.
- No live or OCR test was run.
