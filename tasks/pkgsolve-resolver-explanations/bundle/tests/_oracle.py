"""The grader's own reading of the specification.

Nothing here is imported from the submission except the value types, so the
expected answers never come from the code under test.

* :func:`enumerate_solutions` / :func:`preferred_solution` implement sections
  3.1 and 3.2 literally -- every assignment, filtered by validity, reduced by
  the pairwise preference comparison written out as a loop. Exhaustive, so it is
  only ever used on deliberately tiny universes.
* :func:`satisfiable` is a complete backtracking search used on the *reduced*
  universes of section 4, which have very few dependency edges but may have a
  long version axis. Versions that no cited fact and no cited range can tell
  apart are collapsed to one representative first, which is what keeps it fast.
* :func:`check_explanation` is conditions (E1)-(E5), each reported separately.
"""

from __future__ import annotations

import itertools

from pkgsolve import DependencyFact, RootRequirement

MAX_ENUMERATION = 400_000


# ----------------------------------------------------------------------
# sections 3.1 and 3.2, read literally
# ----------------------------------------------------------------------
def is_valid(universe, roots, solution):
    """Root satisfaction, dependency satisfaction and exact closure."""
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
        for dependency in universe.dependencies(name, version):
            chosen = solution.get(dependency.package)
            if chosen is None or not dependency.range.contains(chosen):
                return False
            if dependency.package not in needed:
                needed.add(dependency.package)
                frontier.append(dependency.package)
    return needed == set(solution)


def mentioned_names(universe, roots):
    """Every package that could appear, over-approximated across all versions."""
    seen = set()
    frontier = [requirement.package for requirement in roots]
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        for version in universe.versions(name):
            for dependency in universe.dependencies(name, version):
                if dependency.package not in seen:
                    frontier.append(dependency.package)
    return sorted(seen)


def enumerate_solutions(universe, roots):
    names = mentioned_names(universe, roots)
    options = [tuple(universe.versions(name)) + (None,) for name in names]
    total = 1
    for option in options:
        total *= len(option)
        if total > MAX_ENUMERATION:
            raise RuntimeError(
                "refusing to enumerate %d+ assignments; this instance is too "
                "large for the exhaustive oracle" % (MAX_ENUMERATION,)
            )
    found = []
    for combination in itertools.product(*options):
        solution = {
            name: version
            for name, version in zip(names, combination)
            if version is not None
        }
        if is_valid(universe, roots, solution):
            found.append(solution)
    return found


def preferred_solution(universe, roots):
    """Section 3.2, run literally against the full set of valid solutions.

    Take the packages in alphabetical order as they are discovered; give each
    the newest release that some remaining valid solution still agrees with.
    Slow and obviously correct, which is the point of an oracle.
    """
    remaining = enumerate_solutions(universe, roots)
    if not remaining:
        return None

    decided = {}
    needed = set(requirement.package for requirement in roots)
    while True:
        undecided = sorted(name for name in needed if name not in decided)
        if not undecided:
            break
        package = undecided[0]
        best = max(solution[package] for solution in remaining)
        decided[package] = best
        remaining = [
            solution for solution in remaining if solution.get(package) == best
        ]
        for dependency in universe.dependencies(package, best):
            needed.add(dependency.package)

    assert remaining and all(solution == decided for solution in remaining), (
        "the preference procedure did not converge on one solution: %r" % (remaining,)
    )
    return decided


# ----------------------------------------------------------------------
# section 4: the reduced universe
# ----------------------------------------------------------------------
def _reduced(causes):
    roots = tuple(
        fact.requirement for fact in sorted(causes, key=str)
        if isinstance(fact, RootRequirement)
    )
    facts = tuple(
        fact for fact in sorted(causes, key=str) if isinstance(fact, DependencyFact)
    )
    return roots, facts


def _candidates(universe, roots, facts):
    """One representative per indistinguishable class of versions, descending."""
    packages = set(requirement.package for requirement in roots)
    for fact in facts:
        packages.add(fact.package)
        packages.add(fact.requirement.package)

    table = {}
    for package in sorted(packages):
        owned = [fact for fact in facts if fact.package == package]
        limits = [requirement.range for requirement in roots
                  if requirement.package == package]
        limits += [fact.requirement.range for fact in facts
                   if fact.requirement.package == package]
        seen = {}
        for version in universe.versions(package):
            # Group by the requirements a release actually produces, not by
            # which facts happen to mention it: an explanation that cites one
            # fact per release then collapses to a single class instead of one
            # class per release, which is what keeps this check cheap.
            signature = (
                frozenset(
                    fact.requirement for fact in owned
                    if fact.versions.contains(version)
                ),
                tuple(limit.contains(version) for limit in limits),
            )
            # Later versions win the slot: the representative is the newest of
            # its class, which keeps the search deterministic.
            seen[signature] = version
        table[package] = tuple(sorted(seen.values(), reverse=True))
    return table


def satisfiable(universe, causes):
    """Does the reduced universe ``U(causes)`` have a valid solution?"""
    roots, facts = _reduced(causes)
    if not roots:
        return True  # the empty solution satisfies an empty request
    candidates = _candidates(universe, roots, facts)

    by_package = {}
    for fact in facts:
        by_package.setdefault(fact.package, []).append(fact)

    def dependencies(package, version):
        return tuple(
            fact.requirement
            for fact in by_package.get(package, ())
            if fact.versions.contains(version)
        )

    def search(needed, limits, decided):
        undecided = sorted(name for name in needed if name not in decided)
        if not undecided:
            return True
        name = undecided[0]
        for version in candidates.get(name, ()):
            if not all(limit.contains(version) for limit in limits.get(name, ())):
                continue
            next_limits = {key: list(value) for key, value in limits.items()}
            next_needed = set(needed)
            # Commit before walking the dependencies, so that a package which
            # depends on *itself* is checked against the version just chosen.
            decided[name] = version
            consistent = True
            for requirement in dependencies(name, version):
                next_limits.setdefault(requirement.package, []).append(requirement.range)
                next_needed.add(requirement.package)
                already = decided.get(requirement.package)
                if already is not None and not requirement.range.contains(already):
                    consistent = False
                    break
            if consistent and search(next_needed, next_limits, decided):
                return True
            del decided[name]
        return False

    limits = {}
    needed = set()
    for requirement in roots:
        limits.setdefault(requirement.package, []).append(requirement.range)
        needed.add(requirement.package)
    return search(needed, limits, {})


# ----------------------------------------------------------------------
# section 4: (E1) - (E5)
# ----------------------------------------------------------------------
def fact_problems(universe, fact):
    """(E3) is this ``DependencyFact`` implied by the registry?"""
    problems = []
    target = fact.requirement.package
    published = universe.versions(target)
    allowed = set(version for version in published
                  if fact.requirement.range.contains(version))
    covered = [version for version in universe.versions(fact.package)
               if fact.versions.contains(version)]
    for version in covered:
        declared = [requirement
                    for requirement in universe.dependencies(fact.package, version)
                    if requirement.package == target]
        if not declared:
            problems.append(
                "untrue fact %s: %s %s declares no dependency on %s at all"
                % (fact, fact.package, version, target)
            )
            continue
        really = set(candidate for candidate in published
                     if all(req.range.contains(candidate) for req in declared))
        if not really <= allowed:
            escapes = sorted(really - allowed)
            problems.append(
                "untrue fact %s: %s %s actually allows %s, which the cited "
                "range does not"
                % (fact, fact.package, version,
                   ", ".join("%s %s" % (target, item) for item in escapes[:3]))
            )
    return problems


def check_explanation(universe, roots, causes):
    """Every way ``causes`` fails conditions (E1)-(E5). Empty list means good."""
    problems = []

    if not isinstance(causes, frozenset):
        problems.append(
            "Unsolvable.causes must be a frozenset, got %r" % (type(causes).__name__,)
        )
        try:
            causes = frozenset(causes)
        except TypeError:
            return problems

    # (E1) well-typed
    for fact in causes:
        if not isinstance(fact, (RootRequirement, DependencyFact)):
            problems.append(
                "(E1) %r is neither a RootRequirement nor a DependencyFact"
                % (fact,)
            )
    if problems:
        return problems

    # (E2) rooted in the request
    requested = set(roots)
    for fact in causes:
        if isinstance(fact, RootRequirement) and fact.requirement not in requested:
            problems.append(
                "(E2) cited root requirement %s was never asked for" % (fact.requirement,)
            )

    # (E3) true of the registry
    for fact in causes:
        if isinstance(fact, DependencyFact):
            problems.extend("(E3) " + problem for problem in fact_problems(universe, fact))

    if problems:
        return problems

    # (E4) sufficient
    if satisfiable(universe, causes):
        problems.append(
            "(E4) the cited facts do not rule out every solution; %s"
            % (describe(causes),)
        )
        return problems

    # (E5) minimal
    for fact in sorted(causes, key=str):
        if not satisfiable(universe, causes - {fact}):
            problems.append(
                "(E5) dropping `%s` leaves the explanation unsatisfiable, so it "
                "was not needed; %s" % (fact, describe(causes))
            )
    return problems


def describe(causes):
    if not causes:
        return "causes is empty"
    return "cited %d fact(s): %s" % (
        len(causes), "; ".join(str(fact) for fact in sorted(causes, key=str)),
    )
