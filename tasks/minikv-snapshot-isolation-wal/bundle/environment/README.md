# minikv

A small embedded key/value store, used inside a larger product as the local
cache and offline queue for a sync agent. It is pure Python, has no
dependencies, and stores everything in one directory.

Today it works, but only just: every mutation rewrites the whole database file,
there is no way to group several changes into one atomic unit, and a process
that dies mid-write can leave the file unreadable. Two features on the roadmap —
an offline write queue and a conflict-aware sync loop — both need real
transactions.

## Layout

```
minikv/          the package
  __init__.py    public exports
  errors.py      exception hierarchy (stable, do not rename)
  store.py       MiniKV
  txn.py         Transaction (stubs)
tests/           the existing test suite
```

## Running the tests

```
python -m pytest tests -q
```

These cover what the store already does. They are the floor, not the target —
the specification you are working to is in the task instructions.
