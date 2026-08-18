"""deep_chain -- very deep dependency chains must not blow the stack."""

import sys

from _harness import Recorder, Suite, expect, expect_calls, instrumented, seed

from incremental import Engine

suite = Suite("deep_chain")
RNG = seed()
DEPTH = 20000


def make(reduce_at_zero):
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "link")
    def _link(ctx, i):
        if i == 0:
            return reduce_at_zero(ctx.input("base"))
        return ctx.call("link", i - 1)

    @instrumented(engine, rec, "aside")
    def _aside(ctx):
        return ctx.input("z")

    return engine, rec


@suite.check("a %d-deep chain computes" % DEPTH)
def _():
    engine, rec = make(lambda v: v)
    engine.set_input("base", RNG % 1000)
    engine.set_input("z", 0)
    expect(engine.get("link", DEPTH) == RNG % 1000, "value")
    expect(len(rec.take()) == DEPTH + 1, "every link must run exactly once")


@suite.check("the interpreter is left as it was found")
def _():
    engine, rec = make(lambda v: v)
    engine.set_input("base", 1)
    engine.set_input("z", 0)
    before = sys.getrecursionlimit()
    engine.get("link", DEPTH)
    after = sys.getrecursionlimit()
    expect(
        after == before,
        "the recursion limit must be restored: %d -> %d" % (before, after),
    )


@suite.check("re-verifying a %d-deep chain costs nothing" % DEPTH)
def _():
    engine, rec = make(lambda v: v)
    engine.set_input("base", 4)
    engine.set_input("z", 0)
    engine.get("link", DEPTH)
    rec.reset()

    engine.set_input("z", 1)  # nothing on the chain depends on z
    expect(engine.get("link", DEPTH) == 4, "value")
    expect_calls(rec, [], "a deep re-verification must execute nothing")

    engine.set_input("base", 4)  # equal value, no revision bump
    expect(engine.get("link", DEPTH) == 4, "value")
    expect_calls(rec, [], "still nothing")


@suite.check("a cutoff at the bottom of a %d-deep chain" % DEPTH)
def _():
    engine, rec = make(lambda v: v % 2)
    engine.set_input("base", 4)
    engine.set_input("z", 0)
    expect(engine.get("link", DEPTH) == 0, "value")
    rec.reset()

    engine.set_input("base", 6)  # 6 % 2 == 0, unchanged
    expect(engine.get("link", DEPTH) == 0, "value")
    expect_calls(rec, [("link", 0)], "the deep chain must not be recomputed")


@suite.check("a real change still travels the whole %d-deep chain" % DEPTH)
def _():
    engine, rec = make(lambda v: v % 2)
    engine.set_input("base", 4)
    engine.set_input("z", 0)
    engine.get("link", DEPTH)
    rec.reset()

    engine.set_input("base", 7)  # 7 % 2 == 1
    expect(engine.get("link", DEPTH) == 1, "value")
    expect(len(rec.take()) == DEPTH + 1, "every link must be recomputed exactly once")


if __name__ == "__main__":
    raise SystemExit(suite.main())
