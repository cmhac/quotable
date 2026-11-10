"""
The ``quotable`` command line: ``cost-report``, ``review`` and ``gold-report``.

``python -m quotable`` is the same command.

``quotable cost-report`` adds up what the project has spent. It reads
``.quotable/cost/requests.jsonl`` (see :mod:`quotable.storage`),
never calls a model and never creates anything. Exit codes: 0 for a report (including "no
records yet"), 1 when the cost file cannot be read, 2 for a usage error.

``quotable review`` starts the local review app (:mod:`quotable.review.server`) on 127.0.0.1 over
the runs in ``.quotable/runs/``; it creates nothing itself. Exit codes: 0 after Ctrl+C, 1 when
the port is in use or ``--run`` names no saved run, 2 for a usage error.

``quotable gold-report`` scores the hand-typed gold of ``.quotable/gold/`` (spec 015) against the
newest saved run of each sampled document, or the runs named with ``--run``, prints the report and
writes ``gold_pages.csv`` and ``gold_cells.csv`` to ``--out`` (default ``.quotable/reports/``). It
never calls a model. Exit codes: 0 for a report, 1 when no sample was drawn, not every sampled page
is done, a gold file cannot be read, a ``--run`` is unknown or repeats a document, or a file cannot
be written; 2 for a usage error.
"""

import argparse
import contextlib
import errno
import sys
import webbrowser
from pathlib import Path

from quotable.gold.project import score_project
from quotable.gold.report import cells_csv, format_text, pages_csv
from quotable.gold.score import Progress
from quotable.gold.store import GoldError
from quotable.review.server import make_server
from quotable.runs import list_runs
from quotable.storage import (
    DEFAULT_DIR_NAME,
    cost_file,
    format_report,
    gold_ignore_note,
    reports_dir,
    runs_dir,
    summarize,
)

DEFAULT_PORT = 8765


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quotable", description="Tools for quotable projects.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    report = commands.add_parser(
        "cost-report",
        help="print what the model requests of this project cost",
        description="Add up the cost records in .quotable/cost/ and print the totals.",
    )
    review = commands.add_parser(
        "review",
        help="start the local app for reviewing extracted values",
        description="Serve the review app on 127.0.0.1 over the runs saved in .quotable/runs/.",
    )
    gold = commands.add_parser(
        "gold-report",
        help="score the hand-typed gold tables against saved runs",
        description=(
            "Score the gold in .quotable/gold/ against the newest run of each sampled "
            "document and write gold_pages.csv and gold_cells.csv."
        ),
    )
    for command in (report, review, gold):
        command.add_argument(
            "--dir",
            type=Path,
            metavar="PATH",
            help="the .quotable folder to read (default: .quotable in the current directory)",
        )
    review.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="N",
        help=f"the port to listen on (default: {DEFAULT_PORT})",
    )
    review.add_argument(
        "--no-browser", action="store_true", help="print the address but do not open a browser"
    )
    review.add_argument("--run", metavar="ID", help="open the app on this run")
    review.add_argument("--verbose", action="store_true", help="log every request to stderr")
    gold.add_argument(
        "--run",
        action="append",
        metavar="ID",
        help="score this run instead of its document's newest (repeat for other documents)",
    )
    gold.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="where to write the two CSV files (default: reports/ in the .quotable folder)",
    )
    return parser


def _cost_report(project: Path) -> int:
    path = cost_file(project)
    try:
        report = format_report(summarize(path), path)
    except OSError as err:
        print(f"quotable: cannot read {path}: {err.strerror or err}", file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0


def _review(args: argparse.Namespace, project: Path) -> int:
    runs, _ = list_runs(project)
    shown = args.dir if args.dir is not None else Path(DEFAULT_DIR_NAME)
    where = f"{runs_dir(shown)}/"
    if args.run is not None and args.run not in {run.id for run in runs}:
        print(f"quotable: no run {args.run} in {where}", file=sys.stderr)
        return 1
    try:
        server = make_server(project, args.port, verbose=args.verbose)
    except OSError as err:
        if err.errno != errno.EADDRINUSE:
            raise
        print(f"quotable: port {args.port} is in use; try --port", file=sys.stderr)
        return 1
    with server:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        print(f"Serving the review app at {url} (Ctrl+C to stop)")
        if runs:
            print(f"Runs: {len(runs)} in {where}")
        else:
            print(f"No runs yet in {where}; call extract_tables on a PDF to make one.")
        if not args.no_browser:
            webbrowser.open(f"{url}/#/run/{args.run}" if args.run else f"{url}/")
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    return 0


def _gold_report(args: argparse.Namespace, project: Path) -> int:
    try:
        result = score_project(project, args.run or ())
    except GoldError as err:
        print(f"quotable: {err}", file=sys.stderr)
        return 1
    if isinstance(result, Progress):
        print(
            f"quotable: {result.done} of {result.total} sampled pages are done; "
            "mark them all done before scoring",
            file=sys.stderr,
        )
        return 1
    out = args.out if args.out is not None else reports_dir(project)
    pages_file, cells_file = out / "gold_pages.csv", out / "gold_cells.csv"
    sys.stdout.write(format_text(result))
    try:
        out.mkdir(parents=True, exist_ok=True)
        pages_file.write_text(pages_csv(result), encoding="utf-8", newline="")
        cells_file.write_text(cells_csv(result), encoding="utf-8", newline="")
    except OSError as err:
        print(f"quotable: cannot write to {out}: {err.strerror or err}", file=sys.stderr)
        return 1
    print(f"wrote {pages_file} and {cells_file}")
    if (note := gold_ignore_note(project)) is not None:
        print(f"quotable: {note}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command; return the exit code (argparse exits 2 itself on a usage error)."""
    args = _parser().parse_args(argv)
    project = args.dir if args.dir is not None else Path.cwd() / DEFAULT_DIR_NAME
    if args.command == "review":
        return _review(args, project)
    if args.command == "gold-report":
        return _gold_report(args, project)
    return _cost_report(project)


if __name__ == "__main__":
    raise SystemExit(main())
