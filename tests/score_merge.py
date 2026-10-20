"""
Score the merge rules on the golden fixture (spec 007, task 003).

    python -m tests.score_merge            # the sweep
    python -m tests.score_merge --detail   # also list every disagreement of the defaults

For every relation with ``stage == "merge"`` it asks `mergeable_pairs` (the pair checks plus
mutual uniqueness over all parts of the document) whether the two parts join, and compares with
the truth. Order of merit (spec, "How rules are chosen"): harmful merges outside
``residual_risk``, then broken required results, then missed merges. No model is involved.
"""

import argparse
from collections import Counter
from dataclasses import dataclass, field, replace

from quotable.steps.merge import DEFAULT_RULES, Rules, mergeable_pairs
from tests.fixture_tables import discovered, doc_ids, load_doc

_CACHE: dict[str, tuple[list, dict[str, int]]] = {}


def _tables(doc_id: str) -> tuple[list, dict[str, int]]:
    if doc_id not in _CACHE:
        _CACHE[doc_id] = discovered(doc_id)
    return _CACHE[doc_id]


@dataclass
class Score:
    """The outcome of one rule set over every merge-stage relation."""

    rules: Rules
    harmful: list[str] = field(default_factory=list)  # outside residual_risk
    harmful_residual: list[str] = field(default_factory=list)
    required_broken: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    missed_by_probe: Counter = field(default_factory=Counter)
    merged_null: Counter = field(default_factory=Counter)  # expect_merge None, by probe
    total_null: Counter = field(default_factory=Counter)

    @property
    def key(self) -> tuple[int, int, int]:
        """Sort key: harmful, broken required, missed (smaller is better)."""
        return len(self.harmful), len(self.required_broken), len(self.missed)


def score(rules: Rules) -> Score:
    """Run ``rules`` over the whole fixture."""
    out = Score(rules)
    for doc_id in doc_ids():
        truth = load_doc(doc_id)
        rels = [r for r in truth["relations"] if r["stage"] == "merge"]
        if not rels:
            continue
        tables, member = _tables(doc_id)
        joined = {frozenset(pair) for pair in mergeable_pairs(tables, rules)}
        for rel in rels:
            merged = frozenset((member[rel["a"]], member[rel["b"]])) in joined
            tag = f"{doc_id}:{rel['a']}{rel['b']}"
            probes = rel["probes"]
            if merged and rel["same_table"] is False:
                (out.harmful_residual if "residual_risk" in probes else out.harmful).append(tag)
            if rel["expect_merge"] is not None and merged != rel["expect_merge"]:
                out.required_broken.append(tag)
            if not merged and rel["same_table"] is True:
                out.missed.append(tag)
                out.missed_by_probe.update(probes)
            if rel["expect_merge"] is None:
                out.total_null.update(probes)
                if merged:
                    out.merged_null.update(probes)
    return out


def variants() -> list[Rules]:
    """Return the rule sets to compare: one setting at a time, then the interacting ones."""
    base = DEFAULT_RULES
    found = [base]
    found += [replace(base, equal_share=s) for s in (0.0, 1 / 3, 0.5, 2 / 3, 1.0)]
    found += [replace(base, grid_tolerance=t) for t in (5.0, 8.0, 10.0, 12.0, 15.0, 20.0)]
    found += [replace(base, min_cells=n) for n in (3, 4, 5, 6, 8)]
    found += [replace(base, shape_share=s) for s in (0.7, 0.75, 0.8, 0.9)]
    found += [replace(base, word_text_apart=True)]
    found += [
        replace(base, equal_share=s, grid_tolerance=t)
        for s in (0.0, 0.5)
        for t in (5.0, 10.0, 15.0)
    ]
    seen: list[Rules] = []
    for rules in found:
        if rules not in seen:
            seen.append(rules)
    return seen


def describe(rules: Rules) -> str:
    """Return a one-line description of a rule set."""
    return (
        f"equal_share={rules.equal_share:.2f} tol={rules.grid_tolerance:g} "
        f"min_cells={rules.min_cells} shape={rules.shape_share:g} "
        f"words_apart={rules.word_text_apart}"
    )


def main() -> None:
    """Print the sweep, best variant first."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()
    scores = sorted((score(r) for r in variants()), key=lambda s: s.key)
    print(f"{'harmful':>7} {'(resid)':>7} {'broken':>6} {'missed':>6}  rules")
    for s in scores:
        print(
            f"{len(s.harmful):>7} {len(s.harmful_residual):>7} {len(s.required_broken):>6} "
            f"{len(s.missed):>6}  {describe(s.rules)}"
        )
    default = score(DEFAULT_RULES)
    print(f"\nDefaults ({describe(DEFAULT_RULES)}):")
    for label, items in (
        ("harmful outside residual_risk", default.harmful),
        ("harmful, residual_risk", default.harmful_residual),
        ("required results broken", default.required_broken),
    ):
        print(f"  {label}: {len(items)}")
        if args.detail:
            for item in items:
                print(f"    {item}")
    print("  missed merges by probe:", dict(default.missed_by_probe))
    print("  expect_merge=null: merged / total by probe:")
    for probe in sorted(default.total_null):
        print(f"    {probe:<16}{default.merged_null[probe]:>4} / {default.total_null[probe]}")
    if args.detail:
        print("  missed:", *default.missed, sep="\n    ")


if __name__ == "__main__":
    main()
