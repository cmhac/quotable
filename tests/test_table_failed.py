"""A table that failed a check (spec 019): the record of what failed."""

import dataclasses

import pytest

import quotable
from quotable import Problem, Table


def test_a_table_built_the_old_way_is_not_failed():
    table = Table(["A"], [], {}, {}, {})
    assert table.problems == [] and not table.failed


def test_a_table_with_a_problem_is_failed():
    table = Table(["A"], [], {}, {}, {}, problems=[Problem("discovery", (3,), "no columns")])
    assert table.failed


def test_a_problem_must_name_a_page():
    with pytest.raises(ValueError, match="at least one page"):
        Problem("discovery", (), "x")


def test_a_problem_cannot_be_changed():
    problem = Problem("location", (1, 2), "overlap")
    with pytest.raises(dataclasses.FrozenInstanceError):
        problem.message = "other"  # ty: ignore[invalid-assignment]


def test_problem_is_exported():
    assert quotable.Problem is Problem
    assert "Problem" in quotable.__all__


def test_the_default_problem_list_is_not_shared():
    a, b = Table([], [], {}, {}, {}), Table([], [], {}, {}, {})
    a.problems.append(Problem("discovery", (1,), "x"))
    assert b.problems == []
