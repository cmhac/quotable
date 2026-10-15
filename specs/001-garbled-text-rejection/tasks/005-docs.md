# 005 - Documentation

Spec: `../spec.md` (Docs). Depends on: task 004.

## Steps

1. `README.md`: state that a text layer is required and that scanned or badly OCR'd PDFs must be
   OCR'd first. Describe `TextLayerError` and the English/Latin-script limit.
2. `AGENTS.md`: update the project state (offline test count, spec 001 done) and the file
   structure (`textcheck.py`, `data/`, `scripts/build_trigrams.py`, the Senate fixture).
3. `tests/data/README.md`: confirm the Senate fixture and reference-corpus entries from tasks
   001 and 003 are present and accurate.
4. Update `README.md`'s "Not carried over yet" only if something there changed.

## Acceptance

- Docs match the implemented behaviour and constants.
- `just check` passes.
