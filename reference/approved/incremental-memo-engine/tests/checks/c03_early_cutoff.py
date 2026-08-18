"""early_cutoff -- exact execution counts where a change stops propagating."""

from _harness import Recorder, Suite, expect, expect_calls, instrumented, seed

from incremental import Engine

suite = Suite("early_cutoff")
RNG = seed()


def chain(names):
    """Build input 'n' -> names[0] -> names[1] -> ... with a shared log."""
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, names[0])
    def _first(ctx):
        return ctx.input("n") % 2

    previous = names[0]
    for name in names[1:]:
        def make(name, previous):
            @instrumented(engine, rec, name)
            def _link(ctx):
                return ctx.call(previous)
            return _link
        make(name, previous)
        previous = name
    return engine, rec


@suite.check("a change that produces an equal value stops at its source")
def _():
    engine, rec = chain(["parity", "a", "b", "c", "d"])
    engine.set_input("n", 1)
    expect(engine.get("d") == 1, "value")
    expect_calls(rec, ["parity", "a", "b", "c", "d"], "first computation")

    engine.set_input("n", 3)
    expect(engine.get("d") == 1, "value")
    expect_calls(rec, ["parity"], "the cutoff must happen at the source")

    engine.set_input("n", 5)
    expect(engine.get("d") == 1, "value")
    expect_calls(rec, ["parity"], "repeated cutoffs must keep cutting off")

    engine.set_input("n", 6)
    expect(engine.get("d") == 0, "value")
    expect_calls(rec, ["parity", "a", "b", "c", "d"], "a real change must still propagate")


@suite.check("a cut-off node stays green when something else changes")
def _():
    # This is the discriminator for the classic bug of comparing a dependency's
    # `changed_at` against the node's own `changed_at` instead of its
    # `verified_at`.  After a cutoff those two stamps differ.
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "val")
    def _val(ctx):
        return ctx.input("x")

    @instrumented(engine, rec, "bucket")
    def _bucket(ctx):
        return ctx.call("val") // 10

    @instrumented(engine, rec, "top")
    def _top(ctx):
        return ctx.call("bucket") + ctx.input("z")

    engine.set_input("x", 1)
    engine.set_input("z", 0)
    expect(engine.get("top") == 0, "value")
    rec.reset()

    engine.set_input("x", 2)  # val changes, bucket does not
    expect(engine.get("top") == 0, "value")
    expect_calls(rec, ["val", "bucket"], "the cutoff happens at bucket")

    engine.set_input("z", 5)  # nothing under bucket changed
    expect(engine.get("top") == 5, "value")
    expect_calls(rec, ["top"], "bucket and val must both stay green")

    engine.set_input("z", 6)
    expect(engine.get("top") == 6, "value")
    expect_calls(rec, ["top"], "and again")

    engine.set_input("x", 40)  # now bucket really moves
    expect(engine.get("top") == 10, "value")
    expect_calls(rec, ["val", "bucket", "top"], "a real change after a cutoff must propagate")


@suite.check("verification stops at the first changed dependency")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "A")
    def _a(ctx):
        return ctx.input("a")

    @instrumented(engine, rec, "B")
    def _b(ctx):
        return ctx.input("b")

    @instrumented(engine, rec, "N")
    def _n(ctx):
        if ctx.call("A"):
            return ctx.call("B")
        return 0

    engine.set_input("a", 1)
    engine.set_input("b", 1)
    expect(engine.get("N") == 1, "value")
    rec.reset()

    engine.set_input("a", 0)
    engine.set_input("b", 2)
    expect(engine.get("N") == 0, "value")
    expect_calls(
        rec,
        ["A", "N"],
        "A is the first recorded dependency and it changed, so B must not be brought up to date",
    )

    expect(engine.get("B") == 2, "value")
    expect_calls(rec, ["B"], "B is only computed when it is actually demanded")


@suite.check("a dependency dropped by the re-execution is never brought up to date")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "A")
    def _a(ctx):
        return ctx.input("a")

    @instrumented(engine, rec, "Bsub")
    def _bsub(ctx):
        return ctx.input("b")

    @instrumented(engine, rec, "B")
    def _b(ctx):
        return ctx.call("Bsub") * 2

    @instrumented(engine, rec, "N")
    def _n(ctx):
        if ctx.call("A") > 0:
            return ctx.call("B")
        return -1

    engine.set_input("a", 1)
    engine.set_input("b", 1)
    expect(engine.get("N") == 2, "value")
    rec.reset()

    engine.set_input("a", 0)
    engine.set_input("b", 5)
    expect(engine.get("N") == -1, "value")
    expect_calls(rec, ["A", "N"], "the whole B subtree is behind a changed first dependency")

    engine.set_input("b", 6)
    expect(engine.get("N") == -1, "value")
    expect_calls(rec, [], "B is no longer a dependency of N at all")

    engine.set_input("a", 1)
    expect(engine.get("N") == 12, "value")
    expect_calls(rec, ["A", "N", "Bsub", "B"], "B comes back, computed on demand")


@suite.check("a dependency replaced by the re-execution is never brought up to date")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "K")
    def _k(ctx):
        return ctx.input("k")

    @instrumented(engine, rec, "opt")
    def _opt(ctx, which):
        return ctx.input("v%d" % which) * 10

    @instrumented(engine, rec, "pick")
    def _pick(ctx):
        return ctx.call("opt", ctx.call("K"))

    engine.set_input("k", 0)
    engine.set_input("v0", 1)
    engine.set_input("v1", 2)
    expect(engine.get("pick") == 10, "value")
    rec.reset()

    engine.set_input("k", 1)
    engine.set_input("v0", 7)  # only reachable through the branch being dropped
    expect(engine.get("pick") == 20, "value")
    expect_calls(
        rec,
        ["K", "pick", ("opt", 1)],
        "opt(0) is behind a changed dependency and is dropped, so it must not run",
    )


@suite.check("a wide fan-in cuts off at the single changed leaf")
def _():
    engine = Engine()
    rec = Recorder()
    width = 8

    @instrumented(engine, rec, "leaf")
    def _leaf(ctx, i):
        return ctx.input("x%d" % i) % 5

    @instrumented(engine, rec, "agg")
    def _agg(ctx):
        return sum(ctx.call("leaf", i) for i in range(width))

    for i in range(width):
        engine.set_input("x%d" % i, i)
    expect(engine.get("agg") == sum(i % 5 for i in range(width)), "value")
    rec.reset()

    engine.set_input("x3", 3 + 5)  # 8 % 5 == 3, unchanged
    expect(engine.get("agg") == sum(i % 5 for i in range(width)), "value")
    expect_calls(rec, [("leaf", 3)], "only the touched leaf may run")

    engine.set_input("x6", 100)  # 100 % 5 == 0, leaf 6 was 1
    expect(engine.get("agg") == sum(i % 5 for i in range(width)) - 1, "value")
    expect_calls(rec, [("leaf", 6), "agg"], "the aggregate must see the real change")


@suite.check("cutoff over a long chain")
def _():
    depth = 200
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "link")
    def _link(ctx, i):
        if i == 0:
            return ctx.input("n") % 3
        return ctx.call("link", i - 1)

    engine.set_input("n", 4)
    expect(engine.get("link", depth) == 1, "value")
    rec.reset()

    engine.set_input("n", 7)  # 7 % 3 == 1, unchanged
    expect(engine.get("link", depth) == 1, "value")
    expect_calls(rec, [("link", 0)], "a %d-node chain must not be recomputed" % (depth,))

    engine.set_input("n", 8)  # 8 % 3 == 2
    expect(engine.get("link", depth) == 2, "value")
    expect_calls(
        rec,
        [("link", i) for i in range(depth + 1)],
        "a real change must reach the whole chain",
    )


@suite.check("equal-but-not-identical values still cut off")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "listy")
    def _listy(ctx):
        return [ctx.input("n") % 2, "constant"]

    @instrumented(engine, rec, "above")
    def _above(ctx):
        return len(ctx.call("listy"))

    engine.set_input("n", 2)
    engine.get("above")
    rec.reset()

    engine.set_input("n", 4)
    expect(engine.get("above") == 2, "value")
    expect_calls(rec, ["listy"], "equality, not identity, decides the cutoff")


@suite.check("cutoff shared by several dependents")
def _():
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "src")
    def _src(ctx):
        return ctx.input("n") % 4

    for i in range(5):
        def make(i):
            @instrumented(engine, rec, "user%d" % i)
            def _user(ctx):
                return ctx.call("src") * (i + 1)
            return _user
        make(i)

    @instrumented(engine, rec, "root")
    def _root(ctx):
        return sum(ctx.call("user%d" % i) for i in range(5))

    engine.set_input("n", 2)
    engine.get("root")
    rec.reset()

    engine.set_input("n", 6)  # 6 % 4 == 2, unchanged
    expect(engine.get("root") == 2 * 15, "value")
    expect_calls(rec, ["src"], "one execution, five dependents left alone")

    engine.set_input("n", 7)  # 7 % 4 == 3
    expect(engine.get("root") == 3 * 15, "value")
    expect_calls(
        rec,
        ["src"] + ["user%d" % i for i in range(5)] + ["root"],
        "a real change reaches everyone exactly once",
    )


@suite.check("a randomized cutoff sequence keeps values correct")
def _():
    import random

    rng = random.Random(RNG ^ 0x5EED)
    engine = Engine()
    rec = Recorder()

    @instrumented(engine, rec, "leaf")
    def _leaf(ctx):
        return ctx.input("n") % 3

    @instrumented(engine, rec, "mid")
    def _mid(ctx):
        return ctx.call("leaf") * 7

    @instrumented(engine, rec, "top")
    def _top(ctx):
        return ctx.call("mid") + 1

    current = rng.randrange(30)
    engine.set_input("n", current)
    expect(engine.get("top") == (current % 3) * 7 + 1, "value")
    rec.reset()

    for _ in range(60):
        nxt = rng.randrange(30)
        old_leaf = current % 3
        engine.set_input("n", nxt)
        expect(engine.get("top") == (nxt % 3) * 7 + 1, "value after n=%d" % (nxt,))
        if nxt == current:
            expected = []
        elif nxt % 3 == old_leaf:
            expected = ["leaf"]
        else:
            expected = ["leaf", "mid", "top"]
        expect_calls(rec, expected, "step n=%d -> %d" % (current, nxt))
        current = nxt


if __name__ == "__main__":
    raise SystemExit(suite.main())
