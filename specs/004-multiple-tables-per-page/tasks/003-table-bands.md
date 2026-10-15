# 003 - A table's part of a multi-table page

Spec: `../spec.md` (Requirement 12; Design, regions). Depends on: 001.
Not wired into the pipeline yet.

## Goal

Given the tables on a page and their first and last row text, return each table's layer: the
whole page layer when it is the only table, otherwise a cropped band. Raise when a band cannot
be isolated.

## Steps

1. New `src/gridkey/regions.py` (or a section of `discover.py` if it stays small; pick the
   smaller diff):
   - `locate(layer, text, which) -> tuple[float, float] | None`: tokenize `text`, find
     candidates with `grounding.find_candidates`, take their boxes with `layer.bbox(start, end)`;
     for `which == "first"` the topmost box's (top, bottom), for `"last"` the bottommost box's.
     `None` when there are no candidates. (The scratch `proto.py` `locate` is the tested logic.)
   - `BAND_MARGIN = 4.0` (pt).
   - `table_layers(page, layer, tables: list[tuple[str, str, str]]) -> list[Layer]` where each
     tuple is (label, first row, last row), in the order given:
       - one table: return `[layer]`, nothing located;
       - two or more: locate each first and last row; if either is not found raise
         `ExtractionError` naming the page, the table's label and which row (first or last) was
         not found; if a located last row is above its first row raise the same kind of error;
         compute each band as (first top - margin, last bottom + margin); if two bands overlap
         raise `ExtractionError` naming the page and both labels; otherwise return
         `layer.crop(top, bottom, -1e9, 1e9)` per table.
2. Tests in `tests/test_regions.py` with `make_pdf` (two stacked tables on one page, sharing
   words such as a repeated header word and an amount):
   - a single table returns the page layer unchanged;
   - two tables: each cropped layer holds exactly its own band's words (assert on the word
     lists), the other table's words are absent, the titles and headers outside both bands are
     absent;
   - a first row not found, a last row not found, and overlapping bands each raise
     `ExtractionError` with the page and the label(s) in the message;
   - repeated first-row text (once in each table) picks the topmost candidate for the first row
     and the bottommost for the last row, as specified.

## Acceptance

- New tests pass offline; `just lint`, `just typecheck` and `just test` pass.
- `grounding.py` and `position.py` are not changed.
