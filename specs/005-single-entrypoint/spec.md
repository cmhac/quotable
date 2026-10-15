# 005 - One entrypoint, pydantic-ai built in

Status: open questions resolved

## Summary

Using the library today takes three objects and an import from a submodule:

```python
from gridkey import CachedClient, extract_tables
from gridkey.pydantic_ai_client import PydanticAIClient  # needs the [openai] extra

client = CachedClient(PydanticAIClient("openai:<model-name>"), Path(".cache"), max_requests=100)
tables = extract_tables(Path("tables.pdf"), client)
```

This spec makes `extract_tables` the only thing a user calls, with the model passed to it as a
required argument, and makes pydantic-ai a normal dependency instead of an optional extra:

```python
from gridkey import extract_tables

tables = extract_tables(
    "tables.pdf",
    model="openai:<model-name>",   # required, no default, never read from the environment
    cache_dir=".cache",            # optional
    max_requests=100,              # optional
)
```

## Motivation

- Two client objects wrapped around each other, plus the function, is more surface than the job
  needs. `CachedClient` and `PydanticAIClient` are implementation detail of "ask a model, and
  remember the answer".
- The `openai` extra is misleading (pydantic-ai supports many providers, the extra only installs
  the OpenAI SDK) and means a plain `pip install gridkey` cannot extract anything.
- A model is a decision about cost and quality; it should be visible at the call site, not
  picked up silently from the environment.

## Requirements

1. **One public entrypoint.** `gridkey.extract_tables(pdf, model, *, ...)` and its async twin
   `extract_tables_async` (same arguments). A user never constructs a client.
2. **`model` is required.** No default value. It is not read from an environment variable by the
   library; omitting it is a `TypeError`. It accepts what pydantic-ai accepts: a
   `"provider:model-name"` string, or a pydantic-ai `Model` instance. Provider API keys still
   come from the environment, as pydantic-ai does it (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
   ...); that is credentials, not the model choice.
3. **Optional keyword arguments** (all keyword-only, after `model`):
   - `cache_dir: str | Path | None = None`: when set, answers are cached on disk there, as
     `CachedClient` does today (same key: model identity, instructions, output schema, every
     prompt part). When `None`, nothing is cached.
   - `max_requests: int | None = None`: cap on new (uncached) model requests; exceeding it
     raises `BudgetExceededError`. Applies with or without a cache.
   - `model_settings: dict | None = None`: passed to pydantic-ai, and part of the cache key.
   - `discovery_pages` and `recheck`: unchanged.
4. **`pdf` accepts `str | Path`.** (Today `extract_tables` wraps in `Path`, but the annotation says
   `Path`.)
5. **Public names after the change** (`gridkey.__all__`): `extract_tables`,
   `extract_tables_async`, `Table`, `Row`, `Flag`, `ExtractionError`, `TextLayerError`,
   `BudgetExceededError`. Removed from the public surface: `CachedClient`, `LLMClient`,
   `Request`, `Image`. `gridkey.pydantic_ai_client` is removed as a public module.
   No deprecation shims: the project is unpublished (spec 003).
6. **Internals stay swappable for tests.** `llm.py` keeps `Request`, `Image`, the `LLMClient`
   protocol and the disk cache as internal building blocks, and `extract.py` keeps an internal
   function that takes an already-built client (what the public function calls after building
   one). The offline tests call that function with their fake models, so none of the 138 tests
   needs a rewrite beyond imports. The fakes stay the way the offline suite replays recorded rows.
7. **pydantic-ai is a required dependency, with the provider SDKs but nothing heavy.**
   `[project.optional-dependencies]` and the `openai` extra are deleted. `dependencies` gains
   `pydantic-ai-slim[<providers>]==2.54.0` (pinned, as everything else is). See Design for why
   this is not the plain `pydantic-ai` package.
8. **`pydantic_ai` is imported at the top of the module that uses it**, no deferred import.
   (It was deferred only so the extra could be absent.)
9. **Test-only model variable.** The live test reads `GRIDKEY_LIVE_TEST_MODEL` (renamed from
   `GRIDKEY_LIVE_MODEL`) and passes it as `model`. Nothing under `src/` reads it.
10. **Docs and tooling follow:** README example, "Development" section and install line;
   `AGENTS.md` (file tree, project state, commands table); `justfile` (`setup` becomes plain
   `uv sync`); `.env.example`; docstrings that mention the extra.
11. **Behaviour is otherwise unchanged:** prompts, pipeline stages, thresholds and cache keys for
    a given model string do not change, so existing caches stay valid (checked: the key uses
    `identity`, which keeps the format `"<model>:<sorted settings json>"`).

## Design

### Dependency

The plain `pydantic-ai` 2.54.0 package installs only `anthropic`, `google`, `openai`, plus
`cli`, `evals`, `logfire`, `mcp` and `web` (starlette, uvicorn, an MCP stack, OpenTelemetry).
It does **not** include Groq, Mistral, Cohere, Bedrock, Hugging Face or xAI, so "the full
dependency" would neither give every provider nor stay minimal. Checked against PyPI metadata
for `pydantic-ai-slim` 2.54.0: provider support is selected by extras.

Proposed pin:

```
pydantic-ai-slim[anthropic,bedrock,cohere,google,groq,huggingface,mistral,openai,openrouter,xai]==2.54.0
```

Resolution check (`uv pip compile`, Python 3.11, with the existing `pydantic==2.13.5` and
`pymupdf==1.28.2` pins): resolves to 84 packages with no conflict, and none of torch, nvidia-*,
triton, tensorflow, transformers, numpy, scipy, onnxruntime or sentence-transformers. The
heaviest additions are `boto3`/`botocore` (Bedrock), `grpcio` (xAI) and `google-genai`. The
`sentence-transformers` extra (which pulls in PyTorch) is deliberately left out; it is for
embeddings and unrelated to this use. Not checked: installed size on disk and import time; the
implementation task measures both.

### Code

- `extract.py`: `extract_tables_async(pdf, model, *, cache_dir, max_requests, model_settings,
  discovery_pages, recheck)` builds the client, then calls the internal function that
  currently holds the pipeline (renamed `run_pipeline`, taking a client). `extract_tables` is the
  `asyncio.run` wrapper.
- `llm.py`: `CachedClient` stays as an internal class, and its `cache_dir` becomes optional
  (`None` = no disk cache, the request cap still applies). The public function always wraps the
  model client in it, so the cap works with or without a cache. Module docstring updated.
- `pydantic_ai_client.py` -> `gridkey/_model.py` (internal name): `PydanticAIClient` unchanged
  in behaviour. Identity for a model instance becomes `"<system>:<model_name>"` instead of the
  bare class name, because two different `OpenAIChatModel("gpt-x")` / `("gpt-y")` instances would
  otherwise share one cache key. This changes keys only for instance models, which nothing
  caches today.

### Alternatives considered

- **`model` read from `GRIDKEY_MODEL` when not passed.** Rejected by the request: the model is
  an explicit argument.
- **Keep `CachedClient` public as an advanced option.** Rejected: it is the second client object
  this spec removes; `cache_dir` and `max_requests` cover its use.
- **Depend on plain `pydantic-ai`.** Rejected, see Design / Dependency.
- **Accept any `LLMClient` as `model`.** Rejected: it keeps the client concept in the public
  API. Tests reach the internal function instead.

## Out of scope

- A default on-disk cache (later spec).
- Prompts, thresholds or pipeline stages.
- A CLI or a `.env` loader.
- Choosing a model for the user or validating a model string beyond what pydantic-ai does.
- Streaming, retries or rate-limit handling beyond what pydantic-ai provides.

## Tests

All offline.

- Existing suite passes with import changes only (the internal function replaces the public
  one in tests that pass a fake client); same test count.
- `extract_tables(pdf)` without `model` raises `TypeError`; no environment variable changes
  that (test sets `GRIDKEY_MODEL` and `OPENAI_MODEL` and asserts it still fails).
- A pydantic-ai `FunctionModel` passed as `model` runs the whole pipeline on a sample PDF
  through the public function (the existing `test_pydantic_ai_client` approach, now end to
  end), and the result equals the fake-client result.
- `cache_dir`: a second identical run makes no model request; `max_requests` raises
  `BudgetExceededError` with and without `cache_dir`.
- `from gridkey import CachedClient` fails (`ImportError`); `gridkey.__all__` equals the list
  in requirement 5.
- Instance-model identity differs for two models with different names.
- `uv lock` succeeds; `uv pip list` in the synced environment has none of the heavy packages
  above; `just check` passes.
- Live test (`tests/live/`) calls the public function; run only with the user's go-ahead.

## Docs

`README.md`, `AGENTS.md` (project state: spec 005; file tree; commands), `justfile`,
`.env.example`, module docstrings.

## Open questions

1. Resolved (user): the model is NOT an environment variable; it is a required argument
   (requirement 2). The earlier wording was a typo.
2. Resolved (user): the live test keeps a test-only environment variable, renamed to make that
   clear: `GRIDKEY_LIVE_TEST_MODEL` (was `GRIDKEY_LIVE_MODEL`). The library never reads it. No
   fallback to the old name.
3. Resolved (user): the provider list in Design / Dependency is accepted as proposed.
4. Resolved (user): `cache_dir=None` (no caching) stays the default here. A default on-disk
   cache is a later spec and is out of scope.
5. Resolved (user): the public API changes in requirement 5 are approved. A custom provider is
   a pydantic-ai `Model` instance passed as `model`, which the user wants to keep.
