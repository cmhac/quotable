# 004 - Discovery reads the fields

Spec: `../spec.md` (Requirements 3 to 7; Design / Code: `models.py`, `discover.py`). Depends on:
task 003.

## Goal

With extra fields requested, the discovery request also returns each page's field values; without
them, the request is the same object as today.

## Steps

1. Read `discover.py` (`DISCOVER_PROMPT`, `CARRY_PROMPT`, `_ask_window`, `discover`, `Found`) and
   `models.py` (`PageTables`, `WindowTables`) and `llm.py` (`Request`, `request_key`) first.
2. `models.py`: `ExtraValue(name, value)` with `value: str | None`, and a page entry and a window
   entry that extend `PageTables` and `WindowTables` with `extras: list[ExtraValue]`. They are used
   only when extra fields are requested; `WindowTables` itself does not change.
3. `discover.py`: add the extra-fields paragraph of requirement 5 (the fields are reported, not
   ignored; each page judged on its own; never inferred from another page or the known tables;
   verbatim; `null` when absent; table cells are not extra fields unless the description says so),
   then the fields as `name: description`, groups listed with name, description and their fields
   indented, then `ExtraFields.prompt`. `CARRY_PROMPT` stays as it is and never mentions values
   (requirement 6).
4. `discover(...)` takes `extra_fields` and returns a `Discovery(tables: list[Found], extras:
   dict[int, dict[str, str | None]])`. With `extra_fields=None` the requests are built exactly as
   today. Update every caller and test of `discover` for the new return type.
5. Answer checks (requirement 7): one entry per page and, in each, exactly the requested names, each
   once. A mismatch goes back once with the problems named, together with a page-count problem in
   the same retry; a second failure raises `ExtractionError`. An empty string counts as `None`.
6. Tests in `tests/test_discover.py` (fake client): without fields the `Request` is identical to
   today's (instructions, output type `WindowTables`, parts) and `request_key` equals the key from
   the pre-change code path (build the expected key from a copy of the old construction in the
   test); the prompt holds fields, descriptions, group names and descriptions, and the caller's
   text; known-table text never carries a field value; a wrong name set is retried once together
   with a page-count problem; a second failure raises; groups do not change the output type.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The new tests pass, the existing discovery tests pass with only the return-type update, and the
checks are clean.
