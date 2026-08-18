#!/usr/bin/env bash
# Sealed verifier entrypoint.
#
# Prints a human-readable report, writes the numeric reward to /logs/reward.txt
# (plus score.json / junit.xml) and exits 0 only when the weighted score reaches
# the pass threshold.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPL_ROOT="${IMPL_ROOT:-/app}"
export LOG_DIR="${LOG_DIR:-/logs}"

# Locate the sealed check suite, whichever way the harness laid the tests out.
GRADER=""
for candidate in "$HERE" /tests /app/tests /verifier "$HERE/.."; do
    if [ -f "$candidate/grade.py" ] && [ -d "$candidate/checks" ]; then
        GRADER="$candidate"
        break
    fi
done

if [ -z "$GRADER" ]; then
    echo "FATAL: could not locate grade.py + checks/ (looked next to $HERE)" >&2
    echo "SCORE: 0.0"
    exit 2
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "FATAL: no python interpreter on PATH" >&2
    echo "SCORE: 0.0"
    exit 2
fi

mkdir -p "$LOG_DIR" 2>/dev/null || true

echo "== incremental engine verifier =="
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
