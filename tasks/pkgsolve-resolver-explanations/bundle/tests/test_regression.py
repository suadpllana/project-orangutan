"""regression -- the grader's own pristine copy of the visible suite.

Weight zero: the starting workspace passes every one of these by definition, so
scoring them would hand the untouched state free reward. Instead this category's
pass ratio MULTIPLIES the final score -- keeping what already worked earns
nothing, and breaking it costs proportionally across every other category.

Edits to `/app/public_tests/` change nothing: this copy is what runs.
"""


import pytest

from pkgsolve import (
    ANY,
    InMemoryRegistry,
    InvalidRange,
    InvalidVersion,
    PkgSolveError,
    Range,
    Registry,
    Requirement,
    Unsolvable,
    Version,
    resolve,
)


class CountingRegistry(Registry):
    """Wraps a registry and counts the calls, the way the grader does."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def versions(self, package):
        self.calls += 1
        return self.inner.versions(package)

    def dependencies(self, package, version):
        self.calls += 1
        return self.inner.dependencies(package, version)


# ----------------------------------------------------------------- Version
def test_version_parse_accepts_three_components():
    assert Version.parse("1.2.3") == Version(1, 2, 3)
    assert Version.parse("0.0.0") == Version(0, 0, 0)
    assert Version.parse("10.20.30") == Version(10, 20, 30)


def test_version_parse_rejects_junk():
    for text in ("1.2", "1.2.3.4", "01.2.3", "v1.2.3", "1.2.-3", "", "1.2.x"):
        with pytest.raises(InvalidVersion):
            Version.parse(text)
    assert issubclass(InvalidVersion, ValueError)
    assert issubclass(InvalidVersion, PkgSolveError)


def test_version_orders_component_wise_and_prints():
    assert Version(1, 0, 0) < Version(1, 0, 1) < Version(1, 1, 0) < Version(2, 0, 0)
    assert str(Version(1, 2, 3)) == "1.2.3"
    assert sorted([Version(2, 0, 0), Version(1, 9, 9)]) == [Version(1, 9, 9), Version(2, 0, 0)]


def test_version_is_immutable_and_hashable():
    version = Version(1, 2, 3)
    assert len({version, Version(1, 2, 3)}) == 1
    with pytest.raises(AttributeError):
        version.major = 9


def test_version_parse_rejects_non_str():
    with pytest.raises(TypeError):
        Version.parse(123)
    with pytest.raises(TypeError):
        Version(1, "2", 3)


# ------------------------------------------------------------------- Range
def test_range_any_forms_are_equal():
    assert Range.parse("*") == Range.parse("") == Range(()) == ANY
    assert ANY.is_any()
    assert ANY.contains(Version(0, 0, 0))


def test_range_comparators_are_conjunctive():
    window = Range.parse(">=1.2.0,<2.0.0")
    assert not window.contains(Version(1, 1, 9))
    assert window.contains(Version(1, 2, 0))
    assert window.contains(Version(1, 9, 9))
    assert not window.contains(Version(2, 0, 0))
    assert Range.parse("!=1.1.0").contains(Version(1, 1, 1))
    assert not Range.parse("!=1.1.0").contains(Version(1, 1, 0))
    assert Range.parse("==1.0.0").contains(Version(1, 0, 0))


def test_range_is_canonical_and_hashable():
    assert Range.parse(" >=1.0.0 , <2.0.0 ") == Range.parse("<2.0.0,>=1.0.0")
    assert str(Range.parse("<2.0.0,>=1.0.0")) == ">=1.0.0,<2.0.0"
    assert str(ANY) == "*"
    assert len({Range.parse(">=1.0.0"), Range.parse(">=1.0.0")}) == 1


def test_range_rejects_junk():
    for text in ("1.0.0", ">=", "~1.0.0", "^1.0.0", ">=1.0.0||<2.0.0", ">=1.0.0,"):
        with pytest.raises(InvalidRange):
            Range.parse(text)
    assert issubclass(InvalidRange, ValueError)


def test_range_contains_rejects_non_version():
    with pytest.raises(TypeError):
        ANY.contains("1.0.0")


# ------------------------------------------------------------- Requirement
def test_requirement_parse_with_and_without_a_spec():
    assert Requirement.parse("foo") == Requirement("foo", ANY)
    assert Requirement.parse("foo *") == Requirement("foo", ANY)
    assert Requirement.parse("foo >=1.0.0,<2.0.0") == Requirement(
        "foo", Range.parse(">=1.0.0,<2.0.0")
    )
    assert str(Requirement.parse("foo >=1.0.0")) == "foo >=1.0.0"


def test_requirement_rejects_bad_names_and_types():
    for name in ("Foo", "-foo", "foo-", "foo--bar", "1foo", "foo_bar", ""):
        with pytest.raises(ValueError):
            Requirement(name, ANY)
    with pytest.raises(TypeError):
        Requirement(b"foo", ANY)
    with pytest.raises(TypeError):
        Requirement("foo", ">=1.0.0")


def test_requirement_is_immutable_and_hashable():
    requirement = Requirement.parse("foo >=1.0.0")
    assert len({requirement, Requirement.parse("foo >=1.0.0")}) == 1
    with pytest.raises(AttributeError):
        requirement.package = "bar"


# ---------------------------------------------------------------- Registry
def test_registry_versions_are_sorted_and_unknown_is_empty():
    registry = InMemoryRegistry({"app": {"2.0.0": [], "1.0.0": [], "1.10.0": []}})
    assert registry.versions("app") == (
        Version(1, 0, 0),
        Version(1, 10, 0),
        Version(2, 0, 0),
    )
    assert registry.versions("nothing-here") == ()


def test_registry_returns_requirements_in_declaration_order():
    registry = InMemoryRegistry({"app": {"1.0.0": ["zed *", "abc >=1.0.0"]}})
    assert registry.dependencies("app", Version(1, 0, 0)) == (
        Requirement.parse("zed *"),
        Requirement.parse("abc >=1.0.0"),
    )


def test_registry_rejects_an_unpublished_release():
    registry = InMemoryRegistry({"app": {"1.0.0": []}})
    with pytest.raises(LookupError):
        registry.dependencies("app", Version(9, 9, 9))
    with pytest.raises(LookupError):
        registry.dependencies("ghost", Version(1, 0, 0))


# ----------------------------------------------------------------- resolve
def test_resolve_with_no_requirements_asks_nothing():
    registry = CountingRegistry(InMemoryRegistry({"app": {"1.0.0": []}}))
    assert resolve(registry, []) == {}
    assert registry.calls == 0


def test_resolve_prefers_the_newer_release():
    # Worked example 1 from the specification.
    registry = InMemoryRegistry({
        "app": {"1.0.0": [], "2.0.0": ["util >=1.0.0"]},
        "util": {"1.0.0": [], "1.1.0": []},
    })
    assert resolve(registry, [Requirement.parse("app *")]) == {
        "app": Version(2, 0, 0),
        "util": Version(1, 1, 0),
    }


def test_resolve_decides_packages_in_alphabetical_order():
    # Worked example 2: `aa` is decided before `zz`, so it takes 3.0.0 and pins
    # `zz` down. Deciding `zz` first would give a different, valid, wrong answer.
    registry = InMemoryRegistry({
        "aa": {"1.0.0": ["zz *"], "2.0.0": ["zz *"], "3.0.0": ["zz <=1.0.0"]},
        "zz": {"1.0.0": [], "2.0.0": []},
    })
    assert resolve(registry, [Requirement.parse("aa *"), Requirement.parse("zz *")]) == {
        "aa": Version(3, 0, 0),
        "zz": Version(1, 0, 0),
    }


def test_resolve_only_considers_a_package_once_something_needs_it():
    # Worked example 3: `aaa` sorts first but is not needed until `mid` is
    # decided, so `mid` goes first.
    registry = InMemoryRegistry({
        "mid": {"1.0.0": ["aaa *"]},
        "aaa": {"1.0.0": [], "2.0.0": []},
    })
    assert resolve(registry, [Requirement.parse("mid *")]) == {
        "aaa": Version(2, 0, 0),
        "mid": Version(1, 0, 0),
    }


def test_resolve_handles_a_dependency_cycle():
    registry = InMemoryRegistry({
        "left": {"1.0.0": ["right *"]},
        "right": {"1.0.0": ["left *"]},
    })
    assert resolve(registry, [Requirement.parse("left *")]) == {
        "left": Version(1, 0, 0),
        "right": Version(1, 0, 0),
    }


def test_resolve_raises_unsolvable_when_nothing_fits():
    registry = InMemoryRegistry({
        "alpha": {"1.0.0": ["shared >=2.0.0"]},
        "beta": {"1.0.0": ["shared <2.0.0"]},
        "shared": {"1.0.0": [], "2.0.0": []},
    })
    with pytest.raises(Unsolvable):
        resolve(registry, [Requirement.parse("alpha *"), Requirement.parse("beta *")])
    assert issubclass(Unsolvable, PkgSolveError)
