"""zipstream v2: LZ77 over a bounded window, entropy-coded with a backward-
adaptive contextual Huffman model.

The frame is a sequence of byte-aligned blocks:

    "ZS"                                    magic
    repeat:
        u8   tag        0 end, 1 compressed, 2 stored
        u16  count - 1  bytes of payload this block expands to
        ...  either a bit-packed symbol stream, padded to a byte boundary,
             or `count` raw bytes
    (the end tag closes the frame)

No code table is ever written down. Both ends rebuild the same tables from the
statistics of the blocks they have already handled, so the encoder never needs
to see the whole payload before it can emit the first byte -- which is the only
way to satisfy a non-seekable source, a non-seekable sink, and a memory budget
far below the size of the stream, all at once.

A block whose coded form is no smaller than its input is emitted stored, so
incompressible input costs three bytes per block rather than the expansion an
entropy coder would otherwise inflict on it.
"""

from .bitio import BitReader, BitWriter
from .errors import CorruptStream
from .matcher import Window
from .model import CONTEXT_OF, Deltas, Model
from .tables import (
    DIST_EXTRA,
    LENGTH_CODE,
    LENGTH_EXTRA,
    LENGTH_EXTRA_VALUE,
    LITERALS,
    MIN_MATCH,
    distance_code,
)

MAGIC = b"ZS"
BLOCK = 1 << 13

TAG_END = 0
TAG_COMPRESSED = 1
TAG_STORED = 2


class _Collector(object):
    """A sink that keeps a block's coded bytes until the size decision."""

    __slots__ = ("chunks", "size")

    def __init__(self):
        self.chunks = []
        self.size = 0

    def write(self, payload):
        self.chunks.append(payload)
        self.size += len(payload)

    def value(self):
        return b"".join(self.chunks)


def _read_exactly(source, want):
    """Read up to `want` bytes, tolerating short reads; b'' means end of input."""
    chunk = source.read(want)
    if not chunk or len(chunk) == want:
        return chunk
    parts = [chunk]
    got = len(chunk)
    while got < want:
        more = source.read(want - got)
        if not more:
            break
        parts.append(more)
        got += len(more)
    return b"".join(parts)


def compress(source, sink):
    """Compress every byte of `source` into `sink`, in a single pass."""
    sink.write(MAGIC)
    model = Model()
    deltas = Deltas()
    window = Window(index=True)
    previous = 0

    while True:
        block = _read_exactly(source, BLOCK)
        if not block:
            break

        prior = previous
        base = window.origin + len(window.data)
        window.extend(block)
        deltas.clear()

        collector = _Collector()
        writer = BitWriter(collector)
        _encode_block(writer, block, base, window, model, deltas, prior)
        writer.finish()
        payload = collector.value()

        count = len(block)
        size = bytes(((count - 1) >> 8, (count - 1) & 0xFF))
        if len(payload) < count:
            sink.write(bytes((TAG_COMPRESSED,)) + size)
            sink.write(payload)
            model.apply(deltas)
        else:
            sink.write(bytes((TAG_STORED,)) + size)
            sink.write(block)
            model.bump_literals(block, prior)
        model.end_block()
        window.trim()
        previous = block[-1]

    sink.write(bytes((TAG_END,)))


def _encode_block(writer, block, base, window, model, deltas, previous):
    data = window.data
    origin = window.origin
    end = base + len(block)
    position = base

    litlen_tables = model.litlen
    dist_table = model.dist
    delta_litlen = deltas.litlen
    delta_dist = deltas.dist
    insert = window.insert
    find = window.find

    while position < end:
        length, distance = find(position)
        context = CONTEXT_OF[previous]
        if length:
            code = LENGTH_CODE[length]
            symbol = LITERALS + code
            litlen_tables[context].encode(writer, symbol)
            delta_litlen[context][symbol] += 16
            extra = LENGTH_EXTRA[code]
            if extra:
                writer.write(LENGTH_EXTRA_VALUE[length], extra)
            dist_symbol, dist_value = distance_code(distance)
            dist_table.encode(writer, dist_symbol)
            delta_dist[dist_symbol] += 16
            extra = DIST_EXTRA[dist_symbol]
            if extra:
                writer.write(dist_value, extra)
            stop = position + length
            while position < stop:
                insert(position)
                position += 1
            previous = data[position - 1 - origin]
        else:
            byte = data[position - origin]
            litlen_tables[context].encode(writer, byte)
            delta_litlen[context][byte] += 16
            insert(position)
            position += 1
            previous = byte
    return previous


def decompress(source, sink):
    """Reverse `compress`. Raises CorruptStream on a damaged or short frame."""
    reader = BitReader(source)
    if reader.raw(len(MAGIC)) != MAGIC:
        raise CorruptStream("not a zipstream frame")

    model = Model()
    window = Window()
    previous = 0

    while True:
        tag = reader.raw(1)[0]
        if tag == TAG_END:
            break
        if tag not in (TAG_COMPRESSED, TAG_STORED):
            raise CorruptStream("unknown block tag %d" % (tag,))
        header = reader.raw(2)
        count = ((header[0] << 8) | header[1]) + 1

        if tag == TAG_STORED:
            block = reader.raw(count)
            model.bump_literals(block, previous)
            window.extend(block)
            sink.write(block)
            previous = block[-1]
        else:
            start = len(window.data)
            previous = _decode_block(reader, count, window, model, previous)
            reader.align()
            produced = window.data[start:]
            sink.write(bytes(produced))
        model.end_block()
        window.trim()


def _decode_block(reader, count, window, model, previous):
    data = window.data
    litlen_tables = model.litlen
    dist_table = model.dist
    litlen_counts = model.litlen_counts
    dist_counts = model.dist_counts
    remaining = count

    while remaining > 0:
        context = CONTEXT_OF[previous]
        symbol = litlen_tables[context].decode(reader)
        litlen_counts[context][symbol] += 16
        if symbol < LITERALS:
            data.append(symbol)
            previous = symbol
            remaining -= 1
            continue
        code = symbol - LITERALS
        if code >= len(LENGTH_EXTRA):
            raise CorruptStream("length code %d is out of range" % (code,))
        length = _length_of(code, reader)
        dist_symbol = dist_table.decode(reader)
        dist_counts[dist_symbol] += 16
        distance = _distance_of(dist_symbol, reader)
        if length > remaining:
            raise CorruptStream("match overruns the block by %d bytes" % (length - remaining,))
        window.copy_match(distance, length)
        remaining -= length
        previous = data[-1]
    return previous


def _length_of(code, reader):
    from .tables import LENGTH_BASE

    extra = LENGTH_EXTRA[code]
    return LENGTH_BASE[code] + (reader.read(extra) if extra else 0)


def _distance_of(symbol, reader):
    from .tables import DIST_BASE, DIST_SIZE

    if symbol >= DIST_SIZE:
        raise CorruptStream("distance code %d is out of range" % (symbol,))
    extra = DIST_EXTRA[symbol]
    return DIST_BASE[symbol] + (reader.read(extra) if extra else 0)


_ = MIN_MATCH  # the matcher owns the minimum; named here for the reader
