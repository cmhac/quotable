"""Extract tables from PDFs with a vision LLM and check every value against the text layer."""

from quotable.errors import (
    BudgetExceededError,
    CostLimitExceededError,
    ExtractionError,
    OcrUnavailableError,
    TableFailedWarning,
    TextLayerError,
)
from quotable.ocr.config import OcrConfig
from quotable.pipeline import extract_tables, extract_tables_async
from quotable.steps.extra_fields import ExtraField, ExtraFields, FieldGroup
from quotable.table import Flag, MergedPart, MergeEvidence, Problem, Row, Table

__all__ = [
    "BudgetExceededError",
    "CostLimitExceededError",
    "ExtraField",
    "ExtraFields",
    "ExtractionError",
    "FieldGroup",
    "Flag",
    "OcrConfig",
    "MergeEvidence",
    "MergedPart",
    "OcrUnavailableError",
    "Problem",
    "Row",
    "Table",
    "TableFailedWarning",
    "TextLayerError",
    "extract_tables",
    "extract_tables_async",
]
