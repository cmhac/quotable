"""``quotable cost-report``: the command that adds up the cost log."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import quotable
from quotable.__main__ import main
from tests.test_costs import line, write_lines

SRC = Path(quotable.__file__).parent


def project_with_costs(root: Path) -> Path:
    folder = root / ".quotable" / "cost"
    folder.mkdir(parents=True)
    write_lines(
        folder,
        line(run="a", model="m1", cost_usd=0.25, input_tokens=1000, output_tokens=100),
        line(run="b", model="m1", cost_usd=0.5, input_tokens=2000, output_tokens=200),
    )
    return root / ".quotable"


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_the_report_is_printed_for_the_working_directory(capsys):
    project_with_costs(Path.cwd())
    assert main(["cost-report"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Cost report for .quotable/cost/requests.jsonl\n")
    assert "Runs:      2" in out
    assert "Tokens:    3,000 in, 300 out" in out
    assert "Total:     $0.7500" in out
    assert capsys.readouterr().err == ""


def test_dir_reads_another_projects_folder(tmp_path, capsys):
    other = project_with_costs(tmp_path / "other")
    assert main(["cost-report", "--dir", str(other)]) == 0
    out = capsys.readouterr().out
    assert f"Cost report for {other}/cost/requests.jsonl" in out
    assert "Runs:      2" in out


def test_no_project_folder_says_so_exits_zero_and_creates_nothing(capsys):
    assert main(["cost-report"]) == 0
    assert capsys.readouterr().out == (
        "No cost records found in .quotable/cost/requests.jsonl. "
        "Costs are recorded when quotable sends a request to a model.\n"
    )
    assert listing(Path.cwd()) == []


def test_an_empty_cost_file_says_so_and_changes_nothing(capsys):
    folder = Path.cwd() / ".quotable" / "cost"
    folder.mkdir(parents=True)
    (folder / "requests.jsonl").write_text("")
    before = listing(Path.cwd())
    assert main(["cost-report"]) == 0
    assert capsys.readouterr().out.startswith("No cost records found in ")
    assert listing(Path.cwd()) == before


def test_a_damaged_line_is_reported_and_the_rest_summed(capsys):
    project = project_with_costs(Path.cwd())
    with (project / "cost" / "requests.jsonl").open("a") as handle:
        handle.write("{broken\n")
    assert main(["cost-report"]) == 0
    out = capsys.readouterr().out
    assert "Skipped 1 unreadable line." in out
    assert "Total:     $0.7500" in out


def test_dir_that_is_a_file_exits_one_naming_the_path(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert main(["cost-report", "--dir", str(blocker)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(blocker) in captured.err
    assert captured.err.startswith("quotable: cannot read ")


def test_a_cost_file_that_is_a_folder_exits_one(capsys):
    (Path.cwd() / ".quotable" / "cost" / "requests.jsonl").mkdir(parents=True)
    assert main(["cost-report"]) == 1
    assert "requests.jsonl" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [[], ["nonsense"], ["cost-report", "--nope"], ["cost-report", "--dir"]]
)
def test_a_usage_error_exits_two(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        main(argv)
    assert stop.value.code == 2
    assert "usage: quotable" in capsys.readouterr().err


def test_the_public_api_is_unchanged():
    assert "main" not in quotable.__all__
    assert not any("cost" in name.lower() or "cli" in name.lower() for name in quotable.__all__)


@pytest.mark.parametrize(
    "module",
    [
        pytest.param("__main__.py", id="cli.py"),
        pytest.param("storage.py", id="costs.py"),
        "__main__.py",
    ],
)
def test_the_report_modules_import_only_the_standard_library_and_quotable(module):
    tree = ast.parse((SRC / module).read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= set(sys.stdlib_module_names) | {"quotable"}, roots


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603


def test_python_dash_m_quotable_and_the_installed_script_print_the_same_report():
    project_with_costs(Path.cwd())
    script = Path(sys.executable).parent / "quotable"
    assert script.exists(), "run `uv sync` so the [project.scripts] entry is installed"
    by_module = run([sys.executable, "-m", "quotable", "cost-report"], Path.cwd())
    by_script = run([str(script), "cost-report"], Path.cwd())
    assert by_module.returncode == by_script.returncode == 0
    assert by_module.stdout == by_script.stdout
    assert "Total:     $0.7500" in by_module.stdout
