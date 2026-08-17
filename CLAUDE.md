# Project Orangutan — task authoring

Orangutan collects self-contained software-engineering tasks that a frontier
coding agent works on autonomously and that are graded objectively by a sealed
verifier. Authoring one means producing two things:

* a **draft** — structured metadata describing the task (`draft.yaml` here);
* a **task bundle** — a ZIP in the Terminal-Bench / Harbor format holding the
  actual environment, verifier and reference solution (`bundle/` here).

Read this file first. `docs/` has the details; `docs/submission-funnel.md`
describes what happens after you submit and what the reviewer is looking for.

---

## Repository layout

```
CLAUDE.md                  this file
README.md                  orientation
docs/
  draft-fields.md          the draft: fields, bounds, enums
  bundle-format.md         the ZIP: required paths, task.toml, network phases
  submission-funnel.md     two-phase submission, the funnel stages, the review bar
  authoring-playbook.md    the end-to-end process, in order
  verifier-patterns.md     reusable grader mechanics, all of them run
  exploit-catalog.md       how agents game graders, and what stops each
  quality-checklist.md     the pre-submit checklist
templates/
  draft.template.yaml      starting point for a new draft
tools/
  new_task.py              scaffold a task directory + bundle skeleton
  validate_draft.py        bounds, enums, resource floors and ceilings
  check_bundle.py          the structure + quality gates, run locally
  build_bundle.py          package dist/<slug>.zip
  render_submission.py     regenerate submission.md from draft.yaml
tasks/<slug>/
  draft.yaml               every draft field - the single source of the prose
  submission.md            generated; paste-ready render of draft.yaml
  README.md                orientation + measured numbers
  bundle/                  exactly what gets zipped and uploaded
    task.toml
    instruction.md         the problem statement + the normative specification
    environment/           becomes /app; Dockerfile + the starting workspace
    tests/                 test.sh + the sealed grader and held-out suite
    solution/              solve.sh + the reference implementation
```

One task exists: `tasks/minikv-snapshot-isolation-wal`. Read it before writing a
new one — it is the worked example every doc in `docs/` refers to.

## Commands

```bash
python3 tools/new_task.py <lowercase-kebab-slug>     # scaffold
python3 tools/validate_draft.py --all                # draft bounds and enums
python3 tools/check_bundle.py --all                  # structure + quality gates
python3 tools/render_submission.py --all             # regenerate submission.md
python3 tools/render_submission.py --all --check     # fail if stale
python3 tools/build_bundle.py --all                  # dist/<slug>.zip

# reproduce the funnel's oracle & nop stage
cp -r tasks/<slug>/bundle/environment/<workspace files> /tmp/app
APP_DIR=/tmp/app bash tasks/<slug>/bundle/solution/solve.sh
SUBMISSION_DIR=/tmp/app bash tasks/<slug>/bundle/tests/test.sh     # oracle: 1.0
SUBMISSION_DIR=/tmp/pristine bash tasks/<slug>/bundle/tests/test.sh # nop: floor
```

`tests/test.sh` exits 0 only when the binary success condition is met, and
prints `REWARD <score>` and `BINARY_PASS <true|false>`.

## Conventions

* **`draft.yaml` is the single source of the prose.** `submission.md` is
  generated from it. Never edit `submission.md`; regenerate it.
* **The directory name equals `workingSlug`.** The validator enforces it.
* **Field names in `draft.yaml` match the draft form exactly** (camelCase:
  `workingSlug`, `collectionFamily`, `expertTimeEstimateHours`, …) so there is
  no translation step when pasting.
* **`bundle/` is exactly what gets zipped.** Nothing outside it is uploaded, so
  anything the harness needs must live there.
* **Write the draft fields last**, when their numbers are measurements rather
  than intentions.
* Only `notes` and `schema_version` in `draft.yaml` are not form fields.

---

## The ten rules

Ordered by how much grief each one saves.

**1. Read the guideline before you build anything.** This repository was first
built from screenshots of the draft form after the guideline URL returned 403,
and the result had the right task inside the wrong container: no `task.toml`, no
`instruction.md`, entrypoints under invented names, `/workspace` instead of
`/app`, and `taskFamily: "feature development"` where the enum wanted
`feature_development`. The content survived the correction; the packaging and
half the metadata did not. If a source you were pointed at is unreachable, stop
and say so — do not infer a spec you were told exists.

**2. The tests are the task.** Prose is cheap to write and easy to make sound
rigorous. A grader either separates a real solution from a plausible one or it
does not, and the only way to find out is to run it against both. The spec and
the grader are the work; the draft fields are the write-up.

**3. Write the hidden tests before the reference solution.** Then run the
reference against them and expect it to fail. The minikv reference failed two
tests on its first full run — one was a bug in a test, and **one was a real bug
in the reference**: after recovering from a truncated log it appended new
records behind the damaged tail, where recovery would never look again. That
would have shipped as a "correct" oracle. If your oracle passes first try,
suspect the tests.

**4. Both ends of the oracle & nop stage have to land.** The reference must
reach (near) full reward. The untouched starting state must sit **at its floor**
— and free credit is easy to ship by accident. Audit it by listing every test
the seed *passes* and asking what work each one credits. Here that found four
things: a weighted regression category the seed passes by definition; four API
tests that never touched the new interface; a crash scenario that passed because
a non-daemon timer fired during interpreter shutdown after the operation under
test had already raised; and two throughput benchmarks measuring reads the naive
store was already fast at. Together: 0.1785 of unearned reward, now 0.0000.

**5. Partial credit is for attempts, not for the seed.** Continuous, monotone
scoring makes a task far more useful than an all-or-nothing gate, so keep it —
but earn it. Weight the categories that measure new capability, and give
"did not break what already worked" weight zero, letting its pass ratio multiply
the result — free reward removed, cliff avoided.

**6. Close the obvious shortcut with a different requirement than the one it
dodges.** In minikv, "rewrite a snapshot on every commit" satisfies every
correctness test and dies on the throughput budget. Interacting constraints are
what make difficulty real instead of a matter of typing volume. A task whose
requirements are independent is a checklist, not a problem.

**7. Force the design, don't just check the output.** The usual way to fake
transaction isolation is one lock held from `begin()` to `commit()`, and it
looks perfect under any concurrent test. A *single-threaded* test that
interleaves outside writes deadlocks the fake and answers correctly for the real
thing. Generalise: if a wrong design is only distinguishable by timing, find the
call sequence where it stops making progress instead.

**8. Test the ceiling as well as the floor.** Snapshot isolation must *allow*
write skew, so a serializable implementation is wrong for that spec even though
it sounds stronger. Without a test asserting the permitted anomaly is permitted,
"reach for the strongest-sounding guarantee" is a winning strategy and the
grader is measuring vocabulary. Every negative assertion also needs a positive
twin: "no corrupt data appears" is satisfied by an empty database.

**9. Assert structural properties, not byte layouts.** The recovery tests do not
know the log format. They damage the file and assert the recovered state is a
*prefix* of the commit history — no gaps, no invented entries, every value
checked against its key. Strong, format-agnostic, and it leaves the author free
to design the encoding. Size bounds get the same treatment: `≤ 4 * live_bytes +
65536`, never an absolute number that encodes your own constants.

**10. Make cheating structurally impossible, not merely forbidden.** Copy only
implementation files into a scratch tree the grader owns and run there; that one
decision kills `conftest.py` injection, `sitecustomize.py`, `pytest.ini`
deselection and edits to the visible tests, all at once. Then forbid it in
`instruction.md` *as well*, so a legitimate solution never trips a defence it
was not warned about. `docs/exploit-catalog.md` has the full table.

---

## Three things that are easy to get wrong

**A grader that gets killed reports nothing.** Per-category timeouts sum to more
than `verifierTimeoutSec` in the worst case, so give the run a global deadline,
shrink each category's limit to what remains, and order categories
cheapest-and-most-diagnostic first. A hang must cost one category, never the
report.

**State the failure model in the spec.** minikv's durability is process failure
(`SIGKILL`), not machine failure, so `flush()` suffices and `fsync` is not
required. That is not a detail: with `fsync` in the write path, the throughput
budgets would have been measuring the grading host's disk, and the same
submission would pass or fail depending on where it ran. Any budget you set is
implicitly a claim about what the machine does; make the claim explicit.

**Every hidden test must trace back to a sentence in `instruction.md`.** Walk
the list before submitting. A test with no sentence behind it is either a bug in
the test or a gap in the spec, and in grading it is indistinguishable from
noise. The converse too: every MUST needs a test, or it is decoration.

---

## Known gaps

* `https://project-orangutan-guideline.edgeone.dev/` is blocked by this
  environment's egress policy (403 on CONNECT). The docs here were reconciled
  against the guideline text pasted into the session on 2026-08-17. If the
  guideline changes, re-reconcile rather than trusting these files.
* `[environment] network_mode = "open"` in `task.toml` is the build phase, which
  the guideline says is not gated — but the accepted value there is the one
  thing in the bundle that could not be checked against a published enum. It is
  flagged in the task's `notes`.
* The rubric judge's criteria are known only in outline (clarity, specification
  completeness, whether the verifier measures the objective, anti-gaming
  adequacy). `docs/quality-checklist.md` targets them from that outline.
