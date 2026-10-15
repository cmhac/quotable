# Instructions for AI agents working in this repo

> CRITICAL: This document must be updated regularly to reflect changes to the codebase. Failure to do so may result in AI agents operating with outdated or incorrect instructions. This document is not intended to be a full record of every change made, but rather a high-level overview of the key instructions and guidelines for AI agents working in this repository.

## Project introduction

`pdf-table-extract` is a small Python library that extracts tables from PDFs with a vision LLM and then checks every extracted value against the PDF's own text layer. The pipeline is: schema discovery, per-page layout discovery, per-page extraction, grounding (each value is looked up in the text layer), a position check (a value must sit in its own row and column), and a recheck of flagged cells. It is generic (not specific to any one document set) and was distilled from `scripts/extraction/extract_included_projects.py` in the VRA community-projects repository, which remains the reference for anything not yet ported.

## Project state

An initial, barebones port. The pipeline works end to end and the offline test suite passes (75 tests, no network or API key needed). The live test in `tests/live/` has been written but not run. Nothing is committed yet. Not yet ported from the original: page orientation, histogram-based layout matching, adding schema-missing columns from header labels, the `incomplete` verdict and per-layout bands in the position check, splitting large rechecks, dollar-based cost caps, and a CSV/CLI writer. `README.md` lists these in "Not carried over yet".

## File structure

```
.
├── README.md - General documentation for the repository
├── AGENTS.md - Documentation specifically for AI agents working in this repository
├── CLAUDE.md - symlink to AGENTS.md for Claude Code
├── .env - Environment variables, including the OpenAI API key, gitignored
├── .env.example - Example environment variables file, tracked in git
├── specs/ - Specification documents for the project
├── pyproject.toml - Dependencies (pinned), ruff/ty/pytest config
├── src/pdf_table_extract/
│   ├── extract.py - The pipeline: extract_table(pdf, client)
│   ├── text.py - Text layer: tokenize, load_layer
│   ├── layout.py - Page header detection and per-page columns
│   ├── grounding.py - Look values up in the text layer
│   ├── position.py - Row/column position check
│   ├── recheck.py - Second look at flagged cells
│   ├── table.py - Table/Row/Flag results and ground_document
│   ├── models.py - Pydantic structured outputs requested from the model
│   ├── llm.py - Request/Image, LLMClient protocol, CachedClient (disk cache, request cap)
│   └── pydantic_ai_client.py - Optional pydantic-ai client (the [openai] extra)
└── tests/
    ├── data/ - Sample PDFs plus recorded model rows (*.rows.json)
    ├── live/ - Tests that call a real model (opt-in, deselected by default)
    └── test_*.py - Offline tests, driven by a fake model
```

Note: `specs/` and `CLAUDE.md` do not exist yet; they are created with the first spec.

## Spec-driven development

This project follows a spec-driven development approach, meaning that the specifications defined in the `specs/` directory serve as the primary source of truth for the project's functionality. The development workflow is as follows:

1. User requests features, bug fixes, and other changes, and the agent writes an initial specification for the requested change in the `specs/` directory.
2. User reviews the spec and provides feedback or approval.
3. Agent splits the spec into actionable tasks that can be implemented in the codebase.
4. User reviews the actionable tasks and provides feedback or approval before implementation begins.
5. Agent implements the actionable tasks in the codebase, ensuring that the implementation aligns with the approved specifications.
6. User reviews the implemented changes and provides feedback or approval, completing the development cycle for the requested change.

### Naming conventions

- Each spec in the `specs/` directory gets its own folder, numbered serially using the format `nnn-feature-name`, where `nnn` is a three-digit number representing the order of the specification and `feature-name` is a brief, descriptive name for the feature or change being specified.
- Within the folder for each spec, the main specification file should be named `spec.md`.
- Tasks related to a spec should be placed in a `tasks/` subfolder within the spec's folder, numbered serially using the format `nnn-task-name.md`, where `nnn` is a three-digit number representing the order of the task and `task-name` is a brief, descriptive name for the task.
- After initial task implementation, if the user requests any changes or modifications to the written code, spec deltas may be created in a `deltas/` subfolder within the spec's folder, numbered serially using the format `nnn-delta-description.md`, where `nnn` is a three-digit number representing the order of the delta and `delta-description` is a brief, descriptive name for the delta.
