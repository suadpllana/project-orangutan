"""dynamic_deps -- dependency sets that grow, shrink and move between runs."""

from _harness import Recorder, Suite, expect, expect_calls, instrumented, seed

from incremental import Engine

suite = Suite("dynamic_deps")
RNG = seed()


@suite.check("a dropped input stops invalidating")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "pick")
    def _pick(ctx):
        if ctx.input("use_a"):
            return ("a", ctx.input("a"))
        return ("b", ctx.input("b"))

    engine.set_input("use_a", True)
    engine.set_input("a", 1)
    engine.set_input("b", 2)
    expect(engine.get("pick") == ("a", 1), "value")
    rec.reset()

    engine.set_input("b", 99)
    expect(engine.get("pick") == ("a", 1), "value")
    expect_calls(rec, [], "b is not a dependency yet")

    engine.set_input("use_a", False)
    expect(engine.get("pick") == ("b", 99), "value")
    expect_calls(rec, ["pick"], "the branch flip")

    engine.set_input("a", 1000)
    expect(engine.get("pick") == ("b", 99), "value")
    expect_calls(rec, [], "a is no longer a dependency")

    engine.set_input("b", 5)
    expect(engine.get("pick") == ("b", 5), "value")
    expect_calls(rec, ["pick"], "b is a dependency now")


@suite.check("a dropped query dependency stops invalidating")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "flag")
    def _flag(ctx):
        return ctx.input("flag")

    @instrumented(engine, rec, "heavy")
    def _heavy(ctx):
        return ctx.input("h") * 2

    @instrumented(engine, rec, "chooser")
    def _chooser(ctx):
        if ctx.call("flag"):
            return ctx.call("heavy")
        return -1

    engine.set_input("flag", 1)
    engine.set_input("h", 3)
    expect(engine.get("chooser") == 6, "value")
    rec.reset()

    engine.set_input("h", 4)
    expect(engine.get("chooser") == 8, "value")
    expect_calls(rec, ["heavy", "chooser"], "heavy is on the path")

    engine.set_input("flag", 0)
    expect(engine.get("chooser") == -1, "value")
    expect_calls(rec, ["flag", "chooser"], "the flag flip")

    engine.set_input("h", 100)
    expect(engine.get("chooser") == -1, "value")
    expect_calls(rec, [], "heavy was dropped from the dependency set")

    engine.set_input("flag", 1)
    expect(engine.get("chooser") == 200, "value")
    expect_calls(rec, ["flag", "chooser", "heavy"], "heavy comes back, freshly computed")


@suite.check("a dependency set that grows")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "cell")
    def _cell(ctx, i):
        return ctx.input("x%d" % i)

    @instrumented(engine, rec, "acc")
    def _acc(ctx):
        return sum(ctx.call("cell", i) for i in range(ctx.input("n")))

    for i in range(4):
        engine.set_input("x%d" % i, 10 ** i)
    engine.set_input("n", 1)
    expect(engine.get("acc") == 1, "value")
    rec.reset()

    engine.set_input("x2", 12345)
    expect(engine.get("acc") == 1, "value")
    expect_calls(rec, [], "cell 2 is not a dependency yet")

    engine.set_input("n", 3)
    expect(engine.get("acc") == 1 + 10 + 12345, "value")
    expect_calls(rec, ["acc", ("cell", 1), ("cell", 2)], "the two new cells appear")

    engine.set_input("x1", 7)
    expect(engine.get("acc") == 1 + 7 + 12345, "value")
    expect_calls(rec, [("cell", 1), "acc"], "cell 1 is a dependency now")


@suite.check("the dependency selected by an argument")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "slot")
    def _slot(ctx, k):
        return ctx.input("v%d" % k)

    @instrumented(engine, rec, "selected")
    def _selected(ctx):
        return ctx.call("slot", ctx.input("idx"))

    engine.set_input("v0", 10)
    engine.set_input("v1", 20)
    engine.set_input("idx", 0)
    expect(engine.get("selected") == 10, "value")
    rec.reset()

    engine.set_input("v1", 99)
    expect(engine.get("selected") == 10, "value")
    expect_calls(rec, [], "slot 1 is not reachable")

    engine.set_input("idx", 1)
    expect(engine.get("selected") == 99, "value")
    expect_calls(rec, ["selected", ("slot", 1)], "the new slot is computed")

    engine.set_input("v0", 1000)
    expect(engine.get("selected") == 99, "value")
    expect_calls(rec, [], "slot 0 was dropped")


@suite.check("dependency order can change between executions")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "P")
    def _p(ctx):
        return ctx.input("p")

    @instrumented(engine, rec, "Q")
    def _q(ctx):
        return ctx.input("q")

    @instrumented(engine, rec, "combo")
    def _combo(ctx):
        if ctx.input("swap"):
            return ctx.call("Q") * 10 + ctx.call("P")
        return ctx.call("P") * 10 + ctx.call("Q")

    engine.set_input("swap", False)
    engine.set_input("p", 1)
    engine.set_input("q", 2)
    expect(engine.get("combo") == 12, "value")
    rec.reset()

    engine.set_input("swap", True)
    expect(engine.get("combo") == 21, "value")
    expect_calls(rec, ["combo"], "only the order of the same dependencies changed")

    engine.set_input("q", 5)
    expect(engine.get("combo") == 51, "value")
    expect_calls(rec, ["Q", "combo"], "Q still invalidates after the reorder")

    engine.set_input("p", 6)
    expect(engine.get("combo") == 56, "value")
    expect_calls(rec, ["P", "combo"], "P still invalidates after the reorder")


@suite.check("many dependencies dropped at once stay dropped")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "cell")
    def _cell(ctx, i):
        return ctx.input("y%d" % i)

    @instrumented(engine, rec, "window")
    def _window(ctx):
        return sum(ctx.call("cell", i) for i in range(ctx.input("width")))

    for i in range(8):
        engine.set_input("y%d" % i, 1)
    engine.set_input("width", 8)
    expect(engine.get("window") == 8, "value")
    rec.reset()

    engine.set_input("width", 2)
    expect(engine.get("window") == 2, "value")
    expect_calls(rec, ["window"], "shrinking the window recomputes only the window")

    for i in range(2, 8):
        engine.set_input("y%d" % i, 100)
    expect(engine.get("window") == 2, "value")
    expect_calls(rec, [], "six dropped dependencies must all stay dropped")

    engine.set_input("y1", 5)
    expect(engine.get("window") == 6, "value")
    expect_calls(rec, [("cell", 1), "window"], "the surviving dependencies still work")


@suite.check("a dropped dependency does not come back through another change")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "toggle")
    def _toggle(ctx):
        return ctx.input("t")

    @instrumented(engine, rec, "expensive")
    def _expensive(ctx):
        return ctx.input("e") + 1

    @instrumented(engine, rec, "cheap")
    def _cheap(ctx):
        return ctx.input("c") + 2

    @instrumented(engine, rec, "gate")
    def _gate(ctx):
        if ctx.call("toggle"):
            return ctx.call("expensive")
        return ctx.call("cheap")

    engine.set_input("t", 1)
    engine.set_input("e", 10)
    engine.set_input("c", 20)
    expect(engine.get("gate") == 11, "value")

    engine.set_input("t", 0)
    expect(engine.get("gate") == 22, "value")
    rec.reset()

    for round_index in range(4):
        engine.set_input("e", 100 + round_index)
        expect(engine.get("gate") == 22, "value in round %d" % (round_index,))
        expect_calls(rec, [], "round %d: `expensive` was dropped" % (round_index,))

    engine.set_input("c", 30)
    expect(engine.get("gate") == 32, "value")
    expect_calls(rec, ["cheap", "gate"], "the live branch still invalidates")


@suite.check("shrinking and growing repeatedly")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "part")
    def _part(ctx, i):
        return ctx.input("p%d" % i) * (i + 1)

    @instrumented(engine, rec, "assembled")
    def _assembled(ctx):
        chosen = ctx.input("chosen")
        return tuple(ctx.call("part", i) for i in chosen)

    for i in range(4):
        engine.set_input("p%d" % i, 1)
    engine.set_input("chosen", (0, 1, 2, 3))
    expect(engine.get("assembled") == (1, 2, 3, 4), "value")
    rec.reset()

    engine.set_input("chosen", (1,))
    expect(engine.get("assembled") == (2,), "value")
    expect_calls(rec, ["assembled"], "no part needs recomputing")

    engine.set_input("p3", 9)
    expect(engine.get("assembled") == (2,), "value")
    expect_calls(rec, [], "part 3 is not selected")

    engine.set_input("chosen", (3, 1))
    expect(engine.get("assembled") == (36, 2), "value")
    expect_calls(rec, ["assembled", ("part", 3)], "part 3 comes back and is recomputed")

    engine.set_input("p0", 7)
    expect(engine.get("assembled") == (36, 2), "value")
    expect_calls(rec, [], "part 0 has been dropped for two rounds")


@suite.check("repeated reads count once")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "src")
    def _src(ctx):
        return ctx.input("x")

    @instrumented(engine, rec, "many")
    def _many(ctx):
        total = 0
        for _ in range(20):
            total += ctx.call("src") + ctx.input("x")
        return total

    engine.set_input("x", 2)
    expect(engine.get("many") == 80, "value")
    expect_calls(rec, ["src", "many"], "src runs once no matter how often it is read")

    engine.set_input("x", 3)
    expect(engine.get("many") == 120, "value")
    expect_calls(rec, ["src", "many"], "and once per invalidation")


if __name__ == "__main__":
    raise SystemExit(suite.main())
