# The task bundle

Phase two of submission. A single `application/zip` archive, up to **512 MiB
compressed**, in the Terminal-Bench / Harbor task format. Everything the harness
needs to build the environment, run the reference solution, and grade the result
lives inside it.

**The paths below are relative to the archive root.** `my-task/` is the task
directory on your disk, whose *contents* you zip — it is **not** a level inside
the archive. A ZIP whose entries read `my-task/task.toml` is rejected at
inspection with *"required file missing"*, because the inspector looks for
`task.toml`. This cost one upload artifact; `tools/build_bundle.py` now asserts
the five required paths exist at the root of the ZIP it just wrote.

**It cost a second one for a reason `build_bundle.py` cannot see.** macOS
auto-expands a downloaded `.zip`, so the thing left on disk is a folder;
re-compressing that folder in Finder puts the wrapper straight back and adds a
`__MACOSX/` tree and `.DS_Store` besides. The archive that was built correctly
and the archive that was uploaded are then different files with the same name.
Verify the one you are about to upload:

```bash
python3 tools/verify_zip.py dist/<slug>.zip          # audit any .zip
python3 tools/verify_zip.py <downloaded>.zip --fix   # rewrite it flat in place
```

`--fix` drops the wrapper and the macOS artefacts and rebuilds the entries with
the executable bits intact. On the rejected `pkgsolve` upload it reproduced the
original archive's sha256 exactly, which is how we know the build was never at
fault. **Upload the file as downloaded; do not expand it first.**

```
my-task/                 <- your directory; zip its CONTENTS, not itself
├── task.toml            # [metadata], [verifier], [agent], [environment]
├── instruction.md       # the problem statement the agent reads
├── environment/
│   └── Dockerfile       # builds /app - deps baked in, no runtime network
├── tests/
│   └── test.sh          # the sealed verifier entrypoint (grader + held-out data)
└── solution/
    └── solve.sh         # the reference solution entrypoint the oracle runs
```

## The five required paths

The **structure stage** is deterministic and rejects a bundle that is missing
any of them, has unsafe or duplicate paths, or whose `task.toml` is not
parseable TOML. The set is exact:

| Path | Why it must exist under this name |
| --- | --- |
| `task.toml` | Present and valid TOML. |
| `instruction.md` | Present. |
| `environment/Dockerfile` | Present. |
| `tests/test.sh` | **The grader runs exactly this script.** A non-empty `tests/` directory alone is not enough. |
| `solution/solve.sh` | The canonical entrypoint the oracle runs. Likewise required by name. |

Everything else in the bundle is yours to organise. In this repository the extra
files sit beside the entrypoints: `tests/grade.py` plus the held-out test
modules, `solution/<package>/` holding the reference implementation, and the
starting workspace next to the Dockerfile in `environment/`.

## `task.toml`

**This shape is transcribed from an approved bundle, not inferred.** Guessing it
cost two rejections; the second, "resource declaration mismatch", was a
`network_mode` key in `[environment]`, which does not belong there.

```toml
[metadata]
name = "minikv-snapshot-isolation-wal"
title = "minikv: snapshot-isolated transactions over a crash-safe write-ahead log"
description = """..."""
tags = ["library-clone", "storage", "transactions", "python"]
collection_family = "library_clone"      # snake_case here; title case in the form
task_family = "feature_development"
verifier_family = "programmatic"
difficulty = "hard"
expert_time_estimate_hours = 4
version = "1.0.0"

[agent]
network_mode = "none"        # the rollout - "open" is refused here
timeout_sec = 14000          # below the draft's envelope, never equal to it

[verifier]
entrypoint = "tests/test.sh"
network_mode = "none"
timeout_sec = 600            # below the draft's envelope
reward_file = "/logs/reward.txt"
pass_threshold = 0.85

[environment]
dockerfile = "environment/Dockerfile"
build_context = "environment"
cpus = 2
memory_mb = 4096
storage_mb = 8192
gpus = 0
```

Three things worth calling out, all of them things we got wrong by guessing:

* **`[environment]` describes the build, not a network posture.** It declares
  `dockerfile` and `build_context` and the four resource figures. An extra
  `network_mode` there is rejected as *"resource declaration mismatch"*.
* **`[metadata]` carries the families**, in `snake_case` — `library_clone`,
  not `Library clone` — plus `title`, `difficulty`,
  `expert_time_estimate_hours` and `version`.
* **`[verifier]` declares the reward contract**: `entrypoint`, `reward_file` and
  `pass_threshold`. The grader must actually write that file; see below.

## The reward contract

`[verifier] reward_file` is not decorative. The grader writes the numeric score
to `/logs/reward.txt` (and, for good measure, `/logs/score.txt`,
`/logs/score.json` and `/logs/junit.xml`), and exits 0 exactly when the score
reaches `pass_threshold`. Two details matter:

* **Every trial must produce a reward file, whatever happens.** Write a `0.0`
  floor before grading starts and the real score at the end, to every plausible
  location (`LOG_DIR`, `/logs`, `/verifier`, `/tests`, beside `grade.py`, its
  parent, CWD, `/tmp`) under **both** names (`reward.txt` *and* `reward.json`).
  Declaring `reward_file` is not enough: a run that dies before writing it is
  rejected as *"your verifier completed without writing a reward file"*. Wrap
  the grading run in `except BaseException` so a crash still publishes, and
  print which locations were written so a read-only mount is visible.
* **Delete stale reward artefacts before grading.** The agent can write to
  `/logs`. A `reward.txt` containing `1.0`, left behind before the verifier
  runs, is otherwise indistinguishable from a perfect score. Do this *before*
  the `0.0` floor, not after.
* **The score is continuous and the threshold is below 1.0.** The approved task
  uses `0.85`. Pick a threshold that cannot be reached without doing the core of
  the work — check it against your category weights.

## Locating things at runtime

`test.sh` and `solve.sh` in the approved bundle do not assume a layout. They
resolve `IMPL_ROOT` (default `/app`) and `LOG_DIR` (default `/logs`) from the
environment, and search a list of candidate directories for the grader and the
reference sources:

```bash
for candidate in "$HERE" /tests /app/tests /verifier "$HERE/.."; do
    if [ -f "$candidate/grade.py" ]; then GRADER="$candidate"; break; fi
done
```

Copy that habit. It costs five lines and removes a whole class of "worked
locally, failed in the harness".

### Network posture is per phase, and the phases are read separately

* **`[environment] network_mode`** — the image build. A build that fetches
  packages is normal and is **not gated**.
* **`[agent] network_mode`** — the rollout. This is the one phase the network
  policy governs: `none` and `allowlist` are admitted, `open` is **refused**.
* **`[verifier] network_mode`** — grading.

Two rejections to avoid:

* Writing `[metadata] open_internet_justification` without also stating
  `[agent] network_mode` explicitly. The rollout's egress is read from that
  field alone, so the trial would otherwise run sealed and fail for a reason
  that is not your task's difficulty.
* A rollout the file seals (`none`) while your draft asks for `allowlist` hosts.
  The two must agree.

### Resources must ask for strictly less than the draft

The `[environment]` figures (`cpus`, `memory_mb`, `storage_mb`, `gpus`) are
checked against the sandbox budget *and* against your draft. "May ask for less,
never more" means **less**: a bundle whose resources exactly equalled its draft
was rejected as `resource declaration mismatch` three times running, and the
same bundle cleared intake the moment they were lowered.

```toml
# draft: cpuMillis 2000, memoryMb 4096, storageMb 8192, gpuCount 0
cpus = 1            # not 2
memory_mb = 2048    # not 4096
storage_mb = 4096   # not 8192
gpus = 0            # the one field that stays equal - it cannot go lower
```

Declare what the task actually needs and measure to back it: pin the suite to one
core with `taskset -c 0` before claiming `cpus = 1`. The same discipline already
applied to the timeouts, which the approved bundle sets below its draft too.

`tools/check_bundle.py` reproduces all of these cross-checks locally.

## What `/app` is

`environment/` becomes `/app`. The Dockerfile is the build context's recipe: it
copies the starting workspace into `/app` and bakes in every dependency, because
the rollout has no network unless you asked for `allowlist`.

Two things worth doing in the Dockerfile beyond the copy:

* **A build-time self-check.** Assert that the starting state passes its own
  visible tests *and* that the thing being asked for is still missing. A seed
  that accidentally ships a working implementation is a task with no gap, and
  you want to learn that at build time, not at the oracle stage.
* **One clean git commit**, so the agent can diff its own work.

## The entrypoints

`solution/solve.sh` must drive the verifier to full reward — that is what the
oracle stage measures. Make it fail loudly: install the reference, then import
it and exercise the main path, so a broken drop-in fails in the oracle step
rather than silently in the verifier.

`tests/test.sh` is the sealed verifier. Exit 0 for pass, non-zero for fail, and
print a machine-readable summary so the reward is visible in the harness log as
well as in whatever report file you write. Resolve paths relative to the script
itself (`$(dirname "${BASH_SOURCE[0]}")`) rather than assuming a working
directory.

## The visible / hidden split

This is a review-bar requirement, not a nicety. Give the agent enough of the
check to aim at — a public portion that states what "done" means — while keeping
the decisive held-out cases and the grading logic sealed under `tests/`. The
agent should be able to self-check against the visible part and still be unable
to overfit the hidden part. **Say which is which in `verificationStrategy`.**

In this repository's task, the visible half is
`environment/public_tests/test_basic.py` (13 tests, baked into the image,
describing only behaviour that already exists) and the hidden half is all of
`tests/` (117 tests plus the grader). **Name the visible directory
`public_tests/`, not `tests/`** — the approved bundle does, and it keeps the
agent's copy from ever being confused with the sealed suite the harness mounts.
The Dockerfile also defensively `rm -rf`s `/app/tests`, `/app/solution`,
`/app/Dockerfile` and `/app/task.toml` after the copy, so the verifier and the
reference cannot be reachable from inside the container whatever the build
context turns out to be. The visible
half is also scored at weight zero, with its pass ratio multiplying the final
score — see the nop-floor note
in `verifier-patterns.md` for why.

## Packaging

```bash
python3 tools/check_bundle.py tasks/<slug>    # structure + quality + cross-checks
python3 tools/build_bundle.py tasks/<slug>    # writes dist/<slug>.zip
```

`build_bundle.py` writes entries at the archive root (no `<slug>/` wrapper),
skips `__pycache__` and `.pyc`, preserves the executable bit on `tests/test.sh`
and `solution/solve.sh`, and re-opens the finished ZIP to assert the five
required paths are really there before it reports success.

Resubmitting a byte-for-byte identical bundle is blocked by content hash, and
near-duplicates are caught by the similarity stage — so make each task genuinely
new before you submit.
