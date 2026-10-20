"""The review app's static files (spec 013 task 010): no injected markup, nothing remote."""

import re
from pathlib import Path

import pytest

import quotable.review

STATIC = Path(quotable.review.__file__).parent / "static"
FORBIDDEN = {
    "innerHTML": r"innerHTML",
    "outerHTML": r"outerHTML",
    "insertAdjacentHTML": r"insertAdjacentHTML",
    "document.write": r"document\s*\.\s*write",
    "eval(": r"\beval\s*\(",
    "new Function": r"\bnew\s+Function\b",
    "http://": r"http://",
    "https://": r"https://",
}
REFERENCE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""")
IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""")


def static_files() -> list[Path]:
    return sorted(p for p in STATIC.iterdir() if p.is_file())


def test_the_static_folder_has_files_to_check():
    names = {p.name for p in static_files()}
    assert {"index.html", "app.js", "app.css"} <= names


@pytest.mark.parametrize("path", static_files(), ids=lambda p: p.name)
@pytest.mark.parametrize("name", FORBIDDEN)
def test_no_file_injects_markup_or_names_a_remote_address(path: Path, name: str):
    text = path.read_text(encoding="utf-8")
    assert not re.search(FORBIDDEN[name], text), f"{path.name} contains {name}"


def test_index_loads_the_app_script_and_styles():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    references = REFERENCE.findall(index)
    assert any(r.endswith("app.css") for r in references)
    assert any(r.endswith("app.js") for r in references)


def local_name(reference: str) -> str:
    """Return the file name a reference in index.html or a module import points at."""
    return reference.removeprefix("/static/").removeprefix("./")


def test_every_file_index_references_exists():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for reference in REFERENCE.findall(index):
        assert reference.startswith("/static/"), f"{reference} is not a file of the app"
        assert (STATIC / local_name(reference)).is_file(), f"{reference} is missing"


@pytest.mark.parametrize(
    "path", [p for p in static_files() if p.suffix == ".js"], ids=lambda p: p.name
)
def test_every_module_a_script_imports_exists(path: Path):
    for reference in IMPORT.findall(path.read_text(encoding="utf-8")):
        assert "/" not in local_name(reference), f"{path.name} imports {reference} from a subfolder"
        assert (STATIC / local_name(reference)).is_file(), f"{path.name} imports {reference}"
