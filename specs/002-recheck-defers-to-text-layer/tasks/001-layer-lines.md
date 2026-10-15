# 001 - Layer.lines(): the text layer as visual lines

Spec: `../spec.md` (Requirement 1; Design, `text.py`).

## Goal

A method that returns a page's text layer as one string per visual line, top to bottom, words
left to right, sharing its line-grouping rule with `Layer.crop`. Not used by the pipeline yet.

## Steps

1. In `src/pdf_table_extract/text.py`, factor the line-grouping loop out of `Layer.crop` into one
   helper (words sorted by vertical centre, a word joins the current line when its centre is
   within `line_tol` of the line's first word, each line sorted left to right).
2. `Layer.crop` uses the helper; its behaviour does not change.
3. Add `Layer.lines(line_tol: float = 2.0) -> list[str]`: the text of each visual line, words
   joined with single spaces, using the same helper. The default tolerance matches `crop`.
4. Tests in `tests/test_text.py` (build layers with `Layer.add`, and one through `make_pdf`):
   - words on one line come out left to right, lines top to bottom, regardless of the order
     they were added;
   - words whose centres differ by more than the tolerance are separate lines;
   - an empty layer gives `[]`;
   - a rotated fixture page (`fy22_milcon_house_original.pdf`, `/Rotate 90`) reads in upright
     order: its first line is the table's printed heading or header row, not a column of text.
   Existing `crop` tests still pass unchanged.

## Acceptance

- New tests pass offline; `just lint`, `just typecheck` and `just test` pass.
- `Layer.crop` output is identical to before (existing tests prove it).
- Nothing in `recheck.py` or `extract.py` changes in this task.
