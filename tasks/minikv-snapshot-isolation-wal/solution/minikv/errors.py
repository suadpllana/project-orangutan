"""Exception hierarchy for minikv.

These classes are part of the public API and are imported by callers, so their
names and inheritance relationships must not change.
"""


class MiniKVError(Exception):
    """Base class for every error raised by minikv."""


class ConflictError(MiniKVError):
    """Raised by ``Transaction.commit`` when the transaction lost a write race."""


class TransactionClosedError(MiniKVError):
    """Raised when a transaction is used after it committed, rolled back or aborted."""


class CorruptDatabaseError(MiniKVError):
    """Raised when on-disk state cannot be interpreted at all."""
