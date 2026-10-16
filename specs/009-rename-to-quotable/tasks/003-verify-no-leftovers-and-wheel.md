# 003 - Verify no leftovers and the built wheel

Spec: `../spec.md` (Requirement 9; Tests). Depends on: tasks 001 and 002. Changes nothing in the
repository unless a leftover is found.

## Steps

1. From the repository root run `git grep -i gridkey -- . ':!specs'` and a plain `grep -rIi
   gridkey` with `--exclude-dir` for `.git`, `.venv`, `__pycache__`, `.ruff_cache`,
   `.pytest_cache` and `specs`. The only hits allowed are the history sentences in `AGENTS.md`.
   `git grep` covers tracked files; the plain grep also covers untracked ones. `.env` is
   git-ignored and holds secrets: do not print its lines. If the plain grep lists `.env` by name
   (use `-l`), report that the user's key still needs renaming; do not read or edit the file.
2. Fix any other hit and say which file it was.
3. Confirm the specs search: `git grep -il gridkey -- specs` returns only folders `003` to `009`,
   and no `pdf-table-extract` text was added anywhere.
4. `uv build --out-dir "$KIROCREW_SCRATCH/wheel"`, then `unzip -l` the wheel. Confirm it lists
   `quotable/data/trigram_counts.json`, `quotable/py.typed` and the modules, and nothing under
   `gridkey/`. Delete the build output afterwards.
5. Run `just check` once more.
6. Run `tests/test_cache.py` on its own (`just test -k test_cache`): it covers the default folder
   `.quotable/` and its `.gitignore`. Run no extraction and no model.

## Acceptance

- The step 1 searches return only the allowed hits.
- The wheel's contents are as described in step 4.
- `just check` passes.
- The report lists what was searched, what was found, and what was not checked (the user's
  `.env`, other projects and scratch scripts that import `gridkey`, shell history).
