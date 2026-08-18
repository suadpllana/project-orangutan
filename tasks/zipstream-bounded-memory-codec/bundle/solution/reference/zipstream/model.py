"""The shared adaptive model.

Both ends build one of these and feed it exactly the same symbols in exactly
the same order, so the code tables they derive are identical without a byte of
table ever being transmitted. That is the trick that makes a single pass over a
stream of unknown length possible.

Two rules keep the two sides in lockstep, and both matter more than they look:

  * counts are only ever *rescaled* at a block boundary, never mid-block, so it
    cannot matter that the encoder applies a block's counts in one go while the
    decoder applies them one symbol at a time;
  * a stored block still updates the literal statistics, from the raw bytes,
    which both sides can see.

Literals and lengths share an alphabet split across four contexts selected by
the previous byte -- enough to separate digits from punctuation from letters,
which is most of the first-order structure in telemetry, without paying for 256
sparse tables that would neither fit the budget nor converge.
"""

from array import array

from .huffman import Table
from .tables import DIST_SIZE, LITLEN_SIZE

CONTEXTS = 4

# Rescale a context once its counts get this hot, so the model keeps tracking a
# stream whose statistics move instead of freezing on its first megabyte.
RESCALE_AT = 1 << 16

CONTEXT_OF = bytes((byte >> 6) & 3 for byte in range(256))

_ZERO_LITLEN = bytes(4 * LITLEN_SIZE)
_ZERO_DIST = bytes(4 * DIST_SIZE)


class Deltas(object):
    """One block's worth of symbol counts, held back until the size decision."""

    __slots__ = ("litlen", "dist")

    def __init__(self):
        self.litlen = [array("i", _ZERO_LITLEN) for _ in range(CONTEXTS)]
        self.dist = array("i", _ZERO_DIST)

    def clear(self):
        for counts in self.litlen:
            counts[:] = array("i", _ZERO_LITLEN)
        self.dist[:] = array("i", _ZERO_DIST)


class Model(object):
    __slots__ = ("litlen_counts", "dist_counts", "litlen", "dist")

    def __init__(self):
        self.litlen_counts = [
            array("i", [1]) * LITLEN_SIZE for _ in range(CONTEXTS)
        ]
        self.dist_counts = array("i", [1]) * DIST_SIZE
        self.litlen = [Table(LITLEN_SIZE) for _ in range(CONTEXTS)]
        self.dist = Table(DIST_SIZE)
        self.rebuild()

    def rebuild(self):
        for context in range(CONTEXTS):
            self.litlen[context].update(self.litlen_counts[context])
        self.dist.update(self.dist_counts)

    def apply(self, deltas):
        for context in range(CONTEXTS):
            counts = self.litlen_counts[context]
            block = deltas.litlen[context]
            for symbol in range(LITLEN_SIZE):
                value = block[symbol]
                if value:
                    counts[symbol] += value
        block = deltas.dist
        counts = self.dist_counts
        for symbol in range(DIST_SIZE):
            value = block[symbol]
            if value:
                counts[symbol] += value

    def bump_literals(self, block, previous):
        """Fold a stored block's raw bytes into the literal statistics."""
        litlen_counts = self.litlen_counts
        context_of = CONTEXT_OF
        for byte in block:
            litlen_counts[context_of[previous]][byte] += 16
            previous = byte

    def end_block(self):
        for counts in self.litlen_counts:
            if sum(counts) >= RESCALE_AT:
                for index in range(LITLEN_SIZE):
                    counts[index] = (counts[index] + 1) >> 1
        counts = self.dist_counts
        if sum(counts) >= RESCALE_AT:
            for index in range(DIST_SIZE):
                counts[index] = (counts[index] + 1) >> 1
        self.rebuild()
