# 004 - Move the repository directory to ~/tools/gridkey

Spec: `../spec.md` (Requirement 10; Design step 8). Depends on: tasks 001, 002 and 003.

## Goal

Rename the checkout on this machine from `/Users/hackerc/tools/pdf-table-extract` to
`/Users/hackerc/tools/gridkey`. This is the last task: after it, the tool's working directory
changes and every later command uses the new path.

## Steps

1. Check before moving: `/Users/hackerc/tools/gridkey` does not exist; `git status` is clean or
   has only changes the user knows about (uncommitted work moves with the directory, nothing is
   lost); no process of mine is running in the directory.
2. Tell the user the move is about to happen and what it changes (see Notes). Ask only if the
   user has not already said to go ahead; they have asked for this rename in spec 003.
3. `mv /Users/hackerc/tools/pdf-table-extract /Users/hackerc/tools/gridkey`.
4. In the new directory: delete `.venv` (it holds absolute paths to the old location and is
   regenerable from `uv.lock`), then `uv sync --extra openai`.
5. Run `just check`.
6. Confirm `git branch --show-current`, `git log --oneline -3` and `git status --short` give the
   same results as before the move.

## Notes for the user

- The old path no longer exists. Shell history, editor workspaces, aliases and bookmarks that
  use `~/tools/pdf-table-extract` need updating; they were not searched.
- Scratch scripts in `$KIROCREW_SCRATCH` import `pdf_table_extract` and will not run until
  they use `gridkey`; their caches remain valid.
- `.env` moves with the directory. Its key `PDF_TABLE_EXTRACT_LIVE_MODEL` is still the old
  name until the user renames it to `GRIDKEY_LIVE_MODEL`.

## Acceptance

- `/Users/hackerc/tools/pdf-table-extract` does not exist; `/Users/hackerc/tools/gridkey` does.
- `just check` passes from the new path.
- Branch, history and working tree state are the same as before the move.
- Nothing was pushed or committed by this task.
