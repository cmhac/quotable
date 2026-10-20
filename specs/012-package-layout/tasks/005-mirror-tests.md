# 005 - Mirror the subpackages in `tests/`

Spec: `../spec.md` (Requirement 10; Design step 5). Depends on: task 004.

## Goal

Test files sit in folders that match the package, nothing else about them changes, and
`just check` passes with the same tests.

## Steps

1. Create `tests/text/`, `tests/llm/` and `tests/steps/`, each with an empty `__init__.py`
   (`tests/ocr/` and `tests/live/` already have one).
2. `git mv` (names unchanged):
   - `tests/text/`: `test_text.py`, `test_textcheck.py`, `test_textcheck_calibration.py`,
     `test_ngrams.py`
   - `tests/ocr/`: `test_ocr.py`, `test_ocr_cache.py`, `test_ocr_device.py`, `test_ocr_pages.py`,
     `test_paddle_adapter.py` (next to the existing `test_real_ocr.py`)
   - `tests/llm/`: `test_llm.py`, `test_model.py`
   - `tests/steps/`: `test_discover.py`, `test_layout.py`, `test_regions.py`,
     `test_grounding.py`, `test_position.py`, `test_merge.py`, `test_merge_checks.py`,
     `test_extra_fields.py`, `test_extra_fields_recheck.py`, `test_recheck.py`

   Everything else stays at the top of `tests/` (the pipeline, table, storage and CLI tests, the
   fixture and scorer tests, and all helper modules and `data/`).

3. Fix the imports between test modules that moved (`tests.test_merge_checks` from
   `test_merge.py` becomes `tests.steps.test_merge_checks`; `tests.test_entrypoint`,
   `tests.test_senate_tables` stay where they are, but check each importer). Helper imports
   (`tests.conftest`, `tests.table_builder`, `tests.fixture_tables`, `tests.fake_ocr`, ...) do
   not change.
4. Two tests locate the data folder with `Path(__file__).parent / "data"`:
   `tests/steps/test_extra_fields.py` (three places: the Senate PDF, `SYNTHETIC`, and the
   `.rows.json` read) and `tests/text/test_textcheck_calibration.py` (`DATA`). Replace them with
   `DATA` from `tests/conftest.py` (`SYNTHETIC = DATA / "synthetic"`), and check nothing else
   in the moved files uses `__file__` (`grep -rn "__file__" tests`; `tests/live/` and
   `tests/synthetic_cases.py` do not move and stay as they are).
5. `justfile` and docstrings that name test paths (`just test-live` comment, `tests/data/README.md`,
   test docstrings): update any that point at a moved file.
6. `uv run ruff check --fix .`, `uv run ruff format .`, `just check`. Do not commit unless the
   user asks.

## Acceptance

- `ls tests/*.py | wc -l` is the helpers plus the top-level tests listed in the spec; the
  moved files are only in subfolders.
- `uv run pytest --collect-only -q | sed 's|^[^:]*::||' | sort` is identical to
  `/tmp/spec012-names.txt`, and the count is 1,442 with 131 deselected.
- `uv run pytest -m ocr --collect-only -q` and `uv run pytest -m live --collect-only -q` list
  the same tests as before the task (run the same commands on `a5713ba` via `git stash` or a
  worktree if the earlier numbers were not recorded). Neither is run.
- `grep -rn "Path(__file__).parent / \"data\"" tests` finds nothing.
- `just check` passes.
