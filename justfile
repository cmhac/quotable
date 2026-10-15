# Commands for working on this repo. Run `just` to list them.

default:
    @just --list

# Install dependencies (including the optional pydantic-ai client) and the git hooks
setup:
    uv sync --extra openai
    uv run pre-commit install

# Lint (no changes made)
lint:
    uv run ruff check .

# Format all code
format:
    uv run ruff format .

# Type check
typecheck:
    uv run ty check

# Run the offline tests (no network, no API key); pass pytest args, e.g. `just test -k grounding`
test *args:
    uv run pytest {{ args }}

# Run the live tests: calls a real model and costs money (needs OPENAI_API_KEY and PDF_TABLE_EXTRACT_LIVE_MODEL)
test-live:
    uv run pytest -m live

# Run every pre-commit hook (ruff check --fix, ruff format, ty) on all files
hooks:
    uv run pre-commit run --all-files

# Everything CI-style: hooks, then tests
check: hooks test
