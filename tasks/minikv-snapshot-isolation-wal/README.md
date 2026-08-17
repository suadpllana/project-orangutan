# minikv-snapshot-isolation-wal

Rebuild a toy key/value store's storage engine: snapshot-isolated transactions,
an append-only write-ahead log that survives `SIGKILL`, recovery that degrades
to a prefix of the commit history when the log is damaged, and a crash-safe
checkpoint that actually reclaims space — under a performance budget that rules
out rewriting the database on every write.

| | |
| --- | --- |
| task family | feature development |
| verifier family | programmatic |
| expert estimate | 4 hours |
| network | none |
| graded tests | 117 across 7 categories |
| reference score | 1.0000 (binary pass) |
| unmodified-seed score | 0.1785 (binary fail) |

## Layout

```
task.yaml                  every authoring-form field, ready to paste
submission.md              the same content rendered for review
environment/
  Dockerfile               python:3.11-slim + pytest, builds the agent image
  workspace/               exactly what the agent starts from
    minikv/                the package (naive storage engine + stubs)
    tests/test_basic.py    13 visible tests that must keep passing
    SPEC.md                the normative specification
    README.md
solution/
  minikv/                  the reference implementation (the oracle)
verifier/
  run_verifier.sh          harness entry point
  grade.py                 collection, integrity scan, per-category runner
  tests/                   the 117 graded tests + the crash helper
```

## Running it locally

```bash
# the reference implementation must score 1.0
python3 verifier/grade.py --submission solution --out /tmp/oracle.json

# the starting point must score well below it, and must not pass
python3 verifier/grade.py --submission environment/workspace --out /tmp/seed.json

# build the agent image (also self-checks the starting point)
docker build -t minikv-task environment/
```

`grade.py` exits 0 only when the binary success condition is met.

## Design notes

The one thing worth knowing before reading the code: the specification's
durability model is **process failure, not machine failure**. Bytes handed to
the kernel count as durable, so `flush()` suffices and no `fsync` is required.
That is deliberate — with `fsync` in the loop the performance budgets would
really be measuring the grading host's disk, and the same submission would pass
or fail depending on where it ran.

Two requirements do most of the discriminating work:

* `test_begin_does_not_block_writers` is single-threaded, so the usual fake —
  one lock held from `begin()` to `commit()` — deadlocks instead of passing.
* `test_write_skew_is_allowed` fails any implementation that reaches for
  serializability, so both over- and under-strictness are penalised.

The reference implementation had a real bug the suite caught: after recovering
from a truncated log it appended new records *behind* the damaged tail, where
recovery would never look again. `test_damaged_log_is_still_writable_afterwards`
covers it.
