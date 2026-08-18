"""Canonical Huffman codes, built from counts both sides already share.

Nothing here is ever transmitted. The encoder and the decoder rebuild identical
tables at identical points in the symbol stream from the statistics of the data
they have already processed, which is what makes a single pass possible: there
is no table to write ahead of a payload nobody has seen yet.

Every table is allocated once and rewritten in place on each rebuild. That is
not a micro-optimisation -- rebuilding five tables per block by allocating new
ones keeps two full sets alive at the moment of hand-over, and on this budget
that alone is most of the allowance.
"""

from array import array

from .errors import CorruptStream

MAX_BITS = 15
FAST_BITS = 9

_EMPTY_FAST = b"\xff" * (4 << FAST_BITS)


def code_lengths(counts, size):
    """Canonical code lengths for `size` symbols, capped at MAX_BITS."""
    work = counts
    while True:
        lengths = _lengths_once(work, size)
        if max(lengths) <= MAX_BITS:
            return lengths
        work = [(value + 1) >> 1 if value else 0 for value in work[:size]]


def _lengths_once(counts, size):
    from heapq import heapify, heappop, heappush

    lengths = [0] * size
    live = [(counts[symbol], symbol) for symbol in range(size) if counts[symbol]]
    if not live:
        return lengths
    if len(live) == 1:
        lengths[live[0][1]] = 1
        return lengths
    heap = [(count, (symbol,)) for count, symbol in live]
    heapify(heap)
    while len(heap) > 1:
        low_count, low = heappop(heap)
        high_count, high = heappop(heap)
        for symbol in low:
            lengths[symbol] += 1
        for symbol in high:
            lengths[symbol] += 1
        heappush(heap, (low_count + high_count, low + high))
    return lengths


class Table(object):
    """One code over `size` symbols: encoder arrays plus a decoder lookup."""

    __slots__ = ("size", "lengths", "codes", "fast", "counts_by_len",
                 "symbols", "first_code", "first_index")

    def __init__(self, size):
        self.size = size
        self.lengths = bytearray(size)
        self.codes = array("i", bytes(4 * size))
        self.fast = array("i", _EMPTY_FAST)
        self.symbols = array("i", bytes(4 * size))
        self.counts_by_len = [0] * (MAX_BITS + 2)
        self.first_code = [0] * (MAX_BITS + 2)
        self.first_index = [0] * (MAX_BITS + 2)

    def update(self, counts):
        """Rewrite this table in place from `counts`."""
        size = self.size
        lengths = code_lengths(counts, size)
        self.lengths[:] = bytes(lengths)

        counts_by_len = self.counts_by_len
        for bits in range(MAX_BITS + 2):
            counts_by_len[bits] = 0
        for length in lengths:
            if length:
                counts_by_len[length] += 1

        codes = self.codes
        symbols = self.symbols
        fast = self.fast
        fast[:] = array("i", _EMPTY_FAST)
        first_code = self.first_code
        first_index = self.first_index

        code = 0
        index = 0
        for bits in range(1, MAX_BITS + 1):
            first_code[bits] = code
            first_index[bits] = index
            if not counts_by_len[bits]:
                code <<= 1
                continue
            shift = FAST_BITS - bits
            for symbol in range(size):
                if lengths[symbol] != bits:
                    continue
                codes[symbol] = code
                symbols[index] = symbol
                if shift >= 0:
                    start = code << shift
                    entry = (symbol << 4) | bits
                    fast[start : start + (1 << shift)] = array("i", [entry]) * (1 << shift)
                code += 1
                index += 1
            code <<= 1

    def encode(self, writer, symbol):
        writer.write(self.codes[symbol], self.lengths[symbol])

    def decode(self, reader):
        entry = self.fast[reader.peek(FAST_BITS)]
        if entry >= 0:
            reader.skip(entry & 15)
            return entry >> 4
        return self._decode_long(reader)

    def _decode_long(self, reader):
        """Bit-at-a-time walk, for the codes too long to sit in the fast table."""
        counts_by_len = self.counts_by_len
        first_code = self.first_code
        first_index = self.first_index
        symbols = self.symbols
        code = 0
        for bits in range(1, MAX_BITS + 1):
            code = (code << 1) | reader.read(1)
            count = counts_by_len[bits]
            if count and code - first_code[bits] < count:
                return symbols[first_index[bits] + code - first_code[bits]]
        raise CorruptStream("no symbol matches the next %d bits" % (MAX_BITS,))
