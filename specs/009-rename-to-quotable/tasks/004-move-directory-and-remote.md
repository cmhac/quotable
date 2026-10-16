# 004 - Move the repository directory to ~/tools/quotable and update the remote

Spec: `../spec.md` (Requirement 10; Design / Moving the directory, Updating the remote). Depends
on: tasks 001, 002 and 003. This is the last task: after the move the working directory changes,
and every later command uses the new path.

## Goal

Rename the checkout on this machine from `/Users/hackerc/tools/gridkey` to
`/Users/hackerc/tools/quotable`, rebuild the environment and the git hook there, and point
`origin` at the renamed GitHub repository.

## Steps

1. Check before moving: `/Users/hackerc/tools/quotable` does not exist; `git status` is clean or
   shows only changes the user knows about (uncommitted work moves with the directory); no
   other agent, editor or process of mine is working in the directory. If one is, stop and
   ask the user.
2. Tell the user the move is about to happen and what it changes (see Notes). Go ahead without
   asking again: the user asked for this move in the spec.
3. `mv /Users/hackerc/tools/gridkey /Users/hackerc/tools/quotable`.
4. In the new directory: delete `.venv` (it holds absolute paths to the old location; fully
   regenerable from `uv.lock`), then run `just setup`. `just setup` also rewrites
   `.git/hooks/pre-commit`, which contains the old absolute `.venv` path; confirm with
   `grep INSTALL_PYTHON .git/hooks/pre-commit` that it now points at `/Users/hackerc/tools/quotable`.
5. `just check`.
6. Confirm `git branch --show-current`, `git log --oneline -3` and `git status --short` match what
   they were before the move.
7. Remote: ask the user whether the GitHub repository has been renamed. Only when they say yes,
   run `git remote set-url origin https://github.com/cmhac/quotable.git` and `git remote -v`.
   If they have not, report that this step is waiting and stop; do not guess. Do not push, and
   do not run `git fetch` (it contacts GitHub) unless the user asks.

## Notes for the user

- The old path no longer exists. Shell history, editor workspaces, aliases and bookmarks that use
  `~/tools/gridkey` need updating; they were not searched.
- Scratch scripts and other projects that import `gridkey` stop working until they import
  `quotable`. Their `.gridkey/` caches stay valid if the folder is renamed to `.quotable/`.
- `.env` moves with the directory; its key `GRIDKEY_LIVE_TEST_MODEL` is still the old name until
  the user renames it to `QUOTABLE_LIVE_TEST_MODEL`.

## Acceptance

- `/Users/hackerc/tools/gridkey` does not exist; `/Users/hackerc/tools/quotable` does.
- `just check` passes from the new path, and the pre-commit hook points at the new `.venv`.
- Branch, history and working tree are the same as before the move.
- `origin` is `https://github.com/cmhac/quotable.git` if the user confirmed the rename; otherwise
  it is unchanged and the report says so.
- Nothing was pushed or committed by this task.
