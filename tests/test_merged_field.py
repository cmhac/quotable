"""Table.merged and MergedPart: the audit record of spec 007's merge step."""

import dataclasses

import pytest

import quotable
from quotable.table import MergedPart, MergeEvidence, PageResult, Table


def _table() -> Table:
    return Table(["A"], [PageResult(1, [{"A": "x"}])], {}, {}, {})


def test_a_table_built_the_old_way_has_nothing_merged():
    assert _table().merged == ()


def test_merged_follows_ocr_pages_so_positional_construction_still_works():
    # spec 010 appended its three extra-field members after `merged`
    names = [f.name for f in dataclasses.fields(Table)]
    assert names[names.index("merged") - 1] == "ocr_pages"
    assert names[names.index("merged") + 1 :] == ["extra_fields", "extra_names", "extra_changes"]


def test_merged_part_is_frozen_and_hashable():
    part = MergedPart(pages=(7, 8), columns=("A", "B"), evidence=MergeEvidence())
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(part, "pages", (1,))  # noqa: B010
    assert hash(part) == hash(
        MergedPart(pages=(7, 8), columns=("A", "B"), evidence=MergeEvidence())
    )


def test_replace_and_equality_keep_working_with_a_merged_part():
    part = MergedPart(pages=(7,), columns=("A",), evidence=MergeEvidence())
    table = dataclasses.replace(_table(), merged=(part,))
    assert table.merged == (part,)
    assert table != _table()


def test_merged_part_is_exported():
    assert quotable.MergedPart is MergedPart
    assert quotable.MergeEvidence is MergeEvidence
    assert "MergedPart" in quotable.__all__


def test_the_evidence_is_typed_and_frozen_so_the_audit_record_is_hashable():
    evidence = MergeEvidence(
        token_sets=((("amount",), ("amount", "requested")),),
        equal_positions=0,
        max_x_difference=1.5,
        shapes=("currency",),
        cells=((6, 7),),
    )
    part = MergedPart(pages=(7,), columns=("Amount",), evidence=evidence)
    assert hash(part) == hash(dataclasses.replace(part))
    assert part.evidence.max_x_difference == 1.5
