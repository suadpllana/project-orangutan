#!/usr/bin/env bash
# Sealed verifier entrypoint.
#
# Prints a human-readable report, writes the numeric reward to every location
# the harness might read (reward.txt AND reward.json, under /logs, /verifier,
# /tests and beside this script) and exits 0 only when the weighted score
# reaches the pass threshold declared in task.toml.
#
# EVERY TRIAL MUST PRODUCE A REWARD FILE. This script therefore writes a 0.0
# floor before it does anything else, and re-checks afterwards that at least one
# reward file exists -- a verifier that dies without one is reported as
# "completed without writing a reward file", which is a verifier bug, not a
# submission failure.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPL_ROOT="${IMPL_ROOT:-/app}"
export LOG_DIR="${LOG_DIR:-/logs}"

REWARD_DIRS="$LOG_DIR /logs /verifier /tests $HERE"

write_reward() {
    # $1 = score
    for d in $REWARD_DIRS; do
        mkdir -p "$d" 2>/dev/null || continue
        printf '%s\n' "$1" > "$d/reward.txt" 2>/dev/null || true
        printf '{"reward": %s, "score": %s}\n' "$1" "$1" > "$d/reward.json" 2>/dev/null || true
    done
}

have_reward() {
    for d in $REWARD_DIRS; do
        [ -s "$d/reward.txt" ] && return 0
        [ -s "$d/reward.json" ] && return 0
    done
    return 1
}

write_reward "0.000000"

# Locate the sealed suite, whichever way the harness laid the tests out.
GRADER=""
for candidate in "$HERE" /tests /app/tests /verifier "$HERE/.."; do
    if [ -f "$candidate/grade.py" ] && [ -f "$candidate/test_preference.py" ]; then
        GRADER="$candidate"
        break
    fi
done

if [ -z "$GRADER" ]; then
    echo "FATAL: could not locate grade.py + the check suite (looked next to $HERE)" >&2
    echo "SCORE: 0.0"
    exit 2
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "FATAL: no python interpreter on PATH" >&2
    echo "SCORE: 0.0"
    exit 2
fi

echo "== pkgsolve verifier =="
echo "implementation: $IMPL_ROOT"
echo "log dir:        $LOG_DIR"
"$PY" -c "import sys; print('interpreter:', sys.version.split()[0])"
echo

"$PY" "$GRADER/grade.py"
STATUS=$?

# Belt and braces: if the grader somehow exited without publishing, the 0.0
# floor written above is still on disk. Confirm it, and say so loudly if not.
if have_reward; then
    :
else
    echo "WARNING: no reward file found after grading; writing a 0.0 floor" >&2
    write_reward "0.000000"
fi

echo
if [ "$STATUS" -eq 0 ]; then
    echo "verifier: PASS"
else
    echo "verifier: FAIL (exit $STATUS)"
fi
exit "$STATUS"
