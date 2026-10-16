# 007 - Missed-header check and the second look

Spec: `../spec.md` (Requirements 11, 12; Design / Code: `field_regions`, `suspect_pages`). Depends
on: tasks 002, 004 and 005.

## Goal

Pages where the model said "no header" but the text layer shows unexplained text where the header
is printed on other pages get one focused second question, and only a grounded answer changes
anything.

## Steps

1. Read `regions.py` (`locate`, `table_layers`) and `text.py` first. A table's band comes from the
   first and last row text discovery already reports.
2. `field_regions(places)`: for each field, the union of its places over the pages that printed it,
   grown by 6 pt on every side. A field with no place on any page has no region.
3. `suspect_pages(...)`: for each page where a field is null, the words whose centre is inside the
   field's region and not inside any table's band on that page are the evidence. If a table's rows
   cannot be located, remove no words for it (false alarm, never a miss). Return the pages and the
   evidence words per field.
4. The second look: one request per suspect page (page image, the fields in question, the evidence
   words), through the same client and cache, counted by `max_requests`. New output model in
   `models.py` for the answer. An answer value that grounds `exact` or `fuzzy` (task 005) makes the
   page a printing page for that field; anything else is discarded.
5. It runs whenever extra fields are requested, whatever `carry_forward` says (decision).
6. Tests (fake client): on the Senate sample (recorded rows, a fake discovery answer that reads the
   block on page 1 only) no second look is requested for pages 2 and 3; with the band exclusion
   switched off by a test-only argument both pages are suspect; a faked missed header on a fixture
   document is caught; a grounded second-look answer makes the page a printing page; an ungrounded
   or null answer changes nothing; `max_requests` counts the requests; the bait documents of
   scenarios 6 and 10 behave as the truth declares; the check runs with `carry_forward=False`.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The Senate sample raises no second look on pages 2 and 3, every bait in the fixture is handled as
declared, and the checks are clean.
