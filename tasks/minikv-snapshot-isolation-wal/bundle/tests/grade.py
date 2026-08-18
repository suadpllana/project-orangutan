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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
IMPL_ROOT = Path(os.environ.get("IMPL_ROOT", "/app"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "/logs"))

# Continuous score in [0, 1]; the run passes when it reaches this. Declared in
# task.toml as [verifier] pass_threshold and repeated here so the grader is
# self-contained.
PASS_THRESHOLD = 0.85

# name -> (test file, weight, per-category wall-clock limit in seconds)
#
# Ordered cheapest-and-most-diagnostic first: if the global deadline bites, the
# categories that explain *why* a submission failed have already run.  The
# reference solution finishes the whole list in about four seconds, so every
# limit here is a runaway-detector, not a budget anyone should feel.
#
# `regression` carries weight 0 on purpose.  It re-runs the visible suite, which
# the starting state already passes, so scoring it would hand the untouched
# workspace free reward and lift the nop run off its floor.  Instead its pass
# ratio multiplies the final score: breaking behaviour that already worked costs
# you proportionally, and the multiplier keeps the reward continuous rather than
# introducing a cliff.
CATEGORIES = [
    ("regression", "test_regression.py", 0.00, 25),
    ("api", "test_api.py", 0.12, 40),
    ("isolation", "test_isolation.py", 0.27, 40),
    ("compaction", "test_compaction.py", 0.11, 100),
    ("threads", "test_threads.py", 0.05, 50),
    ("durability", "test_durability.py", 0.28, 75),
    ("performance", "test_performance.py", 0.17, 120),
]
MULTIPLIER_CATEGORIES = {"regression"}

TEST_FILES = [test_file for _name, test_file, _w, _t in CATEGORIES] + [
    "crash_child.py"
]

# Every category timing out at once would overrun the harness' verifier
# timeout, and a killed verifier reports nothing at all.  Cap the whole run
# instead, so a partial score always reaches the report.
#
# The per-category caps sum to 450s and the deadline is 480s, both inside the
# bundle's 600s [verifier] timeout_sec, which is inside the draft's 1200s.
# Measured: the reference grades in ~5s; the untouched starting state - the
# slowest thing that still finishes - in ~250s once its two runaway categories
# hit their caps.
DEFAULT_DEADLINE = 480.0

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
def clear_stale_rewards() -> None:
    """Delete any reward artefact that existed before this run.

    The agent can write to /logs. Without this, pre-creating reward.txt with
    1.0 would be a way to be scored without solving anything.
    """
    for directory in reward_dirs():
        for name in ("reward.txt", "reward.json", "score.txt", "score.json",
                     "junit.xml"):
            path = directory / name
            try:
                if path.exists():
                    os.chmod(path, 0o644)
                    path.unlink()
            except OSError:
                print(f"WARNING: could not clear a pre-existing {path}", flush=True)


def reward_dirs() -> List[Path]:
    """Every directory the harness might look in for a reward file.

    The rejection that taught us this said: "Your verifier completed without
    writing a reward file (verifier/reward.txt or reward.json) - every trial
    must produce one." Where the harness mounts the sealed suite is not
    knowable from inside the bundle, so write to all of them. They are cheap.
    """
    candidates = [
        LOG_DIR,                 # whatever [verifier] reward_file points at
        Path("/logs"),
        Path("/verifier"),
        Path("/tests"),
        HERE,                    # next to grade.py, wherever that landed
        HERE.parent,
        Path.cwd(),
        Path("/tmp"),            # last resort: somewhere always writable
    ]
    seen, unique = set(), []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def publish_reward(score: float, report: Dict | None = None) -> None:
    """Write reward.txt AND reward.json everywhere the harness might read.

    Called once with 0.0 before any grading starts, so that a crash, a hang or
    a harness-side timeout still leaves a reward file behind, and again with the
    real score at the end. Never raises: a failure to write one location must
    not stop the others.
    """
    score = max(0.0, min(1.0, float(score)))
    text = f"{score:.6f}\n"
    blob = json.dumps(
        {
            "reward": score,
            "score": score,
            "passed": bool(report["passed"]) if report and "passed" in report else score >= PASS_THRESHOLD,
            "threshold": PASS_THRESHOLD,
        },
        indent=2,
    )
    detail = json.dumps(report, indent=2) if report is not None else blob

    written = []
    for directory in reward_dirs():
        for name, payload in (
            ("reward.txt", text),
            ("reward.json", blob),
            ("score.txt", text),
            ("score.json", detail),
        ):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / name).write_text(payload)
                if name == "reward.txt":
                    written.append(str(directory))
            except (OSError, ValueError):
                continue

    # Say where the reward landed. A run that reaches here having written
    # nowhere is a read-only-mount problem, and silence would hide it.
    if written:
        print(f"reward {score:.6f} written to: {', '.join(written)}", flush=True)
    else:
        print(
            "ERROR: could not write a reward file anywhere - every candidate "
            "directory was unwritable",
            flush=True,
        )


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
        (tree / "_tests").mkdir()
        for test_file in TEST_FILES:
            shutil.copy2(HERE / test_file, tree / "_tests" / test_file)

        total_weight = 0.0
        earned = 0.0
        all_green = True
        multiplier = 1.0
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
                if name in MULTIPLIER_CATEGORIES:
                    multiplier = 0.0
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
            if name in MULTIPLIER_CATEGORIES:
                multiplier = ratio
            if ratio < 1.0:
                all_green = False
            print(
                f"  {name:<12} {outcome['passed']:>3}/{outcome['total']:<3} "
                f"({outcome['seconds']:>6.1f}s)"
                + ("  [multiplier]" if name in MULTIPLIER_CATEGORIES else "")
                + ("  TIMEOUT" if outcome["timed_out"] else ""),
                flush=True,
            )

        # Breaking behaviour the starting point already had scales the whole
        # score down, rather than costing a fixed slice of it.
        raw = earned / total_weight if total_weight else 0.0
        report["regression_multiplier"] = round(multiplier, 4)
        report["raw_score"] = round(raw, 4)
        report["score"] = round(raw * multiplier, 4)
        report["binary_pass"] = all_green and report["score"] == 1.0
        return report
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, default=IMPL_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)
    args = parser.parse_args()

    clear_stale_rewards()
    # Publish a floor immediately. Every trial must produce a reward file; if
    # this process is killed, hangs, or raises on the next line, the harness
    # still finds one rather than reporting that the verifier produced nothing.
    publish_reward(0.0)

    print(f"implementation root: {args.submission}")
    print(f"log dir:             {LOG_DIR}")
    print(f"reward locations:    {', '.join(str(d) for d in reward_dirs())}")
    print()

    try:
        report = grade(args.submission.resolve(), args.deadline)
    except BaseException as exc:  # noqa: BLE001 - the reward must survive anything
        traceback.print_exc()
        publish_reward(
            0.0,
            {"score": 0.0, "passed": False, "grader_error": repr(exc)},
        )
        print()
        print("=" * 68)
        print("SCORE: 0.0000")
        print(f"THRESHOLD: {PASS_THRESHOLD:.2f}")
        print("RESULT: FAIL (grader error)")
        print("=" * 68)
        return 1

    report["threshold"] = PASS_THRESHOLD
    report["passed"] = (
        not report["integrity_error"] and report["score"] >= PASS_THRESHOLD
    )
    report["reward"] = report["score"]

    publish_reward(report["score"], report)
    if args.out is not None:
        try:
            args.out.write_text(json.dumps(report, indent=2))
        except OSError:
            pass

    print()
    if report["integrity_error"]:
        print(f"INTEGRITY VIOLATION: {report['integrity_error']}")
    print("=" * 68)
    print(f"SCORE: {report['score']:.4f}")
    print(f"THRESHOLD: {PASS_THRESHOLD:.2f}")
    print(f"BINARY_PASS: {str(report['binary_pass']).lower()}")
    print(f"RESULT: {'PASS' if report['passed'] else 'FAIL'}")
    print("=" * 68)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
