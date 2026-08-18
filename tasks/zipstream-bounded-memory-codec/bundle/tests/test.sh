#!/usr/bin/env bash
# Sealed verifier entrypoint.
#
# Publishes a 0.0 reward before anything else runs, so a verifier that is
# killed, hangs, or dies on its first line still leaves a reward behind; then
# hands over to grade.py, which publishes the real score.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPL_ROOT="${IMPL_ROOT:-/app}"
export LOG_DIR="${LOG_DIR:-/logs}"

# Locate the sealed suite, whichever way the harness laid the tests out.
GRADER=""
for candidate in "$HERE" /tests /app/tests /verifier "$HERE/.."; do
    if [ -f "$candidate/grade.py" ] && [ -f "$candidate/child_codec.py" ]; then
        GRADER="$candidate"
        break
    fi
done

PY="$(command -v python3 || command -v python)"

# The 0.0 floor, written everywhere and under both names, before grading starts.
if [ -n "$PY" ]; then
    "$PY" - <<'FLOOR'
import json, os, tempfile
log_dir = os.environ.get("LOG_DIR", "/logs")
here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
blob = json.dumps({"score": 0.0, "reward": 0.0, "passed": False, "stage": "verifier started"})
written = []
seen = []
for directory in (log_dir, "/logs", "/verifier", "/tests", os.getcwd(), tempfile.gettempdir()):
    if not directory or directory in seen:
        continue
    seen.append(directory)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        continue
    for name in ("reward.txt", "reward.json", "score.txt", "score.json"):
        path = os.path.join(directory, name)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(blob if name.endswith(".json") else "0.000000\n")
            written.append(path)
        except OSError:
            pass
print("reward floor 0.0 written to %d location(s)" % (len(written),))
if not written:
    print("WARNING: no writable reward location was found")
FLOOR
else
    echo "FATAL: no python interpreter on PATH" >&2
    echo "SCORE: 0.0"
    exit 2
fi

if [ -z "$GRADER" ]; then
    echo "FATAL: could not locate grade.py + child_codec.py (looked next to $HERE)" >&2
    echo "SCORE: 0.0"
    exit 2
fi

echo "== zipstream verifier =="
echo "implementation: $IMPL_ROOT"
"$PY" -c "import sys; print('interpreter:', sys.version.split()[0])"
echo

"$PY" "$GRADER/grade.py"
STATUS=$?

echo
if [ "$STATUS" -eq 0 ]; then
    echo "verifier: PASS"
else
    echo "verifier: FAIL (exit $STATUS)"
fi
exit "$STATUS"
