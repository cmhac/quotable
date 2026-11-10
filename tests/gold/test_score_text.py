"""The scorer's text rules and assignment (spec 015 task 007)."""

import itertools
import random

import pytest

from quotable.gold.score import assign, column_key, normal, score_cell, similarity, squash


def test_normal_folds_formatting_but_not_content():
    """The VRA cases: dollar signs, commas, copy hyphens, periods and name order are ignored."""
    assert normal(" $1,500,000 ") == normal("1500000")
    assert normal("Espanola Broadband Expan- sion") == normal("Espanola Broadband Expansion.")
    assert normal("Schatz; Hirono") == normal("Hirono; Schatz")
    assert normal("Jesús G. ‘‘Chuy’’ García") == normal("Jesús G. “Chuy” García")
    assert normal("Trone") != normal("Tron")
    assert normal("Pro\u00adcious, WV") == normal("Procious, WV")  # soft hyphen


def test_the_okina_is_a_quote_like_character():
    assert normal("Hawai\u02bbi") == normal("Hawai\u2019i")


def test_dots_and_dashes_are_compared_as_they_are_not_as_blank():
    """Spec 014 keeps such cells as extracted, so the scorer must not call them empty."""
    assert normal("....") != normal("")
    assert normal("....") == normal(" .... ")
    assert normal("---") != normal("")
    assert normal("\u2014") == normal("-")
    assert normal("Pine County....") == normal("Pine County")  # a trailing period still goes


def test_blank_cells_are_equal_and_empty():
    assert normal("") == normal("   ") == ""


def test_score_cell_reports_three_levels():
    assert score_cell("Smith", "Smith") == {"exact": True, "normal": True, "fuzzy": True}
    assert score_cell("Smith", "SMITH ") == {"exact": False, "normal": True, "fuzzy": True}
    assert score_cell("Smithson Town", "Smithson Twon") == {
        "exact": False,
        "normal": False,
        "fuzzy": True,
    }
    assert score_cell("Smith", "Jones") == {"exact": False, "normal": False, "fuzzy": False}
    assert score_cell("", "") == {"exact": True, "normal": True, "fuzzy": True}


def brute_lcs(a: str, b: str) -> int:
    for size in range(min(len(a), len(b)), 0, -1):
        for picked in itertools.combinations(range(len(a)), size):
            sub = "".join(a[i] for i in picked)
            it = iter(b)
            if all(ch in it for ch in sub):
                return size
    return 0


def test_similarity_is_the_indel_ratio_that_rapidfuzz_gives():
    # the value in rapidfuzz's documentation for fuzz.ratio("this is a test", "this is a test!")
    assert similarity("this is a test", "this is a test!") == pytest.approx(0.96551724137931)
    rng = random.Random(3)
    for _ in range(150):
        a = "".join(rng.choice("abc ") for _ in range(rng.randint(0, 7)))
        b = "".join(rng.choice("abc ") for _ in range(rng.randint(0, 7)))
        expected = (
            1.0 if a == b else 0.0 if not a or not b else 2 * brute_lcs(a, b) / (len(a) + len(b))
        )
        assert similarity(a, b) == pytest.approx(expected)


def test_two_blanks_are_identical_and_one_blank_is_not():
    assert similarity("", "") == 1.0
    assert similarity("", "x") == 0.0


def test_squash_and_column_key():
    assert squash("  a \n b\t") == "a b"
    assert column_key("Amount ($)") == column_key("amount") == "amount"


def best_total(matrix) -> float:
    n, m = len(matrix), len(matrix[0])
    k = min(n, m)
    best = float("-inf")
    for rows in itertools.permutations(range(n), k):
        for cols in itertools.permutations(range(m), k):
            best = max(best, sum(matrix[r][c] for r, c in zip(rows, cols, strict=True)))
    return best


def test_assign_equals_an_exhaustive_search_on_random_matrices():
    rng = random.Random(11)
    for _ in range(200):
        n, m = rng.randint(1, 4), rng.randint(1, 4)
        matrix = [[round(rng.random(), 2) for _ in range(m)] for _ in range(n)]
        pairs = assign(matrix)
        assert len(pairs) == min(n, m)
        assert len({r for r, _ in pairs}) == len({c for _, c in pairs}) == len(pairs)
        assert sum(matrix[r][c] for r, c in pairs) == pytest.approx(best_total(matrix))


def test_assign_of_nothing_is_nothing():
    assert assign([]) == []
    assert assign([[]]) == []


def test_assign_is_stable_for_equal_input():
    matrix = [[1.0, 1.0], [1.0, 1.0]]
    assert assign(matrix) == assign(matrix)
