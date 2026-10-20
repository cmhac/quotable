"""
Build the English trigram reference counts shipped in ``quotable/text``.

Run once by a maintainer (``uv run python scripts/build_trigrams.py``); the library never
touches the network. The corpus is a fixed list of public-domain Project Gutenberg books
(see ``scripts/README.md``). The output is deterministic for the same texts.
"""

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from quotable.text.quality import letter_runs, trigrams

OUTPUT = Path(__file__).resolve().parent.parent / "quotable/text/trigram_counts.json"
URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
# (Gutenberg ebook id, title). Mixed prose plus founding-era government text.
BOOKS = [
    (5, "The United States Constitution"),
    (11, "Alice's Adventures in Wonderland"),
    (84, "Frankenstein; or, the modern prometheus"),
    (98, "A Tale of Two Cities"),
    (174, "The Picture of Dorian Gray"),
    (345, "Dracula"),
    (1342, "Pride and Prejudice"),
    (1404, "The Federalist Papers"),
    (1661, "The Adventures of Sherlock Holmes"),
    (2701, "Moby Dick; Or, The Whale"),
]
_BODY = re.compile(r"\*\*\* START OF.*?\*\*\*(.*?)\*\*\* END OF", re.DOTALL)
TIMEOUT = 60


def read_book(ebook_id: int, corpus_dir: Path | None) -> str:
    """Return the book's text between the Project Gutenberg start and end markers."""
    if corpus_dir:
        raw = (corpus_dir / f"pg{ebook_id}.txt").read_text(encoding="utf-8")
    else:
        url = URL.format(id=ebook_id)
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    match = _BODY.search(raw)
    if not match:
        msg = f"book {ebook_id}: Project Gutenberg start/end markers not found"
        raise ValueError(msg)
    return match.group(1)


def main() -> None:
    """Count trigrams over the corpus and write the data file."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--corpus-dir", type=Path, help="read pg<id>.txt files from here instead of downloading"
    )
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    for ebook_id, _title in BOOKS:
        for run in letter_runs(read_book(ebook_id, args.corpus_dir)):
            counts.update(trigrams(run))

    data = {
        "corpus": [
            {"id": i, "title": t, "url": URL.format(id=i), "licence": "public domain"}
            for i, t in BOOKS
        ],
        "trigrams": dict(sorted(counts.items())),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {len(counts)} trigrams ({sum(counts.values())} total) to {OUTPUT}\n")


if __name__ == "__main__":
    main()
