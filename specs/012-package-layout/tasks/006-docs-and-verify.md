# 006 - Docs, leftover search and wheel check

Spec: `../spec.md` (Requirements 7, 9; Design step 6; Tests). Depends on: task 005.

## Goal

`AGENTS.md` and the scripts docs describe the new layout, no old path is left outside the history
specs, and a built wheel installs and runs.

## Steps

1. `AGENTS.md`:
   - File structure: replace the `src/quotable/` tree with the new `quotable/` tree (requirement 2,
     one line of description per module as the current tree has) and the new `tests/` tree
     (requirement 10), including `errors.py`, `storage.py`, `steps/__init__.py` as the place that
     lists the stage order, and `text/trigram_counts.json`.
   - Project state: add a short sentence that spec 012 is implemented (flat layout, four
     subpackages, tests mirror them; behaviour, API and cache keys unchanged; 1,442 tests).
     Mention that `recheck.py` now shares `render_png`. Fix existing module mentions in that
     paragraph (`merge.merge_tables` is `steps/merge.py`, `table.output_names`,
     `PydanticAIClient`, `.quotable/` code in `storage.py`, and so on).
   - Spec naming conventions: add that specs 001 to 011 refer to modules by the paths they had
     when written and are not rewritten (spec 012 moved them).
   - Commands table: no change unless a recipe's path changed.
     `CLAUDE.md` is a symlink; do not touch it.
2. `scripts/README.md` and `scripts/build_trigrams.py` already point at
   `quotable/text/trigram_counts.json` (tasks 001, 002); confirm.
3. Leftover search (requirement 9). Each of these finds nothing outside `specs/001`-`011`,
   `specs/012/spec.md` and `specs/012/tasks/`, `.git/`, `.venv/` and caches:
   `git grep -n "src/quotable"`, and `git grep -n -E "quotable\.(textcheck|ngrams|ocr_pages|ocr_cache|ocr_device|_paddle|_model|llm|models|schema|cache|costs|regions|cli)\b"`,
   plus `git grep -n -E "quotable\.(text|ocr|extract|discover|grounding|position|merge|extra_fields|recheck|layout)\b"`
   whose hits must all be the new paths (`quotable.text.layer`, `quotable.ocr.config`,
   `quotable.steps.merge`, ...), not the old flat ones. Also `git grep -n "from quotable import"`
   only imports names in `__all__`.
4. Wheel check:
   - `uv build` (writes `dist/`, which is git-ignored).
   - `unzip -l dist/quotable-0.1.0-py3-none-any.whl`: contains `quotable/__init__.py`,
     `quotable/__main__.py`, `quotable/errors.py`, `quotable/pipeline.py`, `quotable/storage.py`,
     `quotable/table.py`, `quotable/py.typed`, every file in `quotable/text/`, `ocr/`, `llm/`,
     `steps/` (including `text/trigram_counts.json`); contains no `tests/`, `scripts/`, `specs/`
     or `src/`.
   - In a fresh virtual environment outside the repository
     (`uv venv /tmp/q-whl && uv pip install --python /tmp/q-whl/bin/python dist/*.whl`), from
     `/tmp`: `python -c "import quotable; print(quotable.extract_tables)"`,
     `python -c "from quotable.text.quality import assess_text_layers"` (loads the trigram data
     path), and `quotable cost-report --dir /tmp/empty` (exit 0).
   - Delete `/tmp/q-whl`; leave `dist/` alone (git-ignored) or remove it.
5. `just setup` once more (the hook and editable install), then `just check`. Report the final
   test count. Do not commit unless the user asks.

## Acceptance

- All searches in step 3 come back clean, and the wheel checks in step 4 pass; paste the
  commands' results in the report.
- `just check` passes with 1,442 tests; sorted test names still match `/tmp/spec012-names.txt`.
- `AGENTS.md`'s tree matches `find quotable tests -maxdepth 2 -name "*.py"` (no module missing,
  no module listed that does not exist).
- No live or OCR test was run.
