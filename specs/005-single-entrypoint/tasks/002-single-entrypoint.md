# 002 - The single entrypoint

Spec: `../spec.md` (Requirements 1 to 6, 8, 11; Design / Code). Depends on: task 001.

## Goal

`extract_tables(pdf, model, *, cache_dir, max_requests, model_settings, discovery_pages,
recheck)` and `extract_tables_async` are the only public way in; the old client classes are
internal.

## Steps

1. `git mv src/gridkey/pydantic_ai_client.py src/gridkey/_model.py`. Import `pydantic_ai` at the
   top of the module (no deferred import, no `noqa: PLC0415`). Update the docstring (no
   `pip install gridkey[openai]`). Identity for a model instance becomes
   `"<system>:<model_name>"` (check the attribute names on pydantic-ai's `Model` in 2.54.0
   before using them); for a string it stays the string. Format stays
   `"<name>:<sorted settings json>"`.
2. `llm.py`: `CachedClient.cache_dir` becomes `Path | None`; `None` skips reading and writing the
   disk cache, the `max_requests` cap still applies. Update the module docstring.
3. `extract.py`:
   - Rename the current `extract_tables_async` to `run_pipeline(pdf, client, *, discovery_pages,
     recheck)`; it takes an `LLMClient` and stays internal (the offline tests call it).
   - New `extract_tables_async(pdf: str | Path, model, *, cache_dir=None, max_requests=None,
     model_settings=None, discovery_pages=DISCOVERY_PAGES, recheck=True)`: builds
     `CachedClient(PydanticAIClient(model, model_settings=...), cache_dir, max_requests)` and
     calls `run_pipeline`. `model` has no default and is not read from the environment.
     Type `model` as pydantic-ai's `Model | KnownModelName | str`.
   - `extract_tables` is the `asyncio.run` wrapper with the same arguments.
   - Update the module docstring.
4. `__init__.py`: `__all__` is exactly `BudgetExceededError`, `ExtractionError`, `Flag`, `Row`,
   `Table`, `TextLayerError`, `extract_tables`, `extract_tables_async`.
5. `ruff check`, `ty check`, `ruff format`. Tests are task 003, so the suite fails until then.

## Done when

`python -c "from gridkey import extract_tables"` works, `extract_tables("x.pdf")` raises
`TypeError` (missing `model`), `from gridkey import CachedClient` raises `ImportError`, and ruff
and ty pass on `src/`.
