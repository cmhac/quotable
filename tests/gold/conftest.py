"""Fixtures of the gold tests: the project the browse tests build, copied to the working folder."""

import shutil
from pathlib import Path

import pytest

from tests.review.test_browse_api import Built, built  # noqa: F401


@pytest.fixture
def project(built: Built) -> Path:  # noqa: F811
    """A copy of the built project at ``.quotable/`` in the working directory."""
    target = Path.cwd() / ".quotable"
    shutil.copytree(built.project, target)
    return target
