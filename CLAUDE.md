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
  difficulty-gate.md       the Difficulty evaluation stage - READ BEFORE SETTING TIMEOUTS
  reward-contract.md       the reward file: the contract, and how it failed twice
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
* **Every new `tasks/<slug>/` must include a built ZIP artifact in that same
  folder.** After scaffolding a task, run `python3 tools/build_bundle.py --all`
  and place the current archive as `tasks/<slug>/<slug>.zip` so the bundle sits
  beside its source and can be handed off without hunting through `dist/`.
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

## The fifteen rules

Ordered by how much grief each one saves.

**1. Read the guideline before you build anything.** This repository was first
built from screenshots of the draft form after the guideline URL returned 403,
and the result had the right task inside the wrong container: no `task.toml`, no
`instruction.md`, entrypoints under invented names, `/workspace` instead of
`/app`, and `taskFamily: "feature development"` where the enum wanted
`feature_development`. The content survived the correction; the packaging and
half the metadata did not. If a source you were pointed at is unreachable, stop
and say so — do not infer a spec you were told exists.

**2. Check the artifact the platform opens, not the one you wrote.** "Required
file missing" has now been hit twice, and *the second time the archive I built
was correct*. Both failures put the required paths below the archive root; only
one of them was a packaging bug.

*Mechanism 1 — the build wrapped it.* `build_bundle.py` used to put everything
under `<slug>/`. Every check in this repository looked at `bundle/` on disk and
passed. The required paths are relative to the **archive root**; the guideline's
`my-task/` diagram is the directory whose *contents* you zip. `build_bundle.py`
now re-opens the ZIP and asserts the five paths before reporting success.

*Mechanism 2 — there was no archive to upload, so the directory got zipped.*
This is what rejected `pkgsolve-resolver-explanations`. `dist/` is gitignored
and I never wrote the `tasks/<slug>/<slug>.zip` copy the conventions call for,
so the only thing in the task folder that looked like "the bundle" was the
folder itself. What reached the platform was a zip of `tasks/<slug>/`:
38 entries, every required path two levels down under
`pkgsolve-resolver-explanations/bundle/`, and `draft.yaml`, `README.md` and
`submission.md` swept in beside them. The archive I had verified — 35 entries,
five paths at the root — was never uploaded. **A verification that ends at the
file you wrote does not cover the file they open.**

Two habits close it, and both are now enforced:

* `build_bundle.py` writes `tasks/<slug>/<slug>.zip` on every build, so the
  hand-over copy is never missing and there is never an ambiguous folder to zip
  by mistake. It also refuses to report success if a shell entrypoint carries
  CRLF.
* Audit the file that is actually going to be uploaded, whatever its provenance:

  ```bash
  python3 tools/verify_zip.py <the-file-you-are-about-to-upload.zip>
  python3 tools/verify_zip.py <that-file.zip> --fix     # rewrites it flat
  ```

  It finds the wrapper at any depth, names it, lists the non-bundle files that
  were swept in, flags `__MACOSX/` and `.DS_Store`, and `--fix` rebuilds the
  archive flat with the executable bits intact.

*A third route to the same rejection, worth knowing before it costs an upload:*
macOS auto-expands a downloaded `.zip` (Safari's "Open safe files after
downloading" is on by default), so what is left on disk is a folder;
re-compressing it in Finder rebuilds the `<slug>/` wrapper and adds a
`__MACOSX/` tree. Reproduced here with `ditto -c -k --keepParent`: 35 entries
become 79 and not one required path sits at the root. **So when you hand a
bundle over, say in the same breath: upload it as downloaded, do not expand it
first.**

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

**15. The agent time budget is the long-horizon gate, and the form default
fails it.** `pkgsolve-resolver-explanations` cleared Bundle structure,
Similarity screening, Rubric review and Oracle & nop, then failed **Difficulty
evaluation** with *"Too short for the collection — not long-horizon"*. The cause
was one number: `agentTimeoutSec: 14400`, the form default, four hours. The
guideline's 7,200 s is the absolute floor, not this collection's bar, and
"ask for what the task needs and no more" is about CPU and memory — being frugal
with the horizon is disqualification, not modesty. Worse, the same draft
declared `expertTimeEstimateHours: 7`, so it gave an agent four hours for work
it had just certified takes an expert seven; `validate_draft.py` only warned
below *half* the estimate, so it said nothing. Use **43,200 s (12 h)** for
`agentTimeoutSec` and **42,000** in `task.toml`, keep
`agent + verifier + 1800 ≤ 50,400`, and **raise the value in the form, save,
reload and read it back before uploading** — intake compares against the stored
draft (rule 4). `validate_draft.py` now errors on both mistakes.
`docs/difficulty-gate.md` has the full analysis and the checklist.

---

## "completed without writing a reward file" — twice, and the fix was wrong

Oracle & nop has failed twice with:

> Your verifier completed without writing a reward file
> (`verifier/reward.txt` or `reward.json`) — **every trial must produce one.**

**Read the two paths in that message.** `verifier/reward.txt` is written
*relative* and carries a directory component; `reward.json` is written relative
with none. They are two paths under one root the message never names.

The first fix read it as naming two *absolute* locations and wrote to a list of
absolute directories — `LOG_DIR, /logs, /verifier, /tests, <dir of grade.py>,
its parent, CWD, /tmp` × `reward.txt, reward.json, score.txt, score.json`. That
covers `verifier/reward.txt` **only if the unnamed root happens to be `/`**. It
was recorded here as SOLVED while the stage was still running; it was not. The
identical rejection came back on the next task.

### What actually works

Take every plausible root, and under each write the reward **both at the root
and inside a `verifier/` subdirectory of it**:

```
roots:  $LOG_DIR, $REWARD_DIR, $VERIFIER_DIR, $OUTPUT_DIR, $OUTPUTS_DIR,
        $RESULTS_DIR, $RESULT_DIR, $TEST_OUTPUT_DIR,
        /logs /verifier /tests /output /outputs /results /app /workspace
        <dir of grade.py>, its parent, $PWD, $PWD/.., /tmp /var/tmp /
each x   {"", "/verifier"}
each x   reward.txt, reward.json, score.txt, score.json
```

Four rules make it hold, and all four are cheap:

1. **Publish a `0.0` floor before grading starts**, from `test.sh` *and* again
   from `grade.py`, over that whole net.
2. **Wrap the grading run in `except BaseException`** and publish on the way
   out. A grader that dies without a reward is reported as a verifier bug.
3. **Never create a directory just to empty it, and prefer not to empty it at
   all.** `clear_stale_rewards` skips roots that do not already exist, so
   widening the net cannot turn a read-only mount into a failure — but *deleting*
   a stale reward is itself the next bug on this list: see "It came back anyway"
   below. Overwrite; only unlink a file that refuses to be written.
4. **Print every location that took the file and every one that refused it.**
   Both failures above were silent, which is why the second one had to be
   reasoned about instead of read off a log. `test.sh` now prints `$PWD`, the
   suite directory and both lists before it does anything else.

Verified three ways with `LOG_DIR` unset and `/logs` unwritable, so that the
working directory is the only place that will take a file: a normal run leaves
`1.000000` in `./reward.json` and `./verifier/reward.txt`, an exception inside
`grade()` leaves `0.000000` in both, and `SIGKILL` three seconds in leaves
`0.000000` in both.

**A local grader run now scatters `reward.*` and `verifier/` directories through
the working tree**, including inside `bundle/`. `build_bundle.py` skips both and
`check_bundle.py` warns about them, because shipping a stale score inside the
archive would be worse than the bug this fixed.

`docs/reward-contract.md` is the full playbook: the root list, the five rules,
the three-way verification recipe and the pre-submit checklist. Copy the
mechanism from `tasks/pkgsolve-resolver-explanations/bundle/tests/`; do not
re-derive it.

### It came back anyway, on a bundle that already did all of that

`zipstream-bounded-memory-codec` was built with the write-everywhere floor above
and failed **Oracle & nop** with the identical message. Two things were wrong,
and both generalise:

**1. The floor was being deleted by the grader that depended on it.** A stale
`reward.txt` containing `1.0` must never be read as a score, so `grade.py`
opened by *unlinking* every reward artefact in every candidate directory —
including the 0.0 floor `test.sh` had just written. Everything after that unlink
was unprotected. **Overwrite a stale reward, never remove it**: the anti-gaming
requirement is that the value is not the agent's, not that the file is absent,
and there must be no instant in the trial with no reward on disk. Only unlink a
file that refuses to be written, and write a fresh one immediately.

While you are there, close the rest of the path:

* write the floor in **POSIX shell**, before the interpreter is even looked
  for — the previous version's floor was a Python heredoc, so "no python on
  PATH" meant no reward file at all;
* `trap` on `EXIT`, `TERM`, `INT`, `HUP` and re-assert it;
* publish **after every scoring category** (measure the multiplier category
  first so the partial score stays monotone) — a killed run then reports what
  it measured instead of nothing;
* have `test.sh` parse `SCORE:` back out of the grader's own report and write
  the reward again itself, so the reward does not depend on the grader's writer;
* write into a **`verifier/` subdirectory** of every candidate as well as the
  candidates themselves. The platform's message names `verifier/reward.txt`,
  which reads as a relative path as easily as an absolute one.

**2. The verifier was slow enough to be killed.** `task.toml` claimed 87 s of
child time; the same suite took **264 s** on an ordinary 2.8 GHz core. A 3x
spread between two unremarkable machines, against a 1000 s limit, is a coin
flip. **Measure the verifier on the machine you are on, not on the one you
measured last time, and treat a claimed timing in a comment as unverified until
you have re-run it.** Then leave real headroom: the grader's own deadline plus
one call's cap must be comfortably below `[verifier] timeout_sec`.

If your grading cost is dominated by `tracemalloc`, know the multiplier before
you design the run: it was **14x** on an allocation-heavy codec here, which
makes the verifier's runtime proportional to the number of graded bytes. Keep
the large streams only where the measurement genuinely needs them (the memory
proof) and grade the scale-free properties — a ratio against a baseline on the
same bytes, a bound that is a multiple of the input length — on smaller ones.
That halved the run without weakening a check.

**And do not let a `tracemalloc` budget charge for compiling the submission.**
Importing a module from `.py` leaves roughly eight times the source size alive
that importing it from `.pyc` does. Measured here: the same package cost
345,633 B against a 384 KiB import budget from source and 121,143 B
precompiled. A grader that copies sources into a scratch tree recompiles on
every call, so a spec that allows 96 KiB of source and budgets 384 KiB is
measuring source length, not design. Byte-compile the tree the grader owns
once, before any measurement.

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
