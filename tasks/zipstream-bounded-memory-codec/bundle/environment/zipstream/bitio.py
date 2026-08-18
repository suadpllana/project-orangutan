"""Bit-level output and input, MSB first.

The writer accumulates into a bytearray the caller owns; the reader walks a
bytes-like object. Neither is streaming -- the current codec builds the whole
frame in memory before handing it to the sink.
"""

from .errors import CorruptStream


class BitWriter(object):
    """Accumulate bits, MSB first, into an internal bytearray."""

    def __init__(self):
        self.buffer = bytearray()
        self._bits = 0
        self._count = 0

    def write_bits(self, value, count):
        """Append the low `count` bits of `value`, most significant first."""
        if count < 0:
            raise ValueError("negative bit count")
        self._bits = (self._bits << count) | (value & ((1 << count) - 1))
        self._count += count
        while self._count >= 8:
            self._count -= 8
            self.buffer.append((self._bits >> self._count) & 0xFF)
        self._bits &= (1 << self._count) - 1

    def flush(self):
        """Pad the final partial byte with zero bits."""
        if self._count:
            self.buffer.append((self._bits << (8 - self._count)) & 0xFF)
            self._bits = 0
            self._count = 0
        return self.buffer


class BitReader(object):
    """Read bits, MSB first, from a bytes-like object."""

    def __init__(self, data, offset=0):
        self.data = data
        self.position = offset
        self._bits = 0
        self._count = 0

    def read_bits(self, count):
        while self._count < count:
            if self.position >= len(self.data):
                raise CorruptStream("ran out of input after %d bits" % (self._count,))
            self._bits = (self._bits << 8) | self.data[self.position]
            self.position += 1
            self._count += 8
        self._count -= count
        value = (self._bits >> self._count) & ((1 << count) - 1)
        self._bits &= (1 << self._count) - 1
        return value
