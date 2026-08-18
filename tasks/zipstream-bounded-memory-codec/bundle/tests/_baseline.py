"""The size the shipping codec would have produced, computed exactly.

Every compression target in the grade is expressed as a fraction of this
number rather than as an absolute ratio. That is not a convenience: the graded
streams are synthesised fresh on every run, so an absolute target would drift
with the seed and a submission would pass or fail on luck. Measuring both
codecs on the same bytes cancels the drift almost entirely -- across two dozen
seeds the reference solution's fraction of this baseline moves by well under
one percent on every profile.

This reproduces `/app/zipstream`'s v1 container arithmetic exactly: a four byte
magic, a method byte, a four byte length, a 256 byte table of code lengths, and
the order-0 canonical Huffman payload -- or a stored frame when that would be
no smaller. It is checked against the real thing in `test.sh`'s self-check.
"""

from heapq import heapify, heappop, heappush

HEADER = 4 + 1 + 4
TABLE = 256
MAX_BITS = 15


def _code_lengths(counts):
    work = list(counts)
    while True:
        lengths = _lengths_once(work)
        if max(lengths) <= MAX_BITS:
            return lengths
        work = [(value + 1) // 2 if value else 0 for value in work]


def _lengths_once(counts):
    lengths = [0] * 256
    live = [(count, symbol) for symbol, count in enumerate(counts) if count]
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


def baseline_size(data):
    """Bytes the v1 codec in `/app` emits for `data`."""
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    lengths = _code_lengths(counts)
    bits = 0
    for symbol in range(256):
        if counts[symbol]:
            bits += counts[symbol] * lengths[symbol]
    payload = (bits + 7) // 8
    if payload >= len(data):
        return HEADER + len(data)
    return HEADER + TABLE + payload


def baseline_size_of_file(path, chunk=1 << 20):
    counts = [0] * 256
    total = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            total += len(block)
            for byte in block:
                counts[byte] += 1
    lengths = _code_lengths(counts)
    bits = 0
    for symbol in range(256):
        if counts[symbol]:
            bits += counts[symbol] * lengths[symbol]
    payload = (bits + 7) // 8
    if payload >= total:
        return HEADER + total
    return HEADER + TABLE + payload
