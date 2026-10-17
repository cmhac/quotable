"""
The ``quotable`` command line: ``quotable cost-report`` adds up what the project has spent.

It reads ``.quotable/cost/requests.jsonl`` (see :mod:`quotable.costs`), never calls a model and
never creates anything. Exit codes: 0 for a report (including "no records yet"), 1 when the
cost file cannot be read, 2 for a usage error.
"""

import argparse
import sys
from pathlib import Path

from quotable.cache import DEFAULT_DIR_NAME
from quotable.costs import cost_file, format_report, summarize


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quotable", description="Tools for quotable projects.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    report = commands.add_parser(
        "cost-report",
        help="print what the model requests of this project cost",
        description="Add up the cost records in .quotable/cost/ and print the totals.",
    )
    report.add_argument(
        "--dir",
        type=Path,
        metavar="PATH",
        help="the .quotable folder to read (default: .quotable in the current directory)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command; return the exit code (argparse exits 2 itself on a usage error)."""
    args = _parser().parse_args(argv)
    project = args.dir if args.dir is not None else Path.cwd() / DEFAULT_DIR_NAME
    path = cost_file(project)
    try:
        report = format_report(summarize(path), path)
    except OSError as err:
        print(f"quotable: cannot read {path}: {err.strerror or err}", file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0
