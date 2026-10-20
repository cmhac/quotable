# 002 - The run format: write and read `.quotable/runs/<run id>/`

Spec: `../spec.md` (Requirements A2, A3, A7; C1 and C2 for what the summary must hold).
Depends on: task 001.

## Goal

A new internal module, `quotable/runs.py`, writes one run to disk and reads runs back. Nothing
calls the writer yet (task 003). The reader is what the app uses (tasks 006 to 008).

## Format (version 1)

Two JSON files per run, so the runs list never loads the big one:

- `run.json` (small): `v`; `run` (`id`, `started`, `ended` as UTC ISO 8601 with `Z`,
  `quotable` version, `model`, `settings`); `document` (`name`, `path` absolute, `size`,
  `sha256`, `pages`); `summary` (tables, rows, cells, flagged cells by status, OCR pages); and
  one entry per table (`index`, `label`, `columns`, `extra_names`, `pages`, rows, flagged,
  merged part count, `ocr_pages`). Settings: `discovery_pages`, `recheck`, `ocr` (`true`,
  `false` or the `OcrConfig` fields), `merge_reworded`, `max_requests`, and `extra_fields`
  (each field's name, description and group, the prompt, `carry_forward`).
- `tables.json`: `v`; `pages` (each page any table is on: `size` `[width, height]` in points and
  `words` as `[text, x0, y0, x1, y1]`, the full page, OCR text on OCR'd pages); and `tables`,
  in the order `extract_tables` returned them, each with `index`, `label`, `columns`, `pages`,
  `ocr_pages`, `position`, `layouts` (page, columns, source, and `header`: `line`, `bottom`,
  column centres `x`, or `null`), `bands` (page -> `[y0, y1]`, only pages shared with another
  table), `areas` (page -> `rows` index -> `[y0, y1]` and `columns` name -> `[x0, x1]`, from
  task 001), `merged` (pages, columns and every `MergeEvidence` field), `proposals` (every
  field of `Proposal`), `extra_names`, `extra_fields` (page -> name -> value, source page,
  grounding), `extra_changes` (`[page, name, old, new]`), and `rows` (page, row, values, and
  each cell's `status`, `coverage`, `density`, `n_candidates`, `matched_text`, `bbox` and the
  box of every candidate, computed with the table's own layer: `layer.bbox(start, end)`).

Floats are rounded to 2 decimals (points) or 4 (coverage, density) to keep the files small.

## Steps

1. Red first: tests in `tests/test_runs.py` (step 5).
2. `storage.py`: `RUNS_DIR_NAME = "runs"` next to the cache and cost names, and
   `runs_dir(project_dir) -> Path`.
3. `quotable/runs.py`:
   - `RunInfo` (frozen dataclass: the `run` and `document` fields above) and
     `write_run(project_dir, info, tables, page_layers, page_sizes, headers, bands) -> Path`.
     It writes both files into `runs/.<id>.tmp/` with `write_atomic`, then renames the folder to
     `runs/<id>/` (`os.replace`). On any `OSError` it removes the temporary folder (best effort)
     and re-raises; the caller warns (task 003).
   - `list_runs(project_dir) -> tuple[list[RunSummary], int]`: every `runs/<id>/run.json` whose
     id matches `[0-9a-f]{32}` and whose `v` is 1, newest first; the int counts folders that
     could not be read (skipped, never raised). Dot-folders are ignored.
   - `load_run(project_dir, run_id) -> Run`: the id must match the pattern and name an existing
     folder (`KeyError` otherwise); reads both files into plain dataclasses the app uses
     (`Run`, `RunTable`, `RunRow`, `RunCell`, `RunPage`). It does not rebuild `Table`.
4. Docstring at the top of `runs.py` describes the format; `v` changes when it changes.
5. Tests: build tables with `run_pipeline` and a fake client on the Senate sample of
   `tests/test_senate_tables.py` (two tables sharing a page, spec 004) and on an `extra-*`
   fixture document (spec 010), write them, read them
   back: values, statuses, boxes, candidates, areas, band, header, merged parts, proposals,
   extra fields all survive; `list_runs` returns newest first, skips a damaged `run.json` and a
   `v: 2` file and counts them, and ignores a leftover `.<id>.tmp`; `load_run` refuses
   `../x`, an unknown id and an id with capitals; a write that fails half way (monkeypatch
   `write_atomic` to raise on the second file) leaves no folder at all.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

A written run reads back with every field the spec's sections B to E need, no failed write
leaves anything in `runs/`, and the suite passes.
