"""Framing for the write-ahead log and the checkpoint file.

Both files use the same record frame::

    [u32 payload_len][u32 crc32(payload)][payload]

so a torn or damaged record is always detectable: either the frame header is
short, or the payload is short, or the checksum does not match.  In every case
the reader treats that offset as the end of the file.

A WAL payload is one commit::

    [u64 version][u32 entry_count]  then entry_count of
    [u32 key_len][u32 value_len][key][value]

with ``value_len == TOMBSTONE`` marking a delete.
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Optional, Tuple

WAL_MAGIC = b"MKVWAL\x01\x00"
SNAPSHOT_MAGIC = b"MKVSNP\x01\x00"

TOMBSTONE = 0xFFFFFFFF
MAX_PAYLOAD = 256 * 1024 * 1024

_FRAME = struct.Struct("<II")
_COMMIT_HEAD = struct.Struct("<QI")
_ENTRY_HEAD = struct.Struct("<II")

Entry = Tuple[bytes, Optional[bytes]]


def encode_commit(version: int, entries: List[Entry]) -> bytes:
    """Serialise one commit into a framed record."""
    parts = [_COMMIT_HEAD.pack(version, len(entries))]
    for key, value in entries:
        if value is None:
            parts.append(_ENTRY_HEAD.pack(len(key), TOMBSTONE))
            parts.append(key)
        else:
            parts.append(_ENTRY_HEAD.pack(len(key), len(value)))
            parts.append(key)
            parts.append(value)
    payload = b"".join(parts)
    return _FRAME.pack(len(payload), zlib.crc32(payload)) + payload


def _decode_payload(payload: bytes) -> Tuple[int, List[Entry]]:
    version, count = _COMMIT_HEAD.unpack_from(payload, 0)
    offset = _COMMIT_HEAD.size
    entries: List[Entry] = []
    for _ in range(count):
        key_len, value_len = _ENTRY_HEAD.unpack_from(payload, offset)
        offset += _ENTRY_HEAD.size
        key = payload[offset : offset + key_len]
        if len(key) != key_len:
            raise ValueError("truncated key")
        offset += key_len
        if value_len == TOMBSTONE:
            entries.append((key, None))
            continue
        value = payload[offset : offset + value_len]
        if len(value) != value_len:
            raise ValueError("truncated value")
        offset += value_len
        entries.append((key, value))
    if offset != len(payload):
        raise ValueError("trailing bytes in payload")
    return version, entries


def read_records(blob: bytes, start: int) -> Tuple[List[Tuple[int, List[Entry]]], int]:
    """Read commits from ``blob`` until the first damaged or partial record.

    Returns the commits plus the offset just past the last good one.  Stopping
    at the first bad record - rather than trying to resynchronise past it - is
    what makes recovery produce a prefix of the commit history, and the offset
    is where the log has to be truncated before anything new is appended.
    """
    records: List[Tuple[int, List[Entry]]] = []
    offset = start
    total = len(blob)
    while offset + _FRAME.size <= total:
        payload_len, expected_crc = _FRAME.unpack_from(blob, offset)
        if payload_len > MAX_PAYLOAD:
            break
        body_start = offset + _FRAME.size
        body_end = body_start + payload_len
        if body_end > total:
            break
        payload = blob[body_start:body_end]
        if zlib.crc32(payload) != expected_crc:
            break
        try:
            records.append(_decode_payload(payload))
        except (ValueError, struct.error):
            break
        offset = body_end
    return records, offset
