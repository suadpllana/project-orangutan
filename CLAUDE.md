# Project Orangutan — task authoring

This repository holds AI-training tasks: each one is a coding problem an agent
attempts inside a sandbox, plus a programmatic grader that scores the attempt.
Authoring a task means writing all four parts — the environment the agent starts
in, the specification it works from, a reference solution, and the grader — and
then filling in an authoring form that describes them.

Read this file first. `docs/authoring-playbook.md` is the long version.

---

## Repository layout

```
CLAUDE.md                  this file
README.md                  orientation
docs/
  form-schema.md           the authoring form: fields, limits, defaults
  authoring-playbook.md    the end-to-end process, in order
  verifier-patterns.md     reusable grader mechanics, all of them run
  exploit-catalog.md       how agents game graders, and what stops each
  quality-checklist.md     the pre-submit checklist
templates/
  task.template.yaml       starting point for a new task.yaml
tools/
  new_task.py              scaffold a task directory
  validate_task.py         check task.yaml against the form's rules
  render_submission.py     regenerate submission.md from task.yaml
tasks/<slug>/
  task.yaml                every form field - the single source of the prose
  submission.md            generated; paste-ready render of task.yaml
  README.md                orientation + measured numbers
  environment/
    Dockerfile             builds the agent image
    workspace/             exactly what the agent starts from
      SPEC.md              the normative specification
      tests/               visible tests that must keep passing
  solution/                the reference implementation (the oracle)
  verifier/
    run_verifier.sh        harness entry point
    grade.py               collection, integrity scan, category runner
    tests/                 the hidden graded suite
```

One task exists: `tasks/minikv-snapshot-isolation-wal`. Read it before writing
a new one — it is the worked example every doc in `docs/` refers to.

## Commands

```bash
python3 tools/new_task.py <lowercase-kebab-slug>     # scaffold
python3 tools/validate_task.py --all                 # limits, slug, layout
python3 tools/render_submission.py --all             # regenerate submission.md
python3 tools/render_submission.py --all --check     # fail if stale

python3 tasks/<slug>/verifier/grade.py \
    --submission tasks/<slug>/solution --out /tmp/oracle.json
python3 tasks/<slug>/verifier/grade.py \
    --submission tasks/<slug>/environment/workspace --out /tmp/seed.json

docker build -t <slug> tasks/<slug>/environment/
```

`grade.py` exits 0 only when the binary success condition is met.

## Conventions

* **`task.yaml` is the single source of the prose.** `submission.md` is
  generated from it. Never edit `submission.md`; regenerate it.
* **The directory name equals `working_slug`.** The validator enforces it.
* **`collection_family` stays blank in the file.** It is a dropdown whose option
  list is not reproducible offline; pick it in the form. The validator warns,
  which is expected and is the only warning a finished task should have.
* **Write the form fields last**, when their numbers are measurements rather
  than intentions.
* **Mark unverified claims as unverified.** Parts of the form schema are
  inferred from screenshots; `docs/form-schema.md` labels each line. Do not
  quietly upgrade an inference into a fact.

---

## The nine rules

These are what the first task actually taught. They are ordered by how much
grief each one saves.

**1. The tests are the task.** Prose is cheap to write and easy to make sound
rigorous. A grader either separates a real solution from a plausible one or it
does not, and the only way to find out is to run it against both. Budget your
time accordingly: the spec and the grader are the work, the form fields are the
write-up.

**2. Write the hidden tests before the reference solution.** Then run the
reference against them and expect it to fail. The minikv reference failed two
tests on its first full run — one was a bug in a test, and **one was a real bug
in the reference**: after recovering from a truncated log it appended new
records behind the damaged tail, where recovery would never look again. That
would have shipped as a "correct" oracle, and every agent that got it right
would have been scored wrong. If your oracle passes first try, suspect the
tests.

**3. Measure the gap, at both ends.** The reference must score 1.0000 and pass;
the untouched seed must score well below and fail. Both numbers go in the task
README. minikv: 1.0000 versus 0.1785. If the seed scores 0.0, the categories are
too coarse to show partial progress; if the two are close, the grader is not
discriminating. Then grade a deliberately-wrong variant and check it lands where
you predicted.

**4. Close the obvious shortcut with a different requirement than the one it
dodges.** In minikv, "rewrite a snapshot on every commit" satisfies every
correctness test and dies on the throughput budget. Interacting constraints are
what make difficulty real instead of a matter of typing volume. A task whose
requirements are independent is a checklist, not a problem.

**5. Force the design, don't just check the output.** The usual way to fake
transaction isolation is one lock held from `begin()` to `commit()`, and it
looks perfect under any concurrent test. A *single-threaded* test that
interleaves outside writes deadlocks the fake and answers correctly for the real
thing. Generalise: if a wrong design is only distinguishable by timing, find the
call sequence where it stops making progress instead.

**6. Test the ceiling as well as the floor.** Snapshot isolation must *allow*
write skew, so a serializable implementation is wrong for that spec even though
it sounds stronger. Without a test asserting the permitted anomaly is permitted,
"reach for the strongest-sounding guarantee" is a winning strategy and the
grader is measuring vocabulary. Every negative assertion also needs a positive
twin: "no corrupt data appears" is satisfied by an empty database.

**7. Assert structural properties, not byte layouts.** The recovery tests do not
know the log format. They damage the file and assert the recovered state is a
*prefix* of the commit history — no gaps, no invented entries, every value
checked against its key. Strong, format-agnostic, and it leaves the author free
to design the encoding. Size bounds get the same treatment: `≤ 4 * live_bytes +
65536`, never an absolute number that encodes your own constants.

**8. Make cheating structurally impossible, not merely forbidden.** Copy only
implementation files into a scratch tree the grader owns and run there; that one
decision kills `conftest.py` injection, `sitecustomize.py`, `pytest.ini`
deselection and edits to the visible tests, all at once. Then forbid it in the
spec *as well*, so a legitimate solution never trips a defence it was not warned
about. `docs/exploit-catalog.md` has the full table.

**9. A grader that gets killed reports nothing.** Per-category timeouts sum to
more than `verifier_timeout_s` in the worst case, so give the run a global
deadline, shrink each category's limit to what remains, and order categories
cheapest-and-most-diagnostic first. A hang must cost one category, never the
report.

---

## Two things that are easy to get wrong

**State the failure model in the spec.** minikv's durability is process failure
(`SIGKILL`), not machine failure, so `flush()` suffices and `fsync` is not
required. That is not a detail: with `fsync` in the write path, the throughput
budgets would have been measuring the grading host's disk, and the same
submission would pass or fail depending on where it ran. Any budget you set is
implicitly a claim about what the machine does; make the claim explicit.

**Every hidden test must trace back to a sentence in `SPEC.md`.** Walk the list
before submitting. A test with no sentence behind it is either a bug in the test
or a gap in the spec, and in grading it is indistinguishable from noise. The
converse too: every MUST needs a test, or it is decoration.

---

## Known gaps

* **The authoring guideline at
  `https://project-orangutan-guideline.edgeone.dev/` is blocked by this
  environment's egress policy** (403 on CONNECT). Everything in `docs/` is
  derived from screenshots of the authoring UI plus the experience of building
  the first task. If you can reach the guideline, reconcile it against
  `docs/form-schema.md` and this file, and mark what changed.
* Dropdown option lists — `collection_family`, and the non-default options for
  `task_family`, `verifier_family` and `network.mode` — are not known. The
  values in `tools/validate_task.py` are guesses and warn rather than error.
* No min/max bounds are shown for the resource fields; the bounds in the
  validator are sanity rails, not transcribed limits.
