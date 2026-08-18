"""invalidation -- revisions, dirty propagation, demand-driven evaluation."""

from _harness import Recorder, Suite, expect, expect_calls, expect_raises, instrumented, seed

from incremental import Engine, InputNotSetError

suite = Suite("invalidation")
RNG = seed()


def diamond():
    """base -> (left, right) -> top, with a grader-owned execution log."""
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "base")
    def _base(ctx):
        return ctx.input("x")

    @instrumented(engine, rec, "left")
    def _left(ctx):
        return ctx.call("base") * 2

    @instrumented(engine, rec, "right")
    def _right(ctx):
        return ctx.call("base") * 3

    @instrumented(engine, rec, "top")
    def _top(ctx):
        return ctx.call("left") + ctx.call("right") + ctx.input("bias")

    return engine, rec


@suite.check("setting an equal value changes nothing")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "copy")
    def _copy(ctx):
        return list(ctx.input("x"))

    @instrumented(engine, rec, "size")
    def _size(ctx):
        return len(ctx.call("copy")) + ctx.input("bias")

    engine.set_input("x", [1, {"a": 2}])
    engine.set_input("bias", 0)
    expect(engine.get("size") == 2, "value")
    revision = engine.revision
    rec.reset()

    engine.set_input("x", [1, {"a": 2}])  # equal, but a different object
    expect(engine.revision == revision, "an equal value must not bump the revision")
    engine.set_input("bias", 0)
    expect(engine.revision == revision, "an equal value must not bump the revision")
    engine.get("size")
    expect_calls(rec, [], "no-op set_input")

    engine.set_input("x", [1, {"a": 3}])  # a genuinely different value
    expect(engine.revision == revision + 1, "a different value must bump the revision")
    expect(engine.get("size") == 2, "value")
    expect_calls(rec, ["copy", "size"], "the change must reach both nodes")


@suite.check("a change reaches every dependent exactly once")
def _():
    engine, rec = diamond()
    engine.set_input("x", 1)
    engine.set_input("bias", 0)
    expect(engine.get("top") == 5, "value")
    expect_calls(rec, ["base", "left", "right", "top"], "first computation")

    engine.set_input("x", 4)
    expect(engine.get("top") == 20, "value after change")
    expect_calls(rec, ["base", "left", "right", "top"], "one change, one execution per node")


@suite.check("a change to one input does not touch an unrelated subgraph")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "red")
    def _red(ctx):
        return ctx.input("red") + 1

    @instrumented(engine, rec, "blue")
    def _blue(ctx):
        return ctx.input("blue") + 1

    @instrumented(engine, rec, "redtop")
    def _redtop(ctx):
        return ctx.call("red") * 10

    engine.set_input("red", 1)
    engine.set_input("blue", 1)
    engine.get("redtop")
    engine.get("blue")
    rec.reset()

    engine.set_input("blue", 99)
    expect(engine.get("redtop") == 20, "value")
    expect_calls(rec, [], "an unrelated change must execute nothing")

    expect(engine.get("blue") == 100, "value")
    expect_calls(rec, ["blue"], "only the affected node re-executes")


@suite.check("evaluation is demand driven")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "cell")
    def _cell(ctx, i):
        return ctx.input("x%d" % i)

    @instrumented(engine, rec, "rootA")
    def _a(ctx):
        return ctx.call("cell", 0) + ctx.call("cell", 1)

    @instrumented(engine, rec, "rootB")
    def _b(ctx):
        return ctx.call("cell", 2) + ctx.call("cell", 3)

    for i in range(4):
        engine.set_input("x%d" % i, i)

    engine.get("rootA")
    expect_calls(rec, [("cell", 0), ("cell", 1), "rootA"], "rootB's subgraph must stay untouched")
    expect(engine.stats()["nodes"] == 3, "only the demanded subgraph may be memoized")

    engine.set_input("x3", 100)
    engine.get("rootA")
    expect_calls(rec, [], "a change under rootB must not affect rootA")


@suite.check("a shared dependency is executed at most once per get")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "shared")
    def _shared(ctx):
        return ctx.input("x")

    for i in range(6):
        def make(i):
            @instrumented(engine, rec, "fan%d" % i)
            def _fan(ctx):
                return ctx.call("shared") + i
            return _fan
        make(i)

    @instrumented(engine, rec, "root")
    def _root(ctx):
        return sum(ctx.call("fan%d" % i) for i in range(6))

    engine.set_input("x", 1)
    engine.get("root")
    expect_calls(rec, ["shared"] + ["fan%d" % i for i in range(6)] + ["root"], "first pass")

    engine.set_input("x", 2)
    engine.get("root")
    expect_calls(
        rec,
        ["shared"] + ["fan%d" % i for i in range(6)] + ["root"],
        "shared must be executed once, not once per dependent",
    )


@suite.check("remove_input invalidates and can be undone")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "v")
    def _v(ctx):
        return ctx.input("x") * 2

    @instrumented(engine, rec, "w")
    def _w(ctx):
        return ctx.call("v") + 1

    engine.set_input("x", 5)
    expect(engine.get("w") == 11, "value")
    rec.reset()

    revision = engine.revision
    expect(engine.remove_input("x") is True, "remove_input return value")
    expect(engine.revision == revision + 1, "removing a set input must bump the revision")
    expect_raises(InputNotSetError, engine.get, "w")
    expect_calls(rec, ["v", "w"], "removal invalidates the whole chain")

    expect(engine.remove_input("x") is False, "removing an unset input is a no-op")
    expect(engine.revision == revision + 1, "a no-op removal must not bump the revision")

    engine.set_input("x", 5)
    expect(engine.get("w") == 11, "value restored")


@suite.check("reading an unset input records the dependency")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "maybe")
    def _maybe(ctx):
        return ctx.input("late") + 1

    expect_raises(InputNotSetError, engine.get, "maybe")
    rec.reset()
    expect_raises(InputNotSetError, engine.get, "maybe")
    expect_calls(rec, [], "the failure is memoized like any other outcome")

    engine.set_input("late", 41)
    expect(engine.get("maybe") == 42, "setting the input must invalidate the failed node")
    expect_calls(rec, ["maybe"], "exactly one re-execution")


@suite.check("re-getting at the same revision costs nothing")
def _():
    engine, rec = diamond()
    engine.set_input("x", RNG % 100)
    engine.set_input("bias", 7)
    engine.get("top")
    rec.reset()
    for _ in range(50):
        engine.get("top")
        engine.get("left")
        engine.get("base")
    expect_calls(rec, [], "nothing may re-execute while the revision stands still")


@suite.check("an intermediate node can be demanded directly")
def _():
    engine, rec = diamond()
    engine.set_input("x", 2)
    engine.set_input("bias", 1)
    expect(engine.get("left") == 4, "value")
    expect_calls(rec, ["base", "left"], "only base and left")
    expect(engine.get("top") == 11, "value")
    expect_calls(rec, ["right", "top"], "base and left are reused")


if __name__ == "__main__":
    raise SystemExit(suite.main())
