# 003 - Verify no leftovers and the built wheel

Spec: `../spec.md` (Requirement 9; Tests). Depends on: tasks 001 and 002. No repo changes
unless a leftover is found.

## Steps

1. From the repository root, run these searches with `grep` or `git grep`, excluding `.git`,
   `.venv`, `__pycache__` and `.ruff_cache`:
   - case-insensitive `pdf[-_ ]table[-_ ]extract`;
   - `PDF_TABLE_EXTRACT`.
   The only hits allowed are in `specs/001-*`, `specs/002-*`, `specs/003-*` and the single
   history note in `AGENTS.md`. `.env` is git-ignored and is not read; if a hit is expected
   there, it is the user's to change.
2. Fix any other hit (a file the earlier tasks missed) and say which file it was.
3. `uv build` into a scratch directory under `$KIROCREW_SCRATCH` (`--out-dir`), then list the
   wheel with `unzip -l`. Confirm it contains `gridkey/data/trigram_counts.json`,
   `gridkey/py.typed` and the modules, and nothing under `pdf_table_extract/`. Delete the
   build output when done.
4. Run `just check` one more time.

## Acceptance

- Step 1 searches return only the allowed hits.
- The wheel's contents are as described in step 3.
- `just check` passes.
- The report lists what was searched, what was found, and anything not checked (the user's
  `.env`, scratch scripts outside the repository).
