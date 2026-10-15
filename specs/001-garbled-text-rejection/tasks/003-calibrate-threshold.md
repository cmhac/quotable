# 003 - Add the Senate fixture and calibrate the threshold

Spec: `../spec.md` (Design: threshold chosen from data; Tests: calibration margin).
Depends on: task 002.

## Goal

Replace the provisional constants with values taken from real scores, and lock them in with
tests.

## Steps

1. Copy the 3-page Senate sample to `tests/data/senate_expenditures_garbled.pdf` (source is
   `$KIROCREW_SCRATCH/senate/sample2.pdf`) and add it to `tests/data/README.md` with a note that
   its text layer is garbled while the pages render correctly.
2. Score every page of the three existing fixtures and the Senate fixture. Report the per-page
   scores to the user in a short table.
3. Set `MIN_LETTERS` and `GARBLED_SCORE_THRESHOLD` in the gap between the lowest legitimate
   page and the highest garbled page.
4. Add calibration tests: all three existing fixtures accepted; the Senate fixture rejected
   with `TextLayerError`; the lowest legitimate page scores above the threshold, and the
   highest garbled page below it, each by a stated margin.

## Stop condition

If the legitimate and garbled score ranges overlap, or the gap is too thin to give a sensible
margin, stop and report the scores to the user. Do not tune the threshold to fit, and do not
add a bypass.

## Acceptance

- Constants set from data, with the measured scores recorded in a comment or the test file.
- Calibration tests pass offline; `just check` passes.
