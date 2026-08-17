#!/usr/bin/env bash
# Sealed verifier entrypoint. The grader runs exactly this script.
#
# Exit status is 0 when the binary success condition is met and 1 otherwise.
# The JSON report carries the partial score either way.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMISSION="${SUBMISSION_DIR:-/app}"
REPORT="${REPORT_PATH:-/tmp/minikv-report.json}"

mkdir -p "$(dirname "$REPORT")"
python3 "${HERE}/grade.py" --submission "$SUBMISSION" --out "$REPORT"
STATUS=$?

# Echo the machine-readable summary so it lands in the harness log too.
python3 - "$REPORT" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print(f"REWARD {report['score']:.4f}")
print(f"BINARY_PASS {str(report['binary_pass']).lower()}")
PY

exit $STATUS
