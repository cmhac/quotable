# 004 - Docs

Spec: `../spec.md` (Docs). Depends on: tasks 001 to 003.

## Goal

The README and AGENTS.md describe the frames, the new dependencies and the column-name rule.

## Steps

1. `README.md`:
   - the opening example gains `table.to_pandas()` and `table.to_polars()` next to `records()`;
   - a sentence that pandas and polars are installed with gridkey;
   - the column-name rule in one short paragraph: a PDF column is never renamed; a library column
     (`page`, `row`, `<column>__grounding`, `<column>__coverage`, `grounding_status`,
     `recheck_changes`) whose name is taken gets a trailing `_`;
   - "Not carried over yet / Output": still no CSV writer or CLI, but the frames write one in a
     line (`table.to_polars().write_csv(path)`);
   - the OCR section ("OpenCV, pandas and others") no longer lists pandas as a cost of the
     `ocr` extra, since it is now installed anyway.
2. `AGENTS.md`: project state (spec 008 implemented, with the dependency and collision rule in a
   sentence; the "CSV/CLI writer" item in "Not yet ported" says the frames exist), the `table.py`
   line in the file tree, `tests/test_frames.py` in the tree, and the test count (run
   `just test`, use the printed number).
3. Spec 005's "no numpy" statement is history and is not edited.
4. Set `specs/008-dataframe-output/spec.md` Status to `implemented` only after the user
   approves the change.
5. `just check` (stage new files first so the hooks see them).

## Done when

`just check` passes and README.md and AGENTS.md agree with the code.
