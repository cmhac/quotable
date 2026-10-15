# 002 - Docs

Spec: `../spec.md` (Requirements 6 and 7; Docs; Design step 5). Depends on: task 001.

## Steps

1. `README.md`: change the title to `# gridkey`; the examples' imports and install line
   (`pip install gridkey[openai]`); the live-test instructions (`GRIDKEY_LIVE_MODEL`). Add one
   or two sentences near the top saying where the name comes from: PDF tables are grids that
   are locked on the page, and this is the key that unlocks them. Add nothing else.
2. `AGENTS.md`:
   - introduction: the project name;
   - file tree: `src/gridkey/`;
   - commands table: `GRIDKEY_LIVE_MODEL`;
   - one line saying that `specs/001-*` and `specs/002-*` keep the old name `pdf-table-extract`
     because they record decisions made under it;
   - project state: spec 003 implemented, test count unchanged.
3. `scripts/README.md`: the package path in the first paragraph.
4. Leave the project description in `pyproject.toml` and the README's first-paragraph meaning
   as they are.

## Acceptance

- `just check` passes.
- Following the README's example, as written, imports from `gridkey` and uses names that
  exist.
- `AGENTS.md` and `README.md` contain no `pdf_table_extract`, `pdf-table-extract` or
  `PDF_TABLE_EXTRACT`, except the single history note in `AGENTS.md` from step 2.
