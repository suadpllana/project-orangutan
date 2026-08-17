# Verifier patterns

Reusable mechanics for programmatic graders. Every pattern here is in
`tasks/minikv-snapshot-isolation-wal/bundle/tests/` and has been run.

---

## Collection: never execute from the submission directory

```python
def collect_package(submission, tree):
    source = submission / "minikv"
    for path in sorted(source.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "conftest.py":
            continue
        shutil.copy2(path, tree / "minikv" / path.relative_to(source))
```

Copy only implementation files into a scratch tree the grader owns, then run
there. This one decision neutralises a whole family of exploits at once: a
`conftest.py` that patches assertions, a `sitecustomize.py` that runs at
interpreter start, a `pytest.ini` that deselects tests, and any edit to the
visible test suite. State the rule in the spec ("every file you add must live
inside `pkg/`") so a legitimate solution never trips over it.

## Integrity scan: tokenise, do not grep

Grepping for `pytest` flags a docstring that says "run the tests with pytest".
Tokenising and looking only at `NAME` tokens skips comments and string literals
for free:

```python
tokens = list(tokenize.tokenize(open(path, "rb").readline))
for token in tokens:
    if token.type == tokenize.NAME and token.string in FORBIDDEN:
        ...
```

Track the previous name and whether a `.` preceded the token, so ambiguous words
only count when qualified: `stack` matters after `inspect` or `traceback`,
`modules` and `argv` after `sys`, `environ` after `os`. Verified both ways — a
`sys.modules` check trips it, a docstring mentioning `pytest`, `os.environ` and
`sys.argv` does not.

An integrity violation should zero the score outright, not cost one category.

## Isolate each category in its own process

```python
subprocess.run([sys.executable, "-m", "pytest", test_file,
                "-p", "no:cacheprovider", f"--rootdir={tree}",
                f"--confcutdir={tree}/_tests", f"--junitxml={junit}"],
               cwd=tree, env=env, timeout=timeout, capture_output=True)
```

Separate processes mean a deadlock or an infinite loop costs one category
instead of the whole run — which matters, because *forcing* a deadlock is
sometimes the point of a test. Parse JUnit XML rather than scraping stdout;
pytest's summary format is not an API.

Count `skipped` as a pass. Tests only skip when the implementation legitimately
gives them nothing to look at, and a skip that scores zero punishes a design
choice you already allowed.

## Budget the whole run, not just each part

Per-category timeouts sum to more than the harness' verifier timeout in the
worst case, and a verifier killed by the harness reports *nothing*. Give the run
a global deadline, shrink each category's limit to what is left, and mark the
rest unrun:

```python
remaining = deadline - time.monotonic()
if remaining <= 5:
    report["categories"][name] = {"skipped_no_time": True, "ratio": 0.0, ...}
    continue
outcome = run_category(tree, test_file, min(timeout, remaining))
```

Order categories cheapest-and-most-diagnostic first, so a submission that hangs
late still produces a report that explains why.

Size the deadline against the *bundle's* `[verifier] timeout_sec`, and that
against `verifierTimeoutSec` — three nested budgets, each comfortably inside the
next, and never above the form default at the outer end. minikv runs a 900 s
internal deadline inside the bundle's 1200 s `[verifier] timeout_sec`, which is
exactly `verifierTimeoutSec`'s 1200 s default. Pick the numbers from
measurements at both ends: the reference grades in ~4 s and the untouched seed —
the slowest thing that still finishes — in ~500 s. The per-category limits are
allowed to sum above the deadline; that is what the deadline is for.

## Crash testing: a child that kills itself

```python
# in the helper
def _die():
    os.kill(os.getpid(), signal.SIGKILL)

# in the test
proc = subprocess.run([sys.executable, HELPER, scenario, path], timeout=180)
assert proc.returncode == -9, "scenario did not die by SIGKILL"
```

Asserting the child died *by signal 9* is the load-bearing half. Without it, a
submission that catches the kill, forks a survivor, or exits cleanly passes the
recovery check for the wrong reason.

For "kill at an arbitrary moment", have the child arm a timer for a random delay
and then loop on the operation under test. The assertion — nothing committed was
lost — holds no matter when the axe falls, so the randomness adds coverage
without adding flakiness. Parameterise it over a handful of repetitions.

## Structural assertions beat format assertions

The recovery tests do not know the log's encoding. They damage `wal.log` and
assert the recovered state is a **prefix** of the commit history:

```python
present = sorted(int(k[1:]) for k in state)
assert present == list(range(len(present)))   # no gaps, no invented keys
```

Write the history as N single-key commits with the key encoding its own
position, then damage the file at eight truncation fractions and eight
single-byte flips. This is a strong property, it is format-agnostic, and it
catches the tempting wrong answer — resynchronising past a corrupt record —
which resurrects commits that were never made.

Pair it with the complements, or an implementation that throws the log away
passes vacuously:

* a clean reopen sees **all** N commits;
* truncating one byte leaves **strictly fewer** than N;
* the store is **still writable** after recovering from damage, and the new
  write survives another reopen.

That last one is what caught the reference implementation appending behind a
damaged tail.

## Force the design with a single-threaded test

The usual way to fake transaction isolation is one lock held from `begin()` to
`commit()`. Under a concurrent test it looks perfect. Under a *sequential* test
it deadlocks:

```python
txn = db.begin()
for i in range(50):
    db.put(f"other{i}".encode(), b"x")   # a held lock blocks forever here
assert txn.get(b"k") == b"old"           # a live view returns the new value
```

Generalise: if a wrong design is only distinguishable by timing, find the
sequence of calls where it stops making progress instead.

## Test the ceiling, not only the floor

Snapshot isolation must *allow* write skew; a serializable implementation is
wrong for this spec even though it sounds stronger. Assert it:

```python
def test_write_skew_is_allowed(db):
    t1, t2 = db.begin(), db.begin()
    t1.get(b"y"); t2.get(b"x")
    t1.put(b"x", b"0"); t2.put(b"y", b"0")
    t1.commit(); t2.commit()          # both must succeed
```

Without a test like this, "reach for the strongest-sounding guarantee" is a
winning strategy, and the grader is measuring vocabulary rather than
understanding.

## Bound resources from two sides at once

A single bound is usually satisfiable by a degenerate answer. Two bounds that
pull in opposite directions are not:

* `wal.log` ≤ 4 KiB after a checkpoint — a no-op checkpoint fails this;
* whole directory ≤ `4 * live_bytes + 65536` — copying the log into the
  checkpoint fails this;
* plus a throughput budget — checkpointing on every commit fails that.

Express the size bound relative to the *logical* data size, never as an absolute
number, so it does not encode your own encoding's constants.

## Make performance budgets robust

Give budgets roughly an order of magnitude of headroom over the reference and
make sure the naive implementation misses by more than that. minikv's reference
runs the whole performance category in 0.9 s against budgets summing to 60 s,
while the seed does not finish it at all. A budget that a correct-but-slow
submission fails on a busy grading host is a flaky test, and a flaky test in a
grader is worse than a missing one.

## Drive the nop run to the floor

The funnel runs your verifier against the *untouched* starting state and expects
it to sit at its floor. Partial credit is still wanted — but it has to be credit
for work the agent did, not credit the seed was born with. Audit this by
running the grader against a pristine `/app` and looking at every test that
passes.

Three sources of free credit, all of them found this way:

* **A regression category with weight.** Re-running the visible suite is worth
  having — breaking existing behaviour should be disqualifying — but the seed
  passes it by definition. Give it weight `0` and let its pass ratio *multiply*
  the final score: passing it earns nothing, breaking it costs proportionally,
  and the reward stays continuous instead of falling off a cliff.
* **Tests that never touch the new API.** Four `api` tests here checked the
  exception hierarchy, directory creation, size limits and the context manager —
  all true of the starting store. Folding a transactional assertion into each
  one keeps the coverage and removes the free pass.
* **A crash scenario that dies for the wrong reason.** The checkpoint-race child
  armed a `threading.Timer` and then looped on `checkpoint()`. On a store with
  no `checkpoint()` the loop raised immediately, but the non-daemon timer still
  fired during interpreter shutdown, so the process died by SIGKILL and the
  parent was satisfied. Six free passes. The fix is to guard the loop and
  `os._exit` with a status that is *not* signal 9:

  ```python
  timer = threading.Timer(delay, _die); timer.daemon = True; timer.start()
  try:
      while True:
          db.checkpoint()
  except BaseException:
      os._exit(96)          # parent asserts rc == -9, so this fails the scenario
  ```

* **Benchmarks that measure what the seed was already good at.** Two read
  throughput tests passed on the naive store, because a dict lookup is fast.
  Re-pointing them at the new engine — measure gets *after a `checkpoint()`*,
  and scans *through a stale-snapshot transaction* — kept the benchmark and
  removed the free pass, and both variants are stronger tests besides.

Weighted regression plus those three bugs put the seed at 0.1785. Fixing them
took it to 0.0000 without touching the partial-credit design for real
attempts.

## Keep the visible half honest

The review bar wants a public portion of the verifier the agent can aim at, and
a sealed portion it cannot overfit. The trap is making the visible half a
*description of the target*: then a competent agent reads it, satisfies it, and
stops. Make the visible suite describe what must **not regress** — behaviour
that already exists — and say so in the instructions, in as many words:

> The visible tests are deliberately only the floor. They describe the behaviour
> that exists today, not the behaviour this document requires. Use the
> specification, not the visible tests, as your definition of done.

Then grade against your own pristine copy of that suite, so editing it locally
changes nothing.

## Report enough to diagnose

`report.json` carries per-category pass counts, per-test failure messages,
timings, the weighted score and the binary verdict. When a batch of submissions
scores 0.45, the failure messages are the only way to tell "implemented
transactions, kept the naive persistence" apart from "broke something else".
