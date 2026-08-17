# Pre-submit checklist

Run top to bottom. Anything unticked is a reason not to submit yet.

## Mechanical

```bash
python3 tools/validate_task.py --all
python3 tools/render_submission.py --all --check
python3 tasks/<slug>/verifier/grade.py --submission tasks/<slug>/solution     --out /tmp/oracle.json
python3 tasks/<slug>/verifier/grade.py --submission tasks/<slug>/environment/workspace --out /tmp/seed.json
docker build -t <slug> tasks/<slug>/environment/
```

- [ ] `validate_task.py` reports no errors (a blank `collection_family` warning
      is expected — it is a dropdown).
- [ ] `submission.md` is not stale.
- [ ] Every field is inside its character limit, and none is within 10% of the
      cap by accident.
- [ ] The image builds, and its build-time self-check passes.

## The grader

- [ ] The reference solution scores **1.0000** and `binary_pass: true`, from a
      clean checkout, with no files left over from development.
- [ ] The unmodified seed scores **well below** the reference and
      `binary_pass: false`.
- [ ] The seed's score is **not 0.0** — if it is, the categories are too coarse
      to show partial progress.
- [ ] At least one deliberately-wrong variant has been graded and landed where
      you predicted.
- [ ] A submission with no package at all, and one with a syntax error, both
      produce a report rather than a crash.
- [ ] The integrity scan has been shown to fire on a real cheat **and** to stay
      quiet on a docstring that mentions the same words.
- [ ] Per-category timeouts sum to less than `verifier_timeout_s`, or the global
      deadline covers the difference and the field has been raised with a note.
- [ ] The whole grader run is well inside its budget for a *correct* submission
      (the minikv reference: ~4 s against 2400 s).

## The specification

- [ ] Every hidden test traces back to a sentence in `SPEC.md`. Walk the list.
- [ ] Every "MUST" in `SPEC.md` has at least one test behind it.
- [ ] The failure model is stated (process crash vs machine crash, what counts
      as durable, what is out of scope).
- [ ] Things that are *not* required are stated as explicitly as things that
      are.
- [ ] Filenames, limits and exception names the grader depends on are named in
      the spec.
- [ ] The implementation constraints — where files may live, what may be
      imported, what may not be inspected — are stated, so no defence is a
      surprise.
- [ ] A competent reader could implement it without guessing your API names.

## The tests

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

## The prose

- [ ] OBJECTIVE is complete enough to work from without the repository.
- [ ] ENVIRONMENT SUMMARY names the image, the packages, the tree, the resources
      and the failure model.
- [ ] DIFFICULTY EXPLANATION argues both halves — why it is hard *and* why it is
      solvable in the estimated time.
- [ ] ORACLE STRATEGY describes the solution you actually ran, with its measured
      score.
- [ ] VERIFICATION STRATEGY describes the grader you actually ran, including
      test counts per category.
- [ ] BINARY SUCCESS CONDITION is a condition, not a paragraph — someone should
      be able to evaluate it from `report.json` alone.
- [ ] PARTIAL SCORE STRATEGY gives the weights, the formula, and predicted
      scores for the plausible failure modes.
- [ ] ANTICIPATED EXPLOITS names a countermeasure for every exploit listed.
- [ ] `notes` records anything you deviated from the defaults on, and why.

## Honesty

- [ ] Every number in the prose was measured, not estimated.
- [ ] Anything unverified (dropdown option lists, undocumented limits) is marked
      as unverified rather than asserted.
- [ ] Known weaknesses are in `notes` rather than omitted.
