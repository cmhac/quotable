"""The second look at extra field values that grounded fuzzy or not at all (requirement 9)."""

import asyncio

import pytest

from quotable.extra_fields import ExtraField, ExtraResult, ground_fields
from quotable.grounding import FieldGrounding
from quotable.llm import Image
from quotable.models import ExtrasRecheck, ExtraValue
from quotable.recheck import recheck_fields
from quotable.text import Layer

FIELDS = {
    "division": ExtraField("division", "The division at the top left"),
    "year": ExtraField("year", "The funding year"),
}


def layer_of(*words):
    layer = Layer()
    for text, x, y in words:
        layer.add(text, (x, y, x + 30, y + 8))
    return layer


class Asker:
    identity = "fake"

    def __init__(self, answers):
        self.answers = answers
        self.requests = []

    async def ask(self, request):
        self.requests.append(request)
        return ExtrasRecheck(extras=[ExtraValue(name=n, value=v) for n, v in self.answers.items()])


def printed_from(layer, values, page=1):
    grounded = ground_fields(layer, values)
    return {page: {n: ExtraResult(values[n], page, g) for n, g in grounded.items()}}


def run(printed, layers, client):
    return asyncio.run(recheck_fields(printed, layers, [b"png1", b"png2"], FIELDS, client))


def test_a_better_answer_is_accepted_and_reported():
    layer = layer_of(("Division", 10, 10), ("Roads", 50, 10), ("2018", 90, 10))
    printed = printed_from(layer, {"division": "Raods", "year": "2018"})
    assert printed[1]["division"].grounding.status == "ungrounded"
    client = Asker({"division": "Roads"})
    got, changes = run(printed, {1: layer}, client)
    assert got[1]["division"].value == "Roads"
    assert got[1]["division"].grounding.status == "exact"
    assert got[1]["division"].source_page == 1
    assert got[1]["year"].value == "2018"
    assert changes == {(1, "division"): ("Raods", "Roads")}


def test_a_request_has_the_image_the_text_layer_and_the_flagged_field_only():
    layer = layer_of(("Division", 10, 10), ("Roads", 50, 10), ("2018", 90, 10))
    printed = printed_from(layer, {"division": "Raods", "year": "2018"})
    client = Asker({"division": "Roads"})
    run(printed, {1: layer}, client)
    (request,) = client.requests
    assert (request.stage, request.page) == ("recheck", 1)
    assert isinstance(request.parts[0], Image)
    text = "\n".join(p for p in request.parts if isinstance(p, str))
    assert "Division Roads 2018" in text  # the whole text layer
    assert "Raods" in text
    assert "year" not in text.split("Fields to re-check:")[1]  # exact fields are not asked


@pytest.mark.parametrize("answer", ["Raods", "Harbors", "", "  ", None])
def test_an_answer_that_is_not_strictly_better_is_not_kept(answer):
    layer = layer_of(("Division", 10, 10), ("Roads", 50, 10))
    printed = printed_from(layer, {"division": "Raods"})
    got, changes = run(printed, {1: layer}, Asker({"division": answer}))
    assert got[1]["division"].value == "Raods"
    assert changes == {}


def test_a_fuzzy_value_stays_when_the_answer_is_only_as_fuzzy():
    layer = layer_of(("Department", 10, 10), ("of", 45, 10), ("Roads", 60, 10), ("and", 95, 10))
    printed = printed_from(layer, {"division": "Department of Roads and Bridges"})
    assert printed[1]["division"].grounding.status == "fuzzy"
    got, changes = run(printed, {1: layer}, Asker({"division": "Department of Roads and Brigdes"}))
    assert got[1]["division"].value == "Department of Roads and Bridges"
    assert changes == {}


def test_one_request_per_page_and_none_when_nothing_is_flagged():
    layer = layer_of(("Roads", 10, 10), ("2018", 50, 10))
    clean = printed_from(layer, {"division": "Roads", "year": "2018"})
    client = Asker({})
    run(clean, {1: layer}, client)
    assert client.requests == []
    both = printed_from(layer, {"division": "Raods", "year": "2O18"})
    client = Asker({"division": "Roads", "year": "2018"})
    got, changes = run(both, {1: layer}, client)
    assert len(client.requests) == 1
    assert set(changes) == {(1, "division"), (1, "year")}
    assert got[1]["year"].value == "2018"


def test_pages_are_asked_separately():
    one = layer_of(("Roads", 10, 10))
    two = layer_of(("Parks", 10, 10))
    printed = {
        **printed_from(one, {"division": "Raods"}, 1),
        **printed_from(two, {"division": "Prks"}, 2),
    }
    client = Asker({"division": "Roads"})
    run(printed, {1: one, 2: two}, client)
    assert sorted(r.page for r in client.requests) == [1, 2]


def test_a_missing_value_is_never_asked_about():
    layer = layer_of(("Roads", 10, 10))
    printed = {1: {"division": ExtraResult("", None, FieldGrounding("empty"))}}
    client = Asker({})
    run(printed, {1: layer}, client)
    assert client.requests == []
