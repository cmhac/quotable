# 003 - Model answers are always cached, in `.gridkey/`

Spec: `../spec.md` (Requirement 11, the model-answer part; Design / Flow, Modules `cache.py`;
Tests, default cache location). Depends on: nothing.

## Goal

Every run caches model answers on disk, in `.gridkey/` in the current directory or in
`cache_dir`. There is no in-memory mode. This task does not touch OCR; the OCR cache (task 005)
builds on the directory rule written here.

## Steps

1. New `src/gridkey/cache.py`:
   - `resolve_cache_dir(cache_dir: str | Path | None) -> Path`: the argument, else
     `Path.cwd() / ".gridkey"`. Creates the directory (with parents). When gridkey creates the
     default `.gridkey/` itself, write `.gridkey/.gitignore` containing `*`; a directory the
     user named is not given one, and an existing `.gridkey/` is not touched. If the directory
     cannot be created or written (check with a real write, not `os.access`), raise `OSError`
     that names the path and says to pass `cache_dir`.
   - `write_atomic(path, data)`: move `_write_atomic` out of `llm.py` (same behaviour: temp
     file in the same directory, then rename) and import it back in `llm.py`.
2. `llm.py`: `CachedClient.cache_dir` becomes `Path` (required). Remove the `None` branches.
   File names, keys and layout of model-answer files do not change, so existing caches stay
   valid. `max_requests` still caps only new requests. Update the module docstring.
3. `extract.py`: `extract_tables_async` calls `resolve_cache_dir(cache_dir)` once and passes the
   result to `CachedClient`. Keep the `cache_dir: str | Path | None = None` signature (`None`
   now means "use the default"). Update the docstrings that say caching is optional.
4. `.gitignore`: add `.gridkey/`.
5. `tests/conftest.py`: an autouse fixture that `monkeypatch.chdir`s every test into
   `tmp_path`, so no test writes `.gridkey/` into the repo. Check that tests which use relative
   paths to `tests/data/` use absolute paths (fix them if not).
6. Tests:
   - `test_entrypoint.py`: "a second run with a `cache_dir` makes no request" becomes "a second
     run makes no request, with or without `cache_dir`"; the `max_requests` test is
     parametrised on default directory vs explicit directory (no `use_cache=False` case).
   - `test_llm.py`: cases that built `CachedClient` with `None` pass a temp directory.
   - New `tests/test_cache.py`: default location is `./.gridkey/` and holds `.gitignore` with
     `*` and the model-answer files; a named `cache_dir` gets the files, no `.gitignore`, and
     nothing is created in the working directory; an existing `.gridkey/` is not given a
     `.gitignore`; a relative `cache_dir` resolves against the working directory; an
     unwritable directory raises `OSError` naming the path; a corrupt cache file is a miss and
     is overwritten; the atomic write leaves no temp file behind.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All offline tests pass, `git status` after `just test` shows no `.gridkey/` in the repo, and a
second run of the same extraction makes zero new model requests with no `cache_dir` argument.
