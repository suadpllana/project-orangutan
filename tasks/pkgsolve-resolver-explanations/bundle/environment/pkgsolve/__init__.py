"""pkgsolve - version resolution for the build farm.

The public surface is fixed: the graded suite imports every name below straight
from ``pkgsolve``.
"""

from __future__ import annotations

from .errors import InvalidRange, InvalidVersion, PkgSolveError, Unsolvable
from .ranges import ANY, Range
from .registry import InMemoryRegistry, Registry
from .requirements import DependencyFact, Requirement, RootRequirement
from .solver import resolve
from .versions import Version

__all__ = [
    "ANY",
    "DependencyFact",
    "InMemoryRegistry",
    "InvalidRange",
    "InvalidVersion",
    "PkgSolveError",
    "Range",
    "Registry",
    "Requirement",
    "RootRequirement",
    "Unsolvable",
    "Version",
    "resolve",
]

__version__ = "1.0.0"
