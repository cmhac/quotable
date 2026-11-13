"""The exceptions ``extract_tables`` raises."""

from decimal import Decimal

import quotable
from quotable.errors import BudgetExceededError, CostLimitExceededError, TableFailedWarning


def test_the_cost_limit_error_is_a_budget_error_and_keeps_its_fields():
    error = CostLimitExceededError(
        "over",
        reason="spent",
        limit=Decimal(5),
        spent=Decimal(6),
        over=Decimal(1),
        raise_by=Decimal(1),
        stage="audit",
        done=3,
        total=9,
        in_flight=2,
    )
    assert isinstance(error, BudgetExceededError)
    assert str(error) == "over"
    assert (error.reason, error.over, error.stage, error.done, error.total) == (
        "spent",
        Decimal(1),
        "audit",
        3,
        9,
    )
    assert error.estimate is None and error.finish_by is None and error.in_flight == 2


def test_it_is_exported():
    assert quotable.CostLimitExceededError is CostLimitExceededError
    assert "CostLimitExceededError" in quotable.__all__


def test_the_failed_table_warning_is_a_user_warning_and_is_exported():
    assert issubclass(TableFailedWarning, UserWarning)
    assert quotable.TableFailedWarning is TableFailedWarning
    assert "TableFailedWarning" in quotable.__all__
