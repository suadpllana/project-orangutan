"""Checkpointing has to actually reclaim space, and never lose data."""

import pytest

from minikv import MiniKV

WAL_BUDGET = 4096
DIR_OVERHEAD = 65536


def dir_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def logical_bytes(pairs):
    return sum(len(k) + len(v) for k, v in pairs)


def churn(db, keys=3000, rewrites=4, deletes=1000):
    for i in range(keys):
        db.put(f"key:{i:06d}".encode(), b"v" * 80)
    for generation in range(rewrites):
        for i in range(keys):
            db.put(f"key:{i:06d}".encode(), bytes([generation]) * 80)
    for i in range(deletes):
        db.delete(f"key:{i:06d}".encode())


def test_checkpoint_bounds_the_log(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        churn(db)
        assert db.stats()["wal_bytes"] > WAL_BUDGET, (
            "the log should be large before the checkpoint - if it is not, the "
            "write path is not append-based"
        )
        db.checkpoint()
        assert (path / "wal.log").exists(), "wal.log must survive a checkpoint"
        assert db.stats()["wal_bytes"] <= WAL_BUDGET


def test_checkpoint_bounds_the_directory(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        churn(db)
        db.checkpoint()
        live = db.scan()
    budget = 4 * logical_bytes(live) + DIR_OVERHEAD
    assert dir_bytes(path) <= budget, (
        f"directory is {dir_bytes(path)} bytes for {logical_bytes(live)} bytes of "
        f"live data; superseded versions are not being reclaimed"
    )


def test_checkpoint_preserves_contents(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        churn(db, keys=800, rewrites=2, deletes=300)
        before = db.scan()
        db.checkpoint()
        assert db.scan() == before
    with MiniKV(str(path)) as db:
        assert db.scan() == before
        assert db.stats()["live_keys"] == len(before)


def test_writes_after_checkpoint_are_durable(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        for i in range(100):
            db.put(f"k{i:04d}".encode(), b"before")
        db.checkpoint()
        for i in range(100, 150):
            db.put(f"k{i:04d}".encode(), b"after")
        db.delete(b"k0000")
    with MiniKV(str(path)) as db:
        assert db.get(b"k0000") is None
        assert db.get(b"k0099") == b"before"
        assert db.get(b"k0149") == b"after"
        assert db.stats()["live_keys"] == 149


def test_checkpoint_on_empty_database(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        db.checkpoint()
        assert db.scan() == []
    with MiniKV(str(path)) as db:
        assert db.scan() == []
        assert db.stats()["commit_version"] == 0


def test_repeated_checkpoints_are_stable(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        churn(db, keys=500, rewrites=2, deletes=100)
        db.checkpoint()
        first = dir_bytes(path)
        for _ in range(5):
            db.checkpoint()
        assert dir_bytes(path) <= first + DIR_OVERHEAD
        assert db.stats()["live_keys"] == 400


def test_checkpoint_does_not_bump_commit_version(tmp_path):
    with MiniKV(str(tmp_path / "db")) as db:
        for i in range(20):
            db.put(f"k{i}".encode(), b"v")
        before = db.stats()["commit_version"]
        db.checkpoint()
        assert db.stats()["commit_version"] == before


def test_checkpoint_then_transaction(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        db.put(b"k", b"v")
        db.checkpoint()
        with db.begin() as txn:
            txn.put(b"j", b"w")
    with MiniKV(str(path)) as db:
        assert db.scan() == [(b"j", b"w"), (b"k", b"v")]


def test_all_deleted_checkpoints_to_almost_nothing(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        for i in range(2000):
            db.put(f"k{i:05d}".encode(), b"v" * 100)
        for i in range(2000):
            db.delete(f"k{i:05d}".encode())
        db.checkpoint()
        assert db.stats()["live_keys"] == 0
    assert dir_bytes(path) <= DIR_OVERHEAD
    with MiniKV(str(path)) as db:
        assert db.scan() == []
