#!/usr/bin/env bash
# Entry point the harness calls after the agent's timeout expires.
#
#   run_verifier.sh [submission_dir] [report_path]
#
# Exit status is 0 when the binary success condition is met and 1 otherwise;
# the JSON report carries the partial score either way.
set -uo pipefail

SUBMISSION="${1:-/workspace}"
REPORT="${2:-/verifier/report.json}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$(dirname "$REPORT")"
exec python3 "$HERE/grade.py" --submission "$SUBMISSION" --out "$REPORT"
