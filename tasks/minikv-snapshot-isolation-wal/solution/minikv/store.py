"""The MiniKV store: MVCC in memory, an append-only log on disk.

Design in one paragraph.  Every committed write lands in ``wal.log`` as one
framed record before it becomes visible, so durability is just "append, then
flush".  In memory each key owns a version chain, which is what lets a
transaction read a consistent snapshot while other writers keep committing.
Conflict detection is first-committer-wins on the write set only, which is
exactly snapshot isolation - write skew is allowed through on purpose.
``checkpoint()`` rewrites the live set into ``snapshot.dat`` atomically and
then truncates the log, bounding both the file size and the length of the
version chains.
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .errors import ConflictError, CorruptDatabaseError
from .txn import Transaction
from .wal import SNAPSHOT_MAGIC, WAL_MAGIC, encode_commit, read_records

MAX_KEY_BYTES = 4 * 1024
MAX_VALUE_BYTES = 1024 * 1024

WAL_FILE = "wal.log"
SNAPSHOT_FILE = "snapshot.dat"
SNAPSHOT_TMP = "snapshot.dat.tmp"

Chain = List[Tuple[int, Optional[bytes]]]


class MiniKV:
    """An embedded key/value store backed by a directory on disk."""

    def __init__(self, path: str) -> None:
        self.path = os.fspath(path)
        os.makedirs(self.path, exist_ok=True)

        self._lock = threading.RLock()
        self._closed = False

        # Current committed state, and the full version chains behind it.
        self._latest: Dict[bytes, bytes] = {}
        self._versions: Dict[bytes, Chain] = {}
        self._commit_version = 0
        self._checkpoint_version = 0
        self._active: Counter = Counter()

        self._wal = None
        self._wal_end = None
        self._recover()

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    @staticmethod
    def _check_key(key: object) -> bytes:
        if type(key) is not bytes:
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        if len(key) == 0:
            raise ValueError("key must not be empty")
        if len(key) > MAX_KEY_BYTES:
            raise ValueError(f"key must be at most {MAX_KEY_BYTES} bytes")
        return key

    @staticmethod
    def _check_value(value: object) -> bytes:
        if type(value) is not bytes:
            raise TypeError(f"value must be bytes, got {type(value).__name__}")
        if len(value) > MAX_VALUE_BYTES:
            raise ValueError(f"value must be at most {MAX_VALUE_BYTES} bytes")
        return value

    @staticmethod
    def _check_prefix(prefix: object) -> bytes:
        if type(prefix) is not bytes:
            raise TypeError(f"prefix must be bytes, got {type(prefix).__name__}")
        return prefix

    def _assert_open(self) -> None:
        if self._closed:
            raise ValueError("database is closed")

    # ------------------------------------------------------------------
    # recovery
    # ------------------------------------------------------------------
    def _p(self, name: str) -> str:
        return os.path.join(self.path, name)

    def _recover(self) -> None:
        try:
            os.unlink(self._p(SNAPSHOT_TMP))
        except FileNotFoundError:
            pass

        self._load_snapshot()
        self._replay_wal()
        self._open_wal()

    def _load_snapshot(self) -> None:
        try:
            with open(self._p(SNAPSHOT_FILE), "rb") as handle:
                blob = handle.read()
        except FileNotFoundError:
            return
        if not blob.startswith(SNAPSHOT_MAGIC):
            raise CorruptDatabaseError(f"{SNAPSHOT_FILE} has a bad header")
        records, _end = read_records(blob, len(SNAPSHOT_MAGIC))
        if not records:
            raise CorruptDatabaseError(f"{SNAPSHOT_FILE} contains no usable record")
        version, entries = records[0]
        self._apply_locked(version, entries)
        self._checkpoint_version = version
        self._commit_version = version

    def _replay_wal(self) -> None:
        try:
            with open(self._p(WAL_FILE), "rb") as handle:
                blob = handle.read()
        except FileNotFoundError:
            self._wal_end = None
            return
        if not blob.startswith(WAL_MAGIC):
            # An unreadable header means nothing in the log can be trusted; the
            # snapshot alone is still a valid prefix of history.  Signal that
            # the log has to be started over.
            self._wal_end = 0
            return
        records, end = read_records(blob, len(WAL_MAGIC))
        for version, entries in records:
            if version <= self._checkpoint_version:
                # Already folded into the snapshot; the log had not been
                # truncated yet when the process died.
                continue
            self._apply_locked(version, entries)
            self._commit_version = version
        self._wal_end = end

    def _open_wal(self) -> None:
        path = self._p(WAL_FILE)
        if self._wal_end is None:
            with open(path, "wb") as handle:
                handle.write(WAL_MAGIC)
            self._wal = open(path, "r+b")
            self._wal.seek(0, os.SEEK_END)
            return

        self._wal = open(path, "r+b")
        if self._wal_end == 0:
            # Damaged header: rebuild an empty log.
            self._wal.seek(0)
            self._wal.truncate()
            self._wal.write(WAL_MAGIC)
        elif os.path.getsize(path) > self._wal_end:
            # Drop the damaged tail, otherwise the next append would land
            # behind a record recovery already refuses to read.
            self._wal.seek(self._wal_end)
            self._wal.truncate()
        self._wal.flush()
        self._wal.seek(0, os.SEEK_END)

    # ------------------------------------------------------------------
    # applying commits
    # ------------------------------------------------------------------
    def _apply_locked(self, version: int, entries) -> None:
        for key, value in entries:
            self._versions.setdefault(key, []).append((version, value))
            if value is None:
                self._latest.pop(key, None)
            else:
                self._latest[key] = value

    def _write_commit(self, version: int, entries: List[Tuple[bytes, Optional[bytes]]]) -> None:
        self._wal.write(encode_commit(version, entries))
        # flush() hands the bytes to the kernel, which is what "survives
        # SIGKILL" means.  No fsync: surviving a power cut is out of scope.
        self._wal.flush()

    # ------------------------------------------------------------------
    # snapshot reads (called by Transaction)
    # ------------------------------------------------------------------
    def _read_at(self, key: bytes, snapshot: int) -> Optional[bytes]:
        with self._lock:
            self._assert_open()
            if snapshot >= self._commit_version:
                return self._latest.get(key)
            chain = self._versions.get(key)
            if not chain:
                return None
            value = None
            for version, candidate in chain:
                if version > snapshot:
                    break
                value = candidate
            return value

    def _scan_at(self, prefix: bytes, snapshot: int) -> List[Tuple[bytes, bytes]]:
        with self._lock:
            self._assert_open()
            if snapshot >= self._commit_version:
                return sorted(
                    (k, v) for k, v in self._latest.items() if k.startswith(prefix)
                )
            out = []
            for key, chain in self._versions.items():
                if not key.startswith(prefix):
                    continue
                value = None
                for version, candidate in chain:
                    if version > snapshot:
                        break
                    value = candidate
                if value is not None:
                    out.append((key, value))
            return sorted(out)

    def _release_snapshot(self, snapshot: int) -> None:
        with self._lock:
            if self._active[snapshot] <= 1:
                del self._active[snapshot]
            else:
                self._active[snapshot] -= 1

    def _commit_txn(self, snapshot: int, writes: Dict[bytes, Optional[bytes]]) -> None:
        with self._lock:
            self._assert_open()
            for key in writes:
                chain = self._versions.get(key)
                if chain and chain[-1][0] > snapshot:
                    raise ConflictError(
                        f"key {key!r} was written after this transaction's snapshot"
                    )
            version = self._commit_version + 1
            entries = sorted(writes.items())
            self._write_commit(version, entries)
            self._apply_locked(version, entries)
            self._commit_version = version

    # ------------------------------------------------------------------
    # autocommit API
    # ------------------------------------------------------------------
    def get(self, key: bytes) -> Optional[bytes]:
        with self._lock:
            self._assert_open()
            return self._latest.get(self._check_key(key))

    def put(self, key: bytes, value: bytes) -> None:
        key = self._check_key(key)
        value = self._check_value(value)
        with self._lock:
            self._assert_open()
            version = self._commit_version + 1
            self._write_commit(version, [(key, value)])
            self._apply_locked(version, [(key, value)])
            self._commit_version = version

    def delete(self, key: bytes) -> bool:
        key = self._check_key(key)
        with self._lock:
            self._assert_open()
            existed = key in self._latest
            version = self._commit_version + 1
            self._write_commit(version, [(key, None)])
            self._apply_locked(version, [(key, None)])
            self._commit_version = version
            return existed

    def scan(self, prefix: bytes = b"") -> List[Tuple[bytes, bytes]]:
        prefix = self._check_prefix(prefix)
        with self._lock:
            self._assert_open()
            return sorted(
                (k, v) for k, v in self._latest.items() if k.startswith(prefix)
            )

    def begin(self) -> Transaction:
        with self._lock:
            self._assert_open()
            snapshot = self._commit_version
            self._active[snapshot] += 1
            return Transaction(self, snapshot)

    # ------------------------------------------------------------------
    # checkpointing
    # ------------------------------------------------------------------
    def checkpoint(self) -> None:
        with self._lock:
            self._assert_open()
            version = self._commit_version
            entries = sorted(self._latest.items())

            tmp = self._p(SNAPSHOT_TMP)
            with open(tmp, "wb") as handle:
                handle.write(SNAPSHOT_MAGIC)
                handle.write(encode_commit(version, entries))
                handle.flush()
            # Atomic: readers see either the old snapshot or the new one.  The
            # log is only truncated afterwards, so a crash in between just
            # replays records the snapshot already contains.
            os.replace(tmp, self._p(SNAPSHOT_FILE))

            self._wal.seek(len(WAL_MAGIC))
            self._wal.truncate()
            self._wal.flush()
            self._wal.seek(0, os.SEEK_END)

            self._checkpoint_version = version
            self._prune_locked()

    def _prune_locked(self) -> None:
        """Drop version-chain entries no open transaction can still reach."""
        horizon = self._checkpoint_version
        if self._active:
            horizon = min(horizon, min(self._active))
        for key in list(self._versions):
            chain = self._versions[key]
            keep_from = 0
            for index, (version, _value) in enumerate(chain):
                if version > horizon:
                    break
                keep_from = index
            trimmed = chain[keep_from:]
            if len(trimmed) == 1 and trimmed[0][1] is None:
                del self._versions[key]
            else:
                self._versions[key] = trimmed

    # ------------------------------------------------------------------
    # introspection and lifecycle
    # ------------------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            self._assert_open()
            total = 0
            for entry in os.scandir(self.path):
                if entry.is_file():
                    total += entry.stat().st_size
            try:
                wal_bytes = os.path.getsize(self._p(WAL_FILE))
            except FileNotFoundError:
                wal_bytes = 0
            return {
                "commit_version": self._commit_version,
                "live_keys": len(self._latest),
                "wal_bytes": wal_bytes,
                "total_bytes": total,
                "checkpoint_version": self._checkpoint_version,
                "open_transactions": sum(self._active.values()),
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._wal is not None:
                self._wal.flush()
                self._wal.close()
                self._wal = None

    def __enter__(self) -> "MiniKV":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
