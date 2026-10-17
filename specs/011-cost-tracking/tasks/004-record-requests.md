# 004 - Record every paid request

Spec: `../spec.md` (Requirements 1, 4 to 9; Design / Code; Tests). Depends on: tasks 001 and 002.

## Goal

`extract_tables` writes one cost record for every request that reaches the model, and for no
other. The request cache key, the `LLMClient` protocol and the public API do not change.

## Steps

1. Before editing anything: compute `request_key(identity, request)` for one fixed `Request`
   (fixed stage, instructions, a small `BaseModel` output type and parts) with the code as it
   is, and paste the resulting 64-character string into a test as a literal. It must still pass
   at the end (Requirement 9).
2. Red first: the tests of step 6, failing.
3. `_model.py`: `PydanticAIClient.__init__` takes an optional keyword `on_usage`, a callable
   `(request, model, usage, cost)` where `model` is `model_name(self.model)` (the
   `provider:model-name` the cache key uses, not `identity`), `usage` the pydantic-ai
   `RunUsage` and `cost` a `Decimal | None`. It is not part of `identity`. In `ask`, after
   `agent.run`, read `result.usage` (a property in the pinned pydantic-ai 2.54.0, not a
   method; the spec's `result.usage()` is corrected) and price it with a small module function
   `_price(result) -> Decimal | None` that returns `result.response.cost().total_price` and
   returns `None` on `LookupError` (the model or provider is not in `genai-prices`; a
   `TestModel` raises exactly this) and on `AssertionError` (pydantic-ai asserts a model name).
   Then call `on_usage`. Retries inside one `agent.run` are already summed by `result.usage`,
   so one `ask` is one record. Return `result.output` as before.
4. `costs.py`: `CostLog.record_usage(request, model, usage, cost)` adapts to `record`: it reads
   `request.stage` and the four token counts off `usage` (duck-typed, so no pydantic-ai
   import). If every count is zero it calls `skip("the model reported no usage")` and writes
   nothing.
5. `extract.py`, `extract_tables_async`: build one `CostLog()` per call, next to the client,
   and pass `on_usage=costs.record_usage` to `PydanticAIClient`. Costs always go to the
   project's `.quotable/cost/`, never into a `cache_dir` the caller named. Add one sentence to
   the docstring. `CachedClient` is untouched: it calls the inner client only on a miss, so a
   cache hit writes nothing without extra code. A request that raises writes nothing because
   `on_usage` runs after `agent.run` returns.
6. Tests (offline; a fake model is fine because they check bookkeeping, not model behaviour):
   - `PydanticAIClient` over `TestModel` with a small `BaseModel`: one record per `ask`, the
     right `stage`, `model` is `test:test`, tokens equal `result.usage`, `cost_usd` null
     (unpriced path). The priced path monkeypatches `quotable._model._price` to a fixed
     `Decimal`; the record carries it. Real prices cannot be tested offline (see the spec).
   - A model that raises (a `FunctionModel` that raises) leaves the file absent.
   - A model reporting zero usage writes nothing and warns once.
   - `extract_tables(PDF, Calls().model(), recheck=False)` as in `tests/test_entrypoint.py`:
     two records (discovery and the page), stages as expected, one `run` id; a second run in the
     same folder adds none (all cache hits) and a third run after deleting `.quotable/cache/`
     adds exactly two with a different `run` id.
   - `cache_dir=tmp_path/"named"`: the cache files land there, `cost/requests.jsonl` lands in
     the working directory's `.quotable/`, and nothing cost-related is inside `named`.
   - An unwritable `.quotable/cost`: `extract_tables` still returns its tables and stderr holds
     one warning.
   - `BudgetExceededError` (`max_requests=1`) still raises as before, and the request that
     was refused wrote no record.
   - The cache-key literal from step 1.
   - A `PydanticAIClient` built without `on_usage` behaves as before.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, the existing suite passes unchanged (every existing test that uses a fake
client is untouched), and `ty` and `ruff` are clean. `quotable.__all__` is unchanged.
