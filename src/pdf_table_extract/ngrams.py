"""Character trigrams: letter runs, trigram extraction and the shipped English reference counts."""

import json
import re
import unicodedata
from functools import cache
from importlib import resources

START = "^"  # two of these pad the front of a letter run
END = "$"  # one of these pads the back
MIN_RUN = 2  # shorter letter runs carry no trigram evidence
_RUN = re.compile(rf"[a-z]{{{MIN_RUN},}}")


def letter_runs(text: str) -> list[str]:
    """
    Return the runs of two or more ASCII letters in the text, lowercased.

    Accented letters are folded to their base letter; digits, punctuation and spaces
    end a run, so ``4$44`` contributes nothing.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return _RUN.findall(folded)


def trigrams(run: str) -> list[str]:
    """Return the padded character trigrams of one letter run (every letter is scored)."""
    padded = f"{START}{START}{run}{END}"
    return [padded[i : i + 3] for i in range(len(padded) - 2)]


@cache
def load_counts() -> dict[str, int]:
    """Return the shipped English trigram counts (see ``scripts/build_trigrams.py``)."""
    path = resources.files("pdf_table_extract").joinpath("data", "trigram_counts.json")
    return json.loads(path.read_text(encoding="utf-8"))["trigrams"]
