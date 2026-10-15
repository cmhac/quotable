# 004 - Docs

Spec: `../spec.md` (Docs). Depends on: task 002.

## Steps

1. `README.md`: update the Recheck row of the pipeline table. Flagged cells go back to the model
   once, with the page image and the page's whole text layer, and the model is told to copy the
   text layer's reading; an answer is kept only if grounding of that cell strictly improves. Add
   one sentence saying that because the text layer wins, OCR errors in it (for example commas
   read as periods) can pass into the output.
2. `README.md`, "Not carried over yet", Recheck bullet: remove "sending the text-layer text of
   each flagged row", which is now done (as the whole page).
3. `AGENTS.md`: project state (spec 002 implemented; the offline test count after tasks 001 and
   002) and the file structure if anything was added.
4. `tests/data/README.md` already lists both Senate fixtures; check the OCR'd entry's wording
   still matches how the tests use it.

## Acceptance

- `just check` passes (hooks, then tests).
- The README no longer lists as missing something this spec delivered.
