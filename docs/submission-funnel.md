# Submission, the funnel, and the bar

## The two-phase flow

Submitting is deliberately two-phase so nothing untrusted enters the pipeline
unchecked:

1. **Create a draft.** Fill in the fields in `docs/draft-fields.md`. The draft is
   versioned — revise it while you iterate on the bundle.
2. **Request an upload URL.** When the bundle is ready, the app hands you a
   short-lived signed URL pointing at a private quarantine bucket. Nothing is
   public and nothing is trusted yet.
3. **Upload the ZIP.** It lands as an upload artifact in an `uploaded` state.
4. **Quarantine and inspection.** An automated inspection opens the archive in
   isolation and moves it through `inspecting` to either `safe` or `rejected`.
   Only a `safe` artifact can be attached to a submission.
5. **Inspection submits the task automatically.** On passing, the system
   atomically snapshots draft + bundle into a submission and starts the funnel.
   **There is no separate submit button.** Watch inspection and validation from
   *My tasks*.

Resubmitting a byte-for-byte identical bundle is blocked by content hash;
near-duplicates are caught by the similarity stage.

## The funnel

Every stage runs before a human sees the task. You watch each one live on the
task page.

| Stage | What it does | What you can pre-check locally |
| --- | --- | --- |
| **Structure** | Required files, safe/unique paths, parseable `task.toml`. Deterministic and instant. | `tools/check_bundle.py` |
| **Similarity / dedup** | Embedding search over the corpus; too close to an existing task is a rejection. | Nothing — make the task genuinely novel. |
| **Oracle & nop** | Your reference solution and the untouched starting state both run on the real harness. The oracle must reach (near) full reward; **the untouched state must sit at its floor.** | Run `solve.sh` then `test.sh`, and run `test.sh` against a pristine `/app`. |
| **Quality check** | Blocking criteria plus an injection-hardened model judge reading the whole bundle against the rubric: clarity, specification completeness, whether the verifier genuinely measures the objective, anti-gaming adequacy. | `tools/check_bundle.py` covers only the blocking criteria. |
| **Difficulty probe** | Independent frontier-agent trials at the full time budget. Trivially saturated ⇒ too easy, fails. Effectively unsolvable also shows. | Nothing — this is what `difficultyExplanation` has to argue. |
| **Synthesis** | Terminal step. Confirms every earlier stage passed and finalises the outcome. Adds no new judgement. | — |

Failures are classified. A **verdict** failure is about the task and comes back
with a reason. An **infra** failure is a platform flake, never counts against
you, and is re-run.

### The blocking quality criteria

A well-formed task always satisfies these; failing one is a real, fixable
defect:

* `instruction.md` is real content, not a stub (a hard host-side floor, well
  below what a reviewer expects).
* `task.toml` declares a non-empty task name in its metadata.
* At least one file under `solution/`, or the oracle cannot run.
* At least one file under `tests/`, or the task cannot be graded.

Passing structure is the floor. The judge and the human reviewer are the real
bar.

## The review bar

A task that clears the funnel lands in the human review queue, oldest first.
Rejections and revision requests always come with a written reason, so you can
fix and resubmit. The bar is higher than "passes the funnel" — a reviewer weighs
every one of these:

1. **Fits a collection family.** Clearly one of Library clone, Product clone, ML
   engineering, Algorithmic optimization, and a *real instance* of it — not a
   contrived puzzle that happens to compile.
2. **Solvable by the reference.** `solution/` must drive the verifier to full
   reward. If it can't, the oracle stage fails and there is no task.
3. **Robust, multi-channel verification.** A single assertion is not enough.
   Grade from several independent angles — behaviour and outputs, invariants and
   edge cases, and where the family fits, a performance or quality metric — so a
   partial or lucky solution cannot pass. **Weak, one-shot verifiers are the most
   common reason a task that "works" still isn't keepable.**
4. **A visible / hidden verifier split.** Enough of the check in the open that
   the agent can aim and self-check; the decisive cases and grading logic sealed.
   State which is which in `verificationStrategy`.
5. **Not gameable.** The verifier measures the real objective, seals held-out
   data and grading logic under `tests/`, and defeats everything you listed in
   `anticipatedExploits`.
6. **Realistic.** Stands in for work a real engineer would do, in an environment
   that resembles a real codebase — not a synthetic drill. `motivation` should
   make that obvious.
7. **Novel.** Not a re-skin of an existing task or a well-known exercise a model
   has seen a thousand times. The gates block near-duplicates; the deeper bar is
   conceptual.
8. **Hard, but not impossible.** A frontier model must not trivially solve it —
   that is the whole point — yet it must be genuinely achievable, as your
   reference proves.

## Payout

Approved tasks are paid a flat per-task amount, recorded at approval and paid on
the normal cycle. Plan throughput around validation cost, and make each task
genuinely distinct — content-hash and similarity gates block resubmitted
duplicates.
