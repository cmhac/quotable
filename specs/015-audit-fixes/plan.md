# Implementation Plan: Audit fixes

**Branch**: `spec/015-audit-fixes` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-audit-fixes/spec.md`

## Summary

Seven small, independent fixes from the 2026-11-10 audit. None adds a feature, an option or a
public name. Each one is the smallest change that meets its requirements; the decisions and the
alternatives rejected are in [research.md](research.md).

| Story | Change |
|-------|--------|
| 1 (finding 3) | The recheck uses the run's one 4-request semaphore. `recheck_table` and `recheck_fields` take it as an argument (as `audit_table` already does), and `resolve_extra_fields` receives it instead of making its own. The recheck renders each page inside the limited task, so at most 4 page images exist at a time. |
| 2 (finding 2) | One module-level `threading.Lock` in `quotable/review/sources.py` around the PyMuPDF open and render in `page_png`. |
| 3 (finding 4) | The parsed-run cache in `sources.py` is bounded by the size of the run files (64 MiB) instead of a count of 4. `get_queue` builds the item list once instead of twice. |
| 4 (finding 11) | pandas and polars move from `dependencies` to optional extras `pandas` and `polars`, and into the `dev` group. `to_pandas()` and `to_polars()` raise an `ImportError` that names the install line. |
| 5 (finding 9) | A README passage. The existing test `test_the_pdf_can_be_a_string_and_the_async_twin_works` already awaits `extract_tables_async` inside a running loop, so no new test is needed. |
| 6 (finding 6) | `git rm tests/test_merge_checks.py` (byte-identical to `tests/steps/test_merge_checks.py`). |
| 6 (finding 7) | Remove the half-equal rule from `quotable/steps/merge.py` and its unit test and scorer rows. Fixture files are not touched. |

## Technical Context

**Language/Version**: Python 3.11+ (3.11.14 in the dev environment)

**Primary Dependencies**: unchanged, except pandas and polars become optional extras (story 4)

**Storage**: unchanged. `.quotable/` layout, saved-run format, verdict files and cache keys do not
change. No data design is needed, so there is no `data-model.md`.

**Testing**: pytest (offline). `ruff` and `ty` through `just hooks`. New tests are offline and use
fakes only for deterministic code (a request probe, a fake render), never to stand in for model
behavior.

**Target Platform**: library plus a local web app on 127.0.0.1

**Project Type**: library with a CLI and a local review app

**Performance Goals**: a repeated queue request on the 8-document demo project takes at most half
as long as on `main` (SC-003). Expected: about 0.4 s to about 0.15 s (reading runs 0.18 s and the
second item-list build 0.13 s go; the profile numbers are in [research.md](research.md)).

**Constraints**: at most 4 model requests in flight in a run (SC-001); at most one PyMuPDF render
at a time in the review app (SC-002); at most 64 MiB of run files cached, about 320 MB parsed
(FR-007).

**Scale/Scope**: one analyst and one reviewer; up to about 50 documents per project.

## Constitution Check

*GATE: passes before research and again after design. No violations; Complexity Tracking is empty.*

| Principle | Check |
|-----------|-------|
| I. The text layer is the truth | Not touched. The recheck sends the same requests with the same content and the same answers are applied. |
| II. Fail closed on doubt | The `ImportError` is loud and says what to install. The render lock is released on failure (`with` block). A removed merge check changes no decision (research R7), so the merge still refuses on doubt. |
| III. Offline-testable | Every new test runs offline. No live run is needed or requested. |
| IV. One public entrypoint | `quotable/__init__.py` is unchanged. Prompts, cache keys and the saved-run format are unchanged, and a test asserts the recheck sends the same requests as before. The extras change what `pip install` brings, not the API. |
| V. Generic by design | Nothing document-specific. |
| VI. Simplicity | Each fix is the smallest that meets its requirement. The larger refactor of putting one limit inside `CachedClient` was considered and rejected for now (research R1). |
| Technology constraints | pandas and polars stay ranges and stay imported inside the methods that use them. |
| Workflow | `AGENTS.md` is updated in the same change (project state, test count, dependencies, `equal_share` mention). The constitution needs no amendment. |

## Project Structure

### Documentation (this feature)

```text
specs/015-audit-fixes/
├── plan.md              # this file
├── research.md          # decisions, measurements and rejected alternatives
├── quickstart.md        # how to check each story by hand
├── contracts/
│   └── install-and-errors.md   # the only outward-facing changes: extras and the ImportError
├── checklists/requirements.md
└── tasks.md             # created by speckit-tasks, not by this command
```

### Source Code (repository root)

```text
quotable/
├── pipeline.py              # pass the run's gate to resolve_extra_fields and recheck_table
├── steps/
│   ├── recheck.py           # recheck_table, recheck_fields take the gate; render inside it
│   └── merge.py             # remove equal_share, half_equal_ok, the half_equal branch, import math
├── table.py                 # to_pandas / to_polars: ImportError with the install line
└── review/
    ├── sources.py           # render lock; run cache bounded by bytes
    ├── queue.py             # expose the item list builder so get_queue builds it once
    └── review.py            # get_queue builds the list once
pyproject.toml               # extras pandas / polars; dev group gains both
uv.lock                      # re-locked, not hand-edited
README.md                    # extras install lines; notebook passage
AGENTS.md                    # project state, test count, dependencies
tests/
├── test_merge_checks.py     # DELETED (duplicate)
├── steps/test_merge_checks.py   # remove the half-equal test, import and default assertion
├── steps/test_recheck*.py, test_extra_fields_recheck.py   # new gate argument; limit tests
├── review/                  # render-lock test; run-cache tests; items-built-once test
├── test_frames.py           # ImportError tests
├── test_synthetic.py        # reword the half-equal test
└── score_merge.py           # drop the equal_share rows of the sweep
```

**Structure Decision**: no new modules. Everything is an edit to an existing file. The package
layout from spec 012 is unchanged.

## Order of work

The stories are independent. Suggested order by risk: story 1, story 2, story 3, story 6 (both
parts), story 4, story 5. Stories 1 to 3 each ship with their tests first (the test must fail on
`main`, then pass). Story 4 touches `uv.lock` and needs the network or a warm uv cache; do it last
so a locking problem does not block the rest.

## Risks and how the plan handles them

- **Re-locking needs the network.** `uv lock` may need PyPI. If it cannot run offline, the task
  stops and says so; `uv.lock` is never hand-edited.
- **Finding 2 and finding 3 were never reproduced.** The tests prove the new behavior (one render
  at a time, never more than 4 requests in flight), not that a crash or a rate limit happened
  before. The spec says this under Assumptions.
- **`pip install quotable` no longer brings pandas.** This is the one change a current user can
  notice. The error message names the fix, the README shows it, and the next release is a minor
  version (outside this spec).
- **Spec 007's half-equal score rows can no longer be reproduced.** Accepted in Question 1,
  option A. Spec 007 is not edited.

## Complexity Tracking

No constitution violations to justify.
