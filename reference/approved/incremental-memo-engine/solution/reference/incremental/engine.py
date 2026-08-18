"""A demand-driven incremental computation engine (reference implementation).

The engine implements the classic "red/green" verification algorithm:

* a global ``revision`` counter is bumped every time an input actually changes;
* every memoized node records ``changed_at`` (the revision at which its own
  value last changed) and ``verified_at`` (the revision at which it was last
  confirmed to be up to date);
* a node is re-executed only when one of its recorded dependencies, brought up
  to date first, reports ``changed_at > node.verified_at``;
* after a re-execution whose outcome compares equal to the previous outcome,
  ``changed_at`` is *not* advanced -- this is "early cutoff", and it is what
  stops a change from rippling through the whole graph.
"""

from __future__ import annotations

import os
import pickle
import sys
import tempfile

__all__ = [
    "Engine",
    "Query",
    "IncrementalError",
    "CycleError",
    "InputNotSetError",
    "QueryNotRegisteredError",
    "CacheFormatError",
]

CACHE_FORMAT = "incremental-cache-v1"

# A dependency chain of 20k user frames needs a lot of Python frames: one
# ``_ensure`` + one ``_execute`` + the user function + one ``Ctx.call`` per
# level.  CPython does not consume C stack for Python-to-Python calls, so a
# generous limit is safe; it is restored as soon as the top-level call returns.
_DEEP_RECURSION_LIMIT = 600_000


class IncrementalError(Exception):
    """Base class for every error raised by this package."""


class CycleError(IncrementalError):
    """Raised when a query re-enters a node that is already being computed."""

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
    """Handle for a registered derived query.  Created by ``Engine.query``."""

    __slots__ = ("name", "fn", "_engine")

    def __init__(self, name, fn, engine):
        self.name = name
        self.fn = fn
        self._engine = engine

    def __repr__(self):
        return "<Query %s>" % (self.name,)


class _Node:
    __slots__ = ("value", "error", "deps", "changed_at", "verified_at")

    def __init__(self, value, error, deps, changed_at, verified_at):
        self.value = value
        self.error = error
        self.deps = deps
        self.changed_at = changed_at
        self.verified_at = verified_at


class Ctx:
    """The handle a query body uses to read inputs and call other queries."""

    __slots__ = ("_engine", "_deps", "_seen")

    def __init__(self, engine):
        self._engine = engine
        self._deps = []
        self._seen = set()

    def _record(self, dep):
        if dep not in self._seen:
            self._seen.add(dep)
            self._deps.append(dep)

    def input(self, key):
        self._record(("i", key))
        engine = self._engine
        try:
            return engine._inputs[key]
        except KeyError:
            raise InputNotSetError(key) from None

    def call(self, query, *args):
        engine = self._engine
        key = engine._key(query, args)
        self._record(key)
        node = engine._ensure(key)
        if node.error is not None:
            raise node.error
        return node.value


class Engine:
    """A memoizing, demand-driven incremental computation engine."""

    def __init__(self):
        self._revision = 0
        self._inputs = {}
        self._input_changed = {}  # key -> revision (tombstones are kept)
        self._nodes = {}
        self._queries = {}
        self._stack = []
        self._stack_set = set()
        self._executions = 0

    # ------------------------------------------------------------------ #
    # registration
    # ------------------------------------------------------------------ #
    def query(self, fn=None, *, name=None):
        """Register a derived query.  Usable bare or with ``name=``."""

        def register(func):
            if not callable(func):
                raise TypeError("query target must be callable")
            qname = name if name is not None else getattr(func, "__name__", None)
            if not isinstance(qname, str) or not qname:
                raise TypeError("query name must be a non-empty string")
            if qname in self._queries:
                raise ValueError("a query named %r is already registered" % (qname,))
            handle = Query(qname, func, self)
            self._queries[qname] = handle
            return handle

        if fn is None:
            return register
        return register(fn)

    def _key(self, query, args):
        if isinstance(query, Query):
            if query._engine is not self:
                raise ValueError("query %r belongs to a different Engine" % (query.name,))
            qname = query.name
        elif isinstance(query, str):
            qname = query
        else:
            raise TypeError("expected a Query or a query name, got %r" % (type(query).__name__,))
        if qname not in self._queries:
            raise QueryNotRegisteredError(qname)
        args = tuple(args)
        try:
            hash(args)
        except TypeError:
            raise TypeError("query arguments must be hashable") from None
        return ("q", qname, args)

    # ------------------------------------------------------------------ #
    # inputs
    # ------------------------------------------------------------------ #
    @property
    def revision(self):
        return self._revision

    def _reject_reentrant(self, what):
        if self._stack:
            raise RuntimeError("%s must not be called while a query is executing" % (what,))

    def set_input(self, key, value):
        self._reject_reentrant("Engine.set_input()")
        if not isinstance(key, str):
            raise TypeError("input keys must be strings")
        if key in self._inputs:
            try:
                unchanged = bool(self._inputs[key] == value)
            except Exception:
                unchanged = False
            if unchanged:
                return
        self._revision += 1
        self._inputs[key] = value
        self._input_changed[key] = self._revision

    def remove_input(self, key):
        self._reject_reentrant("Engine.remove_input()")
        if not isinstance(key, str):
            raise TypeError("input keys must be strings")
        if key not in self._inputs:
            return False
        del self._inputs[key]
        self._revision += 1
        self._input_changed[key] = self._revision
        return True

    def has_input(self, key):
        return key in self._inputs

    def get_input(self, key):
        try:
            return self._inputs[key]
        except KeyError:
            raise InputNotSetError(key) from None

    # ------------------------------------------------------------------ #
    # evaluation
    # ------------------------------------------------------------------ #
    def get(self, query, *args):
        self._reject_reentrant("Engine.get()")
        key = self._key(query, args)
        previous_limit = sys.getrecursionlimit()
        if previous_limit < _DEEP_RECURSION_LIMIT:
            sys.setrecursionlimit(_DEEP_RECURSION_LIMIT)
        try:
            node = self._ensure(key)
        finally:
            if previous_limit < _DEEP_RECURSION_LIMIT:
                try:
                    sys.setrecursionlimit(previous_limit)
                except RecursionError:  # pragma: no cover - defensive
                    pass
        if node.error is not None:
            raise node.error
        return node.value

    def _ensure(self, key):
        if key in self._stack_set:
            index = self._stack.index(key)
            raise CycleError([(k[1], k[2]) for k in self._stack[index:]])

        node = self._nodes.get(key)
        revision = self._revision
        if node is not None:
            if node.verified_at == revision:
                return node
            stale = False
            verified_at = node.verified_at
            for dep in node.deps:
                if dep[0] == "i":
                    dep_changed = self._input_changed.get(dep[1], 0)
                else:
                    dep_changed = self._ensure(dep).changed_at
                if dep_changed > verified_at:
                    stale = True
                    break
            if not stale:
                node.verified_at = revision
                return node
        return self._execute(key, node)

    def _execute(self, key, previous):
        ctx = Ctx(self)
        self._stack.append(key)
        self._stack_set.add(key)
        try:
            fn = self._queries[key[1]].fn
            self._executions += 1
            try:
                value = fn(ctx, *key[2])
                error = None
            except CycleError:
                raise
            except Exception as exc:  # memoized like any other outcome
                value = None
                error = exc
        finally:
            self._stack.pop()
            self._stack_set.discard(key)

        revision = self._revision
        if previous is not None and _outcome_equal(previous, value, error):
            changed_at = previous.changed_at
        else:
            changed_at = revision
        node = _Node(value, error, tuple(ctx._deps), changed_at, revision)
        self._nodes[key] = node
        return node

    # ------------------------------------------------------------------ #
    # introspection
    # ------------------------------------------------------------------ #
    def stats(self):
        return {
            "executions": self._executions,
            "nodes": len(self._nodes),
            "revision": self._revision,
            "inputs": len(self._inputs),
        }

    # ------------------------------------------------------------------ #
    # durability
    # ------------------------------------------------------------------ #
    def save(self, path):
        self._reject_reentrant("Engine.save()")
        state = {
            "format": CACHE_FORMAT,
            "revision": self._revision,
            "inputs": self._inputs,
            "input_changed": self._input_changed,
            "nodes": [
                (key, node.value, node.error, node.deps, node.changed_at, node.verified_at)
                for key, node in self._nodes.items()
            ],
        }
        path = os.fspath(path)
        directory = os.path.dirname(os.path.abspath(path))
        handle, tmp = tempfile.mkstemp(dir=directory, prefix=".incremental-", suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as stream:
                pickle.dump(state, stream, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load(self, path):
        self._reject_reentrant("Engine.load()")
        try:
            with open(os.fspath(path), "rb") as stream:
                state = pickle.load(stream)
        except (OSError, IncrementalError):
            raise
        except Exception as exc:
            raise CacheFormatError("could not read cache file: %s" % (exc,)) from exc

        if not isinstance(state, dict) or state.get("format") != CACHE_FORMAT:
            raise CacheFormatError("not an incremental cache file")
        try:
            revision = int(state["revision"])
            inputs = dict(state["inputs"])
            input_changed = dict(state["input_changed"])
            raw_nodes = list(state["nodes"])
            nodes = {}
            for key, value, error, deps, changed_at, verified_at in raw_nodes:
                nodes[tuple(key)] = _Node(value, error, tuple(deps), int(changed_at), int(verified_at))
        except Exception as exc:
            raise CacheFormatError("malformed incremental cache: %s" % (exc,)) from exc

        # Drop nodes whose query is unknown to this engine, then keep dropping
        # until nothing references a node that is gone.
        keep = {key for key in nodes if key[1] in self._queries}
        while True:
            doomed = set()
            for key in keep:
                for dep in nodes[key].deps:
                    if dep[0] == "q" and dep not in keep:
                        doomed.add(key)
                        break
            if not doomed:
                break
            keep -= doomed

        self._revision = revision
        self._inputs = inputs
        self._input_changed = input_changed
        self._nodes = {key: nodes[key] for key in keep}
        self._executions = 0


def _outcome_equal(previous, value, error):
    if (previous.error is None) != (error is None):
        return False
    if error is not None:
        if type(previous.error) is not type(error):
            return False
        try:
            return bool(previous.error.args == error.args)
        except Exception:
            return False
    try:
        return bool(previous.value == value)
    except Exception:
        return False
