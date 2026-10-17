# 005 - The `quotable cost-report` command

Spec: `../spec.md` (Requirements 10 and 11; Design / Code; Tests / CLI). Depends on: task 003.

## Goal

`quotable cost-report` prints the report. It never calls a model, needs no key and creates
nothing.

## Steps

1. Red first: `tests/test_cli.py`, failing.
2. New `src/quotable/cli.py`: `main(argv: list[str] | None = None) -> int` with `argparse`
   (`prog="quotable"`), a required sub-command `cost-report` and `--dir PATH` (default: the
   `.quotable` folder in the working directory; the cost file is `<dir>/cost/requests.jsonl`).
   Never use `resolve_project_dir()` here: it creates folders. It prints `format_report(...)`
   to stdout and returns 0, also for "no cost records". An `OSError` from `summarize` prints
   `quotable: cannot read <path>: <reason>` to stderr and returns 1. A usage error is
   argparse's own exit 2. Imports: the standard library and `quotable.costs` only.
3. New `src/quotable/__main__.py`: `raise SystemExit(main())`.
4. `pyproject.toml`: add `[project.scripts]` with `quotable = "quotable.cli:main"`, then
   `uv sync` so the script exists in `.venv/bin`. Check that `uv lock` changes nothing in
   `uv.lock` beyond what the entry point needs (normally nothing).
5. Tests (in-process through `main([...])` and `capsys`, working directory is the autouse temp
   directory): a hand-written `.quotable/cost/requests.jsonl` gives the report on stdout and
   exit 0; `--dir` reads another folder; no `.quotable/` prints the no-records text and exit 0
   and creates nothing (compare the directory listing before and after); the same for a folder
   with an empty file; a damaged line is reported and the rest summed; `--dir` pointing at a
   file, or a `cost/requests.jsonl` that is a directory, exits 1 with the path in stderr; an
   unknown option and a missing sub-command exit 2; `quotable.__all__` is unchanged.
   Subprocess tests: `sys.executable -m quotable cost-report` and the installed `quotable`
   script next to `sys.executable` both print the same report for the same folder.
6. The module-level imports of `cli.py` and `costs.py` are stdlib plus `quotable.*` only: test
   it by parsing their source with `ast`. The spec's Requirement 11 says the command does not
   import pandas, polars, PyMuPDF or pydantic-ai, but `import quotable.cli` first runs
   `quotable/__init__.py`, which loads the pipeline (the spec says making that lazy is out of
   scope), so `sys.modules` cannot be asserted clean; the source check is what holds.
7. Measure and report: best of three `time uv run quotable cost-report` in an empty folder,
   and `python -X importtime -c "import quotable.cli"` total. These numbers go in the task
   report; no threshold.
8. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, the existing suite passes unchanged, `ty` and `ruff` are clean, and
`uv run quotable cost-report` works in an empty folder and in a folder with a cost file.
