# project-orangutan

Self-contained software-engineering tasks that a frontier coding agent works on
autonomously, each graded objectively by a sealed verifier.

Every task is authored in two parts:

| part | what it is | where it lives |
| --- | --- | --- |
| **draft** | structured metadata describing the task | `tasks/<slug>/draft.yaml` |
| **bundle** | a ZIP in the Terminal-Bench / Harbor format holding the environment, verifier and reference solution | `tasks/<slug>/bundle/` |

The draft is filled in first and is versioned; the bundle is uploaded through a
quarantined channel and, once it passes inspection, submits the task
automatically. `docs/submission-funnel.md` has the flow and the review bar.

## Tasks

| slug | family | summary | expert est. | oracle | nop |
| --- | --- | --- | --- | --- | --- |
| [`minikv-snapshot-isolation-wal`](tasks/minikv-snapshot-isolation-wal) | Library clone | Snapshot-isolated transactions and a crash-safe write-ahead log for an embedded key/value store | 4 h | 1.0000 pass | 0.0000 fail |

## Getting started

```bash
pip install pyyaml pytest

python3 tools/new_task.py my-new-task         # scaffold draft + bundle skeleton
python3 tools/validate_draft.py --all         # bounds, enums, resource floors
python3 tools/check_bundle.py --all           # the structure + quality gates
python3 tools/render_submission.py --all      # regenerate submission.md
python3 tools/build_bundle.py --all           # dist/<slug>.zip, ready to upload
```

To reproduce the funnel's oracle & nop stage for a task, see that task's README.

## Documentation

* [`CLAUDE.md`](CLAUDE.md) — start here: conventions and the ten rules that matter
* [`docs/draft-fields.md`](docs/draft-fields.md) — the draft, field by field
* [`docs/bundle-format.md`](docs/bundle-format.md) — required paths, `task.toml`, network phases
* [`docs/submission-funnel.md`](docs/submission-funnel.md) — submission, the funnel, the review bar
* [`docs/authoring-playbook.md`](docs/authoring-playbook.md) — the process, in order
* [`docs/verifier-patterns.md`](docs/verifier-patterns.md) — reusable grader mechanics
* [`docs/exploit-catalog.md`](docs/exploit-catalog.md) — how agents game graders
* [`docs/quality-checklist.md`](docs/quality-checklist.md) — before you submit
