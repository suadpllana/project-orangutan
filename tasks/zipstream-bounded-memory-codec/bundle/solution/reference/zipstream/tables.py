"""Length and distance code tables.

A match is coded as a symbol in the literal/length alphabet plus a few raw
extra bits, then a distance symbol plus its own extra bits. Bucketing the
ranges this way keeps both alphabets small enough that their adaptive
statistics converge inside a few kilobytes of input, which matters when the
whole model has to fit the window budget.
"""

MIN_MATCH = 4
MAX_MATCH = 258

LITERALS = 256
LENGTH_BASE = (
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258,
)
LENGTH_EXTRA = (
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
)
LENGTH_CODES = len(LENGTH_BASE)
LITLEN_SIZE = LITERALS + LENGTH_CODES

DIST_BASE = (
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
    257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
)
DIST_EXTRA = (
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11,
)
DIST_SIZE = len(DIST_BASE)

# length -> (code index, extra bits value)
_LENGTH_CODE = [0] * (MAX_MATCH + 1)
_LENGTH_EXTRA_VALUE = [0] * (MAX_MATCH + 1)
for _length in range(MIN_MATCH, MAX_MATCH + 1):
    for _index in range(LENGTH_CODES - 1, -1, -1):
        if _length >= LENGTH_BASE[_index]:
            _LENGTH_CODE[_length] = _index
            _LENGTH_EXTRA_VALUE[_length] = _length - LENGTH_BASE[_index]
            break

LENGTH_CODE = tuple(_LENGTH_CODE)
LENGTH_EXTRA_VALUE = tuple(_LENGTH_EXTRA_VALUE)


def distance_code(distance):
    for index in range(DIST_SIZE - 1, -1, -1):
        if distance >= DIST_BASE[index]:
            return index, distance - DIST_BASE[index]
    raise ValueError("distance %d is not codeable" % (distance,))


# Distances are small and bounded by the window, so the lookup is a plain list.
MAX_DISTANCE = DIST_BASE[-1] + (1 << DIST_EXTRA[-1]) - 1
