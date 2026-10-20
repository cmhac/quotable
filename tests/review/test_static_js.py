"""The app's JavaScript, tested with node where it is installed (spec 013 task 010)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parent / "js"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_javascript_tests_pass():
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.mjs"))
    assert files
    result = subprocess.run(  # noqa: S603
        [str(NODE), "--test", *files],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, "TZ": "UTC"},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
