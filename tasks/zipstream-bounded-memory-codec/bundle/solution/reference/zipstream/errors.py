"""Exceptions raised by the codec."""


class ZipstreamError(Exception):
    """Base class for every error this package raises."""


class CorruptStream(ZipstreamError):
    """The compressed stream is truncated, damaged, or not a zipstream frame.

    `decompress` raises this rather than returning short output, so a caller
    that gets no exception knows it got the whole payload back.
    """


class StreamError(ZipstreamError):
    """The source or sink violated the stream protocol."""
