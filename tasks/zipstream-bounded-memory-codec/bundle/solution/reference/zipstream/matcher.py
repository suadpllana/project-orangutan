"""The match finder: a fixed-size sliding window and a hash chain over it.

Everything here is allocated once, at construction, and never grows. The window
is the single largest structure the codec owns, so its size is the knob that
trades compression against the memory budget; 8 KiB costs about one percent of
ratio against 32 KiB on telemetry and fits the budget with room for the model.
"""

from array import array

from .tables import MAX_MATCH, MIN_MATCH

WINDOW_BITS = 13
WINDOW = 1 << WINDOW_BITS
WINDOW_MASK = WINDOW - 1

HASH_BITS = 13
HASH_SIZE = 1 << HASH_BITS

# How far down a hash chain to walk before taking the best match found so far.
MAX_CHAIN = 6
# A match at least this long is good enough; stop looking.
GOOD_ENOUGH = 48


class Window(object):
    """The bytes both ends can refer back to, plus the encoder's index."""

    __slots__ = ("data", "origin", "head", "chain")

    def __init__(self, index=False):
        self.data = bytearray()
        self.origin = 0
        if index:
            self.head = array("i", b"\xff" * (4 * HASH_SIZE))
            self.chain = array("i", b"\xff" * (4 * WINDOW))
        else:
            self.head = None
            self.chain = None

    def extend(self, chunk):
        self.data += chunk

    def trim(self):
        """Drop everything that has fallen out of the window."""
        excess = len(self.data) - (WINDOW + MAX_MATCH)
        if excess > 0:
            del self.data[:excess]
            self.origin += excess

    def append_byte(self, value):
        self.data.append(value)

    def copy_match(self, distance, length):
        """Copy a match out of the window, overlapping copies included."""
        data = self.data
        start = len(data) - distance
        if start < 0:
            from .errors import CorruptStream

            raise CorruptStream("match distance %d runs before the window" % (distance,))
        if distance >= length:
            data += data[start : start + length]
        else:
            for offset in range(length):
                data.append(data[start + offset])

    def insert(self, position):
        """Record `position` (absolute) in the hash index."""
        data = self.data
        index = position - self.origin
        if index + MIN_MATCH > len(data):
            return
        key = (
            (data[index] << 5)
            ^ (data[index + 1] << 3)
            ^ (data[index + 2] << 1)
            ^ data[index + 3]
        ) & (HASH_SIZE - 1)
        head = self.head
        self.chain[position & WINDOW_MASK] = head[key]
        head[key] = position

    def find(self, position):
        """Longest match for `position`; returns (length, distance) or (0, 0)."""
        data = self.data
        origin = self.origin
        index = position - origin
        limit = len(data) - index
        if limit < MIN_MATCH:
            return 0, 0
        if limit > MAX_MATCH:
            limit = MAX_MATCH

        key = (
            (data[index] << 5)
            ^ (data[index + 1] << 3)
            ^ (data[index + 2] << 1)
            ^ data[index + 3]
        ) & (HASH_SIZE - 1)

        candidate = self.head[key]
        chain = self.chain
        oldest = position - WINDOW
        if oldest < origin:
            oldest = origin

        best_length = 0
        best_distance = 0
        depth = MAX_CHAIN
        target = data[index : index + limit]

        while candidate >= oldest and depth:
            depth -= 1
            other = candidate - origin
            # Cheap rejection: the byte that would extend the current best.
            if best_length and data[other + best_length] != target[best_length]:
                candidate = chain[candidate & WINDOW_MASK]
                continue
            length = 0
            while length < limit and data[other + length] == target[length]:
                length += 1
            if length > best_length:
                best_length = length
                best_distance = position - candidate
                if length >= GOOD_ENOUGH or length == limit:
                    break
            candidate = chain[candidate & WINDOW_MASK]

        if best_length < MIN_MATCH:
            return 0, 0
        return best_length, best_distance
