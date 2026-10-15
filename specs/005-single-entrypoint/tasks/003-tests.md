# 003 - Tests

Spec: `../spec.md` (Tests; Requirement 6). Depends on: task 002.

## Goal

The offline suite passes against the new API, with the new behaviour covered. No network, no API
key.

## Steps

1. Move the existing tests to the internal function: wherever a test calls
   `extract_tables(pdf, fake_client, ...)` (`test_extract.py`, `test_tables.py`,
   `test_recheck.py`, `test_senate_tables.py`, and any other file `grep` finds), import
   `run_pipeline` from `gridkey.extract` and call that instead. Fix `CachedClient` imports
   (`gridkey.llm`) in `test_tables.py` and `test_llm.py`. Same test count, same assertions.
2. `tests/test_pydantic_ai_client.py` -> `tests/test_model.py`: import from `gridkey._model`,
   drop the `importorskip`. Add: two instance models with different names have different
   identities; a string model keeps the old identity format.
3. New `tests/test_entrypoint.py`:
   - calling `extract_tables(pdf)` without `model` raises `TypeError`, also with
     `GRIDKEY_MODEL` and `OPENAI_MODEL` set (use `monkeypatch.setenv`);
   - a pydantic-ai `FunctionModel` (or the repo's recorded-rows fake wrapped as one) passed as
     `model` runs the whole pipeline on a sample PDF through the public function and returns the
     same tables as `run_pipeline` with the fake client;
   - `cache_dir`: a second identical run makes no model request;
   - `max_requests` raises `BudgetExceededError` with and without `cache_dir`;
   - `str` and `Path` both work for `pdf`;
   - `gridkey.__all__` equals the list in task 002 step 4, and `from gridkey import CachedClient`
     fails.
4. `test_llm.py`: add a `cache_dir=None` case (nothing written, cap still enforced).
5. `just test` and `just lint`, `just typecheck`.

## Done when

`just test` is green and the test count equals the old count plus the new tests.
