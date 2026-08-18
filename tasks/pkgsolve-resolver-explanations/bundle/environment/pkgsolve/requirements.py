"""Requirements, and the two kinds of fact an ``Unsolvable`` cites."""

from __future__ import annotations

import re

from .ranges import Range
from .versions import Version

_NAME_RE = re.compile(r"\A[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")


def check_package_name(name):
    """Return ``name`` if it is a legal package name, else raise."""
    if not isinstance(name, str):
        raise TypeError("package name must be a str, got %r" % (type(name).__name__,))
    if _NAME_RE.match(name) is None:
        raise ValueError("not a legal package name: %r" % (name,))
    return name


class Requirement:
    """``package`` constrained to ``range``."""

    __slots__ = ("package", "range")

    def __init__(self, package, range):  # noqa: A002 - `range` is the field name
        check_package_name(package)
        if not isinstance(range, Range):
            raise TypeError("range must be a Range, got %r" % (type(range).__name__,))
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "range", range)

    @classmethod
    def parse(cls, text):
        """``"foo >=1.0.0,<2.0.0"``; a bare name means every version."""
        if not isinstance(text, str):
            raise TypeError("requirement must be a str, got %r" % (type(text).__name__,))
        parts = text.strip().split(None, 1)
        if not parts:
            raise ValueError("empty requirement")
        name = parts[0]
        spec = parts[1] if len(parts) > 1 else "*"
        return cls(name, Range.parse(spec))

    def __setattr__(self, name, value):
        raise AttributeError("Requirement is immutable")

    def __delattr__(self, name):
        raise AttributeError("Requirement is immutable")

    def __eq__(self, other):
        if not isinstance(other, Requirement):
            return NotImplemented
        return self.package == other.package and self.range == other.range

    def __hash__(self):
        return hash(("pkgsolve.Requirement", self.package, self.range))

    def __str__(self):
        return "%s %s" % (self.package, self.range)

    def __repr__(self):
        return "Requirement.parse(%r)" % (str(self),)


class RootRequirement:
    """Fact: "the caller asked for this requirement"."""

    __slots__ = ("requirement",)

    def __init__(self, requirement):
        if not isinstance(requirement, Requirement):
            raise TypeError("requirement must be a Requirement")
        object.__setattr__(self, "requirement", requirement)

    def __setattr__(self, name, value):
        raise AttributeError("RootRequirement is immutable")

    def __eq__(self, other):
        if not isinstance(other, RootRequirement):
            return NotImplemented
        return self.requirement == other.requirement

    def __hash__(self):
        return hash(("pkgsolve.RootRequirement", self.requirement))

    def __str__(self):
        return "the manifest requires %s" % (self.requirement,)

    __repr__ = __str__


class DependencyFact:
    """Fact: "every version of ``package`` inside ``versions`` requires ``requirement``"."""

    __slots__ = ("package", "versions", "requirement")

    def __init__(self, package, versions, requirement):
        check_package_name(package)
        if not isinstance(versions, Range):
            raise TypeError("versions must be a Range, got %r" % (type(versions).__name__,))
        if not isinstance(requirement, Requirement):
            raise TypeError("requirement must be a Requirement")
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "versions", versions)
        object.__setattr__(self, "requirement", requirement)

    def __setattr__(self, name, value):
        raise AttributeError("DependencyFact is immutable")

    def __eq__(self, other):
        if not isinstance(other, DependencyFact):
            return NotImplemented
        return (
            self.package == other.package
            and self.versions == other.versions
            and self.requirement == other.requirement
        )

    def __hash__(self):
        return hash(
            ("pkgsolve.DependencyFact", self.package, self.versions, self.requirement)
        )

    def __str__(self):
        return "every %s %s requires %s" % (self.package, self.versions, self.requirement)

    __repr__ = __str__
