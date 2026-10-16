"""Extract tables from PDFs with a vision LLM and check every value against the text layer."""

from quotable.extra_fields import ExtraField, ExtraFields, FieldGroup
from quotable.extract import extract_tables, extract_tables_async
from quotable.llm import BudgetExceededError
from quotable.ocr import OcrConfig, OcrUnavailableError
from quotable.schema import ExtractionError
from quotable.table import Flag, MergedPart, MergeEvidence, Row, Table
from quotable.textcheck import TextLayerError

__all__ = [
    "BudgetExceededError",
    "ExtraField",
    "ExtraFields",
    "ExtractionError",
    "FieldGroup",
    "Flag",
    "OcrConfig",
    "MergeEvidence",
    "MergedPart",
    "OcrUnavailableError",
    "Row",
    "Table",
    "TextLayerError",
    "extract_tables",
    "extract_tables_async",
]
