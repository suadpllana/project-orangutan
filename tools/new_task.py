#!/usr/bin/env python3
"""Scaffold a new task directory and bundle skeleton.

    python3 tools/new_task.py <lowercase-kebab-slug>

Creates the layout `validate_draft.py` and `check_bundle.py` expect, with all
five required bundle paths present so the structure gate passes from the start.
Nothing is overwritten: the command refuses to run if the directory exists.
"""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

TASK_TOML = '''[metadata]
name = "{slug}"
description = """
TODO - one paragraph on what the agent has to build.
"""
tags = []

[agent]
# The rollout. This is the phase the network policy governs: "none" and
# "allowlist" are admitted, "open" is refused. Must agree with the draft's
# networkRequirements.mode, and must be stated explicitly.
network_mode = "none"
timeout_sec = 14400

[verifier]
network_mode = "none"
timeout_sec = 2400

[environment]
# The image build. Fetching packages here is normal and is not gated.
network_mode = "open"
# Checked against the sandbox budget AND the draft: may ask for less, never more.
cpus = 2
memory_mb = 4096
storage_mb = 8192
gpus = 0
'''

INSTRUCTION = """# TODO: the task, in one line

`/app` holds TODO. Your job is to TODO.

Run the visible tests with `python -m pytest tests -q` from `/app`. They must
keep passing.

The visible tests are deliberately only the floor: they describe the behaviour
that exists today, not the behaviour this document requires. The graded suite is
much larger and is not shipped in the image. Use the specification below, not
the visible tests, as your definition of done.

---

# TODO v1.0 specification

This section is the contract. It is normative: the grader tests these statements
and nothing else. Where it says MUST, a test asserts it.

## 1. TODO

## N. Implementation constraints

* Standard library only; no network.
* Every file you add or change must live inside `/app/TODO/`.
* The implementation must not read the environment, the process tree, the call
  stack, or test-runner state to decide how to behave. The grader scans for this
  and scores zero if it finds it.

<!-- State the failure model explicitly. State what is OUT of scope as clearly
     as what is in it. Every hidden test must trace back to a sentence here. -->
"""

DOCKERFILE = """# Builds /app. Everything the agent needs is baked in here: the rollout has no
# network, so nothing may be fetched at runtime.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \\
    && apt-get install -y --no-install-recommends git ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "pytest==9.1.1"

WORKDIR /app
# COPY <package>/ /app/<package>/
COPY tests/ /app/tests/

RUN git init -q \\
    && git config user.email author@example.com \\
    && git config user.name "task" \\
    && git add -A \\
    && git commit -qm "initial state"

# Build-time self-check: the starting point must pass its own visible tests, and
# the thing being asked for must still be missing.
RUN python -m pytest tests -q

CMD ["/bin/bash"]
"""

TEST_SH = """#!/usr/bin/env bash
# Sealed verifier entrypoint. The grader runs exactly this script.
#
# Exit status is 0 when the binary success condition is met and 1 otherwise.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMISSION="${SUBMISSION_DIR:-/app}"
REPORT="${REPORT_PATH:-/tmp/report.json}"

mkdir -p "$(dirname "$REPORT")"
python3 "${HERE}/grade.py" --submission "$SUBMISSION" --out "$REPORT"
STATUS=$?

python3 - "$REPORT" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print(f"REWARD {report['score']:.4f}")
print(f"BINARY_PASS {str(report['binary_pass']).lower()}")
PY

exit $STATUS
"""

GRADE_STUB = '''#!/usr/bin/env python3
"""Grade a submission for {slug}.

Start from tasks/minikv-snapshot-isolation-wal/bundle/tests/grade.py - it
already implements collection into a grader-owned scratch tree, the tokenised
integrity scan, per-category subprocesses with timeouts, a global deadline,
JUnit parsing, and a weight-0 regression gate that keeps the nop run at its
floor. See docs/verifier-patterns.md for why each of those is there.
"""

raise SystemExit("grade.py not implemented for {slug}")
'''

SOLVE_SH = """#!/usr/bin/env bash
# Reference solution entrypoint. The oracle run executes exactly this script and
# must then reach full reward.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${APP_DIR:-/app}"

# TODO: install the reference implementation into $APP, then exercise it here so
# a broken drop-in fails loudly in the oracle step rather than in the verifier.
echo "solve.sh not implemented"
exit 1
"""

README = """# {slug}

<!-- One paragraph: what the agent has to build. -->

| | |
| --- | --- |
| collection family | Library clone |
| task family | feature_development |
| verifier family | programmatic |
| expert estimate | 4 hours |
| network | none |
| graded tests | TODO |
| oracle | TODO |
| nop | TODO |

## Reproducing the oracle & nop stage

```bash
python3 tools/check_bundle.py tasks/{slug}
docker build -t {slug} tasks/{slug}/bundle/environment/
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    args = parser.parse_args()

    slug = args.slug
    if not SLUG_RE.match(slug) or not 3 <= len(slug) <= 80:
        return fail(f"slug must be lowercase-kebab, 3-80 chars: {slug!r}")

    root = REPO / "tasks" / slug
    if root.exists():
        return fail(f"{root.relative_to(REPO)} already exists")

    template = (REPO / "templates" / "draft.template.yaml").read_text()
    template = template.replace('workingSlug: ""', f"workingSlug: {slug}")

    bundle = root / "bundle"
    for directory in ("environment/tests", "tests", "solution"):
        (bundle / directory).mkdir(parents=True)

    (root / "draft.yaml").write_text(template)
    (root / "README.md").write_text(README.format(slug=slug))
    (bundle / "task.toml").write_text(TASK_TOML.format(slug=slug))
    (bundle / "instruction.md").write_text(INSTRUCTION)
    (bundle / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (bundle / "tests" / "grade.py").write_text(GRADE_STUB.format(slug=slug))

    for relative, content in (
        ("tests/test.sh", TEST_SH),
        ("solution/solve.sh", SOLVE_SH),
    ):
        path = bundle / relative
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"created tasks/{slug}/")
    print()
    print("next:")
    print("  1. write bundle/instruction.md  (normative, complete, self-contained)")
    print("  2. build the seed under bundle/environment/: working code that is")
    print("     honestly inadequate, plus the visible tests it already passes")
    print("  3. write bundle/tests/ - the held-out suite - BEFORE the solution")
    print("  4. write bundle/solution/ and run the grader; expect it to fail")
    print("  5. grade the untouched seed; drive it to its floor")
    print("  6. fill in draft.yaml, then validate + check + render")
    print()
    print("  docs/authoring-playbook.md has the long version")
    return 0


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
