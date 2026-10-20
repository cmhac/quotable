"""``quotable cost-report``: the command that adds up the cost log."""

import ast
import re
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

import pytest

import quotable
from quotable.__main__ import main
from quotable.review import server as review_server
from quotable.runs import write_run
from tests.test_costs import line, write_lines
from tests.test_runs import make_info

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


# --- quotable review (spec 013) ---------------------------------------------------------------
@pytest.fixture
def no_serving(monkeypatch):
    """Make ``serve_forever`` stop at once, as Ctrl+C does; return the browser calls."""
    opened: list[str] = []

    def stop(self, poll_interval=0.5):
        raise KeyboardInterrupt

    monkeypatch.setattr(review_server.ReviewServer, "serve_forever", stop)
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    return opened


def saved_run(project: Path) -> str:
    info = make_info(Path(__file__))
    write_run(project, info, [], {}, {}, [], [])
    return info.id


def test_review_help_lists_the_options(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["review", "--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    for option in ("--dir", "--port", "--no-browser", "--run", "--verbose"):
        assert option in out
    assert "8765" in out


def test_the_top_level_help_lists_review_next_to_cost_report(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "review" in out
    assert "cost-report" in out


def test_review_prints_the_address_and_the_run_count_and_opens_the_browser(no_serving, capsys):
    saved_run(Path.cwd() / ".quotable")
    saved_run(Path.cwd() / ".quotable")
    assert main(["review", "--port", "0"]) == 0
    out = capsys.readouterr().out
    (url,) = no_serving
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/", url)
    assert f"Serving the review app at {url.rstrip('/')} (Ctrl+C to stop)" in out
    assert "Runs: 2 in .quotable/runs/" in out


def test_no_browser_prints_the_address_and_opens_nothing(no_serving, capsys):
    assert main(["review", "--port", "0", "--no-browser"]) == 0
    assert "Serving the review app at http://127.0.0.1:" in capsys.readouterr().out
    assert no_serving == []


def test_without_runs_it_says_how_to_make_one_and_still_starts(no_serving, capsys):
    assert main(["review", "--port", "0", "--no-browser"]) == 0
    out = capsys.readouterr().out
    assert "Serving the review app" in out
    assert "No runs yet in .quotable/runs/" in out
    assert "extract_tables" in out


def test_review_creates_nothing(no_serving):
    assert main(["review", "--port", "0", "--no-browser"]) == 0
    assert listing(Path.cwd()) == []


def test_dir_names_another_project_folder(no_serving, tmp_path, capsys):
    other = tmp_path / "other" / ".quotable"
    saved_run(other)
    assert main(["review", "--dir", str(other), "--port", "0", "--no-browser"]) == 0
    assert f"Runs: 1 in {other / 'runs'}/" in capsys.readouterr().out


def test_run_opens_the_browser_on_that_run(no_serving):
    run_id = saved_run(Path.cwd() / ".quotable")
    assert main(["review", "--port", "0", "--run", run_id]) == 0
    (url,) = no_serving
    assert url.endswith(f"/#/run/{run_id}")


def test_an_unknown_run_exits_one_before_serving(no_serving, capsys):
    saved_run(Path.cwd() / ".quotable")
    assert main(["review", "--port", "0", "--run", "f" * 32]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("quotable: no run ")
    assert "f" * 32 in captured.err
    assert "Serving" not in captured.out
    assert no_serving == []


def test_a_taken_port_exits_one_and_says_so(capsys):
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    try:
        port = taken.getsockname()[1]
        assert main(["review", "--port", str(port), "--no-browser"]) == 1
    finally:
        taken.close()
    captured = capsys.readouterr()
    assert captured.err == f"quotable: port {port} is in use; try --port\n"
    assert captured.out == ""


def test_ctrl_c_stops_it_and_frees_the_port(no_serving, capsys):
    assert main(["review", "--port", "0", "--no-browser"]) == 0
    found = re.search(r"127\.0\.0\.1:(\d+)", capsys.readouterr().out)
    assert found
    port = int(found.group(1))
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


@pytest.mark.parametrize(
    "argv", [["review", "--port", "x"], ["review", "--run"], ["review", "--nope"]]
)
def test_a_review_usage_error_exits_two(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        main(argv)
    assert stop.value.code == 2
    assert "usage: quotable" in capsys.readouterr().err
