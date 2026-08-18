"""The pkgsolve exception hierarchy.

Stable public API: the names and the inheritance are part of the contract and
callers catch them. Do not rename or re-parent anything here.
"""

from __future__ import annotations


class PkgSolveError(Exception):
    """Base class for every error pkgsolve raises on purpose."""


class InvalidVersion(PkgSolveError, ValueError):
    """A version string that is not three dot-separated decimal components."""


class InvalidRange(PkgSolveError, ValueError):
    """A range string the comparator grammar does not accept."""


class Unsolvable(PkgSolveError):
    """No assignment of versions satisfies the requirements.

    ``causes`` is a frozenset of facts that together prove it: see the
    specification, section 4. An empty set is not a proof of anything, and the
    resolver in this package does not yet produce a real one.
    """

    def __init__(self, causes=()):
        self.causes = frozenset(causes)
        super().__init__(
            "no solution (%d cited cause%s)"
            % (len(self.causes), "" if len(self.causes) == 1 else "s")
        )
