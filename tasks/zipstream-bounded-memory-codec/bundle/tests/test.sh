#!/usr/bin/env bash
# Sealed verifier entrypoint.
#
# EVERY TRIAL MUST PRODUCE A REWARD FILE. That requirement, not the grading, is
# what this script is shaped around:
#
#   * the 0.0 floor is written in POSIX shell, before anything else, so it does
#     not depend on a python interpreter being on PATH;
#   * it is written to every directory the harness might read, under both
#     names, and into a `verifier/` subdirectory of each -- the platform's own
#     error message names `verifier/reward.txt` and `reward.json`, so both the
#     absolute and the relative reading of that path are covered;
#   * a trap re-asserts the reward on EXIT, INT, TERM and HUP, so a verifier
#     that is killed part-way still leaves a number behind;
#   * the score is parsed back out of the grader's own report and re-written
#     here in shell, so the reward does not depend on grade.py's writer either.
#
# Nothing in here ever deletes a reward file. A stale value is overwritten in
# place, so there is no instant at which the trial has no reward on disk.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPL_ROOT="${IMPL_ROOT:-/app}"
export LOG_DIR="${LOG_DIR:-/logs}"

REWARD_BASES="$LOG_DIR /logs /verifier /tests /output /results $HERE $HERE/.. $(pwd) /tmp"
REWARD_NAMES="reward.txt reward.json score.txt score.json"

write_reward() {
    # $1 = the score, formatted; writes it everywhere, creating nothing it
    # cannot, and never removing anything.
    _score="$1"
    _seen=""
    for _base in $REWARD_BASES; do
        [ -n "$_base" ] || continue
        for _dir in "$_base" "$_base/verifier"; do
            case " $_seen " in *" $_dir "*) continue ;; esac
            _seen="$_seen $_dir"
            mkdir -p "$_dir" 2>/dev/null || continue
            for _name in $REWARD_NAMES; do
                case "$_name" in
                    *.json)
                        printf '{"reward": %s, "score": %s}\n' "$_score" "$_score" \
                            > "$_dir/$_name" 2>/dev/null || true
                        ;;
                    *)
                        printf '%s\n' "$_score" > "$_dir/$_name" 2>/dev/null || true
                        ;;
                esac
            done
        done
    done
}

count_rewards() {
    _found=0
    for _base in $REWARD_BASES; do
        for _dir in "$_base" "$_base/verifier"; do
            [ -s "$_dir/reward.txt" ] && _found=$((_found + 1))
            [ -s "$_dir/reward.json" ] && _found=$((_found + 1))
        done
    done
    echo "$_found"
}

FINAL_SCORE="0.000000"

on_exit() {
    # Whatever happens -- a clean finish, a signal, a killed grader -- the trial
    # ends with a reward file on disk.
    write_reward "$FINAL_SCORE"
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

write_reward "0.000000"
echo "reward floor 0.0 published to $(count_rewards) file(s) before grading"

# Locate the sealed suite, whichever way the harness laid the tests out.
GRADER=""
for candidate in "$HERE" /tests /app/tests /verifier "$HERE/.."; do
    if [ -f "$candidate/grade.py" ] && [ -f "$candidate/child_codec.py" ]; then
        GRADER="$candidate"
        break
    fi
done

if [ -z "$GRADER" ]; then
    echo "FATAL: could not locate grade.py + child_codec.py (looked next to $HERE)" >&2
    echo "SCORE: 0.0"
    exit 2
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "FATAL: no python interpreter on PATH" >&2
    echo "SCORE: 0.0"
    exit 2
fi

echo "== zipstream verifier =="
echo "implementation: $IMPL_ROOT"
echo "log dir:        $LOG_DIR"
"$PY" -c "import sys; print('interpreter:', sys.version.split()[0])"
echo

REPORT="$(mktemp 2>/dev/null || echo /tmp/zipstream-verifier-report.txt)"
"$PY" "$GRADER/grade.py" 2>&1 | tee "$REPORT"
STATUS="${PIPESTATUS[0]}"

# Read the score back out of the grader's own report and republish it from the
# shell. If grade.py's writer failed for any reason, this still lands.
PARSED="$(sed -n 's/^SCORE:[[:space:]]*\([0-9][0-9.]*\).*$/\1/p' "$REPORT" | tail -1)"
if [ -n "$PARSED" ]; then
    FINAL_SCORE="$PARSED"
fi
write_reward "$FINAL_SCORE"
rm -f "$REPORT" 2>/dev/null || true

echo
echo "reward $FINAL_SCORE published to $(count_rewards) file(s)"
if [ "$STATUS" -eq 0 ]; then
    echo "verifier: PASS"
else
    echo "verifier: FAIL (exit $STATUS)"
fi
exit "$STATUS"
