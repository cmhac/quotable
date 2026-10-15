# 001 - Reject documents with a garbled text layer

Status: draft, awaiting review

## Summary

Before any model request, check that the PDF's text layer is readable text. If it is garbled
or missing, stop with an error that tells the user to fix the PDF's OCR and try again. The
check uses character n-grams. Grounding cannot be turned off, so a usable text layer (real or
OCR-generated) is a hard requirement of the library.

## Motivation

A trial on three pages of the Senate "Report of the Secretary of the Senate" (printed pages
B-41 to B-43) extracted all 124 rows correctly from the page images, but every cell came back
`ungrounded`. The text layer is garbled: a font-encoding problem turns `0.00` into `4$44` and
a header into `-)1 (J,,-VH`. The pages render fine; only the extractable text is wrong.

The pipeline then spent 7 model requests, including 3 rechecks that could not change anything,
to produce a result with no verification at all. The library's promise is that every value is
checked against the text layer. When that cannot work, the right outcome is to say so up front,
at no cost.

## Requirements

1. **Check first.** `extract_table_async` (and so `extract_table`) assesses the text layer of
   the whole document before rendering pages or making any request to the client. A rejected
   document makes zero requests.
2. **Garbled detection.** For each page, the text layer is scored with a character-trigram
   model of English (see Design). A page below the threshold is `garbled`.
3. **Not enough evidence.** A page with too few letters to score (for example a page of
   numbers only) is `unassessable` and does not count for or against the document.
4. **Missing text.** A document with no text layer words on any page (a scan with no OCR) is
   rejected.
5. **Document verdict.** The document is rejected when the garbled share of its assessable
   pages is above `MAX_GARBLED_PAGE_SHARE` (0.10), or when requirement 4 applies. If there are
   no assessable pages but the document has text, it is accepted.
6. **No opt-out.** There is no argument, environment variable or flag to skip the check or to
   run without grounding. The thresholds are module constants, not parameters of
   `extract_table`.
7. **Clear error.** Rejection raises `TextLayerError` (exported from `pdf_table_extract`). The
   message states the reason (garbled or missing), how many pages were affected out of how
   many were assessed, the first few affected page numbers, a short excerpt of the offending
   text for garbled pages, and the remedy: the PDF needs a better OCR text layer (for example
   re-run OCR over the whole document, replacing the existing text layer) before extraction.
8. **Reuse the loaded layers.** The check reads the `Layer` objects the pipeline already
   loads, so it adds no second pass over the PDF.

## Design

- New module `src/pdf_table_extract/textcheck.py` holds the scoring, a `PageQuality` result
  (page number, verdict, score, letter count) and `check_text_layers(layers)`, which raises
  `TextLayerError` or returns the per-page results.
- Scoring: lowercase and ASCII-fold the page's words (reusing the folding in `text.tokenize`),
  keep letter runs of two or more letters, pad each run with start and end markers, and take
  the mean log-probability per trigram under the reference table, with smoothing for unseen
  trigrams. Digits and punctuation are ignored, which is why number-heavy tables are not
  penalised and `4$44` contributes nothing on its own; the garbled letter runs around it are
  what score badly.
- Reference table: trigram counts from public-domain English text, produced by a script kept in
  the repo (`scripts/build_trigrams.py`) and shipped as package data. No network access and no
  new runtime dependency at run time. The corpus and its licence are recorded in
  `tests/data/README.md` or next to the script.
- `extract_table_async` loads the layers first, calls the check, then renders PNGs. This
  reorders the first lines of the function; nothing else in the pipeline changes.
- Threshold and `MIN_LETTERS` are chosen from data, not guessed: score the three existing
  fixtures and the Senate fixture, and put the threshold in the gap between them.

## Limits

- The reference model is English and Latin-script. A document in another language or script is
  out of scope for now and may be wrongly rejected or wrongly accepted.
- Table text is not prose (names, abbreviations, codes). If a legitimate table page scores
  below the threshold in testing, the fix is a better reference or threshold, not a bypass.
- A garbled text layer that happens to be fully consistent can still look like text; this check
  catches the common case (broken font encodings, bad OCR), not every wrong layer.
- Only the text layer is judged. Whether a readable layer actually matches the page image is
  what grounding already tests.

## Out of scope

- Running OCR inside this library, or repairing/decoding a garbled layer.
- Disabling grounding, or a degraded "extract without verification" mode.
- Multiple tables per page, parent/child context across pages, and schema discovery beyond the
  first pages (separate specs, from the same Senate trial).

## Tests

All offline, no network.

- The three existing fixtures (`fy22_ag`, `fy22_milcon`, `fy24_milcon`) are accepted.
- New fixture: the 3-page Senate sample (`senate_expenditures_garbled.pdf`, about 90 KB, a
  public document), rejected with `TextLayerError`. A fake client asserts it received zero
  requests.
- A PDF built with `make_pdf` from ordinary English words is accepted; one built from random
  letter strings is rejected; a page of numbers only is `unassessable`; a PDF with no text is
  rejected as missing.
- Document verdict boundary: a mix of good and garbled pages is accepted at or below
  `MAX_GARBLED_PAGE_SHARE` and rejected above it.
- Error message names the reason, page numbers and the remedy.
- The calibration margin is asserted: the lowest legitimate fixture page scores above the
  threshold and the highest garbled Senate page scores below it, each by a stated margin. If
  the two ranges overlap, stop and report back instead of adjusting the threshold to fit.
- Existing tests that build PDFs with `make_pdf` still pass. If their placeholder words trip
  the check, change those tests' words to plausible text rather than loosening the check.

## Docs

- `README.md`: add "requires a text layer; scanned or badly OCR'd PDFs must be OCR'd first".
- `AGENTS.md`: update project state and file structure (`textcheck.py`, `scripts/`, the new
  fixture).
- `tests/data/README.md`: add the Senate fixture and the reference corpus note.

## Open questions

1. Whole document or leading pages only? This spec checks every page, because the layers are
   already in memory and a document can be garbled only in later pages. Checking only the
   pages schema discovery sees (the first 5) would be cheaper but could miss them.
2. `MAX_GARBLED_PAGE_SHARE` of 0.10: one odd page in a long document should not block it, but
   a majority-garbled one must. Say if you want it stricter (any garbled page rejects).
3. Is committing the 3-page Senate PDF as a test fixture OK?
