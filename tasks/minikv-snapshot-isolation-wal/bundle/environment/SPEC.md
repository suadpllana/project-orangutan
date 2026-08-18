# minikv v1.0 specification

This section is the contract. It is normative: the grader tests these statements
and nothing else. Where it says MUST, a test asserts it.

Everything is scoped to a single **database directory** — the `path` argument of
`MiniKV(path)`. The directory is created if it does not exist.

## 1. Types and validation

* Keys and values are `bytes`. Anything else (including `str`, `bytearray`,
  `memoryview`, `None`) MUST raise `TypeError`.
* An empty key MUST raise `ValueError`. Empty **values** are legal.
* Keys longer than 4096 bytes and values longer than 1048576 bytes MUST raise
  `ValueError`.
* `scan(prefix)` takes `bytes`; a non-`bytes` prefix MUST raise `TypeError`.
  The default prefix is `b""`, which matches every key.
* Validation MUST happen before any state changes: a rejected call leaves the
  database and the transaction exactly as they were.

## 2. Autocommit API — `MiniKV`

```python
db = MiniKV(path)                      # open or create; recover from disk
db.get(key)          -> bytes | None
db.put(key, value)   -> None
db.delete(key)       -> bool           # True if the key existed
db.scan(prefix=b"")  -> list[tuple[bytes, bytes]]
db.begin()           -> Transaction
db.checkpoint()      -> None
db.stats()           -> dict
db.close()           -> None
```

* `scan` returns `(key, value)` pairs whose key starts with `prefix`, sorted
  ascending by key (plain `bytes` ordering). Deleted keys MUST NOT appear.
* `put` and `delete` are **autocommit**: each one behaves exactly like a
  transaction that touches that single key and commits immediately. They never
  raise `ConflictError`.
* `MiniKV` supports the context-manager protocol; `__exit__` closes the store.
* After `close()`, every method except `close()` MUST raise `ValueError`.
  `close()` is idempotent.

### `stats()`

Returns a `dict` that MUST contain at least these keys:

| key                | type  | meaning                                            |
| ------------------ | ----- | -------------------------------------------------- |
| `commit_version`   | `int` | monotonically increasing count of commits applied  |
| `live_keys`        | `int` | number of keys currently visible                   |
| `wal_bytes`        | `int` | current size of `wal.log` in bytes                 |
| `total_bytes`      | `int` | total size of every file in the database directory |

`commit_version` MUST start at 0 for a fresh database, MUST increase by exactly
1 for each committed write transaction (including each autocommit `put`/
`delete`, whether or not the delete found a key), MUST NOT change for a
read-only transaction, a rolled-back transaction, a failed commit, or a
`checkpoint()`, and MUST survive reopening the database.

## 3. Transactions — `MiniKV.begin()`

```python
txn = db.begin()
txn.get(key)          -> bytes | None
txn.put(key, value)   -> None
txn.delete(key)       -> bool
txn.scan(prefix=b"")  -> list[tuple[bytes, bytes]]
txn.commit()          -> None
txn.rollback()        -> None
```

### 3.1 Snapshot isolation

* `begin()` takes a **snapshot** of the committed state at that instant.
* Every read in the transaction MUST observe that snapshot, **plus** the
  transaction's own uncommitted writes (read-your-own-writes), and MUST NOT
  observe any write committed by anyone else after `begin()` — no matter how
  many other transactions commit in between. This applies to `scan` too: a key
  created after the snapshot MUST NOT appear (no phantoms).
* `txn.delete(key)` returns whether the key was visible *to the transaction* at
  that moment.
* Opening a transaction MUST NOT block autocommit writes or other transactions.
  A test performs `t = db.begin()`, then `db.put(...)`, then reads through `t`,
  all from a single thread; an implementation that holds a lock across the
  transaction's lifetime will deadlock.

### 3.2 Commit, conflicts and abort

* `commit()` applies every write atomically: after it returns, either all of the
  transaction's writes are visible or, if it raised, none are.
* **First-committer-wins.** `commit()` MUST raise `ConflictError` if any key the
  transaction *wrote* was written (by an autocommit call or by another
  transaction that committed) after this transaction's snapshot was taken.
  Deletes count as writes on both sides.
* Conflicts are detected on the **write set only**. A transaction that merely
  *read* a key someone else changed MUST still commit. Write skew is therefore
  allowed and MUST NOT be rejected: this is snapshot isolation, not
  serializability, and a test asserts the permissive behaviour.
* A read-only transaction MUST always commit successfully.
* `ConflictError` **aborts** the transaction: its writes are discarded and the
  object is closed.
* `rollback()` discards the writes. It is idempotent and is a no-op on an
  already-closed transaction.
* Using a closed transaction — `get`, `put`, `delete`, `scan` or `commit` after
  `commit`/`rollback`/abort — MUST raise `TransactionClosedError`.
* `Transaction` is a context manager: `__enter__` returns the transaction,
  `__exit__` commits on a clean exit and rolls back if the body raised. A
  `ConflictError` raised by that implicit commit MUST propagate to the caller.

## 4. Durability

The reference workload is *process* failure: `SIGKILL`, no machine crash. Data
that reached the operating system counts as durable.

* When `put`, `delete` or `commit()` returns, the change MUST already be on its
  way to the OS — if the process is `SIGKILL`ed on the very next instruction,
  reopening the directory MUST show the change.
* Writes of a transaction that never committed MUST NOT be visible after a
  crash.
* The write-ahead log MUST be a single file named `wal.log` inside the database
  directory, and it MUST be the mechanism by which committed data reaches disk.
  Its internal format is up to you.
* Recovery MUST tolerate a damaged log tail. If `wal.log` is truncated at an
  arbitrary byte offset, or any single byte in it is corrupted, then reopening
  the database MUST NOT raise, and the resulting state MUST be a **prefix** of
  the commit history: there is some `j` such that every commit up to `j` is
  fully applied and no commit after `j` is applied even partially. A record
  whose bytes do not verify MUST be treated as the end of the log, together with
  everything that follows it.
* Recovery therefore requires each log record to carry enough redundancy — a
  length and a checksum — to detect a partial or damaged record.
* A store reopened on a damaged log MUST remain writable, and the new writes
  MUST survive another reopen.

## 5. Checkpointing

* `db.checkpoint()` folds the log into a compact on-disk representation.
* After `checkpoint()` returns, `wal.log` MUST still exist and MUST be at most
  **4096 bytes**.
* After `checkpoint()`, the total size of the database directory MUST be at most
  `4 * L + 65536` bytes, where `L` is the sum of `len(key) + len(value)` over
  the live keys. In other words the checkpoint has to actually drop superseded
  versions and deleted keys, not just copy the log.
* A checkpoint MUST be crash-safe: a `SIGKILL` at any point during or right
  after `checkpoint()` MUST leave a reopenable database whose contents are the
  full committed history — data that was already committed cannot be lost by
  checkpointing.
* Checkpointing MUST NOT change what any *open* transaction sees.
* `checkpoint()` on an empty database is legal and cheap.

## 6. Performance

Measured on the grading machine (1 CPU core, no GPU, ordinary disk), with
16-byte keys and 96-byte values:

| workload                                                        | budget |
| --------------------------------------------------------------- | ------ |
| 20 000 sequential autocommit `put`s                             | 20 s   |
| 20 000 random `get`s over those keys, **after a `checkpoint()`** | 5 s    |
| 50 `scan(prefix)` calls **through a transaction whose snapshot is already stale**, over 20 000 keys | 10 s |
| 2 000 single-write transactions                                 | 10 s   |
| reopening a 10 000-commit log                                   | 15 s   |

Reads must stay fast on both paths: after the log has been folded into a
checkpoint, and when they are resolved against an older snapshot rather than the
current state. Neither may degrade into a per-key search.

The starting implementation is roughly O(n) bytes written per `put` and misses
the first budget by more than an order of magnitude. An append-only log makes it
comfortable.

## 7. Threads

* A single `MiniKV` object MUST be safe to use from multiple threads: 8 threads
  doing autocommit `put`s to disjoint keys MUST not lose, duplicate or corrupt
  any write, and the store MUST be reopenable afterwards.
* The same holds for transactions: threads that each open their own
  `Transaction` and write disjoint keys MUST all commit, without spurious
  `ConflictError`s and without corrupting the store.
* A transaction opened in one thread MUST keep seeing a consistent snapshot
  while other threads commit: a `scan` through it returns the same key set
  however many writes land in between.
* Two threads MAY share a single `Transaction` object, but nothing tests that.
* Multi-**process** access to one directory is out of scope; no test opens the
  same directory from two live processes at once.

## 8. Implementation constraints

* Python 3.11 standard library only. No third-party packages, no network — the
  sandbox has neither.
* **Every file you add or change must live inside `/app/minikv/`.** Grading
  copies `minikv/**/*.py` into a clean tree and imports it from there; anything
  you leave outside that directory (including `conftest.py`,
  `sitecustomize.py`, `pytest.ini`, or edits to `public_tests/test_basic.py`)
  is discarded before the graded tests run.
* The store must not read the environment, the process tree, the call stack, or
  test-runner state to decide how to behave. The grader scans for this and
  scores zero if it finds it.
* `data.json` is not part of the contract. You may keep it, replace it, or
  delete it — only `wal.log` is a required filename. A database directory
  written by the *old* implementation does not need to be readable by the new
  one; every test starts from an empty directory.
