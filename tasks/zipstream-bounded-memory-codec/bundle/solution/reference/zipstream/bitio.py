"""Streaming bit I/O.

Neither side ever holds more than a few kilobytes: the writer drains into the
sink every `FLUSH_AT` bytes and the reader pulls from the source in `CHUNK`
byte reads. Bits are packed most-significant first.
"""

from .errors import CorruptStream

FLUSH_AT = 4096
CHUNK = 4096

# How much zero padding a reader will invent past the end of the source before
# it decides the frame was truncated rather than merely byte-aligned.
MAX_PAD_BITS = 64


class BitWriter(object):
    __slots__ = ("_sink", "_out", "_acc", "_n", "written")

    def __init__(self, sink):
        self._sink = sink
        self._out = bytearray()
        self._acc = 0
        self._n = 0
        self.written = 0

    def write(self, value, count):
        if count:
            self._acc = (self._acc << count) | (value & ((1 << count) - 1))
            self._n += count
            out = self._out
            while self._n >= 8:
                self._n -= 8
                out.append((self._acc >> self._n) & 0xFF)
            self._acc &= (1 << self._n) - 1
            if len(out) >= FLUSH_AT:
                self._drain()

    def align(self):
        if self._n:
            self.write(0, 8 - self._n)

    def raw(self, data):
        """Append whole bytes. Only valid immediately after `align()`."""
        self._out += data
        if len(self._out) >= FLUSH_AT:
            self._drain()

    def _drain(self):
        payload = bytes(self._out)
        del self._out[:]
        self.written += len(payload)
        self._sink.write(payload)

    def finish(self):
        self.align()
        if self._out:
            self._drain()
        return self.written


class BitReader(object):
    __slots__ = ("_source", "_buf", "_pos", "_acc", "_n", "_pad", "_real")

    def __init__(self, source):
        self._source = source
        self._buf = b""
        self._pos = 0
        self._acc = 0
        self._n = 0
        self._pad = 0
        # How many of the bits sitting in the accumulator came from the source
        # rather than from the zero padding invented past the end of it. The
        # structural reads below refuse to be served invented bytes: without
        # this, a frame truncated by exactly one byte hands the decoder a
        # padded 0x00, which is indistinguishable from the end-of-frame tag,
        # and the truncation is accepted as a clean finish.
        self._real = 0

    def _fill(self, need):
        while self._n < need:
            if self._pos >= len(self._buf):
                chunk = self._source.read(CHUNK)
                if not chunk:
                    # Past the end of the frame. A little zero padding is normal
                    # -- the last byte is only partly used -- but a decoder that
                    # keeps asking is reading a truncated stream.
                    self._pad += 8
                    if self._pad > MAX_PAD_BITS:
                        raise CorruptStream("stream ended mid-symbol")
                    self._acc <<= 8
                    self._n += 8
                    continue
                self._buf = chunk
                self._pos = 0
            self._acc = (self._acc << 8) | self._buf[self._pos]
            self._pos += 1
            self._n += 8
            self._real += 8

    def _consume(self, count):
        self._real -= count
        if self._real < 0:
            self._real = 0

    def peek(self, count):
        if self._n < count:
            self._fill(count)
        return (self._acc >> (self._n - count)) & ((1 << count) - 1)

    def skip(self, count):
        self._n -= count
        self._acc &= (1 << self._n) - 1
        self._consume(count)

    def read(self, count):
        if not count:
            return 0
        if self._n < count:
            self._fill(count)
        self._n -= count
        value = (self._acc >> self._n) & ((1 << count) - 1)
        self._acc &= (1 << self._n) - 1
        self._consume(count)
        return value

    def align(self):
        drop = self._n & 7
        if drop:
            self.skip(drop)

    def raw(self, count):
        """Read `count` whole bytes. Only valid immediately after `align()`."""
        out = bytearray()
        while count and self._n:
            if self._real < 8:
                raise CorruptStream("the frame ended before its structure did")
            self._n -= 8
            out.append((self._acc >> self._n) & 0xFF)
            self._real -= 8
            count -= 1
        self._acc &= (1 << self._n) - 1
        while count:
            if self._pos >= len(self._buf):
                chunk = self._source.read(min(CHUNK, count))
                if not chunk:
                    raise CorruptStream("stored block is truncated")
                self._buf = chunk
                self._pos = 0
            take = min(count, len(self._buf) - self._pos)
            out += self._buf[self._pos : self._pos + take]
            self._pos += take
            count -= take
        return bytes(out)
