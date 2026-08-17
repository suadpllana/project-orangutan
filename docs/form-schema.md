# The authoring form

Transcribed from screenshots of the authoring UI. Everything marked
**(verified)** is legible in a screenshot; everything marked **(unverified)** is
an inference and should be confirmed against the live form before you rely on
it. `tools/validate_task.py` enforces the verified rules as errors and the
unverified ones as warnings.

## Progress checklist

The header shows `N of 6 sections ready` and a status chip (`In progress`).
The six sections are: **Identity, Task, Difficulty, Verification, Resources,
Network**. Resources and Network start ticked because they ship with defaults,
so in practice four sections need writing. **(verified)**

## Section 1 — Task identity

| Form label | `task.yaml` key | Control | Rules |
| --- | --- | --- | --- |
| TITLE | `title` | text | no stated limit **(verified)** |
| WORKING SLUG | `working_slug` | text | `lowercase-kebab, 3–80 chars` **(verified)** |
| COLLECTION FAMILY | `collection_family` | select | placeholder `— select a family —`, marked **Required** **(verified)**; option list not visible **(unverified)** |
| TASK FAMILY | `task_family` | select | defaults to `feature development` **(verified)**; other options not visible **(unverified)** |
| VERIFIER FAMILY | `verifier_family` | select | defaults to `programmatic` **(verified)**; other options not visible **(unverified)** |

Because `collection_family` is a dropdown whose options are not reproducible
offline, leave it blank in `task.yaml` and pick it in the form. The validator
warns rather than errors on a blank value.

## Section 2 — What the task is

| Form label | Key | Limits | Helper text |
| --- | --- | --- | --- |
| OBJECTIVE | `objective` | 40–20,000 | "what the agent must accomplish" |
| MOTIVATION | `motivation` | 20–10,000 | "why this task matters" |
| ENVIRONMENT SUMMARY | `environment_summary` | 40–20,000 | "the runtime, stack, and services" |

All **(verified)**.

## Section 3 — Difficulty & effort

| Form label | Key | Limits | Helper text |
| --- | --- | --- | --- |
| DIFFICULTY EXPLANATION | `difficulty_explanation` | 40–20,000 | "why it is hard but solvable" |
| EXPERT TIME ESTIMATE (HOURS) | `expert_time_estimate_hours` | any positive estimate, defaults to `4` | — |

All **(verified)**.

## Section 4 — Oracle & verification

| Form label | Key | Limits | Helper text |
| --- | --- | --- | --- |
| ORACLE STRATEGY | `oracle_strategy` | 20–20,000 | "how the reference solution solves it" |
| VERIFICATION STRATEGY | `verification_strategy` | 40–20,000 | "how the verifier grades it" |
| BINARY SUCCESS CONDITION | `binary_success_condition` | 20–10,000 | "the pass/fail line" |
| PARTIAL SCORE STRATEGY | `partial_score_strategy` | 20–10,000 | "how partial credit is assigned" |
| ANTICIPATED EXPLOITS | `anticipated_exploits` | 20–20,000 | "ways an agent might game the grader" |

All **(verified)**.

## Section 5 — Resource request

| Form label | Key | Default |
| --- | --- | --- |
| CPU (MILLIS) | `resources.cpu_millis` | `2000` |
| MEMORY (MB) | `resources.memory_mb` | `4096` |
| STORAGE (MB) | `resources.storage_mb` | `8192` |
| GPU COUNT | `resources.gpu_count` | `0` |
| AGENT TIMEOUT (S) | `resources.agent_timeout_s` | `14400` |
| VERIFIER TIMEOUT (S) | `resources.verifier_timeout_s` | `1200` |

All defaults **(verified)**. No min/max is shown in the UI; the bounds in
`tools/validate_task.py` are sanity rails, not transcribed limits
**(unverified)**.

`agent_timeout_s` defaults to 14400 s = 4 h, matching the default expert
estimate of 4 hours. If you raise the expert estimate, raise the agent timeout
with it.

`verifier_timeout_s` of 1200 s is a real constraint on grader design: **the sum
of your per-test-group timeouts has to fit inside it**, because a verifier the
harness kills reports nothing at all. Either keep the total under the budget or
raise the field and say why in `notes`.

## Section 6 — Network requirements

| Form label | Key | Notes |
| --- | --- | --- |
| MODE | `network.mode` | select, defaults to `none` **(verified)**; other options not visible **(unverified)** |
| JUSTIFICATION | `network.justification` | "Optional — explain why network access is needed (≤ 4,000 chars)" **(verified)** |

`none` is the right default and the easiest to defend. If a task needs the
network, everything it downloads becomes an unpinned dependency of your score,
so bake it into the image instead wherever you can.

## Mapping to `task.yaml`

`task.yaml` in each task directory holds exactly these fields plus two things
the form does not have:

* `schema_version` — bump if this document changes shape.
* `notes` — authoring notes for humans and future sessions. Never pasted into
  the form.

Run both tools before submitting:

```bash
python3 tools/validate_task.py --all          # limits, slug, layout
python3 tools/render_submission.py --all      # regenerate submission.md
```

`submission.md` is the paste-ready render, one section per form field with a
character count against each limit.
