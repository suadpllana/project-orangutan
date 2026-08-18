"""The visible half of the verifier.

These tests describe the behaviour the shipping codec ALREADY has. They are the
floor, not the target: every one of them passes against the code in `/app`
today, and every one of them must still pass when you are done. None of them
looks at memory, at compression ratio, or at how much of the input you consume
before you produce output, which is where the actual work of this task is --
read SPEC.md for that.

The graded suite is much larger, is not shipped in the image, and re-runs a
pristine copy of this file, so editing this file changes nothing.

    python -m pytest public_tests -q
"""

import os

import pytest

import zipstream

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


class Reader(object):
    """A one-pass source: read(n) and nothing else, exactly like the grader's."""

    def __init__(self, data, short=False):
        self._data = data
        self._offset = 0
        self._short = short
        self._step = 0

    def read(self, size):
        assert size > 0, "the codec must ask for a positive number of bytes"
        self._step += 1
        if self._short and self._step % 2 == 0 and size > 1:
            size //= 2
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class Writer(object):
    """A write-only sink."""

    def __init__(self):
        self.chunks = []

    def write(self, payload):
        assert isinstance(payload, (bytes, bytearray, memoryview))
        self.chunks.append(bytes(payload))
        return len(payload)

    def value(self):
        return b"".join(self.chunks)


def roundtrip(data, short=False):
    frame = Writer()
    zipstream.compress(Reader(data, short=short), frame)
    payload = frame.value()
    out = Writer()
    zipstream.decompress(Reader(payload), out)
    return payload, out.value()


def sample_names():
    if not os.path.isdir(SAMPLES):
        return []
    return sorted(name for name in os.listdir(SAMPLES) if name.endswith(".bin"))


def load_sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as handle:
        return handle.read()


# --------------------------------------------------------------- the API exists


def test_public_api_is_exported():
    for name in ("compress", "decompress", "compress_bytes", "decompress_bytes",
                 "CorruptStream", "ZipstreamError"):
        assert hasattr(zipstream, name), "zipstream.%s is missing" % (name,)


def test_corrupt_stream_is_a_zipstream_error():
    assert issubclass(zipstream.CorruptStream, zipstream.ZipstreamError)
    assert issubclass(zipstream.ZipstreamError, Exception)


def test_compress_returns_none_and_writes_to_the_sink():
    sink = Writer()
    assert zipstream.compress(Reader(b"hello telemetry"), sink) is None
    assert sink.value(), "compress wrote nothing"


# ------------------------------------------------------------------- round trips


@pytest.mark.parametrize("name", sample_names())
def test_samples_roundtrip(name):
    data = load_sample(name)
    _, back = roundtrip(data)
    assert back == data


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x00",
        b"A",
        b"\xff\xfe\xfd",
        b"a" * 4096,
        bytes(range(256)),
        bytes(range(256)) * 8,
        b"ts=1 host=a svc=b\n" * 200,
    ],
)
def test_edge_payloads_roundtrip(data):
    _, back = roundtrip(data)
    assert back == data


def test_short_reads_do_not_truncate_the_payload():
    data = b"".join(b"ts=%d host=edge-01 lvl=INFO\n" % index for index in range(500))
    _, back = roundtrip(data, short=True)
    assert back == data


def test_byte_helpers_agree_with_the_stream_api():
    data = b"ts=1 host=a\n" * 100
    frame, back = roundtrip(data)
    assert zipstream.decompress_bytes(frame) == data
    assert zipstream.decompress_bytes(zipstream.compress_bytes(data)) == data


# ----------------------------------------------------------------- the container


def test_every_frame_starts_with_the_magic():
    for data in (b"", b"x", b"telemetry" * 100):
        frame, _ = roundtrip(data)
        assert frame[:2] == b"ZS", "frames must be identifiable by their first two bytes"


def test_decompress_rejects_a_stream_that_is_not_a_frame():
    with pytest.raises(zipstream.CorruptStream):
        zipstream.decompress_bytes(b"not a zipstream frame at all")


def test_decompress_rejects_an_empty_input():
    with pytest.raises(zipstream.CorruptStream):
        zipstream.decompress_bytes(b"")


def test_decompress_rejects_a_truncated_frame():
    data = b"".join(b"row,%d,%d\n" % (index, index * 7) for index in range(2000))
    frame, _ = roundtrip(data)
    assert len(frame) > 40
    with pytest.raises(zipstream.CorruptStream):
        zipstream.decompress_bytes(frame[: len(frame) // 2])


# -------------------------------------------------------------- it does compress


def test_repetitive_input_gets_smaller():
    data = b"ts=1713451200 host=edge-01 svc=ingest lvl=INFO\n" * 2000
    frame, back = roundtrip(data)
    assert back == data
    assert len(frame) < (len(data) * 3) // 4, "a highly repetitive stream must compress"
