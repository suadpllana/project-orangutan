# The draft

Phase one of submission. The draft is the structured metadata describing the
task; it is versioned, so you can revise it while you iterate on the bundle.
Bounds are enforced on submit — `tools/validate_draft.py` enforces them here,
where fixing them is cheap.

Treat the character minimums as a floor, not a target. **A reviewer should be
able to understand and trust the task from the draft alone.**

`tasks/<slug>/draft.yaml` holds these fields verbatim, plus `schema_version` and
`notes` (authoring notes, never pasted into the form).

## Task identity

| Field | Bounds | Notes |
| --- | --- | --- |
| `title` | 3–200 chars | A human name, written for a reviewer skimming a queue — not for the agent. |
| `workingSlug` | 3–80, lowercase-kebab | `a-z0-9` with single hyphens. Also the task directory name. |
| `collectionFamily` | enum | The artifact type the task is built around. Locked choice, not free text. |
| `taskFamily` | enum | What kind of work this is. |
| `verifierFamily` | enum | How it is graded. |

**`collectionFamily`** — the corpus is balanced across these, so pick the honest
fit:

* `Library clone` — reimplement a focused library or module to spec.
* `Product clone` — build a working slice of a real application.
* `ML engineering` — train, tune, or wire up a model against a metric.
* `Algorithmic optimization` — make a correct solution measurably faster or leaner.

**`taskFamily`** — `feature_development`, `debugging`, `refactoring`,
`performance`, `systems_integration`, `other`.

**`verifierFamily`** — `programmatic` (tests/scripts), `optimization` (a metric
to push), `ml_artifact` (a trained artifact), `custom`.

## What the task is

| Field | Bounds | What goes in it |
| --- | --- | --- |
| `objective` | 40–20,000 | The concrete deliverable, stated the way you would hand it to an engineer: what to build, fix or produce, and what "done" looks like. The spine of the task. |
| `motivation` | 20–10,000 | The real-world scenario or capability this stands in for. Keeps the task grounded in something an engineer would actually do. |

## Difficulty & effort

| Field | Bounds | What goes in it |
| --- | --- | --- |
| `difficultyExplanation` | 40–20,000 | Where the difficulty *actually lives*: the reasoning, the traps, the parts a strong model gets wrong. "It's hard" is not an explanation. This is what convinces the difficulty probe and the reviewer that a frontier model won't one-shot it. |
| `expertTimeEstimateHours` | any positive number | How long a qualified human expert would take end to end. Descriptive metadata — **not** a gate; long-horizon is enforced on the agent time budget instead. Give an honest figure however large. |

## Environment & resources

`environmentSummary` (40–20,000): the base image, languages and tooling,
pre-installed dependencies, and the starting state the agent finds in `/app`.
Everything must be baked into the image — there is no network at runtime unless
you request it.

`resourceEstimate`:

| Key | Range |
| --- | --- |
| `cpuMillis` | 100 – 64,000 |
| `memoryMb` | 128 – 262,144 |
| `storageMb` | 128 – 1,048,576 |
| `gpuCount` | 0 – 8 |
| `agentTimeoutSec` | ≤ 86,400 (24 h) |
| `verifierTimeoutSec` | ≤ 86,400 (24 h) |

Ask for what the task needs and no more. Three constraints bite beyond the raw
ranges:

* **Long-horizon floor.** Effective `agentTimeoutSec` must be at least
  **7,200 s (2 h)**.
* **Per-trial ceiling.** The whole trial — build + agent + verify + teardown —
  must fit **50,400 s (14 h)**. Outside that window the task is rejected at
  intake.
* **Sandbox envelope.** The trial sandbox provides **8 CPUs, 65,536 MB memory,
  40,960 MB storage**. A request above that is rejected rather than run starved,
  because a task denied the resources it declared fails for infrastructure
  reasons and would be mis-recorded as hard.

Your bundle's `task.toml` `[environment]` block is checked against these numbers
*and* against the draft: **it may ask for less, never more.** A value there that
no longer matches the draft is rejected, not quietly ignored.

`networkRequirements`:

* `mode`: `none` (default, fully offline) or `allowlist` (at least one host, up
  to 100). **Unrestricted open egress is not admitted** and is rejected at
  intake.
* `hosts`: only accepted in `allowlist` mode.
* `justification`: a non-empty one is expected.

Prefer `none` — it makes grading deterministic. This field is about *your task*,
not the harness: the rollout always runs deny-all plus the model endpoint the
harness injects, so leave it `none` unless the task itself must reach a host.

## Oracle & verification

| Field | Bounds | What goes in it |
| --- | --- | --- |
| `oracleStrategy` | 20–20,000 | How your reference solution under `solution/` actually solves the task, so the oracle run reaches full reward. If it isn't solvable by your own reference, it isn't a task. |
| `verificationStrategy` | 40–20,000 | What the verifier under `tests/` runs, what it checks, and why that genuinely measures the objective rather than a proxy an agent can satisfy without doing the work. **State which part of the verifier is visible and which is held out.** |

## Scoring & exploits

| Field | Bounds | What goes in it |
| --- | --- | --- |
| `binarySuccessCondition` | 20–10,000 | The single unambiguous pass/fail line. Objective and machine-checkable. |
| `partialScoreStrategy` | 20–10,000 | How partial progress earns partial credit. Continuous, monotone scoring makes a task far more useful than an all-or-nothing gate — describe the components and how they add up. |
| `anticipatedExploits` | 20–20,000 | The shortcuts you expect an agent to try — hard-coding outputs, reading held-out data, gaming the metric — and how your verifier defeats each. **Reviewers weight this heavily.** |

## Checking a draft

```bash
python3 tools/validate_draft.py --all        # bounds, enums, floors, ceilings
python3 tools/render_submission.py --all     # regenerate submission.md
```

`submission.md` is the paste-ready render: one section per field, each with its
character count against the limit.
