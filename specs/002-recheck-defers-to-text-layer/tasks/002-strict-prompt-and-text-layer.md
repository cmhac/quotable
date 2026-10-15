# 002 - Strict recheck prompt and the page's text layer in the request

Spec: `../spec.md` (Requirements 1-7; Design, `recheck.py`; Docs, `recheck.py` docstring).
Depends on: task 001.

## Goal

Each recheck request carries the page's whole text layer, and the prompt tells the model to
copy the text layer's reading. The acceptance rule is untouched.

## Steps

1. In `src/pdf_table_extract/recheck.py`, replace `RECHECK_PROMPT` with the strict wording
   proven in the experiments (Requirement 2): the text layer is an OCR of the same page and is
   the reference; for each listed cell, find that cell's text in the text layer (same row, same
   column) and return it copied character for character, with its own spelling, digits and
   punctuation; a disagreement in spelling or characters is not a reason to keep the model's own
   value, since the text layer is more reliable than its reading of the image, especially for
   unusual names; keep the model's own value only when the text layer has no text for that cell
   (missing, or belonging to another cell); no explanations. Mention that the columns of a row
   appear on the same line of the text layer.
2. `_request` adds a text part `Text layer of the whole page, one visual line per line:\n...`
   built from `table.layers[page].lines()`, placed between the previous rows and the cell list.
   The image (150 dpi), previous rows and flagged-cell list are unchanged.
3. Reword `RECHECK_REASONS` only where an entry contradicts the new prompt (the current wording
   is checked and left alone if it does not).
4. Leave `_proposals`, `_regrounded`, the `RECHECK_STATUSES` tuple and the acceptance rule as
   they are (Requirements 4 and 5). No new parameters anywhere (Requirement 6).
5. Update the module docstring: it describes the text-layer text being sent, and drops
   "sending the text-layer text of each flagged row" from the list of things left out.
6. Tests in `tests/test_recheck.py`:
   - the recheck request has a text part containing the page's whole text layer, one visual
     line per line, in reading order, and it includes words from rows that were not flagged
     (assert on the text, not only that a part exists);
   - the prompt states that the text layer is the reference and that a spelling disagreement is
     not a reason to keep the model's value (assert on key phrases);
   - a recheck on a page with several lines of text sends exactly one recheck request per page,
     as before (`client.stages()`).
   The existing recheck tests pass unchanged: accepted when grounding improves, original kept
   when it does not, blank ignored, same-token answer not applied, unlisted cells ignored,
   clean document never rechecked. Fix any existing assertion on the request parts that the new
   part breaks, by updating the assertion, not by weakening the new behaviour.

## Acceptance

- New and existing tests pass offline; `just lint`, `just typecheck` and `just test` pass.
- `git diff` shows no change to `grounding.py`, `position.py`, `layout.py` or `extract.py`, and
  `extract_table`'s signature is unchanged.
