# 009 - Rename the tool to quotable

Status: approved; open questions resolved; tasks written (`tasks/001` to `004`), awaiting approval.

## Summary

Rename the project from `gridkey` (import `gridkey`) to `quotable` (import `quotable`). Nothing
about behaviour changes. This is the same kind of change as spec 003 (`pdf-table-extract` to
`gridkey`), with one difference that matters: the repository now has a GitHub remote
(`https://github.com/cmhac/gridkey.git`), which the user renames on GitHub themselves.

## Motivation

The user chose the new name. It also fits what the tool guarantees: every value it returns has
been looked up in the PDF's own text layer, so it can be quoted from the document.

Name check, 2026-10-16:

- PyPI: `https://pypi.org/pypi/quotable/json` returned HTTP 404, so no project called
  `quotable` exists there.
- GitHub: `https://github.com/cmhac/quotable` returned HTTP 404 (the account's own namespace is
  free, or the repository is private; either way the user's rename decides it).
- Not checked: other indexes, trademarks, other GitHub accounts, and whether other products use
  the word. From memory only, not verified: a public random-quotes web API is also called
  "Quotable", which may make searches for the name noisy. It is not a Python package.

## Requirements

1. **Names.**
   - Distribution (`pyproject.toml` `name`): `quotable`.
   - Import package: `quotable`. `src/gridkey/` is moved to `src/quotable/` with `git mv`, so
     history follows the files.
   - Optional extras keep their names: `quotable[ocr]`, `quotable[ocr-core]`.
   - Environment variable for the live test model: `QUOTABLE_LIVE_TEST_MODEL` (was
     `GRIDKEY_LIVE_TEST_MODEL`). `OPENAI_API_KEY` is unchanged.
   - Default cache folder: `.quotable/` (was `.gridkey/`), in `cache.py`'s `DEFAULT_DIR_NAME`,
     its docstrings, the folder's own `.gitignore` rule, the repository `.gitignore`, `README.md`
     and `AGENTS.md`.
   - Logger names: `quotable.ocr` (was `gridkey.ocr`).
2. **No compatibility layer.** No `gridkey` shim, alias package, old environment variable
   fallback, or fallback to an existing `.gridkey/` folder. Nothing was published (the only
   public thing is the GitHub repository, which is being renamed), so there are no outside
   users. Anything on this machine that imports `gridkey` breaks until updated.
3. **Every reference is updated** in code, tests, docs and tooling. On `main` at `44ce9a1`
   (spec 008 merged) there are 282 occurrences of `gridkey` in 69 tracked files outside
   `specs/` (21 in `src/`, 39 in `tests/`); the places to change are:
   - all `import` / `from gridkey...` lines in `src/`, `tests/` and `scripts/`, and `:mod:`,
     `:class:` and `:func:` references and other mentions in docstrings (for example
     ``gridkey.merge`` in `discover.py` and `extract.py`);
   - plain strings: `resources.files("gridkey")` in `ngrams.py`; the output path in
     `scripts/build_trigrams.py`; `logging.getLogger("gridkey.ocr")` in `ocr.py`, `_paddle.py`
     and `ocr_pages.py`; `DEFAULT_DIR_NAME` and the error text "cannot use ... as the gridkey
     cache directory" in `cache.py`; the messages in `ocr.py`, `textcheck.py` ("gridkey OCR'd
     page(s) ..."), `_paddle.py` (`pip install "gridkey[ocr]"`) and `ocr_device.py`;
   - tests that assert on those strings or whose names contain the old name
     (`test_ocr_pipeline.py`, `test_ocr_device.py`, `test_paddle_adapter.py`, `test_cache.py`,
     `test_entrypoint.py`, `test_frames.py`, `test_merge_pipeline.py`, `test_merged_field.py`,
     `conftest.py`, `tests/live/`, `tests/ocr/`, `tests/data/README.md`). One needs care:
     `test_merge_checks.py` asserts `"gridkey.extract" not in {...module names...}`. If the
     string is left alone after the rename it still passes, but checks nothing, so it must
     become `"quotable.extract"` and be shown to fail when `merge.py` imports from `extract`
     (the leftover search in requirement 9 would catch the literal, but only a failing run
     proves the test still tests something);
   - `README.md` (title, examples, install lines, cache folder, the prose that says "gridkey
     does X", live-test instructions), `AGENTS.md` (introduction, file tree, commands table,
     project state), `scripts/README.md`;
   - `justfile` comment, `.env.example`, `.gitignore`, and the comment in `pyproject.toml`
     ("gridkey is installed into its own environment").
4. **Lock file.** `uv.lock` is regenerated with `uv lock` (not edited by hand). Only the
   project's own `[[package]] name` entry should change; dependencies and pins do not.
5. **Version and metadata.** Version stays `0.1.0`. The description, author and licence
   metadata are unchanged.
6. **Past specs are history.** Specs `001` to `008` keep the names they were written under
   (`pdf-table-extract` in 001 and 002, `gridkey` in 003 to 008), including the folder
   `specs/003-rename-to-gridkey/`. They are not rewritten. The line in `AGENTS.md` that
   explains this for 001 and 002 is extended to cover `gridkey` too.
7. **README origin sentence.** The sentence explaining the old name (grids locked on the page,
   the key that unlocks them) is removed and nothing replaces it (user's decision).
8. **Behaviour, public API and data are unchanged.** Names of functions, classes, exceptions
   and arguments stay as they are; `data/trigram_counts.json` only moves with the package.
   The model prompts and the cache keys do not contain the project name (a case-insensitive
   search of `src/` found it only in imports, docstrings, the strings listed in requirement 3
   and the cache folder name), so cached model and OCR answers stay valid. A user who wants to
   keep an existing cache renames the folder: `mv .gridkey .quotable`.
9. **No leftovers.** After the change, a case-insensitive search for `gridkey` finds nothing
   outside `specs/` (folders `001` to `009`), the history note in `AGENTS.md`, `.git/`,
   `.venv/` and caches (`__pycache__`, `.ruff_cache`, `.pytest_cache`). The local `.env` is
   git-ignored and holds secrets; it is not read, and the user renames the key there.
10. **The local directory and git remote** are changed as the last steps (user's decisions),
    after the code changes pass `just check`: first the directory move, then the `origin` URL
    (which waits until the user has renamed the GitHub repository).

## Design

A mechanical rename, in this order so each intermediate state is easy to check:

1. Work on an implementation branch (`spec/009-rename-to-quotable-impl`) cut from `main` after
   every spec ahead of this one has been merged (spec 008 is; the user says one more comes
   before this one). Before starting, update `main`, re-run the reference count from
   requirement 3 and note how it changed.
2. `git mv src/gridkey src/quotable`. Then delete the leftover `src/gridkey/` folder, which
   holds only git-ignored `__pycache__` files. This matters: with the editable install
   pointing at `src/`, a leftover folder would let `import gridkey` succeed as an empty
   namespace package and hide a missed reference.
3. Replace `gridkey` with `quotable` in `src/`, `tests/` and `scripts/` (imports, docstrings,
   the strings in requirement 3, test names). Run `ruff check --fix` and `ruff format`
   afterwards, because the import sort order can change (`quotable` sorts differently from
   `gridkey`).
4. `pyproject.toml`: `name = "quotable"`.
5. Replace `GRIDKEY_LIVE_TEST_MODEL` with `QUOTABLE_LIVE_TEST_MODEL` in `tests/live/`,
   `tests/test_entrypoint.py` (the list of variable names the library must not read becomes
   `QUOTABLE_MODEL`, `QUOTABLE_LIVE_TEST_MODEL`, ...), `justfile`, `.env.example`, `README.md`
   and `AGENTS.md`.
6. Replace the name in prose in `README.md`, `AGENTS.md` and `scripts/README.md`, and update
   the history note in `AGENTS.md`.
7. `uv lock`, then `just setup` (`uv sync` and the pre-commit hook install) to rebuild the
   environment under the new name. `uv sync` removes the old `gridkey` editable install.
8. Run `just check`, then the leftover searches from requirement 9.
9. Move the directory and update the remote, as described below (task 004).

### Moving the directory

`mv /Users/hackerc/tools/gridkey /Users/hackerc/tools/quotable` (the target does not exist
today). `.git` moves with it, so branches, history and uncommitted work are unchanged. Then, at
the new path:

- delete `.venv` (it holds absolute paths and is regenerable from `uv.lock`) and run
  `just setup`. `just setup` also rewrites `.git/hooks/pre-commit`, which currently contains
  the absolute path `/Users/hackerc/tools/gridkey/.venv/bin/python3`; skipping this leaves a
  hook that fails;
- run `just check` again; confirm `git branch --show-current`, `git log --oneline -3` and
  `git status --short` match what they were before the move.

The move changes the working directory of every process and agent using the repository, so it
runs only when no other agent or editor is working in it.

### Updating the remote

After the user says the GitHub repository is renamed: `git remote set-url origin
https://github.com/cmhac/quotable.git`, then `git remote -v` to confirm. GitHub redirects the
old URL, so this is tidiness rather than a fix. If the user has not yet renamed the
repository, the step waits; it is not skipped silently. Nothing is pushed by this spec.

### Not done by the tasks

These sit outside the repository's files:

- Renaming the GitHub repository, and its description or topics (the user).
- Renaming `GRIDKEY_LIVE_TEST_MODEL` to `QUOTABLE_LIVE_TEST_MODEL` in the local `.env` (the
  user). Until then `just test-live` skips itself, as it does when the variable is unset.
- Scratch scripts, notebooks or other projects that `import gridkey`, and `.gridkey/` cache
  folders next to them. They are not searched for or updated. Their cached answers stay valid
  if the folder is renamed to `.quotable/`.
- Shell history, editor workspaces, aliases and bookmarks that use the old directory path.

## Risks

- **Conflicts with work in flight.** The rename touches almost every source and test file.
  Specs 007 and 008 are merged into `main`; the user says one more spec lands before this one.
  Implement this after it is merged, from `main`, never in parallel with it.
- **Another agent in the directory during the move.** Moving the directory under a running
  agent breaks its paths. See "Moving the directory".
- **Stale editable install or leftover folder.** A stale `.venv` fails with
  `ModuleNotFoundError: quotable`; a leftover `src/gridkey/` folder makes the old import look
  alive (Design step 2).
- **Missed string reference.** The name appears in plain strings (`resources.files`, logger
  names, messages, the cache folder name). A grep can miss a name built from parts, so the test
  suite (which loads the trigram data and asserts on several messages) is part of the check.
- **Silently orphaned cache.** The default cache folder changes name, so a user with a
  populated `.gridkey/` re-spends model requests on the next run unless they rename the folder
  (`mv .gridkey .quotable`). Accepted (requirement 2); it is not documented in the README,
  because nothing was published and only the user's own folders are affected.
- **Wheel contents.** Not checked until implementation: that a built wheel contains
  `quotable/data/trigram_counts.json` and `quotable/py.typed`.

## Alternatives considered

- **Keep the import name `gridkey` and rename only the distribution.** Rejected: two names for
  one thing, for a project this young.
- **A `gridkey` shim that re-exports `quotable`, or reading the old cache folder as a
  fallback.** Rejected: nothing was published, and the shim would need removing later.
- **Rewrite specs 001 to 008 to the new name.** Rejected: they record decisions as they were
  made.
- **Do the rename by hand-editing `uv.lock`.** Rejected: use `uv lock`.

## Out of scope

- Any change in behaviour, defaults, prompts, thresholds or API names.
- Publishing to PyPI or reserving the name, pushing, and changing the author, licence or
  description metadata.
- A logo, tagline or CLI command named `quotable` (the library has no CLI).
- Changing past specs.

## Tests

All offline, no network; no live or OCR test is run.

- The existing suite passes with the same number of tests as on the base branch (969 on
  `main` at `44ce9a1`, plus whatever the spec ahead of this one adds), changed only in
  imports, strings and the test names that contain the old name.
- `test_the_module_imports_nothing_from_extract` (merge) still tests something after the
  rename: temporarily make `merge.py` import from `extract` and see it fail, then undo.
- `import quotable` works and `quotable.__all__` is unchanged (`tests/test_entrypoint.py`
  already compares it to a list).
- `import gridkey` fails with `ModuleNotFoundError` (checks the old install and the leftover
  folder).
- `tests/test_ngrams.py` and `tests/test_textcheck.py` pass, which covers
  `resources.files("quotable")`.
- `tests/test_cache.py` covers the default folder `.quotable/` and its `.gitignore`.
- The leftover search from requirement 9 returns nothing.
- `uv build --out-dir "$KIROCREW_SCRATCH/..."` succeeds; `unzip -l` on the wheel lists
  `quotable/data/trigram_counts.json`, `quotable/py.typed` and the modules, and nothing under
  `gridkey/`. The build output is deleted afterwards.
- `git diff uv.lock` shows only the project's own name entry changing.
- `just check` passes (ruff, ruff-format, ty, tests), before any directory move and again after
  it.

## Docs

- `README.md`: new title, examples, install line, cache folder, live-test variable.
- `AGENTS.md`: introduction, file tree (`src/quotable/`), commands table, the new variable, the
  history note (specs 001 to 008 keep their old names), and the project state (spec 009
  implemented; where "Spec 003 renamed the project to `gridkey`" appears, add that spec 009
  renamed it again to `quotable`). The text in the project state that describes what earlier
  specs did keeps working if it uses the new name for code (`quotable[ocr]`, `.quotable/`).
- `scripts/README.md` and `.env.example`: new names.

## Open questions

None. Resolved by the user:

1. No origin sentence in the README, and no replacement (requirement 7).
2. Move `~/tools/gridkey` to `~/tools/quotable` as the last task (requirement 10).
3. Update the `origin` URL after the GitHub repository is renamed (requirement 10).
4. Build on `main` once the spec ahead of this one is merged; spec 008 is already merged.
