# Commands for working on this repo. Run `just` to list them.

# Load .env (git-ignored) into the environment of every recipe
set dotenv-load

default:
    @just --list

# Install dependencies and the git hooks
setup:
    uv sync
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

# Score the merge rules on the golden fixture (spec 007; no model, no cost)
score-merge:
    uv run python -m tests.score_merge

# Score the extra-fields checks on the fixture with injected faults (spec 010; no model, no cost)
score-extra-fields:
    uv run python -m tests.score_extra_fields

# Run the live tests: calls a real model and costs money (needs OPENAI_API_KEY and QUOTABLE_LIVE_TEST_MODEL).
# Pass pytest args, e.g. `just test-live -n 4 tests/live/test_live_extra_fields.py`;
# QUOTABLE_LIVE_RUNS=1 runs each spec 010 case once instead of three times.
test-live *args:
    uv run pytest -m live -rs {{ args }}

# Run the real-OCR tests: real PaddleOCR models on the CPU (slow, downloads ~140 MB of models on first use, no API cost)
test-ocr:
    uv run pytest -m ocr -rs --durations=0

# Regenerate the golden synthetic fixture (tests/data/synthetic): PDFs plus truth files
synthetic:
    uv run python -m tests.synthetic_cases

# Run every pre-commit hook (ruff check --fix, ruff format, ty) on all files
hooks:
    uv run pre-commit run --all-files

# Everything CI-style: hooks, then tests
check: hooks test
