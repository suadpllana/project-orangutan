"""Snapshot-isolated transactions."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .errors import TransactionClosedError

_OPEN = 0
_CLOSED = 1


class Transaction:
    """A snapshot-isolated view of a store.

    The transaction owns nothing but a snapshot version and a private write
    set.  It never holds a lock between calls, so other writers - including
    autocommit ``put``/``delete`` - stay unblocked for its whole lifetime.
    """

    __slots__ = ("_store", "_snapshot", "_writes", "_state")

    def __init__(self, store, snapshot: int) -> None:
        self._store = store
        self._snapshot = snapshot
        self._writes: Dict[bytes, Optional[bytes]] = {}
        self._state = _OPEN

    # ------------------------------------------------------------------
    @property
    def snapshot(self) -> int:
        return self._snapshot

    def _assert_open(self) -> None:
        if self._state is not _OPEN:
            raise TransactionClosedError("transaction is closed")

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get(self, key: bytes) -> Optional[bytes]:
        self._assert_open()
        key = self._store._check_key(key)
        if key in self._writes:
            return self._writes[key]
        return self._store._read_at(key, self._snapshot)

    def scan(self, prefix: bytes = b"") -> List[Tuple[bytes, bytes]]:
        self._assert_open()
        prefix = self._store._check_prefix(prefix)
        merged: Dict[bytes, bytes] = dict(self._store._scan_at(prefix, self._snapshot))
        for key, value in self._writes.items():
            if not key.startswith(prefix):
                continue
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        return sorted(merged.items())

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def put(self, key: bytes, value: bytes) -> None:
        self._assert_open()
        key = self._store._check_key(key)
        value = self._store._check_value(value)
        self._writes[key] = value

    def delete(self, key: bytes) -> bool:
        self._assert_open()
        key = self._store._check_key(key)
        existed = self.get(key) is not None
        self._writes[key] = None
        return existed

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def commit(self) -> None:
        self._assert_open()
        if not self._writes:
            self._finish()
            return
        try:
            self._store._commit_txn(self._snapshot, self._writes)
        except BaseException:
            # A conflict - or anything else that stops the commit - aborts the
            # transaction and discards its writes.
            self._finish()
            raise
        self._finish()

    def rollback(self) -> None:
        if self._state is not _OPEN:
            return
        self._finish()

    def _finish(self) -> None:
        self._writes = {}
        self._state = _CLOSED
        self._store._release_snapshot(self._snapshot)

    # ------------------------------------------------------------------
    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        self.commit()
        return False
