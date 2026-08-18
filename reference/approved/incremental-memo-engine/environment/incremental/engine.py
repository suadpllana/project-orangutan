"""Skeleton for the incremental computation engine.

Every public name required by ``SPEC.md`` is declared here.  The exception
classes are already finished -- their constructor signatures and attributes are
part of the contract.  Everything else raises ``NotImplementedError`` and is
yours to write.

You are free to add modules, helpers and internal state.  Do not change the
names, signatures or semantics that ``SPEC.md`` pins down.
"""

from __future__ import annotations

__all__ = [
    "Engine",
    "Query",
    "IncrementalError",
    "CycleError",
    "InputNotSetError",
    "QueryNotRegisteredError",
    "CacheFormatError",
]


class IncrementalError(Exception):
    """Base class for every error raised by this package."""


class CycleError(IncrementalError):
    """Raised when a query re-enters a node that is already being computed.

    ``cycle`` is a list of ``(query_name, args_tuple)`` pairs: the node that was
    re-entered first, followed by the rest of the cycle in call order, with no
    repetition of the first element at the end.
    """

    def __init__(self, cycle):
        self.cycle = list(cycle)
        rendered = " -> ".join("%s%r" % (name, tuple(args)) for name, args in self.cycle)
        super().__init__("dependency cycle: " + rendered)


class InputNotSetError(IncrementalError):
    """Raised when reading an input key that is not currently set."""

    def __init__(self, key):
        self.key = key
        super().__init__("input is not set: %r" % (key,))


class QueryNotRegisteredError(IncrementalError):
    """Raised when referring to a query name that was never registered."""

    def __init__(self, name):
        self.name = name
        super().__init__("no query registered under the name %r" % (name,))


class CacheFormatError(IncrementalError):
    """Raised by :meth:`Engine.load` when a file is not a usable cache."""


class Query:
    """Handle for a registered derived query.

    Instances are produced by :meth:`Engine.query`; user code never constructs
    them directly.  ``name`` is the registered name and ``fn`` is the undecorated
    function.
    """

    __slots__ = ("name", "fn", "_engine")

    def __init__(self, name, fn, engine):
        self.name = name
        self.fn = fn
        self._engine = engine

    def __repr__(self):
        return "<Query %s>" % (self.name,)


class Ctx:
    """The handle a query body uses to read inputs and call other queries.

    A fresh ``Ctx`` is handed to every execution of a query body; it is what
    records that execution's dependencies.
    """

    def input(self, key):
        """Read input ``key``, recording a dependency on it."""
        raise NotImplementedError

    def call(self, query, *args):
        """Evaluate another query, recording a dependency on it."""
        raise NotImplementedError


class Engine:
    """A memoizing, demand-driven incremental computation engine."""

    def __init__(self):
        raise NotImplementedError

    # -- registration --------------------------------------------------- #
    def query(self, fn=None, *, name=None):
        """Register a derived query.  Usable bare or with ``name=``."""
        raise NotImplementedError

    # -- inputs --------------------------------------------------------- #
    @property
    def revision(self):
        """The current global revision counter."""
        raise NotImplementedError

    def set_input(self, key, value):
        raise NotImplementedError

    def remove_input(self, key):
        raise NotImplementedError

    def has_input(self, key):
        raise NotImplementedError

    def get_input(self, key):
        raise NotImplementedError

    # -- evaluation ------------------------------------------------------ #
    def get(self, query, *args):
        """Bring the node up to date and return its value (or raise its error)."""
        raise NotImplementedError

    # -- introspection --------------------------------------------------- #
    def stats(self):
        """Return ``{"executions", "nodes", "revision", "inputs"}``."""
        raise NotImplementedError

    # -- durability ------------------------------------------------------ #
    def save(self, path):
        raise NotImplementedError

    def load(self, path):
        raise NotImplementedError
