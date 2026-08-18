"""The resolver.

Three things have to be true at once, and each of them rules out the cheap way
of getting the other two.

*The answer is one specific solution.* Section 3.2 fixes the decision order:
alphabetical over the packages as they are discovered, newest release first,
backtracking when a choice turns out not to be completable. This function is
that procedure, literally. What it may not do is reorder the decisions -- and
"pick the most constrained package next" is exactly the heuristic that makes
backtracking cheap, so the efficiency has to be found somewhere else.

*The search has a registry budget.* Three mechanisms buy it back without
touching the decision order:

  - ``_Client`` memoises, so no question is ever asked twice;
  - failures carry a **conflict set** -- the decided packages the failure
    actually consulted -- so the search can jump straight past choices the
    failure did not depend on, instead of retrying each of them;
  - a failure that consulted no outside decision is *intrinsic* to the
    sub-problem, and is remembered against the sub-problem's constraints, so a
    dead end is discovered once rather than once per path that reaches it;
  - when a required package fails outright, the union of what its releases ask
    of some other package is a globally valid constraint. Learning it turns
    "try forty versions and walk forty subtrees" into "start at the third".

*A failure has to be explained.* Every dependency list the search reads is
recorded as a ``DependencyFact`` about that exact release. When the search
fails, those facts plus the root requirements are a sound proof by
construction: the search never rejected a release without a cited reason. The
proof is then widened where the whole range was read (so the explanation reads
as "every version of x requires y" rather than as forty separate lines) and
minimised by deletion. Both of those steps run against data already in the
cache, so neither costs a single registry call.
"""

from __future__ import annotations

from .errors import Unsolvable
from .ranges import ANY, Range
from .requirements import DependencyFact, Requirement, RootRequirement


def resolve(registry, requirements):
    """Return the preferred valid solution, or raise ``Unsolvable``."""
    roots = _check_requirements(requirements)
    if not roots:
        return {}
    search = _Search(_Client(registry), roots)
    solution = search.run()
    if solution is None:
        raise Unsolvable(search.explain())
    return solution


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


def _exactly(version):
    return Range((("==", version),))


class _Client:
    """A memoising view of the registry. One question, one round trip."""

    def __init__(self, registry):
        self._registry = registry
        self._versions = {}
        self._dependencies = {}

    def versions(self, package):
        cached = self._versions.get(package)
        if cached is None:
            cached = tuple(self._registry.versions(package))
            self._versions[package] = cached
        return cached

    def dependencies(self, package, version):
        key = (package, version)
        cached = self._dependencies.get(key)
        if cached is None:
            cached = tuple(self._registry.dependencies(package, version))
            self._dependencies[key] = cached
        return cached

    def have_dependencies(self, package, version):
        return (package, version) in self._dependencies

    def read_releases(self, package):
        return sorted(
            version for (name, version) in self._dependencies if name == package
        )


class _Restart(Exception):
    """A globally valid narrowing was just derived.

    Abandon the pass and start again with it in force. Without this the pass
    that derived the narrowing carries on grinding through the very releases
    the narrowing just ruled out -- which is most of the cost it was supposed
    to save. Restarting is free in registry terms: the cache is warm.
    """


class _Failure:
    """Why a sub-problem has no solution.

    ``blame`` names the packages decided *above* the sub-problem that the
    failure depended on, either because one of them contributed a range that
    ruled a release out or because the failure ran into one of their chosen
    versions head-on. If the current decision is not in ``blame``, none of its
    other releases can help and the search jumps straight past them.

    ``external`` is the narrower half: only the head-on collisions. Ranges
    contributed from above are part of the sub-problem's own identity -- they
    are in the memo key -- so consulting one does not stop the failure being a
    property of the sub-problem itself. An empty ``external`` is what licenses
    remembering the sub-problem as hopeless.
    """

    __slots__ = ("blame", "external")

    def __init__(self, blame=(), external=()):
        self.blame = set(blame)
        self.external = set(external)


class _Search:
    def __init__(self, client, roots):
        self.client = client
        self.roots = list(roots)
        self.root_names = set(requirement.package for requirement in self.roots)
        self.learned = {}        # package -> list[Range], globally valid
        self.dead = set()        # sub-problems already proved hopeless
        self.used = set()        # DependencyFact for every list we read
        self._learned_something = False

    # -- registry ------------------------------------------------------
    def dependencies(self, package, version):
        found = self.client.dependencies(package, version)
        window = _exactly(version)
        for requirement in found:
            self.used.add(DependencyFact(package, window, requirement))
        return found

    def global_ranges(self, package):
        ranges = [
            requirement.range for requirement in self.roots
            if requirement.package == package
        ]
        ranges.extend(self.learned.get(package, ()))
        return ranges

    # -- driving -------------------------------------------------------
    def run(self):
        while True:
            self._learned_something = False
            self.dead = set()
            limits = {}
            for package in sorted(
                set(self.root_names) | set(self.learned)
            ):
                for one in self.global_ranges(package):
                    limits.setdefault(package, []).append((one, None))
            try:
                outcome = self.decide(set(self.root_names), limits, {})
            except _Restart:
                continue          # a narrowing landed; start again, cache warm
            if not isinstance(outcome, _Failure):
                return outcome
            if self._learned_something:
                continue
            return None

    def learn(self, package, allowed):
        """Record a globally valid narrowing of ``package``."""
        published = self.client.versions(package)
        if not published:
            return
        if allowed:
            window = Range(((">=", min(allowed)), ("<=", max(allowed))))
        else:
            # Nothing works. Any range that holds no published version says so.
            window = Range(((">", max(published)),))
        existing = self.learned.setdefault(package, [])
        if window in existing:
            return
        existing.append(window)
        self._learned_something = True

    # -- the search ----------------------------------------------------
    def decide(self, needed, limits, decided):
        undecided = sorted(name for name in needed if name not in decided)
        if not undecided:
            return dict(decided)

        key = (
            frozenset(undecided),
            frozenset(
                (name, one)
                for name in undecided
                for (one, _owner) in limits.get(name, ())
            ),
        )
        if key in self.dead:
            # The sub-problem is known hopeless. Its blame is whoever supplied
            # the ranges that define it, recomputed here for this path.
            owners = set()
            for name in undecided:
                for (_one, owner) in limits.get(name, ()):
                    if owner is not None:
                        owners.add(owner)
            return _Failure(owners, ())

        name = undecided[0]
        active = tuple(limits.get(name, ()))
        # Whoever asked for this package at all is part of any failure of it,
        # not only whoever narrowed it. Leaving them out lets the search
        # conclude that a package with no usable release "does not depend on"
        # the decision that pulled it in, and then jump past that decision
        # without ever looking at its other releases.
        blame = set(owner for (_one, owner) in active if owner is not None)
        external = set()

        for version in reversed(self.client.versions(name)):
            blocked = False
            for (one, owner) in active:
                if not one.contains(version):
                    if owner is not None:
                        blame.add(owner)
                    blocked = True
            if blocked:
                continue

            child_limits = {other: list(value) for other, value in limits.items()}
            child_needed = set(needed)
            decided[name] = version
            clash = False
            for requirement in self.dependencies(name, version):
                child_limits.setdefault(requirement.package, []).append(
                    (requirement.range, name)
                )
                child_needed.add(requirement.package)
                settled = decided.get(requirement.package)
                if settled is not None and not requirement.range.contains(settled):
                    if requirement.package != name:
                        blame.add(requirement.package)
                        external.add(requirement.package)
                    clash = True
                    break
            if clash:
                del decided[name]
                continue

            outcome = self.decide(child_needed, child_limits, decided)
            del decided[name]
            if not isinstance(outcome, _Failure):
                return outcome
            if name not in outcome.blame:
                # Nothing about this failure depended on `name`, so no other
                # release of it can help. Hand the failure straight up.
                return _Failure(outcome.blame - {name}, outcome.external - {name})
            blame |= outcome.blame - {name}
            external |= outcome.external - {name}

        if not external:
            self.dead.add(key)
        self._maybe_learn(name)
        return _Failure(blame - {name}, external - {name})

    def _maybe_learn(self, name):
        """Narrow whatever a required package constrains, once and for all.

        If ``name`` is required unconditionally, then whichever of its releases
        is eventually chosen, every package it depends on is confined to the
        union of what its releases ask. That is a fact about the registry, not
        about the current path, so it survives backtracking -- and it is what
        turns "try forty releases, walk forty subtrees" into "start at the
        third".
        """
        if name not in self.root_names:
            return
        windows = self.global_ranges(name)
        usable = [
            version for version in self.client.versions(name)
            if all(one.contains(version) for one in windows)
        ]
        if not usable:
            return
        if not all(self.client.have_dependencies(name, version) for version in usable):
            return

        reach = {}
        for version in usable:
            here = {}
            for requirement in self.client.dependencies(name, version):
                allowed = set(
                    candidate
                    for candidate in self.client.versions(requirement.package)
                    if requirement.range.contains(candidate)
                )
                previous = here.get(requirement.package)
                here[requirement.package] = (
                    allowed if previous is None else (previous & allowed)
                )
            for target, allowed in here.items():
                reach.setdefault(target, []).append(allowed)

        for target in sorted(reach):
            per_version = reach[target]
            if len(per_version) != len(usable):
                continue          # some release does not mention it: no bound
            union = set()
            for allowed in per_version:
                union |= allowed
            if union >= set(self.client.versions(target)):
                continue          # no narrowing to be had
            self.learn(target, union)
        if self._learned_something:
            raise _Restart()

    # -- explaining ----------------------------------------------------
    def explain(self):
        causes = set(RootRequirement(requirement) for requirement in self.roots)
        causes |= self._widened()
        if _satisfiable(self.client, causes):
            # Widening can only tighten the reduced universe, so this should be
            # unreachable; fall back to the raw per-release facts rather than
            # emit something unsound.
            causes = set(
                RootRequirement(requirement) for requirement in self.roots
            ) | self.used
        return frozenset(self._minimise(causes))

    def _widened(self):
        """Fold per-release facts into one fact per contiguous run of releases."""
        groups = {}
        for fact in self.used:
            groups.setdefault((fact.package, fact.requirement), []).append(fact)

        widened = set()
        for (package, requirement), facts in groups.items():
            published = list(self.client.versions(package))
            carrying = set()
            for fact in facts:
                for version in published:
                    if fact.versions.contains(version):
                        carrying.add(version)
            positions = sorted(published.index(version) for version in carrying)
            contiguous = positions == list(range(positions[0], positions[-1] + 1))
            complete = all(
                self.client.have_dependencies(package, published[index])
                for index in range(positions[0], positions[-1] + 1)
            )
            if not (contiguous and complete):
                widened |= set(facts)
                continue
            low, high = published[positions[0]], published[positions[-1]]
            if positions[0] == 0 and positions[-1] == len(published) - 1:
                window = ANY
            else:
                window = Range(((">=", low), ("<=", high)))
            widened.add(DependencyFact(package, window, requirement))
        return widened

    def _minimise(self, causes):
        """Drop every cited fact whose removal still leaves the proof standing."""
        kept = set(causes)
        for fact in sorted(causes, key=str):
            trial = kept - {fact}
            if not _satisfiable(self.client, trial):
                kept = trial
        return kept


# ----------------------------------------------------------------------
# satisfiability of a reduced universe -- cached data only, no round trips
# ----------------------------------------------------------------------
def _satisfiable(client, causes):
    roots = [
        fact.requirement for fact in causes if isinstance(fact, RootRequirement)
    ]
    if not roots:
        return True
    facts = [fact for fact in causes if isinstance(fact, DependencyFact)]

    owned = {}
    for fact in facts:
        owned.setdefault(fact.package, []).append(fact)

    def edges(package, version):
        return tuple(
            fact.requirement
            for fact in owned.get(package, ())
            if fact.versions.contains(version)
        )

    # Two releases the cited facts and ranges cannot tell apart are
    # interchangeable, so only one of each class needs trying. Grouping by the
    # requirements a release actually produces -- rather than by which facts
    # mention it -- is what keeps a per-release explanation cheap to check.
    packages = set(requirement.package for requirement in roots)
    for fact in facts:
        packages.add(fact.package)
        packages.add(fact.requirement.package)

    candidates = {}
    for package in sorted(packages):
        windows = [
            requirement.range for requirement in roots
            if requirement.package == package
        ] + [
            fact.requirement.range for fact in facts
            if fact.requirement.package == package
        ]
        classes = {}
        for version in client.versions(package):
            signature = (
                frozenset(edges(package, version)),
                tuple(window.contains(version) for window in windows),
            )
            classes[signature] = version
        candidates[package] = tuple(sorted(classes.values(), reverse=True))

    def search(needed, limits, decided):
        undecided = sorted(name for name in needed if name not in decided)
        if not undecided:
            return True
        name = undecided[0]
        for version in candidates.get(name, ()):
            if not all(window.contains(version) for window in limits.get(name, ())):
                continue
            child_limits = {key: list(value) for key, value in limits.items()}
            child_needed = set(needed)
            decided[name] = version
            fine = True
            for requirement in edges(name, version):
                child_limits.setdefault(requirement.package, []).append(requirement.range)
                child_needed.add(requirement.package)
                settled = decided.get(requirement.package)
                if settled is not None and not requirement.range.contains(settled):
                    fine = False
                    break
            if fine and search(child_needed, child_limits, decided):
                return True
            del decided[name]
        return False

    limits = {}
    needed = set()
    for requirement in roots:
        limits.setdefault(requirement.package, []).append(requirement.range)
        needed.add(requirement.package)
    return search(needed, limits, {})
