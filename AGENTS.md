# Instructions for AI agents working in this repo

> CRITICAL: This document must be updated regularly to reflect changes to the codebase. Failure to do so may result in AI agents operating with outdated or incorrect instructions. This document is not intended to be a full record of every change made, but rather a high-level overview of the key instructions and guidelines for AI agents working in this repository.

## Project introduction

`gridkey` is a small Python library that extracts tables from PDFs with a vision LLM and then checks every extracted value against the PDF's own text layer. The pipeline is: schema discovery, per-page layout discovery, per-page extraction, grounding (each value is looked up in the text layer), a position check (a value must sit in its own row and column), and a recheck of flagged cells. It is generic (not specific to any one document set) and was distilled from `scripts/extraction/extract_included_projects.py` in the VRA community-projects repository, which remains the reference for anything not yet ported.

## Project state

An initial, barebones port. The pipeline works end to end and the offline test suite passes (621 tests, no network, API key or PaddleOCR needed). Spec 001 (reject documents whose text layer is garbled or missing, before any model request) is implemented, and grounding cannot be disabled. Spec 002 (the recheck sends the page's whole text layer and tells the model to copy it, so the text layer wins over the model) is implemented. Spec 003 renamed the project to `gridkey` (package, distribution and the live-test model variable); behaviour is unchanged. Spec 004 (several tables per document, including several on one page) is implemented: `extract_tables` returns one `Table` per table, discovery looks at every page in windows, and a table on a shared page is checked against its own band of the text layer only; its live check on the OCR'd Senate PDF (task 008) has not been run. Spec 005 (one entrypoint) is implemented: `extract_tables(pdf, model, *, cache_dir, max_requests, model_settings, discovery_pages, recheck, ocr)` is the only public way in, `model` is a required argument (a pydantic-ai model string or `Model` instance, never read from the environment), and pydantic-ai with all provider SDKs (no PyTorch) is a regular dependency. The offline tests drive the pipeline through the internal `run_pipeline(pdf, client)` with fake clients. The live test in `tests/live/` is opt-in (see Commands). Spec 006 (OCR with PaddleOCR, and an always-on cache) is implemented: when the text-layer check would reject a document, `extract_tables(..., ocr=True | False | OcrConfig)` OCRs only the bad pages (garbled or empty), checks again and carries on, and `Table.ocr_pages` lists the OCR'd pages; PaddleOCR is the optional extras `gridkey[ocr]` (CPU) and `gridkey[ocr-core]` (NVIDIA users add `paddlepaddle-gpu` themselves), imported only when a page misses the OCR cache; model answers and OCR results are always cached in `.gridkey/` (or `cache_dir`). The NVIDIA path has never run on real hardware (checklist in `tests/data/README.md`), and AMD is not supported. The real-OCR tests in `tests/ocr/` are opt-in too. Not yet ported from the original: page orientation, histogram-based layout matching, adding schema-missing columns from header labels, the `incomplete` verdict and per-layout bands in the position check, splitting large rechecks, dollar-based cost caps, and a CSV/CLI writer. `README.md` lists these in "Not carried over yet"; what spec 004 does not handle is under "Not handled". Spec 007 (merge the parts of a table whose header is reworded between pages, on by default with a `merge_reworded` switch) is a draft on branch `spec/007-merge-reworded-headers`; only its golden synthetic fixture exists so far (`tests/data/synthetic/`, 154 PDFs with truth files, made by `tests/synthetic.py` and `tests/synthetic_cases.py`, tracked in git; regenerate with `just synthetic`); no `src/` code has changed.

## File structure

```
.
├── README.md - General documentation for the repository
├── AGENTS.md - Documentation specifically for AI agents working in this repository
├── CLAUDE.md - symlink to AGENTS.md for Claude Code
├── .env - Environment variables, including the OpenAI API key, gitignored
├── .env.example - Example environment variables file, tracked in git
├── specs/ - Specification documents for the project
├── scripts/ - Maintainer scripts (build_trigrams.py regenerates the reference counts)
├── pyproject.toml - Dependencies (pinned), ruff/ty/pytest config
├── justfile - Commands for lint, format, type check, tests and hooks (run `just`)
├── .pre-commit-config.yaml - Pre-commit hooks: ruff check --fix, ruff format, ty check
├── src/gridkey/
│   ├── extract.py - The public extract_tables(pdf, model, ..., ocr) -> list[Table], usable_layers (check, OCR, check again), and run_pipeline(pdf, client, ocr=...) (internal, used by the tests)
│   ├── discover.py - Table discovery: windows of pages, tables found so far carried forward, grouping by columns
│   ├── regions.py - A table's band of a page that holds several tables (from its first and last row)
│   ├── schema.py - ExtractionError and the column checks
│   ├── cache.py - The cache directory rule (`cache_dir` or `.gridkey/`, with its own .gitignore) and the atomic write
│   ├── ocr.py - OcrConfig, OcrWord, the OcrEngine protocol, OcrUnavailableError, words_to_layer (pixels -> points)
│   ├── ocr_pages.py - ocr_pages: OCR cache first, render and recognise only on a miss, build Layers
│   ├── ocr_cache.py - The OCR cache key and per-page files in `<cache>/ocr/` (imports no PaddleOCR)
│   ├── ocr_device.py - Pure device choice (CPU or NVIDIA) over Capabilities, and detect_capabilities
│   ├── _paddle.py - Internal: the only module importing `paddleocr` (deferred), GPU-to-CPU fallback
│   ├── text.py - Text layer: tokenize, load_layer, Layer.lines
│   ├── textcheck.py - Garbled/missing text-layer check (English trigram score), assess_text_layers, the rejection messages; TextLayerError
│   ├── ngrams.py - Letter runs, trigrams and the shipped reference counts
│   ├── data/trigram_counts.json - English trigram counts, built by scripts/build_trigrams.py
│   ├── layout.py - Page header detection and per-page columns
│   ├── grounding.py - Look values up in the text layer
│   ├── position.py - Row/column position check
│   ├── recheck.py - Second look at flagged cells
│   ├── table.py - Table/Row/Flag results and ground_document
│   ├── models.py - Pydantic structured outputs requested from the model
│   ├── llm.py - Internal: Request/Image, LLMClient protocol, CachedClient (optional disk cache, request cap)
│   └── _model.py - Internal: the pydantic-ai client built from the `model` argument
└── tests/
    ├── data/ - Sample PDFs plus recorded model rows (*.rows.json)
    ├── ocr/ - Tests that run the real PaddleOCR models on the CPU (opt-in, deselected by default)
    ├── live/ - Tests that call a real model (opt-in, deselected by default)
    ├── fake_ocr.py, fake_paddle.py - Fake OCR engines and a fake `paddleocr`/`paddle` for the offline tests
    ├── synthetic.py, synthetic_cases.py - Generator of the golden synthetic fixture (PDFs with a text layer plus truth files) for spec 007
    ├── data/synthetic/ - The generated fixture, tracked in git: `<id>.pdf`, `<id>.json` (truth), `manifest.json`
    └── test_*.py - Offline tests, driven by a fake model
```

## Commands and quality gates

Commands live in the `justfile` ([just](https://github.com/casey/just) is the command runner; run `just` to list them). Use these rather than typing the underlying `uv run ...` commands, and add a recipe there when a new command is something a person will need to run.

| Command                   | What it does                                                                                                                                                                                                                                   |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `just setup`              | `uv sync` and install the git pre-commit hook (run once after cloning)                                                                                                                                                          |
| `just lint`               | `ruff check .` (reports only, changes nothing)                                                                                                                                                                                                 |
| `just format`             | `ruff format .`                                                                                                                                                                                                                                |
| `just typecheck`          | `ty check`                                                                                                                                                                                                                                     |
| `just test [pytest args]` | Offline tests: no network, no API key. Pass pytest args, e.g. `just test -k grounding`                                                                                                                                                         |
| `just synthetic`          | Regenerate the golden synthetic fixture in `tests/data/synthetic/` (deterministic; `tests/test_synthetic.py` fails if the committed files differ from a fresh run) |
| `just test-ocr`           | Real-OCR tests (`-m ocr`): run the real PaddleOCR models on the CPU, so they take minutes and download about 140 MB of models on first use (through PaddleOCR). They call no model API and cost no money                                  |
| `just test-live`          | Live tests (`-m live`): calls a real model and costs money. Needs `OPENAI_API_KEY` and `GRIDKEY_LIVE_TEST_MODEL` (test-only; the library never reads the model from the environment), read from `.env` (see `.env.example`); without both the test is skipped. Never run without the user's explicit go-ahead |
| `just hooks`              | Run every pre-commit hook on all tracked files                                                                                                                                                                                                 |
| `just check`              | `just hooks`, then `just test`                                                                                                                                                                                                                 |

Pre-commit (`.pre-commit-config.yaml`) runs `ruff check --fix`, `ruff format` and `ty check` on every commit. The hooks are local hooks that call `uv run`, so they use the ruff and ty versions pinned in `uv.lock` rather than separately pinned hook revisions. Tests are not part of the hooks; run `just test` yourself. Ruff, ty and the offline tests must pass before you finish a change. Do not bypass hooks with `--no-verify`.

Two things to know about the hooks: `pre-commit run --all-files` (and so `just hooks`) only covers files git tracks, so stage or commit new files first for it to see them; and a hook that auto-fixes a file reports a pass for a file git does not track yet.

## Spec-driven development

This project follows a spec-driven development approach, meaning that the specifications defined in the `specs/` directory serve as the primary source of truth for the project's functionality. The development workflow is as follows:

1. User requests features, bug fixes, and other changes, and the agent writes an initial specification for the requested change in the `specs/` directory. Agent opens a new branch for the implementation of the specification.
2. User reviews the spec and provides feedback or approval. If there are any open questions that need the user's decision, the user is required to provide clear guidance or answers before the agent proceeds with splitting the spec into actionable tasks.
   CRITICAL: DO NOT move to step 3 until all open questions have been resolved and the user has provided clear guidance or answers.
3. Agent splits the spec into actionable tasks that can be implemented in the codebase.
4. User reviews the actionable tasks and provides feedback or approval before implementation begins.
5. Agent implements the actionable tasks in the codebase, ensuring that the implementation aligns with the approved specifications.
6. User reviews the implemented changes and provides feedback or approval, completing the development cycle for the requested change.

### Naming conventions

- Each spec in the `specs/` directory gets its own folder, numbered serially using the format `nnn-feature-name`, where `nnn` is a three-digit number representing the order of the specification and `feature-name` is a brief, descriptive name for the feature or change being specified.
- Within the folder for each spec, the main specification file should be named `spec.md`.
- Tasks related to a spec should be placed in a `tasks/` subfolder within the spec's folder, numbered serially using the format `nnn-task-name.md`, where `nnn` is a three-digit number representing the order of the task and `task-name` is a brief, descriptive name for the task.
- After initial task implementation, if the user requests any changes or modifications to the written code, spec deltas may be created in a `deltas/` subfolder within the spec's folder, numbered serially using the format `nnn-delta-description.md`, where `nnn` is a three-digit number representing the order of the delta and `delta-description` is a brief, descriptive name for the delta.
- Specs 001 and 002 keep the project's former name, `pdf-table-extract` (import `pdf_table_extract`), because they record decisions made under it. They are history and are not rewritten.
