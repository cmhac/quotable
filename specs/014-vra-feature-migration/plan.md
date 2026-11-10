# Implementation Plan: Migrate two VRA improvements (omission audit, sharp page images)

**Branch**: `spec/014-vra-feature-migration` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/014-vra-feature-migration/spec.md`

## Summary

Add an omission-audit step (`audit=True` by default) that asks the model once about a page whose
text layer prints words no extracted cell accounts for, and keeps only proposals the text layer
confirms. Add a provider-aware image policy (`sharp_images=True` by default): 300-dpi page images
with detail `original` for OpenAI, 300 dpi for Anthropic, today's image for everyone else, used by
extraction, recheck and audit, with a size check before any request. Cell values are not cleaned
(the dot and dash blanking was dropped from the spec).

Approach, from [research.md](research.md): the audit is a `Table -> Table` step in a new module,
placed after the first grounding and before the extra-field attachment and merge, that re-grounds
a table only when it accepted something. It reuses the layer, grounding and position structures
already in quotable and adds no dependency (a dozen-line edit-distance function replaces VRA's
`rapidfuzz`). The image policy is a frozen dataclass chosen once per run from the model's provider;
`Image` carries a detail value that leaves existing cache keys alone.

## Technical Context

**Language/Version**: Python 3.11 (`requires-python >=3.11`), type-checked with `ty`

**Primary Dependencies**: pymupdf 1.28.2, pydantic 2.13.5, pydantic-ai-slim 2.54.0 (all pinned, already installed). No new dependency.

**Storage**: files only: the request cache in `.quotable/cache/`, the cost log in `.quotable/cost/`, saved runs in `.quotable/runs/`. Saved-run JSON gains keys (format version unchanged).

**Testing**: pytest, offline by default with fake clients and pydantic-ai's `FunctionModel`; a live test in `tests/live/` is opt-in. The synthetic fixture (`tests/data/synthetic/`, 154 PDFs with truth files) supplies SC-002.

**Target Platform**: a Python library and a small CLI, used on a developer's machine or a server

**Project Type**: library

**Performance Goals**: the audit costs at most one model request per page; its own computation (token counts, one edit-distance pass over a page's vocabulary) must be negligible next to a model request. No latency target.

**Constraints**: offline suite stays free of network, keys and PaddleOCR; `sharp_images=False` and `audit=False` reproduce today's requests exactly; extraction memory must not grow with page count (no list of all pages at 300 dpi).

**Scale/Scope**: documents up to hundreds of pages; one audit request per page at most; 40-word and 40-cell hints per request.

## Constitution Check

*GATE: passes before Phase 0 and after Phase 1.*

| Principle | Check |
| --- | --- |
| I. The text layer is the truth | The audit adds a value only if `ground_rows` finds it `exact` or `fuzzy` in the table's layer, never `ungrounded` (with the near-spelling rule for the check only; a `fuzzy` value is flagged and goes to the recheck); added rows then go through the normal grounding, position check and recheck. Grounding is not switchable. Pass. |
| II. Fail closed on doubt | A proposal that fails any rule is rejected and recorded. An oversize page stops the run before any request. A request failure raises like any other. Pass. |
| III. Offline-testable, live opt-in | Every requirement has an offline test with a fake client. The live test is opt-in and run only with the user's go-ahead; model behavior is tested against the real model, not a scripted fake. Pass. |
| IV. One entrypoint, explicit inputs | Two keyword arguments on the existing entrypoint; no new public name. Cache keys and prompts: unchanged with both switches off (golden-key test); with the new defaults the extraction and recheck keys of the first run change, which the spec states (FR-020, FR-040). Saved-run format: additive keys read with defaults, so no migration. Pass. |
| V. Generic by design | Nothing is specific to VRA: the audit prompt and the rules name no document, column or publisher (checked in research entry 5). The requestor and roster checks stay out. Pass. |
| VI. Simplicity | No new dependency, setting or public type. The constants are code constants. One new step module and one small image module. Pass. |

**Complexity Tracking**: no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/014-vra-feature-migration/
├── plan.md              # this file
├── research.md          # decisions and alternatives
├── data-model.md        # new and changed structures
├── quickstart.md        # how to check it works
├── contracts/
│   └── public-api.md    # what a user sees change
├── checklists/
│   └── requirements.md  # spec quality checklist (done)
└── tasks.md             # speckit-tasks, not created by this command
```

### Source code (repository root)

```text
quotable/
├── pipeline.py          # audit/sharp_images arguments; image policy and size check; audit step; recheck gets the policy; run settings
├── table.py             # AuditItem, Table.audit, OutputNames.audit, records() and frames column audit_added
├── runs.py              # RunInfo.audit/.sharp_images; settings; tables.json "audit"; RunTable.audit; tolerant reader
├── storage.py           # CostRecord.stage comment lists "audit"
├── llm/
│   ├── client.py        # Image.detail; fingerprint adds a non-"high" detail; PydanticAIClient uses it; Request.stage comment
│   ├── answers.py       # MissingRow, FilledCell, Omissions
│   └── images.py        # NEW: ImagePolicy, TODAY, policy_for, check_page_sizes
└── steps/
    ├── audit.py         # NEW: unexplained words, furniture, request, judging, applying, audit_table
    ├── extract.py       # render_png(page, dpi); extract_page(detail=...)
    ├── recheck.py       # recheck_table(images=...), image rendered at the policy's dpi
    └── merge.py         # merge_pair carries audit

tests/
├── llm/test_images.py            # NEW: policy by provider, size check, Image.detail and cache keys
├── steps/test_audit.py           # NEW: the audit's pure parts and audit_table with a fake client
├── test_audit_pipeline.py        # NEW: the step inside the pipeline; multi-table pages; budget; cost stage; SC-002 on the synthetic fixture
├── test_audit_output.py          # NEW: records()/frames column, collisions, merge carry, saved runs (new and old)
├── test_entrypoint.py            # defaults of the public function; golden request key
├── conftest.py                   # extract_tables helper gets audit=False passthrough
├── live/test_live_audit.py       # NEW: opt-in real-model run producing the SC-005 numbers
└── (existing tests)              # those that count requests through the public function pass audit=False

README.md                          # audit, sharp_images with the provider table and the "verified for OpenAI only" note, first-run cache note, dots and dashes kept
AGENTS.md                          # project state, file structure, spec 014
```

**Structure Decision**: follow the existing layout. The audit is a pipeline stage, so it goes in
`quotable/steps/` next to `recheck.py`; the image policy is about talking to the model, so it goes
in `quotable/llm/`. Tests mirror the package.

## Design

### The audit step (`steps/audit.py`)

`audit_table(table, pdf, client, images, gate) -> Table`:

1. For each page of the table, take `layer = table.layers[page]` and the page's rows. The columns
   a page prints are `table.columns` minus the page's `absent`.
2. `unexplained(layer, rows, names)` returns `(token, word id)` for each layer token left over after
   removing, one for one, the tokens of the cells. `furniture(table)` is the set of tokens
   unexplained on at least 30% of the table's pages (only when it has five or more pages). Words =
   unexplained tokens not in the furniture set, by word, in reading order.
3. A page with no words is skipped. Otherwise build the request: the numbered column structure,
   the page image at `images.dpi` with `images.detail`, one text part with the listed rows
   (numbered from 1), the words (at most 40) and the empty-cell hints (at most 40, from
   `PageGrounding.row_windows` and `column_ranges`), stage `audit`, output `Omissions`.
4. Ask through `client` inside `gate`. Judge each answer with the rules of FR-006 and FR-007,
   recording an `AuditItem` for every proposal.
5. Apply accepted fills, then accepted rows (inserted after the row each names), build the new
   `PageResult` list, and if anything was accepted ground the table again with `ground_document`.
   Return `replace(table, pages=..., grounded=..., position=..., audit=items)`; a table with
   nothing accepted is returned with only `audit` set.

Pure functions (testable without a client): `unexplained`, `furniture`, `near_word` (the small edit
distance), `judge_cell`, `judge_row`, `apply`, `hints`, `build_request`.

### The image policy (`llm/images.py`)

As in `data-model.md`. `run_pipeline` calls `check_page_sizes(pdf, images)` right after the text-layer
check, before rendering or any request. `extract_page` takes `detail` and renders happen at
`images.dpi` in three places: the extraction of a page (inside `one()`), `recheck_table`, and the
audit. Discovery and the extra-field stages keep using the existing 150-dpi `pngs`.

### Pipeline order

`text layers (and OCR)` → `size check` → `discovery` → `layouts` → `extract` (sharp) → `ground` →
**`audit`** (sharp) → `extra fields` → `merge` → `recheck` (sharp). The audit gate is the same
semaphore the extraction uses.

### Defaults

`extract_tables` / `extract_tables_async`: `audit=True`, `sharp_images=True`; they build
`images = policy_for(model, sharp_images)` and pass `audit` and `images` to `run_pipeline`, which
defaults to `audit=False, images=TODAY` so its many internal callers and tests keep today's
behavior. `_save_run` receives both settings.

### Tests that need `audit=False`

Tests that go through the public function with a model that counts or scripts requests
(`test_entrypoint`, `test_cache`, `test_costs`, `test_save_runs`, `test_runs`, `test_frames`,
`test_ocr_pipeline`, `test_extra_fields_pipeline`, `test_tables`, `test_senate_tables`,
`tests/review/test_browse_api`, `tests/steps/test_recheck`, `tests/review_demo.py` and the live
tests) are found by running the suite after the change and get `audit=False` where a stage they
do not expect would break them. Each is a one-argument edit that leaves what the test checks
unchanged. The default itself is tested separately.

### Risks and open points

- **Cost.** The audit is on by default and, with page numbers counting, may audit almost every
  page. The live run (SC-005) measures it. Nothing in the code depends on the result.
- **First run after upgrading** re-pays extraction and recheck for already-cached documents (the
  images changed) and pays the new audit. README says so.
- **Anthropic and other providers** are unverified (OpenAI is the only one the user has seen
  work). README says so (FR-040).
- **Google.** quotable already sets `detail: high` for every provider and pydantic-ai's Google
  model builds `VideoMetadataDict(**vendor_metadata)` from it for binary content. Whether that
  already fails was not run. This plan leaves it alone, as the spec says; `Image.detail` keeps the
  same value (`high`) for Google.
- **Row renumbering.** Turning the audit on can renumber rows after an added one on a reviewed
  document. Stale verdicts are the existing protection (spec assumption).
