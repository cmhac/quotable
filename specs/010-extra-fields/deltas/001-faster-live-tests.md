# 001 - Faster live tests

Delta to: ../spec.md (the live tests under "Tests", task 012). Requested after the first live run
looked too slow: about 700 to 800 new requests, run one test at a time, estimated at 45 to 60
minutes (an estimate; no request time was measured).

## Change

1. **Parallel runs.** `pytest-xdist==3.8.0` joins the dev dependency group. The live cases are
   independent: each writes to its own cache directory (`.cache/extra/<kind>/<case>/run<N>`) and
   its own `report-<case>-run<N>.json`. Run them with `just test-live -n 4 <file>`. `-n` is not
   in `addopts`, so the offline suite is unchanged.
2. **Run count.** `QUOTABLE_LIVE_RUNS` (default 3, a positive whole number; anything else raises
   `ValueError`) sets how many times each case runs. `1` is the cheap first look; it cannot show
   run-to-run differences, so the default stays 3. Parsing is `live_runs()` in
   `tests/extra_fields_live.py`, tested offline.
3. **Progress lines under `-n`.** Each line names its worker (`[live 02:14 gw1]`) and the request
   count is per worker. Checked with a probe run under `-n 2` with default capture and no `-s`:
   the lines reached stderr.
4. **`just test-live`** takes pytest arguments, like `just test`.

## Found by the first live run (1 run per case, `-n 4`)

5. **Field wording.** Every fixture page is topped by a title line printed on every page
   (`Annual Funding Report  |  Section N`, `tests/synthetic.py`), above the header block. The
   position-only description "line k of the block at the top left" let the model count that
   title as line 1, so 16 of 17 failing accuracy tests read the title as the first field. The
   description now says to count from the first line below any title printed at the top of every
   page. Offline tests pin that every fixture page has such a title and that the description says
   so. Not yet re-run live: whether the model now reads the right line is unmeasured.
   Still open from that run: `extra-block-on-text-page` (the test looks up a page that has no
   table) and one differing amount in the Senate regression.

## Not changed

- The library's `MAX_CONCURRENT_REQUESTS = 4` and discovery's one-window-after-another order.
- The regression test still uses separate caches for the runs with and without extra fields.
  Sharing extraction answers between them was proposed and not chosen.

## Risks

- Each worker keeps up to 4 requests in flight, so `-n 4` can mean 16 at once. The library has no
  retry for rate-limit errors of its own; whether the provider SDK retries them was not checked.
  A rate-limit failure would show as a failed test, not a wrong answer. Lower `-n` if it happens.
- Worker request counters are separate, so the "model request N" numbers are not a global total.

## Done when

- `live_runs` tests pass (red first, then green), `ruff`, `ty` and `just test` pass.
- `pytest -m live --collect-only` lists 3 runs per case by default and 1 with
  `QUOTABLE_LIVE_RUNS=1`.
- No live test was run.

## Label handling (live findings)

- With the library prompt as it was, a printed "label value" line came back whole (12 of 12
  samples). Added a sentence to `EXTRAS_PROMPT`: report only the value unless the field's
  description asks for the whole line or the label. Alone, with position-only test descriptions,
  it did not help (14 of 15 still wrong): "line 1" gives the model no way to tell where a label
  ends.
- The test descriptions now say, per field, what the line is, read from the fixture's geometry
  (`value_lines` in `tests/extra_fields_live.py`): it starts with a label to leave out, or the
  value is the whole line, and how many lines a wrapped value covers. No header word is printed.
  `ExtraField` docs and the README tell callers to say the same in their descriptions.
- Result, 3 runs per document: 62 passed and 13 failed. The remaining failures are not label
  errors: `extra-block-on-text-page` (harness `KeyError`), the Senate regression (OCR noise, two
  different amounts), `extra-group-clears` and `extra-group-and-free-field` (page 4 prints only
  the second line of the block, in the first line's place, so a positional description can't
  tell them apart), and one run of `extra-section-25p` (the running title returned for a field).

## Descriptions name the fields again (supersedes the position-only rule for the fixture)

The rule "a description must not reuse a word of the header" was read too strictly. Naming the
field ("the funding year", "the account line") is how a caller describes it and is allowed;
only the values to find should not be in the request. The fixture accuracy tests now send the
truth's own names and descriptions (`request_for`), plus a sentence about the title printed on
every page, one about the label, and for a wrapped value, to join the lines with single
spaces (`described_request` in `tests/extra_fields_live.py`). There is no check for value
words. The position-only fields stay for the real-report slice, where there is no truth.

- `extra-block-on-text-page`: final values are judged only on pages that hold a table.
- Result, 3 runs: all 60 fixture accuracy runs passed, including the two group documents.
  The only failures left are the Senate regression (OCR amounts differ between two reads).

## Senate regression: comma and period read as the same

Six cached Senate reads (3 without extra fields, 3 with) differ as much between two runs
without them as between a run with and one without, so the difference is the model's reading
of a scan, not the extra fields. The scan's comma is ambiguous (the PDF's own text layer has
both `LAISCH. MARK` and `6,941,271.74` / `6.941.271.74` for the same print). The regression
comparison now reads a comma as a period (`rows_of`); nothing else is loosened.

Result, 3 runs: 13 of 15 regression runs pass. Still failing, with different causes:
- run 2: the headings read in Title Case instead of upper case (shape), plus two cut or
  changed names (`GALLEGO`/`GALLEGOS`, `LAISCH, MARK` / `LAISCH, MARK P`);
- run 3: `STAFF` against `PROFESSIONAL STAFF`.

Case is ignored too (headings, values): a heading read as `Description` for `DESCRIPTION` is
not a difference. Result, 3 runs: 13 of 15 regression runs pass. The two left are cut names
in the run without extra fields (run 2: `GALLEGO`, `LAISCH, MARK`; run 3: `STAFF`); the text
layer has the full `GALLEGOS`, `LAISCH. MARK P` and `PROFESSIONAL STAFF`, so the run with
extra fields was the correct one each time.
