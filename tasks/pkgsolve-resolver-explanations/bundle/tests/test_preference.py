"""preference -- section 3.2, the one solution out of many that is correct.

Every universe here has several valid solutions. Returning *a* valid one is
worth nothing; the tests name the single preferred one. Several of them are
deliberately cases where a different -- and faster -- decision order produces a
valid solution that is not the one the specification defines.
"""

from __future__ import annotations

from _support import assert_solution, case, solve_within, with_ballast

BUDGET = 200      # 5.0x the reference's worst (40)


def test_newer_release_wins():
    # Worked example 1 in the specification.
    universe, roots = case(
        {
            "app": {"1.0.0": [], "2.0.0": ["util >=1.0.0"]},
            "util": {"1.0.0": [], "1.1.0": []},
        },
        ["app *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "util": "1.1.0"}))


def test_the_alphabetically_first_package_is_decided_first():
    # Worked example 2. Deciding `zz` first -- fewest releases, the standard
    # heuristic and the fast one -- returns {aa 2.0.0, zz 2.0.0}, which is a
    # perfectly valid solution and the wrong answer.
    universe, roots = case(
        {
            "aa": {"1.0.0": ["zz *"], "2.0.0": ["zz *"], "3.0.0": ["zz <=1.0.0"]},
            "zz": {"1.0.0": [], "2.0.0": []},
        },
        ["aa *", "zz *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"aa": "3.0.0", "zz": "1.0.0"}))


def test_the_order_the_roots_were_listed_in_does_not_matter():
    # The same universe as above with the manifest written the other way round.
    # A resolver that walks the requirement list in order decides `zz` first and
    # returns {aa 2.0.0, zz 2.0.0}.
    universe, roots = case(
        {
            "aa": {"1.0.0": ["zz *"], "2.0.0": ["zz *"], "3.0.0": ["zz <=1.0.0"]},
            "zz": {"1.0.0": [], "2.0.0": []},
        },
        ["zz *", "aa *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"aa": "3.0.0", "zz": "1.0.0"}))


def test_the_first_name_wins_even_when_it_has_the_most_releases():
    # `aardvark` sorts first and has the most releases and the loosest
    # constraints -- every heuristic worth the name would leave it for later.
    # Deciding `kb` first (fewest releases) returns {aardvark 5, kb 2, zulu 3},
    # which is valid and wrong.
    universe, roots = case(
        {
            "aardvark": {
                "1.0.0": ["zulu *"],
                "2.0.0": ["zulu *"],
                "3.0.0": ["zulu *"],
                "4.0.0": ["zulu *"],
                "5.0.0": ["zulu *"],
                "6.0.0": ["zulu <=1.0.0"],
            },
            "kb": {"1.0.0": ["zulu *"], "2.0.0": ["zulu >=2.0.0"]},
            "zulu": {"1.0.0": [], "2.0.0": [], "3.0.0": []},
        },
        ["aardvark *", "kb *", "zulu *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(
        solution, with_ballast({"aardvark": "6.0.0", "kb": "1.0.0", "zulu": "1.0.0"})
    )


def test_a_package_is_a_candidate_only_once_something_needs_it():
    # Worked example 3: `aaa` sorts before `mid` but is not needed until `mid`
    # is decided, so `mid` is decided first and takes its newest release.
    universe, roots = case(
        {
            "mid": {"1.0.0": ["aaa *"], "2.0.0": ["aaa <=1.0.0"]},
            "aaa": {"1.0.0": [], "2.0.0": []},
        },
        ["mid *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"aaa": "1.0.0", "mid": "2.0.0"}))


def test_not_installing_is_the_last_resort_not_the_first():
    # `optional` cannot be installed at all -- nothing depends on it and it is
    # not a root -- so it is absent, and everything else is still maximal.
    # "Install as little as possible" would also drop `helper`, which is wrong.
    universe, roots = case(
        {
            "app": {"1.0.0": [], "2.0.0": ["helper >=1.0.0"]},
            "helper": {"1.0.0": [], "2.0.0": []},
            "optional": {"1.0.0": []},
        },
        ["app *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "helper": "2.0.0"}))
    assert "optional" not in solution


def test_an_earlier_name_dominates_however_much_it_costs_a_later_one():
    # `aa 3.0.0` pins `zebra` to its oldest release. The comparison reaches
    # `aa` first, so that is the answer even though it costs six major versions
    # of `zebra`.
    universe, roots = case(
        {
            "aa": {
                "1.0.0": ["zebra >=7.0.0"],
                "2.0.0": ["zebra >=4.0.0"],
                "3.0.0": ["zebra <=1.0.0"],
            },
            "zebra": {"%d.0.0" % major: [] for major in range(1, 8)},
        },
        ["aa *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"aa": "3.0.0", "zebra": "1.0.0"}))


def test_a_later_name_is_maximised_only_after_the_earlier_one_is_fixed():
    universe, roots = case(
        {
            "aa": {"1.0.0": ["bb <=3.0.0"], "2.0.0": ["bb <=2.0.0"]},
            "bb": {"%d.0.0" % major: [] for major in range(1, 5)},
        },
        ["aa *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"aa": "2.0.0", "bb": "2.0.0"}))


def test_a_later_name_may_still_decide_between_equal_earlier_choices():
    # Both `front` versions are compatible with everything, so `front` is fixed
    # at its newest, and only then does `middle` get maximised.
    universe, roots = case(
        {
            "front": {"1.0.0": ["middle *"], "2.0.0": ["middle *"]},
            "middle": {"1.0.0": [], "2.0.0": [], "3.0.0": []},
        },
        ["front *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"front": "2.0.0", "middle": "3.0.0"}))


def test_a_package_only_an_older_release_would_pull_in_stays_out():
    # `widget` takes its newest release, which needs nothing, so `zaccessory`
    # never enters the closure at all -- and a resolver that maximises the
    # install set installs it anyway.
    universe, roots = case(
        {
            "widget": {"1.0.0": ["zaccessory *"], "2.0.0": []},
            "zaccessory": {"1.0.0": []},
        },
        ["widget *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"widget": "2.0.0"}))
    assert "zaccessory" not in solution


def test_root_requirements_bound_the_maximum():
    universe, roots = case(
        {
            "app": {"%d.0.0" % major: [] for major in range(1, 6)},
            "other": {"1.0.0": ["app <=2.0.0"]},
        },
        ["app *", "other *"],
    )
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"app": "2.0.0", "other": "1.0.0"}))


def test_a_deep_chain_is_maximised_from_the_top():
    # Each link caps the next; the alphabetically first link is maximised
    # first, and everything downstream follows from that.
    length, width = 7, 3
    spec = {}
    for index in range(length):
        name = "n%d" % index
        spec[name] = {}
        for major in range(1, width + 1):
            follows = []
            if index + 1 < length:
                follows.append("n%d >=%d.0.0" % (index + 1, major))
            spec[name]["%d.0.0" % major] = follows
    spec["n%d" % (length - 1)] = {"1.0.0": [], "2.0.0": []}
    universe, roots = case(spec, ["n0 *"])
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(
        solution, with_ballast({"n%d" % index: "2.0.0" for index in range(length)})
    )


def test_a_diamond_shares_one_version_of_the_base():
    universe, roots = case(
        {
            "top": {"1.0.0": ["left *", "right *"]},
            "left": {"1.0.0": ["base >=2.0.0"], "2.0.0": ["base >=4.0.0"]},
            "right": {"1.0.0": ["base <=3.0.0"], "2.0.0": ["base <=2.0.0"]},
            "base": {"%d.0.0" % major: [] for major in range(1, 5)},
        },
        ["top *"],
    )
    # `top` is the only package needed at the start, so it goes first. Deciding
    # it makes `left` and `right` needed, and `left` comes next: 2.0.0 would
    # force base >=4.0.0, which no `right` can match, so `left` takes 1.0.0 --
    # which makes `base` needed, and `base` now sorts BEFORE `right`. base 4.0.0
    # is not completable, 3.0.0 is, and `right` is left with 1.0.0.
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(
        solution,
        with_ballast(
            {"base": "3.0.0", "left": "1.0.0", "right": "1.0.0", "top": "1.0.0"}
        ),
    )


def test_a_cycle_is_maximised_like_anything_else():
    universe, roots = case(
        {
            "ping": {"1.0.0": ["pong <=1.0.0"], "2.0.0": ["pong >=2.0.0"]},
            "pong": {"1.0.0": ["ping *"], "2.0.0": ["ping <=1.0.0"]},
        },
        ["ping *"],
    )
    # ping 2.0.0 needs pong >=2.0.0, and pong 2.0.0 needs ping <=1.0.0 -- a
    # contradiction. So ping 1.0.0, and then pong is maximised under <=1.0.0.
    solution, _ = solve_within(universe, roots, BUDGET)
    assert_solution(solution, with_ballast({"ping": "1.0.0", "pong": "1.0.0"}))
