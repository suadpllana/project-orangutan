#!/usr/bin/env python3
"""Run exactly one codec call, in a process of its own, and report the numbers.

Compression and decompression are never run in the same interpreter. That is
deliberate: if they were, a "codec" could stash the payload in a module global
and hand back a four-byte receipt, and every ratio in the report would be a
lie. The only thing that crosses from one process to the other is the frame on
disk.

Everything the harness itself needs is imported before `tracemalloc` starts, so
the submission is charged for its own import and for whatever it drags in, and
for nothing else.

    python3 child_codec.py <request.json>
"""

import array  # noqa: F401  (preloaded so a submission is not charged for it)
import bisect  # noqa: F401
import collections  # noqa: F401
import functools  # noqa: F401
import heapq  # noqa: F401
import io  # noqa: F401
import itertools  # noqa: F401
import json
import math  # noqa: F401
import operator  # noqa: F401
import os
import string  # noqa: F401
import struct  # noqa: F401
import sys
import time
import traceback
import types  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness  # noqa: E402

import tracemalloc  # noqa: E402


def main(argv):
    with open(argv[1], "r", encoding="utf-8") as stream:
        request = json.load(stream)

    result = {
        "ok": False,
        "error": None,
        "traceback": None,
        "resident": 0,
        "working": 0,
        "peak": 0,
        "seconds": 0.0,
        "bytes_in": 0,
        "bytes_out": 0,
        "reads": 0,
        "writes": 0,
        "violations": [],
        "exception_type": None,
        "first_write_after": -1,
        "largest_write": 0,
        "is_corrupt_stream": False,
        "output_at_eof": -1,
    }
    report_path = request["report"]

    def publish():
        try:
            with open(report_path, "w", encoding="utf-8") as stream:
                json.dump(result, stream)
        except OSError:
            pass

    source = None
    sink = None
    package = None
    try:
        tracemalloc.start()
        _harness.block_modules()
        _harness.install_audit_hook()

        sys.path.insert(0, request["impl_root"])
        import zipstream

        package = zipstream
        entry = getattr(zipstream, request["mode"])
        result["resident"] = tracemalloc.get_traced_memory()[0]

        source = _harness.FileSource(request["input"], short_reads=request.get("short_reads", False))
        sink = _harness.FileSink(request["output"], source=source)
        source.sink = sink

        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        _harness.strict(True)
        started = time.time()
        try:
            entry(source, sink)
        finally:
            _harness.strict(False)
            elapsed = time.time() - started
            peak = tracemalloc.get_traced_memory()[1]

        result["seconds"] = elapsed
        result["peak"] = peak
        result["working"] = max(0, peak - base)
        result["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - every failure has to be reported
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["exception_type"] = type(exc).__name__
        try:
            corrupt = getattr(package, "CorruptStream", None)
            result["is_corrupt_stream"] = bool(
                isinstance(corrupt, type) and isinstance(exc, corrupt)
            )
        except Exception:
            result["is_corrupt_stream"] = False
        result["traceback"] = traceback.format_exc()[-4000:]
        try:
            result["peak"] = tracemalloc.get_traced_memory()[1]
        except Exception:
            pass
    finally:
        _harness.strict(False)
        for stream_object in (source, sink):
            try:
                if stream_object is not None:
                    stream_object.close()
            except Exception:
                pass
        if source is not None:
            result["bytes_in"] = source.bytes_read
            result["reads"] = source.reads
            result["output_at_eof"] = source.output_at_eof
            result["violations"].extend(source.violations)
        if sink is not None:
            result["bytes_out"] = sink.bytes_written
            result["writes"] = sink.writes
            result["first_write_after"] = sink.first_write_after
            result["largest_write"] = sink.largest_write
            result["violations"].extend(sink.violations)
        try:
            if not tracemalloc.is_tracing():
                result["violations"].append("the codec stopped tracemalloc")
        except Exception:
            result["violations"].append("tracemalloc is no longer usable")
        result["violations"].extend(_harness.audit_violations())
        publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
