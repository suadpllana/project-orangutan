"""Canonical Huffman codes over a 256-symbol alphabet.

Code lengths are limited to 15 bits: if the shape of the tree exceeds that, the
counts are flattened and the tree rebuilt, which costs a little compression and
keeps the decoder's tables small.
"""

import heapq

MAX_BITS = 15


def code_lengths(counts):
    """Return a list of 256 code lengths (0 for a symbol that never occurs)."""
    counts = list(counts)
    while True:
        lengths = _lengths_once(counts)
        if max(lengths) <= MAX_BITS:
            return lengths
        counts = [(count + 1) // 2 if count else 0 for count in counts]


def _lengths_once(counts):
    live = [(count, symbol) for symbol, count in enumerate(counts) if count]
    lengths = [0] * 256
    if not live:
        return lengths
    if len(live) == 1:
        lengths[live[0][1]] = 1
        return lengths

    heap = [(count, (symbol,)) for count, symbol in live]
    heapq.heapify(heap)
    while len(heap) > 1:
        low_count, low_symbols = heapq.heappop(heap)
        high_count, high_symbols = heapq.heappop(heap)
        for symbol in low_symbols:
            lengths[symbol] += 1
        for symbol in high_symbols:
            lengths[symbol] += 1
        heapq.heappush(heap, (low_count + high_count, low_symbols + high_symbols))
    return lengths


def canonical_codes(lengths):
    """Map each symbol to (code, length) using the canonical assignment."""
    codes = {}
    code = 0
    for bits in range(1, MAX_BITS + 1):
        for symbol, length in enumerate(lengths):
            if length == bits:
                codes[symbol] = (code, bits)
                code += 1
        code <<= 1
    return codes


class Decoder(object):
    """Canonical Huffman decoder driven by per-length first-code tables."""

    def __init__(self, lengths):
        self.counts = [0] * (MAX_BITS + 1)
        for length in lengths:
            if length:
                self.counts[length] += 1
        self.symbols = [
            symbol
            for bits in range(1, MAX_BITS + 1)
            for symbol, length in enumerate(lengths)
            if length == bits
        ]
        self.first_code = [0] * (MAX_BITS + 2)
        self.first_index = [0] * (MAX_BITS + 2)
        code = 0
        index = 0
        for bits in range(1, MAX_BITS + 1):
            self.first_code[bits] = code
            self.first_index[bits] = index
            code += self.counts[bits]
            index += self.counts[bits]
            code <<= 1

    def decode(self, reader):
        code = 0
        for bits in range(1, MAX_BITS + 1):
            code = (code << 1) | reader.read_bits(1)
            count = self.counts[bits]
            if count and code - self.first_code[bits] < count:
                return self.symbols[self.first_index[bits] + code - self.first_code[bits]]
        raise ValueError("no symbol matches the next 15 bits")
