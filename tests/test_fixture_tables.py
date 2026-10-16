"""Rebuilding `Table`s from the golden fixture's truth files and real text layers."""

import json

import pytest

from tests.fixture_tables import DATA, doc_ids, load_doc, relations, tables_of

IDS = doc_ids()


def test_every_manifest_document_is_listed():
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert [entry["id"] for entry in manifest] == IDS
    assert len(IDS) >= 150


@pytest.mark.parametrize("doc_id", IDS)
def test_every_part_builds_a_table_whose_cells_ground_exactly(doc_id):
    truth = load_doc(doc_id)
    tables = tables_of(doc_id)
    assert sorted(tables) == sorted(p["id"] for p in truth["parts"])
    for part in truth["parts"]:
        table = tables[part["id"]]
        assert table.columns == part["columns"]
        assert [r.page for r in table.pages] == part["pages"]
        for page in table.pages:
            for row, cells in zip(
                table.grounded[page.page].rows, table.grounded[page.page].cells, strict=True
            ):
                for column, grounding in cells.items():
                    expected = "empty" if not row[column] else "exact"
                    assert grounding.status == expected, (doc_id, part["id"], page.page, column)
        assert table.position["misplaced"] == 0


def test_a_part_on_a_shared_page_gets_only_its_own_band():
    tables = tables_of("struct-shared-page")
    a, b = tables["A"], tables["B"]
    assert sorted(a.layers) == sorted(b.layers)  # the same pages
    for page in a.layers:
        a_boxes = {w.bbox for w in a.layers[page].words}
        b_boxes = {w.bbox for w in b.layers[page].words}
        assert a_boxes
        assert b_boxes
        assert not a_boxes & b_boxes


def test_relations_carry_the_labels():
    rels = relations("struct-shared-page")
    assert rels[0]["expect_merge"] is False
    assert rels[0]["stage"] == "merge"
