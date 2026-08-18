"""structure -- graph shapes the resolver has to survive.

Cycles, self-dependencies, repeated edges, disconnected components and empty
corners. Section 3.1 says all of these are legal; each test names the wrong
implementation it catches.
"""

from __future__ import annotations

from _oracle import check_explanation
from _support import (
    assert_solution,
    case,
    solve_within,
    unsolvable_within,
    with_ballast,
)

BUDGET = 140      # 5.2x the reference's worst (27)


def test_a_root_on_an_unpublished_package_fails_with_an_explanation():
    universe, roots = case({"app": {"1.0.0": []}}, ["app *", "nowhere *"])
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert not check_explanation(universe, roots, error.causes)


def test_a_self_dependency_that_holds_is_fine():
    # Catches a resolver that treats any self-edge as a cycle error.
    universe, roots = case(
        {"a": {"1.0.0": [], "2.0.0": ["a >=2.0.0"], "3.0.0": ["a >=2.0.0"]}},
        ["a *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"a": "3.0.0"}))


def test_a_self_dependency_that_cannot_hold_rejects_that_release():
    # Catches a resolver that ignores self-edges instead of checking them.
    universe, roots = case(
        {"a": {"1.0.0": [], "2.0.0": ["a <=1.0.0"]}},
        ["a *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"a": "1.0.0"}))


def test_two_edges_to_the_same_package_in_one_release_intersect():
    # Catches a resolver that keeps only the last requirement it saw.
    universe, roots = case(
        {
            "app": {"1.0.0": ["lib >=2.0.0", "lib <=3.0.0"]},
            "lib": {"%d.0.0" % major: [] for major in range(1, 6)},
        },
        ["app *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "1.0.0", "lib": "3.0.0"}))


def test_disconnected_roots_are_solved_together():
    universe, roots = case(
        {
            "one": {"1.0.0": ["one-dep *"], "2.0.0": ["one-dep >=9.0.0"]},
            "one-dep": {"1.0.0": []},
            "two": {"1.0.0": [], "2.0.0": []},
        },
        ["one *", "two *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(
        solution, with_ballast({"one": "1.0.0", "one-dep": "1.0.0", "two": "2.0.0"})
    )


def test_a_release_with_no_dependencies_is_a_leaf():
    universe, roots = case({"solo": {"1.0.0": [], "2.0.0": []}}, ["solo *"])
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"solo": "2.0.0"}))


def test_an_exact_pin_is_honoured_over_the_newest_release():
    universe, roots = case(
        {
            "app": {"%d.0.0" % major: [] for major in range(1, 6)},
            "wrapper": {"1.0.0": ["app ==2.0.0"]},
        },
        ["wrapper *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "wrapper": "1.0.0"}))


def test_a_cycle_with_no_consistent_assignment_fails_with_an_explanation():
    universe, roots = case(
        {
            "north": {"1.0.0": ["south >=2.0.0"], "2.0.0": ["south >=3.0.0"]},
            "south": {"1.0.0": ["north *"], "2.0.0": ["north >=3.0.0"]},
        },
        ["north *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert not check_explanation(universe, roots, error.causes)


def test_a_not_equal_comparator_carves_a_hole():
    universe, roots = case(
        {
            "app": {"1.0.0": ["lib !=3.0.0,<=3.0.0"]},
            "lib": {"%d.0.0" % major: [] for major in range(1, 5)},
        },
        ["app *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "1.0.0", "lib": "2.0.0"}))


def test_a_package_reached_only_through_a_rejected_release_stays_out():
    universe, roots = case(
        {
            "app": {
                "1.0.0": ["only-here *"],
                "2.0.0": ["shared-dep *"],
                "3.0.0": ["shared-dep >=9.0.0"],
            },
            "only-here": {"1.0.0": []},
            "shared-dep": {"1.0.0": [], "2.0.0": []},
        },
        ["app *"],
    )
    # app 3.0.0 is impossible; app 2.0.0 wins on version and `only-here` never
    # enters the closure, even though it sorts before `shared-dep`.
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "shared-dep": "2.0.0"}))
    assert "only-here" not in solution
