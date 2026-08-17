# project-orangutan

AI-training tasks: coding problems an agent attempts inside a sandbox, each
paired with a programmatic grader that scores the attempt.

A task is four artefacts and a write-up:

| artefact | what it is |
| --- | --- |
| `environment/` | the image and the workspace the agent starts in |
| `environment/workspace/SPEC.md` | the normative specification it works from |
| `solution/` | the reference implementation — the oracle |
| `verifier/` | the hidden test suite and the grader that runs it |
| `task.yaml` | every authoring-form field, the single source of the prose |

## Tasks

| slug | summary | expert est. | reference | seed |
| --- | --- | --- | --- | --- |
| [`minikv-snapshot-isolation-wal`](tasks/minikv-snapshot-isolation-wal) | Snapshot-isolated transactions and a crash-safe write-ahead log for an embedded key/value store | 4 h | 1.0000 pass | 0.1785 fail |

## Getting started

```bash
pip install pyyaml pytest

python3 tools/new_task.py my-new-task        # scaffold
python3 tools/validate_task.py --all         # check task.yaml
python3 tools/render_submission.py --all     # regenerate submission.md
```

To grade a task's reference solution and its untouched starting point:

```bash
python3 tasks/<slug>/verifier/grade.py --submission tasks/<slug>/solution --out /tmp/oracle.json
python3 tasks/<slug>/verifier/grade.py --submission tasks/<slug>/environment/workspace --out /tmp/seed.json
```

## Documentation

* [`CLAUDE.md`](CLAUDE.md) — start here: conventions and the rules that matter
* [`docs/form-schema.md`](docs/form-schema.md) — the authoring form, field by field
* [`docs/authoring-playbook.md`](docs/authoring-playbook.md) — the process, in order
* [`docs/verifier-patterns.md`](docs/verifier-patterns.md) — reusable grader mechanics
* [`docs/exploit-catalog.md`](docs/exploit-catalog.md) — how agents game graders
* [`docs/quality-checklist.md`](docs/quality-checklist.md) — before you submit
