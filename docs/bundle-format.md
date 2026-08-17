# The task bundle

Phase two of submission. A single `application/zip` archive, up to **512 MiB
compressed**, in the Terminal-Bench / Harbor task format. Everything the harness
needs to build the environment, run the reference solution, and grade the result
lives inside it.

```
my-task/
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

Four tables. `[metadata]` carries name and identity; `[verifier]`, `[agent]` and
`[environment]` carry grading, agent and sandbox configuration.

```toml
[metadata]
name = "minikv-snapshot-isolation-wal"
description = """..."""
tags = ["python", "storage", "transactions"]

[agent]
network_mode = "none"        # the rollout - "open" is refused here
timeout_sec = 14400

[verifier]
network_mode = "none"
timeout_sec = 2400

[environment]
network_mode = "open"        # the image build - fetching packages is normal
cpus = 2
memory_mb = 4096
storage_mb = 8192
gpus = 0
```

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

### Resources must agree with the draft

The `[environment]` figures (`cpus`, `memory_mb`, `storage_mb`, `gpus`) are
checked against the sandbox budget *and* against your draft. **The bundle may
ask for less than the draft, never more.** A stale value is rejected rather than
ignored.

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

In this repository's task, the visible half is `environment/tests/test_basic.py`
(13 tests, baked into the image, describing only behaviour that already exists)
and the hidden half is all of `tests/` (117 tests plus the grader). The visible
half is also scored at weight zero and used as a gate — see the nop-floor note
in `verifier-patterns.md` for why.

## Packaging

```bash
python3 tools/check_bundle.py tasks/<slug>    # structure + quality + cross-checks
python3 tools/build_bundle.py tasks/<slug>    # writes dist/<slug>.zip
```

`build_bundle.py` roots the archive at a single `<slug>/` directory, skips
`__pycache__` and `.pyc`, and preserves the executable bit on `tests/test.sh`
and `solution/solve.sh`.

Resubmitting a byte-for-byte identical bundle is blocked by content hash, and
near-duplicates are caught by the similarity stage — so make each task genuinely
new before you submit.
