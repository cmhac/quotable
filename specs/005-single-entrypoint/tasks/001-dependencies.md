# 001 - pydantic-ai becomes a required dependency

Spec: `../spec.md` (Requirements 7, 8; Design / Dependency). Depends on: nothing.

## Goal

A plain `uv sync` installs pydantic-ai with every approved provider SDK and nothing heavy; the
`openai` extra no longer exists.

## Steps

1. `pyproject.toml`: delete `[project.optional-dependencies]`. Add to `dependencies`:
   `pydantic-ai-slim[anthropic,bedrock,cohere,google,groq,huggingface,mistral,openai,openrouter,xai]==2.54.0`.
   Keep the existing `pydantic==2.13.5` and `pymupdf==1.28.2` pins.
2. `uv lock` (never edit `uv.lock` by hand), then `uv sync`.
3. `justfile`: `setup` runs `uv sync` (no `--extra openai`) and installs the hook; fix its
   comment ("including the optional pydantic-ai client").
4. Check the environment: `uv pip list` shows none of torch, nvidia-*, triton, tensorflow,
   transformers, numpy, scipy, onnxruntime, sentence-transformers. Record the package count and
   the size of `.venv/lib/python*/site-packages` (`du -sh`), and the time of
   `python -X importtime -c "import gridkey"` after task 002, in the task's report. If anything
   heavy appears, stop and tell the user.

## Done when

`uv sync` works from a clean lock, the heavy-package check is empty, and the numbers are
reported.
