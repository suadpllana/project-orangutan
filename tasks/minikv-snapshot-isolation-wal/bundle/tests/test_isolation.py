"""Snapshot isolation: what a transaction sees, and when a commit loses."""

import pytest

from minikv import ConflictError, MiniKV, TransactionClosedError


@pytest.fixture()
def db(tmp_path):
    store = MiniKV(str(tmp_path / "db"))
    yield store
    store.close()


# ----------------------------------------------------------------------
# reads
# ----------------------------------------------------------------------
def test_transaction_reads_its_snapshot(db):
    db.put(b"k", b"old")
    txn = db.begin()
    db.put(b"k", b"new")
    assert txn.get(b"k") == b"old"
    txn.rollback()
    assert db.get(b"k") == b"new"


def test_begin_does_not_block_writers(db):
    """A lock held for the transaction's lifetime would deadlock right here."""
    db.put(b"k", b"old")
    txn = db.begin()
    for i in range(50):
        db.put(f"other{i}".encode(), b"x")
    db.delete(b"k")
    assert txn.get(b"k") == b"old"
    txn.rollback()


def test_many_commits_do_not_move_the_snapshot(db):
    db.put(b"k", b"v0")
    txn = db.begin()
    for i in range(1, 30):
        db.put(b"k", f"v{i}".encode())
    assert txn.get(b"k") == b"v0"
    txn.rollback()


def test_read_your_own_writes(db):
    db.put(b"k", b"old")
    txn = db.begin()
    txn.put(b"k", b"mine")
    assert txn.get(b"k") == b"mine"
    txn.delete(b"k")
    assert txn.get(b"k") is None
    txn.put(b"k", b"again")
    assert txn.get(b"k") == b"again"
    txn.rollback()
    assert db.get(b"k") == b"old"


def test_uncommitted_writes_are_invisible_outside(db):
    txn = db.begin()
    txn.put(b"secret", b"1")
    assert db.get(b"secret") is None
    assert db.scan() == []
    other = db.begin()
    assert other.get(b"secret") is None
    other.rollback()
    txn.rollback()


def test_no_phantoms_in_scan(db):
    db.put(b"a:1", b"1")
    txn = db.begin()
    db.put(b"a:2", b"2")
    db.put(b"b:1", b"1")
    assert txn.scan(b"a:") == [(b"a:1", b"1")]
    assert txn.scan() == [(b"a:1", b"1")]
    txn.rollback()


def test_scan_merges_own_writes(db):
    db.put(b"a:1", b"1")
    db.put(b"a:2", b"2")
    txn = db.begin()
    txn.put(b"a:3", b"3")
    txn.delete(b"a:1")
    txn.put(b"a:2", b"two")
    assert txn.scan(b"a:") == [(b"a:2", b"two"), (b"a:3", b"3")]
    txn.commit()
    assert db.scan(b"a:") == [(b"a:2", b"two"), (b"a:3", b"3")]


def test_delete_reports_visibility_in_snapshot(db):
    db.put(b"k", b"v")
    txn = db.begin()
    db.delete(b"k")
    assert txn.delete(b"k") is True  # still visible in the snapshot
    txn.rollback()

    txn2 = db.begin()
    assert txn2.delete(b"k") is False
    txn2.rollback()


def test_snapshot_survives_a_checkpoint(db):
    db.put(b"k", b"old")
    txn = db.begin()
    db.put(b"k", b"new")
    db.checkpoint()
    assert txn.get(b"k") == b"old"
    assert txn.scan() == [(b"k", b"old")]
    txn.rollback()


# ----------------------------------------------------------------------
# commit and conflict
# ----------------------------------------------------------------------
def test_commit_is_atomic(db):
    txn = db.begin()
    for i in range(20):
        txn.put(f"k{i:02d}".encode(), b"v")
    assert db.scan() == []
    txn.commit()
    assert len(db.scan()) == 20


def test_write_write_conflict_first_committer_wins(db):
    db.put(b"k", b"base")
    t1 = db.begin()
    t2 = db.begin()
    t1.put(b"k", b"one")
    t2.put(b"k", b"two")
    t1.commit()
    with pytest.raises(ConflictError):
        t2.commit()
    assert db.get(b"k") == b"one"


def test_autocommit_write_conflicts_with_transaction(db):
    db.put(b"k", b"base")
    txn = db.begin()
    db.put(b"k", b"autocommit")
    txn.put(b"k", b"txn")
    with pytest.raises(ConflictError):
        txn.commit()
    assert db.get(b"k") == b"autocommit"


def test_delete_conflicts_both_directions(db):
    db.put(b"k", b"base")
    t1 = db.begin()
    t2 = db.begin()
    t1.delete(b"k")
    t2.put(b"k", b"v")
    t1.commit()
    with pytest.raises(ConflictError):
        t2.commit()
    assert db.get(b"k") is None

    db.put(b"j", b"base")
    t3 = db.begin()
    t4 = db.begin()
    t3.put(b"j", b"v")
    t4.delete(b"j")
    t3.commit()
    with pytest.raises(ConflictError):
        t4.commit()
    assert db.get(b"j") == b"v"


def test_conflict_on_a_key_created_after_the_snapshot(db):
    t1 = db.begin()
    t2 = db.begin()
    t1.put(b"new", b"one")
    t2.put(b"new", b"two")
    t1.commit()
    with pytest.raises(ConflictError):
        t2.commit()


def test_disjoint_writes_both_commit(db):
    t1 = db.begin()
    t2 = db.begin()
    t1.put(b"a", b"1")
    t2.put(b"b", b"2")
    t1.commit()
    t2.commit()
    assert db.scan() == [(b"a", b"1"), (b"b", b"2")]


def test_read_only_transaction_never_conflicts(db):
    db.put(b"k", b"base")
    txn = db.begin()
    assert txn.get(b"k") == b"base"
    for i in range(5):
        db.put(b"k", f"v{i}".encode())
    txn.commit()  # must not raise
    assert db.get(b"k") == b"v4"


def test_write_skew_is_allowed(db):
    """Snapshot isolation, not serializability: this pair must both commit."""
    db.put(b"x", b"100")
    db.put(b"y", b"100")
    t1 = db.begin()
    t2 = db.begin()
    assert t1.get(b"y") == b"100"
    assert t2.get(b"x") == b"100"
    t1.put(b"x", b"0")
    t2.put(b"y", b"0")
    t1.commit()
    t2.commit()
    assert db.get(b"x") == b"0"
    assert db.get(b"y") == b"0"


def test_conflict_discards_the_whole_write_set(db):
    db.put(b"k", b"base")
    t1 = db.begin()
    t2 = db.begin()
    t2.put(b"k", b"loser")
    t2.put(b"untouched", b"loser")
    t1.put(b"k", b"winner")
    t1.commit()
    with pytest.raises(ConflictError):
        t2.commit()
    assert db.get(b"untouched") is None


def test_later_transaction_sees_the_winner(db):
    db.put(b"k", b"base")
    t1 = db.begin()
    t1.put(b"k", b"one")
    t1.commit()
    t3 = db.begin()
    assert t3.get(b"k") == b"one"
    t3.rollback()


def test_serial_transactions_do_not_conflict(db):
    for i in range(10):
        txn = db.begin()
        txn.put(b"counter", str(i).encode())
        txn.commit()
    assert db.get(b"counter") == b"9"


def test_rollback_discards_writes(db):
    db.put(b"k", b"base")
    txn = db.begin()
    txn.put(b"k", b"nope")
    txn.put(b"new", b"nope")
    txn.rollback()
    assert db.get(b"k") == b"base"
    assert db.get(b"new") is None


def test_rollback_is_idempotent(db):
    txn = db.begin()
    txn.rollback()
    txn.rollback()


def test_closed_transaction_rejects_everything(db):
    txn = db.begin()
    txn.commit()
    for call in (
        lambda: txn.get(b"k"),
        lambda: txn.put(b"k", b"v"),
        lambda: txn.delete(b"k"),
        lambda: txn.scan(),
        lambda: txn.commit(),
    ):
        with pytest.raises(TransactionClosedError):
            call()


def test_aborted_transaction_is_closed(db):
    db.put(b"k", b"base")
    t1 = db.begin()
    t2 = db.begin()
    t1.put(b"k", b"one")
    t2.put(b"k", b"two")
    t1.commit()
    with pytest.raises(ConflictError):
        t2.commit()
    with pytest.raises(TransactionClosedError):
        t2.get(b"k")
    t2.rollback()  # still a no-op


def test_rolled_back_transaction_rejects_use(db):
    txn = db.begin()
    txn.rollback()
    with pytest.raises(TransactionClosedError):
        txn.get(b"k")


# ----------------------------------------------------------------------
# transactions as context managers
# ----------------------------------------------------------------------
def test_context_manager_commits_on_clean_exit(db):
    with db.begin() as txn:
        txn.put(b"k", b"v")
    assert db.get(b"k") == b"v"


def test_context_manager_rolls_back_on_error(db):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with db.begin() as txn:
            txn.put(b"k", b"v")
            raise Boom()
    assert db.get(b"k") is None


def test_context_manager_propagates_conflict(db):
    db.put(b"k", b"base")
    loser = db.begin()
    with pytest.raises(ConflictError):
        with loser as txn:
            txn.put(b"k", b"mine")
            db.put(b"k", b"theirs")
    assert db.get(b"k") == b"theirs"


# ----------------------------------------------------------------------
# versioning
# ----------------------------------------------------------------------
def test_commit_version_counts_write_transactions(db):
    assert db.stats()["commit_version"] == 0
    db.put(b"a", b"1")
    assert db.stats()["commit_version"] == 1
    db.delete(b"missing")
    assert db.stats()["commit_version"] == 2

    txn = db.begin()
    txn.put(b"b", b"1")
    txn.put(b"c", b"1")
    txn.commit()
    assert db.stats()["commit_version"] == 3


def test_commit_version_ignores_reads_and_failures(db):
    db.put(b"k", b"base")
    baseline = db.stats()["commit_version"]

    read_only = db.begin()
    read_only.get(b"k")
    read_only.commit()
    assert db.stats()["commit_version"] == baseline

    aborted = db.begin()
    aborted.put(b"k", b"x")
    aborted.rollback()
    assert db.stats()["commit_version"] == baseline

    t1 = db.begin()
    t2 = db.begin()
    t1.put(b"k", b"one")
    t2.put(b"k", b"two")
    t1.commit()
    after_winner = db.stats()["commit_version"]
    with pytest.raises(ConflictError):
        t2.commit()
    assert db.stats()["commit_version"] == after_winner
