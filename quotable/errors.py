"""The exceptions ``extract_tables`` raises (all exported from ``quotable``)."""

from decimal import Decimal


class BudgetExceededError(RuntimeError):
    """The cap on new (uncached) model requests was reached."""


class CostLimitExceededError(BudgetExceededError):
    """
    The run's cost limit (``max_cost``) was, or would be, passed (spec 017).

    ``reason`` is ``"spent"`` (the actual cost went above the limit), ``"estimate"`` (an estimate
    made before spending is above it), ``"unpriced"`` (the model's price is not known, so the
    limit could not be kept) or ``"unmetered"`` (a request reported no usage). Money fields are
    ``Decimal`` dollars; ``str(error)`` is the full message.
    """

    def __init__(  # noqa: D107, PLR0913
        self,
        message: str,
        *,
        reason: str,
        limit: Decimal,
        spent: Decimal,
        over: Decimal,
        raise_by: Decimal,
        estimate: Decimal | None = None,
        finish_by: Decimal | None = None,
        stage: str | None = None,
        done: int | None = None,
        total: int | None = None,
        in_flight: int = 0,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.limit = limit
        self.spent = spent
        self.over = over
        self.raise_by = raise_by
        self.estimate = estimate
        self.finish_by = finish_by
        self.stage = stage
        self.done = done
        self.total = total
        self.in_flight = in_flight


class ExtractionError(RuntimeError):
    """The model output could not be turned into a valid table."""


class TextLayerError(RuntimeError):
    """The PDF's text layer is garbled or missing, so values cannot be verified."""


class OcrUnavailableError(TextLayerError):
    """The document needs OCR, but OCR cannot run (not installed, or the device is missing)."""


class TableFailedWarning(UserWarning):
    """
    A table failed a check (spec 019), or the data of a table that failed was read.

    ``extract_tables`` returns a failed table instead of raising; ``Table.problems`` says what
    went wrong. Python's warning filters decide whether this is shown, ignored or an error.
    """
