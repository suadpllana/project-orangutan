"""The budgets from SPEC.md section 6.

These exist to rule out the O(n)-bytes-per-write shape the store starts with.
The margins are wide: the reference implementation finishes each one in well
under a fifth of its budget.
"""

import random
import time

import pytest

from minikv import MiniKV

N = 20_000
KEYS = [f"key:{i:010d}".encode() for i in range(N)]
VALUE = b"v" * 96


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    path = tmp_path_factory.mktemp("perf") / "db"
    db = MiniKV(str(path))
    started = time.monotonic()
    for key in KEYS:
        db.put(key, VALUE)
    elapsed = time.monotonic() - started
    yield db, elapsed
    db.close()


def test_bulk_put_throughput(loaded):
    _db, elapsed = loaded
    assert elapsed < 20.0, f"{N} autocommit puts took {elapsed:.1f}s (budget 20s)"


def test_random_get_throughput(loaded):
    db, _ = loaded
    rng = random.Random(1234)
    sample = [rng.choice(KEYS) for _ in range(N)]
    started = time.monotonic()
    for key in sample:
        assert db.get(key) == VALUE
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"{N} gets took {elapsed:.1f}s (budget 5s)"


def test_scan_throughput(loaded):
    db, _ = loaded
    started = time.monotonic()
    for i in range(200):
        prefix = f"key:00000{i % 2}".encode()
        assert db.scan(prefix)
    elapsed = time.monotonic() - started
    assert elapsed < 10.0, f"200 scans took {elapsed:.1f}s (budget 10s)"


def test_transaction_throughput(tmp_path):
    db = MiniKV(str(tmp_path / "db"))
    started = time.monotonic()
    for i in range(2000):
        with db.begin() as txn:
            txn.put(f"t{i:06d}".encode(), VALUE)
    elapsed = time.monotonic() - started
    db.close()
    assert elapsed < 10.0, f"2000 transactions took {elapsed:.1f}s (budget 10s)"


def test_reopen_is_not_quadratic(tmp_path):
    path = tmp_path / "db"
    db = MiniKV(str(path))
    for key in KEYS[:10_000]:
        db.put(key, VALUE)
    db.close()

    started = time.monotonic()
    db = MiniKV(str(path))
    elapsed = time.monotonic() - started
    assert db.stats()["live_keys"] == 10_000
    db.close()
    assert elapsed < 15.0, f"recovering 10k commits took {elapsed:.1f}s (budget 15s)"
