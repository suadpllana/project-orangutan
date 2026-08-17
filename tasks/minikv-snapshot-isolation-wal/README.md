# minikv-snapshot-isolation-wal

Rebuild a toy embedded key/value store's storage engine: snapshot-isolated
transactions, an append-only write-ahead log that survives `SIGKILL`, recovery
that degrades to a prefix of the commit history when the log is damaged, and a
crash-safe checkpoint that actually reclaims space — under a performance budget
that rules out rewriting the database on every write.

| | |
| --- | --- |
| collection family | Library clone |
| task family | `feature_development` |
| verifier family | `programmatic` |
| expert estimate | 4 hours |
| network | `none` (all phases except the image build) |
| graded tests | 117 across 7 categories |
| pass threshold | 0.85 (`[verifier] pass_threshold`) |
| oracle | **1.0000**, PASS, ~5 s |
| nop (untouched `/app`) | **0.0000**, FAIL |

## Layout

```
draft.yaml                 every draft field - the single source of the prose
submission.md              generated; paste-ready render of draft.yaml
bundle/                    exactly what gets zipped and uploaded
  task.toml                [metadata] [agent] [verifier] [environment]
  instruction.md           the problem statement + the normative specification
  environment/             the build context; COPY . /app/
    Dockerfile             python:3.11-slim + pytest; builds /app
    minikv/                the naive storage engine + transaction stubs
    public_tests/          13 visible tests - the public half of the verifier
    SPEC.md                the spec again, in the tree
    selfcheck.py           build-time assertion; deleted from the image
    README.md
  tests/                   sealed
    test.sh                the verifier entrypoint declared in task.toml
    grade.py               collection, integrity scan, category runner, reward
    test_*.py              the 117 held-out tests
    crash_child.py         the SIGKILL scenarios
  solution/
    solve.sh               the entrypoint the oracle runs
    reference/minikv/      the reference implementation
```

## Reproducing the oracle & nop stage locally

```bash
cd bundle

# oracle: install the reference into a copy of /app, then grade it
mkdir -p /tmp/app /tmp/logs && cp -r environment/minikv environment/public_tests /tmp/app/
IMPL_ROOT=/tmp/app bash solution/solve.sh
IMPL_ROOT=/tmp/app LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 1.0000, PASS

# nop: grade the untouched starting state
mkdir -p /tmp/nop && cp -r environment/minikv environment/public_tests /tmp/nop/
IMPL_ROOT=/tmp/nop LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 0.0000, FAIL

docker build -t minikv-task environment/   # unverified here: no docker daemon
```

The score lands in `$LOG_DIR/reward.txt`, `score.txt` and `score.json`.

The image build has **not** been run in this repository's authoring environment
(docker CLI present, no daemon). `environment/selfcheck.py` — the build-time
assertion that the seed is still the seed — was run directly instead, and it
passes on the starting state and correctly refuses the reference. Build the
image once before submitting.

`tests/test.sh` exits 0 only when the score reaches the 0.85 threshold, and
prints `SCORE`, `THRESHOLD` and `RESULT`.

## Design notes

The durability model is **process failure, not machine failure**. Bytes handed
to the kernel count as durable, so `flush()` suffices and no `fsync` is
required. That is deliberate: with `fsync` in the loop the performance budgets
would really be measuring the grading host's disk, and the same submission would
pass or fail depending on where it ran.

Three requirements do most of the discriminating:

* `test_begin_does_not_block_writers` is single-threaded, so the usual fake —
  one lock held from `begin()` to `commit()` — deadlocks instead of passing.
* `test_write_skew_is_allowed` fails any implementation that reaches for
  serializability, so over- and under-strictness cost the same.
* The recovery tests never look at the log format. They damage `wal.log` at
  eight truncation points and eight corruption points and assert the recovered
  state is a *prefix* of the commit history.

### Two bugs the suite caught

**In the reference.** After recovering from a truncated log it appended new
records *behind* the damaged tail, where recovery would never look again — so
the write vanished on the next reopen. `test_damaged_log_is_still_writable_afterwards`
covers it.

**In the suite itself.** `test_kill_during_checkpoint_loses_nothing` passed on
the untouched seed: the child armed a non-daemon `threading.Timer`, and when
`checkpoint()` raised `NotImplementedError` the timer still fired during
interpreter shutdown, so the process died by `SIGKILL` and the parent was
satisfied. Six free passes. The loop is now guarded and exits `96` on any
exception, which the parent treats as a scenario failure.

Both are in `docs/verifier-patterns.md` as patterns rather than anecdotes.

### Getting the nop to its floor

The first measurement put the untouched starting state at 0.1785 — all of it
credit the seed was born with rather than partial progress. Three fixes took
it to 0.0000:

* `regression` moved to weight 0, with its pass ratio multiplying the final
  score instead (the seed passes the visible suite by definition, so scoring it
  was free reward; breaking it now costs proportionally);
* four `api` tests that never touched the transactional API had a transactional
  assertion folded into each;
* the two read-throughput benchmarks now run after a `checkpoint()` and through
  a stale-snapshot transaction respectively, so they measure the new engine
  rather than a dict lookup.
