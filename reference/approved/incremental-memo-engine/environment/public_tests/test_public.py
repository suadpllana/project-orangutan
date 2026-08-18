"""Public smoke tests for the `incremental` engine.

These are a small, deliberately easy subset of what the sealed grader checks.
Passing them is necessary but nowhere near sufficient: the grader adds exact
execution-count cases, randomized differential testing against a model of the
verification algorithm, durability edge cases and performance budgets.

Run with:  cd /app && python -m pytest public_tests -q
"""

import pytest

from incremental import (
    CacheFormatError,
    CycleError,
    Engine,
    InputNotSetError,
    QueryNotRegisteredError,
)


class Recorder:
    """Records one entry every time an instrumented query body runs."""

    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls = []

    @property
    def counts(self):
        out = {}
        for name in self.calls:
            out[name] = out.get(name, 0) + 1
        return out


def instrumented(engine, recorder, name):
    """Decorator: register `fn` under `name`, recording every execution."""

    def decorate(fn):
        def body(ctx, *args):
            recorder.calls.append(name if not args else (name,) + args)
            return fn(ctx, *args)

        body.__name__ = name
        return engine.query(body, name=name)

    return decorate


@pytest.fixture
def env():
    engine = Engine()
    recorder = Recorder()
    return engine, recorder


# --------------------------------------------------------------------------- #
# basics
# --------------------------------------------------------------------------- #
def test_first_get_computes_then_memoizes(env):
    engine, rec = env

    @instrumented(engine, rec, "double")
    def _(ctx):
        return ctx.input("x") * 2

    engine.set_input("x", 21)
    assert engine.get("double") == 42
    assert rec.calls == ["double"]

    assert engine.get("double") == 42
    assert rec.calls == ["double"], "a second get must not re-run the body"
    assert engine.stats()["executions"] == 1
    assert engine.stats()["nodes"] == 1


def test_arguments_identify_distinct_nodes(env):
    engine, rec = env

    @instrumented(engine, rec, "square")
    def _(ctx, n):
        return n * n

    assert engine.get("square", 3) == 9
    assert engine.get("square", 4) == 16
    assert engine.get("square", 3) == 9
    assert rec.counts == {("square", 3): 1, ("square", 4): 1}


def test_input_errors_and_validation(env):
    engine, rec = env

    @instrumented(engine, rec, "ident")
    def _(ctx):
        return ctx.input("missing")

    with pytest.raises(InputNotSetError):
        engine.get("ident")
    with pytest.raises(QueryNotRegisteredError):
        engine.get("nope")
    with pytest.raises(TypeError):
        engine.get("ident", [1, 2])
    with pytest.raises(TypeError):
        engine.set_input(7, "x")


def test_query_handle_from_another_engine_is_rejected(env):
    engine, rec = env
    other = Engine()

    @other.query
    def elsewhere(ctx):
        return 1

    with pytest.raises(ValueError):
        engine.get(elsewhere)


# --------------------------------------------------------------------------- #
# invalidation
# --------------------------------------------------------------------------- #
def test_setting_an_equal_value_is_a_noop(env):
    engine, rec = env

    @instrumented(engine, rec, "v")
    def _(ctx):
        return ctx.input("x")

    engine.set_input("x", [1, 2, 3])
    engine.get("v")
    revision = engine.revision
    rec.reset()

    engine.set_input("x", [1, 2, 3])
    assert engine.revision == revision, "an equal value must not bump the revision"
    engine.get("v")
    assert rec.calls == []


def test_change_propagates_through_the_chain(env):
    engine, rec = env

    @instrumented(engine, rec, "leaf")
    def _(ctx):
        return ctx.input("x")

    @instrumented(engine, rec, "mid")
    def _(ctx):
        return ctx.call("leaf") + 1

    @instrumented(engine, rec, "top")
    def _(ctx):
        return ctx.call("mid") * 10

    engine.set_input("x", 1)
    assert engine.get("top") == 20
    rec.reset()

    engine.set_input("x", 5)
    assert engine.get("top") == 60
    assert rec.counts == {"leaf": 1, "mid": 1, "top": 1}


def test_unrelated_subgraph_is_untouched(env):
    engine, rec = env

    @instrumented(engine, rec, "a")
    def _(ctx):
        return ctx.input("a")

    @instrumented(engine, rec, "b")
    def _(ctx):
        return ctx.input("b")

    engine.set_input("a", 1)
    engine.set_input("b", 1)
    engine.get("a")
    engine.get("b")
    rec.reset()

    engine.set_input("b", 2)
    assert engine.get("a") == 1
    assert rec.calls == [], "changing b must not touch a"


def test_remove_input_invalidates(env):
    engine, rec = env

    @instrumented(engine, rec, "v")
    def _(ctx):
        return ctx.input("x")

    engine.set_input("x", 3)
    assert engine.get("v") == 3
    assert engine.remove_input("x") is True
    assert engine.remove_input("x") is False
    with pytest.raises(InputNotSetError):
        engine.get("v")


# --------------------------------------------------------------------------- #
# early cutoff & dynamic dependencies
# --------------------------------------------------------------------------- #
def test_early_cutoff_stops_propagation(env):
    engine, rec = env

    @instrumented(engine, rec, "parity")
    def _(ctx):
        return ctx.input("n") % 2

    @instrumented(engine, rec, "mid")
    def _(ctx):
        return ctx.call("parity")

    @instrumented(engine, rec, "top")
    def _(ctx):
        return ctx.call("mid")

    engine.set_input("n", 1)
    assert engine.get("top") == 1
    rec.reset()

    engine.set_input("n", 3)  # parity is unchanged
    assert engine.get("top") == 1
    assert rec.calls == ["parity"], "the cutoff must happen at `parity`"

    rec.reset()
    engine.set_input("n", 4)  # parity flips
    assert engine.get("top") == 0
    assert rec.counts == {"parity": 1, "mid": 1, "top": 1}


def test_dependencies_shrink_when_a_branch_is_dropped(env):
    engine, rec = env

    @instrumented(engine, rec, "pick")
    def _(ctx):
        if ctx.input("use_a"):
            return ctx.input("a")
        return ctx.input("b")

    engine.set_input("use_a", True)
    engine.set_input("a", 1)
    engine.set_input("b", 2)
    assert engine.get("pick") == 1
    rec.reset()

    engine.set_input("b", 99)  # not a dependency right now
    assert engine.get("pick") == 1
    assert rec.calls == []

    engine.set_input("use_a", False)
    assert engine.get("pick") == 99
    rec.reset()

    engine.set_input("a", 1000)  # no longer a dependency
    assert engine.get("pick") == 99
    assert rec.calls == []


# --------------------------------------------------------------------------- #
# errors & cycles
# --------------------------------------------------------------------------- #
def test_exceptions_are_memoized_and_participate_in_cutoff(env):
    engine, rec = env

    @instrumented(engine, rec, "boom")
    def _(ctx):
        ctx.input("k")
        raise ValueError("always the same")

    @instrumented(engine, rec, "guard")
    def _(ctx):
        try:
            return "ok:" + str(ctx.call("boom"))
        except ValueError as exc:
            return "caught:" + str(exc)

    engine.set_input("k", 1)
    assert engine.get("guard") == "caught:always the same"
    first = None
    with pytest.raises(ValueError) as info:
        engine.get("boom")
    first = info.value
    rec.reset()

    with pytest.raises(ValueError) as info:
        engine.get("boom")
    assert info.value is first, "the memoized exception object must be re-raised"
    assert rec.calls == []

    engine.set_input("k", 2)
    assert engine.get("guard") == "caught:always the same"
    assert rec.calls == ["boom"], "an equal exception must cut the change off"


def test_cycle_is_reported_and_not_cached(env):
    engine, rec = env

    @instrumented(engine, rec, "a")
    def _(ctx):
        return ctx.call("b")

    @instrumented(engine, rec, "b")
    def _(ctx):
        return ctx.call("a")

    with pytest.raises(CycleError) as info:
        engine.get("a")
    assert info.value.cycle == [("a", ()), ("b", ())]
    assert engine.stats()["nodes"] == 0


def test_reentrant_calls_are_rejected(env):
    engine, rec = env

    @instrumented(engine, rec, "bad")
    def _(ctx):
        engine.set_input("x", 1)
        return 1

    with pytest.raises(RuntimeError):
        engine.get("bad")


# --------------------------------------------------------------------------- #
# durability
# --------------------------------------------------------------------------- #
def build(engine, rec):
    @instrumented(engine, rec, "leaf")
    def _(ctx, i):
        return ctx.input("x%d" % i)

    @instrumented(engine, rec, "total")
    def _(ctx):
        return sum(ctx.call("leaf", i) for i in range(3))


def test_save_load_preserves_incrementality(env, tmp_path):
    engine, rec = env
    build(engine, rec)
    for i in range(3):
        engine.set_input("x%d" % i, i)
    assert engine.get("total") == 3

    path = tmp_path / "cache.bin"
    engine.save(path)

    fresh = Engine()
    rec2 = Recorder()
    build(fresh, rec2)
    fresh.load(path)

    assert fresh.revision == engine.revision
    assert fresh.stats()["executions"] == 0
    assert fresh.get("total") == 3
    assert rec2.calls == [], "a loaded cache must not need recomputation"

    fresh.set_input("x1", 10)
    assert fresh.get("total") == 12
    assert rec2.counts == {("leaf", 1): 1, "total": 1}


def test_load_rejects_a_bad_file(env, tmp_path):
    engine, rec = env
    build(engine, rec)
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"this is not a cache file")
    with pytest.raises(CacheFormatError):
        engine.load(junk)
    with pytest.raises(OSError):
        engine.load(tmp_path / "does-not-exist.bin")


# --------------------------------------------------------------------------- #
# stats & scale
# --------------------------------------------------------------------------- #
def test_stats_agree_with_observed_executions(env):
    engine, rec = env
    build(engine, rec)
    for i in range(3):
        engine.set_input("x%d" % i, i)
    engine.get("total")
    engine.set_input("x0", 7)
    engine.get("total")
    assert engine.stats()["executions"] == len(rec.calls)
    assert engine.stats()["revision"] == engine.revision
    assert engine.stats()["inputs"] == 3


def test_a_moderately_deep_chain_works(env):
    engine, rec = env
    depth = 3000

    @engine.query(name="chain")
    def chain(ctx, i):
        if i == 0:
            return ctx.input("base")
        return ctx.call("chain", i - 1) + 1

    engine.set_input("base", 0)
    assert engine.get("chain", depth) == depth
