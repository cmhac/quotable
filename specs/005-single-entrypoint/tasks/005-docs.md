# 005 - Docs

Spec: `../spec.md` (Requirement 10; Docs). Depends on: tasks 001 to 004.

## Goal

The README and AGENTS.md describe the new API and dependency.

## Steps

1. `README.md`: replace the opening example with the single-call form from the spec's Summary
   (model required; `cache_dir` and `max_requests` optional); delete the sentence about
   `identity`/`ask` clients and say a custom provider is a pydantic-ai `Model` instance passed as
   `model`; say provider API keys come from the environment as pydantic-ai documents; fix the
   "Model requests are cached" paragraph (`cache_dir`, `max_requests`); `just setup` comment in
   "Development" (no extra); live-test instructions with `GRIDKEY_LIVE_TEST_MODEL`.
2. `AGENTS.md`: project state (spec 005 implemented; keep the file honest), file tree
   (`_model.py` replaces `pydantic_ai_client.py`; `llm.py` and `extract.py` descriptions), the
   commands table (`just setup`, `just test-live` variable name). Update the test count.
3. Update `specs/005-single-entrypoint/spec.md` Status to implemented only after the user
   approves the change.
4. `just check` (stage new files first so the hooks see them) and the leftover searches from
   task 004.

## Done when

`just check` passes and nothing in README.md or AGENTS.md mentions `CachedClient`,
`PydanticAIClient`, `[openai]` or `--extra openai`.
