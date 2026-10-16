"""
The case matrix of the golden synthetic fixture (see ``tests/synthetic.py``).

``all_docs()`` returns every document; ``python -m tests.synthetic_cases [--out DIR]`` writes
them (``<id>.pdf``, ``<id>.json`` and ``manifest.json``). ``just synthetic`` does the same into
``tests/data/synthetic``.
"""

import argparse
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from tests.synthetic import Col, Doc, Gap, Part, Relation, Stack, render, validate

DEFAULT_OUT = Path(__file__).parent / "data" / "synthetic"


def C(  # noqa: N802, PLR0913, PLR0917
    name: str,
    kind: str,
    sup: str | None = None,
    sub: str | None = None,
    reorder: str | None = None,
    disj: str | None = None,
    fill: float = 1.0,
) -> Col:
    """Build a column (short name: the schemas below are tables of these)."""
    return Col(name, kind, sup, sub, reorder, disj, fill)


SCHEMAS: dict[str, tuple[Col, ...]] = {
    "projects6": (
        C("Project", "text", "Project Name", disj="Initiative"),
        C("County", "word", "County Name", disj="Region"),
        C(
            "Requested Amount",
            "currency",
            "Requested Amount Total",
            None,
            "Amount Requested",
            "Funds Sought",
        ),
        C(
            "Requested Local Match",
            "currency",
            "Requested Local Match Share",
            "Local Match",
            "Local Match Requested",
            "Cost Share",
        ),
        C(
            "Recommended Amount",
            "currency",
            "Recommended Amount Total",
            None,
            "Amount Recommended",
            "Staff Award",
        ),
        C(
            "Community Benefit Rating",
            "word",
            "Community Benefit Rating Score",
            "Benefit Rating",
            "Rating Community Benefit",
            "Merit",
        ),
    ),
    "awards4": (
        C("Applicant", "text", "Applicant Name", disj="Organization"),
        C("Program", "word", "Program Area", disj="Category"),
        C(
            "Amount Awarded",
            "currency",
            "Amount Awarded Total",
            "Awarded",
            "Awarded Amount",
            "Grant",
        ),
        C("Year", "integer", "Fiscal Year", disj="Period"),
    ),
    "tiny3": (
        C("Name", "word", "Full Name", disj="Label"),
        C("Count", "integer", "Count Total", disj="Number"),
        C("Share", "percent", "Share Percent", disj="Portion"),
    ),
    "census8": (
        C("Town", "word", "Town Name", disj="Place"),
        C("County", "word", "County Name", disj="Region"),
        C("Population", "integer", "Population Total", disj="Residents"),
        C("Households", "integer", "Households Total", disj="Homes"),
        C("Median Age", "decimal", "Median Age Years", "Age", disj="Typical Years"),
        C("Poverty Rate", "percent", "Poverty Rate Percent", "Poverty", disj="Need"),
        C("Last Survey", "date", "Last Survey Date", "Survey", disj="Counted"),
        C("Notes", "note", "Notes Remarks", fill=0.5, disj="Comments"),
    ),
    "wide10": (
        C("Code", "integer", "Code Number"),
        C("Site", "word", "Site Name"),
        C("Region", "word", "Region Name"),
        C("Opened", "date", "Opened Date"),
        C("Units", "integer", "Units Total"),
        C("Cost", "currency", "Cost Total"),
        C("Grant", "currency", "Grant Total"),
        C("Share", "percent", "Share Percent"),
        C("Score", "decimal", "Score Value"),
        C("Grade", "word", "Grade Letter"),
    ),
    "town4": (
        C("Town", "word", "Town Name"),
        C("County", "word", "County Name"),
        C("Population", "integer", "Population 2020"),
        C("Households", "integer", "Households 2020"),
    ),
    "ambig4": (
        C("Applicant", "text"),
        C("Amount", "currency"),
        C("Amount Awarded", "currency"),
        C("Year", "integer"),
    ),
}
FONT = {"census8": 7.5, "wide10": 6.5}


def part(pid: str, schema: str, names: list[str] | None = None, **kw) -> Part:  # noqa: ANN003
    """Build a part of a schema, with its header as given (default: the schema's names)."""
    cols = SCHEMAS[schema]
    kw.setdefault("font", FONT.get(schema, 8.0))
    return Part(pid, cols, tuple(names or [c.name for c in cols]), **kw)


def reword(schema: str, positions: list[int], how: str = "mixed") -> list[str]:
    """Return the schema's names with the given positions reworded."""
    cols = SCHEMAS[schema]
    names = [c.name for c in cols]
    for j, p in enumerate(sorted(positions)):
        c = cols[p]
        if how == "sup" or (how == "mixed" and (j % 2 == 0 or not c.sub)):
            names[p] = c.sup or c.name
        elif how in {"mixed", "sub"}:
            names[p] = c.sub or c.sup or c.name
        elif how == "reorder":
            names[p] = c.reorder or c.name
        elif how == "disj":
            names[p] = c.disj or c.name
    return names


def pair(  # noqa: PLR0913
    id_: str,
    desc: str,
    tags: list[str],
    a: Part,
    b: Part,
    *,
    gap: int = 2,
    gap_kind: str = "prose",
    same: bool | None = True,
    expect: bool | None = None,
    probes: list[str] | None = None,
    stage: str = "merge",
    note: str = "",
    isolate: bool = True,
) -> Doc:
    """Build a document: part A, a gap, part B, and the relation between A and B."""
    items: list[Part | Gap | Stack] = [a, *([Gap(gap, gap_kind)] if gap else []), b]
    rel = Relation(a.id, b.id, same, expect, probes or [], stage, note, isolate)
    return Doc(id_, desc, tags, items, [rel])


# --- families ---------------------------------------------------------------------------------
def half_sweep() -> Iterator[Doc]:
    """k of n headers reworded: only the half-equal rule can decide these."""
    for schema, cols in SCHEMAS.items():
        n = len(cols)
        if schema in ("town4", "ambig4"):
            continue
        for k in range(1, n + 1):
            for sel in ("first", "last"):
                if k == n and sel == "last":
                    continue
                pos = list(range(k)) if sel == "first" else list(range(n - k, n))
                yield pair(
                    f"half-{schema}-{sel}{k}",
                    f"{schema}: {k} of {n} headers reworded ({sel} {k})",
                    ["family:half_sweep", f"schema:{schema}"],
                    part("A", schema),
                    part("B", schema, reword(schema, pos)),
                    probes=["half_equal"],
                    note=f"{n - k} of {n} positions have equal words",
                )


def word_order() -> Iterator[Doc]:
    """Same words in another order: equal token sets, different signature."""
    for schema in ("projects6", "awards4"):
        cols = SCHEMAS[schema]
        pos = [i for i, c in enumerate(cols) if c.reorder]
        yield pair(
            f"order-{schema}-all",
            f"{schema}: every reorderable header has its words in another order",
            ["family:word_order", f"schema:{schema}"],
            part("A", schema),
            part("B", schema, reword(schema, pos, "reorder")),
            expect=True,
            probes=["token_containment"],
        )
    names = reword("projects6", [2, 3], "reorder")
    names[0] = SCHEMAS["projects6"][0].sup or names[0]
    yield pair(
        "order-projects6-plus-reword",
        "projects6: two headers reordered and one reworded (5 of 6 positions equal words)",
        ["family:word_order", "schema:projects6"],
        part("A", "projects6"),
        part("B", "projects6", names),
        expect=True,
        probes=["token_containment"],
    )


def _grid_expect(shift: float) -> bool | None:
    if abs(shift) <= 8:  # noqa: PLR2004
        return True
    if abs(shift) <= 12:  # noqa: PLR2004
        return None
    return False


def grid() -> Iterator[Doc]:
    """Part B moved right or left, or one column drifting; tolerance is 10 pt."""
    names = reword("projects6", [0, 1], "sup")
    for s in (0, 2, 4, 6, 8, 9, 10, 11, 12, 14, 16, 20, 24, 30, 40, -6, -16):
        band = 9 <= abs(s) <= 12  # noqa: PLR2004
        yield pair(
            f"grid-shift{s:+d}".replace("+", "p").replace("-", "m"),
            f"projects6: part B moved {s:+d} pt",
            ["family:grid", "schema:projects6"],
            part("A", "projects6"),
            part("B", "projects6", names, shift=float(s)),
            expect=_grid_expect(s),
            probes=["grid", *(["tolerance_band"] if band else [])],
        )
    for s in (6, 8, 14, 24):
        yield pair(
            f"grid-drift{s}",
            f"projects6: only the third column of part B is {s} pt to the right",
            ["family:grid", "schema:projects6"],
            part("A", "projects6"),
            part("B", "projects6", names, drift={2: float(s)}),
            expect=_grid_expect(s),
            probes=["grid"],
        )


def alignment() -> Iterator[Doc]:
    """Right- vs left-aligned numbers, and a larger font: the centres move, the edges may not."""
    names = reword("projects6", [0, 1], "sup")
    numeric = {i: "r" for i, c in enumerate(SCHEMAS["projects6"]) if c.kind == "currency"}
    cases = [
        ("rr", numeric, numeric, True),
        ("lr", {}, numeric, None),
        ("rl", numeric, {}, None),
    ]
    for tag, a_align, b_align, expect in cases:
        yield pair(
            f"align-{tag}",
            f"projects6: numbers aligned {tag[0]} in part A and {tag[1]} in part B",
            ["family:alignment", "schema:projects6"],
            part("A", "projects6", align=a_align),
            part("B", "projects6", names, align=b_align),
            expect=expect,
            probes=["grid", "alignment"],
        )
    for size in (9.0, 10.0):
        yield pair(
            f"align-font{size}".replace(".", "_"),
            f"projects6: part B printed at {size} pt instead of 8 pt",
            ["family:alignment", "schema:projects6"],
            part("A", "projects6"),
            part("B", "projects6", names, font=size),
            expect=None,
            probes=["grid", "alignment"],
        )


def min_cells() -> Iterator[Doc]:
    """Too few values to judge a column: unknown, so no merge."""
    names = reword("projects6", [0, 1], "sup")
    for ra, rb in [
        (10, 10),
        (20, 4),
        (4, 20),
        (4, 4),
        (5, 5),
        (5, 20),
        (20, 5),
        (6, 6),
        (3, 3),
        (2, 2),
        (12, 3),
    ]:
        yield pair(
            f"cells-{ra}x{rb}",
            f"projects6: part A has {ra} rows, part B has {rb}",
            ["family:min_cells", "schema:projects6"],
            part("A", "projects6", pages=1, rows_per_page=ra),
            part("B", "projects6", names, pages=1, rows_per_page=rb),
            expect=min(ra, rb) >= 5,  # noqa: PLR2004
            probes=["min_cells"],
        )
    census = reword("census8", [0, 1], "sup")
    for na, nb in [(10, 10), (6, 6), (5, 5), (4, 4), (3, 3), (10, 4), (4, 10), (0, 0)]:
        yield pair(
            f"cells-notes-{na}x{nb}",
            f"census8: the sparse Notes column has {na} values in part A and {nb} in part B",
            ["family:min_cells", "schema:census8"],
            part("A", "census8", nonempty={7: na}),
            part("B", "census8", census, nonempty={7: nb}),
            expect=min(na, nb) >= 5,  # noqa: PLR2004
            probes=["min_cells"],
        )


def shape() -> Iterator[Doc]:
    """The kind of value in a column: dominant share, and a change of kind between parts."""
    names = reword("projects6", [0, 1], "sup")

    def mixed(share: float) -> dict[int, tuple[str, float]]:
        return {2: ("word", share)}

    for share in (1.0, 0.9, 0.85, 0.8, 0.75, 0.6, 0.5):
        yield pair(
            f"shape-share{round(share * 100)}",
            f"projects6: {round(share * 100)}% of the third column are amounts, the rest words",
            ["family:shape", "schema:projects6"],
            part("A", "projects6", mix=mixed(share)),
            part("B", "projects6", names, mix=mixed(share)),
            expect=share >= 0.8,  # noqa: PLR2004
            probes=["shape"],
        )
    for sa, sb in [(1.0, 0.85), (1.0, 0.7), (0.7, 1.0), (0.9, 0.6)]:
        yield pair(
            f"shape-asym{round(sa * 100)}-{round(sb * 100)}",
            f"projects6: amounts are {round(sa * 100)}% of a column in A, {round(sb * 100)}% in B",
            ["family:shape", "schema:projects6"],
            part("A", "projects6", mix=mixed(sa)),
            part("B", "projects6", names, mix=mixed(sb)),
            expect=min(sa, sb) >= 0.8,  # noqa: PLR2004
            probes=["shape"],
        )
    for kind in ("integer", "percent", "word", "date", "decimal", "text"):
        yield pair(
            f"shape-kind-{kind}",
            f"projects6: the third column holds {kind} values in part B instead of amounts",
            ["family:shape", "schema:projects6"],
            part("A", "projects6"),
            part("B", "projects6", names, kinds={2: kind}),
            same=None,
            expect=False,
            probes=["shape"],
        )


def structure() -> Iterator[Doc]:  # noqa: PLR0915
    """Vetoes and ambiguities that have nothing to do with the thresholds."""
    p6 = SCHEMAS["projects6"]
    names = reword("projects6", [0, 1], "sup")
    tags = ["family:structure", "schema:projects6"]

    a, b = (
        part("A", "projects6", pages=2, rows_per_page=8),
        part("B", "projects6", names, pages=2, rows_per_page=8),
    )
    yield Doc(
        "struct-shared-page",
        "two tables printed one above the other on the same pages, one with reworded headers",
        tags,
        [Stack(a, b)],
        [Relation("A", "B", False, False, ["shared_page"], note="two tables on one page")],
    )

    extra = Col("Notes", "text", fill=0.6)
    b = replace(part("B", "projects6", [*names, "Notes"]), cols=(*p6, extra))
    yield pair(
        "struct-extra-column",
        "part B has a seventh column (Notes)",
        tags,
        part("A", "projects6"),
        b,
        expect=False,
        probes=["count"],
        isolate=False,
    )

    b = replace(part("B", "projects6", names[:-1]), cols=p6[:-1])
    yield pair(
        "struct-dropped-column",
        "part B lacks the last column",
        tags,
        part("A", "projects6"),
        b,
        expect=False,
        probes=["count"],
        isolate=False,
    )

    swapped = list(names)
    swapped[2], swapped[3] = swapped[3], swapped[2]
    cols = list(p6)
    cols[2], cols[3] = cols[3], cols[2]
    b = replace(part("B", "projects6", swapped), cols=tuple(cols))
    yield pair(
        "struct-swapped-columns",
        "part B has its third and fourth columns swapped",
        tags,
        part("A", "projects6"),
        b,
        same=None,
        expect=False,
        probes=["order"],
        isolate=False,
    )

    abbr = list(names)
    abbr[2] = "Requested Amt"
    yield pair(
        "struct-abbreviation",
        "'Requested Amt' for 'Requested Amount'",
        tags,
        part("A", "projects6"),
        part("B", "projects6", abbr),
        expect=False,
        probes=["token_containment", "known_limit"],
        isolate=False,
    )

    disj = list(names)
    disj[2] = p6[2].disj or disj[2]
    yield pair(
        "struct-unrelated-wording",
        "'Funds Sought' for 'Requested Amount'",
        tags,
        part("A", "projects6"),
        part("B", "projects6", disj),
        expect=False,
        probes=["token_containment", "known_limit"],
        isolate=False,
    )

    a = part("A", "ambig4")
    b = part("B", "ambig4", ["Applicant", "Amount Requested", "Amount Awarded", "Year"])
    yield pair(
        "struct-ambiguous-amount",
        "bare 'Amount' next to 'Amount Awarded' in part A",
        ["family:structure", "schema:ambig4"],
        a,
        b,
        same=None,
        expect=False,
        probes=["ambiguity"],
        isolate=False,
    )

    v1, v2 = names, reword("projects6", [2, 3], "sup")
    items: list[Part | Gap | Stack] = [
        part("A", "projects6"),
        Gap(2),
        part("B", "projects6", v1),
        Gap(2),
        part("C", "projects6", v1),
    ]
    yield Doc(
        "struct-three-parts-one-wording",
        "part A, then parts B and C that print the same reworded header",
        tags,
        items,
        [
            Relation("A", "B", True, True, ["unique"], note="B and C are one table already"),
            Relation("A", "C", True, True, ["unique"], note="B and C are one table already"),
            Relation("B", "C", True, True, ["unique"], "discovery"),
        ],
    )
    items = [
        part("A", "projects6"),
        Gap(2),
        part("B", "projects6", v1),
        Gap(2),
        part("C", "projects6", v2),
    ]
    yield Doc(
        "struct-three-parts-two-wordings",
        "part A, then parts B and C that reword different headers: A has two partners",
        tags,
        items,
        [
            Relation("A", "B", True, False, ["unique"]),
            Relation("A", "C", True, False, ["unique"]),
            Relation("B", "C", True, False, ["unique"]),
        ],
    )

    other = part("X", "awards4", pages=1)
    items = [part("A", "projects6"), Gap(1), other, Gap(1), part("B", "projects6", names)]
    yield Doc(
        "struct-interleaved",
        "table A, a different table X, then table A again with two headers reworded",
        tags,
        items,
        [
            Relation("A", "B", True, True, ["unique"], note="X is not a candidate for either"),
            Relation("A", "X", False, False, ["count"], isolate=False),
            Relation("X", "B", False, False, ["count"], isolate=False),
        ],
    )

    a = part("A", "awards4")
    b = part("B", "awards4", ["Applicant", "Program", "Amount Declined", "Year"])
    yield pair(
        "struct-two-tables-one-template",
        "'Amount Awarded' in one section, 'Amount Declined' in another",
        ["family:structure", "schema:awards4"],
        a,
        b,
        same=False,
        expect=False,
        probes=["token_containment"],
        isolate=False,
    )


def residual_risk() -> Iterator[Doc]:
    """Different tables whose headers contain each other: what the rules cannot tell apart."""
    tags = ["family:residual_risk", "schema:town4"]
    a = part("A", "town4")
    for tag, names, kw, expect in [
        ("both", ["Town", "County", "Population 2020", "Households 2020"], {}, None),
        ("one", ["Town", "County", "Population 2020", "Households"], {}, None),
        (
            "shifted",
            ["Town", "County", "Population 2020", "Households 2020"],
            {"shift": 25.0},
            False,
        ),
    ]:
        yield pair(
            f"risk-town4-{tag}",
            f"town4: current figures vs a table of 2020 figures ({tag})",
            tags,
            a,
            part("B", "town4", names, **kw),
            same=False,
            expect=expect,
            probes=["residual_risk"],
        )
    tiny = ["family:residual_risk", "schema:tiny3"]
    for tag, names in [
        ("count", ["Name", "Count Total", "Share"]),
        ("share", ["Name", "Count", "Share Percent"]),
    ]:
        yield pair(
            f"risk-tiny3-{tag}",
            f"tiny3: a short table and a longer-named table of different things ({tag})",
            tiny,
            part("A", "tiny3"),
            part("B", "tiny3", names),
            same=False,
            expect=None,
            probes=["residual_risk", "half_equal"],
        )


def pipeline() -> Iterator[Doc]:
    """Whole-pipeline cases for the live test: gaps of different lengths, no header, etc."""
    names = reword("projects6", [0, 1], "sup")
    tags = ["family:pipeline", "schema:projects6"]
    for gap in (0, 1, 4, 9, 20):
        yield pair(
            f"pipe-exact-gap{gap}",
            f"same header, {gap} table-free pages in between",
            tags,
            part("A", "projects6"),
            part("B", "projects6"),
            gap=gap,
            stage="discovery",
            expect=True,
            probes=["pipeline"],
        )
        yield pair(
            f"pipe-reworded-gap{gap}",
            f"two headers reworded, {gap} table-free pages in between",
            tags,
            part("A", "projects6"),
            part("B", "projects6", names),
            gap=gap,
            expect=True,
            probes=["pipeline"],
        )
    yield pair(
        "pipe-reworded-headerless",
        "reworded header on the first page of B only",
        tags,
        part("A", "projects6"),
        part("B", "projects6", names, pages=3, header="first"),
        gap=5,
        expect=True,
        probes=["pipeline"],
    )
    yield pair(
        "pipe-reworded-lookalike",
        "reworded header after pages of bullet lists",
        tags,
        part("A", "projects6"),
        part("B", "projects6", names),
        gap=3,
        gap_kind="lookalike",
        expect=True,
        probes=["pipeline"],
    )
    yield pair(
        "pipe-caps",
        "same words in capitals after the gap",
        tags,
        part("A", "projects6"),
        part("B", "projects6", [c.name.upper() for c in SCHEMAS["projects6"]]),
        gap=3,
        stage="discovery",
        expect=True,
        probes=["pipeline"],
        note="case only: the signatures match",
    )
    yield pair(
        "pipe-long-parts",
        "four pages in each part, reworded header",
        tags,
        part("A", "projects6", pages=4, rows_per_page=12),
        part("B", "projects6", names, pages=4, rows_per_page=12),
        gap=6,
        expect=True,
        probes=["pipeline"],
    )


def controls() -> Iterator[Doc]:
    """A single table, and two unrelated tables."""
    yield Doc(
        "ctrl-single-table",
        "one table over three pages",
        ["family:controls"],
        [part("A", "projects6", pages=3)],
    )
    yield pair(
        "ctrl-unrelated",
        "a six-column and a four-column table with different headers",
        ["family:controls"],
        part("A", "projects6"),
        part("B", "awards4"),
        same=False,
        expect=False,
        probes=["count"],
        isolate=False,
    )


def all_docs() -> list[Doc]:
    """Return every document of the fixture."""
    families = (
        half_sweep,
        word_order,
        grid,
        alignment,
        min_cells,
        shape,
        structure,
        residual_risk,
        pipeline,
        controls,
    )
    docs = [d for family in families for d in family()]
    ids = [d.id for d in docs]
    if len(ids) != len(set(ids)):
        msg = "duplicate document ids"
        raise ValueError(msg)
    return docs


def write_all(out: Path) -> list[dict]:
    """Write every document (PDF and truth) into ``out``; return the manifest entries."""
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for doc in all_docs():
        case = render(doc, out / f"{doc.id}.pdf")
        (out / f"{doc.id}.json").write_text(json.dumps(case, indent=1) + "\n")
        manifest.append(
            {
                "id": doc.id,
                "description": doc.description,
                "tags": doc.tags,
                "pages": case["pages"],
                "relations": [
                    {k: r[k] for k in ("a", "b", "same_table", "expect_merge", "probes", "stage")}
                    for r in case["relations"]
                ],
            }
        )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def main() -> None:
    """Write the fixture, then check it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-check", action="store_true", help="skip grounding the truth rows")
    args = parser.parse_args()
    manifest = write_all(args.out)
    print(f"wrote {len(manifest)} documents to {args.out}")
    if args.no_check:
        return
    bad = 0
    for entry in manifest:
        case = json.loads((args.out / f"{entry['id']}.json").read_text())
        for problem in validate(case, args.out / f"{entry['id']}.pdf"):
            bad += 1
            print(f"PROBLEM {entry['id']}: {problem}")
    print("all truth rows ground exactly" if not bad else f"{bad} problem(s)")


if __name__ == "__main__":
    main()
