"""The golden synthetic fixture (tests/data/synthetic) is sound and reproducible."""

import filecmp
import json
from collections import defaultdict
from pathlib import Path

import pytest

from tests.synthetic import names_check, validate
from tests.synthetic_cases import DEFAULT_OUT, all_docs, write_all

MANIFEST = json.loads((DEFAULT_OUT / "manifest.json").read_text())
IDS = [entry["id"] for entry in MANIFEST]


def load(case_id: str) -> dict:
    return json.loads((DEFAULT_OUT / f"{case_id}.json").read_text())


def test_the_manifest_lists_every_document_the_generator_makes():
    assert [d.id for d in all_docs()] == IDS


@pytest.mark.parametrize("case_id", IDS)
def test_every_truth_row_is_in_its_pages_text_layer_and_the_text_layer_passes(case_id):
    assert validate(load(case_id), DEFAULT_OUT / f"{case_id}.pdf") == []


@pytest.mark.parametrize("case_id", IDS)
def test_the_header_facts_in_the_truth_match_the_header_names(case_id):
    case = load(case_id)
    parts = {p["id"]: p for p in case["parts"]}
    for rel in case["relations"]:
        a, b = parts[rel["a"]]["columns"], parts[rel["b"]]["columns"]
        assert rel["names_check"] == names_check(tuple(a), tuple(b))


def test_regenerating_gives_the_same_files(tmp_path):
    out = tmp_path / "regenerated"
    write_all(out)
    diff = filecmp.dircmp(DEFAULT_OUT, out)
    assert not diff.left_only
    assert not diff.right_only
    assert not diff.diff_files
    assert not diff.funny_files


def test_each_settled_rule_has_cases_on_both_sides():
    seen: dict[str, set[bool]] = defaultdict(set)
    for entry in MANIFEST:
        for rel in entry["relations"]:
            if rel["expect_merge"] is not None and rel["stage"] == "merge":
                for probe in rel["probes"]:
                    seen[probe].add(rel["expect_merge"])
    for probe in ("grid", "min_cells", "shape", "pipeline"):
        assert probe in seen, probe
    for probe in ("grid", "min_cells", "shape"):
        assert seen[probe] == {True, False}, probe


def test_the_rule_dependent_cases_are_there_to_decide_the_half_equal_rule():
    open_cases = [
        rel
        for entry in MANIFEST
        for rel in entry["relations"]
        if rel["expect_merge"] is None and "half_equal" in rel["probes"]
    ]
    assert len(open_cases) >= 50
    assert {rel["same_table"] for rel in open_cases} == {True, False}


def test_the_fixture_has_no_stray_files():
    expected = {f"{i}.{ext}" for i in IDS for ext in ("pdf", "json")} | {"manifest.json"}
    assert {p.name for p in Path(DEFAULT_OUT).iterdir()} == expected
