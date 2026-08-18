#!/usr/bin/env python3
"""Build-time assertion that the starting workspace is what it claims to be.

Run once by the Dockerfile and then deleted from the image. It checks both
halves of a good seed:

  * the shipping codec really does work -- it round-trips everything the
    visible suite throws at it, so the agent starts from working code rather
    than from stubs;

  * and it really is inadequate in exactly the ways the task asks about. A seed
    that accidentally satisfied one of the budgets would be a task with a
    smaller gap than its own specification claims, and the right time to find
    that out is here, not at the oracle stage.
"""

import sys
import tracemalloc

sys.path.insert(0, "/app")

WORKING_BUDGET = 384 * 1024
STREAM = 512 * 1024


class Reader(object):
    def __init__(self, data):
        self._data = data
        self._offset = 0

    def read(self, size):
        assert size > 0
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class Writer(object):
    def __init__(self):
        self.total = 0
        self.chunks = []

    def write(self, payload):
        self.total += len(payload)
        self.chunks.append(bytes(payload))
        return len(payload)

    def value(self):
        return b"".join(self.chunks)


def main():
    import zipstream

    # --- the half that must work -------------------------------------------
    for payload in (b"", b"\x00", b"A", bytes(range(256)), b"ts=1 host=a\n" * 500):
        sink = Writer()
        zipstream.compress(Reader(payload), sink)
        frame = sink.value()
        assert frame[:2] == b"ZS", "frames must start with the magic, got %r" % (frame[:2],)
        out = Writer()
        zipstream.decompress(Reader(frame), out)
        assert out.value() == payload, "the shipping codec does not round-trip %d bytes" % (
            len(payload),
        )

    try:
        zipstream.decompress_bytes(b"junk that is not a frame")
    except zipstream.CorruptStream:
        pass
    else:
        raise AssertionError("the shipping codec must reject a non-frame")

    # --- the half that must NOT work yet -----------------------------------
    small = (b"ts=1 host=edge-01 svc=ingest lvl=INFO\n" * 6)[:200]
    assert len(zipstream.compress_bytes(small)) > 100, (
        "the seed already meets the small-frame target; the gap this task asks "
        "about is not there"
    )

    payload = b"".join(
        b"ts=%d host=edge-%02d svc=ingest lvl=INFO n=%d\n" % (index, index % 40, index * 7)
        for index in range(STREAM // 44 + 64)
    )[:STREAM]

    tracemalloc.start()
    tracemalloc.reset_peak()
    base = tracemalloc.get_traced_memory()[0]
    sink = Writer()
    zipstream.compress(Reader(payload), sink)
    working = tracemalloc.get_traced_memory()[1] - base
    tracemalloc.stop()
    assert working > WORKING_BUDGET, (
        "the seed compresses %d bytes in %d of working set, inside the %d budget; "
        "it is not the memory-hungry starting point the task describes"
        % (STREAM, working, WORKING_BUDGET)
    )

    print("selfcheck: the seed works, and is inadequate in the ways the spec says")
    print("selfcheck: 200-byte record -> %d bytes, %d KiB stream -> %d B working set" % (
        len(zipstream.compress_bytes(small)), STREAM // 1024, working))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
