# Build `incremental`: a demand-driven incremental computation engine

You are working in `/app`. Your job is to finish the `incremental` package so
that it behaves *exactly* as the specification below describes.

```
/app
â”œâ”€â”€ incremental/          <- the package you must implement
â”‚   â”œâ”€â”€ __init__.py       (public re-exports; already written)
â”‚   â””â”€â”€ engine.py         (exception classes are done, everything else raises
â”‚                          NotImplementedError)
â”œâ”€â”€ public_tests/         <- a small visible subset of the checks
â”‚   â””â”€â”€ test_public.py
â””â”€â”€ SPEC.md               <- the same specification you are reading now
```

Run the visible tests with:

```bash
cd /app && python -m pytest public_tests -q
```

Python 3.12, standard library only, no network. `pytest` is installed for your
convenience but your package must not depend on it.

**What actually makes this hard.** Returning correct values is the easy half.
The sealed grader instruments every query body it registers and asserts the
*exact* multiset of executions after each operation, so an engine that
recomputes a node it did not have to â€” or skips one it did have to â€” fails even
though every value it returns is right. Read Â§3.5 carefully: it is the contract
you are being measured against, and the difference between comparing a
dependency's `changed_at` against a node's `verified_at` (correct) and against
its `changed_at` (a bug that only shows up after an early cutoff) is worth real
points.

The visible tests are a floor, not the bar. The grader additionally runs
randomly generated query graphs and edit sequences against an independent model
of Â§3.5, exercises `save`/`load`, 20,000-deep chains, and execution budgets on a
graph of several thousand nodes.

---

# `incremental` â€” a demand-driven incremental computation engine

## 1. What you are building

`/app/incremental/` is a Python package that must provide a **memoizing,
demand-driven incremental computation engine**: the query-engine core that sits
underneath a modern build system or a language server (Salsa in rust-analyzer,
Skyframe in Bazel, the query system in `rustc`).

You describe a computation as a graph of **inputs** (mutable cells that the
outside world writes) and **derived queries** (pure functions that read inputs
and call other queries). When an input changes, asking for a derived value again
must recompute *only what genuinely needs recomputing* â€” and nothing else.

The skeleton in `incremental/engine.py` declares every public name. The
exception classes are finished; the rest is yours. You may add modules, rename
internals, and restructure the package freely, as long as the public names in
`incremental/__init__.py` keep working and the semantics below hold exactly.

The whole point of this task is the *exactness* of the recomputation. A version
that returns correct values but recomputes too much (or too little) is wrong,
and the grader measures it directly by counting how many times your engine
invokes each query body.

---

## 2. Public API

Everything below is importable as `from incremental import ...`.

### 2.1 Exceptions

| Name | Meaning |
| --- | --- |
| `IncrementalError` | base class of all the errors below |
| `CycleError` | a query re-entered a node that was already being computed |
| `InputNotSetError` | an input key was read while not set; has attribute `.key` |
| `QueryNotRegisteredError` | a query name was used that was never registered; has attribute `.name` |
| `CacheFormatError` | `Engine.load()` was pointed at something that is not a usable cache file |

`CycleError` carries `.cycle`: a `list` of `(query_name, args_tuple)` pairs. The
first element is the node that was re-entered, followed by the rest of the cycle
in call order; the first element is **not** repeated at the end. A self-cycle
`a -> a` therefore gives `[("a", ())]`, and `a -> b -> c -> a` requested at `a`
gives `[("a", ()), ("b", ()), ("c", ())]`.

### 2.2 `Query`

The handle returned when a function is registered. It exposes `.name` (the
registered name) and `.fn` (the undecorated function). It is not callable.

### 2.3 `Engine`

```python
Engine()                      # a fresh engine: revision 0, no inputs, empty cache
```

**Registration**

```python
engine.query(fn)                       # -> Query, name = fn.__name__
engine.query(name="parse")             # -> decorator, returns Query
```

Usable bare (`@engine.query`) or parameterised (`@engine.query(name="...")`).
Registering a second query under a name already in use raises `ValueError`.

**Inputs** â€” input keys are `str`; values are arbitrary Python objects.

```python
engine.set_input(key, value)   # None
engine.remove_input(key)       # True if it was set, False otherwise
engine.has_input(key)          # bool
engine.get_input(key)          # value, or raises InputNotSetError
engine.revision                # int, read-only property
```

`set_input` with a non-`str` key raises `TypeError`.

**Evaluation**

```python
engine.get(query, *args)       # query: a Query handle or a query name (str)
```

Brings the node up to date and returns its value, or raises the exception the
node's body raised.

**Introspection**

```python
engine.stats()  # {"executions": int, "nodes": int, "revision": int, "inputs": int}
```

* `executions` â€” total number of query-body invocations this `Engine` object has
  performed. Starts at 0 and only ever increases (except that `load()` resets it).
* `nodes` â€” number of derived nodes currently held in the memo cache.
* `revision` â€” same value as `engine.revision`.
* `inputs` â€” number of input keys currently set.

**Durability**

```python
engine.save(path)   # write the whole engine state to a single file
engine.load(path)   # replace this engine's state with the saved one
```

### 2.4 The query context

Each execution of a query body receives a fresh context object as its first
positional argument:

```python
@engine.query
def total(ctx, group):
    a = ctx.input("count:" + group)      # read an input, recording a dependency
    b = ctx.call(base, group)            # call another query, recording a dependency
    return a + b
```

* `ctx.input(key)` â€” returns the input's value, or raises `InputNotSetError`.
  **The dependency is recorded either way**, so a later `set_input` for that key
  invalidates this node.
* `ctx.call(query, *args)` â€” evaluates another query (bringing it up to date
  first) and returns its value. If that node's outcome is an exception, the
  exception is raised here and therefore propagates into the calling body.
  `query` may be a `Query` handle or a query name.

The class of the context object is not part of the API â€” only these two methods
are.

---

## 3. Semantics (normative)

### 3.1 Node identity

A derived node is identified by `(query_name, args)`, where `args` is the tuple
of positional arguments. Arguments must be hashable; passing an unhashable
argument raises `TypeError`. Two calls with equal arguments address the same node.

### 3.2 Revisions

The engine holds a global integer `revision`, starting at `0`.

* `set_input(key, value)` where `key` is **not** currently set: `revision += 1`,
  and the key's `changed_at` becomes the new revision.
* `set_input(key, value)` where the key **is** set: the engine compares the new
  value with the stored one using `==` (coerced with `bool()`; if `==` raises,
  treat the values as different). If they compare equal the call is a **no-op** â€”
  the revision does not move and nothing is invalidated. Otherwise the value is
  replaced, `revision += 1`, and the key's `changed_at` becomes the new revision.
* `remove_input(key)` for a set key: the key is deleted, `revision += 1`, and the
  key's `changed_at` becomes the new revision (so nodes that read it are
  invalidated and will raise `InputNotSetError` when re-executed). For an unset
  key it is a no-op returning `False`.

An input key that has never been set has `changed_at == 0`.

### 3.3 Dependency recording

While a query body executes, the engine records, **in the order first
requested**, the dependencies that body touched: input keys via `ctx.input` and
derived nodes via `ctx.call`. Repeats are recorded once, at the position of the
first request.

Each execution **replaces** the node's dependency list; it never merges with the
previous one. A node that stops reading an input must stop being invalidated by
that input.

### 3.4 Memoized state

Each memoized node stores its outcome (a value **or** an exception), its
dependency list, and two revision stamps:

* `changed_at` â€” the revision at which this node's outcome last actually changed;
* `verified_at` â€” the revision at which this node was last confirmed up to date.

### 3.5 The verification algorithm

This is the contract the grader measures. `ensure(N)` at global revision `R`:

```
ensure(N):
    if N is on the current execution stack:
        raise CycleError(<stack from N's first occurrence to the top>)

    if N has no memo:
        return execute(N)

    if N.verified_at == R:
        return N                       # nothing to check, no dependency walk

    for D in N.deps, in recorded order:
        if D is an input key:
            d_changed = changed_at(D)          # 0 if never set
        else:
            ensure(D)                          # bring the dependency up to date
            d_changed = D.changed_at
        if d_changed > N.verified_at:
            return execute(N)                  # stop at the FIRST changed dep
    N.verified_at = R
    return N                                   # "green": no re-execution

execute(N):
    run N's body with a fresh context, capturing either a value or an exception
    new_deps  = the dependencies recorded during that run
    if N had a memo and the new outcome equals the old outcome:
        N.changed_at stays where it was        # early cutoff
    else:
        N.changed_at = R
    N.verified_at = R
    N.deps = new_deps
```

Consequences the grader relies on, and which you must honour exactly:

* **Early cutoff.** If a dependency is re-executed but produces an equal
  outcome, its `changed_at` does not move, so its own dependents are marked
  green without being re-executed. Changes stop propagating where values stop
  changing.
* **Stop at the first changed dependency.** Verification examines dependencies
  in recorded order and stops as soon as one reports a change. Dependencies
  after that point are *not* brought up to date during this verification, so
  they may not be executed at all.
* **`verified_at`, not `changed_at`, is the reference.** Comparing a
  dependency's `changed_at` against the node's own `changed_at` produces
  spurious re-executions after an early cutoff; the grader detects that.
* **Demand-driven.** A `get` may only touch nodes reachable from the requested
  node. Asking for one node must never execute or verify an unrelated subgraph.
* **At most once per `get`.** Within a single top-level `get` call, no node is
  executed more than once and no node's dependency list is walked more than once.
* Freshly computed nodes get `changed_at = verified_at = R`, so a node computed
  during the very same `get` as its dependencies is not immediately stale.

### 3.6 Outcome equality

Two outcomes are equal when:

* both are values and `bool(old == new)` is true (if `==` raises, they are
  **not** equal); or
* both are exceptions of exactly the same type whose `.args` compare equal.

A value and an exception are never equal.

### 3.7 Errors

If a query body raises an exception (other than `CycleError`), the engine
memoizes that exception as the node's outcome, together with the dependencies
recorded before the raise. Subsequent `get`/`ctx.call` on that node re-raise the
memoized exception object without re-running the body, until normal invalidation
says otherwise. Error outcomes take part in early cutoff exactly like values:
re-executing a node that raises `ValueError("boom")` again does **not** move its
`changed_at`, so its dependents stay green.

### 3.8 Cycles

`CycleError` is **never** memoized, and no node that is part of the cycle is left
in the cache. Nodes below the cycle that completed normally stay cached. After
the cycle is removed (by changing an input so the offending `ctx.call` no longer
happens), evaluation must succeed normally.

`CycleError` propagates out through the bodies it passes; do not treat it as a
memoizable outcome.

### 3.9 Re-entrancy

`Engine.get`, `set_input`, `remove_input`, `save` and `load` must not be called
while a query body is executing; each raises `RuntimeError` if it is. Inside a
body, use `ctx.call` and `ctx.input`.

### 3.10 Miscellaneous

* Passing a `Query` handle that belongs to a different `Engine` to `get` or
  `ctx.call` raises `ValueError`.
* Passing a query name that was never registered raises
  `QueryNotRegisteredError`; passing something that is neither a `Query` nor a
  `str` raises `TypeError`.
* The engine is single-threaded; it does not need to be thread-safe.
* Values are handed out by reference. The grader never mutates a value it
  received, and you need not copy anything.

---

## 4. Durability

```python
engine.save(path)
engine.load(path)
```

`save` writes the engine's **entire** state â€” revision counter, input values and
their `changed_at` stamps, and every memoized node with its outcome,
dependencies, `changed_at` and `verified_at` â€” into the single file at `path`.
The on-disk format is entirely your choice. Query *functions* are not saved; only
their names.

`load` replaces the engine's inputs, revision and memo cache with the saved
state, keeping the query registrations the receiving engine already has, and
resets `stats()["executions"]` to `0`.

The requirement that makes this interesting:

> After `Engine.load()`, an engine whose queries are registered under the same
> names must behave **exactly** as the saving engine did â€” including
> incrementality. If nothing changed since the save, a `get` for an
> already-memoized node must perform **zero** executions.

Additional rules:

* A saved node whose query name is not registered in the loading engine is
  dropped. Any node that depends, directly or transitively, on a dropped node is
  dropped as well; no dangling dependency may survive.
* `load` on a file that is missing raises `OSError`. `load` on a file that
  exists but is not a valid cache (truncated, garbage bytes, a cache written in
  some other format) raises `CacheFormatError`.
* `save` must not corrupt or delete an already-existing file at `path` if it
  fails part-way through.
* Memoized values, memoized exceptions, query arguments and input values used
  with `save` may be assumed to be `pickle`-able.

---

## 5. Robustness

* **Deep graphs.** `engine.get` must handle dependency chains at least
  **20,000** levels deep â€” a query that `ctx.call`s the next one, 20,000 times â€”
  without raising `RecursionError`, both on the initial computation and on later
  re-verification. Whatever you do about this must leave the interpreter in the
  state it found it (do not permanently change global interpreter settings).
* **Wide graphs.** Graphs with tens of thousands of nodes must be practical:
  re-verification after a single input change is expected to be proportional to
  the reachable graph, and re-execution proportional to what actually changed.

---

## 6. Environment constraints

* Python 3.12, **standard library only**. No network at any point. Do not add
  third-party dependencies.
* Everything the grader touches is imported from the `incremental` package in
  `/app`.
* `pytest` is installed so you can run the public tests.

---

## 7. How you are graded

The grader is sealed and is **not** in the image. It imports your package,
builds its own query graphs with its own instrumentation (each query body it
registers records the fact that it ran), and checks values *and* the exact
multiset of executions after every operation. `stats()["executions"]` is
cross-checked against what the grader observed, so reporting a number that does
not match reality fails rather than helps.

Scoring is continuous and weighted:

| Category | Weight | What it covers |
| --- | --- | --- |
| `api_basics` | 0.08 | registration, `get`, memoization, `stats`, argument and handle validation |
| `invalidation` | 0.14 | no-op `set_input`, dirty propagation, `remove_input`, unrelated-subgraph isolation |
| `early_cutoff` | 0.16 | exact execution counts where a change stops propagating |
| `dynamic_deps` | 0.08 | dependency sets that grow and shrink between executions |
| `errors_cycles` | 0.12 | memoized exceptions, error cutoff, `CycleError` contents, recovery |
| `durability` | 0.14 | `save`/`load` round-trip preserving incrementality, dropping, bad files |
| `deep_chain` | 0.05 | 20,000-deep chains, first computation and re-verification |
| `performance` | 0.08 | wall-clock and execution budgets on a large graph |
| `randomized` | 0.15 | randomly generated graphs and edit sequences, differentially compared against a model of Â§3.5 |

The final score is the weighted sum. **The task counts as solved when the total
score is at least 0.85.**

A representative â€” but deliberately much smaller and easier â€” subset of the
checks ships with the image at `/app/public_tests/`. Passing all of it is
necessary, nowhere near sufficient, and it does not include the randomized
differential suite, the performance budgets, or most of the exact-count cases.

```bash
cd /app && python -m pytest public_tests -q
```
