"""The resolver.

WHAT THIS IS
------------
A brute-force enumerator. It discovers every package reachable from the root
requirements, pulls down every version of each of them together with that
version's dependencies, enumerates the whole cartesian product of assignments
and keeps the ones that are valid. Then it applies the preference procedure
from section 3.2 of the specification to that list: take the packages in
alphabetical order as they are discovered and, for each, keep only the
solutions that give it the newest version any of them still offers.

It is correct. That is the only good thing about it.

WHY IT IS NOT ENOUGH
--------------------
* It asks the registry for every version of every reachable package before it
  makes a single decision, and then asks again -- once per candidate assignment
  -- while checking validity, and again while narrowing. Nothing is cached. A
  manifest reaching a few hundred releases costs hundreds of thousands of round
  trips, and the graded budgets are one to three orders of magnitude below what
  it spends.
* The product is exponential in the number of packages.
* When it fails it has nothing to say. `Unsolvable` is raised with an empty
  `causes`, which proves nothing at all: see section 4 of the specification for
  what a real explanation has to satisfy.

Replacing this function is the task.
"""

from __future__ import annotations

import itertools

from .errors import Unsolvable
from .requirements import Requirement


def resolve(registry, requirements):
    """Return the preferred valid solution, or raise ``Unsolvable``."""
    roots = _check_requirements(requirements)
    if not roots:
        return {}

    universe = _discover(registry, roots)
    names = sorted(universe)

    options = [tuple(reversed(universe[name])) + (None,) for name in names]
    solutions = []
    for combination in itertools.product(*options):
        assignment = {
            name: version
            for name, version in zip(names, combination)
            if version is not None
        }
        if _is_valid(registry, roots, assignment):
            solutions.append(assignment)

    if not solutions:
        # TODO(pkgsolve#118): work out *why* and cite it. An empty `causes` is
        # not an explanation, and the build farm's users keep asking for one.
        raise Unsolvable(frozenset())

    return _preferred(registry, roots, solutions)


def _preferred(registry, roots, solutions):
    """Section 3.2, applied to the list of every valid solution."""
    remaining = solutions
    decided = {}
    needed = set(requirement.package for requirement in roots)
    while True:
        undecided = sorted(name for name in needed if name not in decided)
        if not undecided:
            return decided
        package = undecided[0]
        best = max(solution[package] for solution in remaining)
        decided[package] = best
        remaining = [
            solution for solution in remaining if solution.get(package) == best
        ]
        for dependency in registry.dependencies(package, best):
            needed.add(dependency.package)


def _check_requirements(requirements):
    """Validate the caller's argument before touching the registry."""
    try:
        items = list(requirements)
    except TypeError:
        raise TypeError("requirements must be iterable of Requirement") from None
    for item in items:
        if not isinstance(item, Requirement):
            raise TypeError(
                "requirements must contain Requirement, found %r"
                % (type(item).__name__,)
            )
    return items


def _discover(registry, roots):
    """Every package reachable from the roots, with all of its versions."""
    universe = {}
    frontier = [requirement.package for requirement in roots]
    while frontier:
        name = frontier.pop()
        if name in universe:
            continue
        published = tuple(registry.versions(name))
        universe[name] = published
        for version in published:
            for dependency in registry.dependencies(name, version):
                if dependency.package not in universe:
                    frontier.append(dependency.package)
    return universe


def _is_valid(registry, roots, solution):
    for requirement in roots:
        version = solution.get(requirement.package)
        if version is None or not requirement.range.contains(version):
            return False

    needed = set(requirement.package for requirement in roots)
    frontier = sorted(needed)
    while frontier:
        name = frontier.pop()
        version = solution.get(name)
        if version is None:
            return False
        for dependency in registry.dependencies(name, version):
            other = solution.get(dependency.package)
            if other is None or not dependency.range.contains(other):
                return False
            if dependency.package not in needed:
                needed.add(dependency.package)
                frontier.append(dependency.package)

    return needed == set(solution)
