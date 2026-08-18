# Task-authoring prompt (reusable)

Paste this verbatim to start a new task. It deliberately does **not** name the
subject or the families — step 0 derives them from what the repo already holds,
so consecutive tasks do not collide at the similarity gate.

---

Read these before writing anything, in this order:

  1. `docs/guideline.md` — the official guideline, verbatim. It is authoritative.
  2. `CLAUDE.md` — the fourteen rules and both SOLVED sections on intake rejections.
  3. `reference/approved/incremental-memo-engine/` — a bundle that was APPROVED.
     Read its `task.toml`, `tests/test.sh`, `tests/grade.py`, `solution/solve.sh`
     and `environment/Dockerfile`. Copy the shape exactly. Never copy the content.
     Heed `reference/README.md`: you are seeing half of a submission, so its
     resource numbers prove nothing about your own.
  4. The most recent task under `tasks/` — the worked example. Read its README for
     the real bugs its own suite caught before it shipped.

## 0. Pick the ground, and pick it AWAY from what exists

Before proposing anything, run:

```bash
grep -H -E '^(title|workingSlug|collectionFamily|taskFamily|verifierFamily)' tasks/*/draft.yaml
```

and read `reference/approved/*/instruction.md` headings. Then choose under these
rules:

* **`collectionFamily` must differ from the most recently authored task.** The
  enum is `Library clone`, `Product clone`, `ML engineering`,
  `Algorithmic optimization`; the corpus is balanced across all four, so rotate.
  If every value has been used, pick the least-used one.
* **`taskFamily` should differ too where the work honestly supports it** —
  `feature_development`, `debugging`, `refactoring`, `performance`,
  `systems_integration`, `other`. Pick the honest fit, never the novel one for
  novelty's sake; a debugging or refactoring task is a genuinely different shape
  of problem and worth reaching for.
* **`verifierFamily`**: `programmatic` unless the task is genuinely a metric to
  push, in which case `optimization`. There is no approved example of the other
  two in this repo, so if you want `ml_artifact` or `custom`, say so and stop —
  I will decide whether to accept the unproven shape.
* **Subject matter must be more than one hop from every existing task and from
  the approved reference.** Same data structure, same domain vocabulary, or same
  central mechanism as an existing task is a near-miss and the similarity gate
  rejects near-misses. State in one line, per candidate, why it is not a
  near-miss of each existing task.

## 1. Fixed constraints (these are platform facts, not preferences)

* **Fully offline**: `networkRequirements.mode: none`. Everything the task needs
  is baked into the image at build time; nothing is fetched at runtime.
* **Runtime**: prefer what the base image already carries, because I cannot build
  the image here to prove an install works. If you want a stack that needs
  installing at build time, or any third-party runtime dependency, say so
  explicitly and flag it as unverifiable in this session rather than assuming it.
* **Deterministic grading.** No wall-clock flakiness that is really measuring the
  grading host, no network, no randomness without a pinned seed. If you set a
  performance budget, state what machine claim it encodes (see CLAUDE.md's
  "State the failure model in the spec").
* **Expert time 4–8 hours**, and it must be honest.
* **At least three requirements that CONSTRAIN EACH OTHER**, so the obvious
  shortcut for one is killed by another. Independent requirements make a
  checklist, and the difficulty probe saturates a checklist.

## 2. Propose three candidates and STOP

One paragraph each. Each candidate must name:

* its `collectionFamily` / `taskFamily` / `verifierFamily`;
* the interacting constraints, explicitly — for each, the shortcut it kills and
  the requirement that kills it;
* one line on why it is not a near-miss of anything already in `tasks/` or
  `reference/approved/`.

Make the three genuinely different from each other, not three framings of one
idea. Then stop and wait for me to choose.

## 3. Then build, in this order

  1. `bundle/instruction.md` — the complete normative spec. Every MUST gets a
     test; every test traces back to a sentence. State the failure model and what
     is explicitly OUT of scope.
  2. The starter tree under `bundle/environment/` — working code that is honestly
     inadequate, not stubs. Visible tests in `public_tests/` describing what must
     NOT REGRESS, and say in `instruction.md` that they are the floor, not the
     target.
  3. The sealed suite under `bundle/tests/` — BEFORE the reference solution.
     Weighted categories, each grading a different angle. Give the run a global
     deadline so a hang costs one category, never the report.
  4. `bundle/solution/` — then run the grader and EXPECT IT TO FAIL. If the oracle
     passes first try, suspect the tests.
  5. Grade the untouched starter tree. List every test it passes and justify each.
     Drive it to 0.0000 — free credit is an authoring bug, not partial credit.
  6. Grade one deliberately-wrong-but-plausible variant; check it lands where you
     predicted, and say beforehand where that is.
  7. `draft.yaml` last, when every number in it is something you measured.

## 4. Hard requirements before you tell me it is ready

* `validate_draft.py --all`, `check_bundle.py --all`,
  `render_submission.py --all --check`, `build_bundle.py --all` — all clean.
* Oracle at full reward and nop at its floor, both through the real
  `tests/test.sh` entrypoint, not a shortcut.
* `task.toml [environment]` asks for STRICTLY LESS than the draft on `cpus`,
  `memory_mb` and `storage_mb` (`gpus` stays 0), and both timeouts are below the
  draft's. Nothing above the form defaults: 2000 / 4096 / 8192 / 0 / 14400 / 1200.
  If you claim `cpus = 1`, prove it with `taskset -c 0`.
* The grader deletes stale reward artefacts before grading, writes `reward_file`
  under both names in every candidate directory, publishes a 0.0 floor before
  grading starts, and exits 0 only at or above `pass_threshold`.
* `tasks/<slug>/<slug>.zip` committed beside the source, and the built ZIP handed
  to me in the same message with its `sha256:` fingerprint.

## 5. If the platform rejects it at intake

Do NOT guess a fix. Build the table from CLAUDE.md's SOLVED section: one row per
attempt, one column per thing the bundle declares. Find the column that has never
varied across the failures, and change that one. Ask me to read values back from
the draft form rather than inferring what it holds.

## 6. Tell me what you could not verify

Explicitly, as a list — there is no docker daemon here, so the image build cannot
be run — rather than implying you did.
