"""Sealed corpus generator for the zipstream verifier.

Every graded stream is synthesised here, at grading time, from the run seed.
Nothing the agent can read describes this file: `/app/samples/` ships five
frozen streams so the submission has something to aim at, but those were built
from a *fixed* vocabulary, while everything graded draws a fresh one.

That matters because the cheapest way to hit a compression target without
writing an adaptive model is to bake a static dictionary or a static frequency
table, trained offline on the visible data, into the codec's source. Randomising
the vocabulary -- host names, service names, field names, message words, series
identifiers, even the field ORDER of a record -- makes such a table transfer
badly, and the source-size cap in the spec stops anyone shipping enough of them
to cover the space.

The profiles are deliberately different from each other in kind:

  logfmt   line-oriented key=value text, long repeated literal runs
  csv      short numeric rows, weak byte-level structure, strong column structure
  jsonl    punctuation-heavy nested records, repeated key names
  opaque   base64 payload lines: 6 bits of entropy in every 8-bit byte
  binlog   a length-prefixed BINARY record format, varints and raw floats
  mixed    the above concatenated in segments, so the statistics change mid-stream
  random   incompressible; used only for the expansion ceiling
"""

import random
import struct

PROFILES = ("logfmt", "csv", "jsonl", "opaque", "binlog", "mixed")

_CONSONANTS = "bcdfghjklmnprstvwz"
_VOWELS = "aeiou"
_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _token(rng, low=3, high=9):
    """A pronounceable lowercase token."""
    out = []
    for _ in range(rng.randrange(low, high)):
        out.append(rng.choice(_CONSONANTS))
        out.append(rng.choice(_VOWELS))
    return "".join(out)[: rng.randrange(low, high)]


class Vocabulary(object):
    """The per-run identifier pool. A different seed is a different dialect."""

    def __init__(self, rng):
        self.hosts = [
            "%s-%02d%s" % (_token(rng, 3, 6), rng.randrange(1, 60), rng.choice("abcdef"))
            for _ in range(rng.randrange(6, 18))
        ]
        self.services = [_token(rng, 4, 10) for _ in range(rng.randrange(4, 11))]
        self.fields = [_token(rng, 3, 7) for _ in range(rng.randrange(6, 13))]
        self.words = [_token(rng, 2, 9) for _ in range(rng.randrange(24, 60))]
        self.series = [
            "%s.%s.%s" % (_token(rng, 3, 6), _token(rng, 3, 6), _token(rng, 2, 5))
            for _ in range(rng.randrange(5, 15))
        ]
        self.levels = ["INFO"] * 12 + ["WARN"] * 3 + ["ERROR", "DEBUG"]
        self.tags = [_token(rng, 2, 6) for _ in range(rng.randrange(4, 10))]
        self.epoch = rng.randrange(1_600_000_000, 1_800_000_000)

    def phrase(self, rng, low=2, high=7):
        return " ".join(rng.choice(self.words) for _ in range(rng.randrange(low, high)))


def _logfmt(rng, vocab, out, budget):
    ts = vocab.epoch * 1000
    order = list(range(len(vocab.fields)))
    while budget > 0:
        ts += rng.randrange(1, 900)
        chunks = [
            "ts=%d.%03d" % (ts // 1000, ts % 1000),
            "host=%s" % rng.choice(vocab.hosts),
            "svc=%s" % rng.choice(vocab.services),
            "lvl=%s" % rng.choice(vocab.levels),
        ]
        rng.shuffle(order)
        for index in order[: rng.randrange(1, 5)]:
            name = vocab.fields[index]
            kind = index % 3
            if kind == 0:
                chunks.append("%s=%d" % (name, rng.randrange(0, 100000)))
            elif kind == 1:
                chunks.append("%s=%.3f" % (name, rng.random() * 100))
            else:
                chunks.append("%s=%s" % (name, rng.choice(vocab.tags)))
        chunks.append('msg="%s"' % vocab.phrase(rng))
        line = (" ".join(chunks) + "\n").encode("ascii")
        out.append(line)
        budget -= len(line)


def _csv(rng, vocab, out, budget):
    ts = vocab.epoch
    header = ("ts,series,value,count,tag\n").encode("ascii")
    out.append(header)
    budget -= len(header)
    while budget > 0:
        ts += rng.randrange(0, 3)
        line = "%d,%s,%.4f,%d,%s\n" % (
            ts,
            rng.choice(vocab.series),
            rng.gauss(50.0, 12.0),
            rng.randrange(0, 4096),
            rng.choice(vocab.tags),
        )
        encoded = line.encode("ascii")
        out.append(encoded)
        budget -= len(encoded)


def _jsonl(rng, vocab, out, budget):
    ts = vocab.epoch * 1000
    while budget > 0:
        ts += rng.randrange(1, 400)
        metrics = ",".join(
            '"%s":%.2f' % (name, rng.random() * 1000)
            for name in rng.sample(vocab.fields, rng.randrange(2, min(5, len(vocab.fields)) + 1))
        )
        tags = ",".join(
            '"%s"' % tag for tag in rng.sample(vocab.tags, rng.randrange(1, min(4, len(vocab.tags)) + 1))
        )
        line = '{"ts":%d,"h":"%s","s":"%s","lvl":"%s","m":{%s},"tg":[%s]}\n' % (
            ts,
            rng.choice(vocab.hosts),
            rng.choice(vocab.services),
            rng.choice(vocab.levels),
            metrics,
            tags,
        )
        encoded = line.encode("ascii")
        out.append(encoded)
        budget -= len(encoded)


def _opaque(rng, vocab, out, budget):
    """Base64 payload lines: every byte carries at most six bits."""
    while budget > 0:
        width = rng.choice((64, 64, 76, 76, 88))
        line = ("".join(rng.choice(_B64) for _ in range(width)) + "\n").encode("ascii")
        out.append(line)
        budget -= len(line)


def _binlog(rng, vocab, out, budget):
    """A length-prefixed binary record: magic, varint fields, IEEE doubles."""
    ts = vocab.epoch * 1000
    while budget > 0:
        ts += rng.randrange(1, 700)
        host = rng.randrange(0, len(vocab.hosts))
        service = rng.randrange(0, len(vocab.services))
        gauges = [rng.gauss(120.0, 30.0) for _ in range(rng.randrange(1, 4))]
        body = bytearray()
        body += _varint(ts)
        body.append(host & 0xFF)
        body.append(service & 0xFF)
        body.append(len(gauges))
        for value in gauges:
            body += struct.pack("<d", value)
        body += _varint(rng.randrange(0, 1 << 20))
        record = b"\x9eZ" + _varint(len(body)) + bytes(body)
        out.append(record)
        budget -= len(record)


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


_GENERATORS = {
    "logfmt": _logfmt,
    "csv": _csv,
    "jsonl": _jsonl,
    "opaque": _opaque,
    "binlog": _binlog,
}


def generate(profile, size, seed):
    """Return exactly `size` bytes of `profile` data for `seed`."""
    rng = random.Random("%s|%s|%s" % (seed, profile, size))
    vocab = Vocabulary(rng)
    if profile == "random":
        return bytes(rng.randrange(256) for _ in range(size))
    if profile == "mixed":
        return _mixed(rng, size)
    generator = _GENERATORS.get(profile)
    if generator is None:
        raise ValueError("unknown profile: %r" % (profile,))
    out = []
    generator(rng, vocab, out, size)
    return b"".join(out)[:size]


# The segment plan is FIXED. Only the vocabulary inside each segment moves with
# the seed: a mixed stream whose shape varied too would make the ratio target a
# lottery, and a target nobody can predict is not a specification.
MIXED_PLAN = ("logfmt", "csv", "jsonl", "binlog", "opaque")


def _mixed(rng, size):
    """Segments of different profiles, so the statistics move under the model."""
    span = size // len(MIXED_PLAN)
    pieces = []
    for index, profile in enumerate(MIXED_PLAN):
        want = span if index + 1 < len(MIXED_PLAN) else size - span * index
        vocab = Vocabulary(rng)
        out = []
        _GENERATORS[profile](rng, vocab, out, want)
        pieces.append(b"".join(out)[:want])
    return b"".join(pieces)[:size]


def repeated(byte, size):
    """A degenerate stream: one byte value, `size` times."""
    return bytes([byte]) * size


def alphabet_cycle(size):
    """Every byte value, cycled -- flat order-0 statistics, perfect order-1."""
    return bytes(index % 256 for index in range(size))
