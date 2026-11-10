# Quickstart: checking spec 015 by hand

Run from the repository root. Everything is offline; no model is called and nothing is spent.

## All stories

```bash
just hooks    # ruff check --fix, ruff format, ty (stage new files first)
just test     # the offline suite
```

Expected: both pass. The test count is the old count (2,704) minus 57 (story 6: 55 and 2) plus the new tests
the task list names.

## Story 1: the request limit

```bash
uv run pytest tests/test_recheck_limit.py tests/steps/test_recheck.py tests/steps/test_extra_fields_recheck.py -k limit
```

Expected: the new tests pass. They run a 20-page table with a flagged cell on every page through
`recheck_table`, and extra-field values through `recheck_fields`, against a client that records how
many `ask` calls overlap. The highest overlap is 4 or less.

## Story 2: the review app renders one page at a time

```bash
uv run pytest tests/review -k render
```

Expected: 20 threads asking for pages see an overlap of 1 at most, all get a result, and a render
that raised does not block the next one.

## Story 3: the review queue

Build the demo project once (offline, about 10 s, no server), then time a repeated queue request:

```bash
uv run python -m tests.review_demo build/review-demo
uv run python - <<'PY'
import pathlib, time
from quotable.review.review import get_queue
from quotable.review.routing import Request
p = pathlib.Path("build/review-demo/.quotable")
get_queue(Request(p, (), {}, None))
t = time.perf_counter(); get_queue(Request(p, (), {}, None)); print(round(time.perf_counter() - t, 3), "s")
PY
```

Expected: at most half of the baseline, which was 0.40 s on `main` (measured 2026-11-10). To
re-measure the baseline, check out `main` in a separate folder with `git worktree add <folder> main`
and run the same script there; do not switch branches in this folder. The tests
`uv run pytest tests/review -k "cache or once"` also check that a repeated request reads no run
file and that a changed file is read again.

## Story 4: install without pandas or polars

```bash
uv run --no-dev --isolated python - <<'PY'
import sys, quotable
assert "pandas" not in sys.modules and "polars" not in sys.modules
try:
    import pandas
except ImportError:
    print("base install: no pandas, as intended")
else:
    raise SystemExit("pandas should not be installed")
PY
uv run pytest tests/test_frames.py
```

Expected: the first prints the line; the second passes with both libraries (the dev group has them).
`uv lock --check` reports the lock file is up to date.

## Story 5: the notebook note

Open `README.md` and look for the passage on notebooks and the extras table. A reader should not
need any other file.

## Story 6: housekeeping

```bash
test "$(find tests -name test_merge_checks.py | wc -l)" = 1 && echo "one copy"
grep -rn --exclude-dir=__pycache__ "equal_share\|half_equal_ok" quotable tests/*.py tests/steps
uv run python -m tests.score_merge | head -5
uv run pytest tests/test_synthetic.py tests/steps -q
```

Expected: "one copy"; the grep finds nothing in `quotable/` and the tests (the fixture's
`half_equal` probe labels live in `tests/data/synthetic/manifest.json` and in the generator, and
stay); the scorer runs without the `equal_share` rows; the fixture tests pass with the fixture
files unchanged (`git status` shows nothing under `tests/data/synthetic/`).
