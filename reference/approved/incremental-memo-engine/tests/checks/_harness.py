"""Shared plumbing for the sealed grader.

Every category module builds a :class:`Suite`, registers checks against it and
calls ``suite.main()``.  ``grade.py`` runs each module in its own subprocess and
reads the JSON result file, so a crash (segfault, ``RecursionError`` escaping to
the interpreter, a hang) costs that category only.

The important design rule: *the grader never trusts the implementation's own
accounting*.  Execution counts come from closures owned by the grader, which the
implementation under test cannot observe or influence.
"""

import json
import os
import sys
import traceback

_APP = os.environ.get("IMPL_ROOT", "/app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)


def seed():
    """The per-run seed, so expected values cannot be hard-coded."""
    raw = os.environ.get("GRADER_SEED")
    if raw is None:
        return int.from_bytes(os.urandom(4), "big")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int.from_bytes(raw.encode("utf-8", "replace")[:4].ljust(4, b"\0"), "big")


class Recorder:
    """Grader-owned execution log.  One entry per query-body invocation."""

    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls = []

    def take(self):
        out = self.calls
        self.calls = []
        return out

    def counts(self):
        out = {}
        for item in self.calls:
            out[item] = out.get(item, 0) + 1
        return out


def label(name, args):
    return name if not args else (name,) + tuple(args)


def instrumented(engine, recorder, name):
    """Register `fn` under `name`, logging every execution of its body."""

    def decorate(fn):
        def body(ctx, *args):
            recorder.calls.append(label(name, args))
            return fn(ctx, *args)

        body.__name__ = name
        return engine.query(body, name=name)

    return decorate


def multiset(items):
    out = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_calls(recorder, expected, message=""):
    """Assert the executions since the last reset are exactly `expected`."""
    got = multiset(recorder.take())
    want = multiset(expected)
    if got != want:
        raise AssertionError(
            "%swrong executions\n  expected: %s\n  observed: %s" % (
                message + ": " if message else "", _fmt(want), _fmt(got)
            )
        )


def _fmt(counter):
    if not counter:
        return "{} (nothing)"
    return "{" + ", ".join("%r: %d" % (k, v) for k, v in sorted(counter.items(), key=repr)) + "}"


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - we want the message
        raise AssertionError(
            "expected %s, got %s: %s" % (exc_type.__name__, type(exc).__name__, exc)
        ) from None
    raise AssertionError("expected %s, nothing was raised" % (exc_type.__name__,))


class Suite:
    def __init__(self, category):
        self.category = category
        self._checks = []

    def check(self, name, points=1.0):
        def decorate(fn):
            self._checks.append((name, float(points), fn))
            return fn

        return decorate

    def main(self, argv=None):
        argv = sys.argv if argv is None else argv
        out_path = argv[1]
        results = []
        for name, points, fn in self._checks:
            entry = {"name": name, "points": points, "earned": 0.0, "detail": ""}
            try:
                outcome = fn()
                note = ""
                if isinstance(outcome, tuple):
                    outcome, note = outcome
                if outcome is None:
                    entry["earned"] = points
                    entry["detail"] = note
                else:
                    fraction = max(0.0, min(1.0, float(outcome)))
                    entry["earned"] = points * fraction
                    entry["detail"] = ("partial credit %.3f; " % (fraction,)) + note
            except Exception:
                entry["detail"] = traceback.format_exc(limit=8)[-1500:]
            except BaseException as exc:  # RecursionError subclasses can be brutal
                entry["detail"] = "fatal: %s: %s" % (type(exc).__name__, exc)
            results.append(entry)
        with open(out_path, "w", encoding="utf-8") as stream:
            json.dump({"category": self.category, "checks": results}, stream)
        return 0
