# Authoring a task for Orangutan — the official guideline

> **Verbatim copy of the authoring guideline**, pasted into the session on
> 2026-08-18. The live page is at
> `https://project-orangutan-guideline.edgeone.dev/`, which this environment's
> egress policy blocks (403 on CONNECT) — that is why it is kept here.
>
> **Read this file in full before authoring anything.** Everything else in
> `docs/` is commentary on it. Where a doc in this repository disagrees with
> this file, this file wins; fix the doc.

---

Orangutan collects self-contained software-engineering tasks that a frontier
coding agent works on autonomously and that are graded objectively by a sealed
verifier. You author each task in two parts: a draft (structured metadata
describing the task) and a task bundle (a ZIP holding the actual environment,
verifier, and reference solution). This page walks through both, the submission
flow, and the bar a task has to clear. Read it fully before your first
submission.

## Two-phase submission — draft, then bundle

Submitting is a deliberate two-phase flow so nothing untrusted enters the
pipeline unchecked. You fill in the draft first, then upload the bundle through
a quarantined channel:

- **Create a draft.** Fill in the authoring fields below (title, objective,
  verification strategy, and the rest). The draft is versioned — you can revise
  it while you iterate on the bundle.
- **Request an upload URL.** When your bundle is ready, the app hands you a
  short-lived, signed URL that points at a private quarantine bucket. Nothing is
  public and nothing is trusted yet.
- **Upload your task bundle.** Push the single ZIP to that URL (see the size and
  format limits below). It lands as an upload artifact in an `uploaded` state.
- **The bundle is quarantined and inspected.** Before it can be used, an
  automated inspection opens the archive in isolation and moves it through
  `inspecting` to either `safe` or `rejected`. Only a `safe` artifact — one whose
  paths and contents pass the structural checks — can be attached to a
  submission.
- **Inspection submits the task automatically.** When a bundle passes
  inspection, the system atomically snapshots the draft + safe bundle into a
  submission and starts the automated funnel. There is no separate submit button
  to wait for; watch inspection and validation from *My tasks*.

Resubmitting a byte-for-byte identical bundle is blocked by content hash, and
near-duplicates of an existing task are caught by the similarity stage — so make
each task genuinely new before you submit.

## Draft authoring fields

These are the fields the draft form collects. Bounds are enforced on submit, so
treat the character minimums as a floor, not a target — a reviewer should be able
to understand and trust the task from the draft alone.

### Task identity

**`title`** — 3–200 chars
A short human name for the task. Shown in the queue and on your task page — write
it for a reviewer skimming a list, not the agent.

**`workingSlug`** — 3–80, lowercase-kebab
A URL-safe handle: lowercase letters, digits, and single hyphens (`a-z0-9`, e.g.
`parse-toml-strict`). Used to identify your draft while you iterate.

**`collectionFamily`** — enum
The artifact type your task is built around, used to balance the corpus across
families: **Library clone** (reimplement a focused library or module to spec),
**Product clone** (build a working slice of a real application), **ML
engineering** (train, tune, or wire up a model against a metric), or
**Algorithmic optimization** (make a correct solution measurably faster or
leaner). Pick the closest fit — it is a locked choice, not free text.

**`taskFamily`** — enum
What kind of work this is: `feature_development`, `debugging`, `refactoring`,
`performance`, `systems_integration`, or `other`.

**`verifierFamily`** — enum
How the task is graded: `programmatic` (tests / scripts), `optimization` (a
metric to push), `ml_artifact` (a trained artifact), or `custom`.

### What the task is

**`objective`** — 40–20,000 chars
The concrete deliverable, stated the way you would hand it to an engineer: what
the agent must build, fix, or produce, and what 'done' looks like. This is the
spine of the task.

**`motivation`** — 20–10,000 chars
Why this task is worth grading — the real-world scenario or capability it stands
in for. Keeps the task grounded in something an engineer would actually do.

### Difficulty & effort

**`difficultyExplanation`** — 40–20,000 chars
Where the difficulty actually lives: the reasoning, the traps, the parts a strong
model gets wrong. Be specific — 'it's hard' is not an explanation. This is what
convinces the difficulty probe and the reviewer that a frontier model won't
one-shot it.

**`expertTimeEstimateHours`** — any positive estimate (metadata)
How long a qualified human expert would take end to end. A descriptive estimate —
it is NOT a gate (long-horizon is enforced on the agent time budget), so give an
honest figure however large.

### Environment & resources

**`environmentSummary`** — 40–20,000 chars
What the sandbox contains: the base image, languages and tooling, pre-installed
dependencies, and the starting state the agent finds in `/app`. Everything must
be baked into the image — there is no network at runtime unless you request it.

**`resourceEstimate`** — structured
The compute envelope: `cpuMillis` (100–64,000), `memoryMb` (128–262,144),
`storageMb` (128–1,048,576), `gpuCount` (0–8), `agentTimeoutSec` and
`verifierTimeoutSec` (each capped at 86,400 = 24h). Ask for what the task needs
and no more. Note the long-horizon floor: the effective `agentTimeoutSec` must be
at least 2h (7,200s), and the whole trial — build + agent + verify + teardown —
must fit the 50,400s (14h) per-trial pool ceiling; a task outside that window is
rejected at intake. The trial sandbox provides 8 CPUs, 65536 MB of memory and
40960 MB of storage; a request above that is rejected rather than run starved,
because a task denied the resources it declared fails for infrastructure reasons
and would be mis-recorded as hard. Your bundle's `task.toml` `[environment]`
block (`cpus`, `memory_mb`, `storage_mb`, `gpus`) is checked against these
numbers too, and against this form: **it may ask for less, never more.**

**`networkRequirements`** — structured
Whether your task needs the internet: `none` (default — fully offline) or
`allowlist` (requires at least one host, up to 100). A non-empty justification is
expected; hosts are only accepted in `allowlist` mode. Unrestricted open egress
is not admitted for this sealed benchmark (it is rejected at intake). Prefer
`none` — it makes grading deterministic. This field is about your task, not about
the harness: the rollout always runs deny-all plus the model endpoint the harness
injects, so leave it `none` unless the task itself must reach a host.

### Oracle & verification

**`oracleStrategy`** — 20–20,000 chars
How your reference solution (under `solution/`) actually solves the task, so the
oracle run reaches full reward. If it isn't solvable by your own reference, it
isn't a task.

**`verificationStrategy`** — 40–20,000 chars
How the verifier under `tests/` measures success: what it runs, what it checks,
and why that genuinely measures the objective rather than a proxy the agent can
satisfy without doing the work.

### Scoring & exploits

**`binarySuccessCondition`** — 20–10,000 chars
The single, unambiguous pass/fail line — the condition that must hold for the task
to count as solved at all. Keep it objective and machine-checkable.

**`partialScoreStrategy`** — 20–10,000 chars
How partial progress earns partial credit (if it does). Continuous, monotone
scoring makes a task far more useful than an all-or-nothing gate — describe the
components and how they add up.

**`anticipatedExploits`** — 20–20,000 chars
The shortcuts and cheats you expect an agent to try — hard-coding expected
outputs, reading the held-out data, gaming the metric — and how your verifier
defeats each. Reviewers weight this heavily.

## The task bundle

The bundle is a single `application/zip` archive (up to 512 MiB compressed) that
contains the actual task, laid out in the Terminal-Bench / Harbor task format.
Everything the harness needs to build the environment, run the reference
solution, and grade the result lives inside it.

```
my-task/
├── task.toml            # [metadata], [verifier], [agent], [environment]
├── instruction.md       # the problem statement the agent reads
├── environment/
│   └── Dockerfile       # builds /app — deps baked in, no runtime network
├── tests/
│   └── test.sh          # the sealed verifier entrypoint (grader + held-out data)
└── solution/
    └── solve.sh         # the reference solution entrypoint the oracle runs
```

`task.toml` declares the task with a `[metadata]` table (name and identity) plus
`[verifier]`, `[agent]`, and `[environment]` sections (grading, agent, and
sandbox configuration). It must be well-formed TOML — the structure stage parses
it and rejects a malformed file. `instruction.md` is the problem statement the
agent reads; `environment/` becomes `/app` and must include a Dockerfile;
`tests/` holds the sealed verifier; `solution/` holds the reference solution the
oracle runs.

Network posture is declared per phase, and the phases are read separately.
`[environment] network_mode` is the image build — a build that fetches packages is
normal and is not gated. `[agent] network_mode` is the rollout, the one phase the
network policy governs: `none` and `allowlist` are admitted, `open` is refused.
`[verifier] network_mode` is grading. If you write a `[metadata]
open_internet_justification`, you must also state `[agent] network_mode`
explicitly — leaving it out while arguing your task needs the internet is
rejected, because the rollout's egress is read from that field alone and the
trial would otherwise run sealed and fail for a reason that is not your task's
difficulty. A rollout the file seals (`none`) while your form asks for
`allowlist` hosts is rejected for the same reason. The `[environment]` resource
figures (`cpus`, `memory_mb`, `storage_mb`, `gpus`) are checked against the
sandbox budget and against your draft — your bundle may ask for less than the
form, never more — so a value there that no longer matches your draft is rejected
rather than quietly ignored.

## Required files & the quality bar

Two early stages gate the bundle before any real compute is spent. The
**structure stage** is deterministic and rejects a bundle that is missing any
required path, has unsafe or duplicate paths, or whose `task.toml` is not
parseable TOML. The required set is exact:

- `task.toml` — present and valid TOML.
- `instruction.md` — present.
- `environment/Dockerfile` — present.
- `tests/test.sh` — the canonical verifier entrypoint. The grader runs exactly
  this script, so it must be present by name (a non-empty `tests/` directory
  alone is not enough).
- `solution/solve.sh` — the canonical reference-solution entrypoint the oracle
  runs. Likewise required by name.

The **quality check stage** then applies a small set of blocking criteria a
well-formed task always satisfies — a failure here is a real, fixable defect:

- **Instruction present and substantive** — `instruction.md` must be real
  content, not a stub (a hard host-side floor, well below the bar a reviewer
  expects).
- **Task metadata present** — `task.toml` must declare a non-empty task name in
  its metadata.
- **Reference solution present** — at least one file under `solution/`, or the
  oracle cannot be run.
- **Verifier present** — at least one file under `tests/`, or the task cannot be
  graded.

Beyond these deterministic checks, an injection-hardened model judge reads the
whole bundle against the quality rubric — clarity, specification completeness,
whether the verifier genuinely measures the objective, and anti-gaming adequacy.
Passing structure is the floor; the judge and the human reviewer are the real
bar.

## What the automated funnel checks

After you submit, the task runs the full funnel before it reaches a human. You
watch each stage live on your task page.

1. **Structure** — required files, safe/unique paths, and parseable `task.toml`.
   Deterministic and instant.
2. **Similarity / dedup** — an embedding search over the corpus; a task too close
   to an existing one is rejected.
3. **Oracle & nop** — your reference solution and the untouched starting state
   both run on the real harness. The oracle must reach (near) full reward; the
   untouched state must sit at its floor. A task the reference can't solve fails
   here.
4. **Quality check** — the blocking criteria plus the rubric judge described
   above.
5. **Difficulty probe** — independent frontier-agent trials at the full time
   budget. If the agent trivially saturates the task, it's too easy and fails; if
   it's effectively unsolvable, that shows too.
6. **Synthesis** — the terminal step. It confirms every earlier stage passed and
   finalizes the outcome; the real gating happened in the stages above
   (structure, oracle & nop, quality, difficulty). It adds no new judgement of
   its own.

Failures are classified. A **verdict** failure is about the task and comes back
to you with a reason; an **infra** failure is a platform flake, never counts
against you, and is re-run.

## Review, the bar & payout

A task that clears the funnel lands in the human review queue, oldest first. A
reviewer makes the final call and either approves it or sends it back —
rejections and revision requests always come with a written reason, so you can
fix and resubmit.

The bar is higher than "passes the funnel." The automated stages are a floor that
rejects broken tasks; a task that is worth keeping clears all of the following,
and a reviewer weighs every one:

- **Fits a collection family.** A good task is clearly one of the four families
  (Library clone, Product clone, ML engineering, Algorithmic optimization) and
  looks like a real instance of it — not a contrived puzzle that happens to
  compile. Set `collectionFamily` to the honest fit; the corpus is balanced
  across them.
- **Solvable by the reference.** Your `solution/` must drive the verifier to full
  reward — if it can't, the oracle stage fails and there is no task.
- **Robust, multi-channel verification.** A single assertion is not enough. Grade
  the objective from several independent angles — behaviour and outputs,
  invariants and edge cases, and where it fits the family, a performance or
  quality metric — so a partial or lucky solution cannot pass. Weak, one-shot
  verifiers are the most common reason a task that "works" still isn't keepable.
- **A visible / hidden verifier split.** Give the agent enough of the check to aim
  at — the public portion of `tests/` that states what "done" means — while
  keeping the decisive held-out cases and grading logic sealed. The agent should
  be able to self-check against the visible part and still be unable to overfit
  the hidden part. State which is which in your `verificationStrategy`.
- **Not gameable.** The verifier must measure the real objective, seal the
  held-out data and grading logic under `tests/`, and defeat the shortcuts you
  listed in `anticipatedExploits` — hard-coding expected outputs, reading the
  held-out data, or gaming the metric.
- **Realistic.** The task should stand in for work a real engineer would actually
  do, in an environment that resembles a real codebase or system — not a synthetic
  drill. Your `motivation` should make that grounding obvious.
- **Novel.** Genuinely new, not a re-skin of an existing task or a well-known
  exercise a model has seen a thousand times. Content-hash and similarity gates
  block near-duplicates, but the deeper bar is conceptual: the problem itself
  should be fresh.
- **Hard, but not impossible.** A frontier model must not trivially solve it —
  that's the whole point — yet it must be genuinely achievable, as your reference
  proves.

Approved tasks are paid a flat per-task amount, recorded at approval and paid on
the normal cycle. Plan your throughput around validation cost, and make each task
genuinely distinct — content-hash and similarity gates block resubmitted
duplicates.
