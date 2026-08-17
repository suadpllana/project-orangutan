"""One store object, several threads."""

import threading

from minikv import ConflictError, MiniKV

THREADS = 8
PER_THREAD = 400


def test_concurrent_autocommit_writes_are_all_durable(tmp_path):
    path = tmp_path / "db"
    errors = []

    def worker(worker_id, db):
        try:
            for i in range(PER_THREAD):
                db.put(f"t{worker_id}:k{i:04d}".encode(), f"{worker_id}-{i}".encode())
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    with MiniKV(str(path)) as db:
        threads = [
            threading.Thread(target=worker, args=(w, db)) for w in range(THREADS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert not errors, f"worker raised: {errors[0]!r}"
        assert db.stats()["live_keys"] == THREADS * PER_THREAD
        assert db.stats()["commit_version"] == THREADS * PER_THREAD

    with MiniKV(str(path)) as db:
        recovered = dict(db.scan())
        assert len(recovered) == THREADS * PER_THREAD
        for worker_id in range(THREADS):
            for i in range(PER_THREAD):
                key = f"t{worker_id}:k{i:04d}".encode()
                assert recovered[key] == f"{worker_id}-{i}".encode()


def test_concurrent_transactions_do_not_corrupt_the_store(tmp_path):
    path = tmp_path / "db"
    committed = []
    errors = []
    lock = threading.Lock()

    def worker(worker_id, db):
        try:
            for i in range(100):
                txn = db.begin()
                key = f"t{worker_id}:k{i:03d}".encode()
                txn.put(key, b"v")
                try:
                    txn.commit()
                except ConflictError:
                    continue
                with lock:
                    committed.append(key)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    with MiniKV(str(path)) as db:
        threads = [
            threading.Thread(target=worker, args=(w, db)) for w in range(THREADS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert not errors, f"worker raised: {errors[0]!r}"

    # Keys are disjoint per worker, so nothing should have conflicted at all.
    assert len(committed) == THREADS * 100
    with MiniKV(str(path)) as db:
        assert set(dict(db.scan())) == set(committed)


def test_reads_during_concurrent_writes_stay_consistent(tmp_path):
    path = tmp_path / "db"
    stop = threading.Event()
    errors = []

    with MiniKV(str(path)) as db:
        for i in range(200):
            db.put(f"k{i:03d}".encode(), b"initial")

        def reader():
            try:
                while not stop.is_set():
                    txn = db.begin()
                    seen = dict(txn.scan(b"k"))
                    txn.rollback()
                    assert len(seen) == 200, f"snapshot had {len(seen)} keys"
            except Exception as exc:
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(3)]
        for thread in readers:
            thread.start()
        for round_id in range(20):
            for i in range(200):
                db.put(f"k{i:03d}".encode(), f"round{round_id}".encode())
        stop.set()
        for thread in readers:
            thread.join(timeout=60)

    assert not errors, f"reader raised: {errors[0]!r}"
