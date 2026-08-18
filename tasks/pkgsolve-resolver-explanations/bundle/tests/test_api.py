"""api -- the shape of the call, and validation.

Every test here also solves a real instance under its query budget. On their
own these checks would pass on the starting workspace, which already returns a
dict and already raises TypeError in the right places; folding a budgeted solve
into each one keeps the coverage and removes the free credit.
"""

from __future__ import annotations

import pytest

from _support import (
    assert_solution,
    case,
    sample_case,
    sample_solution,
    sealed_registry,
    solve_within,
    unsolvable_within,
    with_ballast,
)
from pkgsolve import (
    DependencyFact,
    Range,
    Requirement,
    RootRequirement,
    Unsolvable,
    Version,
    resolve,
)

BUDGET = 150      # 5.2x the reference's worst (29)


def test_returns_a_plain_dict_of_str_to_version():
    universe, roots = sample_case()
    solution, _ = solve_within(universe, roots, BUDGET)
    assert type(solution) is dict
    assert all(isinstance(name, str) for name in solution)
    assert all(isinstance(version, Version) for version in solution.values())
    assert_solution(solution, sample_solution())


def test_a_non_requirement_element_raises_type_error_before_any_query():
    universe, roots = sample_case()
    registry, counter = sealed_registry(universe, hard_limit=BUDGET * 20)
    with pytest.raises(TypeError):
        resolve(registry, list(roots) + ["app >=1.0.0"])
    assert counter["calls"] == 0, (
        "validation must happen before the registry is touched, %d calls made"
        % (counter["calls"],)
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, sample_solution())


def test_a_non_iterable_requirements_argument_raises_type_error():
    universe, roots = sample_case()
    registry, counter = sealed_registry(universe, hard_limit=BUDGET * 20)
    with pytest.raises(TypeError):
        resolve(registry, 17)
    assert counter["calls"] == 0
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, sample_solution())


def test_no_requirements_returns_an_empty_dict_and_asks_nothing():
    universe, roots = sample_case()
    registry, counter = sealed_registry(universe, hard_limit=BUDGET * 20)
    assert resolve(registry, []) == {}
    assert counter["calls"] == 0
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, sample_solution())


def test_failure_raises_unsolvable_carrying_a_frozenset_of_facts():
    universe, roots = case(
        {
            "alpha": {"1.0.0": ["shared >=2.0.0"]},
            "beta": {"1.0.0": ["shared <2.0.0"]},
            "shared": {"1.0.0": [], "2.0.0": []},
        },
        ["alpha *", "beta *"],
    )
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert isinstance(error, Unsolvable)
    assert isinstance(error.causes, frozenset), (
        "Unsolvable.causes must be a frozenset, got %r" % (type(error.causes).__name__,)
    )
    assert error.causes, "an empty causes set explains nothing"
    for fact in error.causes:
        assert isinstance(fact, (RootRequirement, DependencyFact)), (
            "causes may only hold RootRequirement and DependencyFact, found %r" % (fact,)
        )


def test_the_requirement_list_is_not_mutated():
    universe, roots = sample_case()
    given = list(roots)
    snapshot = [(requirement.package, str(requirement.range)) for requirement in given]
    solve_within(universe, given, BUDGET)
    assert [(r.package, str(r.range)) for r in given] == snapshot
    assert len(given) == len(snapshot), "resolve appended to or trimmed the caller's list"


def test_several_root_requirements_on_one_package_all_apply():
    universe, roots = case(
        {"app": {"1.0.0": [], "2.0.0": [], "3.0.0": [], "4.0.0": []}},
        ["app >=2.0.0", "app <4.0.0"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "3.0.0"}))


def test_the_solution_is_exactly_the_closure():
    # `bystander` is published and reachable through a version of `app` that is
    # not chosen, so it must not appear; `helper` is reachable through the
    # version that is chosen, so it must.
    universe, roots = case(
        {
            "app": {"1.0.0": ["bystander *"], "2.0.0": ["helper *"]},
            "helper": {"1.0.0": []},
            "bystander": {"1.0.0": []},
        },
        ["app >=2.0.0"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "helper": "1.0.0"}))
    assert "bystander" not in solution


def test_resolve_still_works_after_a_failure():
    unsolvable, unsolvable_roots = case(
        {"app": {"1.0.0": ["ghost >=1.0.0"]}}, ["app *"]
    )
    unsolvable_within(unsolvable, unsolvable_roots, BUDGET)
    universe, roots = sample_case()
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, sample_solution())


def test_dependencies_are_only_requested_for_published_releases():
    # The sealed registry raises LookupError for a version it never published.
    # A resolver that invents version numbers, or that keeps asking about a
    # release after learning it is gone, trips it.
    universe, roots = case(
        {
            "app": {"1.0.0": ["core >=1.0.0"], "2.0.0": ["core >=2.0.0"]},
            "core": {"1.0.0": [], "2.0.0": []},
        },
        ["app *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "core": "2.0.0"}))
    assert Range.parse("*").contains(solution["app"])
    assert Requirement("app", Range.parse(">=2.0.0")).range.contains(solution["app"])
