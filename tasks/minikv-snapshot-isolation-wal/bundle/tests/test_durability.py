"""Crash recovery: what survives SIGKILL, and what a damaged log may do."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from minikv import MiniKV

HELPER = Path(__file__).parent / "crash_child.py"
SIGKILL_RC = -9


def crash(scenario, path):
    """Run a scenario in a child process that kills itself, then assert it did."""
    proc = subprocess.run(
        [sys.executable, str(HELPER), scenario, str(path)],
        capture_output=True,
        timeout=180,
    )
    assert proc.returncode == SIGKILL_RC, (
        f"{scenario} did not die by SIGKILL (rc={proc.returncode})\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def snapshot_of(path):
    with MiniKV(str(path)) as db:
        return dict(db.scan())


def recovered_state(path):
    """Reopen and return (contents, stats), checking the log did the work.

    The specification requires `wal.log` to be the mechanism by which committed
    data reaches disk, so a store that recovered real data with no log did not
    implement what was asked.
    """
    with MiniKV(str(path)) as db:
        contents = dict(db.scan())
        stats = db.stats()
    wal = Path(path) / "wal.log"
    assert wal.exists(), "the specification requires a log file named wal.log"
    return contents, stats


# ----------------------------------------------------------------------
# committed data survives
# ----------------------------------------------------------------------
def test_autocommit_writes_survive_sigkill(tmp_path):
    path = tmp_path / "db"
    crash("commit_then_kill", path)
    contents, stats = recovered_state(path)
    assert contents == {f"k{i}".encode(): f"v{i}".encode() for i in range(5)}
    assert stats["commit_version"] == 5


def test_committed_transaction_survives_sigkill(tmp_path):
    path = tmp_path / "db"
    crash("txn_commit_then_kill", path)
    contents, stats = recovered_state(path)
    assert contents == {b"a": b"1", b"b": b"2", b"c": b"3"}
    assert stats["commit_version"] == 1, "one transaction is one commit"


def test_deletes_survive_sigkill(tmp_path):
    path = tmp_path / "db"
    crash("delete_then_kill", path)
    contents, stats = recovered_state(path)
    assert contents == {b"b": b"2"}
    assert stats["commit_version"] == 3


def test_checkpoint_plus_later_writes_survive_sigkill(tmp_path):
    path = tmp_path / "db"
    crash("checkpoint_then_kill", path)
    recovered = snapshot_of(path)
    assert len(recovered) == 110
    assert recovered[b"k0000"] == b"v0"
    assert recovered[b"k0109"] == b"v109"


@pytest.mark.parametrize("attempt", range(6))
def test_kill_during_checkpoint_loses_nothing(tmp_path, attempt):
    path = tmp_path / "db"
    crash("checkpoint_race", path)
    recovered = snapshot_of(path)
    expected = {f"k{i:04d}".encode(): f"v{i}".encode() for i in range(2000)}
    assert recovered == expected


# ----------------------------------------------------------------------
# uncommitted data does not survive
# ----------------------------------------------------------------------
def test_open_transaction_leaves_no_trace(tmp_path):
    path = tmp_path / "db"
    crash("txn_open_then_kill", path)
    assert snapshot_of(path) == {b"committed": b"yes"}


def test_rolled_back_transaction_leaves_no_trace(tmp_path):
    path = tmp_path / "db"
    crash("rollback_then_kill", path)
    assert snapshot_of(path) == {b"keep": b"1", b"keep2": b"2"}


# ----------------------------------------------------------------------
# a damaged log must degrade to a prefix of history
# ----------------------------------------------------------------------
COMMITS = 10


def build_history(path):
    """Ten single-key commits, so history is trivially ordered."""
    with MiniKV(str(path)) as db:
        for i in range(COMMITS):
            db.put(f"k{i:03d}".encode(), f"v{i:03d}".encode())


def assert_prefix_state(path):
    """Reopening must yield k000..k(j-1) for some j, with correct values."""
    with MiniKV(str(path)) as db:
        state = dict(db.scan())

    expected_keys = [f"k{i:03d}".encode() for i in range(COMMITS)]
    for key, value in state.items():
        assert key in expected_keys, f"recovery invented key {key!r}"
        index = int(key[1:])
        assert value == f"v{index:03d}".encode(), f"wrong value for {key!r}: {value!r}"

    present = sorted(int(k[1:]) for k in state)
    assert present == list(range(len(present))), (
        f"recovered state is not a prefix of history: {present}"
    )
    return len(present)


def wal_path(path):
    wal = Path(path) / "wal.log"
    assert wal.exists(), "the specification requires a log file named wal.log"
    return wal


@pytest.mark.parametrize("keep_fraction", [0.0, 0.17, 0.33, 0.5, 0.66, 0.8, 0.93, 0.99])
def test_truncated_log_recovers_to_a_prefix(tmp_path, keep_fraction):
    source = tmp_path / "src"
    build_history(source)
    damaged = tmp_path / f"trunc{int(keep_fraction * 100)}"
    shutil.copytree(source, damaged)

    wal = wal_path(damaged)
    size = wal.stat().st_size
    os.truncate(wal, int(size * keep_fraction))
    assert_prefix_state(damaged)


@pytest.mark.parametrize("position", [0.05, 0.2, 0.4, 0.55, 0.7, 0.85, 0.95, 0.999])
def test_corrupted_log_byte_recovers_to_a_prefix(tmp_path, position):
    source = tmp_path / "src"
    build_history(source)
    damaged = tmp_path / f"corrupt{int(position * 1000)}"
    shutil.copytree(source, damaged)

    wal = wal_path(damaged)
    blob = bytearray(wal.read_bytes())
    if not blob:
        pytest.skip("implementation keeps no log records to corrupt")
    offset = min(len(blob) - 1, int(len(blob) * position))
    blob[offset] ^= 0xFF
    wal.write_bytes(bytes(blob))
    assert_prefix_state(damaged)


def test_truncation_keeps_the_surviving_prefix_readable(tmp_path):
    """Cutting the tail must not cost more than the tail."""
    source = tmp_path / "src"
    build_history(source)

    full = tmp_path / "full"
    shutil.copytree(source, full)
    total = assert_prefix_state(full)
    assert total == COMMITS, "a clean reopen must see every commit"

    damaged = tmp_path / "cut"
    shutil.copytree(source, damaged)
    wal = wal_path(damaged)
    size = wal.stat().st_size
    if size <= 16:
        pytest.skip("implementation keeps no log records to truncate")
    os.truncate(wal, size - 1)
    assert assert_prefix_state(damaged) < COMMITS


def test_damaged_log_is_still_writable_afterwards(tmp_path):
    source = tmp_path / "src"
    build_history(source)
    damaged = tmp_path / "cut"
    shutil.copytree(source, damaged)

    wal = wal_path(damaged)
    size = wal.stat().st_size
    os.truncate(wal, max(0, size - 3))

    with MiniKV(str(damaged)) as db:
        db.put(b"after", b"recovery")
    with MiniKV(str(damaged)) as db:
        assert db.get(b"after") == b"recovery"


def test_empty_directory_opens_clean(tmp_path):
    path = tmp_path / "fresh"
    path.mkdir()
    with MiniKV(str(path)) as db:
        assert db.scan() == []
        assert db.stats()["commit_version"] == 0


def test_reopen_preserves_commit_version(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        for i in range(7):
            db.put(f"k{i}".encode(), b"v")
        before = db.stats()["commit_version"]
    with MiniKV(str(path)) as db:
        assert db.stats()["commit_version"] == before
