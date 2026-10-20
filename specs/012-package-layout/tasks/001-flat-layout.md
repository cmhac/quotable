# 001 - Move the package out of `src/`

Spec: `../spec.md` (Requirement 1; Design step 1). Depends on: spec 011 merged into `main`; branch
`spec/012-package-layout` cut from it.

## Goal

After this task the package is at `quotable/` in the repository root, `src/` is gone, the
environment is reinstalled from the new path, and `just check` passes. No module changes yet.

## Steps

1. Record the baseline outside the repository (the tasks that follow compare against it):
   `uv run pytest --collect-only -q | sed 's|^[^:]*::||' | sort > /tmp/spec012-names.txt` and
   note the test count (1,442 collected, 131 deselected at `a5713ba`).
2. `git mv src/quotable quotable`. Then delete the leftover `src/` folder (only git-ignored
   `__pycache__` files remain; left in place, an editable install could keep pointing at it).
3. `pyproject.toml`: add
   ```toml
   [tool.uv.build-backend]
   module-root = ""
   ```
   after `[build-system]`. Change nothing else.
4. `scripts/build_trigrams.py`: `OUTPUT` becomes `.../"quotable/data/trigram_counts.json"`
   (and its docstring). `scripts/README.md`: the same path.
5. `just setup` (`uv sync` rebuilds the editable install from the new location), then
   `uv run ruff check --fix .`, `uv run ruff format .` and `just check`. Do not commit unless the
   user asks.

## Acceptance

- `src/` does not exist; `git status` shows the package files as renames.
- From a directory outside the repository, `uv run --project /Users/hackerc/tools/quotable python
-c "import quotable, pathlib; print(pathlib.Path(quotable.__file__).parent)"` prints
  `/Users/hackerc/tools/quotable/quotable`.
- `just check` passes with the same test count as the baseline.
- `git grep -n "src/quotable" -- . ':!specs'` finds only `AGENTS.md` (task 006 rewrites it).
- No live or OCR test was run.
