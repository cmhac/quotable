<!--
SYNC IMPACT REPORT (temporary scratch for review; remove before committing)
Version change: template (unversioned) -> 1.0.0 (first ratification)
Modified principles: none (all placeholders newly filled)
Added sections: Core Principles I-VI, Technology and Security Constraints, Development Workflow and Quality Gates, Governance
Removed sections: none
Deferred items: none. Every principle is inferred from AGENTS.md and specs 001-013; the user has not yet reviewed them.
-->
# quotable Constitution

## Core Principles

### I. The Text Layer Is the Truth (NON-NEGOTIABLE)

Every extracted value MUST be looked up in the PDF's own text layer (grounding), and a value MUST sit in
its own row and column (position check). Grounding MUST NOT be switchable off. When the model and the
text layer disagree, the text layer wins, and a recheck MUST show the model the page's whole text layer
and tell it to copy it. Output MUST report how each value was verified; it MUST NOT present an
ungrounded value as verified.

Rationale: the library exists to make vision-model table extraction checkable.

### II. Fail Closed on Doubt

When evidence is missing or unclear, the library MUST refuse or leave things alone instead of guessing.
A document whose text layer is garbled or missing MUST be rejected before any model request unless OCR
repairs it. Two tables MUST be merged only when every rule agrees, and any doubt means no merge.
Failures MUST be loud and typed (`quotable.errors`). Recovery paths MUST NOT swallow errors that
change results. A failed write of a side record (cost log, saved run) MAY only warn, and MUST NOT
break an extraction.

Rationale: a wrong table that looks right is worse than an error.

### III. Offline-Testable, Live Tests Opt-In

The default test suite MUST run with no network, no API key and no PaddleOCR, by driving the pipeline
through fake clients. Tests that call a real model (`tests/live/`) or the real OCR models
(`tests/ocr/`) MUST stay opt-in and deselected by default. A live test costs money and MUST NOT be run
without the user's explicit go-ahead. New non-trivial logic MUST ship with a test. Tests that test model
behavior MUST use the real model, never a scripted fake.

Rationale: contributors must be able to run `just test` anywhere, and spend must be a human decision.

### IV. One Public Entrypoint, Explicit Inputs

`extract_tables` is the only public way in, and what `quotable/__init__.py` exports is the only public
API. Everything else is internal and MAY change without notice. The `model` argument MUST be passed
explicitly and MUST NOT be read from the environment. The library MUST NOT read secrets itself;
provider SDKs read their own credentials. Cache keys, prompts and the saved-run format MUST NOT change
without a spec that says so and a migration where old data would be read wrongly.

Rationale: a small public surface keeps the library stable and easy to reason about.

### V. Generic by Design

The library MUST NOT contain logic specific to one document set, publisher or fixture. Behavior that
only one document needs belongs in the caller's configuration, not in the pipeline. The VRA script
`scripts/extraction/extract_included_projects.py` is a reference for what is not yet ported, and
ported behavior MUST be generalized, not copied with its document-specific assumptions.

Rationale: quotable was distilled from one project so that others can use it.

### VI. Simplicity (Ponytail Ultra)

Work follows ponytail at the ultra level (see AGENTS.md): the smallest change that fully solves the
task, and any part of a request the need does not justify MUST be questioned before it is built. No
abstraction, option or configuration nobody asked for. Ponytail never overrides validation at trust
boundaries, error handling that prevents data loss, security, or accessibility. A known shortcut
MUST carry a `shortcut: <limit>, <when to upgrade>` comment.

Rationale: every extra line is read, tested and maintained later.

## Technology and Security Constraints

- Python with `uv`. Dependencies are pinned in `pyproject.toml` (and `uv.lock`); pandas and polars are
  ranges and MUST be imported inside the methods that use them, so `import quotable` loads neither.
- Lint, format and type checks are `ruff` and `ty`, run through the pre-commit hooks and `just`.
- No secrets, credentials or private keys in code, prompts, logs or specs. The cost log MUST NOT store
  prompts, answers or file paths.
- Optional features that need heavy dependencies MUST stay optional extras and MUST be imported
  only when used. The exception is OCR (PaddleOCR and the CPU build of PaddlePaddle): it is a default
  dependency, on the platforms that have a wheel for it, and MUST still be imported only when a page
  needs it.
- Global agent security policy (`~/.kiro/steering/security.md`) and the repo hooks MUST be followed.
  A hook that blocks an action MUST NOT be retried or worked around, and hooks MUST NOT be bypassed
  (no `--no-verify`).

## Development Workflow and Quality Gates

- All changes go through Spec Kit: `speckit-specify`, `speckit-clarify`, `speckit-plan`,
  `speckit-tasks`, `speckit-implement`, `speckit-converge`. Specs 001-013 keep the old layout and
  MUST NOT be rewritten.
- The user approves the spec (with all open questions answered), then the task list, then the finished
  work. An agent MUST NOT start the next stage without that approval.
- Ruff, ty and the offline tests MUST pass before a change is finished.
- A behavior-preserving change (a rename, a move) MUST leave behavior, public API and the offline tests
  unchanged, and the spec MUST say so.
- `AGENTS.md` MUST be updated in the same change whenever the file structure, commands, project state
  or workflow it describes changes.
- Commits are made on the working branch. Nothing is pushed or force-pushed without the user asking.

## Governance

This constitution outranks other project practices where they conflict. It is read at run time by
`speckit-plan`, `speckit-tasks` and `speckit-analyze`, so a plan that breaks a MUST here MUST be
justified in the plan's complexity tracking or changed. `AGENTS.md` is the runtime guidance for
agents; where it and this constitution disagree, this constitution wins and `AGENTS.md` MUST be
fixed.

Amendments are made with `speckit-constitution`, need the user's approval, and MUST bump the version
by semantic rules: MAJOR for removing or redefining a principle, MINOR for adding a principle or
materially expanding guidance, PATCH for wording fixes. Compliance is checked in spec and plan
review and by `speckit-analyze`.

**Version**: 1.1.0 | **Ratified**: 2026-11-10 | **Last Amended**: 2026-11-13
