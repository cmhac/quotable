"""The review queue, sampling and statistics (spec 013, task 005)."""

import math
import random
from collections.abc import Mapping
from dataclasses import replace

import pytest

from quotable.review.queue import (
    FLAGGED,
    Item,
    QueueSettings,
    counts_by_status,
    population,
    review_state,
    sample,
    statistics,
    suggested_size,
    wilson,
    z,
)
from quotable.review.verdicts import CellKey, ExtraKey, Key, Verdict
from quotable.runs import Run, RunCell, RunExtra, RunRow, RunSummary, RunTable

SHA = "ab" * 32
OTHER_SHA = "cd" * 32
COLUMNS = ["Project", "Amount"]


# --- builders ---------------------------------------------------------------------------------
def run_cell(status: str = "exact") -> RunCell:
    return RunCell(status, 1.0, 1.0, 1, None, None, [])


def make_table(
    index: int = 0,
    rows: list[tuple[int, dict[str, str]]] | None = None,
    extras: Mapping[int, Mapping[str, tuple[str, int | None]]] | None = None,
    columns: list[str] | None = None,
) -> RunTable:
    """Rows are ``(page, {column: status})``, numbered from 1 on each page."""
    columns = columns or COLUMNS
    counted: dict[int, int] = {}
    built: list[RunRow] = []
    for page, statuses in rows or []:
        counted[page] = counted.get(page, 0) + 1
        values = {c: f"{c}{page}.{counted[page]}" for c in columns}
        cells = {c: run_cell(statuses.get(c, "exact")) for c in columns}
        built.append(RunRow(page, counted[page], values, cells))
    fields = {
        page: {n: RunExtra(f"{n}@{src}", src, run_cell(status)) for n, (status, src) in e.items()}
        for page, e in (extras or {}).items()
    }
    names = sorted({n for e in fields.values() for n in e})
    pages = sorted({r.page for r in built} | set(fields))
    return RunTable(
        index,
        f"Table {index}",
        columns,
        pages,
        [],
        {},
        [],
        {},
        {},
        [],
        [],
        names,
        fields,
        [],
        built,
    )


def make_run(
    run_id: str,
    tables: list[RunTable],
    name: str = "a.pdf",
    sha: str = SHA,
    started: str = "2026-10-20T10:00:00Z",
) -> Run:
    summary = RunSummary(
        run_id, started, started, "0", "m", {}, name, "/x/" + name, 1, sha, 5, 0, 0, {}, [], []
    )
    return Run(summary, {}, tables)


def one(run_id: str = "1" * 32, **kw) -> Run:
    """A run of one table: page 1 has fuzzy / exact and misplaced / exact, page 2 ungrounded."""
    rows = [
        (1, {"Project": "fuzzy"}),
        (1, {"Amount": "misplaced"}),
        (2, {"Amount": "ungrounded", "Project": "untokenized"}),
    ]
    return make_run(run_id, [make_table(0, rows)], **kw)


def where(items: list[Item]) -> list[tuple]:
    return [(i.run[0], i.table_index, i.page, i.row, i.column) for i in items]


def settings(**kw) -> QueueSettings:
    return QueueSettings(**kw)


def numbered(n: int) -> list[Item]:
    return [
        Item(
            run="1" * 32,
            name="a.pdf",
            sha256=SHA,
            table_index=0,
            table_label="T",
            table_columns=("Project", "Amount"),
            page=1 + i // 50,
            row=1 + i % 50,
            column="Amount",
            status="fuzzy",
            extracted=f"v{i}",
            key=CellKey(SHA, ("Project", "Amount"), 1 + i // 50, 1 + i % 50, "Amount"),
        )
        for i in range(n)
    ]


def verdict(item: Item, kind: str, category: str | None = None, extracted: str | None = None):
    return Verdict(
        time="2026-10-20T14:14:07Z",
        run=item.run,
        name=item.name,
        table_index=item.table_index,
        table_label=item.table_label,
        table_columns=item.table_columns,
        key=item.key,
        extracted=item.extracted if extracted is None else extracted,
        status=item.status,
        verdict=kind,
        value="x" if kind == "changed" else None,
        category=category if kind == "changed" else None,
        note="",
    )


def verdicts_for(pairs: list[tuple[Item, str, str | None]]) -> Mapping[Key, Verdict]:
    return {item.key: verdict(item, kind, cat) for item, kind, cat in pairs}


# --- z, suggested size, Wilson ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("confidence", "expected"), [(80, 1.2816), (90, 1.6449), (95, 1.9600), (99, 2.5758)]
)
def test_z(confidence: int, expected: float):
    assert z(confidence) == pytest.approx(expected, abs=1e-4)


def test_suggested_size_mockup():
    assert suggested_size(8, 95, 1846) == 139


def test_suggested_size_by_hand():
    # n0 = 1.96^2 * 0.25 / 0.05^2 = 384.15; 384.15 / (1 + 383.15 / 1000) = 277.7 -> 278
    assert suggested_size(5, 95, 1000) == 278
    # never more than the population
    assert suggested_size(1, 99, 10) <= 10
    assert suggested_size(5, 95, 1) == 1
    assert suggested_size(5, 95, 0) == 0


def test_wilson_mockup():
    low, high = wilson(6, 35, 95)
    assert low == pytest.approx(0.0810, abs=5e-4)
    assert high == pytest.approx(0.3268, abs=5e-4)


def test_wilson_none_changed():
    # k = 0: low is 0 and high is z^2 / (n + z^2) = 3.8415 / 13.8415
    low, high = wilson(0, 10, 95)
    assert low == pytest.approx(0.0, abs=1e-12)
    assert high == pytest.approx(0.2775, abs=1e-4)


def test_wilson_all_changed_is_the_mirror():
    low, high = wilson(10, 10, 95)
    assert (low, high) == pytest.approx((1 - 0.2775, 1.0), abs=1e-4)


# --- statistics -------------------------------------------------------------------------------
def mockup() -> tuple[list[Item], list[Item], Mapping[Key, Verdict]]:
    """N = 1846, n = 120: 6 changed of 35 judged and 2 can't tell."""
    pop = numbered(1846)
    queue = pop[:120]
    kinds = ["changed"] * 6 + ["correct"] * 29 + ["unsure"] * 2
    cats = ["misspelling"] * 3 + ["wrong_number"] * 2 + ["hallucination"]
    pairs = [
        (item, kind, cats[i] if kind == "changed" else None)
        for i, (item, kind) in enumerate(zip(queue, kinds, strict=False))
    ]
    return pop, queue, verdicts_for(pairs)


def test_mockup_figures():
    pop, queue, found = mockup()
    s = statistics(pop, queue, found, settings(mode="sample", sample_size=120))
    assert (s.population, s.sample, s.reviewed) == (1846, 120, 37)
    assert (s.judged, s.unsure, s.changed) == (35, 2, 6)
    assert s.share == pytest.approx(6 / 35)
    assert s.interval is not None
    assert s.interval == pytest.approx((0.0810, 0.3268), abs=5e-4)
    assert s.estimated == pytest.approx(316.4, abs=0.1)
    assert s.estimated_interval is not None
    assert round(s.estimated_interval[0]) == 150
    assert round(s.estimated_interval[1]) == 603
    assert s.margin_before == pytest.approx(0.0865, abs=5e-4)
    assert s.correction_before == pytest.approx(0.967, abs=5e-4)
    assert s.margin_so_far == pytest.approx(0.1237, abs=5e-4)
    assert s.correction_so_far == pytest.approx(0.991, abs=5e-4)
    assert s.margin_before is not None
    assert s.margin_so_far is not None
    assert round(s.margin_before * 100, 1) == 8.7
    assert round(s.margin_so_far * 100, 1) == 12.4
    assert s.confidence == 95


def test_margin_is_the_formula_by_hand():
    pop, queue, found = mockup()
    s = statistics(pop, queue, found, settings(mode="sample", sample_size=120, confidence=90))
    z90 = 1.6448536
    assert s.margin_before == pytest.approx(
        z90 * math.sqrt(0.25 / 120) * math.sqrt((1846 - 120) / (1846 - 1)), abs=1e-6
    )
    p = 6 / 35
    assert s.margin_so_far == pytest.approx(
        z90 * math.sqrt(p * (1 - p) / 35) * math.sqrt((1846 - 35) / (1846 - 1)), abs=1e-6
    )


def test_nothing_judged():
    pop = numbered(10)
    s = statistics(pop, pop[:4], {}, settings(mode="sample", sample_size=4))
    assert (s.population, s.sample, s.reviewed, s.judged, s.changed) == (10, 4, 0, 0, 0)
    assert s.share is None
    assert s.interval is None
    assert s.estimated is None
    assert s.estimated_interval is None
    assert s.margin_so_far is None
    assert s.margin_before == pytest.approx(1.959964 * math.sqrt(0.25 / 4) * math.sqrt(6 / 9))
    assert s.categories == []


def test_only_unsure_judged_nothing():
    pop = numbered(5)
    found = verdicts_for([(pop[0], "unsure", None)])
    s = statistics(pop, pop, found, settings())
    assert (s.reviewed, s.judged, s.unsure) == (1, 0, 1)
    assert s.share is None


def test_whole_population_has_no_sampling_error():
    pop = numbered(40)
    found = verdicts_for(
        [(i, "changed" if n < 10 else "correct", "other") for n, i in enumerate(pop)]
    )
    s = statistics(pop, pop, found, settings())
    assert s.correction_before == 0.0
    assert s.correction_so_far == 0.0
    assert s.margin_before == 0.0
    assert s.margin_so_far == 0.0
    assert s.share == pytest.approx(0.25)
    assert s.estimated == pytest.approx(10.0)


def test_population_of_one():
    pop = numbered(1)
    s = statistics(pop, pop, {}, settings())
    assert s.margin_before == 0.0
    assert s.share is None
    found = verdicts_for([(pop[0], "changed", "other")])
    s = statistics(pop, pop, found, settings())
    assert (s.judged, s.changed, s.share) == (1, 1, 1.0)
    assert s.margin_so_far == 0.0
    assert s.estimated == pytest.approx(1.0)


def test_empty_population():
    s = statistics([], [], {}, settings())
    assert (s.population, s.sample, s.reviewed) == (0, 0, 0)
    assert s.margin_before is None
    assert s.share is None
    assert s.by_status == []


def test_stale_verdicts_do_not_count():
    pop = numbered(6)
    found = {
        pop[0].key: verdict(pop[0], "changed", "other"),
        pop[1].key: verdict(pop[1], "changed", "other", extracted="old value"),
        pop[2].key: verdict(pop[2], "correct", extracted="old value"),
    }
    assert review_state(pop[0], found) == "changed"
    assert review_state(pop[1], found) == "stale"
    assert review_state(pop[3], found) == "none"
    s = statistics(pop, pop, found, settings())
    assert (s.reviewed, s.judged, s.changed) == (1, 1, 1)


def test_by_status_and_categories_add_up():
    pop = numbered(12)
    for i, status in enumerate(["fuzzy", "misplaced", "ungrounded"] * 4):
        pop[i] = replace(pop[i], status=status)
    queue = pop[:9]
    kinds = ["changed", "changed", "unsure", "correct", "changed", "correct", "correct", "changed"]
    cats = ["wrong_number", "misspelling", None, None, "wrong_number", None, None, "wrong_number"]
    found = verdicts_for(list(zip(queue, kinds, cats, strict=False)))
    cfg = settings(
        statuses=("fuzzy", "misplaced", "ungrounded"), mode="sample", sample_size=9, seed=3
    )
    s = statistics(pop, queue, found, cfg)
    assert [r.status for r in s.by_status] == ["fuzzy", "misplaced", "ungrounded"]
    assert sum(r.population for r in s.by_status) == s.total.population == 12
    assert sum(r.sampled for r in s.by_status) == s.total.sampled == 9
    assert sum(r.reviewed for r in s.by_status) == s.total.reviewed == s.reviewed == 8
    assert sum(r.judged for r in s.by_status) == s.total.judged == s.judged == 7
    assert sum(r.changed for r in s.by_status) == s.total.changed == s.changed == 4
    assert s.total.status == "All"
    assert s.total.share == pytest.approx(4 / 7)
    fuzzy = s.by_status[0]  # items 0, 3, 6 -> changed, correct, correct
    assert (fuzzy.population, fuzzy.sampled, fuzzy.reviewed) == (4, 3, 3)
    assert fuzzy.share == pytest.approx(1 / 3)
    assert s.categories == [("wrong_number", 3), ("misspelling", 1)]
    assert sum(n for _, n in s.categories) == s.changed


def test_categories_most_first_ties_in_the_specs_order():
    pop = numbered(4)
    found = verdicts_for(
        [
            (pop[0], "changed", "other"),
            (pop[1], "changed", "spacing"),
            (pop[2], "changed", "misspelling"),
            (pop[3], "changed", "spacing"),
        ]
    )
    s = statistics(pop, pop, found, settings())
    assert s.categories == [("spacing", 2), ("misspelling", 1), ("other", 1)]


def test_status_with_nothing_judged_has_no_share():
    pop = numbered(3)
    s = statistics(pop, pop, {}, settings())
    assert s.by_status[0].share is None
    assert s.total.share is None


# --- settings ---------------------------------------------------------------------------------
def test_defaults():
    s = QueueSettings()
    assert s.statuses == FLAGGED
    assert "exact" not in s.statuses
    assert (s.run, s.table, s.column) == (None, None, None)
    assert s.extra_fields is True
    assert (s.mode, s.confidence) == ("all", 95)


def test_from_query_defaults():
    assert QueueSettings.from_query({}) == QueueSettings()


def test_from_query_values():
    s = QueueSettings.from_query(
        {
            "statuses": "fuzzy,exact",
            "run": "f" * 32,
            "table": "2",
            "column": "Amount",
            "extra_fields": "0",
            "mode": "sample",
            "sample_size": "120",
            "confidence": "99",
            "margin": "6.5",
            "seed": "42",
        }
    )
    assert s == QueueSettings(
        statuses=("fuzzy", "exact"),
        run="f" * 32,
        table=2,
        column="Amount",
        extra_fields=False,
        mode="sample",
        sample_size=120,
        confidence=99,
        margin=6.5,
        seed=42,
    )


def test_to_dict_round_trips_through_a_query():
    s = QueueSettings(
        statuses=("misplaced", "exact"), run="a" * 32, table=1, column="Amount", seed=9
    )
    d = s.to_dict()
    assert d["statuses"] == ["misplaced", "exact"]
    assert d["run"] == "a" * 32
    assert d["table"] == 1
    assert d["extra_fields"] is True
    query = {
        k: ",".join(v) if isinstance(v, list) else str(int(v) if isinstance(v, bool) else v)
        for k, v in d.items()
        if v is not None
    }
    assert QueueSettings.from_query(query) == s
    assert QueueSettings().to_dict()["run"] is None


def test_empty_statuses_means_none():
    assert QueueSettings.from_query({"statuses": ""}).statuses == ()


@pytest.mark.parametrize(
    "query",
    [
        {"statuses": "nonsense"},
        {"confidence": "97"},
        {"confidence": "high"},
        {"mode": "everything"},
        {"sample_size": "0"},
        {"sample_size": "x"},
        {"margin": "0"},
        {"margin": "-3"},
        {"table": "-1"},
        {"seed": "1.5"},
        {"extra_fields": "maybe"},
    ],
)
def test_from_query_rejects_bad_values(query: dict[str, str]):
    with pytest.raises(ValueError, match=r"."):
        QueueSettings.from_query(query)


# --- population -------------------------------------------------------------------------------
def test_population_is_the_flagged_cells_in_page_order():
    items = population([one()], settings())
    assert where(items) == [
        ("1", 0, 1, 1, "Project"),
        ("1", 0, 1, 2, "Amount"),
        ("1", 0, 2, 1, "Project"),
        ("1", 0, 2, 1, "Amount"),
    ]
    first = items[0]
    assert first.status == "fuzzy"
    assert first.extracted == "Project1.1"
    assert first.name == "a.pdf"
    assert first.table_label == "Table 0"
    assert first.table_columns == ("Project", "Amount")
    assert first.key == CellKey(SHA, ("Project", "Amount"), 1, 1, "Project")
    assert not first.extra


def test_exact_only_when_chosen():
    run = one()
    assert len(population([run], settings())) == 4
    everything = population([run], settings(statuses=(*FLAGGED, "exact")))
    assert len(everything) == 6  # three rows x two columns
    only_exact = population([run], settings(statuses=("exact",)))
    assert {i.status for i in only_exact} == {"exact"}
    assert len(only_exact) == 2


def test_unflagged_statuses_are_not_in_the_default_population():
    rows = [(1, {"Project": "empty", "Amount": "not_on_page"})]
    assert population([make_run("1" * 32, [make_table(0, rows)])], settings()) == []


def test_counts_by_status_ignore_the_status_boxes():
    run = one()
    counts = counts_by_status([run], settings(statuses=("fuzzy",)))
    assert counts == {"fuzzy": 1, "misplaced": 1, "ungrounded": 1, "untokenized": 1, "exact": 2}
    scoped = counts_by_status([run], settings(column="Project"))
    assert scoped == {"fuzzy": 1, "untokenized": 1, "exact": 1}


def test_all_runs_takes_the_newest_run_of_each_document():
    old = one("1" * 32, started="2026-10-19T10:00:00Z")
    new = one("2" * 32, started="2026-10-20T10:00:00Z")
    other = one("3" * 32, name="b.pdf", sha=OTHER_SHA, started="2026-10-01T10:00:00Z")
    items = population([old, new, other], settings())
    assert {i.run for i in items} == {"2" * 32, "3" * 32}
    assert len(items) == 8
    assert [i.name for i in items] == ["a.pdf"] * 4 + ["b.pdf"] * 4


def test_a_chosen_run_is_used_even_when_older():
    old = one("1" * 32, started="2026-10-19T10:00:00Z")
    new = one("2" * 32, started="2026-10-20T10:00:00Z")
    items = population([old, new], settings(run="1" * 32))
    assert {i.run for i in items} == {"1" * 32}
    assert population([old, new], settings(run="9" * 32)) == []


def test_same_time_newest_is_the_larger_run_id():
    a, b = one("1" * 32), one("2" * 32)
    assert {i.run for i in population([a, b], settings())} == {"2" * 32}


def two_tables() -> Run:
    first = make_table(0, [(1, {"Project": "fuzzy", "Amount": "fuzzy"})])
    second = make_table(1, [(3, {"Amount": "misplaced"})], columns=["Name", "Amount"])
    return make_run("1" * 32, [first, second])


def test_scope_by_table():
    run = two_tables()
    assert where(population([run], settings(table=1))) == [("1", 1, 3, 1, "Amount")]
    assert len(population([run], settings())) == 3
    assert population([run], settings(table=5)) == []


def test_scope_by_column():
    run = two_tables()
    assert where(population([run], settings(column="Amount"))) == [
        ("1", 0, 1, 1, "Amount"),
        ("1", 1, 3, 1, "Amount"),
    ]
    assert where(population([run], settings(column="Name"))) == []
    both = population([run], settings(table=0, column="Amount"))
    assert where(both) == [("1", 0, 1, 1, "Amount")]


def extras_run() -> Run:
    rows = [(1, {"Amount": "fuzzy"}), (2, {})]
    extras = {
        1: {"Year": ("fuzzy", 1), "Agency": ("exact", 1)},
        2: {"Year": ("fuzzy", 1), "Agency": ("misplaced", 2)},  # page 2 carries Year from page 1
        3: {"Year": ("empty", None)},
    }
    return make_run("1" * 32, [make_table(0, rows, extras)])


def test_extra_fields_are_one_item_per_printing_page_and_name():
    items = population([extras_run()], settings())
    extra = [i for i in items if i.extra]
    assert [(i.column, i.page, i.status, i.row) for i in extra] == [
        ("Year", 1, "fuzzy", None),
        ("Agency", 2, "misplaced", None),
    ]
    assert extra[0].key == ExtraKey(SHA, "Year", 1)
    assert extra[0].extracted == "Year@1"
    assert [i.extra for i in items] == [False, True, True]  # extra fields last


def test_extra_fields_out():
    items = population([extras_run()], settings(extra_fields=False))
    assert [i.extra for i in items] == [False]


def test_a_column_scope_leaves_extra_fields_out():
    assert not any(i.extra for i in population([extras_run()], settings(column="Amount")))


def test_extra_field_shared_by_two_tables_is_one_item():
    extras = {1: {"Year": ("fuzzy", 1)}}
    run = make_run(
        "1" * 32,
        [make_table(0, [(1, {})], extras), make_table(1, [(1, {})], extras)],
    )
    items = population([run], settings())
    assert [(i.column, i.table_index) for i in items] == [("Year", 0)]
    scoped = population([run], settings(table=1))
    assert [(i.column, i.table_index) for i in scoped] == [("Year", 1)]


def test_extra_fields_with_exact():
    items = population([extras_run()], settings(statuses=(*FLAGGED, "exact")))
    assert [(i.column, i.status) for i in items if i.extra] == [
        ("Agency", "exact"),
        ("Year", "fuzzy"),
        ("Agency", "misplaced"),
    ]


def test_population_order_across_documents_runs_tables_pages():
    b = one("2" * 32, name="b.pdf", sha=OTHER_SHA)
    a = two_tables()
    items = population([b, a], settings())
    assert [(i.name, i.table_index, i.page) for i in items] == [
        ("a.pdf", 0, 1),
        ("a.pdf", 0, 1),
        ("a.pdf", 1, 3),
        ("b.pdf", 0, 1),
        ("b.pdf", 0, 1),
        ("b.pdf", 0, 2),
        ("b.pdf", 0, 2),
    ]


def test_columns_sort_in_table_order_not_alphabetically():
    rows = [(1, {"Zeta": "fuzzy", "Alpha": "fuzzy"})]
    items = population(
        [make_run("1" * 32, [make_table(0, rows, columns=["Zeta", "Alpha"])])], settings()
    )
    assert [i.column for i in items] == ["Zeta", "Alpha"]


# --- sampling ---------------------------------------------------------------------------------
def test_all_keeps_everything():
    items = numbered(30)
    assert sample(items, settings(mode="all", sample_size=5)) == items


def test_sample_is_reproducible_and_in_population_order():
    items = numbered(200)
    cfg = settings(mode="sample", sample_size=20, seed=7)
    first = sample(items, cfg)
    assert first == sample(items, cfg)
    assert len(first) == 20
    positions = [items.index(i) for i in first]
    assert positions == sorted(positions)
    assert len(set(positions)) == 20


def test_another_seed_another_sample():
    items = numbered(200)
    a = sample(items, settings(mode="sample", sample_size=20, seed=1))
    b = sample(items, settings(mode="sample", sample_size=20, seed=2))
    assert a != b


def test_sample_matches_random_sample_of_positions():
    items = numbered(50)
    picked = sorted(random.Random(5).sample(range(50), 10))
    got = sample(items, settings(mode="sample", sample_size=10, seed=5))
    assert got == [items[i] for i in picked]


def test_sample_is_capped_at_the_population():
    items = numbered(8)
    assert sample(items, settings(mode="sample", sample_size=100)) == items
    assert sample([], settings(mode="sample", sample_size=3)) == []


def test_sampling_does_not_change_the_population():
    items = numbered(20)
    before = list(items)
    sample(items, settings(mode="sample", sample_size=5, seed=1))
    assert items == before
