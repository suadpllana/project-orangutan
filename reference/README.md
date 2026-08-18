# Reference material

## `approved/incremental-memo-engine/`

**A task bundle that was approved.** Not ours — supplied as an authoring
reference. It is the only ground truth in this repository for what the platform
actually accepts, and it settled several questions that prose could not:

| question | what the bundle shows |
| --- | --- |
| Where do the required paths sit in the ZIP? | At the **archive root** — `task.toml`, not `my-task/task.toml` |
| What does `[metadata]` carry? | `name`, `title`, `description`, `tags`, `collection_family`, `task_family`, `verifier_family`, `difficulty`, `expert_time_estimate_hours`, `version` |
| Which case for the families? | **snake_case** in the bundle (`library_clone`); title case in the draft form (`Library clone`) |
| What does `[verifier]` declare? | `entrypoint`, `network_mode`, `timeout_sec`, `reward_file`, `pass_threshold` |
| What does `[environment]` declare? | `dockerfile`, `build_context`, `cpus`, `memory_mb`, `storage_mb`, `gpus` — and **no `network_mode`** |
| How does the grader report a score? | Writes `reward_file`; exits 0 only at or above `pass_threshold` |
| Where do the visible tests live? | `environment/public_tests/`, never `tests/` |
| Where does the reference implementation live? | `solution/reference/<pkg>/` |

Read `task.toml`, `tests/test.sh`, `tests/grade.py` and `solution/solve.sh`
before writing your own. Copy the *shape*; never copy the content — the
similarity stage rejects near-duplicates, and the whole point is a novel task.

Worth studying beyond the schema:

* `tests/test.sh` and `solution/solve.sh` resolve `IMPL_ROOT` / `LOG_DIR` from
  the environment and **search a list of candidate directories** rather than
  assuming the harness's layout.
* `tests/grade.py` **deletes stale reward artefacts before grading**, because the
  agent can write to `/logs`; it runs each category in its own subprocess with
  its own timeout; and it writes the score to four places.
* `environment/Dockerfile` uses `COPY . /app/` and then defensively
  `rm -rf /app/tests /app/solution /app/Dockerfile /app/task.toml`, so the sealed
  verifier and the reference can never be reachable from inside the container
  whatever the build context turns out to be.
* Its per-category caps sum to 440 s inside a declared 600 s verifier budget.
