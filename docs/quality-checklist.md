# Pre-submit checklist

Run top to bottom. Anything unticked is a reason not to submit yet. The funnel
stages this mirrors are in `docs/submission-funnel.md`.

## Mechanical

```bash
python3 tools/validate_draft.py --all
python3 tools/check_bundle.py --all
python3 tools/render_submission.py --all --check
python3 tools/build_bundle.py --all
docker build -t <slug> tasks/<slug>/bundle/environment/
```

- [ ] `validate_draft.py` reports no errors and no warnings.
- [ ] `check_bundle.py` reports no errors: all five required paths present,
      `task.toml` parses, no unsafe or duplicate paths, no `__pycache__`.
- [ ] `submission.md` is not stale.
- [ ] Every field is inside its bounds, and none is within 10% of the cap by
      accident.
- [ ] The image builds, and its build-time self-check passes. If you cannot
      reach a docker daemon, say so rather than implying it was verified — and
      keep the Dockerfile free of `RUN` heredocs, which the classic parser does
      not join across newlines.
- [ ] `tests/test.sh` and `solution/solve.sh` are executable in the ZIP.
- [ ] The five required paths are at the **root of the ZIP**, with no `<slug>/`
      wrapper. Check the archive you are about to upload, not the directory it
      came from: `unzip -l dist/<slug>.zip | head`.

## task.toml schema

Transcribed from an approved bundle — see `docs/bundle-format.md`. Guessing any
of this has already cost two rejections.

- [ ] `[metadata]` declares `name`, `title`, `description`, `collection_family`,
      `task_family`, `verifier_family`, `expert_time_estimate_hours` (plus
      `difficulty`, `tags`, `version`).
- [ ] The families are **snake_case** in the bundle (`library_clone`), title
      case in the draft form (`Library clone`), and the two correspond.
- [ ] `[verifier]` declares `entrypoint`, `network_mode`, `timeout_sec`,
      `reward_file`, `pass_threshold`.
- [ ] `[environment]` declares `dockerfile`, `build_context` and the four
      resource figures — and **no `network_mode`**, which is what "resource
      declaration mismatch" means.
- [ ] The grader really writes `reward_file`, and exits 0 only at or above
      `pass_threshold`.
- [ ] The grader **deletes stale reward artefacts** before running; the agent
      can write to `/logs`.
- [ ] `test.sh` and `solve.sh` resolve `IMPL_ROOT` / `LOG_DIR` and search
      candidate directories rather than assuming a layout.
- [ ] The visible tests live in `public_tests/`, not `tests/`.
- [ ] The Dockerfile `rm -rf`s `/app/tests`, `/app/solution`, `/app/Dockerfile`
      and `/app/task.toml` after the copy.

## Resources and network

- [ ] `agentTimeoutSec` ≥ 7,200 s (the long-horizon floor).
- [ ] agent + verifier + build + teardown fits 50,400 s.
- [ ] Nothing exceeds the sandbox envelope (8 CPUs / 65,536 MB / 40,960 MB).
- [ ] `task.toml` timeouts are **strictly below** the draft's envelope, not
      equal to it (the approved bundle uses 14000 against 14400, 600 against
      1200). Resources may be equal — `gpus = 0` has to be.
- [ ] Nothing in `task.toml` exceeds the **form defaults** (2000 cpuMillis,
      4096 MB, 8192 MB, 0 GPUs, 14400 s agent, 1200 s verifier) unless you have
      confirmed the raised value is saved in the form. Intake compares against
      the *stored* draft, not the one in your repo, and a raise that silently
      failed to save shows up as "<field> exceeds draft".
- [ ] The grader's own internal deadline is comfortably inside `task.toml`'s
      `[verifier] timeout_sec`, which is inside `verifierTimeoutSec`.
- [ ] `[agent] network_mode` is stated explicitly and is `none` or `allowlist`,
      and it agrees with `networkRequirements.mode`.
- [ ] If `open_internet_justification` is set, `[agent] network_mode` is set too.

## Oracle & nop

- [ ] `solution/solve.sh` drives the verifier to **full reward**, from a clean
      build, with no files left over from development.
- [ ] The **untouched** starting state sits at its floor.
- [ ] You have listed every test the untouched state *passes* and can say what
      work each one credits. (This is where free credit hides — see the audit in
      `verifier-patterns.md`.)
- [ ] At least one deliberately-wrong variant has been graded and landed where
      you predicted.
- [ ] A submission with no package at all, and one with a syntax error, both
      produce a report rather than a crash.
- [ ] The integrity scan has been shown to fire on a real cheat **and** to stay
      quiet on a docstring that mentions the same words.
- [ ] Per-category timeouts sum to less than `verifierTimeoutSec`, or the global
      deadline covers the difference and it is explained in `notes`.
- [ ] The whole verifier run is well inside its budget for a *correct*
      submission.

## The specification (`instruction.md`)

- [ ] Substantive — far beyond the host-side floor — and self-contained enough
      to work from.
- [ ] Every hidden test traces back to a sentence in it. Walk the list.
- [ ] Every "MUST" has at least one test behind it.
- [ ] The failure model is stated (process crash vs machine crash, what counts
      as durable, what is out of scope).
- [ ] Things that are *not* required are stated as explicitly as things that are.
- [ ] Filenames, limits and exception names the grader depends on are named.
- [ ] The implementation constraints — where files may live, what may be
      imported, what may not be inspected — are stated, so no defence is a
      surprise.
- [ ] It says plainly that the visible tests are the floor, not the target.
- [ ] A competent reader could implement it without guessing your API names.

## The verifier

- [ ] **Multi-channel**: the objective is graded from several independent angles
      (behaviour, invariants under stress, resource bounds, cost), not one
      assertion. This is the most common reason a working task is not keepable.
- [ ] There is a real **visible / hidden split**, and `verificationStrategy`
      says which is which.
- [ ] The visible half describes what must not regress, not what to build.
- [ ] Each category maps to a capability, not to a file layout.
- [ ] For each test, you can name the wrong implementation it catches.
- [ ] No test depends on the implementation's internal file format.
- [ ] Negative assertions have positive twins (see `exploit-catalog.md`).
- [ ] At least one test forces the correct *design*, not just correct output.
- [ ] At least one test asserts the spec's ceiling — that a stronger-than-asked
      behaviour is wrong.
- [ ] Nothing is order-dependent across tests; each starts from a clean fixture.
- [ ] Nothing is timing-flaky. Randomised crash timing is fine when the
      assertion holds regardless of when the crash lands; a bare `sleep` race is
      not.
- [ ] Performance budgets have roughly an order of magnitude of headroom over
      the reference, and the naive baseline misses by more than that.
- [ ] Nothing under `tests/` is reachable from the agent's image.

## The draft prose

- [ ] `objective` is complete enough to work from without the repository.
- [ ] `motivation` makes the realism obvious — this is work an engineer would do.
- [ ] `environmentSummary` names the image, the packages, `/app`'s contents, the
      resources and the failure model.
- [ ] `difficultyExplanation` argues both halves — why a frontier model won't
      one-shot it *and* why it is achievable in the estimated time. Specific
      traps, not adjectives.
- [ ] `oracleStrategy` describes the solution you actually ran, with its
      measured score.
- [ ] `verificationStrategy` describes the verifier you actually ran, including
      test counts per category and the visible/hidden split.
- [ ] `binarySuccessCondition` is a condition, not a paragraph — evaluable from
      the report alone.
- [ ] `partialScoreStrategy` gives the weights, the formula, how timeouts and
      integrity violations score, and predicted scores for plausible failure
      modes.
- [ ] `anticipatedExploits` names a countermeasure for every exploit listed.
- [ ] `notes` records anything you deviated from the defaults on, and why.

## After a fix, before you stop

- [ ] `build_bundle.py` re-run, so `dist/<slug>.zip` reflects the change.
- [ ] Oracle re-verified through `solve.sh` + `test.sh` after the change, not
      just before it.
- [ ] Committed and pushed.
- [ ] **The rebuilt ZIP handed back to the user.** `dist/` is gitignored and the
      container is ephemeral — an unsent artifact means the fix cannot be
      uploaded.
- [ ] Said in one line whether the draft needs editing too, or whether the
      bundle change alone is enough.

## Novelty and honesty

- [ ] The task is not a re-skin of an existing one or a well-known exercise.
- [ ] `collectionFamily` is the honest fit, not the most flattering one.
- [ ] Every number in the prose was measured, not estimated.
- [ ] Anything you could not verify is marked as unverified rather than asserted.
- [ ] Known weaknesses are in `notes` rather than omitted.
