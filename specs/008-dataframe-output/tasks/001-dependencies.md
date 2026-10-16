# 001 - pandas and polars become base dependencies

Spec: `../spec.md` (Requirement 7; Design / Dependency cost). Depends on: nothing.

## Goal

A plain `uv sync` installs pandas and polars, and the cost of that is on record.

## Steps

1. Before changing anything, record the baseline in the task report: package count
   (`uv pip list | wc -l`), `du -sh` of `.venv/lib/python*/site-packages`, and the best of three
   `python -X importtime -c "import gridkey" 2> /dev/null` wall times
   (`time uv run python -c "import gridkey"`).
2. `pyproject.toml`: add `"pandas>=3,<4"` and `"polars>=2,<3"` to `dependencies`, next to the
   existing pins (which stay pinned). Add a short comment saying why these two are ranges
   (spec 008, requirement 7).
3. `uv lock`, then `uv sync`. Never edit `uv.lock` by hand. Check the diff of `uv.lock`: pandas
   3.0.6 and numpy 2.3.5 are already locked through the dev group; the new entries should be
   `polars`, `polars-runtime-32` and maybe `python-dateutil`/`six` moving from dev-only to base.
4. Repeat the three measurements from step 1 and report both sets. The baseline is the one
   that matters when asking whether `import gridkey` got slower: nothing imports pandas or
   polars at module top (the methods import them inside their bodies, task 003), so the import
   time must not change. If it grew by more than noise, stop and tell the user.
5. Confirm the environment still has none of torch, nvidia-*, triton, tensorflow, transformers,
   onnxruntime, sentence-transformers (`uv pip list`).

## Done when

`uv sync` works from a clean lock, `python -c "import pandas, polars"` works, the heavy-package
check is empty, and both sets of numbers are in the report.
