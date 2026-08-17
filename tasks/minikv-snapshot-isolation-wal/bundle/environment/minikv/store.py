"""The MiniKV store.

The current implementation is deliberately simple: the whole database is kept
in a dict and the entire dict is rewritten to ``data.json`` after every
mutation.  That is correct for a toy workload but it is O(n) per write, it
loses data if the process dies mid-rewrite, and it has no notion of a
transaction.

See ``SPEC.md`` for the behaviour the store is required to have.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Dict, List, Optional, Tuple

from .errors import CorruptDatabaseError
from .txn import Transaction

MAX_KEY_BYTES = 4 * 1024
MAX_VALUE_BYTES = 1024 * 1024

DATA_FILE = "data.json"
WAL_FILE = "wal.log"


def _check_key(key: object) -> bytes:
    if not isinstance(key, bytes):
        raise TypeError(f"key must be bytes, got {type(key).__name__}")
    if len(key) == 0:
        raise ValueError("key must not be empty")
    if len(key) > MAX_KEY_BYTES:
        raise ValueError(f"key must be at most {MAX_KEY_BYTES} bytes")
    return key


def _check_value(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(f"value must be bytes, got {type(value).__name__}")
    if len(value) > MAX_VALUE_BYTES:
        raise ValueError(f"value must be at most {MAX_VALUE_BYTES} bytes")
    return value


def _check_prefix(prefix: object) -> bytes:
    if not isinstance(prefix, bytes):
        raise TypeError(f"prefix must be bytes, got {type(prefix).__name__}")
    return prefix


class MiniKV:
    """An embedded key/value store backed by a directory on disk."""

    def __init__(self, path: str) -> None:
        self.path = os.fspath(path)
        os.makedirs(self.path, exist_ok=True)
        self._closed = False
        self._data: Dict[bytes, bytes] = {}
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def _data_path(self) -> str:
        return os.path.join(self.path, DATA_FILE)

    def _load(self) -> None:
        try:
            with open(self._data_path(), "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            self._data = {}
            return
        except json.JSONDecodeError as exc:
            raise CorruptDatabaseError(f"{DATA_FILE} is not valid JSON") from exc

        self._data = {
            base64.b64decode(k): base64.b64decode(v) for k, v in raw.items()
        }

    def _flush(self) -> None:
        raw = {
            base64.b64encode(k).decode("ascii"): base64.b64encode(v).decode("ascii")
            for k, v in self._data.items()
        }
        with open(self._data_path(), "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

    # ------------------------------------------------------------------
    # autocommit API
    # ------------------------------------------------------------------
    def get(self, key: bytes) -> Optional[bytes]:
        self._assert_open()
        return self._data.get(_check_key(key))

    def put(self, key: bytes, value: bytes) -> None:
        self._assert_open()
        self._data[_check_key(key)] = _check_value(value)
        self._flush()

    def delete(self, key: bytes) -> bool:
        self._assert_open()
        existed = self._data.pop(_check_key(key), None) is not None
        self._flush()
        return existed

    def scan(self, prefix: bytes = b"") -> List[Tuple[bytes, bytes]]:
        self._assert_open()
        prefix = _check_prefix(prefix)
        return sorted(
            (k, v) for k, v in self._data.items() if k.startswith(prefix)
        )

    # ------------------------------------------------------------------
    # transactional API - not implemented yet, see SPEC.md
    # ------------------------------------------------------------------
    def begin(self) -> Transaction:
        raise NotImplementedError("transactions are not implemented yet")

    def checkpoint(self) -> None:
        raise NotImplementedError("checkpointing is not implemented yet")

    def stats(self) -> dict:
        raise NotImplementedError("stats() is not implemented yet")

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._flush()
        self._closed = True

    def _assert_open(self) -> None:
        if self._closed:
            raise ValueError("database is closed")

    def __enter__(self) -> "MiniKV":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
