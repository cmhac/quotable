"""The golden synthetic fixture (tests/data/synthetic) is sound and reproducible."""

import filecmp
import json
from collections import defaultdict
from pathlib import Path

import pymupdf
import pytest

from quotable.steps.grounding import find_candidates
from quotable.text.layer import load_layer, tokenize
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


# --- the extra-fields family (spec 010) -------------------------------------------------------
EXTRA_IDS = [i for i in IDS if i.startswith("extra-")]


def extra(case_id: str) -> dict:
    return load(case_id)["extra_fields"]


def overlaps(a: list[float], b: list[float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_the_earlier_documents_are_still_all_there():
    assert len(IDS) - len(EXTRA_IDS) == 154


def test_every_extra_fields_scenario_has_a_document():
    tags = {t for entry in MANIFEST if entry["id"] in EXTRA_IDS for t in entry["tags"]}
    assert {f"scenario-{n}" for n in range(1, 13)} <= tags


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_every_printed_value_grounds_exact_at_its_recorded_box(case_id):
    truth = extra(case_id)
    with pymupdf.open(DEFAULT_OUT / f"{case_id}.pdf") as pdf:
        layers = {i + 1: load_layer(p) for i, p in enumerate(pdf)}
    seen = 0
    for page, printed in truth["printed"].items():
        for name, text in printed.items():
            if text is None:
                assert name not in truth["boxes"].get(page, {})
                continue
            seen += 1
            layer = layers[int(page)]
            found = [
                layer.bbox(c.start, c.end)
                for c in find_candidates(layer, tokenize(text))
                if c.status == "exact"
            ]
            assert found, (page, name)
            assert any(overlaps(list(b), truth["boxes"][page][name]) for b in found), (page, name)
    assert seen


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_no_block_overlaps_a_table_drawn_on_its_page(case_id):
    truth = extra(case_id)
    for page, box in truth["block_boxes"].items():
        for table in truth["table_boxes"].get(page, []):
            assert not overlaps(box, table), (page, box, table)


@pytest.mark.parametrize("case_id", EXTRA_IDS)
def test_expected_values_equal_an_independent_recomputation(case_id):
    truth = extra(case_id)
    names = [f["name"] for f in truth["fields"]]
    group_of = {n: g["name"] for g in truth["groups"] for n in g["fields"]}
    members = {g["name"]: g["fields"] for g in truth["groups"]}
    for mode, grouped in (("plain", False), ("carry", True), ("carry_ungrouped", False)):
        state: dict[str, tuple[str, int] | None] = dict.fromkeys(names)
        for page in sorted(truth["printed"], key=int):
            printed = truth["printed"][page]
            if mode == "plain":
                state = dict.fromkeys(names)
            if grouped:
                for fields in members.values():
                    if any(printed[n] is not None for n in fields):
                        for n in fields:
                            if printed[n] is None:
                                state[n] = None
            for n in names:
                value = printed[n]
                if value is not None:
                    state[n] = (value, int(page))
            want = {
                n: None
                if (held := state[n]) is None
                else {"value": held[0], "source_page": held[1]}
                for n in names
            }
            assert truth["expected"][mode][page] == want, (mode, page)
    assert set(group_of) <= set(names)


def test_the_region_check_baits_are_declared():
    by_tag = {t: e["id"] for e in MANIFEST if e["id"] in EXTRA_IDS for t in e["tags"]}
    quiet = extra(by_tag["scenario-6"])
    bait = extra(by_tag["scenario-10"])
    assert quiet["baits"] == []
    assert sorted({b["page"] for b in bait["baits"]}) == [2, 3]


def test_the_stale_and_blind_documents_are_marked():
    flags = {i: (extra(i)["expect_stale"], extra(i)["expect_blind"]) for i in EXTRA_IDS}
    assert any(stale for stale, _ in flags.values())
    assert any(blind for _, blind in flags.values())


def test_the_number_case_has_a_value_that_is_also_in_the_table():
    case_id = next(e["id"] for e in MANIFEST if "number-case" in e["tags"])
    with pymupdf.open(DEFAULT_OUT / f"{case_id}.pdf") as pdf:
        layer = load_layer(pdf[0])
    assert len(find_candidates(layer, tokenize("2018"))) > 1
