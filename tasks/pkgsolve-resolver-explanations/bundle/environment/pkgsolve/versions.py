"""Versions: exactly three non-negative integers, ordered component-wise."""

from __future__ import annotations

import re

from .errors import InvalidVersion

_VERSION_RE = re.compile(r"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class Version:
    """An immutable ``major.minor.patch`` release."""

    __slots__ = ("major", "minor", "patch")

    def __init__(self, major, minor, patch):
        for name, value in (("major", major), ("minor", minor), ("patch", patch)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("%s must be an int, got %r" % (name, type(value).__name__))
            if value < 0:
                raise ValueError("%s must not be negative, got %d" % (name, value))
        object.__setattr__(self, "major", major)
        object.__setattr__(self, "minor", minor)
        object.__setattr__(self, "patch", patch)

    @classmethod
    def parse(cls, text):
        if not isinstance(text, str):
            raise TypeError("version must be a str, got %r" % (type(text).__name__,))
        match = _VERSION_RE.match(text)
        if match is None:
            raise InvalidVersion("not a version: %r" % (text,))
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    # -- immutability -------------------------------------------------
    def __setattr__(self, name, value):
        raise AttributeError("Version is immutable")

    def __delattr__(self, name):
        raise AttributeError("Version is immutable")

    # -- ordering -----------------------------------------------------
    @property
    def _key(self):
        return (self.major, self.minor, self.patch)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key == other._key

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key < other._key

    def __le__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key <= other._key

    def __gt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key > other._key

    def __ge__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key >= other._key

    def __hash__(self):
        return hash(("pkgsolve.Version",) + self._key)

    def __str__(self):
        return "%d.%d.%d" % self._key

    def __repr__(self):
        return "Version(%d, %d, %d)" % self._key
