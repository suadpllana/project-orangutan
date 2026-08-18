"""Ranges: a conjunction of comparators over versions.

Grammar, in full::

    range      := "*" | "" | comparator ("," comparator)*
    comparator := ("==" | "!=" | ">=" | "<=" | ">" | "<") version

Whitespace around commas and operators is ignored. There is no disjunction, no
caret and no tilde: a range is always an AND of its comparators.
"""

from __future__ import annotations

from .errors import InvalidRange
from .versions import Version

# Two-character operators first: ">=" must not be read as ">" followed by "=".
_OPERATORS = (">=", "<=", "==", "!=", ">", "<")

_TESTS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


class Range:
    """An immutable conjunction of comparators. ``Range()`` accepts everything."""

    __slots__ = ("_comparators",)

    def __init__(self, comparators=()):
        cleaned = []
        for item in comparators:
            try:
                operator, version = item
            except (TypeError, ValueError):
                raise TypeError("comparator must be an (operator, Version) pair") from None
            if operator not in _TESTS:
                raise ValueError("unknown operator %r" % (operator,))
            if not isinstance(version, Version):
                raise TypeError("comparator bound must be a Version")
            cleaned.append((operator, version))
        # Canonical form: sorted and deduplicated, so equal conjunctions compare
        # equal whatever order they were written in.
        unique = sorted(set(cleaned), key=lambda pair: (pair[1]._key, pair[0]))
        object.__setattr__(self, "_comparators", tuple(unique))

    @classmethod
    def parse(cls, text):
        if not isinstance(text, str):
            raise TypeError("range must be a str, got %r" % (type(text).__name__,))
        stripped = text.strip()
        if stripped in ("", "*"):
            return cls(())
        comparators = []
        for token in stripped.split(","):
            token = token.strip()
            if not token:
                raise InvalidRange("empty comparator in %r" % (text,))
            for operator in _OPERATORS:
                if token.startswith(operator):
                    body = token[len(operator):].strip()
                    try:
                        comparators.append((operator, Version.parse(body)))
                    except (TypeError, ValueError):
                        raise InvalidRange("bad comparator %r in %r" % (token, text)) from None
                    break
            else:
                raise InvalidRange(
                    "comparator %r in %r must start with one of %s"
                    % (token, text, " ".join(_OPERATORS))
                )
        return cls(comparators)

    @property
    def comparators(self):
        return self._comparators

    def contains(self, version):
        if not isinstance(version, Version):
            raise TypeError("expected a Version, got %r" % (type(version).__name__,))
        for operator, bound in self._comparators:
            if not _TESTS[operator](version, bound):
                return False
        return True

    def is_any(self):
        return not self._comparators

    # -- immutability -------------------------------------------------
    def __setattr__(self, name, value):
        raise AttributeError("Range is immutable")

    def __delattr__(self, name):
        raise AttributeError("Range is immutable")

    def __eq__(self, other):
        if not isinstance(other, Range):
            return NotImplemented
        return self._comparators == other._comparators

    def __hash__(self):
        return hash(("pkgsolve.Range",) + self._comparators)

    def __str__(self):
        if not self._comparators:
            return "*"
        return ",".join("%s%s" % (operator, bound) for operator, bound in self._comparators)

    def __repr__(self):
        return "Range.parse(%r)" % (str(self),)


ANY = Range(())
