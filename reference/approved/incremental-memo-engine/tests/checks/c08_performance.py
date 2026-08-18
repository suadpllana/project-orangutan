"""performance -- execution and wall-clock budgets on a large graph."""

import random
import time

from _harness import Recorder, Suite, expect, multiset, seed

from incremental import Engine

suite = Suite("performance")
RNG = seed()

LEAVES = 4000
FANOUT = 10
MIDS = LEAVES // FANOUT          # 400
TOPS = MIDS // FANOUT            # 40
NODES = LEAVES + MIDS + TOPS + 1
UPDATES = 200

FAST_SECONDS = 30.0              # full marks at or below this
SLOW_SECONDS = 120.0             # no marks at or above this

STATE = {}


def workload():
    if STATE:
        return STATE
    rng = random.Random(RNG ^ 0xC0FFEE)
    engine = Engine()
    rec = Recorder()

    @engine.query(name="leaf")
    def leaf(ctx, i):
        rec.calls.append(("leaf", i))
        return ctx.input("x%d" % i) % 1000

    @engine.query(name="mid")
    def mid(ctx, j):
        rec.calls.append(("mid", j))
        return sum(ctx.call("leaf", j * FANOUT + k) for k in range(FANOUT))

    @engine.query(name="top")
    def top(ctx, t):
        rec.calls.append(("top", t))
        return sum(ctx.call("mid", t * FANOUT + k) for k in range(FANOUT))

    @engine.query(name="root")
    def root(ctx):
        rec.calls.append("root")
        return sum(ctx.call("top", t) for t in range(TOPS))

    values = {}
    for i in range(LEAVES):
        values[i] = rng.randrange(1000)
        engine.set_input("x%d" % i, values[i])

    total_calls = 0

    started = time.perf_counter()
    expected = sum(v % 1000 for v in values.values())
    got = engine.get("root")
    STATE["build_value_ok"] = got == expected
    STATE["build_calls"] = len(rec.take())
    total_calls += STATE["build_calls"]
    STATE["build_seconds"] = time.perf_counter() - started

    # --- phase B: real single-leaf changes ------------------------------- #
    started = time.perf_counter()
    bad_update = None
    for _ in range(UPDATES):
        i = rng.randrange(LEAVES)
        new = (values[i] + 1 + rng.randrange(998)) % 1000
        expected += new - (values[i] % 1000)
        values[i] = new
        engine.set_input("x%d" % i, new)
        got = engine.get("root")
        batch = rec.take()
        total_calls += len(batch)
        observed = multiset(batch)
        want = multiset([("leaf", i), ("mid", i // FANOUT), ("top", i // (FANOUT * FANOUT)), "root"])
        if got != expected or observed != want:
            if bad_update is None:
                bad_update = "leaf %d: value %r vs %r, executions %r vs %r" % (
                    i, got, expected, observed, want,
                )
    STATE["update_bad"] = bad_update
    STATE["update_seconds"] = time.perf_counter() - started

    # --- phase C: no-op writes ------------------------------------------- #
    started = time.perf_counter()
    revision = engine.revision
    for _ in range(UPDATES):
        i = rng.randrange(LEAVES)
        engine.set_input("x%d" % i, values[i])
        engine.get("root")
    STATE["noop_calls"] = len(rec.take())
    total_calls += STATE["noop_calls"]
    STATE["noop_revision_moved"] = engine.revision != revision
    STATE["noop_seconds"] = time.perf_counter() - started

    # --- phase D: changes that cut off at the leaf ------------------------ #
    started = time.perf_counter()
    bad_cutoff = None
    for _ in range(UPDATES):
        i = rng.randrange(LEAVES)
        raw = engine.get_input("x%d" % i)
        engine.set_input("x%d" % i, raw + 1000)  # same value modulo 1000
        got = engine.get("root")
        batch = rec.take()
        total_calls += len(batch)
        observed = multiset(batch)
        if got != expected or observed != {("leaf", i): 1}:
            if bad_cutoff is None:
                bad_cutoff = "leaf %d: value %r vs %r, executions %r" % (i, got, expected, observed)
    STATE["cutoff_bad"] = bad_cutoff
    STATE["cutoff_seconds"] = time.perf_counter() - started

    STATE["total_seconds"] = (
        STATE["build_seconds"] + STATE["update_seconds"]
        + STATE["noop_seconds"] + STATE["cutoff_seconds"]
    )
    STATE["stats_executions"] = engine.stats()["executions"]
    STATE["observed_executions"] = total_calls
    return STATE


@suite.check("a %d-node graph builds with one execution per node" % NODES, 1.0)
def _():
    state = workload()
    expect(state["build_value_ok"], "the initial value is wrong")
    expect(
        state["build_calls"] == NODES,
        "expected %d executions to build the graph, observed %d" % (NODES, state["build_calls"]),
    )


@suite.check("%d single-leaf updates each touch exactly four nodes" % UPDATES, 2.0)
def _():
    state = workload()
    expect(state["update_bad"] is None, "first bad update -- %s" % (state["update_bad"],))


@suite.check("writing the same value back does nothing at all", 1.0)
def _():
    state = workload()
    expect(not state["noop_revision_moved"], "no-op writes must not move the revision")
    expect(
        state["noop_calls"] == 0,
        "no-op writes triggered %d executions" % (state["noop_calls"],),
    )


@suite.check("%d cut-off updates each touch exactly one node" % UPDATES, 2.0)
def _():
    state = workload()
    expect(state["cutoff_bad"] is None, "first bad cutoff -- %s" % (state["cutoff_bad"],))


@suite.check("stats() matches the observed execution total", 1.0)
def _():
    state = workload()
    expect(
        state["stats_executions"] == state["observed_executions"],
        "stats() says %d executions, the grader counted %d"
        % (state["stats_executions"], state["observed_executions"]),
    )


@suite.check("the whole workload fits the time budget", 3.0)
def _():
    state = workload()
    total = state["total_seconds"]
    detail = "build %.2fs, updates %.2fs, no-ops %.2fs, cutoffs %.2fs, total %.2fs" % (
        state["build_seconds"], state["update_seconds"],
        state["noop_seconds"], state["cutoff_seconds"], total,
    )
    if total <= FAST_SECONDS:
        return None, detail
    if total >= SLOW_SECONDS:
        raise AssertionError("too slow: %s (budget %.0fs)" % (detail, SLOW_SECONDS))
    fraction = (SLOW_SECONDS - total) / (SLOW_SECONDS - FAST_SECONDS)
    return fraction, detail


if __name__ == "__main__":
    raise SystemExit(suite.main())
