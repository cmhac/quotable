"""merge_tables: which pairs join (mutual uniqueness) and what the merged table holds."""

import pytest

from quotable.steps.merge import DEFAULT_RULES, Rules, merge_tables, mergeable_pairs
from quotable.table import MergedPart
from tests.fixture_tables import discovered, doc_ids, load_doc
from tests.steps.test_merge_checks import A_COLUMNS, B_COLUMNS, table


def pair(tmp_path, **b_options):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=7, name="b", start=6, **b_options)
    return a, b


# --- who may merge --------------------------------------------------------------------


def test_one_compatible_pair_is_mergeable(tmp_path):
    a, b = pair(tmp_path)
    assert mergeable_pairs([a, b], DEFAULT_RULES) == [(0, 1)]


def test_a_table_with_two_partners_merges_with_neither(tmp_path):
    a, b = pair(tmp_path)
    c = table(tmp_path, B_COLUMNS, first_page=12, name="c", start=12)
    assert mergeable_pairs([a, b, c], DEFAULT_RULES) == []
    assert merge_tables([a, b, c]) == [a, b, c]


def test_the_pair_is_ordered_by_first_page_whatever_the_list_order(tmp_path):
    a, b = pair(tmp_path)
    assert mergeable_pairs([b, a], DEFAULT_RULES) == [(1, 0)]


def test_unrelated_tables_do_not_block_a_pair(tmp_path):
    a, b = pair(tmp_path)
    other = table(tmp_path, ["Applicant", "Award", "Round"], first_page=4, name="o")
    merged = merge_tables([a, other, b])
    assert len(merged) == 2
    assert merged[1] is other
    assert merged[0].merged  # A's place


# --- what a merge produces ------------------------------------------------------------


def test_the_merged_table_holds_both_parts_under_a_names(tmp_path):
    a, b = pair(tmp_path)
    (merged,) = merge_tables([a, b])
    assert merged.columns == A_COLUMNS
    assert [r.page for r in merged.pages] == [1, 7]
    assert all(set(row) == set(A_COLUMNS) for r in merged.pages for row in r.rows)
    assert merged.pages[1].rows[0][A_COLUMNS[1]] == b.pages[0].rows[0][B_COLUMNS[1]]
    assert sorted(merged.layers) == [1, 7]
    assert merged.label == a.label


def test_the_merged_table_is_grounded_and_position_checked_as_a_whole(tmp_path):
    a, b = pair(tmp_path)
    (merged,) = merge_tables([a, b])
    assert sorted(merged.grounded) == [1, 7]
    statuses = {
        cell.status
        for page in merged.grounded.values()
        for row in page.cells
        for cell in row.values()
    }
    assert statuses == {"exact"}
    assert merged.position == {"misplaced": 0, "unchecked": merged.position["unchecked"]}
    assert len(merged.layouts) == 2
    assert all(layout.columns == tuple(A_COLUMNS) for layout in merged.layouts)
    assert len(merged.rows()) == 12


def test_the_audit_entry_says_what_was_joined(tmp_path):
    a, b = pair(tmp_path)
    (merged,) = merge_tables([a, b])
    (part,) = merged.merged
    assert isinstance(part, MergedPart)
    assert part.pages == (7,)
    assert part.columns == tuple(B_COLUMNS)
    assert part.evidence.equal_positions == 2
    assert part.evidence.shapes == ("text", "currency", "text")
    assert part.evidence.max_x_difference < 10
    assert part.evidence.token_sets[1] == (
        ("local", "match", "requested"),
        ("match", "requested"),
    )


def test_the_inputs_are_not_changed(tmp_path):
    a, b = pair(tmp_path)
    before = (list(a.columns), list(b.columns), [r.page for r in b.pages], b.merged)
    merge_tables([a, b])
    assert (list(a.columns), list(b.columns), [r.page for r in b.pages], b.merged) == before
    assert b.pages[0].rows[0].keys() == set(B_COLUMNS)


def test_word_order_only_merges(tmp_path):
    a_cols = ["Project Name", "Amount Requested", "Status"]
    b_cols = ["Project Name", "Requested Amount", "Status"]
    a = table(tmp_path, a_cols, name="a")
    b = table(tmp_path, b_cols, first_page=7, name="b", start=6)
    assert len(merge_tables([a, b])) == 1


# --- nothing merges: nothing changes --------------------------------------------------


def test_when_nothing_merges_the_same_list_comes_back(tmp_path):
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, ["Applicant", "Award", "Round"], first_page=7, name="b")
    tables = [a, b]
    assert merge_tables(tables) is tables
    assert merge_tables([]) == []


def test_merge_tables_with_rules_that_refuse_returns_the_input(tmp_path):
    a, b = pair(tmp_path)
    tables = [a, b]
    assert merge_tables(tables, rules=Rules(min_cells=50)) is tables


# --- must not merge -------------------------------------------------------------------


def test_the_ambiguous_bare_amount_does_not_merge(tmp_path):
    a_cols = ["Project Name", "Requested Amount", "Recommended Amount"]
    b_cols = ["Project Name", "Amount", "Recommended Amount"]
    a = table(tmp_path, a_cols, name="a")
    b = table(tmp_path, b_cols, first_page=7, name="b", start=6)
    assert len(merge_tables([a, b])) == 2


def test_three_mutually_compatible_tables_do_not_merge(tmp_path):
    cols = [
        ["Project Name", "Requested Amount", "Status"],
        ["Project Name", "Requested Amount Total", "Status"],
        ["Project Name", "Amount Requested Now", "Status"],
    ]
    tables = [
        table(tmp_path, c, first_page=1 + 6 * i, name=f"t{i}", start=6 * i)
        for i, c in enumerate(cols)
    ]
    assert len(merge_tables(tables)) == 3


def test_interleaved_tables_do_not_merge(tmp_path):
    # A pages 1, B pages 4, A' pages 7: A and A' are compatible and so are B and A',
    # so A' has two partners and nothing joins
    a = table(tmp_path, A_COLUMNS, name="a")
    b = table(tmp_path, B_COLUMNS, first_page=4, name="b", start=6)
    c = table(tmp_path, B_COLUMNS, first_page=7, name="c", start=12)
    assert len(merge_tables([a, b, c])) == 3


# --- the fixture ----------------------------------------------------------------------


def _settled():
    cases = []
    for doc_id in doc_ids():
        for rel in load_doc(doc_id)["relations"]:
            if rel["stage"] == "merge" and rel["expect_merge"] is not None:
                cases.append(pytest.param(doc_id, rel, id=f"{doc_id}:{rel['a']}{rel['b']}"))
    return cases


def _pages(table_) -> set[int]:
    return {r.page for r in table_.pages}


@pytest.mark.parametrize(("doc_id", "rel"), _settled())
def test_every_settled_fixture_relation_comes_out_as_expected(doc_id, rel):
    tables, member = discovered(doc_id)
    output = merge_tables(tables)
    a, b = tables[member[rel["a"]]], tables[member[rel["b"]]]
    together = a is b or any(
        t.merged and _pages(a) <= _pages(t) and _pages(b) <= _pages(t) for t in output
    )
    assert together is rel["expect_merge"], rel["note"]
