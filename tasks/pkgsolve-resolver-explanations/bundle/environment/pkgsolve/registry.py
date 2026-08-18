"""The registry protocol, and an in-memory implementation for tests."""

from __future__ import annotations

from .requirements import Requirement, check_package_name
from .versions import Version


class Registry:
    """Read-only view of a package universe.

    The resolver may learn about the universe *only* by calling these two
    methods. The graded suite supplies its own implementation and counts every
    call; see the specification, section 5.
    """

    def versions(self, package):
        """Every published version of ``package``, ascending. ``()`` if unknown."""
        raise NotImplementedError

    def dependencies(self, package, version):
        """The requirements of one release, in declaration order.

        Raises ``LookupError`` unless ``version`` is one that ``versions(package)``
        returned for ``package``.
        """
        raise NotImplementedError


class InMemoryRegistry(Registry):
    """A registry built from nested dicts, for tests and small manifests.

    >>> registry = InMemoryRegistry({
    ...     "app": {"1.0.0": [], "2.0.0": ["util >=1.0.0"]},
    ...     "util": {"1.0.0": [], "1.1.0": []},
    ... })
    >>> registry.versions("app")
    (Version(1, 0, 0), Version(2, 0, 0))
    """

    def __init__(self, data):
        if not isinstance(data, dict):
            raise TypeError("data must be a dict of package -> {version: [requirement]}")
        table = {}
        for package, releases in data.items():
            check_package_name(package)
            if not isinstance(releases, dict):
                raise TypeError("releases for %r must be a dict" % (package,))
            entries = {}
            for version, requirements in releases.items():
                if isinstance(version, str):
                    version = Version.parse(version)
                elif not isinstance(version, Version):
                    raise TypeError("version keys must be str or Version")
                parsed = []
                for requirement in requirements:
                    if isinstance(requirement, str):
                        requirement = Requirement.parse(requirement)
                    elif not isinstance(requirement, Requirement):
                        raise TypeError("requirements must be str or Requirement")
                    parsed.append(requirement)
                entries[version] = tuple(parsed)
            table[package] = entries
        self._table = table
        self._sorted = {name: tuple(sorted(entries)) for name, entries in table.items()}

    def versions(self, package):
        check_package_name(package)
        return self._sorted.get(package, ())

    def dependencies(self, package, version):
        check_package_name(package)
        if not isinstance(version, Version):
            raise TypeError("version must be a Version, got %r" % (type(version).__name__,))
        try:
            return self._table[package][version]
        except KeyError:
            raise LookupError("%s %s is not published" % (package, version)) from None
