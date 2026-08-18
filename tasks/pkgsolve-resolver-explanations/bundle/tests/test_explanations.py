"""explanations -- section 4, conditions (E1) to (E5).

The grader never compares `causes` against a fixed answer. It checks that every
cited fact is true of the registry, that the facts together rule out every
solution, and that none of them is redundant. Any set that clears those bars is
accepted, so there is nothing to overfit and nothing to hard-code.
"""

from __future__ import annotations

from _oracle import check_explanation
from _support import (
    case,
    conflict_case,
    is_ballast,
    mutual_exclusion_spec,
    unsolvable_within,
)
from pkgsolve import DependencyFact, RootRequirement

BUDGET = 60        # 6.7x the reference's worst on these (9)
WIDE_BUDGET = 640  # 5.2x the reference on the sixty-release axis (124)


def assert_explained(universe, roots, error):
    problems = check_explanation(universe, roots, error.causes)
    assert not problems, "the explanation is not acceptable:\n  " + "\n  ".join(problems)


def cited_packages(causes):
    names = set()
    for fact in causes:
        if isinstance(fact, RootRequirement):
            names.add(fact.requirement.package)
        elif isinstance(fact, DependencyFact):
            names.add(fact.package)
            names.add(fact.requirement.package)
    return names


def test_mutual_exclusion_is_explained():
    # Worked example 3 in the specification.
    universe, roots = conflict_case()
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_a_root_on_a_package_that_does_not_exist_is_explained():
    universe, roots = case({"app": {"1.0.0": []}}, ["app *", "ghost >=1.0.0"])
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_a_dependency_on_a_package_that_does_not_exist_is_explained():
    universe, roots = case(
        {"app": {"1.0.0": ["ghost *"], "2.0.0": ["ghost >=1.0.0"]}}, ["app *"]
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_the_cited_version_range_must_not_be_wider_than_the_truth():
    # `a 1.0.0` is happy with any `b`; only `a >=2.0.0` needs one that does not
    # exist. Citing `every a * requires b >=5.0.0` is untrue and is rejected by
    # (E3); citing only `a >=2.0.0` is true, sufficient and minimal.
    universe, roots = case(
        {
            "a": {"1.0.0": ["b >=1.0.0"], "2.0.0": ["b >=5.0.0"], "3.0.0": ["b >=5.0.0"]},
            "b": {"%d.0.0" % major: [] for major in range(1, 5)},
        },
        ["a >=2.0.0"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_contradictory_root_requirements_are_explained():
    universe, roots = case(
        {"app": {"%d.0.0" % major: [] for major in range(1, 4)}},
        ["app >=3.0.0", "app <2.0.0"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_a_three_level_conflict_is_explained():
    universe, roots = case(
        {
            "app": {"1.0.0": ["mid *"], "2.0.0": ["mid *"]},
            "mid": {"1.0.0": ["leaf >=3.0.0"], "2.0.0": ["leaf >=4.0.0"]},
            "leaf": {"1.0.0": [], "2.0.0": []},
        },
        ["app *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_an_unsatisfiable_cycle_is_explained():
    universe, roots = case(
        {
            "ping": {"1.0.0": ["pong >=2.0.0"]},
            "pong": {"1.0.0": ["ping >=2.0.0"]},
        },
        ["ping *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)


def test_facts_the_search_merely_walked_past_are_not_cited():
    # `mid` is perfectly satisfiable and gets visited on the way to the real
    # problem. Citing it is true and sufficient, but not minimal, so (E5) fails.
    universe, roots = case(
        {
            "app": {"1.0.0": ["mid *", "bad *"], "2.0.0": ["bad *"]},
            "mid": {"1.0.0": [], "2.0.0": []},
            "bad": {"1.0.0": ["ghost *"], "2.0.0": ["ghost *"]},
        },
        ["app *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)
    assert "mid" not in cited_packages(error.causes), (
        "`mid` has nothing to do with the failure: %s"
        % (sorted(str(fact) for fact in error.causes),)
    )


def test_only_one_of_two_independent_conflicts_is_cited():
    # Either half on its own makes the manifest unsolvable, so citing both
    # cannot be minimal.
    universe, roots = case(
        {
            "first": {"1.0.0": ["ghost-one *"]},
            "second": {"1.0.0": ["ghost-two *"]},
        },
        ["first *", "second *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)
    names = cited_packages(error.causes)
    assert ("first" in names) != ("second" in names), (
        "exactly one of the two independent conflicts may be cited, got %s" % (names,)
    )


def test_the_satisfiable_part_of_the_manifest_is_not_cited():
    universe, roots = conflict_case()
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert_explained(universe, roots, error)
    ballast = sorted(name for name in cited_packages(error.causes) if is_ballast(name))
    assert not ballast, "the ballast component resolves fine; citing %s is wrong" % (ballast,)


def test_an_explanation_covers_a_long_version_axis():
    # Sixty releases of each side. The cited range has to cover every one of
    # them or (E4) fails, and a per-release citation of all 120 would still be
    # accepted -- what is not accepted is citing a range the registry does not
    # support across its whole width.
    universe, roots = case(mutual_exclusion_spec(60), ["alpha *", "beta *"])
    error, _ = unsolvable_within(universe, roots, WIDE_BUDGET)
    assert_explained(universe, roots, error)


def test_causes_is_an_immutable_set_of_facts():
    universe, roots = conflict_case()
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert isinstance(error.causes, frozenset)
    assert error.causes == frozenset(error.causes)
    # Facts must be hashable and compare by value, or a set of them is useless.
    for fact in error.causes:
        assert hash(fact) == hash(fact)
    assert_explained(universe, roots, error)
