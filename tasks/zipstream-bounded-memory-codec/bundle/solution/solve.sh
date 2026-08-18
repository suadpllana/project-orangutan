#!/usr/bin/env bash
# Reference solution: install the finished `zipstream` package into /app.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${IMPL_ROOT:-/app}"

SRC=""
for candidate in "$HERE/reference" /solution/reference /app/solution/reference "$HERE/../solution/reference"; do
    if [ -d "$candidate/zipstream" ]; then
        SRC="$candidate"
        break
    fi
done

if [ -z "$SRC" ]; then
    echo "FATAL: reference sources not found next to $HERE" >&2
    exit 1
fi

# Replace the package wholesale: v2 shares no module with v1 beyond errors.py,
# and a stale v1 module left behind would be imported in preference to nothing.
rm -rf "$TARGET/zipstream"
mkdir -p "$TARGET/zipstream"
cp "$SRC/zipstream/"*.py "$TARGET/zipstream/"
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "installed reference implementation into $TARGET/zipstream"

# Smoke test: fail here, loudly, rather than silently in the verifier. This
# exercises the four things the spec actually asks for -- a single pass over a
# non-seekable source, a bounded working set, output before the input ends, and
# a frame that is both small and exact.
cd "$TARGET"
python3 - <<'PY'
import os
import sys
import tracemalloc

tracemalloc.start()
sys.path.insert(0, os.environ.get("IMPL_ROOT", "/app"))
import zipstream

WORKING_BUDGET = 384 * 1024


class Reader(object):
    """read(n) and nothing else, exactly like the grader's source."""

    __slots__ = ("_data", "_at", "sink", "output_at_eof")

    def __init__(self, data, sink=None):
        self._data = data
        self._at = 0
        self.sink = sink
        self.output_at_eof = -1

    def read(self, size):
        assert size > 0, "the codec asked for a non-positive read"
        chunk = self._data[self._at : self._at + size]
        self._at += len(chunk)
        if not chunk and self.output_at_eof < 0:
            self.output_at_eof = self.sink.total if self.sink is not None else 0
        return chunk


class Writer(object):
    __slots__ = ("total", "chunks", "keep")

    def __init__(self, keep=True):
        self.total = 0
        self.chunks = []
        self.keep = keep

    def write(self, payload):
        self.total += len(payload)
        if self.keep:
            self.chunks.append(bytes(payload))
        return len(payload)

    def value(self):
        return b"".join(self.chunks)


payload = b"".join(
    b'{"ts":%d,"h":"edge-%02d","s":"ingest","lvl":"INFO","m":{"cpu":%d.%02d}}\n'
    % (1713451200000 + index * 37, index % 40, index % 97, index % 100)
    for index in range(12000)
)
assert len(payload) > 512 * 1024, len(payload)

# Measured against a sink that keeps nothing, so the figure is the codec's
# working set and not this script's copy of the frame.
meter = Writer(keep=False)
source = Reader(payload, sink=meter)
tracemalloc.reset_peak()
base = tracemalloc.get_traced_memory()[0]
zipstream.compress(source, meter)
working = tracemalloc.get_traced_memory()[1] - base

sink = Writer()
zipstream.compress(Reader(payload), sink)
frame = sink.value()
assert len(frame) == meter.total, "compression is not deterministic"

assert frame[:2] == b"ZS", "frames must start with the magic: %r" % (frame[:2],)
assert working <= WORKING_BUDGET, "working set %d exceeds %d" % (working, WORKING_BUDGET)
assert source.output_at_eof >= len(frame) // 4, (
    "only %d of %d output bytes existed when the input ran out" % (source.output_at_eof, len(frame))
)

out = Writer()
zipstream.decompress(Reader(frame), out)
assert out.value() == payload, "round trip lost data"

tiny = Writer()
zipstream.compress(Reader((b"ts=1 host=edge-01 svc=ingest lvl=INFO\n" * 6)[:200]), tiny)
assert tiny.total <= 100, "a 200-byte record became %d bytes" % (tiny.total,)

for damaged in (frame[: len(frame) // 2], frame[:-1], b"", b"nonsense"):
    try:
        zipstream.decompress(Reader(damaged), Writer(keep=False))
    except zipstream.CorruptStream:
        continue
    raise AssertionError("accepted a damaged frame of %d bytes" % (len(damaged),))

print("smoke test OK: %d -> %d bytes (%.4f), working set %d B, %d of %d bytes out at EOF"
      % (len(payload), len(frame), len(frame) / len(payload), working,
         source.output_at_eof, len(frame)))
PY
