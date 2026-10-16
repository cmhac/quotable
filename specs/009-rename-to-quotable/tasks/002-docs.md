# 002 - Docs

Spec: `../spec.md` (Requirements 6 and 7; Docs; Design step 6). Depends on: task 001.

## Steps

1. `README.md`:
   - title `# quotable`; the example imports (`from quotable import ...`); the install lines
     (`pip install quotable`, `quotable[ocr]`, `quotable[ocr-core]`, the `uv pip install` line);
   - the cache folder (`.quotable/`, in the example comment and the cache section);
   - prose that names the tool ("quotable OCRs the bad pages", "pandas and polars are installed
     with quotable", "the quotable column gets a trailing `_`", "quotable joins two tables only
     ...", "quotable creates the folder");
   - the live-test instructions (`QUOTABLE_LIVE_TEST_MODEL`).
   Remove the sentence that explains the name `gridkey` (the play on words about grids and keys)
   and add nothing in its place (user's decision).
2. `AGENTS.md`:
   - introduction: the project name (`quotable`);
   - file tree: `src/quotable/`, and the `cache.py` line (`.quotable/`);
   - commands table: `QUOTABLE_LIVE_TEST_MODEL`;
   - project state: add one sentence that spec 009 renamed the project again, to `quotable`
     (package, distribution, import, cache folder and live-test variable; behaviour unchanged);
     in the sentences about earlier specs, code names use the new name (`quotable[ocr]`,
     `.quotable/`, `import quotable`), while the sentence "Spec 003 renamed the project to
     `gridkey`" stays as history. Keep the test count at the baseline from task 001;
   - the naming-conventions line about historical specs: extend it to say that specs 001 and 002
     keep `pdf-table-extract` and specs 003 to 009 keep `gridkey` (009 describes the rename
     itself), because they record decisions made under those names.
3. `scripts/README.md`: the package path in the first paragraph.

## Acceptance

- `just check` passes.
- Following the README's example as written imports from `quotable` and uses names that exist.
- `README.md` contains no `gridkey`. `AGENTS.md` contains `gridkey` only in the history sentences
  from step 2.
