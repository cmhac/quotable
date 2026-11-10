---

description: "Task list for spec 014: omission audit and sharp page images"
---

# Tasks: Migrate two VRA improvements (omission audit, sharp page images)

**Input**: Design documents from `specs/014-vra-feature-migration/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md, quickstart.md (all present)

**Tests**: Required. The constitution (III) and FR-041 say new logic ships with offline tests using fake clients. Write each story's tests first and watch them fail. The live test (T029) is opt-in.

**Baseline (T001, 2026-11-10)**: `just lint` and `just typecheck` pass; `just test` runs 2,430 passed in 43 s (`-n 4`).

**Organization**: by user story. US1 is the omission audit (P1, MVP). US2 is sharp page images (P2). The spec's third story (blank dot and dash cells) was dropped by the user; FR-030 and SC-007 (cells of only dots or dashes stay as extracted) are covered by a test in US1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 or US2
- Paths are from the repository root. Commit after each task or small group, on `spec/014-vra-feature-migration`; do not push.

---

## Phase 1: Setup

- [x] T001 Confirm the branch is `spec/014-vra-feature-migration` and run `just test`; write the number of passing tests and that `just lint` and `just typecheck` pass into the header of `specs/014-vra-feature-migration/tasks.md` as the baseline (the plan expects every later run to match it, plus the new tests).
- [x] T002 Add `test_request_key_is_unchanged` to `tests/test_cache.py`: build a fixed `Request` (stage `extract`, instructions `"x"`, output type `PageRows`, parts `["text", Image(b"png-bytes")]`), compute `request_key("fake", request)` on the code as it is now, and assert the printed hex digest as a literal. Run it once before any other change so the constant is the pre-change key (SC-001, FR-020).

---

## Phase 2: Foundational (blocks both stories)

**Purpose**: the small shared pieces both the audit and the sharp images use.

- [x] T003 [P] Add `MissingRow` (`after_row: int`, `values: dict[str, str]`), `FilledCell` (`row: int`, `column: str`, `value: str`) and `Omissions` (`missing_rows: list[MissingRow]`, `filled_cells: list[FilledCell]`) to `quotable/llm/answers.py`, with the field descriptions of `data-model.md` ("number of the listed row it follows, 0 = before the first"; "number as listed, from 1").
- [x] T004 [P] In `quotable/llm/client.py` add `detail: str = "high"` to `Image`; make `_fingerprint` add the detail to the image's fingerprint only when it is not `"high"`; make `PydanticAIClient.ask` set `vendor_metadata={"detail": p.detail}` instead of the literal; add `audit` to the `Request.stage` comment. Add `audit` to the stage comment in `quotable/storage.py` (`CostRecord.stage`). Tests in `tests/llm/test_images.py` (new file): an `Image(png)` key equals the key before the change (use T002's constant), `Image(png, "original")` differs, and the client sends the image's detail (use the existing fake-model pattern in `tests/llm/test_model.py`).
- [x] T005 [P] Create `quotable/llm/images.py` with `ImagePolicy` (frozen dataclass: `dpi: int`, `detail: str`, `max_patches: int | None`, `max_side: int | None`) and `TODAY = ImagePolicy(150, "high", None, None)`; nothing else yet (T022 adds the rest).
- [x] T006 [P] In `quotable/steps/extract.py` change `render_png(page)` to `render_png(page, dpi=DPI)` and give `extract_page` a `detail: str = "high"` argument used for its `Image(png, detail)`. Tests in `tests/test_extract.py`: the default call renders and sends exactly what it did, and `detail="original"` reaches the request's `Image`.

**Checkpoint**: `just test` passes with the T001 baseline plus the new tests.

---

## Phase 3: User Story 1 - Find rows and cells the model left out (P1) 🎯 MVP

**Goal**: pages with unexplained words are audited once; proposals the text layer confirms are added; the result is marked and reported; `audit=False` changes nothing.

**Independent Test**: a fake model drops the last row of each page of a synthetic-fixture document and returns it when audited; the row is back in page order, `audit_added == "row"`, grounding `exact`. A fake that proposes a row not on the page adds nothing.

### Tests for User Story 1 (write first, they must fail)

- [x] T007 [P] [US1] Create `tests/steps/test_audit_rules.py` for the pure parts of `quotable/steps/audit.py`: `unexplained` (one-for-one token matching, dots-only cell makes no token); `furniture` (a token unexplained on at least 30% of the pages counts only when the table has "at least five pages"; with four pages nothing is furniture); `near_word` ("a word of five or more letters may differ from a page word by up to two letters" with insert, delete, substitute and one adjacent swap; a token with a digit must match exactly; ambiguity keeps the token); `judge_row` and `judge_cell` give each outcome of `data-model.md` (`accepted`, `invalid_row`, `invalid_cell`, `duplicate`, `not_empty`, `repeated`, `ungrounded`, `no_evidence`, `empty`); `apply` (fills before inserts, `after_row` 0, several rows after the same row keep the model's order, existing values never change: FR-005); `hints` (a word centred in an empty cell's row window and column range is named; at most 40); `build_request` (stage `audit`, output `Omissions`, part order: numbered column structure, image, one text part; at most 40 words).
- [x] T008 [P] [US1] Create `tests/steps/test_audit.py` for `audit_table` with a recording fake client: a page with no unexplained word makes no request; a page with some makes exactly one; accepted proposals re-ground the table and the added row is `exact`; nothing accepted returns the table unchanged except `audit`; every proposal is in `Table.audit` with its outcome; a dots-only and a dash-only cell come through unchanged and are not audited as empty cells (FR-030, SC-007); words outside a shared page's band do not count (FR-002, scenario 6).
- [x] T009 [P] [US1] Create `tests/test_audit_output.py`: `records()[i]["audit_added"]` is `"row"`, `"cells: <columns in table order>"` or `""`; it is the last column and no earlier column moved; a PDF column named `audit_added` keeps its name and the library's becomes `audit_added_`; `to_pandas()` and `to_polars()` carry it as a string; `merge_pair` keeps `[*a.audit, *b.audit]`; a saved run holds `audit` per table and `settings.audit`; a run file written without those keys (copy a fixture run and delete them) still loads with `audit == []` (FR-012).
- [x] T010 [P] [US1] Create `tests/test_audit_pipeline.py`: through `run_pipeline(..., audit=True)` the order is extract, audit, merge, recheck; `audit=False` makes no `audit` request (FR-001); audit requests count toward `max_requests` (`BudgetExceededError`) and are recorded with stage `audit` in the cost log; SC-002 on the synthetic fixture: for each document in `tests/fixture_tables.py` with one part per page, a fake model drops each page's last row on the first pass and returns it when audited, 100% of dropped rows are restored and a document with nothing dropped gets 0 added rows; SC-003: every kept value is found in the layer; through `extract_tables` with a `FunctionModel`, the default is `audit=True` (an `audit` request is made on a page with a title).

### Implementation for User Story 1

- [x] T011 [US1] In `quotable/table.py` add `AuditItem` (`page: int`, `kind: Literal["row", "cell"]`, `values: dict[str, str]`, `outcome: str`, `row: int | None = None`), `Table.audit: list[AuditItem]` (default empty, next to `proposals`), `OutputNames.audit` (`audit_added`, made free like its neighbours, after `changes`), the `audit_added` value in `records()` ("row", "cells: <a>, <b>" in column order, or ""), and the column last in `_frame_columns()` with kind `"str"`. Existing columns and their order must not change (FR-010).
- [x] T012 [US1] In `quotable/steps/merge.py` make `merge_pair` carry `audit=[*a.audit, *b.audit]` and update its docstring ("The recheck has not run yet" stays true; the audit has).
- [x] T013 [US1] Create `quotable/steps/audit.py` with the pure parts: `unexplained`, `furniture` (30%, five pages), `near_word` (own optimal-string-alignment distance, no `rapidfuzz`), `judge_row`, `judge_cell`, `apply`, `hints` (from `PageGrounding.row_windows` and `column_ranges`, at most 40), `build_request` and the prompt text of research entry 5 (VRA's audit prompt, the word hint, the empty-cell hint, and the position rule). Constants at the top: `FURNITURE_SHARE = 0.3`, `FURNITURE_MIN_PAGES = 5`, `HINT_MAX_WORDS = 40`, `CELL_HINT_MAX = 40`, `NEAR_EDITS = 2`, `NEAR_MIN_LEN = 5`. Makes T007 pass.
- [x] T014 [US1] In `quotable/steps/audit.py` add `async def audit_table(table, pdf, client, images, gate) -> Table` as designed in `plan.md`: skip pages without words, render the page at `images.dpi` and send it with `images.detail`, ask inside `gate`, judge every proposal, apply, re-ground with `ground_document` only if something was accepted, return `replace(table, ..., audit=items)`. Makes T008 pass.
- [x] T015 [US1] In `quotable/pipeline.py` add `audit: bool = False` and `images: ImagePolicy = TODAY` to `run_pipeline`, call `audit_table` for every table right after `ground_document` and before the extra-field attachment (same `gate` as extraction), log one line (pages audited, rows and cells kept), and update the module docstring's step list. Add `audit: bool = True` to `extract_tables_async` and `extract_tables` (docstring: what it does, cost, default on) and pass it on; pass `audit` to `_save_run`. In `tests/conftest.py` add `audit: bool = False` to the `extract_tables` helper and pass it to `run_pipeline`.
- [x] T016 [US1] In `quotable/runs.py` add `audit: bool` to `RunInfo`, write it in `_settings()`, write each table's `"audit"` (list of `asdict(item)`) in `_table_data()`, add `audit: list[dict[str, Any]]` to `RunTable`, read it with `data.get("audit", [])` in `_run_table`, and update the module docstring. `FORMAT_VERSION` stays 1. Makes T009 pass.
- [x] T017 [US1] Run `just test`; for every test that goes through the public function with a model that counts or scripts requests and now fails on the new `audit` stage, pass `audit=False` (expected: `tests/test_entrypoint.py`, `test_cache.py`, `test_costs.py`, `test_save_runs.py`, `test_runs.py`, `test_frames.py`, `test_ocr_pipeline.py`, `test_extra_fields_pipeline.py`, `test_tables.py`, `test_senate_tables.py`, `tests/review/test_browse_api.py`, `tests/steps/test_recheck.py`, `tests/review_demo.py`). Do not change what any of them checks. Add one test in `tests/test_entrypoint.py` that the default is `audit=True`.

**Checkpoint**: `just check` passes. US1 works on its own with `sharp_images` not yet present.

---

## Phase 4: User Story 2 - Make small print readable to the model (P2)

**Goal**: extraction, recheck and audit use the provider's sharp image by default; `sharp_images=False` gives today's requests; an oversize page stops the run before any request.

**Independent Test**: with an OpenAI-shaped policy the three stages send a 300-dpi image with detail `original` and discovery sends today's; with `TODAY` every key equals the pre-change key.

### Tests for User Story 2 (write first)

- [ ] T018 [P] [US2] Extend `tests/llm/test_images.py`: `policy_for` returns `(300, "original", 30_000, None)` for `"openai:x"`, `"openai-chat:x"`, `"openai-responses:x"` and an OpenAI `Model` instance; `(300, "high", None, 8_000)` for `"anthropic:x"` and an Anthropic instance; `TODAY` for `"bedrock:x"`, `"google-gla:x"`, a `FunctionModel`, and for any model when `sharp` is false. `check_page_sizes`: a Letter page passes both; a page of 40 by 40 inches fails OpenAI (`ceil(w/32) * ceil(h/32)` over 30,000) and Anthropic (side over 8,000); a rotated page is measured rotated; `TODAY` never raises; the message names the page, its size in pixels and `sharp_images=False`.
- [ ] T019 [P] [US2] Create `tests/test_sharp_images_pipeline.py`: with an OpenAI-shaped `ImagePolicy` and a recording fake client, the extract, recheck and audit requests carry a 300-dpi `Image` with detail `original` (compare decoded pixel width to the page width at 300 dpi) and the `schema` (discovery) request carries the 150-dpi image with detail `high`; with `TODAY` the extraction request keys equal those of a run on the code before this change (SC-001); an oversize page raises `ExtractionError` and the fake client fails the test if asked anything (SC-006); through `extract_tables` with `OpenAIChatModel` monkeypatched into `PydanticAIClient`'s place, check `run_pipeline` receives `policy_for(model, True)` by default and `TODAY` with `sharp_images=False`; `Table`s from a `FunctionModel` run use `TODAY` (SC-004).

### Implementation for User Story 2

- [ ] T020 [US2] In `quotable/llm/images.py` add `policy_for(model, sharp)` (provider = text before `:` of `model_name(model)`; OpenAI is `openai`, `openai-chat`, `openai-responses`; Anthropic is `anthropic`; the table of `contracts/public-api.md`) and `check_page_sizes(pdf, policy)` (page rectangle with rotation times `dpi / 72`, rounded up; first page over `max_patches` or `max_side` raises `ExtractionError`; a policy with neither limit does nothing). Makes T018 pass.
- [ ] T021 [US2] In `quotable/steps/recheck.py` give `recheck_table` an `images: ImagePolicy = TODAY` argument: render with `render_png(document[n - 1], images.dpi)` and pass `images.detail` into `_request`'s `Image`. `recheck_fields` is not changed (spec FR-022). Extend `tests/steps/test_recheck.py` for the default and for a sharp policy.
- [ ] T022 [US2] In `quotable/pipeline.py` make `run_pipeline` call `check_page_sizes(pdf, images)` right after the text-layer check and before rendering or any request; make the per-page extraction (`one()`) render its page at `images.dpi` from the PDF and pass `detail=images.detail`; pass `images` to `audit_table` and `recheck_table`; keep `pngs` (150 dpi) for discovery and the extra-field stages. Add `sharp_images: bool = True` to `extract_tables_async` and `extract_tables`, build `images = policy_for(model, sharp_images)`, pass it on, and pass `sharp_images` to `_save_run`. Update the module docstring. Makes T019 pass.
- [ ] T023 [US2] In `quotable/runs.py` add `sharp_images: bool` to `RunInfo` and write it in `_settings()`; extend `tests/test_runs.py` so a saved run's `settings` holds `audit` and `sharp_images` (FR-024) and a run without them still loads.
- [ ] T024 [US2] Run `just test` and fix any test that the new default changes (expected: none, because the offline models are not OpenAI or Anthropic).

**Checkpoint**: `just check` passes. Both stories work.

---

## Phase 5: Polish and cross-cutting

- [ ] T025 [P] Update `README.md` (FR-040): the audit (what it does, one request per page with unexplained words, `audit=False`); `sharp_images` with the provider table of `contracts/public-api.md`; the note that sharp images are **verified to work with OpenAI only**, unverified on Anthropic (the provider downsizes large images, image tokens can rise on Claude 4.7 and later) and unchanged on other providers; the first-run cache note; that a cell of only dots or dashes is kept as extracted; the new `audit_added` column in the output section; the pipeline table gets an Audit row.
- [ ] T026 [P] Update `AGENTS.md` (constitution: same change): project state (spec 014 implemented, the two defaults, the test count), the file structure (`quotable/steps/audit.py`, `quotable/llm/images.py`, the new test files, `tests/live/test_live_audit.py`), the spec list (014 uses the Spec Kit layout), and the `Not yet ported` list if it changes.
- [ ] T027 [P] Create `tests/live/test_live_audit.py` (marker `live`, skipped without `OPENAI_API_KEY` and `QUOTABLE_LIVE_TEST_MODEL`): run one real multi-page document from `tests/data/` four ways (audit off and on, sharp images off and on, cache dir per variant) and print pages audited out of pages, audit requests, rows and cells kept and rejected (from `Table.audit`), flagged cells, and tokens from `.quotable/cost/`. It asserts only that nothing kept breaks FR-006.
- [ ] T028 Run `just check` (hooks, then tests); stage new files by name first so the hooks see them. Fix whatever it reports. Ruff, ty and every offline test must pass.
- [ ] T029 With the user's go-ahead, run `just test-live tests/live/test_live_audit.py`, copy the numbers into a new "Live results" section of `specs/014-vra-feature-migration/spec.md` (SC-005), run `uv run quotable cost-report` and say plainly that its prices have still not been compared with the provider's dashboard unless the user does so. Do not run it without the go-ahead.
- [ ] T030 Run `speckit-converge` and append any unbuilt work to this file; repeat implement and converge until it reports Converged. The user then reviews the changes.

---

## Dependencies and order

- Phase 1, then Phase 2, then US1, then US2, then Polish. US2 needs US1 only because both edit `pipeline.py` and `runs.py` and the audit takes the image policy; run them in that order.
- Inside Phase 2: T003 to T006 touch different files and run in parallel; T002 must come first of all.
- Inside US1: tests T007 to T010 in parallel (different files); T011 and T012 before T013 only for types; T013 then T014; T015 needs T014; T016 needs T011; T017 last.
- Inside US2: T018 and T019 in parallel; T020 first, then T021 and T023, then T022 (needs both), then T024.
- Polish: T025 to T027 in parallel after US2; T028 after them; T029 needs the user; T030 last.

## Parallel examples

```text
After T002:   T003, T004, T005, T006
US1 tests:    T007, T008, T009, T010
US2 tests:    T018, T019
Polish docs:  T025, T026, T027
```

## Implementation strategy

- **MVP**: Phases 1 to 3. The audit alone delivers the spec's main gain (no silent missing rows) and ships on its own; sharp images follow as a separate increment.
- **Incremental**: finish and check each phase with `just check` before the next. Keep commits small (one per task or pair) on `spec/014-vra-feature-migration`.
- **Not in scope**: gold scoring and annotation, the requestor and roster checks, anything in `scripts/` of the VRA project, display of audit marks in the review app, and cleaning dots or dashes.
