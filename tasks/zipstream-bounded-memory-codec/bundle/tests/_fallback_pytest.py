#!/usr/bin/env python3
"""Run the visible suite when pytest is not available.

The regression category's pass ratio multiplies the whole score, so "pytest did
not run" must not be indistinguishable from "the submission broke every visible
test". This is the fallback: it stands in for the two pytest features the
visible suite actually uses -- `pytest.raises` and `pytest.mark.parametrize` --
collects the `test_*` functions from the grader's own pristine copy of the
suite, runs them, and reports how many passed.

    python3 _fallback_pytest.py <suite.py> <impl_root>

It prints one machine-readable line:

    RESULT {"total": 23, "broken": []}
"""

import importlib.util
import json
import sys
import traceback
import types


class _Raises(object):
    """`with pytest.raises(SomeError):` -- and nothing more than that."""

    def __init__(self, expected):
        self.expected = expected
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        if kind is None:
            raise AssertionError("DID NOT RAISE %r" % (self.expected,))
        if not issubclass(kind, self.expected):
            return False
        self.value = value
        return True


def _parametrize(argnames, argvalues, **_ignored):
    names = [name.strip() for name in argnames.split(",")] \
        if isinstance(argnames, str) else list(argnames)

    def decorate(function):
        cases = list(getattr(function, "_parametrized", []))
        expanded = []
        for value in argvalues:
            row = tuple(value) if len(names) > 1 else (value,)
            expanded.append(dict(zip(names, row)))
        if cases:
            merged = []
            for existing in cases:
                for extra in expanded:
                    combined = dict(existing)
                    combined.update(extra)
                    merged.append(combined)
            expanded = merged
        function._parametrized = expanded
        return function

    return decorate


class _Mark(object):
    """`pytest.mark.<anything>`; only `parametrize` does anything."""

    parametrize = staticmethod(_parametrize)

    def __getattr__(self, _name):
        def decorate(*_args, **_kwargs):
            def identity(function):
                return function
            return identity
        return decorate


def _install_stub():
    stub = types.ModuleType("pytest")
    stub.raises = _Raises
    stub.mark = _Mark()
    stub.fail = lambda message="": (_ for _ in ()).throw(AssertionError(message))
    stub.skip = lambda message="": (_ for _ in ()).throw(AssertionError(
        "skip is not supported by the fallback runner: %s" % (message,)))
    sys.modules["pytest"] = stub
    return stub


def main(argv):
    suite_path, impl_root = argv[1], argv[2]
    sys.path.insert(0, impl_root)
    _install_stub()

    spec = importlib.util.spec_from_file_location("visible_suite", suite_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    total = 0
    broken = []
    for name in sorted(name for name in dir(module) if name.startswith("test_")):
        function = getattr(module, name)
        if not callable(function):
            continue
        cases = getattr(function, "_parametrized", None) or [{}]
        for index, keywords in enumerate(cases):
            total += 1
            label = name if len(cases) == 1 else "%s[%d]" % (name, index)
            try:
                function(**keywords)
            except BaseException:  # noqa: BLE001 - a failing test is the point
                traceback.print_exc()
                broken.append(label)
    print("RESULT " + json.dumps({"total": total, "broken": broken}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
