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

## The ceiling at the other end, which cost the next attempt

The fix above was right about the direction and wrong about the number. Raising
`agentTimeoutSec` to 43,200 does not fail at Difficulty evaluation — **it never
gets that far, because the draft form refuses to store it**:

> Above 37000s (~10h) — leave room for build, verify, teardown, which share a
> trial's 14h wall-clock limit. A larger build or verify budget lowers this; the
> exact bound is the whole per-trial envelope, checked at intake.

So the admissible band is **(14,400, 37,000]** and it is narrower at the top
than this document assumed. The error was arithmetic, and it is worth naming
precisely because the same move will be tempting again:

```
we assumed:  50,400 − 1,200 verifier − 1,800 build/teardown = 47,400 available
             (from which 43,200 looked conservative)
actually:    50,400 − 1,200 verifier − 37,000 agent         = 12,200 reserved
```

**The platform holds back ~12,200 s for build and teardown, not 1,800.** The
1,800 s figure was a guess about how long a Docker build takes, used as though
it were the platform's reserve. It is not: the reserve is the platform's, it is
roughly seven times the guess, and nothing in the guideline states it — the only
place the real bound appears is the form's own validation message. **Never infer
one side of the per-trial envelope by subtracting your own estimate from the
other side.**

## The numbers to use

The binding constraint is the per-trial pool, and both budgets come out of it:

```
agentTimeoutSec + verifierTimeoutSec + (build + teardown) <= 50,400 s  (14 h)
agentTimeoutSec <= 37,000 s                        # enforced by the form itself
```

| field | value | why |
| --- | --- | --- |
| `agentTimeoutSec` | **36,000** (10 h) | largest round value the form accepts; 1,000 s clear of the ceiling and 2.5x the 4 h that was rejected |
| `verifierTimeoutSec` | 1,200 | the form default; the grader should finish in seconds. **Raising it lowers the agent ceiling** — the message says so explicitly |
| `[agent] timeout_sec` in `task.toml` | **34,800** | strictly below the draft, as always |
| `expertTimeEstimateHours` | honest, however large | descriptive metadata, not a gate — see below |

Do not shave the verifier budget to buy agent seconds. The trade is real (a
smaller verify budget raises the ceiling) but 1,000 s of slack is worth more
than the ~35 minutes it would buy, and a verifier that gets killed reports no
reward at all.

### What to do when the expert estimate exceeds 10 h

`pkgsolve` is the case: its phase breakdown sums to 12 h of measured expert
time, and the agent may now be given at most 10.3. These cannot be reconciled
and **they do not need to be** — the guideline is explicit that
`expertTimeEstimateHours` "is NOT a gate (long-horizon is enforced on the agent
time budget), so give an honest figure however large."

So keep the honest estimate and take the whole band. Do **not** shave the
estimate down to match the budget: that is falsifying the one field the
guideline asks you to be candid about, and a reviewer comparing it against the
phase breakdown in `difficultyExplanation` will find the discrepancy. Say in the
prose that the cap is the platform's, not your judgement of the work.

`tools/validate_draft.py` now **errors** on `agentTimeoutSec <= 14400`, on
`agentTimeoutSec > 37000`, and on `agentTimeoutSec < expertTimeEstimateHours *
3600` *while that estimate is still purchasable*; past the ceiling it warns
instead of demanding the impossible. `tools/check_bundle.py` applies the same
ceiling to `task.toml`'s `[agent] timeout_sec`, because the bundle's value is
the effective one.

## ⚠ The trap that will cost you the next attempt

**Intake compares your bundle against the draft the platform STORED, which you
cannot read back from the repository.** Raising `agentTimeoutSec` in
`draft.yaml` changes nothing on its own.

```
1. Open the draft form.
2. Set agentTimeoutSec to 36000. If the form rejects it, read the message: it
   names the ceiling, and the ceiling moves when the build or verify budget
   does.
3. SAVE, then RELOAD the page and read the value back.
4. Only then upload the bundle.
```

If the form edit does not save, `task.toml`'s `timeout_sec = 34800` exceeds the
stored `14400` and the bundle is rejected with *"agentTimeoutSec exceeds
draft"* — a different error, same wasted attempt. This is the same failure mode
recorded under rule 4 in `CLAUDE.md`, which cost an upload on `minikv`.

### There is no bundle-side hedge

It is tempting to leave `task.toml` at `timeout_sec = 14000` — safely under the
stored `14400` whatever happens in the form — and raise only the draft, so that
the gate sees 10 h and the "exceeds draft" check can never fire. It does not
work, and the guideline says why: the floor is on the **effective**
`agentTimeoutSec`, and the effective value is what the agent is actually given,
which is the bundle's. A bundle asking for 4 h is a 4 h trial no matter what the
draft says.

So the form edit is unavoidable. Both numbers have to move, the draft first.

## Is a longer budget enough, or is the task too small?

The message says "too short **for the collection**". The declared horizon is
what the gate reads, but if a reviewer would call the task a two-hour exercise,
a 10-hour budget is a claim the work does not support. Ask honestly:

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

- [ ] `agentTimeoutSec` is **not** 14,400 and **not above 37,000**. 36,000
      unless there is a stated reason for less.
- [ ] `agentTimeoutSec >= expertTimeEstimateHours * 3600`, comfortably — or, if
      the estimate is above ~10 h, the budget is at the 36,000 cap and the prose
      says the cap is the platform's.
- [ ] `verifierTimeoutSec` has not been raised: it comes out of the same
      envelope and raising it lowers the agent ceiling.
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

All three shipped `agentTimeoutSec: 14400`; all three were then raised to
43,200, **which the form refuses**; all three now carry **36,000** with
`task.toml` at **34,800**.

| task | expert estimate | note |
| --- | --- | --- |
| `pkgsolve-resolver-explanations` | 7 h → **12 h** | raised to the honest end-to-end figure, with the phase breakdown now in `difficultyExplanation`. The estimate stays above the 10 h budget on purpose — the cap is the platform's |
| `minikv-snapshot-isolation-wal` | 4 h | left as measured. It is the smallest of the three and may still read as short for the collection; if it is rejected here, the fix is scope, not the number |
| `zipstream-bounded-memory-codec` | 7 h | budget raised only; its author should revisit the estimate and the phase breakdown |
