"""The offline scorer of the extra-fields checks (spec 010) runs and says what it should."""

from collections import defaultdict

from tests.score_extra_fields import KINDS, Tally, _truth, injections, score_one

IDS = [  # a few documents that cover the kinds; `just score-extra-fields` runs them all
    "extra-section-3p",
    "extra-sections-mixed",
    "extra-change-one",
    "extra-group-clears",
    "extra-group-and-free-field",
    "extra-header-in-region",
    "extra-senate-geometry",
]


def tally(kind: str) -> Tally:
    out = defaultdict(Tally)
    for case_id in IDS:
        for read in injections(_truth(case_id), kind):
            score_one(case_id, kind, read, out[kind])
    return out[kind]


def test_a_faithful_model_is_always_right():
    t = tally("none")
    assert (t.runs, t.right, t.silent) == (len(IDS), len(IDS), 0)


def test_every_catchable_missed_header_is_found_and_corrected():
    t = tally("missed")
    assert t.runs > 0
    assert (t.right, t.silent) == (t.runs, 0)
    assert t.caught == t.injected


def test_a_header_with_no_place_cannot_be_caught_and_the_scorer_says_so():
    t = tally("missed_only")
    assert t.runs > 0
    assert t.silent == t.runs


def test_an_invented_or_misplaced_value_is_never_silent():
    for kind in ("invented", "wrong_page"):
        t = tally(kind)
        assert t.runs > 0
        assert t.silent == 0
        assert t.flagged == t.runs


def test_a_misread_value_is_corrected_by_the_recheck():
    t = tally("misread")
    assert t.right == t.runs > 0


def test_every_kind_is_known():
    assert set(KINDS) == {"none", "missed", "missed_only", "invented", "misread", "wrong_page"}
