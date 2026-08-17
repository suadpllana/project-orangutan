"""Surface area: types, validation, lifecycle, stats."""

import pytest

import minikv
from minikv import (
    ConflictError,
    MiniKV,
    MiniKVError,
    Transaction,
    TransactionClosedError,
)


@pytest.fixture()
def db(tmp_path):
    store = MiniKV(str(tmp_path / "db"))
    yield store
    store.close()


def test_exception_hierarchy(db):
    assert issubclass(ConflictError, MiniKVError)
    assert issubclass(TransactionClosedError, MiniKVError)
    assert issubclass(minikv.CorruptDatabaseError, MiniKVError)

    # The classes have to be the ones actually raised, not lookalikes.
    db.put(b"k", b"base")
    winner, loser = db.begin(), db.begin()
    loser.put(b"k", b"mine")
    winner.put(b"k", b"theirs")
    winner.commit()
    with pytest.raises(MiniKVError):
        loser.commit()
    with pytest.raises(MiniKVError):
        loser.get(b"k")


def test_begin_returns_a_transaction(db):
    txn = db.begin()
    assert isinstance(txn, Transaction)
    txn.rollback()


def test_directory_is_created(tmp_path):
    path = tmp_path / "deep" / "db"
    with MiniKV(str(path)) as db:
        with db.begin() as txn:
            txn.put(b"k", b"v")
    assert path.is_dir()
    assert (path / "wal.log").exists(), "the log must live inside the directory"


@pytest.mark.parametrize("bad", ["a", bytearray(b"a"), memoryview(b"a"), 1, None])
def test_key_type_is_enforced(db, bad):
    txn = db.begin()
    for call in (
        lambda: db.get(bad),
        lambda: db.put(bad, b"v"),
        lambda: db.delete(bad),
        lambda: txn.get(bad),
        lambda: txn.put(bad, b"v"),
        lambda: txn.delete(bad),
    ):
        with pytest.raises(TypeError):
            call()
    txn.rollback()


@pytest.mark.parametrize("bad", ["v", bytearray(b"v"), 1, None])
def test_value_type_is_enforced(db, bad):
    txn = db.begin()
    with pytest.raises(TypeError):
        db.put(b"k", bad)
    with pytest.raises(TypeError):
        txn.put(b"k", bad)
    txn.rollback()


@pytest.mark.parametrize("bad", ["a", None, 1])
def test_prefix_type_is_enforced(db, bad):
    txn = db.begin()
    with pytest.raises(TypeError):
        db.scan(bad)
    with pytest.raises(TypeError):
        txn.scan(bad)
    txn.rollback()


def test_empty_key_is_rejected(db):
    txn = db.begin()
    with pytest.raises(ValueError):
        db.put(b"", b"v")
    with pytest.raises(ValueError):
        db.get(b"")
    with pytest.raises(ValueError):
        txn.put(b"", b"v")
    txn.rollback()


def test_size_limits(db):
    db.put(b"k" * 4096, b"v" * 1048576)
    with pytest.raises(ValueError):
        db.put(b"k" * 4097, b"v")
    with pytest.raises(ValueError):
        db.put(b"k", b"v" * 1048577)

    txn = db.begin()
    assert txn.get(b"k" * 4096) == b"v" * 1048576
    with pytest.raises(ValueError):
        txn.put(b"k" * 4097, b"v")
    with pytest.raises(ValueError):
        txn.put(b"k", b"v" * 1048577)
    txn.rollback()


def test_rejected_call_changes_nothing(db):
    db.put(b"k", b"v")
    before = db.stats()["commit_version"]
    with pytest.raises(TypeError):
        db.put(b"k", "not bytes")
    with pytest.raises(ValueError):
        db.put(b"", b"v")
    assert db.stats()["commit_version"] == before
    assert db.scan() == [(b"k", b"v")]


def test_rejected_transaction_write_changes_nothing(db):
    txn = db.begin()
    txn.put(b"a", b"1")
    with pytest.raises(TypeError):
        txn.put(b"b", "not bytes")
    txn.commit()
    assert db.scan() == [(b"a", b"1")]


def test_empty_value_roundtrips_through_a_transaction(db):
    with db.begin() as txn:
        txn.put(b"k", b"")
    assert db.get(b"k") == b""
    assert db.scan() == [(b"k", b"")]


def test_stats_shape(db):
    db.put(b"k", b"v")
    stats = db.stats()
    for field in ("commit_version", "live_keys", "wal_bytes", "total_bytes"):
        assert field in stats, f"stats() is missing {field}"
        assert isinstance(stats[field], int), f"stats()[{field!r}] must be an int"
    assert stats["live_keys"] == 1


def test_stats_live_keys_tracks_deletes(db):
    for i in range(10):
        db.put(f"k{i}".encode(), b"v")
    assert db.stats()["live_keys"] == 10
    db.delete(b"k0")
    db.delete(b"k1")
    assert db.stats()["live_keys"] == 8


def test_stats_wal_bytes_matches_the_file(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        for i in range(20):
            db.put(f"k{i}".encode(), b"v" * 50)
        assert db.stats()["wal_bytes"] == (path / "wal.log").stat().st_size


def test_close_rejects_further_use(tmp_path):
    db = MiniKV(str(tmp_path / "db"))
    db.put(b"k", b"v")
    db.close()
    db.close()
    for call in (
        lambda: db.get(b"k"),
        lambda: db.put(b"k", b"v"),
        lambda: db.delete(b"k"),
        lambda: db.scan(),
        lambda: db.begin(),
        lambda: db.checkpoint(),
        lambda: db.stats(),
    ):
        with pytest.raises(ValueError):
            call()


def test_store_context_manager_closes(tmp_path):
    path = tmp_path / "db"
    with MiniKV(str(path)) as db:
        with db.begin() as txn:
            txn.put(b"k", b"v")
    with pytest.raises(ValueError):
        db.get(b"k")
    with MiniKV(str(path)) as reopened:
        assert reopened.get(b"k") == b"v"
