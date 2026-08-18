# pkgsolve-resolver-explanations

Rebuild the solver core of a package manager. Three requirements hold at once
and each rules out the cheap way of getting the others: the returned solution
must be the one a fixed alphabetical, newest-first decision procedure names — so
the search cannot be reordered by the heuristic that makes backtracking fast; an
unsolvable manifest must raise `Unsolvable` carrying facts the grader re-checks
for truth, sufficiency and minimality; and the whole call, explanation included,
must stay inside a budget of registry questions counted by a client the
submission cannot see.

| | |
| --- | --- |
| collection family | Library clone |
| task family | `feature_development` |
| verifier family | `programmatic` |
| expert estimate | 7 hours |
| network | `none` (all phases except the image build) |
| graded tests | 104 across 8 categories |
| pass threshold | 0.92 (`[verifier] pass_threshold`) |
| oracle | **1.0000**, PASS, ~1.6 s |
| nop (untouched `/app`) | **0.0000**, FAIL |
| nothing is timed | the cost metric is an integer registry-call counter |

## Layout

```
draft.yaml                 every draft field - the single source of the prose
submission.md              generated; paste-ready render of draft.yaml
bundle/                    exactly what gets zipped and uploaded
  task.toml                [metadata] [agent] [verifier] [environment]
  instruction.md           the problem statement + the normative specification
  environment/             the build context; COPY . /app/
    Dockerfile             python:3.11-slim + pytest; builds /app
    pkgsolve/              the value types (complete) + a brute-force resolver
    public_tests/          22 visible tests - the public half of the verifier
    SPEC.md                the spec again, in the tree
    selfcheck.py           build-time assertion; deleted from the image
    README.md
  tests/                   sealed
    test.sh                the verifier entrypoint declared in task.toml
    grade.py               collection, integrity scan, category runner, reward
    _support.py            the sealed registry, the ballast, the budget helpers
    _oracle.py             exhaustive enumeration + the (E1)-(E5) checker
    test_*.py              the 104 held-out tests
    determinism_child.py   the hash-seed subprocess
  solution/
    solve.sh               the entrypoint the oracle runs
    reference/pkgsolve/    the reference implementation
```

## Reproducing the oracle & nop stage locally

```bash
cd bundle

# oracle: install the reference into a copy of /app, then grade it
mkdir -p /tmp/app /tmp/logs && cp -r environment/pkgsolve environment/public_tests /tmp/app/
IMPL_ROOT=/tmp/app bash solution/solve.sh
IMPL_ROOT=/tmp/app LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 1.0000, PASS

# nop: grade the untouched starting state
mkdir -p /tmp/nop && cp -r environment/pkgsolve environment/public_tests /tmp/nop/
IMPL_ROOT=/tmp/nop LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 0.0000, FAIL

docker build -t pkgsolve-task environment/   # unverified here: no docker daemon
```

The image build has **not** been run in this repository's authoring environment
(no docker CLI, no daemon). `environment/selfcheck.py` — the build-time
assertion that the seed is still the seed — was run directly instead and passes.
Build the image once before submitting.

## Uploading

The file to upload is **`pkgsolve-resolver-explanations.zip` in this directory**
— 35 entries, `task.toml` at the archive root. Upload it exactly as it is.

```bash
python3 tools/verify_zip.py tasks/pkgsolve-resolver-explanations/pkgsolve-resolver-explanations.zip
```

Do **not** zip this directory: that buries every required path two levels down
under `pkgsolve-resolver-explanations/bundle/` and the inspector rejects it with
*"required file missing"*. Do not expand the archive and re-compress it either —
macOS puts the wrapper back and adds a `__MACOSX/` tree. `verify_zip.py` detects
both, and `--fix` repairs either one in place.

## Design notes

Nothing in this task is timed. The cost model is a count of calls to
`registry.versions()` and `registry.dependencies()`, made through an object
built from closures with `__slots__ = ()` and no data attributes, whose counter
is returned to the test and never to the resolver. That makes the performance
half of the grade an integer rather than a stopwatch, so a submission scores
identically on a loaded grading host and an idle one.

Three requirements do most of the discriminating, and they were checked against
implementations that satisfy only two of them:

| implementation | score | why it fails |
| --- | --- | --- |
| the reference | **1.0000** | — |
| correct alphabetical search, memoised, no pruning | 0.8857 | 3/7 budget |
| fast search, most-constrained package decided first | 0.8724 | 10/14 preference, 21/24 randomized |
| the untouched starting workspace | 0.0000 | everything |

Reference against the unpruned search, registry calls on the same instances:
14/371, 33/252, 42/289, 63/570, 35/384.

### Three bugs the suite caught

**In the reference, twice.** An unsound backjump: a failure recorded only the
decisions it collided with head-on, not the ones that required the failing
package at all, so a package with no usable release looked independent of the
decision that pulled it in. It reported four solvable instances as unsolvable.
And learning without restarting: a derived global constraint landed, but the
pass that derived it kept grinding through the releases the constraint had just
ruled out — 141 registry calls where 33 was available, which is the difference
between passing and failing the budget the test now sets.

**In the grader.** `_oracle.satisfiable` never checked a self-dependency against
the version being committed. Found by cross-validating it against exhaustive
enumeration on 20,000 random reduced universes; it now agrees on all of them.

### Getting the nop to its floor

The first measurement put the untouched workspace at 0.0200. Two determinism
tests were passing: one because an empty `causes` prints identically under three
hash seeds and the emptiness check was too weak, and one because it only
compared the parent's fixture against the child's and never called the resolver.
Both now fold a budgeted solve and an explanation check into the test. Every
other category is zero because every graded universe carries a small
satisfiable "ballast" component that forces real backtracking, which the
brute-force enumerator cannot afford even on a two-package case.

### A design choice worth recording

The preference law started out declarative — a lexicographic order over
solutions, with "installed" ranked above "not installed". Total, deterministic,
and impossible: computing the maximum under it requires knowing which packages
*could* appear, which means downloading the reachable universe, which is exactly
what the registry budget forbids. The two laws could not both be satisfied. The
procedural form keeps the determinism and the hostility to reordering
heuristics, and is computable lazily.
