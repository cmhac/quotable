# 003 - Rename the tool to gridkey

Status: open questions resolved

## Summary

Rename the project from `pdf-table-extract` (import `pdf_table_extract`) to `gridkey`
(import `gridkey`). The name is a play on words: tables in PDFs are grids that are "locked"
on the page, and this tool is the key that unlocks them. Nothing about behaviour changes.

## Motivation

`pdf-table-extract` describes what the tool does generically and is easy to confuse with the
many other PDF table extractors. `gridkey` is short and distinctive and carries the idea of the
project: getting the data out of a fixed grid.

A name check on PyPI found no project called `gridkey` (HTTP 404 from
`https://pypi.org/pypi/gridkey/json` on 2026-10-15). Not checked: other indexes, trademarks,
GitHub or other organisations' use of the name.

## Requirements

1. **Names.**
   - Distribution (`pyproject.toml` `name`): `gridkey`.
   - Import package: `gridkey`. `src/pdf_table_extract/` is moved to `src/gridkey/` with
     `git mv`, so history follows the files.
   - Environment variable for the live test model: `GRIDKEY_LIVE_MODEL` (was
     `PDF_TABLE_EXTRACT_LIVE_MODEL`). `OPENAI_API_KEY` is unchanged.
   - Optional extra stays `openai`: `pip install gridkey[openai]`.
2. **No compatibility layer.** There is no `pdf_table_extract` shim, alias package or old
   environment variable fallback. The project was never published and exists only on this
   machine (user), and the repository has no git remote. A search of the VRA community-projects
   repository found no reference to it. Anything else on this machine that imports
   `pdf_table_extract` breaks until it is updated.
3. **Every reference is updated** in code, tests, docs and tooling:
   - all `import` / `from pdf_table_extract...` lines in `src/`, `tests/` and `scripts/`;
   - `:mod:` references and docstrings that name the package (`extract.py`, `grounding.py`,
     `pydantic_ai_client.py` and others);
   - the string in `resources.files("pdf_table_extract")` in `ngrams.py`, and the output path
     in `scripts/build_trigrams.py`, which still point at the package directory;
   - `README.md` (title, examples, install line, live-test instructions), `AGENTS.md`
     (introduction, file tree, commands table), `scripts/README.md`;
   - `justfile` comments, `.env.example`, and the live test's docstring, skip message and
     variable.
4. **Lock file.** `uv.lock` is regenerated with `uv lock` (not edited by hand). Dependencies
   and their pins do not change.
5. **Version.** Stays `0.1.0`.
6. **README states the name's origin** in one or two sentences (grids locked on the page; this
   is the key). Nothing else is added.
7. **Past specs are history.** `specs/001-*` and `specs/002-*` keep the old name in the text
   that records what was decided at the time. They are not rewritten. `AGENTS.md` says so in
   one line, so an agent grepping for the old name knows why it still appears there.
8. **Behaviour, public API and data are unchanged.** Names of functions, classes, exceptions
   and arguments stay as they are; the bundled `data/trigram_counts.json` is only moved with
   the package. The model prompts do not contain the package name (checked in the source), so
   cached answers stay valid.
9. **No leftovers.** After the change, a case-insensitive search for
   `pdf[-_ ]table[-_ ]extract` finds nothing outside `specs/001-*`, `specs/002-*` and this
   spec; a search for `PDF_TABLE_EXTRACT` finds nothing outside those.
10. **The directory is renamed last.** Once the code changes are in and `just check` passes,
    the repository directory is moved from `/Users/hackerc/tools/pdf-table-extract` to
    `/Users/hackerc/tools/gridkey` (user's request). Nothing in git changes by this; `.git`
    moves with it. The `.venv` is not relocatable (absolute paths in its scripts and its
    editable install), so it is deleted and rebuilt with `uv sync --extra openai` at the new
    path. After the move, `just check` is run again from the new path. The target path does not
    exist today.

## Design

A mechanical rename, done in this order so every intermediate state is easy to check:

1. `git mv src/pdf_table_extract src/gridkey`.
2. Replace `pdf_table_extract` with `gridkey` in `src/`, `tests/` and `scripts/` (imports,
   `:mod:` references, the `resources.files` string, the trigram output path).
3. `pyproject.toml`: `name = "gridkey"`; the description stays unless the user asks for a
   change (open question 2).
4. Replace `PDF_TABLE_EXTRACT_LIVE_MODEL` with `GRIDKEY_LIVE_MODEL` in `tests/live/`,
   `justfile`, `.env.example`, `README.md` and `AGENTS.md`.
5. Replace the project name in prose in `README.md`, `AGENTS.md` and `scripts/README.md`;
   add the origin sentence to the README and the history note to `AGENTS.md`.
6. `uv lock`, then `uv sync --extra openai` to rebuild the environment under the new name.
7. Run `just check`, then the leftover searches from requirement 9.
8. Move the directory (requirement 10): `mv /Users/hackerc/tools/pdf-table-extract
   /Users/hackerc/tools/gridkey`, delete the old `.venv`, `uv sync --extra openai`, run
   `just check` again. This step is the last task and is run only after the user has what they
   need from the earlier steps (the tool's working directory changes, so later commands use the
   new path). Deleting `.venv` is the only deletion and is fully regenerable from `uv.lock`.

Not done by the tasks (they sit outside the repository's files):

- The user's local `.env` is git-ignored and holds secrets, so it is not read or edited: the
  user renames the key `PDF_TABLE_EXTRACT_LIVE_MODEL` to `GRIDKEY_LIVE_MODEL` there. Until
  then `just test-live` skips itself, as it does when the variable is unset.
- Scratch scripts outside the repository that import `pdf_table_extract` (the Senate
  experiments) are not updated and will fail to import after the rename. Their cached model
  answers are unaffected.
- Shell history, editor workspaces, bookmarks or aliases that use the old directory path are
  not searched for and may need updating by the user.

## Risks

- **Conflicts with spec 002.** The rename touches almost every source and test file, and
  spec 002 changes `recheck.py`, `text.py`, tests, `README.md` and `AGENTS.md`. Implement this
  spec after spec 002 is merged, or on top of its branch, not in parallel.
- **Stale editable install.** The `.venv` has the project installed under the old name.
  `uv sync` replaces it; a stale environment would fail with `ModuleNotFoundError: gridkey`.
- **Missed string reference.** The package name appears as plain strings in a few places
  (`resources.files`, the trigram output path). A grep-only check could miss one built from
  parts, so the test suite (which loads the trigram data) is part of the check.
- **Wheel contents.** Not checked until implementation: that a built wheel contains
  `gridkey/data/trigram_counts.json` and `py.typed`.

## Alternatives considered

- **Keep the old import name and rename only the distribution.** Rejected: two names for one
  thing is confusing for a project this young.
- **Leave a `pdf_table_extract` shim that re-exports `gridkey`.** Rejected: the project was
  never published, so there are no outside users, and the shim would need removing later.
- **Rewrite specs 001 and 002 to the new name.** Rejected: they record decisions as they were
  made.

## Out of scope

- Any change in behaviour, defaults, prompts or thresholds.
- Publishing to PyPI, reserving the name, creating a remote, or changing the author or
  licence metadata.
- Changing the project description or the README beyond the name and the origin sentence.
- A logo, tagline, or CLI command named `gridkey` (the library has no CLI; the writer is
  listed in "Not carried over yet").

## Tests

All offline, no network.

- The existing suite passes unchanged apart from the import lines: same test count as before
  the rename (101 with spec 002's tests).
- `import gridkey` works and exposes the same public names as `pdf_table_extract` did
  (`extract_table`, `CachedClient`, `TextLayerError` and the rest of `__init__`'s exports).
  The existing tests that import them cover this; no new test unless one is missing.
- `import pdf_table_extract` fails (`ModuleNotFoundError`), confirming nothing of the old
  package is left installed.
- The tests that load the trigram data (`tests/test_ngrams.py`, `tests/test_textcheck.py`)
  pass, which covers the `resources.files("gridkey")` path.
- Leftover searches from requirement 9 return nothing.
- `uv build` succeeds and the wheel lists `gridkey/data/trigram_counts.json` and
  `gridkey/py.typed` (manual, then the build output is deleted).
- `just check` passes (ruff, ruff-format, ty, tests), before the directory move and again from
  `/Users/hackerc/tools/gridkey` after it.
- After the move: `git status` and `git log` work at the new path and show the same branch and
  history; `/Users/hackerc/tools/pdf-table-extract` no longer exists.

## Docs

- `README.md`: new title, examples, install line, live-test environment variable, and the
  origin sentence.
- `AGENTS.md`: introduction, file tree (`src/gridkey/`), commands table, the new environment
  variable, the note about historical specs, and the project state (this spec implemented).
- `scripts/README.md` and `.env.example`: new names.

## Open questions

1. Resolved (user): `pdf-table-extract` was never published and is only local, so there is no
   shim and no release under the old name (requirement 2).
2. Resolved (user): the project description stays as it is.
3. Resolved (user): the repository directory is renamed to `~/tools/gridkey` once the code
   changes are in (requirement 10).
