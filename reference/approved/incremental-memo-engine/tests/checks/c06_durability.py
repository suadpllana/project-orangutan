"""durability -- save/load must preserve the whole incremental state."""

import os
import tempfile

from _harness import (
    Recorder,
    Suite,
    expect,
    expect_calls,
    expect_raises,
    instrumented,
    seed,
)

from incremental import CacheFormatError, Engine, InputNotSetError

suite = Suite("durability")
RNG = seed()


def build(engine, rec):
    """leaf(i) -> mid(j) -> root, plus an independent `side` branch."""

    @instrumented(engine, rec, "leaf")
    def _leaf(ctx, i):
        return ctx.input("x%d" % i) % 100

    @instrumented(engine, rec, "mid")
    def _mid(ctx, j):
        return sum(ctx.call("leaf", 3 * j + k) for k in range(3))

    @instrumented(engine, rec, "root")
    def _root(ctx):
        return sum(ctx.call("mid", j) for j in range(3)) + ctx.input("bias")

    @instrumented(engine, rec, "side")
    def _side(ctx):
        return ctx.call("leaf", 0) * 1000

    return engine


def populate(engine):
    for i in range(9):
        engine.set_input("x%d" % i, i * 7)
    engine.set_input("bias", 5)


def tmpfile():
    handle, path = tempfile.mkstemp(suffix=".cache")
    os.close(handle)
    os.unlink(path)
    return path


@suite.check("a round trip preserves values, revision and incrementality")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        expected = engine.get("root")
        engine.get("side")
        saved_stats = engine.stats()
        engine.save(path)

        fresh = Engine()
        rec2 = Recorder()
        build(fresh, rec2)
        fresh.load(path)

        expect(fresh.revision == engine.revision, "revision: %r vs %r" % (fresh.revision, engine.revision))
        stats = fresh.stats()
        expect(stats["executions"] == 0, "load must reset the execution counter, got %r" % (stats["executions"],))
        expect(stats["nodes"] == saved_stats["nodes"], "node count: %r vs %r" % (stats["nodes"], saved_stats["nodes"]))
        expect(stats["inputs"] == saved_stats["inputs"], "input count")
        expect(fresh.get_input("x4") == 28, "input values must survive")

        expect(fresh.get("root") == expected, "value")
        expect(fresh.get("side") == 0, "value")
        expect_calls(rec2, [], "a loaded cache must need no recomputation at all")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("an incremental update after a load stays minimal")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        engine.get("root")
        engine.save(path)

        fresh = Engine()
        rec2 = Recorder()
        build(fresh, rec2)
        fresh.load(path)

        fresh.set_input("x4", 12345)
        expect(fresh.get("root") == 0 + 7 + 14 + (21 + 45 + 35) + (42 + 49 + 56) + 5, "value")
        expect_calls(rec2, [("leaf", 4), ("mid", 1), "root"], "only the affected path")

        fresh.set_input("x4", 12345 + 100)  # leaf 4 is unchanged modulo 100
        fresh.get("root")
        expect_calls(rec2, [("leaf", 4)], "early cutoff must still work after a load")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("stamps are preserved, not reinvented")
def _():
    # An implementation that stamps every loaded node as "verified now" would
    # serve a stale value here; one that forgets the stamps entirely would
    # recompute the untouched branch.
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        engine.get("root")
        engine.get("side")

        engine.set_input("x7", 1)      # a real change to mid(2), never re-read
        engine.set_input("unrelated", RNG)  # touches nothing at all
        engine.save(path)

        fresh = Engine()
        rec2 = Recorder()
        build(fresh, rec2)
        fresh.load(path)

        expect(fresh.get("side") == 0, "the untouched branch keeps its value")
        expect_calls(rec2, [], "the untouched branch must not be recomputed")

        expected = (0 + 7 + 14) + (21 + 28 + 35) + (42 + 1 + 56) + 5
        expect(fresh.get("root") == expected, "the pending change must be picked up after the load")
        expect_calls(rec2, [("leaf", 7), ("mid", 2), "root"], "and only that change")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("memoized failures survive a round trip")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()

        @instrumented(engine, rec, "boom")
        def _boom(ctx):
            raise ValueError("stored %d" % ctx.input("k"))

        engine.set_input("k", 3)
        expect_raises(ValueError, engine.get, "boom")
        engine.save(path)

        fresh = Engine()
        rec2 = Recorder()

        @instrumented(fresh, rec2, "boom")
        def _boom2(ctx):
            raise ValueError("stored %d" % ctx.input("k"))

        fresh.load(path)
        err = expect_raises(ValueError, fresh.get, "boom")
        expect(str(err) == "stored 3", "message: %r" % (str(err),))
        expect_calls(rec2, [], "the memoized failure must survive the round trip")

        fresh.set_input("k", 4)
        err = expect_raises(ValueError, fresh.get, "boom")
        expect(str(err) == "stored 4", "message after invalidation: %r" % (str(err),))
        expect_calls(rec2, ["boom"], "exactly one re-execution")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("unknown queries are dropped, transitively")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        engine.set_input("e", 4)

        @instrumented(engine, rec, "extra")
        def _extra(ctx):
            return ctx.input("e")

        @instrumented(engine, rec, "consumer")
        def _consumer(ctx):
            return ctx.call("extra") * 2

        engine.get("root")
        expect(engine.get("consumer") == 8, "value")
        before = engine.stats()["nodes"]
        engine.save(path)

        fresh = Engine()
        rec2 = Recorder()
        build(fresh, rec2)

        # `consumer` is registered again -- with a different body -- while
        # `extra` is not registered at all.  The saved `consumer` node depends
        # on a node that cannot survive, so it must be dropped too.
        @instrumented(fresh, rec2, "consumer")
        def _consumer2(ctx):
            return ctx.input("e") + 1000

        fresh.load(path)
        expect(
            fresh.stats()["nodes"] == before - 2,
            "expected %d nodes after dropping extra+consumer, got %d" % (before - 2, fresh.stats()["nodes"]),
        )
        expect(fresh.get("root") == engine.get("root"), "the surviving graph is intact")
        expect_calls(rec2, [], "the surviving graph needs no recomputation")

        expect(fresh.get("consumer") == 1004, "a dropped node must be recomputed from the new body")
        expect_calls(rec2, ["consumer"], "exactly one execution")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("load replaces whatever the engine already had")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        engine.get("root")
        engine.save(path)

        other = Engine()
        rec2 = Recorder()
        build(other, rec2)
        for i in range(9):
            other.set_input("x%d" % i, 900 + i)
        other.set_input("bias", 999)
        other.get("root")
        other.get("side")
        rec2.reset()

        other.load(path)
        expect(other.revision == engine.revision, "revision must come from the file")
        expect(other.get_input("x0") == 0, "inputs must come from the file")
        expect(other.get("root") == engine.get("root"), "values must come from the file")
        expect_calls(rec2, [], "and the cache with them")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("bad cache files are rejected")
def _():
    engine = Engine()
    rec = Recorder()
    build(engine, rec)

    path = tmpfile()
    try:
        with open(path, "wb") as stream:
            stream.write(b"\x00\x01not a cache at all\xff")
        expect_raises(CacheFormatError, engine.load, path)

        with open(path, "wb") as stream:
            stream.write(b"")
        expect_raises(CacheFormatError, engine.load, path)

        populate(engine)
        engine.get("root")
        engine.save(path)
        with open(path, "rb") as stream:
            good = stream.read()
        with open(path, "wb") as stream:
            stream.write(good[: max(1, len(good) // 2)])
        expect_raises(CacheFormatError, engine.load, path)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    expect_raises(OSError, engine.load, path + ".nope")


@suite.check("a failed save leaves the previous file usable")
def _():
    path = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        good_value = engine.get("root")
        engine.save(path)

        @instrumented(engine, rec, "unpicklable")
        def _unpicklable(ctx):
            return lambda: ctx  # closures cannot be pickled

        engine.get("unpicklable")
        try:
            engine.save(path)
        except Exception:
            pass
        else:
            raise AssertionError("saving an unpicklable value should not silently succeed")

        fresh = Engine()
        rec2 = Recorder()
        build(fresh, rec2)
        fresh.load(path)
        expect(fresh.get("root") == good_value, "the previous cache must still be readable")
        expect_calls(rec2, [], "and still incremental")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@suite.check("round trips are repeatable")
def _():
    path_a = tmpfile()
    path_b = tmpfile()
    try:
        engine = Engine()
        rec = Recorder()
        build(engine, rec)
        populate(engine)
        engine.get("root")
        engine.save(path_a)

        mid = Engine()
        rec2 = Recorder()
        build(mid, rec2)
        mid.load(path_a)
        mid.set_input("x8", 3)
        mid.get("root")
        mid.save(path_b)

        last = Engine()
        rec3 = Recorder()
        build(last, rec3)
        last.load(path_b)
        expect(last.get("root") == mid.get("root"), "value after two round trips")
        expect_calls(rec3, [], "no recomputation after two round trips")
        expect(last.revision == mid.revision, "revision after two round trips")

        last.remove_input("x0")
        expect_raises(InputNotSetError, last.get, "root")
    finally:
        for path in (path_a, path_b):
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    raise SystemExit(suite.main())
