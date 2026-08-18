"""randomized -- differential testing against a model of the spec's algorithm.

Random query graphs and random edit sequences are driven through the
implementation under test *and* through an independent model that implements
section 3.5 of the spec directly.  After every step the two are compared on:

* the value (or exception) returned by every demanded node,
* the exact multiset of query bodies that were executed,
* the revision counter,
* the number of memoized nodes.

The node bodies are literally the same code in both worlds -- ``run_body`` is
handed a different ``read`` callback -- so any divergence is a divergence in the
incremental bookkeeping, not in the arithmetic.  Because the graphs and values
are generated from a per-run seed, no expected result can be hard-coded.
"""

import random

from _harness import Recorder, Suite, expect, multiset, seed

from incremental import Engine

suite = Suite("randomized")
RNG = seed()

STEPS = 45
BATCH = 16


# --------------------------------------------------------------------------- #
# the shared node bodies
# --------------------------------------------------------------------------- #
def safe(raw):
    """Reads never let a dependency's failure escape the body."""

    def read(ref):
        try:
            return raw(ref)
        except ValueError as exc:
            return -len(str(exc))

    return read


def run_body(node, read):
    kind = node["kind"]
    refs = node["refs"]
    if kind == "cond":
        # Reads exactly two of three references; which two depends on a value.
        head = read(refs[0])
        if head % 2 == 0:
            return read(refs[1]) % node["m"]
        return read(refs[2]) % node["m"]
    if kind == "select":
        # Reads exactly two of `len(refs)` references, and stops early.
        which = read(refs[0]) % (len(refs) - 1)
        return read(refs[1 + which]) % node["m"]
    if kind == "guard":
        # Short-circuits: everything after the first reference may vanish.
        head = read(refs[0])
        if head % 3 == 0:
            return head
        total = head
        for ref in refs[1:]:
            total += read(ref)
        return total % node["m"]
    total = 0
    for ref in refs:
        total += read(ref)
    if kind == "raise" and total % 3 == 0:
        raise ValueError("bad-%d" % (total % 2,))
    return total % node["m"]


KINDS = ["sum", "sum", "cond", "cond", "select", "select", "guard", "guard", "raise"]


def make_spec(rng):
    inputs = ["i%d" % k for k in range(rng.randrange(3, 7))]
    nodes = []
    for j in range(rng.randrange(10, 18)):
        pool = [("i", key) for key in inputs] + [("q", n["name"]) for n in nodes]
        kind = rng.choice(KINDS)
        if kind == "cond":
            count = 3
        elif kind == "select":
            count = rng.randrange(3, 6)
        else:
            count = rng.randrange(2, 5)
        nodes.append({
            "name": "n%d" % j,
            "kind": kind,
            "refs": [rng.choice(pool) for _ in range(count)],
            "m": rng.randrange(2, 6),
        })
    return {"inputs": inputs, "nodes": nodes, "domain": [rng.randrange(12) for _ in range(6)]}


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #
def outcome_equal(previous, value, error):
    if (previous["error"] is None) != (error is None):
        return False
    if error is not None:
        return type(previous["error"]) is type(error) and previous["error"].args == error.args
    try:
        return bool(previous["value"] == value)
    except Exception:
        return False


class Model:
    def __init__(self, spec):
        self.by_name = {node["name"]: node for node in spec["nodes"]}
        self.revision = 0
        self.inputs = {}
        self.input_changed = {}
        self.nodes = {}
        self.log = []

    def set_input(self, key, value):
        if key in self.inputs and self.inputs[key] == value:
            return
        self.revision += 1
        self.inputs[key] = value
        self.input_changed[key] = self.revision

    def get(self, name):
        node = self.ensure(name)
        if node["error"] is not None:
            raise node["error"]
        return node["value"]

    def ensure(self, name):
        node = self.nodes.get(name)
        if node is not None:
            if node["verified_at"] == self.revision:
                return node
            stale = False
            for dep in node["deps"]:
                if dep[0] == "i":
                    dep_changed = self.input_changed.get(dep[1], 0)
                else:
                    dep_changed = self.ensure(dep[1])["changed_at"]
                if dep_changed > node["verified_at"]:
                    stale = True
                    break
            if not stale:
                node["verified_at"] = self.revision
                return node
        return self.execute(name, node)

    def execute(self, name, previous):
        deps = []
        seen = set()

        def raw(ref):
            if ref not in seen:
                seen.add(ref)
                deps.append(ref)
            if ref[0] == "i":
                return self.inputs[ref[1]]
            child = self.ensure(ref[1])
            if child["error"] is not None:
                raise child["error"]
            return child["value"]

        self.log.append(name)
        try:
            value, error = run_body(self.by_name[name], safe(raw)), None
        except Exception as exc:
            value, error = None, exc

        changed_at = self.revision
        if previous is not None and outcome_equal(previous, value, error):
            changed_at = previous["changed_at"]
        node = {
            "value": value,
            "error": error,
            "deps": tuple(deps),
            "changed_at": changed_at,
            "verified_at": self.revision,
        }
        self.nodes[name] = node
        return node

    def take_log(self):
        out = self.log
        self.log = []
        return out


# --------------------------------------------------------------------------- #
# the implementation under test
# --------------------------------------------------------------------------- #
def register(engine, spec, rec):
    for node in spec["nodes"]:
        def make(node):
            def body(ctx):
                rec.calls.append(node["name"])

                def raw(ref):
                    if ref[0] == "i":
                        return ctx.input(ref[1])
                    return ctx.call(ref[1])

                return run_body(node, safe(raw))

            body.__name__ = node["name"]
            engine.query(body, name=node["name"])

        make(node)


def describe(fn):
    try:
        return ("value", fn())
    except Exception as exc:
        return ("error", type(exc).__name__, exc.args)


def trial(rng):
    """Return None if the implementation matched the model, else a message."""
    spec = make_spec(rng)
    names = [node["name"] for node in spec["nodes"]]
    engine = Engine()
    rec = Recorder()
    register(engine, spec, rec)
    model = Model(spec)

    for key in spec["inputs"]:
        value = rng.choice(spec["domain"])
        engine.set_input(key, value)
        model.set_input(key, value)

    for step in range(STEPS):
        for _ in range(rng.randrange(1, 4)):
            key = rng.choice(spec["inputs"])
            value = rng.choice(spec["domain"])
            engine.set_input(key, value)
            model.set_input(key, value)

        if engine.revision != model.revision:
            return "step %d: revision %r, expected %r" % (step, engine.revision, model.revision)

        for _ in range(rng.randrange(2, 5)):
            name = rng.choice(names)
            got = describe(lambda: engine.get(name))
            want = describe(lambda: model.get(name))
            if got != want:
                return "step %d: get(%s) -> %r, expected %r" % (step, name, got, want)

        observed = multiset(rec.take())
        expected = multiset(model.take_log())
        if observed != expected:
            return "step %d: executions %r, expected %r" % (step, observed, expected)

        if engine.stats()["nodes"] != len(model.nodes):
            return "step %d: %d memoized nodes, expected %d" % (
                step, engine.stats()["nodes"], len(model.nodes),
            )

    return None


def batch(offset, count):
    failures = []
    for index in range(count):
        rng = random.Random((RNG ^ 0xA5A5A5) + offset * 1000 + index)
        try:
            problem = trial(rng)
        except Exception as exc:
            problem = "crashed: %s: %s" % (type(exc).__name__, exc)
        if problem is not None:
            failures.append("graph #%d -- %s" % (offset * 1000 + index, problem))
    passed = count - len(failures)
    note = "%d/%d random graphs matched the model" % (passed, count)
    if failures:
        note += "; first failures: " + " | ".join(failures[:3])
    return passed / float(count), note


@suite.check("random graphs, batch 1", 2.0)
def _():
    return batch(0, BATCH)


@suite.check("random graphs, batch 2", 2.0)
def _():
    return batch(1, BATCH)


@suite.check("random graphs, batch 3", 2.0)
def _():
    return batch(2, BATCH)


@suite.check("the cumulative execution counter matches the model", 1.0)
def _():
    rng = random.Random(RNG ^ 0x13579)
    spec = make_spec(rng)
    names = [node["name"] for node in spec["nodes"]]
    engine = Engine()
    rec = Recorder()
    register(engine, spec, rec)
    model = Model(spec)

    for key in spec["inputs"]:
        value = rng.choice(spec["domain"])
        engine.set_input(key, value)
        model.set_input(key, value)

    total = 0
    for _ in range(40):
        key = rng.choice(spec["inputs"])
        value = rng.choice(spec["domain"])
        engine.set_input(key, value)
        model.set_input(key, value)
        name = rng.choice(names)
        try:
            engine.get(name)
        except Exception:
            pass
        try:
            model.get(name)
        except Exception:
            pass
        total += len(rec.take())
        model.take_log()

    expect(
        engine.stats()["executions"] == total,
        "stats() reports %d executions, the grader observed %d"
        % (engine.stats()["executions"], total),
    )


if __name__ == "__main__":
    raise SystemExit(suite.main())
