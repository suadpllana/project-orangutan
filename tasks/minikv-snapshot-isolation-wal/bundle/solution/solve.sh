#!/usr/bin/env bash
# Reference solution entrypoint. The oracle run executes exactly this script and
# must then reach full reward.
#
# The reference implementation is a drop-in replacement for /app/minikv: same
# public API, a real MVCC + write-ahead-log engine behind it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${APP_DIR:-/app}"

rm -rf "${APP}/minikv"
cp -r "${HERE}/minikv" "${APP}/minikv"
find "${APP}/minikv" -name '__pycache__' -type d -prune -exec rm -rf {} +

# Fail loudly here rather than in the verifier if the drop-in does not import.
python3 - "$APP" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import tempfile
from minikv import MiniKV
with tempfile.TemporaryDirectory() as path:
    with MiniKV(path) as db:
        with db.begin() as txn:
            txn.put(b"k", b"v")
        assert db.get(b"k") == b"v"
        db.checkpoint()
print("reference solution installed")
PY
