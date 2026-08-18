"""Shared machinery for running one codec call under the graded constraints.

Imported by `child_codec.py`, which is the only thing that ever calls into a
submission. The parent grader never imports the submission at all, so a module
that misbehaves on import costs one measurement rather than the whole report.

Three defences live here, and each of them is structural rather than a rule
somebody has to remember to test:

* `Source` and `Sink` expose exactly one method each. Any other attribute the
  codec reaches for -- `seek`, `tell`, `getvalue`, `__len__`, `fileno` -- is
  recorded and then raises, so "read the whole thing and rewind" is not merely
  discouraged, it is unavailable. `Source` also refuses `read()` with no size,
  which is the other way to ask for the entire stream in one call.

* Compression libraries are made unimportable before the submission is loaded.
  Blocking `zlib` alone would leave `gzip` and `codecs.encode(..., 'zlib_codec')`
  standing, so the whole family goes, along with the two ways out of the
  process -- `ctypes` and `subprocess` -- that could reach a system compressor.

* An audit hook denies writes to the filesystem, and any socket or subprocess,
  for the duration of the graded call. Together with running compression and
  decompression in *different* processes, that closes the oldest trick in
  compression benchmarking: keep the payload somewhere and hand back a receipt.
"""

import os
import sys

BLOCKED_MODULES = frozenset(
    [
        # Anything that would do the modelling for you.
        "zlib", "gzip", "bz2", "lzma", "zipfile", "tarfile", "_compression",
        "brotli", "zstandard", "zstd", "lz4", "snappy", "py7zr", "blosc",
        "encodings.zlib_codec", "encodings.bz2_codec",
        # Anything that could reach one anyway.
        "ctypes", "subprocess", "multiprocessing", "socket",
        # And the instrument itself: a codec that can stop the tracer can
        # report any working set it likes.
        "tracemalloc",
    ]
)

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

_STRICT = [False]
_AUDIT_VIOLATIONS = []


class _Blocker(object):
    """A meta-path finder that refuses the modules above."""

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if fullname in BLOCKED_MODULES or root in BLOCKED_MODULES:
            raise ImportError(
                "%s is not available: this codec has to model the data itself" % (fullname,)
            )
        return None

    # Python 2-era hook name, harmless to keep for exotic import machinery.
    def find_module(self, fullname, path=None):
        self.find_spec(fullname, path)
        return None


def block_modules():
    """Make the compression libraries unimportable, however they are reached."""
    for name in BLOCKED_MODULES:
        sys.modules.pop(name, None)
    sys.meta_path.insert(0, _Blocker())


def _audit(event, args):
    if not _STRICT[0]:
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = False
        if isinstance(mode, str):
            writing = any(character in mode for character in "wxa+")
        elif isinstance(flags, int):
            writing = bool(flags & WRITE_FLAGS)
        if writing:
            _AUDIT_VIOLATIONS.append("opened %r for writing" % (path,))
            raise PermissionError("the codec may not write to the filesystem")
        return
    for prefix in ("socket.", "subprocess.", "os.exec", "os.system", "os.fork",
                   "os.posix_spawn", "os.remove", "os.rename", "os.mkdir",
                   "shutil.", "webbrowser."):
        if event.startswith(prefix):
            _AUDIT_VIOLATIONS.append("called %s" % (event,))
            raise PermissionError("the codec may not use %s" % (event,))


def install_audit_hook():
    sys.addaudithook(_audit)


def strict(enabled):
    _STRICT[0] = bool(enabled)


def audit_violations():
    return list(_AUDIT_VIOLATIONS)


class ContractViolation(Exception):
    """The codec used the source or the sink in a way the protocol forbids."""


_MISSING = object()


class Source(object):
    """A one-pass, non-seekable byte source of unknown length.

    `read(n)` with a positive `n` returns up to `n` bytes and returns `b""`
    once, and only once, the stream is exhausted. It is free to return fewer
    bytes than asked for without that meaning end of stream -- real sockets do,
    and a codec that treats a short read as EOF silently truncates its input.
    """

    __slots__ = ("_data", "_offset", "_short", "_step", "reads", "bytes_read",
                 "violations", "sink", "output_at_eof")

    def __init__(self, data, short_reads=False):
        self._data = data
        self._offset = 0
        self._short = short_reads
        self._step = 0
        self.reads = 0
        self.bytes_read = 0
        self.violations = []
        self.sink = None
        self.output_at_eof = -1

    def _note_eof(self):
        """How much output existed the moment the input ran out.

        A codec that has written almost nothing by this point did not stream:
        it read the whole payload first and is only now going to think about
        it. Peak memory alone will not always catch that -- a fixed buffer
        allocated up front looks frugal -- but this does.
        """
        if self.output_at_eof < 0:
            self.output_at_eof = self.sink.bytes_written if self.sink is not None else 0

    def read(self, size=_MISSING):
        if size is _MISSING:
            self.violations.append("read() with no size: the stream has no known length")
            raise ContractViolation("read() requires a positive size")
        if not isinstance(size, int) or isinstance(size, bool):
            self.violations.append("read(%r): size must be an int" % (size,))
            raise ContractViolation("read() requires a positive integer size")
        if size <= 0:
            self.violations.append("read(%d): the whole stream cannot be asked for at once" % (size,))
            raise ContractViolation("read() requires a positive size")

        self.reads += 1
        self._step += 1
        if self._short and self._step % 3 == 0 and size > 1:
            size = size // 2
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        self.bytes_read += len(chunk)
        if not chunk:
            self._note_eof()
        return chunk

    def __getattr__(self, name):
        self.violations.append("touched source.%s" % (name,))
        raise AttributeError(
            "the source has no %r: it is a one-pass stream of unknown length" % (name,)
        )


class Sink(object):
    """A write-only, non-seekable byte sink."""

    __slots__ = ("chunks", "bytes_written", "writes", "violations", "_keep")

    def __init__(self, keep=True):
        self.chunks = []
        self.bytes_written = 0
        self.writes = 0
        self.violations = []
        self._keep = keep

    def write(self, payload):
        if isinstance(payload, str):
            self.violations.append("write() was given str, not bytes")
            raise ContractViolation("the sink takes bytes, not str")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            self.violations.append("write() was given %s" % (type(payload).__name__,))
            raise ContractViolation("the sink takes bytes-like objects")
        data = bytes(payload)
        self.writes += 1
        self.bytes_written += len(data)
        if self._keep:
            self.chunks.append(data)
        return len(data)

    def value(self):
        return b"".join(self.chunks)

    def __getattr__(self, name):
        self.violations.append("touched sink.%s" % (name,))
        raise AttributeError("the sink has no %r: it is a write-only stream" % (name,))


class FileSource(Source):
    """A Source backed by a file, so a large stream never sits in memory twice."""

    __slots__ = ("_handle",)

    def __init__(self, path, short_reads=False):
        Source.__init__(self, b"", short_reads=short_reads)
        self._handle = open(path, "rb")

    def read(self, size=_MISSING):
        if size is _MISSING:
            self.violations.append("read() with no size: the stream has no known length")
            raise ContractViolation("read() requires a positive size")
        if not isinstance(size, int) or isinstance(size, bool):
            self.violations.append("read(%r): size must be an int" % (size,))
            raise ContractViolation("read() requires a positive integer size")
        if size <= 0:
            self.violations.append("read(%d): the whole stream cannot be asked for at once" % (size,))
            raise ContractViolation("read() requires a positive size")
        self.reads += 1
        self._step += 1
        if self._short and self._step % 3 == 0 and size > 1:
            size = size // 2
        chunk = self._handle.read(size)
        self.bytes_read += len(chunk)
        if not chunk:
            self._note_eof()
        return chunk

    def close(self):
        self._handle.close()


class FileSink(object):
    """A write-only sink backed by a file.

    It also watches the source it is paired with, and records how much of the
    input had been consumed when the first byte of output appeared. A codec
    that reads everything before it writes anything is not streaming, however
    small its own buffers happen to be, and that is the one thing a peak-memory
    figure on its own cannot tell you.
    """

    __slots__ = ("_handle", "bytes_written", "writes", "violations", "_source",
                 "first_write_after", "largest_write")

    def __init__(self, path, source=None):
        self._handle = open(path, "wb")
        self.bytes_written = 0
        self.writes = 0
        self.violations = []
        self._source = source
        self.first_write_after = -1
        self.largest_write = 0

    def write(self, payload):
        if isinstance(payload, str):
            self.violations.append("write() was given str, not bytes")
            raise ContractViolation("the sink takes bytes, not str")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            self.violations.append("write() was given %s" % (type(payload).__name__,))
            raise ContractViolation("the sink takes bytes-like objects")
        if self.first_write_after < 0:
            self.first_write_after = self._source.bytes_read if self._source is not None else 0
        self._handle.write(payload)
        self.writes += 1
        self.bytes_written += len(payload)
        if len(payload) > self.largest_write:
            self.largest_write = len(payload)
        return len(payload)

    def close(self):
        self._handle.close()

    def __getattr__(self, name):
        self.violations.append("touched sink.%s" % (name,))
        raise AttributeError("the sink has no %r: it is a write-only stream" % (name,))
