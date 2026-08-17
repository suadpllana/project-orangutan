# Authoring playbook

The order that actually works, learned by building
`tasks/minikv-snapshot-isolation-wal`. The short version: **the tests are the
task**. Prose is cheap to write and easy to make sound rigorous; a grader either
separates a real solution from a plausible one or it does not, and you only find
out by running it.

---

## 0. Pick a task worth grading

**It has to fit a collection family.** `Library clone`, `Product clone`,
`ML engineering`, `Algorithmic optimization` — and look like a real instance of
one, not a contrived puzzle that happens to compile. Pick the honest fit; the
corpus is balanced across them and a reviewer weighs this.

A task is a good candidate when all five hold:

1. **The finished state is objectively checkable.** Not "is the code clean" but
   "does this sequence of calls return this value". If you cannot describe the
   pass condition as a program, pick something else or accept an LLM-judge
   verifier family and a much softer score.
2. **It has interacting constraints.** One requirement is an exercise. Four
   requirements that constrain each other — correctness *and* a crash model
   *and* a size bound *and* a performance floor — is a task. Interaction is what
   makes the difficulty real rather than a matter of typing volume.
3. **The obvious shortcut is closed by a *different* requirement than the one it
   dodges.** In the minikv task, "rewrite a snapshot on every commit" satisfies
   every correctness test and dies on the throughput budget. That pairing is the
   whole design.
4. **An expert can finish it in the estimated time.** Aim for the estimate to be
   honest. Padding the scope until it is unsolvable produces a task where every
   score is zero, which measures nothing.
5. **It is self-contained.** No network, no third-party packages, no external
   services. Every dependency is a way for the score to depend on something
   other than the agent.

Anti-patterns: tasks that are mostly boilerplate; tasks with a single hidden
"aha"; tasks whose grader can only check that *some* output was produced; tasks
where the spec is ambiguous enough that a correct solution can fail.

## 1. Write `instruction.md` before you write anything else

`instruction.md` is what the agent reads, and it must be **normative and complete**: every
statement the grader checks appears in it, and nothing the grader checks is
missing from it. The test for this is simple — after you finish the hidden
suite, walk each test back to the sentence that authorises it. A test with no
sentence behind it is either a bug in the test or a gap in the spec, and in
grading it just produces noise.

Say "MUST" where you mean it. State the things that are *not* required as
explicitly as the things that are: the minikv specification says multi-process access is
out of scope and that `data.json` is not part of the contract, and both of those
saved the agent from defending against a test that does not exist.

**State your failure model.** minikv's durability is process failure
(`SIGKILL`), not machine failure, so `flush()` suffices and `fsync` is not
required. This is not a detail: with `fsync` in the write path, the throughput
budgets would have been measuring the grading host's disk, and the same
submission would pass or fail depending on where it ran.

## 2. Build the seed workspace

`environment/` becomes `/app`, and its Dockerfile has to bake in every
dependency — the rollout has no network. Put a build-time self-check in the
Dockerfile: assert the starting state passes its own visible tests *and* that
the thing being asked for is still missing, so a seed that accidentally ships a
working implementation fails at build rather than at the oracle stage.

The starting point should be **working code that is honestly inadequate**, not a
pile of stubs. minikv starts with a real store that rewrites the whole file on
every write: correct, obviously naive, and O(n) per write. That gives the agent
something to read, a test suite to keep green, and a clear direction.

Give the agent the exception classes and the method signatures it will need —
guessing your API names is not the skill being measured. Have the stubs raise
`NotImplementedError` so nothing silently half-works.

Ship the **visible half of the verifier** here too: a test suite covering what
already works. The review bar asks for a visible/hidden split, and this is it.
Say in `instruction.md` that the visible suite is the floor, not the target,
otherwise a competent agent satisfies it and stops.

## 3. Write the hidden suite

Group tests into categories that map onto capabilities, because that is what
partial credit will be reported in. For each category ask: *what wrong
implementation does this catch?* If you cannot name one, the test is decoration.

Techniques worth reusing are collected in `verifier-patterns.md`. The four that
mattered most here:

* **Force the real design with a single-threaded test.** A lock held for a
  transaction's lifetime looks like isolation under any concurrent test. Open a
  transaction, write through the store, then read through the transaction, all
  on one thread: the fake deadlocks, the real thing answers.
* **Test the ceiling as well as the floor.** Snapshot isolation must *allow*
  write skew. Asserting that a stronger-sounding algorithm fails is what stops
  "reach for the strongest guarantee" from being a winning strategy.
* **Assert structural properties, not byte layouts.** The recovery tests do not
  know the log format. They damage the file and assert the recovered state is a
  *prefix* of the commit history. That is a strong property, it is
  format-agnostic, and it leaves the author free to design the encoding.
* **Kill the process for real.** A helper `SIGKILL`s itself; the parent asserts
  the child died with signal 9 and then reopens the database. Nothing that runs
  in `close()`, `atexit` or `__del__` can save a submission.

## 4. Write the oracle — and expect it to fail

Write the reference solution *after* the tests, and run it. The minikv reference
failed two tests on its first full run. One was a bug in a test (arithmetic in a
prefix). **The other was a real bug in the reference**: after recovering from a
truncated log it appended new records behind the damaged tail, where recovery
would never look again. That bug would have shipped as a "correct" oracle, and
every agent that got it right would have looked wrong.

If your oracle passes on the first run, be suspicious of the tests, not pleased
with yourself.

## 5. Run the grader against the seed

This reproduces the funnel's **oracle & nop** stage, and both ends have to land
where the stage expects: the reference at (near) full reward, the untouched
starting state **at its floor**.

The first run here scored the seed at 0.1785, and every point of it was free
credit rather than partial progress — a weighted regression category the seed
passes by definition, four API tests that never touched the new interface, a
crash scenario that passed for the wrong reason, and two benchmarks measuring
reads the naive store was already fast at. `verifier-patterns.md` has the audit
and the fixes; the seed now scores 0.0000. Do that audit by reading the list of tests the seed
*passes*, one by one, and asking what work each of them credits.

Driving the nop to zero is not in tension with partial credit. Partial credit is
for intermediate states of a real attempt; the seed is not an attempt.

Then grade at least one *deliberately wrong* variant — a plausible mistake, not
a stub — and check it lands where you expect.

## 6. Harden the grader

Assume the submission is adversarial, then make cheating structurally
impossible rather than merely forbidden:

* Copy only implementation files into a scratch tree the grader owns; never run
  anything from inside the submission directory.
* Keep your own copy of the visible tests, so editing them locally does nothing.
* Drop `conftest.py` from what you collect, and run pytest with `--rootdir`,
  `--confcutdir` and `-p no:cacheprovider`.
* Scan the collected source for test-runner and environment introspection —
  tokenised, so that comments and docstrings do not false-positive.
* Run each category as its own process with its own timeout, and give the run as
  a whole a deadline, so a hang costs one category instead of the report.
* Parse results from JUnit XML, not from stdout.

Everything you defend against goes in ANTICIPATED EXPLOITS with the
countermeasure next to it. That field is a design record, not a brainstorm: each
entry should name the exploit *and* the thing that stops it.

## 7. Fill in `draft.yaml`, then validate and package

Keep every field's prose in `draft.yaml` — it is the single source — and
regenerate `submission.md`:

```bash
python3 tools/validate_draft.py --all      # bounds, enums, resource floors
python3 tools/check_bundle.py --all        # structure + quality gates, cross-checks
python3 tools/render_submission.py --all
python3 tools/build_bundle.py --all        # dist/<slug>.zip
```

Write the fields last, when the numbers in them are facts you measured rather
than intentions. `verificationStrategy` should describe the verifier you ran,
including the visible/hidden split; `partialScoreStrategy` should predict scores
you can back up; `difficultyExplanation` has to convince the difficulty probe
and a reviewer, so name the specific traps rather than reaching for adjectives.

Then submit: fill the draft, request an upload URL, push the ZIP. Passing
inspection submits the task automatically — there is no separate submit button.
`docs/submission-funnel.md` covers what runs next.

## 8. The pre-submit check

Run through `quality-checklist.md`. The three that catch the most:

* Does the reference actually reach full reward *from a clean build*?
* Does the untouched starting state sit at its floor?
* Does every hidden test trace back to a sentence in `instruction.md`?
* Do the per-category timeouts sum to less than `verifierTimeoutSec`?
