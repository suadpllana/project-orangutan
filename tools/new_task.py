#!/usr/bin/env python3
"""Scaffold a new task directory.

    python3 tools/new_task.py <lowercase-kebab-slug>

Creates the standard layout with the template `task.yaml` and placeholder
files, so the directory is already the shape `validate_task.py` expects.
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

GRADE_STUB = '''#!/usr/bin/env python3
"""Grade a submission for {slug}.

Start from tasks/minikv-snapshot-isolation-wal/verifier/grade.py - it already
implements collection into a scratch tree, the tokenised integrity scan,
per-category subprocesses with timeouts, a global deadline and JUnit parsing.
See docs/verifier-patterns.md for why each of those is there.
"""

raise SystemExit("grade.py not implemented for {slug}")
'''

RUN_STUB = """#!/usr/bin/env bash
# Entry point the harness calls after the agent's timeout expires.
#
#   run_verifier.sh [submission_dir] [report_path]
set -uo pipefail

SUBMISSION="${1:-/workspace}"
REPORT="${2:-/verifier/report.json}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$(dirname "$REPORT")"
exec python3 "$HERE/grade.py" --submission "$SUBMISSION" --out "$REPORT"
"""

SPEC_STUB = """# <project> v1.0 specification

This document is the contract the finished code must satisfy. It is normative:
the grader tests these statements and nothing else. Where this document says
MUST, a test asserts it.

## 1. ...

## N. Implementation constraints

* Language/runtime and standard library only; no network.
* Every file you add or change must live inside `<pkg>/`.
* The implementation must not read the environment, the process tree, the call
  stack, or test-runner state to decide how to behave.

<!-- State the failure model explicitly. State what is OUT of scope as clearly
     as what is in it. Every hidden test must trace back to a sentence here. -->
"""

README_STUB = """# {slug}

<!-- One paragraph: what the agent has to build. -->

| | |
| --- | --- |
| task family | feature development |
| verifier family | programmatic |
| expert estimate | 4 hours |
| network | none |
| graded tests | TODO |
| reference score | TODO |
| unmodified-seed score | TODO |

## Running it locally

```bash
python3 verifier/grade.py --submission solution --out /tmp/oracle.json
python3 verifier/grade.py --submission environment/workspace --out /tmp/seed.json
docker build -t {slug} environment/
```
"""

DOCKERFILE_STUB = """FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \\
    && apt-get install -y --no-install-recommends git ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "pytest==9.1.1"

WORKDIR /workspace
COPY workspace/ /workspace/

RUN git init -q \\
    && git config user.email author@example.com \\
    && git config user.name "task" \\
    && git add -A \\
    && git commit -qm "initial state"

# Build-time self-check: the starting point must pass its own tests, and the
# thing being asked for must still be missing.
RUN python -m pytest tests -q

CMD ["/bin/bash"]
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

    template = (REPO / "templates" / "task.template.yaml").read_text()
    template = template.replace('working_slug: ""', f"working_slug: {slug}")

    for directory in (
        "environment/workspace/tests",
        "solution",
        "verifier/tests",
    ):
        (root / directory).mkdir(parents=True)

    (root / "task.yaml").write_text(template)
    (root / "README.md").write_text(README_STUB.format(slug=slug))
    (root / "environment" / "Dockerfile").write_text(DOCKERFILE_STUB)
    (root / "environment" / "workspace" / "SPEC.md").write_text(SPEC_STUB)
    (root / "verifier" / "grade.py").write_text(GRADE_STUB.format(slug=slug))

    run_verifier = root / "verifier" / "run_verifier.sh"
    run_verifier.write_text(RUN_STUB)
    run_verifier.chmod(run_verifier.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    print(f"created tasks/{slug}/")
    print()
    print("next:")
    print("  1. write environment/workspace/SPEC.md  (normative, complete)")
    print("  2. build the seed: working code that is honestly inadequate")
    print("  3. write verifier/tests/ before the solution")
    print("  4. write solution/ and run the grader - expect it to fail")
    print("  5. grade the seed; check the gap")
    print("  6. fill in task.yaml, then validate + render")
    print()
    print("  docs/authoring-playbook.md has the long version")
    return 0


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
