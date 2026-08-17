"""Child process used by the durability tests.

Each scenario does some work and then SIGKILLs itself.  Nothing is ever closed
cleanly, so whatever the parent can read afterwards is exactly what the
implementation made durable.
"""

import os
import random
import signal
import sys
import threading

from minikv import MiniKV


def _die():
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)
    os._exit(97)  # unreachable on a healthy platform


def commit_then_kill(path):
    db = MiniKV(path)
    for i in range(5):
        db.put(f"k{i}".encode(), f"v{i}".encode())
    _die()


def txn_commit_then_kill(path):
    db = MiniKV(path)
    txn = db.begin()
    txn.put(b"a", b"1")
    txn.put(b"b", b"2")
    txn.put(b"c", b"3")
    txn.commit()
    _die()


def txn_open_then_kill(path):
    db = MiniKV(path)
    db.put(b"committed", b"yes")
    txn = db.begin()
    txn.put(b"ghost1", b"x")
    txn.put(b"ghost2", b"y")
    _die()


def rollback_then_kill(path):
    db = MiniKV(path)
    db.put(b"keep", b"1")
    txn = db.begin()
    txn.put(b"drop", b"1")
    txn.rollback()
    db.put(b"keep2", b"2")
    _die()


def delete_then_kill(path):
    db = MiniKV(path)
    db.put(b"a", b"1")
    db.put(b"b", b"2")
    db.delete(b"a")
    _die()


def checkpoint_then_kill(path):
    db = MiniKV(path)
    for i in range(100):
        db.put(f"k{i:04d}".encode(), f"v{i}".encode())
    db.checkpoint()
    for i in range(100, 110):
        db.put(f"k{i:04d}".encode(), f"v{i}".encode())
    _die()


def checkpoint_race(path):
    """Kill the process at an arbitrary moment while checkpoints are running.

    Whenever the axe falls, every committed key must still be there.
    """
    db = MiniKV(path)
    for i in range(2000):
        db.put(f"k{i:04d}".encode(), f"v{i}".encode())

    delay = random.uniform(0.001, 0.05)
    threading.Timer(delay, _die).start()
    while True:
        db.checkpoint()


SCENARIOS = {
    "commit_then_kill": commit_then_kill,
    "txn_commit_then_kill": txn_commit_then_kill,
    "txn_open_then_kill": txn_open_then_kill,
    "rollback_then_kill": rollback_then_kill,
    "delete_then_kill": delete_then_kill,
    "checkpoint_then_kill": checkpoint_then_kill,
    "checkpoint_race": checkpoint_race,
}


if __name__ == "__main__":
    SCENARIOS[sys.argv[1]](sys.argv[2])
    _die()
