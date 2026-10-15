# 001 - Build the English trigram reference table

Spec: `../spec.md` (Design: reference table). Depends on: nothing.

## Goal

Produce the shipped reference data the scorer compares page text against, and the script that
regenerates it.

## Steps

1. Choose a public-domain English corpus that is licence-clean and large enough for stable
   trigram counts (a few MB). Prefer ordinary mixed prose; Project Gutenberg texts are the
   default. Fetching the corpus is a one-time, build-time download of public data; the library
   never touches the network at run time. Record corpus name, source URLs and licence.
2. Write `scripts/build_trigrams.py`: lowercase, ASCII-fold (same folding as `text.tokenize`),
   keep letter runs of two or more letters, pad each run with start and end markers, count
   trigrams, and write log-probabilities with a smoothing floor for unseen trigrams.
3. Run it once and commit the output as package data under
   `src/pdf_table_extract/data/` (compact JSON or similar). Make sure `pyproject.toml` includes
   the data file in the built package.
4. Add a loader function (cached) that returns the table. No new runtime dependency.

## Acceptance

- Script is deterministic: re-running it on the same corpus gives an identical file.
- Package data is found when the package is installed (check with a wheel build or
  `importlib.resources`), not only from the source tree.
- The file is small (target under 1 MB).
- Corpus and licence are recorded next to the script.
- `just check` passes.
