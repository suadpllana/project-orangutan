#!/usr/bin/env python3
"""Sealed grader for the `incremental` task.

Each category runs in its own subprocess so that a crash, a hang or a blown
stack in one costs only that category.  Results are merged into a weighted
score which is written to every reward location the harness might read, plus a
JUnit report and a human-readable summary.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, "checks")
IMPL_ROOT = os.environ.get("IMPL_ROOT", "/app")
LOG_DIR = os.environ.get("LOG_DIR", "/logs")

PASS_THRESHOLD = 0.85

# Per-category wall-clock caps.  The reference finishes every category in about
# a second, so these are 15x-150x headroom; they sum to 440s, well inside the
# declared 600s verifier budget, so a pathological submission burns its own
# category and no more.  `performance` gets the largest share because its own
# time score interpolates all the way out to 120s before it reads as a failure.
CATEGORIES = [
    ("api_basics", "c01_api_basics.py", 0.08, 15),
    ("invalidation", "c02_invalidation.py", 0.14, 25),
    ("early_cutoff", "c03_early_cutoff.py", 0.16, 25),
    ("dynamic_deps", "c04_dynamic_deps.py", 0.08, 15),
    ("errors_cycles", "c05_errors_cycles.py", 0.12, 25),
    ("durability", "c06_durability.py", 0.14, 35),
    ("deep_chain", "c07_deep_chain.py", 0.05, 60),
    ("performance", "c08_performance.py", 0.08, 150),
    ("randomized", "c09_randomized.py", 0.15, 90),
]


def run_category(name, script, timeout, workdir):
    out_path = os.path.join(workdir, "%s.json" % name)
    env = dict(os.environ)
    env["IMPL_ROOT"] = IMPL_ROOT
    env["PYTHONPATH"] = os.pathsep.join([IMPL_ROOT, CHECKS, env.get("PYTHONPATH", "")]).strip(os.pathsep)
    env.setdefault("PYTHONHASHSEED", "0")
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(CHECKS, script), out_path],
            cwd=IMPL_ROOT,
            env=env,
            timeout=timeout,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        stderr, returncode = proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "category": name,
            "checks": [],
            "error": "timed out after %ds" % (timeout,),
            "seconds": time.time() - started,
        }

    elapsed = time.time() - started
    if not os.path.exists(out_path):
        return {
            "category": name,
            "checks": [],
            "error": "produced no result (exit %s)\n%s" % (returncode, (stderr or "")[-2000:]),
            "seconds": elapsed,
        }
    with open(out_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    data["seconds"] = elapsed
    if stderr:
        data["stderr"] = stderr[-2000:]
    return data


def junit(categories, path):
    def escape(text):
        return (
            str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
        )

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<testsuites>"]
    for entry in categories:
        checks = entry["result"].get("checks", [])
        failures = sum(1 for c in checks if c["earned"] < c["points"])
        lines.append(
            '  <testsuite name="%s" tests="%d" failures="%d" time="%.3f">'
            % (escape(entry["name"]), max(len(checks), 1), failures if checks else 1,
               entry["result"].get("seconds", 0.0))
        )
        if not checks:
            lines.append('    <testcase name="category"><failure message="%s"/></testcase>'
                         % escape(entry["result"].get("error", "no results")))
        for check in checks:
            lines.append('    <testcase name="%s">' % escape(check["name"]))
            if check["earned"] < check["points"]:
                lines.append('      <failure message="%s"/>' % escape(check["detail"] or "failed"))
            lines.append("    </testcase>")
        lines.append("  </testsuite>")
    lines.append("</testsuites>")
    try:
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
    except OSError:
        pass


def main():
    if not os.path.isdir(CHECKS):
        print("FATAL: the sealed check suite is missing at %s" % (CHECKS,))
        return 2

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        workdir = LOG_DIR
    except OSError:
        workdir = HERE

    # Never let an artefact that was lying around before the verifier ran be
    # mistaken for this run's result.
    for stale in ("reward.txt", "score.txt", "score.json", "junit.xml"):
        for directory in (LOG_DIR, HERE):
            path = os.path.join(directory, stale)
            try:
                if os.path.exists(path):
                    os.chmod(path, 0o644)
                    os.unlink(path)
            except OSError:
                print("WARNING: could not clear a pre-existing %s" % (path,))

    seed = os.environ.get("GRADER_SEED") or str(int.from_bytes(os.urandom(4), "big"))
    os.environ["GRADER_SEED"] = seed
    print("grader seed: %s" % (seed,))
    print("implementation root: %s" % (IMPL_ROOT,))
    print()

    results = []
    total = 0.0
    for name, script, weight, timeout in CATEGORIES:
        result = run_category(name, script, timeout, workdir)
        checks = result.get("checks", [])
        possible = sum(c["points"] for c in checks)
        earned = sum(c["earned"] for c in checks)
        fraction = (earned / possible) if possible else 0.0
        total += weight * fraction
        results.append({"name": name, "weight": weight, "fraction": fraction, "result": result})
        print("%-14s weight %.2f  score %5.1f%%  (%.2f/%.2f pts, %.1fs)" % (
            name, weight, 100 * fraction, earned, possible, result.get("seconds", 0.0)))
        if result.get("error"):
            print("    !! %s" % (result["error"].splitlines()[0] if result["error"] else "",))
        for check in checks:
            mark = "PASS" if check["earned"] >= check["points"] else (
                "PART" if check["earned"] > 0 else "FAIL")
            print("    [%s] %s" % (mark, check["name"]))
            if check["detail"]:
                for line in str(check["detail"]).strip().splitlines()[-6:]:
                    print("           %s" % (line,))
        print()

    total = round(min(1.0, max(0.0, total)), 6)
    passed = total >= PASS_THRESHOLD

    print("=" * 68)
    print("SCORE: %.4f" % (total,))
    print("THRESHOLD: %.2f" % (PASS_THRESHOLD,))
    print("RESULT: %s" % ("PASS" if passed else "FAIL",))
    print("=" * 68)

    report = {
        "score": total,
        "reward": total,
        "passed": passed,
        "threshold": PASS_THRESHOLD,
        "seed": seed,
        "categories": [
            {"name": r["name"], "weight": r["weight"], "fraction": r["fraction"],
             "checks": r["result"].get("checks", []), "error": r["result"].get("error")}
            for r in results
        ],
    }
    for path, payload in (
        (os.path.join(LOG_DIR, "reward.txt"), "%.6f\n" % (total,)),
        (os.path.join(LOG_DIR, "score.txt"), "%.6f\n" % (total,)),
        (os.path.join(LOG_DIR, "score.json"), json.dumps(report, indent=2)),
        (os.path.join(HERE, "reward.txt"), "%.6f\n" % (total,)),
    ):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(payload)
        except OSError as exc:
            if os.path.commonpath([os.path.abspath(path), os.path.abspath(LOG_DIR)]) == os.path.abspath(LOG_DIR):
                print("WARNING: could not write %s (%s)" % (path, exc))
    junit(results, os.path.join(LOG_DIR, "junit.xml"))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
