"""The zipstream v1 codec: order-0 static Huffman over the whole payload.

This is the shipping implementation. It is correct -- every stream it writes
reads back byte for byte -- and it is the wrong shape for the collector:

  * it reads the entire source into memory before it can emit anything, because
    the code table is built from statistics of the whole payload;
  * it holds the entire compressed frame in memory too, because the 256-byte
    table has to be written before the payload;
  * it models nothing beyond the marginal frequency of each byte, so the
    repeated field names and near-constant timestamps that dominate telemetry
    cost it full price every time they occur.

See SPEC.md for what is being asked for instead.
"""

import struct

from .bitio import BitReader, BitWriter
from .errors import CorruptStream
from .huffman import Decoder, canonical_codes, code_lengths

MAGIC = b"ZS1\x00"
METHOD_STORED = 0
METHOD_HUFFMAN = 1

READ_CHUNK = 1 << 16


def _read_all(source):
    """Drain the source. Short reads are normal; only b'' means end of stream."""
    parts = []
    while True:
        chunk = source.read(READ_CHUNK)
        if not chunk:
            break
        parts.append(chunk)
    return b"".join(parts)


def compress(source, sink):
    """Compress every byte of `source` into `sink`."""
    data = _read_all(source)

    counts = [0] * 256
    for byte in data:
        counts[byte] += 1

    lengths = code_lengths(counts)
    codes = canonical_codes(lengths)

    writer = BitWriter()
    for byte in data:
        code, length = codes[byte]
        writer.write_bits(code, length)
    payload = writer.flush()

    header = bytearray()
    header += MAGIC
    if len(payload) >= len(data):
        header.append(METHOD_STORED)
        header += struct.pack("<I", len(data))
        sink.write(bytes(header))
        sink.write(data)
        return

    header.append(METHOD_HUFFMAN)
    header += struct.pack("<I", len(data))
    header += bytes(lengths)
    sink.write(bytes(header))
    sink.write(bytes(payload))


def decompress(source, sink):
    """Reverse `compress`, raising CorruptStream on damaged input."""
    frame = _read_all(source)
    if len(frame) < len(MAGIC) + 5:
        raise CorruptStream("frame is shorter than a header")
    if frame[: len(MAGIC)] != MAGIC:
        raise CorruptStream("bad magic %r" % (frame[: len(MAGIC)],))

    method = frame[len(MAGIC)]
    offset = len(MAGIC) + 1
    (length,) = struct.unpack("<I", frame[offset : offset + 4])
    offset += 4

    if method == METHOD_STORED:
        body = frame[offset:]
        if len(body) != length:
            raise CorruptStream("stored payload is %d bytes, header says %d" % (len(body), length))
        sink.write(body)
        return

    if method != METHOD_HUFFMAN:
        raise CorruptStream("unknown method %d" % (method,))

    lengths = list(frame[offset : offset + 256])
    if len(lengths) != 256:
        raise CorruptStream("truncated code table")
    offset += 256

    decoder = Decoder(lengths)
    reader = BitReader(frame, offset)
    out = bytearray()
    try:
        for _ in range(length):
            out.append(decoder.decode(reader))
    except ValueError as exc:
        raise CorruptStream(str(exc))
    sink.write(bytes(out))
