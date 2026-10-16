# 003 - Public API: `ExtraField`, `FieldGroup`, `ExtraFields` and validation

Spec: `../spec.md` (Requirements 1, 2; Design / Code, first bullet). Depends on: nothing (it can run
in parallel with tasks 001 and 002).

## Goal

The three dataclasses exist, are exported, and reject bad input before any request is made.

## Steps

1. New `src/quotable/extra_fields.py` with frozen dataclasses `ExtraField(name, description)`,
   `FieldGroup(name, description, fields)` and `ExtraFields(fields, prompt="",
   carry_forward=False)`. `carry_forward` defaults to **False** (decision in the spec).
2. `validate_extra_fields(extra_fields)` implements requirement 2 exactly: at least one field;
   every item an `ExtraField` or `FieldGroup`; a group inside a group is a `TypeError`; field names
   non-empty after stripping and unique after stripping across the whole request; non-empty field
   descriptions; groups with a non-empty name and description, at least one field, and a unique
   name; a group with one field is allowed. Everything else is a `ValueError` with a message that
   names the offending field or group.
3. `flatten(extra_fields)` returns the fields in column order (groups flattened in place) as small
   records `(field, group name or None)`. Later tasks call it; none re-implements the walk.
4. Export `ExtraField`, `FieldGroup` and `ExtraFields` from `quotable/__init__.py` and `__all__`.
   Check that `import quotable` still imports neither pandas nor polars.
5. Do not add the `extra_fields` argument to `extract_tables` yet (task 010), so nothing public
   half-works.
6. Tests in a new `tests/test_extra_fields.py`: every validation case in the spec's Tests list
   (including a name repeated across a group and an ungrouped field), the order from `flatten`,
   frozen-ness, and the default `carry_forward is False`.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The validation tests pass, the classes are importable from `quotable`, and the checks are clean.
