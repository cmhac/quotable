"""Extra fields (spec 010): the request types, their validation and the pure steps."""

import asyncio
import dataclasses
import json

import pymupdf
import pytest

import quotable
from quotable.llm.answers import ExtraValue, PageExtras
from quotable.llm.client import Image
from quotable.steps.extra_fields import (
    ExtraField,
    ExtraFields,
    ExtraResult,
    FieldGroup,
    field_regions,
    find_suspects,
    flatten,
    ground_fields,
    propagate,
    second_look,
    table_bands,
    validate_extra_fields,
)
from quotable.steps.grounding import FieldGrounding
from quotable.text.layer import Layer, load_layer
from tests.conftest import DATA

A = ExtraField("division", "The division at the top left")
B = ExtraField("year", "The funding year")
C = ExtraField("agency", "The agency")


def test_the_types_are_exported_from_the_package():
    from quotable.steps import extra_fields  # noqa: PLC0415

    for name in ("ExtraField", "FieldGroup", "ExtraFields"):
        assert name in quotable.__all__
        assert getattr(quotable, name) is getattr(extra_fields, name)


def test_the_carry_is_off_unless_asked_for():
    assert ExtraFields([A]).carry_forward is False
    assert ExtraFields([A], carry_forward=True).carry_forward is True
    assert ExtraFields([A]).prompt == ""


def test_the_types_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        A.name = "other"  # ty: ignore[invalid-assignment]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ExtraFields([A]).prompt = "x"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    "fields",
    [
        [],
        [ExtraField("", "d")],
        [ExtraField("   ", "d")],
        [ExtraField("a", "d"), ExtraField(" a ", "d")],
        [ExtraField("a", "")],
        [ExtraField("a", "  ")],
        [FieldGroup("g", "d", [])],
        [FieldGroup("", "d", [A])],
        [FieldGroup("g", "", [A])],
        [FieldGroup("g", "d", [A]), FieldGroup("g", "d2", [B])],
        [FieldGroup("g", "d", [A]), A],  # a name repeated across a group and an ungrouped field
        [FieldGroup("g", "d", [A, ExtraField("division", "again")])],
    ],
)
def test_bad_requests_raise_value_error(fields):
    with pytest.raises(ValueError, match=r"\S"):
        validate_extra_fields(ExtraFields(fields))


def test_a_group_inside_a_group_is_a_type_error():
    inner = FieldGroup("inner", "d", [A])
    with pytest.raises(TypeError):
        validate_extra_fields(ExtraFields([FieldGroup("outer", "d", [inner])]))  # ty: ignore[invalid-argument-type]


def test_other_items_are_type_errors():
    with pytest.raises(TypeError):
        validate_extra_fields(ExtraFields(["division"]))  # ty: ignore[invalid-argument-type]


def test_the_message_names_the_offender():
    with pytest.raises(ValueError, match="'year'"):
        validate_extra_fields(ExtraFields([A, ExtraField("year", ""), B]))


def test_a_group_of_one_field_is_allowed():
    validate_extra_fields(ExtraFields([FieldGroup("g", "d", [A])]))


def test_flatten_keeps_the_order_of_the_list_with_groups_in_place():
    request = ExtraFields([C, FieldGroup("g", "d", [A, B]), ExtraField("z", "last")])
    assert [(f.name, g) for f, g in flatten(request)] == [
        ("agency", None),
        ("division", "g"),
        ("year", "g"),
        ("z", None),
    ]


# --- grounding the values and finding their place (requirement 8) ------------------------------
SENATE = DATA / "senate_expenditures_paddleocr.pdf"


def layer_of(*words):
    """A layer from (text, x, y) words; each word is 30 x 8 pt."""
    layer = Layer()
    for text, x, y in words:
        layer.add(text, (x, y, x + 30, y + 8))
    return layer


def test_a_missing_value_is_empty_and_has_no_place():
    (result,) = ground_fields(layer_of(("Roads", 10, 10)), {"division": None}).values()
    assert result.status == "empty"
    assert result.bbox is None


def test_an_exact_value_has_its_place():
    layer = layer_of(("Division", 10, 10), ("Roads", 50, 10))
    got = ground_fields(layer, {"division": "Roads"})["division"]
    assert (got.status, got.coverage, got.bbox) == ("exact", 1.0, (50, 10, 80, 18))


def test_a_value_that_is_not_on_the_page_is_ungrounded():
    got = ground_fields(layer_of(("Roads", 10, 10)), {"division": "Harbors"})["division"]
    assert (got.status, got.coverage, got.bbox) == ("ungrounded", 0.0, None)


def test_a_value_with_no_letters_or_digits_is_untokenized():
    got = ground_fields(layer_of(("Roads", 10, 10)), {"division": "***"})["division"]
    assert got.status == "untokenized"


def test_a_partial_match_is_fuzzy_as_for_a_table_cell():
    layer = layer_of(("Department", 10, 10), ("of", 45, 10), ("Roads", 60, 10), ("and", 95, 10))
    got = ground_fields(layer, {"division": "Department of Roads and Bridges"})["division"]
    assert got.status == "fuzzy"
    assert got.coverage is not None
    assert 0.75 <= got.coverage < 1.0
    assert got.bbox is not None


def test_misplaced_never_occurs():
    layer = layer_of(("Roads", 10, 10), ("Roads", 10, 200), ("2018", 50, 10), ("2018", 50, 200))
    statuses = {
        g.status for g in ground_fields(layer, {"a": "Roads", "b": "2018", "c": "x"}).values()
    }
    assert "misplaced" not in statuses


def test_a_repeated_value_takes_the_place_nearest_the_unambiguous_fields():
    layer = layer_of(
        ("2018", 10, 300),  # a number in a table far from the header
        ("2018", 50, 20),  # the header's year
        ("Roads", 10, 20),  # unambiguous, in the header
        ("2018", 10, 500),
    )
    got = ground_fields(layer, {"division": "Roads", "year": "2018"})
    assert got["year"].n_candidates == 3
    assert got["year"].bbox == (50, 20, 80, 28)
    assert got["division"].bbox == (10, 20, 40, 28)


def test_without_an_unambiguous_field_a_repeated_value_has_no_place():
    layer = layer_of(("2018", 10, 20), ("2018", 10, 300))
    got = ground_fields(layer, {"year": "2018"})["year"]
    assert (got.status, got.n_candidates, got.bbox) == ("exact", 2, None)


def test_the_senate_header_grounds_exact_and_the_year_is_placed_in_the_header():
    with pymupdf.open(SENATE) as pdf:
        layer = load_layer(pdf[0])
    values = {
        "appropriation": "APPROPRIATIONS",
        "year": "2018",
        "title": "SALARIES, OFFICERS AND EMPLOYEES, SENATE",
    }
    got = ground_fields(layer, values)
    assert {g.status for g in got.values()} == {"exact"}
    assert got["year"].n_candidates == 5  # four more are dates in the summary table
    box = got["year"].bbox
    assert box is not None
    x0, y0, x1, y1 = box
    assert (38 < x0 < 102 and x1 < 110) and (y0 > 80 and y1 < 96)


def test_extra_result_defaults_to_missing():
    result = ExtraResult()
    assert (result.value, result.source_page, result.grounding.status) == ("", None, "empty")


# --- the carry rule and groups (requirement 10) ------------------------------------------------


SYNTHETIC = DATA / "synthetic"


def printed_on(page, value, status="exact"):
    return ExtraResult(value, page, FieldGrounding(status, 1.0 if status == "exact" else 0.8))


def request_of(*items, carry=True):
    return ExtraFields(list(items), carry_forward=carry)


def shown(result):
    """page -> name -> (value, source page) or None, for comparing."""
    return {
        page: {n: (r.value, r.source_page) if r.source_page else None for n, r in row.items()}
        for page, row in result.items()
    }


def walk(request, printed, pages):
    return shown(propagate(pages, printed, flatten(request), carry_forward=request.carry_forward))


def test_without_the_carry_a_page_has_only_what_it_prints():
    request = request_of(A, carry=False)
    got = walk(request, {1: {"division": printed_on(1, "Roads")}}, [1, 2, 3])
    assert got == {1: {"division": ("Roads", 1)}, 2: {"division": None}, 3: {"division": None}}


def test_a_missing_field_is_an_empty_result():
    result = propagate([1], {}, flatten(request_of(A)), carry_forward=True)
    assert result[1]["division"].grounding.status == "empty"
    assert (result[1]["division"].value, result[1]["division"].source_page) == ("", None)


@pytest.mark.parametrize("section", [0, 1, 2, 7])
def test_a_value_carries_over_the_continuation_pages_of_its_section(section):
    pages = list(range(1, 3 + section))
    printed = {2: {"division": printed_on(2, "Roads")}}
    got = walk(request_of(A), printed, pages)
    assert got[1] == {"division": None}  # before the first block: missing, never backwards
    assert all(got[p] == {"division": ("Roads", 2)} for p in pages[1:])


def test_a_later_block_replaces_the_value_from_its_page_on():
    printed = {1: {"division": printed_on(1, "Roads")}, 3: {"division": printed_on(3, "Parks")}}
    got = walk(request_of(A), printed, [1, 2, 3, 4])
    assert [got[p]["division"] for p in (1, 2, 3, 4)] == [
        ("Roads", 1),
        ("Roads", 1),
        ("Parks", 3),
        ("Parks", 3),
    ]


def test_the_same_value_printed_again_starts_a_new_source_page():
    printed = {1: {"division": printed_on(1, "Roads")}, 3: {"division": printed_on(3, "Roads")}}
    got = walk(request_of(A), printed, [1, 2, 3, 4])
    assert [got[p]["division"][1] for p in (1, 2, 3, 4)] == [1, 1, 3, 3]


def test_a_page_without_a_table_still_counts_as_a_page_of_the_walk():
    got = walk(request_of(A), {2: {"division": printed_on(2, "Roads")}}, [1, 2, 3])
    assert got[3] == {"division": ("Roads", 2)}


def test_fields_carry_independently_when_ungrouped():
    printed = {
        1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")},
        3: {"year": printed_on(3, "2019")},
    }
    got = walk(request_of(A, B), printed, [1, 2, 3, 4])
    assert got[4] == {"division": ("Roads", 1), "year": ("2019", 3)}


def test_the_carried_value_keeps_its_grounding():
    printed = {1: {"division": printed_on(1, "Roads", "fuzzy")}}
    result = propagate([1, 2], printed, flatten(request_of(A)), carry_forward=True)
    assert result[2]["division"].grounding.status == "fuzzy"
    assert result[2]["division"].grounding.coverage == 0.8


GROUP = FieldGroup("heading", "Division and year, printed together", [A, B])


def test_a_block_that_prints_one_field_of_a_group_clears_the_other():
    printed = {
        1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")},
        3: {"year": printed_on(3, "2019")},
    }
    got = walk(request_of(GROUP), printed, [1, 2, 3, 4, 5])
    assert got[2] == {"division": ("Roads", 1), "year": ("2018", 1)}  # no block here: both carry
    assert got[3] == {"division": None, "year": ("2019", 3)}
    assert got[5] == {"division": None, "year": ("2019", 3)}  # stays cleared until printed


def test_a_cleared_field_returns_when_a_page_prints_it():
    printed = {
        1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")},
        2: {"year": printed_on(2, "2019")},
        4: {"division": printed_on(4, "Parks")},
    }
    got = walk(request_of(GROUP), printed, [1, 2, 3, 4, 5])
    assert got[3]["division"] is None
    assert got[4] == {"division": ("Parks", 4), "year": None}


def test_a_page_that_prints_no_field_of_the_group_leaves_it_carrying():
    printed = {1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")}}
    got = walk(request_of(GROUP), printed, [1, 2, 3])
    assert got[3] == {"division": ("Roads", 1), "year": ("2018", 1)}


@pytest.mark.parametrize("status", ["ungrounded", "untokenized"])
def test_an_ungrounded_value_does_not_clear_its_siblings(status):
    printed = {
        1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")},
        2: {"year": printed_on(2, "2O19", status)},
    }
    got = walk(request_of(GROUP), printed, [1, 2])
    assert got[2] == {"division": ("Roads", 1), "year": ("2O19", 2)}


def test_a_fuzzy_value_does_clear_its_siblings():
    printed = {
        1: {"division": printed_on(1, "Roads"), "year": printed_on(1, "2018")},
        2: {"year": printed_on(2, "2019", "fuzzy")},
    }
    assert walk(request_of(GROUP), printed, [1, 2])[2]["division"] is None


def test_a_field_outside_the_group_is_never_cleared():
    printed = {
        1: {
            "division": printed_on(1, "Roads"),
            "year": printed_on(1, "2018"),
            "agency": printed_on(1, "H"),
        },
        2: {"year": printed_on(2, "2019")},
    }
    got = walk(request_of(GROUP, C), printed, [1, 2])
    assert got[2] == {"division": None, "year": ("2019", 2), "agency": ("H", 1)}


def test_a_group_of_one_field_clears_nothing():
    printed = {
        1: {"division": printed_on(1, "Roads"), "agency": printed_on(1, "H")},
        2: {"agency": printed_on(2, "K")},
    }
    got = walk(request_of(FieldGroup("g", "d", [C]), A), printed, [1, 2])
    assert got[2] == {"agency": ("K", 2), "division": ("Roads", 1)}


def test_without_the_carry_groups_change_nothing():
    printed = {1: {"year": printed_on(1, "2018")}}
    got = walk(request_of(GROUP, carry=False), printed, [1, 2])
    assert got[1] == {"division": None, "year": ("2018", 1)}
    assert got[2] == {"division": None, "year": None}


def _fixture_ids():
    manifest = json.loads((SYNTHETIC / "manifest.json").read_text())
    return [e["id"] for e in manifest if e["id"].startswith("extra-")]


@pytest.mark.parametrize("case_id", _fixture_ids())
def test_propagate_agrees_with_the_fixture_oracle(case_id):
    truth = json.loads((SYNTHETIC / f"{case_id}.json").read_text())["extra_fields"]
    names = [f["name"] for f in truth["fields"]]
    printed = {
        int(page): {n: printed_on(int(page), v) for n, v in row.items() if v is not None}
        for page, row in truth["printed"].items()
    }
    pages = sorted(printed)
    fields = [(ExtraField(f["name"], f["description"]), f["group"]) for f in truth["fields"]]
    ungrouped = [(f, None) for f, _ in fields]

    def expect(table):
        return {
            int(p): {n: (v["value"], v["source_page"]) if v else None for n, v in row.items()}
            for p, row in table.items()
        }

    assert shown(propagate(pages, printed, fields, carry_forward=True)) == expect(
        truth["expected"]["carry"]
    )
    assert shown(propagate(pages, printed, ungrouped, carry_forward=True)) == expect(
        truth["expected"]["carry_ungrouped"]
    )
    assert shown(propagate(pages, printed, fields, carry_forward=False)) == expect(
        truth["expected"]["plain"]
    )
    assert list(next(iter(truth["expected"]["plain"].values()))) == names


# --- the missed-header check and the second look (requirements 11 and 12) ---------------------


def test_a_fields_region_is_the_union_of_its_places_plus_six_points():
    regions = field_regions({"a": [(10, 20, 30, 40), (50, 10, 70, 30)], "b": []})
    assert regions == {"a": (4, 4, 76, 46)}


def senate_state():
    """Layers, the printing page's groundings and the tables' bands, as discovery reports them."""
    recorded = json.loads((DATA / "senate_expenditures_paddleocr.rows.json").read_text())
    with pymupdf.open(SENATE) as pdf:
        layers = {i + 1: load_layer(p) for i, p in enumerate(pdf)}
    values = {
        "appropriation": "APPROPRIATIONS",
        "year": "2018",
        "title": "SALARIES, OFFICERS AND EMPLOYEES, SENATE",
    }
    printed = {1: ground_fields(layers[1], values)}
    rows = {
        page: [(t["first_row"], t["last_row"]) for t in entry["tables"]]
        for page, entry in enumerate(recorded["discovery"]["pages"], 1)
    }
    bands = {p: table_bands(layers[p], rows[p]) for p in layers}
    return layers, printed, bands


def test_on_the_senate_sample_the_continuation_pages_are_not_suspect():
    layers, printed, bands = senate_state()
    assert find_suspects(layers, printed, bands) == {}


def test_without_the_band_exclusion_both_continuation_pages_would_be_suspect():
    layers, printed, _ = senate_state()
    suspects = find_suspects(layers, printed, {})
    assert sorted(suspects) == [2, 3]
    assert "title" in suspects[2]


def test_the_pages_that_print_the_field_are_not_checked():
    layers, printed, _ = senate_state()
    assert 1 not in find_suspects(layers, printed, {})


def test_a_field_with_no_place_has_no_region_and_is_not_checked():
    layers, printed, _ = senate_state()
    printed = {1: {"year": FieldGrounding("exact", n_candidates=5)}}
    assert find_suspects(layers, printed, {}) == {}


def test_a_missed_header_is_seen_as_evidence_outside_the_tables():
    header = layer_of(("Division", 10, 20), ("Roads", 50, 20), ("Cedar", 10, 300))
    missed = layer_of(("Division", 10, 20), ("Parks", 50, 20), ("Cedar", 10, 300))
    clean = layer_of(("Cedar", 10, 300))
    printed = {1: ground_fields(header, {"division": "Roads"})}
    got = find_suspects({1: header, 2: missed, 3: clean}, printed, {3: [(290, 320)]})
    assert got == {2: {"division": ["Parks"]}}


def test_a_table_row_inside_the_region_is_not_evidence():
    header = layer_of(("Roads", 10, 20))
    page = layer_of(("Cedar", 10, 22))
    printed = {1: ground_fields(header, {"division": "Roads"})}
    assert find_suspects({1: header, 2: page}, printed, {2: [(15, 35)]}) == {}
    assert find_suspects({1: header, 2: page}, printed, {}) == {2: {"division": ["Cedar"]}}


def test_table_bands_come_from_the_first_and_last_row_text():
    layer = layer_of(("Name", 10, 20), ("Cedar", 10, 50), ("Maple", 10, 80), ("Total", 10, 110))
    assert table_bands(layer, [("Cedar", "Maple")]) == [(46.0, 92.0)]
    assert table_bands(layer, [("Cedar", "nowhere")]) == []  # not located: remove nothing


class Asker:
    identity = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    async def ask(self, request):
        self.requests.append(request)
        return self.answer


def look(client, layer, wanted=("division",), evidence=None):
    fields = {f.name: f for f in (A, B) if f.name in wanted}
    return asyncio.run(
        second_look(2, b"png", layer, fields, evidence or {"division": ["Parks"]}, client)
    )


def test_a_grounded_second_look_answer_makes_the_page_print_the_field():
    layer = layer_of(("Division", 10, 20), ("Parks", 50, 20))
    client = Asker(PageExtras(extras=[ExtraValue(name="division", value="Parks")]))
    got = look(client, layer)
    assert got["division"].value == "Parks"
    assert got["division"].source_page == 2
    assert got["division"].grounding.status == "exact"
    (request,) = client.requests
    assert request.stage == "extras"
    assert request.page == 2
    assert isinstance(request.parts[0], Image)
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    assert "division" in text
    assert "Parks" in text


@pytest.mark.parametrize("answer", [None, "", "Harbors"])
def test_a_null_or_ungrounded_second_look_answer_changes_nothing(answer):
    layer = layer_of(("Division", 10, 20), ("Parks", 50, 20))
    client = Asker(PageExtras(extras=[ExtraValue(name="division", value=answer)]))
    assert look(client, layer) == {}


def test_a_second_look_answer_for_a_field_that_was_not_asked_is_ignored():
    layer = layer_of(("Parks", 50, 20), ("2018", 10, 20))
    client = Asker(
        PageExtras(
            extras=[
                ExtraValue(name="division", value="Parks"),
                ExtraValue(name="year", value="2018"),
            ]
        )
    )
    assert list(look(client, layer)) == ["division"]
