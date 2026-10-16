"""Extract tables from PDFs with a vision LLM and check every value against the text layer."""

from gridkey.extract import extract_tables, extract_tables_async
from gridkey.llm import BudgetExceededError
from gridkey.ocr import OcrConfig, OcrUnavailableError
from gridkey.schema import ExtractionError
from gridkey.table import Flag, MergedPart, MergeEvidence, Row, Table
from gridkey.textcheck import TextLayerError

__all__ = [
    "BudgetExceededError",
    "ExtractionError",
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
