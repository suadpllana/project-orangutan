"""Shared plumbing for the sealed pkgsolve suite.

Two design rules run through this file.

**The grader never trusts the implementation's own accounting.** Registry calls
are counted by a closure the submission cannot reach: the object handed to
``resolve()`` stores nothing on the instance and is not an instance of the
submission's own ``Registry`` class, so there is no attribute to read and no
subclass hook to override. The counter is returned to the test, never to the
resolver.

**Every graded universe carries ballast.** A small satisfiable component that
forces real backtracking is merged into every case, so a resolver that
downloads the reachable universe before deciding anything -- which is what the
starting implementation does -- blows the query budget on every single test
rather than only on the ones that were designed to be hard.
"""

from __future__ import annotations

from pkgsolve import Range, Requirement, Unsolvable, Version, resolve


class QueryLimitExceeded(BaseException):
    """Raised by the sealed registry when a run runs away.

    Deliberately **not** an ``Exception`` subclass: a resolver that wraps its
    search in ``except Exception`` must not be able to turn a blown budget into
    a wrong answer, and the specification says so in section 5.
    """


# ----------------------------------------------------------------------
# the universe the grader owns
# ----------------------------------------------------------------------
class Universe:
    """Uncounted access to a package table, for the grader's own use."""

    def __init__(self, spec):
        table = {}
        for package, releases in spec.items():
            entries = {}
            for version, requirements in releases.items():
                key = Version.parse(version) if isinstance(version, str) else version
                entries[key] = tuple(
                    Requirement.parse(r) if isinstance(r, str) else r for r in requirements
                )
            table[package] = entries
        self._table = table
        self._sorted = {name: tuple(sorted(entries)) for name, entries in table.items()}

    def versions(self, package):
        return self._sorted.get(package, ())

    def dependencies(self, package, version):
        try:
            return self._table[package][version]
        except KeyError:
            raise LookupError("%s %s is not published" % (package, version)) from None

    def releases(self):
        return sum(len(entries) for entries in self._table.values())

    def names(self):
        return tuple(sorted(self._table))


def sealed_registry(universe, hard_limit):
    """A counting registry with no reachable state.

    Returns ``(registry, counter)``. ``registry`` exposes exactly ``versions``
    and ``dependencies``; the table and the counter live in closure cells, and
    the instance has no ``__dict__``.
    """
    counter = {"calls": 0, "versions": 0, "dependencies": 0}

    def _tick(kind):
        counter["calls"] += 1
        counter[kind] += 1
        if counter["calls"] > hard_limit:
            raise QueryLimitExceeded(
                "the resolver made more than %d registry calls" % (hard_limit,)
            )

    def versions(package):
        _tick("versions")
        return universe.versions(package)

    def dependencies(package, version):
        _tick("dependencies")
        return universe.dependencies(package, version)

    sealed = type(
        "SealedRegistry",
        (),
        {
            "__slots__": (),
            "versions": staticmethod(versions),
            "dependencies": staticmethod(dependencies),
        },
    )
    return sealed(), counter


# ----------------------------------------------------------------------
# ballast
# ----------------------------------------------------------------------
# Four chained packages, twenty releases, where the top of the chain is pinned
# low by the bottom of it. Satisfiable, independent of everything else, and
# named so that every one of its packages sorts after any package a test
# invents -- so it can never decide a preference comparison.
_BALLAST_NAMES = ("zz-alpha", "zz-bravo", "zz-charlie", "zz-delta")
_BALLAST_COUNTS = (6, 6, 6, 2)

BALLAST_SPEC = {}
for _index, (_name, _count) in enumerate(zip(_BALLAST_NAMES, _BALLAST_COUNTS)):
    BALLAST_SPEC[_name] = {}
    for _major in range(1, _count + 1):
        _follows = []
        if _index + 1 < len(_BALLAST_NAMES):
            _follows.append("%s >=%d.0.0" % (_BALLAST_NAMES[_index + 1], _major))
        BALLAST_SPEC[_name]["%d.0.0" % _major] = _follows

BALLAST_ROOT = Requirement.parse("zz-alpha *")
BALLAST_SOLUTION = {name: Version(2, 0, 0) for name in _BALLAST_NAMES}


def is_ballast(package):
    return package.startswith("zz-")


def case(spec, roots, ballast=True):
    """Merge ballast into a hand-written spec.

    Returns ``(universe, roots)``. The caller's expected solution is completed
    with :func:`with_ballast`.
    """
    merged = dict(spec)
    resolved_roots = [Requirement.parse(r) if isinstance(r, str) else r for r in roots]
    if ballast:
        overlap = set(merged) & set(BALLAST_SPEC)
        assert not overlap, "a test reused a ballast package name: %s" % (overlap,)
        merged.update(BALLAST_SPEC)
        resolved_roots = resolved_roots + [BALLAST_ROOT]
    return Universe(merged), resolved_roots


def with_ballast(expected):
    """Complete an expected solution with the ballast component's answer."""
    combined = dict(BALLAST_SOLUTION)
    combined.update(
        {name: Version.parse(value) if isinstance(value, str) else value
         for name, value in expected.items()}
    )
    return combined


def core_of(solution):
    """The non-ballast half of a solution."""
    return {name: version for name, version in solution.items() if not is_ballast(name)}


# ----------------------------------------------------------------------
# running the submission under a budget
# ----------------------------------------------------------------------
def solve_within(universe, roots, budget):
    """Call ``resolve`` under a counted registry. Returns ``(solution, counter)``."""
    registry, counter = sealed_registry(universe, hard_limit=budget * 20)
    try:
        solution = resolve(registry, list(roots))
    except QueryLimitExceeded as limit:
        raise AssertionError(
            "aborted: %s (the budget for this instance is %d calls over %d releases)"
            % (limit, budget, universe.releases())
        ) from None
    assert isinstance(solution, dict), "resolve must return a dict, got %r" % (type(solution),)
    assert counter["calls"] <= budget, (
        "%d registry calls over %d releases; the budget is %d "
        "(%d versions() + %d dependencies())"
        % (counter["calls"], universe.releases(), budget,
           counter["versions"], counter["dependencies"])
    )
    return solution, counter


def unsolvable_within(universe, roots, budget):
    """Call ``resolve`` expecting ``Unsolvable``. Returns ``(error, counter)``."""
    registry, counter = sealed_registry(universe, hard_limit=budget * 20)
    try:
        solution = resolve(registry, list(roots))
    except QueryLimitExceeded as limit:
        raise AssertionError(
            "aborted: %s (the budget for this instance is %d calls over %d releases)"
            % (limit, budget, universe.releases())
        ) from None
    except Unsolvable as error:
        assert counter["calls"] <= budget, (
            "%d registry calls over %d releases; the budget is %d"
            % (counter["calls"], universe.releases(), budget)
        )
        return error, counter
    raise AssertionError(
        "expected Unsolvable, got a solution: %s" % (format_solution(solution),)
    )


def format_solution(solution):
    if not isinstance(solution, dict):
        return repr(solution)
    return "{" + ", ".join(
        "%s %s" % (name, solution[name]) for name in sorted(solution)
    ) + "}"


def assert_solution(actual, expected):
    assert actual == expected, "expected %s\n     got %s" % (
        format_solution(expected), format_solution(actual),
    )


# ----------------------------------------------------------------------
# instance families for the budget category
# ----------------------------------------------------------------------
def chain_spec(prefix, length, width, tail_width):
    """``prefix``0 -> ``prefix``1 -> ... with each link pinned by the next."""
    spec = {}
    for index in range(length):
        name = "%s%02d" % (prefix, index)
        count = tail_width if index == length - 1 else width
        spec[name] = {}
        for major in range(1, count + 1):
            follows = []
            if index + 1 < length:
                follows.append("%s%02d >=%d.0.0" % (prefix, index + 1, major))
            spec[name]["%d.0.0" % major] = follows
    return spec


def fat_subtree_spec(owner, count, leaf_versions):
    """``owner`` has ``count`` versions, each with its own private subtree.

    Exploring one of these subtrees is pure waste for a resolver that has
    already learned the conflict lives somewhere else entirely.
    """
    spec = {owner: {}}
    for major in range(1, count + 1):
        branch = "%s-branch%02d" % (owner, major)
        spec[owner]["%d.0.0" % major] = ["%s *" % branch]
        spec[branch] = {
            "%d.0.0" % leaf: ["%s-leaf *" % owner] for leaf in range(1, leaf_versions + 1)
        }
    spec["%s-leaf" % owner] = {"1.0.0": []}
    return spec


def mutual_exclusion_spec(width, left="alpha", right="beta", shared="shared"):
    """Every ``left`` needs ``shared >=2``, every ``right`` needs ``shared <2``."""
    spec = {
        left: {"%d.0.0" % major: ["%s >=2.0.0" % shared] for major in range(1, width + 1)},
        right: {"%d.0.0" % major: ["%s <2.0.0" % shared] for major in range(1, width + 1)},
        shared: {"1.0.0": [], "2.0.0": []},
    }
    return spec


def capped_spec(free, count, capper, cap):
    """``capper`` is what really decides ``free``'s version, and it sorts later.

    ``free`` has ``count`` versions each dragging in a private subtree, but
    every version of ``capper`` requires ``free <= cap``. A resolver that
    commits to ``free``'s newest version first pays for ``count - cap`` useless
    subtrees before it finds that out.
    """
    spec = fat_subtree_spec(free, count, 4)
    spec[capper] = {
        "%d.0.0" % major: ["%s <=%d.0.0" % (free, cap)] for major in range(1, cap + 1)
    }
    return spec


# ----------------------------------------------------------------------
# random instances
# ----------------------------------------------------------------------
def random_spec(rng, packages, versions, max_deps):
    """A small random universe. Names sort before any ballast name."""
    names = ["p%02d" % index for index in range(packages)]
    spec = {}
    for position, name in enumerate(names):
        count = rng.randint(1, versions)
        spec[name] = {}
        for major in range(1, count + 1):
            follows = []
            # Only depend on later names, plus an occasional back edge, so the
            # graph is mostly a DAG with a few cycles.
            candidates = names[position + 1:] + (names[:position] if rng.random() < 0.25 else [])
            rng.shuffle(candidates)
            for target in candidates[: rng.randint(0, max_deps)]:
                follows.append("%s %s" % (target, _random_range(rng)))
            spec[name]["%d.0.0" % major] = follows
    return spec


def _random_range(rng):
    choice = rng.random()
    if choice < 0.30:
        return "*"
    if choice < 0.55:
        return ">=%d.0.0" % rng.randint(1, 3)
    if choice < 0.75:
        return "<=%d.0.0" % rng.randint(1, 3)
    if choice < 0.90:
        return "==%d.0.0" % rng.randint(1, 3)
    return ">=%d.0.0,<=%d.0.0" % (1, rng.randint(1, 3))


def random_roots(rng, spec, count):
    names = sorted(spec)
    rng.shuffle(names)
    return [Requirement.parse("%s %s" % (name, _random_range(rng)))
            for name in names[:count]]


# ----------------------------------------------------------------------
# named cases shared between modules
# ----------------------------------------------------------------------
SAMPLE_SPEC = {
    "app": {
        "1.0.0": ["core >=1.0.0"],
        "1.5.0": ["core >=2.0.0"],
        "2.0.0": ["core >=3.0.0", "extra *"],
    },
    "core": {"1.0.0": [], "2.0.0": [], "3.0.0": ["base <=2.0.0"]},
    "base": {"1.0.0": [], "2.0.0": [], "3.0.0": []},
    "extra": {"1.0.0": ["base >=2.0.0"], "2.0.0": ["base >=9.0.0"]},
}


def sample_case():
    """A medium solvable manifest, used wherever a test needs `a real instance`."""
    return case(SAMPLE_SPEC, ["app *"])


def sample_solution():
    return with_ballast(
        {"app": "2.0.0", "base": "2.0.0", "core": "3.0.0", "extra": "1.0.0"}
    )


CONFLICT_SPEC = {
    "alpha": {"1.0.0": ["shared >=2.0.0"], "1.1.0": ["shared >=2.0.0"]},
    "beta": {"1.0.0": ["shared <2.0.0"], "1.1.0": ["shared <2.0.0"]},
    "shared": {"1.0.0": [], "2.0.0": []},
}


def conflict_case():
    return case(CONFLICT_SPEC, ["alpha *", "beta *"])


def determinism_case(name):
    """The cases the hash-seed subprocess and its parent must agree on."""
    if name == "solvable":
        return sample_case()
    if name == "unsolvable":
        return conflict_case()
    raise SystemExit("unknown determinism case %r" % (name,))
