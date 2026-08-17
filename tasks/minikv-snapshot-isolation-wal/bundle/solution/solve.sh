#!/usr/bin/env bash
# Reference solution: install the finished `minikv` package into /app.
#
# The oracle run executes exactly this script and must then reach full reward.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${IMPL_ROOT:-${APP_DIR:-/app}}"

SRC=""
for candidate in "$HERE/reference" /solution/reference /app/solution/reference "$HERE/../solution/reference"; do
    if [ -d "$candidate/minikv" ]; then
        SRC="$candidate"
        break
    fi
done

if [ -z "$SRC" ]; then
    echo "FATAL: reference sources not found next to $HERE" >&2
    exit 1
fi

rm -rf "$TARGET/minikv"
mkdir -p "$TARGET/minikv"
cp "$SRC/minikv/"*.py "$TARGET/minikv/"
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "installed reference implementation into $TARGET/minikv"

# Smoke test: transactions, snapshot isolation, durability and checkpointing
# must all work here, so a broken drop-in fails in the oracle step rather than
# silently in the verifier.
cd "$TARGET"
python3 - <<'PY'
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.environ.get("IMPL_ROOT", os.environ.get("APP_DIR", "/app")))
from minikv import ConflictError, MiniKV

path = tempfile.mkdtemp()
try:
    with MiniKV(path) as db:
        db.put(b"k", b"old")

        # A snapshot must not move under an outside write, and taking one must
        # not block that write - a lock held across the transaction deadlocks.
        txn = db.begin()
        db.put(b"k", b"new")
        assert txn.get(b"k") == b"old", txn.get(b"k")
        txn.rollback()

        # First-committer-wins.
        winner, loser = db.begin(), db.begin()
        winner.put(b"k", b"w")
        loser.put(b"k", b"l")
        winner.commit()
        try:
            loser.commit()
        except ConflictError:
            pass
        else:
            raise SystemExit("conflict detection is broken")

        for i in range(200):
            db.put(f"k{i:04d}".encode(), b"v" * 64)
        db.checkpoint()
        assert db.stats()["wal_bytes"] <= 4096, db.stats()

    with MiniKV(path) as db:
        assert db.get(b"k") == b"w"
        assert db.stats()["live_keys"] == 201, db.stats()
finally:
    shutil.rmtree(path, ignore_errors=True)

print("smoke test OK")
PY
