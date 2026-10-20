# 002 - Create the subpackages and move the modules

Spec: `../spec.md` (Requirements 2, 4, 6, 7, 8; Design step 2). Depends on: task 001.

## Goal

After this task every module sits at its final path and keeps its content, imports are updated and
`just check` passes. For each pair that will be joined (task 003), the **larger** file is moved
here to the joined module's final name; the smaller one stays where it is until task 003, so
`git log --follow` keeps working for the larger one.

## Steps

1. `git mv` each file below (create the folders first). Contents are not edited yet beyond
   imports and strings.

   | From                                                                                      | To                         |
   | ----------------------------------------------------------------------------------------- | -------------------------- |
   | `text.py`                                                                                 | `text/layer.py`            |
   | `textcheck.py` (173 lines; `ngrams.py` joins it in 003)                                   | `text/quality.py`          |
   | `data/trigram_counts.json`                                                                | `text/trigram_counts.json` |
   | `ocr.py`                                                                                  | `ocr/config.py`            |
   | `ocr_cache.py` (103; `ocr_pages.py` joins it)                                             | `ocr/pages.py`             |
   | `_paddle.py` (261; `ocr_device.py` joins it)                                              | `ocr/paddle.py`            |
   | `llm.py` (117; `_model.py` joins it)                                                      | `llm/client.py`            |
   | `models.py` (129; `validate_schema` from `schema.py` joins it)                            | `llm/answers.py`           |
   | `discover.py`, `grounding.py`, `position.py`, `merge.py`, `extra_fields.py`, `recheck.py` | `steps/` (same names)      |
   | `layout.py` (127; `regions.py` joins it)                                                  | `steps/layout.py`          |
   | `costs.py` (299; `cache.py` joins it)                                                     | `storage.py`               |
   | `extract.py` (515; per-page extraction is split out in 003)                               | `pipeline.py`              |
   | `cli.py` (45; `__main__.py`'s 5 lines fold into it)                                       | stays until 003            |

   Left in place for now: `ngrams.py`, `ocr_pages.py`, `ocr_device.py`, `_model.py`,
   `schema.py`, `regions.py`, `cache.py`, `cli.py`, `__main__.py`, `table.py`, `__init__.py`.
   Add `text/__init__.py`, `ocr/__init__.py`, `llm/__init__.py` (one-line docstring each) and
   `steps/__init__.py`.

2. `steps/__init__.py` docstring: the seven-line ordered list from requirement 2 of the spec
   (stage, what runs concurrently inside it), and the sentence that the text-layer check and OCR
   run before step 1.
3. Update every `import` / `from quotable...` line in `quotable/`, `tests/` and `scripts/` to the
   new paths. For the files still in place, imports of moved modules change; imports of the
   moved-but-unjoined smaller modules keep their old path until task 003. Docstring and comment
   mentions (`:mod:`, plain `quotable.merge` and similar, for example in `pipeline.py` and
   `discover.py`) are updated too. Then the strings:
   - `ngrams.py` line 35, `resources.files("quotable").joinpath("data", "trigram_counts.json")`:
     the data file is now `quotable/text/trigram_counts.json`, so it becomes
     `.joinpath("text", "trigram_counts.json")`; check with
     `uv run pytest tests/test_ngrams.py tests/test_textcheck.py`;
   - `scripts/build_trigrams.py` `OUTPUT` and the docstring: `quotable/text/trigram_counts.json`;
     `scripts/README.md` likewise;
   - `"quotable._model._price"` in `tests/test_costs.py` (two places): the `_model` module is
     still in place, so this changes in task 003 and stays untouched here;
   - `tests/test_merge_checks.py`: the module name in `test_the_module_imports_nothing_from_extract`
     becomes `"quotable.pipeline"` and `"quotable.steps.extract"`; the second does not exist
     until 003, so for now check for `"quotable.pipeline"` only and note it.
   - logger names stay `quotable` and `quotable.ocr`.
4. `uv run ruff check --fix .`, `uv run ruff format .`, `just check`. Do not commit unless the
   user asks.

## Acceptance

- Every file in the table is where it says, and `git status` shows renames (not delete plus
  add) for them.
- `just check` passes with the baseline count; the sorted test names match
  `/tmp/spec012-names.txt`.
- `git grep -n "quotable\.\(text\|textcheck\|ocr_pages\|ocr_cache\|ocr_device\|_paddle\|llm\|models\|costs\|extract\|discover\|grounding\|position\|merge\|extra_fields\|recheck\|layout\)\b" -- quotable tests scripts`
  finds only the new subpackage paths (`quotable.text.layer`, `quotable.steps.merge`, ...) and
  the names of modules not yet joined; none of the old flat paths for moved modules.
- `tests/test_merge_checks.py`'s import check is shown to fail once: temporarily add
  `from quotable.pipeline import run_pipeline  # noqa` to `quotable/steps/merge.py`, run
  `just test -k test_the_module_imports_nothing_from_extract`, see it fail, remove the line.
  Report that you did.
- `uv run python -c "from quotable.steps import merge"` works from a directory outside the
  repository (the editable install sees the subpackage).
- No live or OCR test was run.
