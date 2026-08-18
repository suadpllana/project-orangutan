# Project Orangutan — task authoring

Orangutan collects self-contained software-engineering tasks that a frontier
coding agent works on autonomously and that are graded objectively by a sealed
verifier. Authoring one means producing two things:

* a **draft** — structured metadata describing the task (`draft.yaml` here);
* a **task bundle** — a ZIP in the Terminal-Bench / Harbor format holding the
  actual environment, verifier and reference solution (`bundle/` here).

## Read these two things before you write anything

1. **`docs/guideline.md`** — the official authoring guideline, verbatim. Every
   rule, bound and enum comes from there. Where any doc in this repository
   disagrees with it, the guideline wins and the doc is the bug.
2. **`reference/approved/incremental-memo-engine/`** — a bundle that was
   *approved*. It is the only ground truth here for what the platform actually
   accepts. Read its `task.toml`, `tests/test.sh`, `tests/grade.py` and
   `solution/solve.sh` before writing your own, and copy the shape. Guessing
   this schema instead of reading it cost this repository four rejected uploads.

Then this file, then `docs/`. `docs/submission-funnel.md` describes what happens
after you submit and what the reviewer is looking for.

---

## Repository layout

```
CLAUDE.md                  this file
README.md                  orientation
reference/
  approved/                a bundle that passed - the schema ground truth
docs/
  guideline.md             the official guideline, verbatim - read first
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
mkdir -p /tmp/app /tmp/logs
cp -r tasks/<slug>/bundle/environment/<starter files> /tmp/app/
IMPL_ROOT=/tmp/app bash tasks/<slug>/bundle/solution/solve.sh
IMPL_ROOT=/tmp/app LOG_DIR=/tmp/logs bash tasks/<slug>/bundle/tests/test.sh
IMPL_ROOT=/tmp/pristine LOG_DIR=/tmp/logs bash tasks/<slug>/bundle/tests/test.sh
```

`tests/test.sh` writes the score to `$LOG_DIR/reward.txt` and exits 0 only at or
above `[verifier] pass_threshold`, printing `SCORE`, `THRESHOLD` and `RESULT`.
The oracle must reach full reward; the untouched starting state must sit at its
floor.

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

## After every fix, ship the artifact

A fix that only exists in the repository has not been delivered. Whenever you
change anything under `tasks/<slug>/bundle/` — the grader, the spec, `task.toml`,
the environment, the reference — finish the job:

```bash
python3 tools/validate_draft.py --all
python3 tools/check_bundle.py --all
python3 tools/render_submission.py --all
python3 tools/build_bundle.py --all        # rebuilds dist/<slug>.zip
```

then **re-verify the oracle**, commit, push, and **hand the rebuilt
`dist/<slug>.zip` back to the user in the same reply, quoting the `sha256:`
fingerprint `build_bundle.py` prints**. Every send has the same filename, so
without the fingerprint neither of you can tell which one was uploaded — and a
stale upload looks exactly like a fix that did not work. `dist/` is gitignored and
the session container is ephemeral, so the ZIP is not recoverable from the repo
— if you do not send the file, the user has nothing to upload and the fix is
worthless to them. Say in one line what changed and whether the draft needs
editing too.

This is not optional and it is not "if they ask". Two rejections in this
repository were round-trips that a rebuilt attachment would have closed in one.

---

## The fourteen rules

Ordered by how much grief each one saves.

**1. Read the guideline before you build anything.** This repository was first
built from screenshots of the draft form after the guideline URL returned 403,
and the result had the right task inside the wrong container: no `task.toml`, no
`instruction.md`, entrypoints under invented names, `/workspace` instead of
`/app`, and `taskFamily: "feature development"` where the enum wanted
`feature_development`. The content survived the correction; the packaging and
half the metadata did not. If a source you were pointed at is unreachable, stop
and say so — do not infer a spec you were told exists.

**2. Check the artifact you are shipping, not the directory it came from.** The
first upload of the minikv bundle was rejected at inspection for "required file
missing" with all five required files present — one directory too deep, because
`build_bundle.py` wrapped the archive in a `<slug>/` directory. Every check in
this repository looked at `bundle/` on disk and passed. The required paths are
relative to the **archive root**; the guideline's `my-task/` diagram is the
directory whose contents you zip. `build_bundle.py` now re-opens the ZIP and
asserts the five paths before reporting success.

**3. Ask the bundle for less than the draft on *every* field it declares.**
Timeouts and resources alike: `14000` against a 14400 s draft, `600` against
1200, `cpus = 1` against 2000 cpuMillis, `memory_mb = 2048` against 4096. The
one exception is `gpus`, which stays equal at 0 because it cannot go lower — and
that exception is also the proof that the rule cannot be strict everywhere.

This one cost three uploads. Bundles whose resources exactly *equalled* the
draft were rejected as "resource declaration mismatch" three times while every
other field varied between attempts — `[environment] network_mode` present then
absent, `dockerfile`/`build_context` absent then present, timeouts equal then
below. Equality on the resources is the only thing all three had in common. An
approved bundle ships `cpus = 2 / 4096 / 8192`, which looks like a
counterexample, but you only ever see its *bundle*: its draft may well have
declared a larger envelope, and reasoning from the half you can see is what sent
me back and forth. **Declare what the task actually needs, measure to prove it
(`taskset -c 0` for a one-core claim), and leave the draft as the envelope
above it.**

**4. The draft you submitted is not the draft in your repo.** Intake compares
every number in `task.toml` against the draft the platform *stored*, which you
cannot read back from here. The minikv bundle was rejected with "verifier
timeout exceeds draft" while `draft.yaml` and `task.toml` both said 2400 — the
form had kept its 1200 default, so the raise never reached the platform and the
bundle asked for double. Note that equality is fine (`gpuCount: 0` versus
`gpus = 0` passes, so the comparison cannot be strict); the failure mode is
purely a bundle that asks for more than the *stored* draft allows. So: keep the
bundle's asks at or below the **form defaults** — 2000 cpuMillis, 4096 MB,
8192 MB, 0 GPUs, 14400 s agent, **1200 s verifier** — unless you have confirmed
the raised value saved. Both validators now warn when you go above a default.

**5. Copy the schema from an approved bundle; never infer it.** `task.toml`'s
shape is not derivable from the guideline prose. An approved bundle showed that
`[environment]` declares `dockerfile` and `build_context` and **no**
`network_mode` — the extra key is what "resource declaration mismatch" means;
that `[metadata]` carries `title`, `difficulty`, `expert_time_estimate_hours`,
`version` and the three families in `snake_case` (`library_clone`, not
`Library clone`); and that `[verifier]` declares `entrypoint`, `reward_file` and
`pass_threshold`, which the grader has to honour by writing
`/logs/reward.txt` and exiting 0 only at or above the threshold. `docs/bundle-format.md`
has the whole file. Every one of those was a guess before, and two of the
guesses were rejections.

**6. The tests are the task.** Prose is cheap to write and easy to make sound
rigorous. A grader either separates a real solution from a plausible one or it
does not, and the only way to find out is to run it against both. The spec and
the grader are the work; the draft fields are the write-up.

**7. Write the hidden tests before the reference solution.** Then run the
reference against them and expect it to fail. The minikv reference failed two
tests on its first full run — one was a bug in a test, and **one was a real bug
in the reference**: after recovering from a truncated log it appended new
records behind the damaged tail, where recovery would never look again. That
would have shipped as a "correct" oracle. If your oracle passes first try,
suspect the tests.

**8. Both ends of the oracle & nop stage have to land.** The reference must
reach (near) full reward. The untouched starting state must sit **at its floor**
— and free credit is easy to ship by accident. Audit it by listing every test
the seed *passes* and asking what work each one credits. Here that found four
things: a weighted regression category the seed passes by definition; four API
tests that never touched the new interface; a crash scenario that passed because
a non-daemon timer fired during interpreter shutdown after the operation under
test had already raised; and two throughput benchmarks measuring reads the naive
store was already fast at. Together: 0.1785 of unearned reward, now 0.0000.

**9. Partial credit is for attempts, not for the seed.** Continuous, monotone
scoring makes a task far more useful than an all-or-nothing gate, so keep it —
but earn it. Weight the categories that measure new capability, and give
"did not break what already worked" weight zero, letting its pass ratio multiply
the result — free reward removed, cliff avoided.

**10. Close the obvious shortcut with a different requirement than the one it
dodges.** In minikv, "rewrite a snapshot on every commit" satisfies every
correctness test and dies on the throughput budget. Interacting constraints are
what make difficulty real instead of a matter of typing volume. A task whose
requirements are independent is a checklist, not a problem.

**11. Force the design, don't just check the output.** The usual way to fake
transaction isolation is one lock held from `begin()` to `commit()`, and it
looks perfect under any concurrent test. A *single-threaded* test that
interleaves outside writes deadlocks the fake and answers correctly for the real
thing. Generalise: if a wrong design is only distinguishable by timing, find the
call sequence where it stops making progress instead.

**12. Test the ceiling as well as the floor.** Snapshot isolation must *allow*
write skew, so a serializable implementation is wrong for that spec even though
it sounds stronger. Without a test asserting the permitted anomaly is permitted,
"reach for the strongest-sounding guarantee" is a winning strategy and the
grader is measuring vocabulary. Every negative assertion also needs a positive
twin: "no corrupt data appears" is satisfied by an empty database.

**13. Assert structural properties, not byte layouts.** The recovery tests do not
know the log format. They damage the file and assert the recovered state is a
*prefix* of the commit history — no gaps, no invented entries, every value
checked against its key. Strong, format-agnostic, and it leaves the author free
to design the encoding. Size bounds get the same treatment: `≤ 4 * live_bytes +
65536`, never an absolute number that encodes your own constants.

**14. Make cheating structurally impossible, not merely forbidden.** Copy only
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

## SOLVED: "resource declaration mismatch" — ask for strictly less

`tasks/minikv-snapshot-isolation-wal` was rejected at intake **four times** with
`Bundle rejected: resource declaration mismatch`. The fix, confirmed by the
bundle then clearing **Bundle structure** and **Similarity screening**:

> **`[environment]` must ask for strictly LESS than the draft's
> `resourceEstimate` — not equal to it.** `gpus` is the sole exception and stays
> at `0`, because it cannot go lower.

```toml
# draft: cpuMillis 2000, memoryMb 4096, storageMb 8192, gpuCount 0
[environment]
cpus = 1            # not 2
memory_mb = 2048    # not 4096
storage_mb = 4096   # not 8192
gpus = 0            # equal is fine here, and only here
```

The guideline's "may ask for less, never more" turns out to mean *less*, and
that reading applies to the resources exactly as it already visibly applied to
the timeouts. Declare what the task genuinely needs and prove it — the minikv
suite was re-run pinned to one core with `taskset -c 0` (117/117, every budget
met) before claiming `cpus = 1`.

### How it was found, which is the transferable part

Three fixes had already been tried and had not moved the error. Instead of
guessing a fourth, tabulate what each rejected upload actually declared and look
for the variable that never varied:

| attempt | `[environment]` shape | timeouts | resources |
| --- | --- | --- | --- |
| 1 | `network_mode = "open"`, no `dockerfile`/`build_context` | equal | **equal** |
| 2 | `network_mode` removed, `dockerfile`+`build_context` added | below | **equal** |
| 3 | same as 2 | below | **equal** |

Everything changed between attempts except the resources. The `[environment]`
shape and both timeout relationships had each been tested in two configurations
and were therefore exonerated; equality on the resources was the only constant.
**When several fixes in a row do not move an error, stop proposing causes and
start eliminating them: the answer is the column you never changed.**

### The trap that cost the extra attempts

`reference/approved/incremental-memo-engine/task.toml` declares
`cpus = 2 / memory_mb = 4096 / storage_mb = 8192`, which looks like proof that
equality is accepted — and on that basis a correct strictly-below build was
reverted before it was ever uploaded. **You only ever see an approved
submission's bundle, never its draft.** Its draft almost certainly declared a
larger envelope, exactly as its `timeout_sec = 14000` sits below a stated 14400.
Never reason from half of an artifact pair as though you had both.

### Confirmed at intake

Bundle structure ✅ · Similarity screening ✅ · Oracle & nop — running at the time
of writing. Everything downstream of intake (the rubric judge, the difficulty
probe, human review) is still unproven for this task.

## Known gaps

* `https://project-orangutan-guideline.edgeone.dev/` is blocked by this
  environment's egress policy (403 on CONNECT). `docs/guideline.md` is the
  verbatim text, pasted into the session on 2026-08-18. If the guideline
  changes, re-paste it and re-reconcile rather than trusting these files.
* The rubric judge's criteria are known only in outline (clarity, specification
  completeness, whether the verifier measures the objective, anti-gaming
  adequacy). `docs/quality-checklist.md` targets them from that outline.
