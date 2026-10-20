"""The exceptions ``extract_tables`` raises (all exported from ``quotable``)."""


class BudgetExceededError(RuntimeError):
    """The cap on new (uncached) model requests was reached."""


class ExtractionError(RuntimeError):
    """The model output could not be turned into a valid table."""


class TextLayerError(RuntimeError):
    """The PDF's text layer is garbled or missing, so values cannot be verified."""


class OcrUnavailableError(TextLayerError):
    """The document needs OCR, but OCR cannot run (not installed, or the device is missing)."""
