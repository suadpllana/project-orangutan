"""errors_cycles -- memoized exceptions, error cutoff, cycle reporting."""

from _harness import (
    Recorder,
    Suite,
    expect,
    expect_calls,
    expect_raises,
    instrumented,
    seed,
)

from incremental import CycleError, Engine, InputNotSetError

suite = Suite("errors_cycles")
RNG = seed()


@suite.check("an exception is memoized and re-raised as the same object")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "boom")
    def _boom(ctx):
        raise ValueError("kaboom %d" % ctx.input("k"))

    engine.set_input("k", 1)
    first = expect_raises(ValueError, engine.get, "boom")
    expect(str(first) == "kaboom 1", "message: %r" % (str(first),))
    rec.reset()

    for _ in range(3):
        again = expect_raises(ValueError, engine.get, "boom")
        expect(again is first, "the memoized exception object must be re-raised, not rebuilt")
    expect_calls(rec, [], "a memoized failure must not re-run the body")


@suite.check("errors propagate through ctx.call and are memoized on the way")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "bad")
    def _bad(ctx):
        raise KeyError(ctx.input("k"))

    @instrumented(engine, rec, "middle")
    def _middle(ctx):
        return ctx.call("bad") + 1

    @instrumented(engine, rec, "outer")
    def _outer(ctx):
        return ctx.call("middle") + 1

    engine.set_input("k", "zap")
    err = expect_raises(KeyError, engine.get, "outer")
    expect(err.args == ("zap",), "args: %r" % (err.args,))
    expect_calls(rec, ["outer", "middle", "bad"], "each level runs once")

    same = expect_raises(KeyError, engine.get, "outer")
    expect(same is err, "the propagated exception is memoized at every level")
    expect_calls(rec, [], "nothing re-runs")

    mid = expect_raises(KeyError, engine.get, "middle")
    expect(mid is err, "the middle node memoized the same object")


@suite.check("an equal exception cuts the change off")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "fails")
    def _fails(ctx):
        ctx.input("k")
        raise RuntimeError("always identical")

    @instrumented(engine, rec, "guard")
    def _guard(ctx):
        try:
            return "value:%s" % (ctx.call("fails"),)
        except RuntimeError as exc:
            return "caught:%s" % (exc,)

    engine.set_input("k", 1)
    expect(engine.get("guard") == "caught:always identical", "value")
    rec.reset()

    engine.set_input("k", 2)
    expect(engine.get("guard") == "caught:always identical", "value")
    expect_calls(rec, ["fails"], "an equal exception must not wake the dependent")

    engine.set_input("k", 3)
    expect_calls(rec, [], "no get, no work")
    engine.get("guard")
    expect_calls(rec, ["fails"], "still cutting off")


@suite.check("a changed exception message does propagate")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "fails")
    def _fails(ctx):
        raise RuntimeError("code %d" % ctx.input("k"))

    @instrumented(engine, rec, "guard")
    def _guard(ctx):
        try:
            ctx.call("fails")
            return "no error"
        except RuntimeError as exc:
            return "caught:%s" % (exc,)

    engine.set_input("k", 1)
    expect(engine.get("guard") == "caught:code 1", "value")
    rec.reset()

    engine.set_input("k", 2)
    expect(engine.get("guard") == "caught:code 2", "value")
    expect_calls(rec, ["fails", "guard"], "different args means a different outcome")


@suite.check("a different exception type is a different outcome")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "fails")
    def _fails(ctx):
        if ctx.input("mode") == "value":
            raise ValueError("same text")
        raise TypeError("same text")

    @instrumented(engine, rec, "guard")
    def _guard(ctx):
        try:
            ctx.call("fails")
            return "none"
        except Exception as exc:
            return type(exc).__name__

    engine.set_input("mode", "value")
    expect(engine.get("guard") == "ValueError", "value")
    rec.reset()

    engine.set_input("mode", "type")
    expect(engine.get("guard") == "TypeError", "value")
    expect_calls(rec, ["fails", "guard"], "type is part of outcome identity")


@suite.check("failing and succeeding are never equal outcomes")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "flaky")
    def _flaky(ctx):
        n = ctx.input("n")
        if n < 0:
            raise ValueError("negative")
        return n

    @instrumented(engine, rec, "guard")
    def _guard(ctx):
        try:
            return ctx.call("flaky")
        except ValueError:
            return "err"

    engine.set_input("n", 5)
    expect(engine.get("guard") == 5, "value")
    rec.reset()

    engine.set_input("n", -1)
    expect(engine.get("guard") == "err", "value")
    expect_calls(rec, ["flaky", "guard"], "value -> error must propagate")

    engine.set_input("n", -2)
    expect(engine.get("guard") == "err", "value")
    expect_calls(rec, ["flaky"], "error -> equal error cuts off")

    engine.set_input("n", 7)
    expect(engine.get("guard") == 7, "value")
    expect_calls(rec, ["flaky", "guard"], "error -> value must propagate")


@suite.check("dependencies recorded before a raise still invalidate")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "half")
    def _half(ctx):
        first = ctx.input("a")
        if first > 0:
            raise ValueError("positive")
        return ctx.input("b")

    engine.set_input("a", 1)
    engine.set_input("b", 100)
    expect_raises(ValueError, engine.get, "half")
    rec.reset()

    engine.set_input("b", 200)
    expect_raises(ValueError, engine.get, "half")
    expect_calls(rec, [], "b was never read, so it is not a dependency")

    engine.set_input("a", -1)
    expect(engine.get("half") == 200, "value")
    expect_calls(rec, ["half"], "a was read before the raise and must invalidate")


@suite.check("cycles are detected and described")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "self")
    def _self(ctx):
        return ctx.call("self")

    err = expect_raises(CycleError, engine.get, "self")
    expect(list(err.cycle) == [("self", ())], "self cycle: %r" % (err.cycle,))

    engine2 = Engine()

    @engine2.query
    def a(ctx):
        return ctx.call("b")

    @engine2.query
    def b(ctx):
        return ctx.call("c")

    @engine2.query
    def c(ctx):
        return ctx.call("a")

    err = expect_raises(CycleError, engine2.get, "a")
    expect(
        list(err.cycle) == [("a", ()), ("b", ()), ("c", ())],
        "3-cycle entered at a: %r" % (err.cycle,),
    )
    err = expect_raises(CycleError, engine2.get, "b")
    expect(
        list(err.cycle) == [("b", ()), ("c", ()), ("a", ())],
        "3-cycle entered at b: %r" % (err.cycle,),
    )


@suite.check("the cycle excludes the nodes that merely lead into it")
def _():
    engine = Engine()

    @engine.query
    def entry(ctx):
        return ctx.call("ring", 0)

    @engine.query
    def ring(ctx, i):
        return ctx.call("ring", (i + 1) % 3)

    err = expect_raises(CycleError, engine.get, "entry")
    expect(
        list(err.cycle) == [("ring", (0,)), ("ring", (1,)), ("ring", (2,))],
        "cycle must start at the re-entered node: %r" % (err.cycle,),
    )
    expect(engine.stats()["nodes"] == 0, "nothing in the cycle may be cached: %r" % (engine.stats(),))


@suite.check("a cycle is never memoized and the engine recovers")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "leafy")
    def _leafy(ctx):
        return ctx.input("x")

    @instrumented(engine, rec, "left")
    def _left(ctx):
        base = ctx.call("leafy")
        if ctx.input("loop"):
            return base + ctx.call("right")
        return base

    @instrumented(engine, rec, "right")
    def _right(ctx):
        return ctx.call("left") * 2

    engine.set_input("x", 3)
    engine.set_input("loop", True)
    expect_raises(CycleError, engine.get, "right")
    expect(engine.stats()["nodes"] == 1, "only `leafy` survives: %r" % (engine.stats(),))
    rec.reset()

    expect_raises(CycleError, engine.get, "right")
    expect_calls(rec, ["right", "left"], "a cycle is recomputed, never served from cache")

    engine.set_input("loop", False)
    expect(engine.get("right") == 6, "value once the cycle is broken")
    expect_calls(rec, ["right", "left"], "leafy is still cached")


@suite.check("mutating the engine from inside a query is rejected")
def _():
    for name, action in (
        ("set_input", lambda engine: engine.set_input("z", 1)),
        ("remove_input", lambda engine: engine.remove_input("x")),
        ("get", lambda engine: engine.get("inner")),
    ):
        engine = Engine()

        @engine.query
        def inner(ctx):
            return 1

        @engine.query(name="outer")
        def outer(ctx):
            action(engine)
            return 2

        engine.set_input("x", 1)
        expect_raises(RuntimeError, engine.get, "outer")


@suite.check("an unset input inside a deeper query surfaces cleanly")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "reader")
    def _reader(ctx):
        return ctx.input("never")

    @instrumented(engine, rec, "wrapper")
    def _wrapper(ctx):
        return ctx.call("reader")

    err = expect_raises(InputNotSetError, engine.get, "wrapper")
    expect(getattr(err, "key", None) == "never", "InputNotSetError.key: %r" % (getattr(err, "key", None),))


if __name__ == "__main__":
    raise SystemExit(suite.main())
