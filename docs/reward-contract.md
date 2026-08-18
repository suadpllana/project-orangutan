# The reward contract

**Every trial must produce a reward file.** A verifier that finishes without one
is reported as a verifier bug, not a submission failure, and the Oracle & nop
stage fails:

> Your verifier completed without writing a reward file
> (`verifier/reward.txt` or `reward.json`) — every trial must produce one.

This repository hit that message **twice**, on two different tasks, and the fix
written up after the first time was wrong. What follows is what actually works
and how it was established. Copy the mechanism; do not re-derive it.

---

## Read the message literally

> `verifier/reward.txt` **or** `reward.json`

Two paths. The first is **relative and carries a directory component**; the
second is **relative and carries none**. They are two paths under **one root
the message never names**.

That is the whole puzzle, and both failures came from misreading it.

| attempt | where the reward was written | outcome |
| --- | --- | --- |
| minikv, first upload | `/logs/reward.txt`, `/logs/score.json`, beside `grade.py` | rejected |
| minikv v2 → pkgsolve v1 | + `/verifier`, `/tests`, `HERE.parent`, `$PWD`, `/tmp` × `{reward,score}.{txt,json}` | **rejected again** |

The second attempt added the **absolute** `/verifier`. That satisfies
`verifier/reward.txt` only if the unnamed root happens to be `/`. It was not.

Both failing attempts had exactly one thing in common — **no `verifier/`
subdirectory under any root except `/`** — and that is the column that had never
varied. `CLAUDE.md`'s elimination method (tabulate what each attempt declared,
find the constant) is what found it; a third guess would not have.

## What works

For **every plausible root**, write the reward **both at the root and inside a
`verifier/` subdirectory of it**:

```
roots    $LOG_DIR, $REWARD_DIR, $REWARD_PATH, $REWARD_FILE, $VERIFIER_DIR,
         $OUTPUT_DIR, $OUTPUTS_DIR, $RESULTS_DIR, $RESULT_DIR, $TEST_OUTPUT_DIR,
         /logs /verifier /tests /output /outputs /results /app /workspace,
         <dir of grade.py>, its parent, $PWD, $PWD/.., /tmp /var/tmp /
  x      ""  and  "/verifier"
  x      reward.txt, reward.json, score.txt, score.json
```

They are four-byte files. There is no cost to being exhaustive and there is a
whole submission's cost to being clever.

## The five rules

1. **Publish a `0.0` floor before grading starts** — from `tests/test.sh` first,
   then again from `grade.py`. If anything after that dies, the floor is already
   on disk.
2. **Wrap the grading run in `except BaseException`** and publish on the way
   out. `SystemExit`, `KeyboardInterrupt` and `MemoryError` are not `Exception`.
3. **Never create a directory just to empty it.** `clear_stale_rewards()` must
   skip roots that do not already exist, or widening the net turns a read-only
   mount into a new failure mode.
4. **Delete stale reward artefacts before writing the floor.** The agent can
   write to `/logs`; a `reward.txt` containing `1.0` left behind before the
   verifier runs is otherwise indistinguishable from a perfect score.
5. **Print every location that accepted the file and every one that refused
   it.** Both failures above were silent, which is why the second one had to be
   reasoned about instead of read off a log.

## The three-way verification, which is not optional

Run all three with **`LOG_DIR` unset and `/logs` unwritable**, so the working
directory is the only place that will take a file. If you only test the happy
path on a machine where `/logs` exists, you are testing nothing.

```bash
B=tasks/<slug>/bundle
mkdir -p /tmp/run && cd /tmp/run

# 1. normal run
env -u LOG_DIR IMPL_ROOT=/tmp/app bash $B/tests/test.sh
cat ./verifier/reward.txt ./reward.json          # -> the real score

# 2. an exception inside grade(): the except BaseException path
#    (inject `raise RuntimeError("x")` at the top of grade(), run, revert)
cat ./verifier/reward.txt                        # -> 0.000000

# 3. SIGKILL mid-run
env -u LOG_DIR IMPL_ROOT=/tmp/nop bash $B/tests/test.sh & sleep 3; kill -9 $!
cat ./verifier/reward.txt                        # -> 0.000000
```

All three must leave both `./reward.json` and `./verifier/reward.txt`.

## The side effect: clean up after yourself

A local grader run now scatters `reward.*` files and `verifier/` directories
through the working tree — **including inside `bundle/`**. Shipping a stale
score inside the archive would be worse than the bug this fixed, so:

* `tools/build_bundle.py` skips `reward.txt`, `reward.json`, `score.txt`,
  `score.json`, `junit.xml` and any `verifier/` directory;
* `tools/check_bundle.py` warns if any survive in `bundle/`.

After a local run:

```bash
find . -not -path './.git/*' \( -name 'reward.*' -o -name 'score.*' -o -name 'junit.xml' \) -delete
find . -not -path './.git/*' -type d -name verifier -exec rm -rf {} +
```

## Checklist

- [ ] `reward_dirs()` covers every root above, each one twice (`""` and
      `"/verifier"`).
- [ ] Both `reward.txt` **and** `reward.json` are written, not just the one
      named in `[verifier] reward_file`.
- [ ] A `0.0` floor is published from `test.sh` **and** from `grade.py`, before
      any grading.
- [ ] `clear_stale_rewards()` runs before the floor and never creates a
      directory.
- [ ] The grading run is inside `except BaseException`.
- [ ] `test.sh` prints `$PWD`, the suite directory, and both the accepted and
      refused lists.
- [ ] All three scenarios verified with `LOG_DIR` unset.
- [ ] No `reward.*` or `verifier/` left inside the archive
      (`python3 tools/check_bundle.py <task>`).

`tasks/pkgsolve-resolver-explanations/bundle/tests/` is the worked
implementation of all of this.
