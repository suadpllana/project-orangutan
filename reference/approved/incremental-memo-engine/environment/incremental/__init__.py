"""incremental -- a demand-driven incremental computation engine.

Only the names re-exported here are part of the public API that the grader
uses.  You may reorganise the internals of this package however you like, as
long as ``from incremental import Engine, CycleError, ...`` keeps working.
"""

from .engine import (
    CacheFormatError,
    CycleError,
    Engine,
    IncrementalError,
    InputNotSetError,
    Query,
    QueryNotRegisteredError,
)

__all__ = [
    "Engine",
    "Query",
    "IncrementalError",
    "CycleError",
    "InputNotSetError",
    "QueryNotRegisteredError",
    "CacheFormatError",
]
