"""Build-time assertion that the starting state is the starting state.

Run from /app during the image build and then deleted, so the agent never sees
it. A seed that accidentally ships a working implementation is a task with no
gap, and this is the cheapest place to find that out.
"""

from pkgsolve import InMemoryRegistry, Registry, Requirement, Unsolvable, Version, resolve


class Counter(Registry):
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def versions(self, package):
        self.calls += 1
        return self.inner.versions(package)

    def dependencies(self, package, version):
        self.calls += 1
        return self.inner.dependencies(package, version)


def main():
    # The parts that already work: the preference law on a toy universe.
    registry = InMemoryRegistry({
        "app": {"1.0.0": [], "2.0.0": ["util >=1.0.0"]},
        "util": {"1.0.0": [], "1.1.0": []},
    })
    solution = resolve(registry, [Requirement.parse("app *")])
    assert solution == {"app": Version(2, 0, 0), "util": Version(1, 1, 0)}, solution

    # The first part the task is about: failures must be explained, and are not.
    unsolvable = InMemoryRegistry({
        "alpha": {"1.0.0": ["shared >=2.0.0"]},
        "beta": {"1.0.0": ["shared <2.0.0"]},
        "shared": {"1.0.0": [], "2.0.0": []},
    })
    try:
        resolve(unsolvable, [Requirement.parse("alpha *"), Requirement.parse("beta *")])
    except Unsolvable as error:
        assert not error.causes, "the starting resolver must not explain anything yet"
    else:
        raise SystemExit("the starting resolver must still fail on this instance")

    # The second part: registry traffic must still be absurd. Four chained
    # packages, twenty releases in total, and the naive enumerator spends more
    # than fifty round trips per release working its way down to the answer.
    names = ["pa", "pb", "pc", "pd"]
    counts = [6, 6, 6, 2]
    data = {}
    for index, (name, count) in enumerate(zip(names, counts)):
        data[name] = {}
        for major in range(1, count + 1):
            follows = []
            if index + 1 < len(names):
                follows.append("%s >=%d.0.0" % (names[index + 1], major))
            data[name]["%d.0.0" % major] = follows
    chained = Counter(InMemoryRegistry(data))
    answer = resolve(chained, [Requirement.parse("pa *")])
    assert answer == {name: Version(2, 0, 0) for name in names}, answer
    assert chained.calls > 800, (
        "the starting resolver is supposed to be wasteful, spent only %d calls"
        % chained.calls
    )

    print("selfcheck: starting state is intact (%d calls for 20 releases)" % chained.calls)


if __name__ == "__main__":
    main()
