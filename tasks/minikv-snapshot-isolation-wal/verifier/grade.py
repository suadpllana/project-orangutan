#!/usr/bin/env python3
"""Grade a minikv submission.

Usage:  python3 grade.py --submission <workspace> [--out report.json]

The grader never runs anything from inside the submission directory.  It copies
``minikv/**/*.py`` into a scratch tree it controls, drops its own pristine test
files next to it, and runs each category as a separate pytest process with its
own wall-clock limit, so a deadlock or a hang costs one category rather than
the whole run.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE / "tests"

# name -> (test file, weight, per-category wall-clock limit in seconds)
#
# Ordered cheapest-and-most-diagnostic first: if the global deadline bites, the
# categories that explain *why* a submission failed have already run.  The
# reference solution finishes the whole list in about four seconds, so every
# limit here is a runaway-detector, not a budget anyone should feel.
CATEGORIES = [
    ("regression", "test_regression.py", 0.10, 180),
    ("api", "test_api.py", 0.10, 240),
    ("isolation", "test_isolation.py", 0.25, 300),
    ("compaction", "test_compaction.py", 0.10, 300),
    ("threads", "test_threads.py", 0.05, 300),
    ("durability", "test_durability.py", 0.25, 420),
    ("performance", "test_performance.py", 0.15, 420),
]

# Every category timing out at once would overrun the harness' verifier
# timeout, and a killed verifier reports nothing at all.  Cap the whole run
# instead, so a partial score always reaches the report.
DEFAULT_DEADLINE = 2100.0

# Identifiers that only appear when an implementation is trying to notice it is
# being tested, or is reaching outside the process for its behaviour.  Comments
# and string literals are excluded before matching, so documentation is free.
FORBIDDEN_NAMES = {
    "pytest",
    "unittest",
    "PYTEST_CURRENT_TEST",
    "_getframe",
    "currentframe",
    "stack",
    "extract_stack",
    "getouterframes",
    "argv",
    "environ",
    "getenv",
    "putenv",
    "modules",
    "gettrace",
    "settrace",
}
# ``stack`` and ``modules`` are common words; require the attribute owner too.
QUALIFIED_ONLY = {
    "stack": {"inspect", "traceback"},
    "modules": {"sys"},
    "argv": {"sys"},
    "environ": {"os"},
    "extract_stack": {"traceback"},
}


class Integrity(Exception):
    """Raised when the submission breaks the ground rules of the task."""


# ----------------------------------------------------------------------
# collecting the submission
# ----------------------------------------------------------------------
def collect_package(submission: Path, tree: Path) -> List[Path]:
    source = submission / "minikv"
    if not source.is_dir():
        raise Integrity("submission has no minikv/ package")

    target = tree / "minikv"
    target.mkdir(parents=True)
    collected = []
    for path in sorted(source.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name == "conftest.py":
            # A conftest inside the package would be picked up by pytest and
            # could rewrite the graded tests; it is not implementation code.
            continue
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        collected.append(relative)

    if not (target / "__init__.py").exists():
        raise Integrity("minikv/__init__.py is missing")
    return collected


def code_identifiers(path: Path):
    """Yield (name, owner) for every NAME token outside comments and strings."""
    with open(path, "rb") as handle:
        try:
            tokens = list(tokenize.tokenize(handle.readline))
        except (tokenize.TokenError, SyntaxError) as exc:
            raise Integrity(f"{path.name} does not tokenise: {exc}") from exc

    previous_name = None
    saw_dot = False
    for token in tokens:
        if token.type == tokenize.NAME:
            yield token.string, (previous_name if saw_dot else None), token.start[0]
            previous_name = token.string
            saw_dot = False
        elif token.type == tokenize.OP and token.string == ".":
            saw_dot = True
        elif token.type not in (
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.COMMENT,
        ):
            previous_name = None
            saw_dot = False


def check_integrity(tree: Path, files: List[Path]) -> None:
    for relative in files:
        path = tree / "minikv" / relative
        for name, owner, line in code_identifiers(path):
            if name not in FORBIDDEN_NAMES:
                continue
            allowed_owners = QUALIFIED_ONLY.get(name)
            if allowed_owners is not None and owner not in allowed_owners:
                continue
            raise Integrity(
                f"minikv/{relative}:{line} references {name!r}; the store must not "
                f"inspect the test runner, the environment or the call stack"
            )


# ----------------------------------------------------------------------
# running the tests
# ----------------------------------------------------------------------
def run_category(tree: Path, test_file: str, timeout: int) -> Dict:
    junit = tree / f"junit-{test_file}.xml"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    command = [
        sys.executable,
        "-m",
        "pytest",
        str(tree / "_tests" / test_file),
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        f"--rootdir={tree}",
        f"--confcutdir={tree / '_tests'}",
        f"--junitxml={junit}",
        "-q",
        "--tb=line",
        "-W",
        "ignore::DeprecationWarning",
    ]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(tree),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
        output = proc.stdout[-8000:] + proc.stderr[-4000:]
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or b"").decode("utf-8", "replace")[-8000:]
    elapsed = time.monotonic() - started

    result = {
        "timed_out": timed_out,
        "seconds": round(elapsed, 1),
        "total": 0,
        "passed": 0,
        "failures": [],
        "output_tail": output[-4000:],
    }
    if timed_out or not junit.exists():
        return result

    root = ET.parse(junit).getroot()
    for case in root.iter("testcase"):
        result["total"] += 1
        problems = [
            child
            for child in case
            if child.tag in ("failure", "error", "skipped")
        ]
        bad = [c for c in problems if c.tag in ("failure", "error")]
        if not bad:
            # A skip counts as a pass: tests only skip when the implementation
            # legitimately has nothing for them to look at.
            result["passed"] += 1
            continue
        message = (bad[0].get("message") or "").strip().replace("\n", " ")
        result["failures"].append(
            {"test": case.get("name", "?"), "message": message[:400]}
        )
    return result


# ----------------------------------------------------------------------
def grade(submission: Path, deadline_seconds: float = DEFAULT_DEADLINE) -> Dict:
    report = {
        "task": "minikv-snapshot-isolation-wal",
        "binary_pass": False,
        "score": 0.0,
        "integrity_error": None,
        "deadline_hit": False,
        "categories": {},
    }
    deadline = time.monotonic() + deadline_seconds

    tree = Path(tempfile.mkdtemp(prefix="minikv-grade-"))
    try:
        try:
            files = collect_package(submission, tree)
            check_integrity(tree, files)
        except Integrity as exc:
            report["integrity_error"] = str(exc)
            return report

        report["collected_files"] = sorted(str(f) for f in files)
        shutil.copytree(TESTS_DIR, tree / "_tests")

        total_weight = 0.0
        earned = 0.0
        all_green = True
        for name, test_file, weight, timeout in CATEGORIES:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                report["deadline_hit"] = True
                report["categories"][name] = {
                    "weight": weight,
                    "skipped_no_time": True,
                    "total": 0,
                    "passed": 0,
                    "ratio": 0.0,
                    "failures": [],
                }
                total_weight += weight
                all_green = False
                print(f"  {name:<12} skipped - out of verifier time", flush=True)
                continue

            outcome = run_category(tree, test_file, min(timeout, remaining))
            outcome["weight"] = weight
            if outcome["timed_out"]:
                report["deadline_hit"] = report["deadline_hit"] or remaining < timeout
            ratio = outcome["passed"] / outcome["total"] if outcome["total"] else 0.0
            outcome["ratio"] = round(ratio, 4)
            report["categories"][name] = outcome
            total_weight += weight
            earned += weight * ratio
            if ratio < 1.0:
                all_green = False
            print(
                f"  {name:<12} {outcome['passed']:>3}/{outcome['total']:<3} "
                f"({outcome['seconds']:>6.1f}s)"
                + ("  TIMEOUT" if outcome["timed_out"] else ""),
                flush=True,
            )

        report["score"] = round(earned / total_weight, 4) if total_weight else 0.0
        report["binary_pass"] = all_green and report["score"] == 1.0
        return report
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("report.json"))
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)
    args = parser.parse_args()

    print(f"grading {args.submission}")
    report = grade(args.submission.resolve(), args.deadline)
    args.out.write_text(json.dumps(report, indent=2))

    if report["integrity_error"]:
        print(f"INTEGRITY VIOLATION: {report['integrity_error']}")
    print(f"score       {report['score']:.4f}")
    print(f"binary_pass {report['binary_pass']}")
    print(f"report      {args.out}")
    return 0 if report["binary_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
