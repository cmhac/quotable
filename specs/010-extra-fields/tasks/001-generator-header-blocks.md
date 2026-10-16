# 001 - Generator: header blocks and their truth

Spec: `../spec.md` (Requirement 19; Synthetic fixture / `tests/synthetic.py`). Depends on: nothing.

## Goal

`tests/synthetic.py` can draw a header block (label and value lines at a fixed place, like the
Senate sample) on chosen pages and record it in the truth file, without changing any document that
does not ask for a block.

## Steps

1. Read `tests/synthetic.py`, `tests/test_synthetic.py` and `tests/data/README.md` first; match the
   style of the existing dataclasses (`Part`, `Gap`) and the way `render` builds the truth.
2. Add a `HeaderBlock` dataclass: for each field the label and the value (a value may be `None`
   for "this block omits the field"), the position (x, y of the first line), font and size, the
   alignment (left or right), and whether a value wraps over two lines.
3. Give `Part` and `Gap` an optional `blocks` (page index within the item -> `HeaderBlock`) and a
   `table_top_after_block` flag: a table that shares a page with a block starts below it, as in the
   sample; on a page without a block it starts at the usual top (which puts its rows where the
   block was printed on other pages). Defaults keep today's behaviour exactly.
4. Draw the block's text with the same text-layer method the generator already uses, so the value
   lands in the text layer like everything else.
5. `render` adds to the truth only for documents with a block: `extra_fields.fields` (names in
   order, with the group of each, or `null`), `extra_fields.groups` (what the document is expected
   under, see task 002), `extra_fields.printed` (page -> name -> value or `null`, exactly as
   printed), `extra_fields.boxes` (page -> name -> the drawn box of the printed value) and
   `extra_fields.expected` (page -> name -> `{value, source_page}` after carrying, `null` for
   missing). Compute `expected` with a small, independent loop in the generator (it is the oracle
   for task 006, so do not import library code into it).
6. Regenerate with `just synthetic` and check `git status tests/data/synthetic`: no existing file
   changes (no block is requested yet, so nothing new appears either).
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

`just synthetic` reproduces all 154 existing documents byte for byte, the generator can render a
document with a block (shown by a test or a throwaway call whose output is deleted), and the
checks are clean.
