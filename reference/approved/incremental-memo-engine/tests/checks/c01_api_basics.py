"""api_basics -- registration, evaluation, memoization, stats, validation."""

from _harness import Recorder, Suite, expect, expect_calls, expect_raises, instrumented, seed

from incremental import (
    CycleError,
    Engine,
    IncrementalError,
    InputNotSetError,
    Query,
    QueryNotRegisteredError,
)

suite = Suite("api_basics")
RNG = seed()


@suite.check("registration forms and Query handles")
def _():
    engine = Engine()

    @engine.query
    def alpha(ctx):
        return 1

    @engine.query(name="renamed")
    def beta(ctx):
        return 2

    expect(isinstance(alpha, Query), "bare @engine.query must return a Query handle")
    expect(isinstance(beta, Query), "@engine.query(name=...) must return a Query handle")
    expect(alpha.name == "alpha", "handle name must default to the function name, got %r" % (alpha.name,))
    expect(beta.name == "renamed", "explicit name= must win, got %r" % (beta.name,))
    expect(callable(alpha.fn), "Query.fn must expose the undecorated function")
    expect(alpha.fn(None) == 1, "Query.fn must be the original function")

    expect(engine.get(alpha) == 1, "get by handle")
    expect(engine.get("renamed") == 2, "get by name")

    def duplicate():
        @engine.query(name="alpha")
        def again(ctx):
            return 0

    expect_raises(ValueError, duplicate)


@suite.check("memoization: a body runs once per node")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "square")
    def _fn(ctx, n):
        return n * n + ctx.input("bias")

    engine.set_input("bias", RNG % 17)
    bias = RNG % 17
    for _ in range(3):
        expect(engine.get("square", 3) == 9 + bias, "value")
        expect(engine.get("square", 4) == 16 + bias, "value")
    expect_calls(rec, [("square", 3), ("square", 4)], "repeated gets")
    expect(engine.stats()["nodes"] == 2, "two distinct arg tuples -> two nodes")


@suite.check("stats() agrees with what the grader observed")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "leaf")
    def _fn(ctx, i):
        return ctx.input("x%d" % i)

    @instrumented(engine, rec, "total")
    def _fn2(ctx):
        return sum(ctx.call("leaf", i) for i in range(4))

    for i in range(4):
        engine.set_input("x%d" % i, i * 2)
    engine.get("total")
    engine.set_input("x2", 100)
    engine.get("total")

    observed = len(rec.calls)
    stats = engine.stats()
    expect(
        stats["executions"] == observed,
        "stats()['executions'] is %r but the grader counted %d body invocations"
        % (stats["executions"], observed),
    )
    expect(stats["nodes"] == 5, "expected 5 memoized nodes, got %r" % (stats["nodes"],))
    expect(stats["inputs"] == 4, "expected 4 inputs, got %r" % (stats["inputs"],))
    expect(stats["revision"] == engine.revision, "stats()['revision'] must match .revision")
    expect(isinstance(stats["revision"], int) and stats["revision"] > 0, "revision must advance")


@suite.check("input accessors")
def _():
    engine = Engine()
    expect(engine.has_input("k") is False, "has_input on an unset key")
    expect_raises(InputNotSetError, engine.get_input, "k")
    engine.set_input("k", RNG)
    expect(engine.has_input("k") is True, "has_input after set")
    expect(engine.get_input("k") == RNG, "get_input round-trip")
    expect(engine.remove_input("k") is True, "remove_input must report True when it removed something")
    expect(engine.remove_input("k") is False, "remove_input must report False for an unset key")
    expect(engine.has_input("k") is False, "has_input after remove")
    expect_raises(TypeError, engine.set_input, 5, "value")
    err = expect_raises(InputNotSetError, engine.get_input, "gone")
    expect(getattr(err, "key", None) == "gone", "InputNotSetError must carry .key")
    expect(isinstance(err, IncrementalError), "errors must derive from IncrementalError")


@suite.check("query reference validation")
def _():
    engine = Engine()
    other = Engine()

    @engine.query
    def mine(ctx):
        return 1

    @other.query
    def theirs(ctx):
        return 2

    expect_raises(QueryNotRegisteredError, engine.get, "nonexistent")
    expect_raises(ValueError, engine.get, theirs)
    expect_raises(TypeError, engine.get, 42)
    expect_raises(TypeError, engine.get, "mine", [1, 2])
    expect_raises(TypeError, engine.get, "mine", {"a": 1})
    err = expect_raises(QueryNotRegisteredError, engine.get, "nonexistent")
    expect(getattr(err, "name", None) == "nonexistent", "QueryNotRegisteredError must carry .name")


@suite.check("ctx.call accepts handles and names, ctx.input reads values")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "base")
    def base(ctx):
        return ctx.input("v")

    @instrumented(engine, rec, "byname")
    def _fn(ctx):
        return ctx.call("base") + 1

    @instrumented(engine, rec, "byhandle")
    def _fn2(ctx):
        return ctx.call(base) + 2

    engine.set_input("v", 10)
    expect(engine.get("byname") == 11, "ctx.call by name")
    expect(engine.get("byhandle") == 12, "ctx.call by handle")
    expect_calls(rec, ["base", "byname", "byhandle"], "shared dependency executes once")


@suite.check("a fresh engine starts empty")
def _():
    engine = Engine()
    stats = engine.stats()
    expect(engine.revision == 0, "a fresh engine must start at revision 0, got %r" % (engine.revision,))
    expect(stats == {"executions": 0, "nodes": 0, "revision": 0, "inputs": 0}, "fresh stats: %r" % (stats,))
    expect(issubclass(CycleError, IncrementalError), "CycleError must derive from IncrementalError")


if __name__ == "__main__":
    raise SystemExit(suite.main())
