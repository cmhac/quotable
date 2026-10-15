"""The error raised when the model's output cannot become a table, and the column checks."""

from gridkey.models import TableSchema


class ExtractionError(RuntimeError):
    """The model output could not be turned into a valid table."""


def validate_schema(schema: TableSchema) -> list[str]:
    """Return the column names, raising if they cannot key a table."""
    names = [c.name.strip() for c in schema.columns]
    problems = []
    if not names:
        problems.append("no columns")
    if any(not n for n in names):
        problems.append("blank column name")
    if len(set(names)) != len(names):
        problems.append("duplicate column names")
    if problems:
        msg = f"schema discovery returned an unusable schema: {', '.join(problems)}"
        raise ExtractionError(msg)
    return names
