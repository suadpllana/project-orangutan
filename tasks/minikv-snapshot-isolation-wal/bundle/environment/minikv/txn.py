"""Transaction objects.

Nothing here is implemented yet.  ``SPEC.md`` describes the semantics the
finished implementation has to provide.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


class Transaction:
    """A snapshot-isolated view of a :class:`~minikv.store.MiniKV`."""

    def __init__(self, store: "object") -> None:  # pragma: no cover - stub
        raise NotImplementedError("transactions are not implemented yet")

    def get(self, key: bytes) -> Optional[bytes]:
        raise NotImplementedError

    def put(self, key: bytes, value: bytes) -> None:
        raise NotImplementedError

    def delete(self, key: bytes) -> bool:
        raise NotImplementedError

    def scan(self, prefix: bytes = b"") -> List[Tuple[bytes, bytes]]:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError
