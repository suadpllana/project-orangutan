# pkgsolve

The dependency resolver behind the build farm. Pure standard library, no
network.

```
pkgsolve/
  errors.py         the exception hierarchy - stable public API
  versions.py       Version      - complete
  ranges.py         Range        - complete
  requirements.py   Requirement, RootRequirement, DependencyFact - complete
  registry.py       Registry protocol + InMemoryRegistry - complete
  solver.py         resolve()    - the naive enumerator, and the job
public_tests/       22 visible tests covering what already works
SPEC.md             the normative specification
```

```bash
python -m pytest public_tests -q
```

`SPEC.md` is the contract. The visible tests are the floor, not the target:
they describe today's behaviour, and the graded suite is much larger.

Known state, from the issue tracker:

* **#118 `Unsolvable` has nothing in `causes`.** Users get "no solution" with no
  reason. The two fact types the explanation is supposed to be built from are
  already defined in `requirements.py`; nothing produces them.
* **#131 the resolver is quadratic in registry traffic.** `solver.py` downloads
  every version of every reachable package, then re-downloads dependency lists
  once per candidate assignment. The staging registry rate-limits us out on
  anything bigger than a toy manifest.
