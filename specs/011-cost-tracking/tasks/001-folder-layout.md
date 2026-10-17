# 001 - `.quotable/` gets a `cache/` subfolder

Spec: `../spec.md` (Requirement 2; Design / Folder layout; Tests / Folder layout). Depends on: nothing.

## Goal

The default cache lives in `.quotable/cache/`, an existing loose cache is moved there once, and
`.quotable/` has a helper other code can use to find the project folder. Nothing else changes.

## Steps

1. Red first. In `tests/test_cache.py` update the default-location tests to the new layout
   (answers and `ocr/` under `.quotable/cache/`; `.quotable/.gitignore` is `*\n`; the working
   directory holds only `.quotable`; an existing empty `.quotable/` is left without a
   `.gitignore` and gets only `cache/`; a named `cache_dir` is used as given, with no
   `.quotable/` created). Add the move tests (step 3). Run them and watch them fail.
2. `cache.py`: add `CACHE_DIR_NAME = "cache"` and `COST_DIR_NAME = "cost"` next to
   `DEFAULT_DIR_NAME`. Add `resolve_project_dir() -> Path`: `Path.cwd() / ".quotable"`, created
   if missing, with `.gitignore` (`IGNORE_ALL`) written only when this call created the folder.
   It raises `OSError` naming the path, as `resolve_cache_dir` does. `resolve_cache_dir(None)`
   becomes `resolve_project_dir() / "cache"`, created, then the same write probe as today. A
   named `cache_dir` takes the old code path unchanged (no project folder, no `.gitignore`).
   Update both docstrings: the module one still says "deleting the folder starts over", which
   is now "deleting `.quotable/cache/`".
3. The one-time move, inside `resolve_cache_dir(None)`, only when `.quotable/cache/` does not
   exist yet: collect the loose entries of `.quotable/` that are files named
   `<64 lowercase hex>.json` or the folder `ocr`; if there are none, do nothing. Otherwise
   create `cache/` and `os.replace` each entry into it, one at a time. `FileNotFoundError` is
   ignored (another run moved it first); any other `OSError` leaves that entry where it is and
   is counted. Count above zero prints one line to stderr (`print(..., file=sys.stderr)`, as
   `llm.py` does) saying how many entries stayed. Never touch `cost/`, `.gitignore`, `*.tmp`
   or anything else. Known and accepted by the spec: a crash mid-move, or two runs starting
   together, can leave a few answers loose, which costs a cache miss and nothing else.
4. Tests for the move: loose answers and an `ocr/` folder end up under `cache/` with the same
   bytes, and a following `extract_tables` run makes no model request (use `Calls` from
   `tests/test_entrypoint.py`: run once with the cache in the old place, then once more);
   `cost/`, `.gitignore` and an unrecognised file stay put; a second call moves nothing; a
   `.quotable/cache/` that already exists suppresses the move; an entry whose `os.replace`
   raises `OSError` (monkeypatch) stays and one warning is printed (`capsys`); an entry whose
   `os.replace` raises `FileNotFoundError` is ignored without a warning.
5. Check the other callers: `extract.py` calls `resolve_cache_dir` twice (the OCR step passes
   the already-resolved folder back in, which is a named path and must stay a no-op) and
   `tests/live/test_live_extra_fields.py` calls it once. Change the `extract_tables_async`
   docstring ("in ``cache_dir`` or else in ``.quotable/``") to say `.quotable/cache/`. Do not
   edit the README or AGENTS.md yet (task 006).
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new and updated tests pass, the rest of the suite passes unchanged, and `ty` and `ruff` are
clean. A run in an empty directory leaves `.quotable/.gitignore` and `.quotable/cache/` only.
