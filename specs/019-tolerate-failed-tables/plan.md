# Implementation Plan: A table that fails validation no longer stops the run

**Branch**: `019-tolerate-failed-tables` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/019-tolerate-failed-tables/spec.md` (clarified 2026-11-13, two clarifications)

## Summary

Three independent pieces of work, in one spec because the user asked for them together:

1. **Failed tables (Stories 1-4).** `Table` gets a list of `Problem`s and a `failed` property. A check that today raises `ExtractionError` for one table (unusable columns after the retry, rows still invalid after the retry, a first or last row not found on a shared page, overlapping bands) records a `Problem` on that table instead. The call returns the failed table beside the sound ones and emits one `TableFailedWarning` per failed table when it fails. Reading a failed table's data (`rows()`, `page_rows()`, `records()`, `to_pandas()`, `to_polars()`, `flagged()`) returns what it holds and warns once per call. Later stages skip failed tables. Failed tables are never shown to later discovery windows as "known tables".
2. **Cache entries that say what they are (Story 6).** Each new entry gets a `_quotable` object beside the answer: stage, pages, model, time, run id and, for a retry, the key of the request it retried and the problem named. Request keys do not change, and old and new entries are read by the same code.
3. **OCR for every page without text, as a default dependency (Story 5).** Pages with no words are OCR'd before any model request, whatever their share. With `ocr=False`, a document with more than 10% empty pages is refused. `paddleocr` and `paddlepaddle` move from extras to dependencies, with environment markers for the platforms that have a PaddlePaddle wheel.

The retry of a window whose answer has unusable columns (FR-005) is already built (PR #5). This plan extends it: a second bad answer fails the table instead of raising.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`), `ty` and `ruff` as today

**Primary Dependencies**: pydantic-ai 2.54.0, pymupdf. `paddleocr==3.7.0` and `paddlepaddle==3.3.1` move into `dependencies` with markers (research 9). No other new dependency

**Storage**: the request cache (entries gain a `_quotable` key), the saved run (tables gain `failed` and `problems`, read with defaults). Both changes are additive; see [contracts/stored-files.md](contracts/stored-files.md)

**Testing**: pytest, offline, scripted clients. One opt-in live check (SC-004) that needs the user's go-ahead. `filterwarnings = error::quotable.errors.TableFailedWarning` in `pyproject.toml` makes SC-003 (no warning from a sound table) a failing test instead of a hope

**Target Platform**: any machine that runs the library. OCR runs only on macOS arm64, Linux x86_64 and Windows x86_64 with Python 3.11 to 3.13 (PaddlePaddle 3.3.1 wheels; research 9)

**Project Type**: Python library

**Performance Goals**: none new. OCR of 901 pages on a CPU has not been timed (spec: no target)

**Constraints**: the call with no failed table sends the same requests and returns equal tables (FR-012), apart from pages that are now OCR'd. Messages never contain prompts, answers, extracted values or paths. A failing display or a failing cache-detail write must not break an extraction

**Scale/Scope**: documents of about a thousand pages and dozens of tables. The failure list per table is a handful of entries

No `NEEDS CLARIFICATION` items remain. Decisions the spec left to the plan are in [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.* Constitution 1.1.0.

| Principle | Result |
|---|---|
| I. The text layer is the truth | **Met.** A failed table's values are never presented as verified: they come back only through accessors that warn, with the problems attached. Grounding and the position check do not change. More pages now have a text layer to ground against (Story 5) |
| II. Fail closed on doubt | **Met, no amendment needed.** "Loud and typed (`quotable.errors`)": `TableFailedWarning` is defined in `quotable/errors.py` and exported. "MUST NOT swallow errors that change results": nothing is swallowed; the problem stays on the table, is warned at failure and at every read, and is named in the closing message. Doubt still fails closed: a table with unusable columns is never merged, rechecked or audited. The optional wording amendment from the spec (per-table failures as warnings) is **not required** by this plan and stays unapproved |
| III. Offline-testable, live opt-in | **Met.** Every behavior is tested with scripted clients, plus a replay of the two recorded bad answers already in `tests/data/discovery_empty_columns/`. The default suite needs no PaddleOCR even though it is now a dependency (fake engine). The live check (SC-004) is opt-in and is not run without the user's go-ahead. Tests of model behavior use the real model |
| IV. One entrypoint, explicit inputs | **Met.** `extract_tables` and its arguments do not change. Public additions: `TableFailedWarning`, `Problem`, `Table.problems`, `Table.failed`. Request keys and prompts of existing requests do not change (FR-012; the one carve-out is the recheck and audit requests of pages that are now OCR'd). Cache entries and saved runs gain keys that readers old and new ignore or default, so no migration is needed (research 10, 16) |
| V. Generic by design | **Met.** Nothing is specific to one document set. The Trump report is the evidence, not a special case |
| VI. Simplicity | **Met.** One list field and one property on `Table`, one warning category, one extra key per cache entry. No new switch, no new class for a failed table, no change to the review app beyond opening such a run. Shortcuts are marked in code with `shortcut:` comments (see research) |

Technology and Security Constraints: the OCR exception of 1.1.0 covers moving PaddleOCR into `dependencies`; it is still imported only when a page needs it. The cache entry holds no prompt, image, path or credential.

Post-design re-check: unchanged, no violations. See Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/019-tolerate-failed-tables/
├── spec.md
├── plan.md              # this file
├── research.md          # decisions and the facts they rest on
├── data-model.md        # Problem, Table, Found, Request, cache entry, saved-run keys
├── quickstart.md        # how to see each story work
├── contracts/
│   ├── public-api.md    # exports, Table additions, warnings
│   ├── messages.md      # warning text, closing message, OCR progress, error texts
│   └── stored-files.md  # cache entry and saved-run additions
├── checklists/requirements.md
└── tasks.md             # made by speckit-tasks, not here
```

### Source Code (repository root)

```text
quotable/
├── errors.py            # + TableFailedWarning
├── __init__.py          # + TableFailedWarning, Problem
├── table.py             # + Problem; Table.problems, Table.failed; accessors warn once; _rows/_flagged/_records without warning
├── pipeline.py          # split sound and failed tables; location and extraction failures become problems; warn once per failed table;
│                        #   order of the returned list; OCR of empty pages in usable_layers; run id to the cache client
├── progress.py          # final(): failed tables line; OCR progress lines
├── runs.py              # tables.json and run.json: failed, problems (read with defaults); uses the quiet accessors
├── storage.py           # (unchanged; the cache entry is written by llm/client.py)
├── llm/client.py        # Request: pages, retry_of, problem; CachedClient(run_id=...) writes `_quotable`
├── steps/
│   ├── discover.py      # answer problems split into window-level and table-level; Found.problems; failed grouped by label;
│   │                    #   failed tables left out of known_tables(); retry request carries retry_of and problem
│   ├── layout.py        # table_layers raises BandError(ExtractionError) naming the labels at fault
│   ├── extract.py       # the retry request carries retry_of and problem
│   ├── merge.py         # merge_tables leaves failed tables alone
│   ├── recheck.py       # recheck_table returns a failed table unchanged
│   └── audit.py         # audit_table returns a failed table unchanged
├── text/quality.py      # empty-page share with OCR off; the message
└── ocr/
    ├── pages.py         # ocr_pages(on_page=...) progress callback
    └── paddle.py        # messages: no extra to install any more (INSTALL, the ocr-core text)
pyproject.toml, uv.lock  # paddleocr and paddlepaddle in dependencies with markers; extras removed; dev group no longer lists them
README.md, AGENTS.md     # install and GPU sections; project state, file structure
tests/
├── steps/test_discover.py, test_layout.py, test_extract.py, test_merge.py, test_recheck.py, test_audit.py   # failed-table cases
├── test_failed_tables.py          # the pipeline end to end with scripted clients (Stories 1, 2, 4)
├── test_table_warnings.py         # every accessor, sound and failed (Story 2)
├── test_replay_failed_run.py      # SC-001: the recorded bad answers replayed
├── llm/test_cache_entries.py      # Story 6
├── ocr/test_empty_pages.py, test_ocr_pipeline.py   # Story 5 (fake engine)
└── live/test_live_discovery_columns.py             # SC-004 (exists; opt-in)
```

**Structure Decision**: keep the layout of spec 012. No new module: failures are plain data on `Table`, the warning sits with the other public exception types, and each stage keeps its own file.

## Order of work

The three pieces do not depend on each other. Inside the first, each step leaves the suite green:

1. `TableFailedWarning`, `Problem`, `Table.problems` and the accessors that warn (Story 2). Testable with a hand-built failed `Table`.
2. Discovery: table-level problems become failed `Found`s; failed tables leave `known_tables()` (Stories 3, 1, clarification 2).
3. Pipeline: split sound and failed, warn once per failed table, order, closing message (Story 1).
4. Location and extraction failures (Story 4), then the stages that skip failed tables.
5. Saved run and review app opening a failed table (FR-011).
6. Cache entry details (Story 6), then OCR and the dependency change (Story 5), in either order.

## Complexity Tracking

No violations. Two choices that add code and are worth a line:

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| `BandError` subclass of `ExtractionError` in `layout.py` | The pipeline must know which tables a location failure belongs to (both, for an overlap) | A message to parse would break when the wording changes |
| Quiet accessors (`_rows`, `_flagged`, `_records`) | `records()` calls `rows()` and `to_pandas()` calls `records()`; without them one call would warn three times (FR-004 says once). The saved-run writer also reads rows and must not warn | A warnings filter inside the library would hide a user's own filter settings |
