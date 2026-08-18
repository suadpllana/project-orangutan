# The Difficulty evaluation stage

The last automated gate before human review, and the one that rejected
`pkgsolve-resolver-explanations` on attempt 2 with **every other stage passed**:

```
Bundle structure      passed
Similarity screening  passed
Rubric review         passed
Oracle & nop          passed
Difficulty evaluation FAILED
```

> Automated validation didn't pass — **Too short for the collection — not
> long-horizon.**

---

## What that message is about, and what it is not

It is **not** about the prose in `difficultyExplanation`. Rubric review — the
stage that reads your prose — had already passed. The words *long-horizon* and
*too short* are about the **time budget the task declares**, and the guideline
says exactly where that is read from:

> `expertTimeEstimateHours` … is NOT a gate (**long-horizon is enforced on the
> agent time budget**), so give an honest figure however large.

So the gate is **`resourceEstimate.agentTimeoutSec`**. Nothing else.

## The mistake, in one line

**We left `agentTimeoutSec` at the form default of `14400` (4 hours) and
believed we were fine because the guideline's floor is 7,200 s.**

The 7,200 s floor is the *absolute admissibility* floor. It is not the bar this
collection applies. A 4-hour budget was rejected as not long-horizon.

### Three specific errors that produced it

1. **We treated the form default as a recommendation.** `14400` is what the form
   ships with. All three tasks in this repository carried it unchanged. It is a
   placeholder, and for a long-horizon benchmark it is close to the bottom of
   the admissible range.

2. **We read "ask for what the task needs and no more" as a reason to stay
   low.** That sentence is about *CPU, memory and storage* — resources that are
   contended and that starve a trial if over-claimed. The agent time budget is
   not contended in the same way: it is the horizon the collection is built
   around. Being frugal there is not modesty, it is disqualification.

3. **We gave the agent less time than we said a human expert needs.**
   `pkgsolve` declared `expertTimeEstimateHours: 7` and `agentTimeoutSec: 14400`
   — four hours for work we had just certified takes an expert seven. That is
   incoherent on its face and it went unnoticed because
   `tools/validate_draft.py` only warned below *half* the estimate. It is an
   **error** now.

## The numbers to use

The binding constraint is the per-trial pool:

```
agentTimeoutSec + verifierTimeoutSec + (build + teardown) <= 50,400 s  (14 h)
```

Budgeting `1,800 s` for build and teardown and `1,200 s` for the verifier leaves
**47,400 s** for the agent. Take a round number well inside it:

| field | value | why |
| --- | --- | --- |
| `agentTimeoutSec` | **43,200** (12 h) | clearly long-horizon; leaves 4,200 s of slack in the pool |
| `verifierTimeoutSec` | 1,200 | the form default; the grader should finish in seconds |
| `[agent] timeout_sec` in `task.toml` | **42,000** | strictly below the draft, as always |
| `expertTimeEstimateHours` | honest, however large | descriptive metadata, not a gate |

`tools/validate_draft.py` now **errors** on `agentTimeoutSec <= 14400` and on
`agentTimeoutSec < expertTimeEstimateHours * 3600`, and warns below 43,200.

## ⚠ The trap that will cost you the next attempt

**Intake compares your bundle against the draft the platform STORED, which you
cannot read back from the repository.** Raising `agentTimeoutSec` in
`draft.yaml` changes nothing on its own.

```
1. Open the draft form.
2. Set agentTimeoutSec to 43200.
3. SAVE, then RELOAD the page and read the value back.
4. Only then upload the bundle.
```

If the form edit does not save, `task.toml`'s `timeout_sec = 42000` exceeds the
stored `14400` and the bundle is rejected with *"agentTimeoutSec exceeds
draft"* — a different error, same wasted attempt. This is the same failure mode
recorded under rule 4 in `CLAUDE.md`, which cost an upload on `minikv`.

## Is a longer budget enough, or is the task too small?

The message says "too short **for the collection**". The declared horizon is
what the gate reads, but if a reviewer would call the task a two-hour exercise,
a 12-hour budget is a claim the work does not support. Ask honestly:

* **Does the work decompose into independent sittings?** If each requirement can
  be built and checked alone, the task is a checklist and the horizon is
  fictional. Interacting requirements are what make the hours real — see rule 10
  in `CLAUDE.md`.
* **Can an agent get most of the score from the first hour's work?** If the
  correctness categories alone clear the pass threshold, the long tail is
  optional and the task is short whatever the budget says. Weight the categories
  so that abandoning any one capability fails. `pkgsolve` puts 0.69 on its three
  interacting laws against a 0.92 threshold, and two measured
  partial implementations score 0.8857 and 0.8724 — both fail.
* **Do you have measured evidence of the phases?** `difficultyExplanation`
  should name them with the time each took *you*. That is what turns "it's hard"
  into an argument, and it is what a reviewer weighs.

If the answers are no, raising the number is dishonest and the fix is scope, not
metadata.

## Checklist before submitting

- [ ] `agentTimeoutSec` is **not** 14,400. 43,200 unless there is a stated
      reason for less.
- [ ] `agentTimeoutSec >= expertTimeEstimateHours * 3600`, comfortably.
- [ ] `agentTimeoutSec + verifierTimeoutSec + 1800 <= 50400`.
- [ ] `task.toml` `[agent] timeout_sec` is strictly below the draft's value.
- [ ] The raised value has been **saved in the form and read back** after a
      reload.
- [ ] `difficultyExplanation` names the phases and the measured time each took,
      and says what a partial implementation scores — with numbers you ran.
- [ ] The pass threshold and category weights make abandoning any one
      capability a failure.
- [ ] `python3 tools/validate_draft.py --all` is clean apart from the expected
      "confirm the raised value is saved in the form" warning.

## Status of the three tasks in this repository

All three shipped `agentTimeoutSec: 14400`; all three have been raised to
43,200 with `task.toml` at 42,000.

| task | expert estimate | note |
| --- | --- | --- |
| `pkgsolve-resolver-explanations` | 7 h → **12 h** | raised to the honest end-to-end figure, with the phase breakdown now in `difficultyExplanation` |
| `minikv-snapshot-isolation-wal` | 4 h | left as measured. It is the smallest of the three and may still read as short for the collection; if it is rejected here, the fix is scope, not the number |
| `zipstream-bounded-memory-codec` | 7 h | budget raised only; its author should revisit the estimate and the phase breakdown |
