#!/usr/bin/env bash
# Sealed verifier entrypoint.
#
# Prints a human-readable report, writes the numeric reward everywhere the
# harness might read it, and exits 0 only when the weighted score reaches the
# pass threshold declared in task.toml.
#
# EVERY TRIAL MUST PRODUCE A REWARD FILE. This has now been the reason for two
# rejections, both reading:
#
#     Your verifier completed without writing a reward file
#     (verifier/reward.txt or reward.json) - every trial must produce one.
#
# Read that path carefully: `verifier/reward.txt` is RELATIVE and carries a
# directory component, `reward.json` does not. They are two paths under one root
# the message never names. Writing to the absolute `/verifier` covers that root
# only if it happens to be `/` -- which is why the second attempt failed the
# same way as the first.
#
# So this script writes both names at every plausible root AND inside a
# `verifier/` subdirectory of every plausible root, before it does anything
# else, and again after grading. It then prints exactly which locations took the
# file and which refused it, so a third failure is a measurement rather than
# another guess.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPL_ROOT="${IMPL_ROOT:-/app}"
export LOG_DIR="${LOG_DIR:-/logs}"

# Roots, most specific first. Unset variables collapse to nothing and are
# skipped. Only these variables are read, and only their values are printed --
# the environment is never dumped.
REWARD_ROOTS="
${LOG_DIR:-}
${REWARD_DIR:-}
${VERIFIER_DIR:-}
${OUTPUT_DIR:-}
${OUTPUTS_DIR:-}
${RESULTS_DIR:-}
${RESULT_DIR:-}
${TEST_OUTPUT_DIR:-}
/logs
/verifier
/tests
/output
/outputs
/results
/app
/workspace
$HERE
$HERE/..
$PWD
$PWD/..
/tmp
/var/tmp
/
"

REWARD_WROTE=""
REWARD_REFUSED=""

write_reward() {
    # $1 = score, printed verbatim into reward.txt / reward.json
    REWARD_WROTE=""
    REWARD_REFUSED=""
    for root in $REWARD_ROOTS; do
        [ -n "$root" ] || continue
        for sub in "" "/verifier"; do
            d="$root$sub"
            if ! mkdir -p "$d" 2>/dev/null; then
                REWARD_REFUSED="$REWARD_REFUSED $d"
                continue
            fi
            if printf '%s\n' "$1" > "$d/reward.txt" 2>/dev/null; then
                printf '{"reward": %s, "score": %s}\n' "$1" "$1" \
                    > "$d/reward.json" 2>/dev/null || true
                printf '%s\n' "$1" > "$d/score.txt" 2>/dev/null || true
                REWARD_WROTE="$REWARD_WROTE $d"
            else
                REWARD_REFUSED="$REWARD_REFUSED $d"
            fi
        done
    done
}

report_reward() {
    if [ -n "$REWARD_WROTE" ]; then
        echo "reward file written to:$REWARD_WROTE"
    else
        echo "ERROR: no candidate directory accepted a reward file" >&2
    fi
    [ -n "$REWARD_REFUSED" ] && echo "         refused by:$REWARD_REFUSED"
    return 0
}

have_reward() {
    for root in $REWARD_ROOTS; do
        [ -n "$root" ] || continue
        for sub in "" "/verifier"; do
            [ -s "$root$sub/reward.txt" ] && return 0
            [ -s "$root$sub/reward.json" ] && return 0
        done
    done
    return 1
}

# The floor, before anything else can go wrong.
write_reward "0.000000"

echo "== pkgsolve verifier =="
echo "implementation: $IMPL_ROOT"
echo "log dir:        $LOG_DIR"
echo "working dir:    $PWD"
echo "suite dir:      $HERE"
report_reward

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

"$PY" -c "import sys; print('interpreter:', sys.version.split()[0])"
echo

"$PY" "$GRADER/grade.py"
STATUS=$?

# Belt and braces. grade.py publishes the real score itself; if it somehow did
# not, the 0.0 floor written above is still on disk. Confirm that, and if even
# that is gone, write it again and say so loudly.
if have_reward; then
    :
else
    echo "WARNING: no reward file found after grading; writing a 0.0 floor" >&2
    write_reward "0.000000"
    report_reward
fi

echo
if [ "$STATUS" -eq 0 ]; then
    echo "verifier: PASS"
else
    echo "verifier: FAIL (exit $STATUS)"
fi
exit "$STATUS"
