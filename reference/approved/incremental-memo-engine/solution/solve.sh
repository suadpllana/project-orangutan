#!/usr/bin/env bash
# Reference solution: install the finished `incremental` package into /app.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${IMPL_ROOT:-/app}"

SRC=""
for candidate in "$HERE/reference" /solution/reference /app/solution/reference "$HERE/../solution/reference"; do
    if [ -d "$candidate/incremental" ]; then
        SRC="$candidate"
        break
    fi
done

if [ -z "$SRC" ]; then
    echo "FATAL: reference sources not found next to $HERE" >&2
    exit 1
fi

mkdir -p "$TARGET/incremental"
cp "$SRC/incremental/"*.py "$TARGET/incremental/"
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "installed reference implementation into $TARGET/incremental"

# Smoke test: the engine must memoize, cut off, and survive a round trip.
cd "$TARGET"
python3 - <<'PY'
import sys, tempfile, os
sys.path.insert(0, os.environ.get("IMPL_ROOT", "/app"))
from incremental import Engine

calls = []
engine = Engine()

@engine.query(name="parity")
def parity(ctx):
    calls.append("parity")
    return ctx.input("n") % 2

@engine.query(name="top")
def top(ctx):
    calls.append("top")
    return ctx.call("parity") * 10

engine.set_input("n", 1)
assert engine.get("top") == 10, engine.get("top")
assert calls == ["top", "parity"], calls

calls.clear()
engine.set_input("n", 3)
assert engine.get("top") == 10
assert calls == ["parity"], "early cutoff is broken: %r" % (calls,)

handle, path = tempfile.mkstemp()
os.close(handle)
try:
    engine.save(path)
    fresh = Engine()
    fresh.query(lambda ctx: ctx.input("n") % 2, name="parity")
    fresh.query(lambda ctx: ctx.call("parity") * 10, name="top")
    fresh.load(path)
    calls.clear()
    assert fresh.get("top") == 10
    assert fresh.stats()["executions"] == 0, fresh.stats()
finally:
    os.unlink(path)

print("smoke test OK")
PY
