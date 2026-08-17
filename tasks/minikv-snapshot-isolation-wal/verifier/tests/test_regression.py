"""Behaviour that minikv already has and must keep.

The grader runs its own pristine copy of this file, so editing it locally does
not change your score.
"""

import pytest

from minikv import MiniKV


@pytest.fixture()
def db(tmp_path):
    store = MiniKV(str(tmp_path / "db"))
    yield store
    store.close()


def test_get_missing_key_returns_none(db):
    assert db.get(b"nope") is None


def test_put_then_get(db):
    db.put(b"a", b"1")
    assert db.get(b"a") == b"1"


def test_put_overwrites(db):
    db.put(b"a", b"1")
    db.put(b"a", b"2")
    assert db.get(b"a") == b"2"


def test_empty_value_roundtrips(db):
    db.put(b"a", b"")
    assert db.get(b"a") == b""


def test_delete_reports_existence(db):
    db.put(b"a", b"1")
    assert db.delete(b"a") is True
    assert db.delete(b"a") is False
    assert db.get(b"a") is None


def test_scan_is_sorted_and_prefix_filtered(db):
    db.put(b"user:2", b"b")
    db.put(b"user:1", b"a")
    db.put(b"post:1", b"p")
    assert db.scan(b"user:") == [(b"user:1", b"a"), (b"user:2", b"b")]
    assert db.scan() == [(b"post:1", b"p"), (b"user:1", b"a"), (b"user:2", b"b")]


def test_scan_skips_deleted(db):
    db.put(b"a", b"1")
    db.put(b"b", b"2")
    db.delete(b"a")
    assert db.scan() == [(b"b", b"2")]


def test_data_survives_reopen(tmp_path):
    path = str(tmp_path / "db")
    with MiniKV(path) as db:
        db.put(b"k", b"v")
    with MiniKV(path) as db:
        assert db.get(b"k") == b"v"


def test_reopen_sees_deletes(tmp_path):
    path = str(tmp_path / "db")
    with MiniKV(path) as db:
        db.put(b"k", b"v")
        db.delete(b"k")
    with MiniKV(path) as db:
        assert db.get(b"k") is None
        assert db.scan() == []


def test_type_errors(db):
    with pytest.raises(TypeError):
        db.put("a", b"1")
    with pytest.raises(TypeError):
        db.put(b"a", "1")
    with pytest.raises(TypeError):
        db.get("a")
    with pytest.raises(TypeError):
        db.scan("a")


def test_value_errors(db):
    with pytest.raises(ValueError):
        db.put(b"", b"1")
    with pytest.raises(ValueError):
        db.put(b"k" * 5000, b"1")


def test_close_is_idempotent(tmp_path):
    db = MiniKV(str(tmp_path / "db"))
    db.close()
    db.close()
    with pytest.raises(ValueError):
        db.get(b"a")


def test_many_keys_roundtrip(tmp_path):
    path = str(tmp_path / "db")
    with MiniKV(path) as db:
        for i in range(200):
            db.put(f"k{i:04d}".encode(), f"v{i}".encode())
    with MiniKV(path) as db:
        assert len(db.scan()) == 200
        assert db.get(b"k0137") == b"v137"
