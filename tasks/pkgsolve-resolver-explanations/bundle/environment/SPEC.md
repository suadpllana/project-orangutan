<!-- The normative specification, identical to the second half of the task
     instructions. This copy lives in the workspace so it is available from
     inside /app. -->

# pkgsolve v1.0 specification

This section is the contract. It is normative: the grader tests these statements
and nothing else. Where it says MUST, a test asserts it.

## 1. The data model

These four types are already implemented. Their behaviour is part of the
contract because the grader constructs them and compares against them, but you
should not need to change them.

### 1.1 `Version`

A release is exactly three non-negative integers: `Version(major, minor, patch)`.
`Version.parse("1.2.3")` accepts three dot-separated decimal components with no
leading zeros (`"0"` itself is fine) and raises `InvalidVersion` otherwise;
a non-`str` argument raises `TypeError`. Versions order and compare
component-wise, are hashable and immutable, and `str(Version(1, 2, 3))` is
`"1.2.3"`.

There are no pre-release identifiers, no build metadata and no epochs.

### 1.2 `Range`

A range is a **conjunction** of comparators over versions, parsed from a string:

```
Range.parse("*")                    every version
Range.parse(">=1.2.0,<2.0.0")       both comparators must hold
Range.parse("==1.0.0")              exactly one version
Range.parse("!=1.1.0")              every version except one
```

The operators are `==`, `!=`, `>=`, `>`, `<=`, `<`. Comparators are separated by
commas and are ANDed; whitespace around them is ignored. The empty string and
`"*"` both mean "any version". Anything else raises `InvalidRange`. There is no
`||`, no `~`, no `^`.

`Range.contains(version)` is the only semantic operation. `Range` is immutable
and hashable; two ranges are equal when their comparator sets are equal, which
is a **syntactic** test — `Range.parse(">=1.0.0")` and `Range.parse(">0.9.9")`
are different objects even where they accept the same versions.

### 1.3 `Requirement`

`Requirement(package, range)` — a package name and a `Range`. Package names
match `[a-z][a-z0-9]*(-[a-z0-9]+)*`; anything else raises `ValueError`, and a
non-`str` name or non-`Range` range raises `TypeError`. `Requirement.parse("foo
>=1.0.0,<2.0.0")` is a convenience constructor. `Requirement` is immutable and
hashable.

## 2. The registry

The resolver is handed the universe through a `Registry` object. It has exactly
two methods:

```python
registry.versions(package)              -> tuple[Version, ...]
registry.dependencies(package, version) -> tuple[Requirement, ...]
```

* `versions(package)` returns every published version of `package`, **sorted
  ascending**. An unknown package returns the empty tuple.
* `dependencies(package, version)` returns that release's requirements, in
  declaration order. It MUST only be called with a `version` that
  `versions(package)` returned for that `package`; any other call raises
  `LookupError`.
* A release may declare more than one requirement on the same package. They all
  apply — the effective range is their intersection.
* Both methods are pure: the same arguments always return the same answer during
  one `resolve()` call.
* The object the grader passes is **not** an instance of `pkgsolve.Registry`.
  It is duck-typed: do not `isinstance`-check it, and do not subclass-dispatch
  on it.

**This is the only way the resolver may learn anything about the universe.** It
MUST NOT read attributes of the registry object, walk function closures,
globals, frames or the garbage collector, or import the grader's modules. The
grader's registry stores nothing on the instance, and the grader scans your
source for this; see §8.

## 3. `resolve(registry, requirements)`

```python
from pkgsolve import resolve
solution = resolve(registry, [Requirement.parse("app >=1.0.0")])
# -> {"app": Version(2, 1, 0), "runtime": Version(1, 4, 0), ...}
```

* `requirements` is an iterable of `Requirement`. A non-iterable argument, or an
  element that is not a `Requirement`, MUST raise `TypeError`. Validation
  happens **before** any registry call.
* An empty requirement list MUST return an empty `dict` and MUST make no
  registry calls at all.
* Several root requirements MAY name the same package; they all apply.
* The return value is a `dict` mapping package name (`str`) to `Version`.

### 3.1 What makes an assignment valid

A `dict` `S` is a **valid solution** for root requirements `R` when all three
hold:

1. **Root satisfaction** — for every `r` in `R`, `r.package` is in `S` and
   `r.range.contains(S[r.package])`.
2. **Dependency satisfaction** — for every package `p` in `S` and every
   requirement `d` in `registry.dependencies(p, S[p])`, `d.package` is in `S`
   and `d.range.contains(S[d.package])`.
3. **Exact closure** — `S` contains *no other* packages. Formally `set(S)` is
   the smallest set that contains every `r.package` for `r` in `R` and, for each
   `p` in the set, every `d.package` for `d` in
   `registry.dependencies(p, S[p])`.

Rule 3 is a MUST in both directions: a solution that omits a required package is
wrong, and so is one that includes a package nothing asked for.

Dependency **cycles are legal** (`a` requires `b`, `b` requires `a`), including
a package that requires itself. They MUST resolve normally.

### 3.2 The preference law

There is usually more than one valid solution. Exactly one of them is correct,
and this procedure names it:

```python
decided = {}
needed  = {r.package for r in requirements}

while needed - set(decided):
    package = min(needed - set(decided))              # ascending name order
    for version in reversed(registry.versions(package)):      # newest first
        if <decided + {package: version} extends to a valid solution>:
            decided[package] = version
            needed |= {d.package for d in registry.dependencies(package, version)}
            break
    else:
        raise Unsolvable(...)
return decided
```

In one sentence: **take the packages in alphabetical order as they are
discovered, and give each one the newest release that still leaves the manifest
solvable.** The procedure is total and deterministic, so "the preferred
solution" is well defined for every input, and `resolve()` MUST return exactly
it however it computes it.

Two consequences worth stating outright, because both are tested:

* **The decision order is part of the answer, not an implementation detail.**
  Deciding packages in a different order — fewest releases first, most
  constrained first, or the order the registry happened to reveal them — very
  often produces a *valid* solution that is not this one. Efficiency has to come
  from pruning branches that provably cannot succeed, never from reordering the
  decisions.
* **A package is only a candidate once something needs it.** `needed` grows as
  releases are chosen, so a package whose name sorts early can still be decided
  late.

**Worked example 1 — newest first.**

```
root:   app *
app:    1.0.0 (no dependencies)
        2.0.0 -> util >=1.0.0
util:   1.0.0, 1.1.0
```

`app` is decided first and takes `2.0.0`, which is completable. That makes
`util` needed, and it takes `1.1.0`. Answer: `{"app": 2.0.0, "util": 1.1.0}`.

**Worked example 2 — alphabetical order beats a better-looking heuristic.**

```
root:   aa *, zz *
aa:     1.0.0 -> zz *
        2.0.0 -> zz *
        3.0.0 -> zz <=1.0.0
zz:     1.0.0, 2.0.0
```

`aa` sorts first, so it is decided first, and `3.0.0` is completable (`zz`
`1.0.0` satisfies it). Answer: `{"aa": 3.0.0, "zz": 1.0.0}`.

A resolver that decides `zz` first — the package with fewest releases, which is
the usual heuristic and the fast one — takes `zz 2.0.0` and is then forced down
to `aa 2.0.0`. `{"aa": 2.0.0, "zz": 2.0.0}` is a perfectly valid solution and it
is the wrong answer.

**Worked example 3 — discovery order.**

```
root:   mid *
mid:    1.0.0 -> aaa *
aaa:    1.0.0, 2.0.0
```

Only `mid` is needed at the start, so `mid` is decided first even though `aaa`
sorts before it. Answer: `{"aaa": 2.0.0, "mid": 1.0.0}`.

### 3.3 Failure

When no valid solution exists, `resolve()` MUST raise `Unsolvable`. It MUST NOT
return `None`, an empty dict, or a partial assignment, and it MUST NOT raise
`Unsolvable` for an instance that has a solution.

## 4. The explanation law

`Unsolvable` carries `causes`, a `frozenset` of **facts** that together prove
the instance has no solution. There are exactly two kinds of fact, both already
defined in `pkgsolve.requirements`:

```python
RootRequirement(requirement)
    # "the caller asked for `requirement`"

DependencyFact(package, versions, requirement)
    # "every version of `package` inside `versions` requires `requirement`"
```

Let `C` be `causes`. Define the **reduced universe** `U(C)`: the same packages
with the same version lists, but

* the root requirements are only `{f.requirement for f in C if isinstance(f, RootRequirement)}`, and
* the dependencies of `(p, v)` are only
  `tuple(f.requirement for f in C if isinstance(f, DependencyFact) and f.package == p and f.versions.contains(v))`.

`causes` MUST satisfy all four conditions:

* **(E1) Well-typed.** Every element is a `RootRequirement` or a
  `DependencyFact`.
* **(E2) Rooted in the request.** Every cited `RootRequirement.requirement` is
  equal to one of the requirements passed to `resolve()`.
* **(E3) True.** Every cited `DependencyFact(p, R, req)` is *implied by the
  registry*: for every version `v` of `p` with `R.contains(v)`, the requirements
  of `(p, v)` that name `req.package` are non-empty, and every version of
  `req.package` that satisfies all of them also satisfies `req.range`. Citing a
  weaker requirement than the registry declares is allowed — `>=1.0.0` where the
  registry says `>=2.0.0` is true and therefore legal. Citing a range of
  versions of `p` that do not all carry the dependency is not.
* **(E4) Sufficient.** `U(C)` has no valid solution. Because every cited fact is
  true of the real universe, this is a proof that the real instance has none
  either.
* **(E5) Minimal.** For every `f` in `C`, `U(C - {f})` **does** have a valid
  solution. No cited fact may be redundant.

Any set satisfying (E1)–(E5) is accepted; there is no single expected answer and
the grader never compares `causes` against a fixed value.

An empty `causes` fails (E4): with no root requirements the empty solution is
valid.

**Worked example 3.**

```
root:    alpha *, beta *
alpha:   1.0.0 -> shared >=2.0.0
         1.1.0 -> shared >=2.0.0
beta:    1.0.0 -> shared <2.0.0
         1.1.0 -> shared <2.0.0
shared:  1.0.0, 2.0.0
```

A conforming `causes`:

```python
frozenset({
    RootRequirement(Requirement.parse("alpha *")),
    RootRequirement(Requirement.parse("beta *")),
    DependencyFact("alpha", Range.parse("*"), Requirement.parse("shared >=2.0.0")),
    DependencyFact("beta",  Range.parse("*"), Requirement.parse("shared <2.0.0")),
})
```

Sufficient: in `U(C)` both `alpha` and `beta` are required, every version of each
carries its half of the contradiction, and no version of `shared` is both
`>=2.0.0` and `<2.0.0`. Minimal: drop any one of the four and a solution appears.

Note what is *not* citable. "No version of `shared` satisfies both" is not a
fact — version lists are always fully present in `U(C)`, so unavailability is
already true there. And citing the individual releases
(`DependencyFact("alpha", Range.parse("==1.0.0"), ...)` and one for `1.1.0`)
would satisfy (E1)–(E4) but fail (E5) only if one of them were redundant; here
neither is, so that four-into-six expansion is also accepted. Coarse facts are
easier to keep minimal, not mandatory.

## 5. The query budget

The graded suite calls `resolve()` with its own `Registry` and **counts every
call** to `versions()` and `dependencies()`, repeats included.

* Every graded instance carries a budget. Each budget is at least **five times**
  the number of calls the reference implementation makes on that same instance,
  and is checked with `assert calls <= budget`.
* A run that reaches **twenty times** the budget is aborted by the harness with
  an exception that is not an `Exception` subclass. Do not write a bare
  `except BaseException` around your search; you will convert a budget failure
  into a wrong answer and lose the correctness marks too.
* Budgets apply to failing instances as well as solvable ones, and cover the
  work of producing `causes`.
* `resolve()` MUST hold no state between calls. A second call with the same
  arguments MUST make the same number of registry calls as the first (§6), so a
  cache that outlives a call is a test failure, not an optimisation.

The starting implementation misses every graded budget, by roughly 7x on the
smallest instances and by more than four orders of magnitude on the largest.
Closing that gap needs three things, and the budgets are set so that all three
are necessary -- a correct search that memoises but never prunes was measured
missing four of the seven budget instances by between 1.5x and 26x:

1. **Memoise within the call.** Asking the registry the same question twice is
   pure waste.
2. **Do not explore a subtree until the choice that introduces it is still
   viable.** The naive resolver materialises the whole reachable universe before
   it decides anything.
3. **Generalise a conflict beyond the version that exposed it.** Rediscovering
   the same contradiction once per candidate version is what makes the search
   quadratic in the version counts; deriving it as a statement about a *range*
   of versions — the same shape as a `DependencyFact` — is what makes it linear.

Point 3 is also what makes §4 affordable: an explanation assembled from facts
the search already derived costs nothing extra, while re-deriving one by
deleting candidate facts and re-solving costs another full search each time.

## 6. Determinism and purity

* `resolve()` is a pure function of the registry's contents and the requirement
  list.
* Calling it twice in one process with equal arguments MUST return equal results
  **and** make the same number of registry calls.
* Results MUST NOT depend on `PYTHONHASHSEED`. A test runs the same instance in
  two subprocesses started with different hash seeds and compares the returned
  solution and, for failures, the `causes` set. Iterating a `set` of package
  names without sorting is the usual way to fail this.
* `resolve()` MUST NOT mutate the requirement list it is given. (The values
  themselves are immutable, so there is nothing else to protect.)

## 7. What is out of scope

Stated as explicitly as the requirements, because none of it is tested and none
of it should be built:

* Pre-release, build-metadata, epoch or wildcard versions; `^`, `~`, `||` in
  ranges; extras, features, optional dependencies, platform markers, yanked
  releases.
* Any notion of "already installed", upgrades, or lock files.
* Concurrency. `resolve()` is called from one thread at a time and is never
  required to be thread-safe or re-entrant.
* Persistence. Nothing is written to disk; no file format is part of the
  contract.
* Human-readable rendering of `causes`. The grader inspects the objects, never a
  string. `__str__` on `Unsolvable` may say anything.
* Performance in wall-clock terms. Nothing is timed; the only cost model is the
  registry call count in §5. (Each graded category still has a generous
  wall-clock cap so that a hang costs one category rather than the run.)

## 8. Implementation constraints

* Python 3.11 standard library only. No third-party packages and no network —
  the sandbox has neither.
* **Every file you add or change must live inside `/app/pkgsolve/`.** Grading
  copies `pkgsolve/**/*.py` into a clean tree and imports it from there;
  anything you leave outside that directory — including `conftest.py`,
  `sitecustomize.py`, `pytest.ini`, or edits to `public_tests/test_public.py` —
  is discarded before the graded tests run.
* The resolver must not read the environment, the process tree, the call stack,
  the garbage collector, function closures or module globals to decide how to
  behave, and must not name the test runner. The grader tokenises your source
  and scores **zero** if it finds any of it.
* `pkgsolve.__init__` must keep exporting `resolve`, `Registry`,
  `InMemoryRegistry`, `Requirement`, `RootRequirement`, `DependencyFact`,
  `Range`, `Version`, `Unsolvable`, `InvalidVersion`, `InvalidRange` and
  `PkgSolveError`. The grader imports all of them from the package root.
* You may add modules inside `pkgsolve/`, delete `solver.py`'s body, restructure
  freely — only the public names above are fixed.
