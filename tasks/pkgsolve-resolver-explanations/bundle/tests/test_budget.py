"""budget -- section 5, the registry call count.

Nothing here is timed. The metric is an integer the grader owns: how many times
the resolver asked the registry a question. Every budget below is at least five
times what the reference implementation spends on the same instance, so a
correct resolver with a different search order has a wide margin, while an
implementation that materialises the reachable universe before deciding
anything misses by an order of magnitude or more.

The shapes are chosen so that caching alone is not enough. Each one buries the
decisive constraint behind a package whose alternatives drag in large,
completely irrelevant subtrees: paying for those subtrees once per candidate is
what the budget forbids.
"""

from __future__ import annotations

from _oracle import check_explanation
from _support import (
    assert_solution,
    case,
    chain_spec,
    fat_subtree_spec,
    mutual_exclusion_spec,
    solve_within,
    unsolvable_within,
    with_ballast,
)


def test_a_hopeless_root_is_not_re_examined_for_every_other_choice():
    # `aa` has sixty releases, each with a private subtree that costs several
    # queries to walk. `mm` cannot be satisfied at all. Once that is known it is
    # known regardless of `aa`, so at most one of those subtrees may be paid for.
    spec = fat_subtree_spec("aa", 60, 4)
    spec["mm"] = {"%d.0.0" % major: ["ghost *"] for major in range(1, 6)}
    universe, roots = case(spec, ["aa *", "mm *"])
    # reference 14 calls; the same search without backjumping spends 371.
    error, _ = unsolvable_within(universe, roots, 80)
    problems = check_explanation(universe, roots, error.causes)
    assert not problems, "\n  ".join(problems)


def test_a_cap_imposed_by_a_later_package_is_learned_once():
    # Every release of `mm` caps `aa` at 3.0.0, but `aa` sorts first and is
    # decided first. Trying `aa` from 70 downwards and walking each release's
    # private subtree before consulting `mm` costs sixty-seven useless subtrees.
    # The cap is one fact -- the union of what `mm`'s releases ask of `aa` --
    # and it is derivable the first time `mm` fails.
    spec = fat_subtree_spec("aa", 70, 4)
    spec["mm"] = {
        "%d.0.0" % major: ["aa <=%d.0.0" % major] for major in range(1, 4)
    }
    universe, roots = case(spec, ["aa *", "mm *"])
    # reference 33 calls; without the derived cap it is 252 at forty
    # releases of `aa` and grows linearly with them.
    solution, _ = solve_within(universe, roots, 170)
    assert_solution(
        solution,
        with_ballast(
            {
                "aa": "3.0.0",
                "aa-branch03": "4.0.0",
                "aa-leaf": "1.0.0",
                "mm": "3.0.0",
            }
        ),
    )


def test_an_unusable_dependency_is_not_rediscovered_per_parent_release():
    # Every release of `parent` needs `helper`, and no release of `helper` can
    # be installed because all of them need a package that is not published.
    # That is one fact about `helper`, not one per release of `parent`.
    spec = fat_subtree_spec("aa", 80, 3)
    spec["parent"] = {"%d.0.0" % major: ["helper *"] for major in range(1, 25)}
    spec["helper"] = {"%d.0.0" % major: ["ghost >=1.0.0"] for major in range(1, 9)}
    universe, roots = case(spec, ["aa *", "parent *"])
    # reference 42 calls; without backjumping, 289 even at fifty releases of
    # `aa`, and it grows with them.
    error, _ = unsolvable_within(universe, roots, 220)
    problems = check_explanation(universe, roots, error.causes)
    assert not problems, "\n  ".join(problems)


def test_a_wide_fanout_downloads_one_release_per_package():
    # Eighteen independent dependencies, thirty releases each. Only the release
    # actually chosen needs its dependency list fetched.
    spec = {"hub": {"1.0.0": ["w%02d *" % index for index in range(18)]}}
    for index in range(18):
        spec["w%02d" % index] = {"%d.0.0" % major: [] for major in range(1, 31)}
    universe, roots = case(spec, ["hub *"])
    # reference 63 calls; fetching every release's dependency list is 570.
    solution, _ = solve_within(universe, roots, 330)
    expected = {"hub": "1.0.0"}
    expected.update({"w%02d" % index: "30.0.0" for index in range(18)})
    assert_solution(solution, with_ballast(expected))


def test_a_deep_chain_costs_a_constant_per_link():
    # Twenty-five links, six releases each, pinned to 2.0.0 from the bottom.
    spec = chain_spec("link", 25, 6, 2)
    universe, roots = case(spec, ["link00 *"])
    # reference 166 calls -- one per release plus one per package.
    solution, _ = solve_within(universe, roots, 850)
    assert_solution(
        solution, with_ballast({"link%02d" % index: "2.0.0" for index in range(25)})
    )


def test_a_wide_conflict_is_walked_once_on_each_side():
    # Eighty releases on each side of the contradiction. Proving that every one
    # of them carries its half costs one dependency lookup per release and no
    # more; re-walking the cross product costs eighty times that.
    universe, roots = case(mutual_exclusion_spec(80), ["alpha *", "beta *"])
    # reference 164 calls: one per release on each side, and no more.
    error, _ = unsolvable_within(universe, roots, 840)
    problems = check_explanation(universe, roots, error.causes)
    assert not problems, "\n  ".join(problems)


def test_the_budget_covers_the_work_of_explaining():
    # A failing instance that also has a big irrelevant component: the
    # explanation must come out of the search, not out of a second pass over
    # candidate facts.
    spec = fat_subtree_spec("aa", 60, 4)
    spec.update(mutual_exclusion_spec(12, left="mx", right="my", shared="mshared"))
    universe, roots = case(spec, ["aa *", "mx *", "my *"])
    # reference 35 calls; without backjumping past `aa`, 384.
    error, _ = unsolvable_within(universe, roots, 180)
    problems = check_explanation(universe, roots, error.causes)
    assert not problems, "\n  ".join(problems)
