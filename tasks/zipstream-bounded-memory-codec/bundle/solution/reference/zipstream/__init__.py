"""zipstream -- the collector's on-the-wire compression codec.

Public API:

    zipstream.compress(source, sink)      # stream in, stream out
    zipstream.decompress(source, sink)
    zipstream.compress_bytes(data)        # convenience wrappers for tests
    zipstream.decompress_bytes(frame)

`source` is any object with `read(n)`; `sink` is any object with `write(b)`.
Nothing else is required of either, and nothing else may be assumed of them --
see SPEC.md.
"""

import io

from .codec import compress, decompress
from .errors import CorruptStream, StreamError, ZipstreamError

__all__ = [
    "compress",
    "decompress",
    "compress_bytes",
    "decompress_bytes",
    "CorruptStream",
    "StreamError",
    "ZipstreamError",
    "__version__",
]

__version__ = "2.0.0"


def compress_bytes(data):
    """Convenience wrapper: compress a bytes object and return the frame."""
    sink = io.BytesIO()
    compress(io.BytesIO(data), sink)
    return sink.getvalue()


def decompress_bytes(frame):
    """Convenience wrapper: decompress a frame and return the payload."""
    sink = io.BytesIO()
    decompress(io.BytesIO(frame), sink)
    return sink.getvalue()
