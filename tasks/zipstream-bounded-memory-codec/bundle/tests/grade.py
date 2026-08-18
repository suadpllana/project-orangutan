#!/usr/bin/env python3
"""Sealed grader for the zipstream task.

Structure, and why it is this shape:

* The grader never imports the submission. Every call into it happens in a
  fresh interpreter run by `child_codec.py`, so a module that hangs, crashes or
  eats the machine on import costs one measurement instead of the report.

* Compression and decompression of the same stream run in DIFFERENT processes.
  Nothing but the frame on disk crosses between them, which is the only way to
  make "hand back a receipt and keep the payload in a global" impossible rather
  than merely forbidden.

* Measurements are shared across scoring categories. A category here is a view
  over the measurement table, not a separate run, so the eight categories cost
  one compression per stream instead of eight.

* The whole run holds a global deadline. Each call also has its own cap, and a
  call that would start past the deadline is recorded as unrun -- it counts
  against the score, but it never costs the report.

The reward is written before grading starts (0.0), and again at the end, to
every location and under both names the harness might look for.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _baseline  # noqa: E402
import _corpus  # noqa: E402
import _integrity  # noqa: E402

IMPL_ROOT = os.environ.get("IMPL_ROOT", "/app")
LOG_DIR = os.environ.get("LOG_DIR", "/logs")

PASS_THRESHOLD = 0.88

# Wall-clock budgets. The reference grades in about 85s; `[verifier]
# timeout_sec` in task.toml is 1000 and the draft's envelope is 1200, so this
# deadline sits comfortably inside both. A submission nine times slower than
# the reference still finishes.
DEADLINE_SECONDS = 780
PER_CALL_TIMEOUT = 120

# --------------------------------------------------------------------- the rules
# Every one of these numbers is quoted in instruction.md; the spec and the
# grader are meant to be readable side by side.

BIG = 512 * 1024
HUGE = 896 * 1024
WORKING_BUDGET = 384 * 1024
RESIDENT_BUDGET = 384 * 1024
MEMORY_DRIFT = 32 * 1024
INCREMENTAL_FRACTION = 0.25
ADAPTIVITY_SLACK = 1.05
OPAQUE_CEILING = 1.04

RATIO_TARGETS = {
    "logfmt": 0.52,
    "csv": 0.56,
    "jsonl": 0.50,
    "binlog": 0.92,
    "mixed": 0.65,
}

CATEGORIES = [
    ("contract", 0.13),
    ("roundtrip", 0.19),
    ("memory", 0.13),
    ("framing", 0.09),
    ("ratio", 0.26),
    ("ceiling", 0.09),
    ("adaptivity", 0.06),
    ("robustness", 0.05),
    ("regression", 0.00),
]

# Small frames, because a collector sends far more of them than large ones.
# They are scored in aggregate rather than one by one: a per-frame bound tight
# enough to fail a 265-byte code table would also fail an honest design whose
# header happens to be a few bytes bigger, and the fixed cost of a frame is
# what is actually being measured.
TINY = [
    ("empty", b""),
    ("one_zero", b"\x00"),
    ("one_letter", b"A"),
    ("three", b"\xff\x00\xff"),
    ("seven", b"ts=1 h\n"),
    ("line", b"ts=1713451200 host=edge-01 lvl=INFO\n"),
    ("full_alphabet", bytes(range(256))),
]
# Average slack per frame in the aggregate bound.
FRAME_ALLOWANCE = 24

# Two small payloads that genuinely compress. A container that writes a code
# table into every frame cannot get near these: the shipping codec turns 200
# bytes into 372.
SMALL_REPETITIVE = (b"ts=1 host=edge-01 svc=ingest lvl=INFO\n" * 6)[:200]
SMALL_REPETITIVE_BOUND = 100
SMALL_JSON = (b'{"ts":1713451200123,"h":"edge-01","s":"ingest","lvl":"INFO"}\n' * 8)[:400]
SMALL_JSON_BOUND = 260


def expansion_bound(size):
    """The most a frame may ever be, for an input of `size` bytes."""
    return size + 64 + size // 64


# ------------------------------------------------------------------ reward files

REWARD_NAMES = ("reward.txt", "reward.json", "score.txt", "score.json")


def reward_directories():
    seen = []
    for directory in (LOG_DIR, "/logs", "/verifier", "/tests", HERE,
                      os.path.dirname(HERE), os.getcwd(), tempfile.gettempdir()):
        if directory and directory not in seen:
            seen.append(directory)
    return seen


def clear_stale_rewards():
    """The agent can write to /logs. A leftover 1.0 must never be read as a score."""
    cleared = []
    for directory in reward_directories():
        for name in REWARD_NAMES + ("junit.xml",):
            path = os.path.join(directory, name)
            try:
                if os.path.exists(path):
                    os.chmod(path, 0o644)
                    os.unlink(path)
                    cleared.append(path)
            except OSError:
                print("WARNING: could not clear a pre-existing %s" % (path,))
    if cleared:
        print("cleared %d stale reward artefact(s)" % (len(cleared),))


def publish(score, report=None):
    """Write the score everywhere the harness might look, under both names."""
    payload = dict(report or {})
    payload["score"] = score
    payload["reward"] = score
    text = "%.6f\n" % (score,)
    blob = json.dumps(payload, indent=2, sort_keys=True)
    written = []
    for directory in reward_directories():
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            continue
        for name in REWARD_NAMES:
            path = os.path.join(directory, name)
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(blob if name.endswith(".json") else text)
                written.append(path)
            except OSError:
                pass
    return written


# -------------------------------------------------------------------- the runner


class Runner(object):
    """Runs codec calls in child processes, under one shared deadline."""

    def __init__(self, impl_root, scratch, deadline):
        self.impl_root = impl_root
        self.scratch = scratch
        self.deadline = deadline
        self.results = {}
        self.calls = 0
        self.seconds = 0.0

    def remaining(self):
        return self.deadline - time.monotonic()

    def call(self, name, mode, input_path, short_reads=False):
        if name in self.results:
            return self.results[name]

        left = self.remaining()
        if left <= 3:
            outcome = {"ok": False, "error": "not run: the verifier ran out of time",
                       "unrun": True, "violations": []}
            self.results[name] = outcome
            return outcome

        output_path = os.path.join(self.scratch, "out_%s.bin" % (name,))
        report_path = os.path.join(self.scratch, "rep_%s.json" % (name,))
        request_path = os.path.join(self.scratch, "req_%s.json" % (name,))
        sandbox = os.path.join(self.scratch, "cwd_%s" % (name,))
        os.makedirs(sandbox, exist_ok=True)

        with open(request_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "mode": mode,
                    "impl_root": self.impl_root,
                    "input": input_path,
                    "output": output_path,
                    "report": report_path,
                    "short_reads": short_reads,
                },
                handle,
            )

        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONHASHSEED"] = "0"
        environment.pop("PYTHONPATH", None)

        started = time.time()
        timed_out = False
        stderr = ""
        try:
            finished = subprocess.run(
                [sys.executable, os.path.join(HERE, "child_codec.py"), request_path],
                cwd=sandbox,
                env=environment,
                timeout=min(PER_CALL_TIMEOUT, max(3, left)),
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            stderr = finished.stderr or ""
        except subprocess.TimeoutExpired:
            timed_out = True
        elapsed = time.time() - started
        self.calls += 1
        self.seconds += elapsed

        if os.path.isfile(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as handle:
                    outcome = json.load(handle)
            except ValueError:
                outcome = {"ok": False, "error": "the child wrote an unreadable report",
                           "violations": []}
        else:
            outcome = {
                "ok": False,
                "violations": [],
                "error": ("timed out after %ds" % (min(PER_CALL_TIMEOUT, int(left)),))
                if timed_out
                else "the child produced no report\n%s" % (stderr[-800:],),
            }

        # Nothing the codec ran should have left anything behind.
        leftovers = sorted(os.listdir(sandbox))
        if leftovers:
            outcome.setdefault("violations", []).append(
                "left files behind: %s" % (", ".join(leftovers[:5]),)
            )

        outcome["output"] = output_path
        outcome["seconds_wall"] = elapsed
        self.results[name] = outcome
        return outcome


def call_ok(result):
    """A measurement counts only if the call obeyed every stated constraint."""
    if not result or not result.get("ok"):
        return False
    if result.get("violations"):
        return False
    if result.get("resident", 0) > RESIDENT_BUDGET:
        return False
    if result.get("working", 0) > WORKING_BUDGET:
        return False
    return True


def why_not(result):
    if not result:
        return "no result"
    if result.get("error"):
        return result["error"].splitlines()[0][:200]
    if result.get("violations"):
        return "; ".join(result["violations"][:3])
    if result.get("resident", 0) > RESIDENT_BUDGET:
        return "import footprint %d B exceeds %d" % (result["resident"], RESIDENT_BUDGET)
    if result.get("working", 0) > WORKING_BUDGET:
        return "working set %d B exceeds %d" % (result["working"], WORKING_BUDGET)
    return "ok"


# --------------------------------------------------------------------- the checks


class Sheet(object):
    def __init__(self):
        self.checks = []

    def add(self, category, name, earned, detail="", points=1.0):
        self.checks.append(
            {
                "category": category,
                "name": name,
                "points": points,
                "earned": max(0.0, min(points, float(earned))),
                "detail": detail,
            }
        )

    def by_category(self):
        grouped = {}
        for check in self.checks:
            grouped.setdefault(check["category"], []).append(check)
        return grouped


def same_bytes(first, second):
    try:
        with open(first, "rb") as left, open(second, "rb") as right:
            while True:
                a = left.read(1 << 16)
                b = right.read(1 << 16)
                if a != b:
                    return False
                if not a:
                    return True
    except OSError:
        return False


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def write_stream(scratch, name, data):
    path = os.path.join(scratch, "in_%s.bin" % (name,))
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def build_edge_stream(seed):
    """One stream that is many shapes at once, so heterogeneity is graded too."""
    parts = [
        b"\x00" * 8192,
        _corpus.generate("logfmt", 96 * 1024, seed),
        b"\xff" * 4096,
        _corpus.alphabet_cycle(16 * 1024),
        _corpus.generate("random", 48 * 1024, seed + 1),
        b"\n" * 1024,
        _corpus.generate("jsonl", 96 * 1024, seed + 2),
        _corpus.repeated(0x7A, 32 * 1024),
        _corpus.generate("binlog", 96 * 1024, seed + 3),
    ]
    blob = b"".join(parts)
    while len(blob) < BIG:
        blob += _corpus.generate("csv", BIG - len(blob), seed + 4)
    return blob[:BIG]


def grade(runner, scratch, seed, sheet):
    streams = {}

    def stream(name, data):
        streams[name] = write_stream(scratch, name, data)
        return streams[name]

    # ---------------------------------------------------------------- framing
    # Cheapest and most diagnostic first: small payloads, where the fixed cost
    # of a frame is the whole story.
    total_in = 0
    total_out = 0
    failures = []
    for name, payload in TINY:
        path = stream("tiny_%s" % (name,), payload)
        total_in += len(payload)
        compressed = runner.call("tiny_%s_c" % (name,), "compress", path)
        if not call_ok(compressed):
            failures.append("%s: %s" % (name, why_not(compressed)))
            continue
        total_out += file_size(compressed["output"])
        back = runner.call("tiny_%s_d" % (name,), "decompress", compressed["output"])
        if not call_ok(back):
            failures.append("%s: %s" % (name, why_not(back)))
        elif not same_bytes(path, back["output"]):
            failures.append("%s: did not round-trip" % (name,))
    allowance = total_in + FRAME_ALLOWANCE * len(TINY)
    if failures:
        sheet.add("framing", "framing.small_frames", 0.0, "; ".join(failures[:3])[:200])
    else:
        sheet.add(
            "framing",
            "framing.small_frames",
            1.0 if total_out <= allowance else 0.0,
            "%d payload bytes became %d frame bytes across %d frames (allowance %d)"
            % (total_in, total_out, len(TINY), allowance),
        )

    for label, payload, bound in (
        ("repetitive", SMALL_REPETITIVE, SMALL_REPETITIVE_BOUND),
        ("json_lines", SMALL_JSON, SMALL_JSON_BOUND),
    ):
        path = stream("small_%s" % (label,), payload)
        compressed = runner.call("small_%s_c" % (label,), "compress", path)
        back = None
        if call_ok(compressed):
            back = runner.call("small_%s_d" % (label,), "decompress", compressed["output"])
        if not call_ok(compressed) or not call_ok(back):
            sheet.add("framing", "framing.%s" % (label,), 0.0,
                      why_not(compressed if not call_ok(compressed) else back))
            continue
        if not same_bytes(path, back["output"]):
            sheet.add("framing", "framing.%s" % (label,), 0.0, "did not round-trip")
            continue
        size = file_size(compressed["output"])
        sheet.add(
            "framing",
            "framing.%s" % (label,),
            1.0 if size <= bound else 0.0,
            "%d bytes of compressible payload became %d (bound %d)"
            % (len(payload), size, bound),
        )

    # ------------------------------------------------------------- round trips
    profiles = ("logfmt", "csv", "jsonl", "binlog", "mixed", "opaque")
    for profile in profiles:
        stream(profile, _corpus.generate(profile, BIG, seed))
    stream("random", _corpus.generate("random", BIG, seed))
    stream("repeated", _corpus.repeated((seed % 251) + 1, BIG))
    stream("cycle", _corpus.alphabet_cycle(BIG))
    stream("edge", build_edge_stream(seed))

    roundtrip_set = list(profiles) + ["random", "repeated", "cycle", "edge"]
    frames = {}
    for name in roundtrip_set:
        compressed = runner.call("%s_c" % (name,), "compress", streams[name])
        if not call_ok(compressed):
            sheet.add("roundtrip", "roundtrip.%s" % (name,), 0.0,
                      "compress: %s" % (why_not(compressed),))
            continue
        frames[name] = compressed
        back = runner.call("%s_d" % (name,), "decompress", compressed["output"])
        if not call_ok(back):
            sheet.add("roundtrip", "roundtrip.%s" % (name,), 0.0,
                      "decompress: %s" % (why_not(back),))
            continue
        if same_bytes(streams[name], back["output"]):
            sheet.add("roundtrip", "roundtrip.%s" % (name,), 1.0,
                      "%d -> %d -> %d bytes" % (BIG, file_size(compressed["output"]), BIG))
        else:
            sheet.add("roundtrip", "roundtrip.%s" % (name,), 0.0,
                      "recovered %d bytes and they differ" % (file_size(back["output"]),))

    # ---------------------------------------------------------------- contract
    short = runner.call("logfmt_short_c", "compress", streams["logfmt"], short_reads=True)
    if call_ok(short):
        sheet.add("contract", "contract.short_reads", 1.0,
                  "%d reads, %d bytes consumed" % (short.get("reads", 0), short.get("bytes_in", 0)))
        if short.get("bytes_in") == BIG:
            sheet.add("contract", "contract.consumes_everything", 1.0, "")
        else:
            sheet.add("contract", "contract.consumes_everything", 0.0,
                      "read %s of %d bytes: a short read is not end of stream"
                      % (short.get("bytes_in"), BIG))
        if "logfmt" in frames and same_bytes(short["output"], frames["logfmt"]["output"]):
            sheet.add("contract", "contract.chunking_is_invisible", 1.0,
                      "identical frame under both read schedules")
        else:
            sheet.add("contract", "contract.chunking_is_invisible", 0.0,
                      "the frame changed when the source returned short reads: %d vs %d bytes"
                      % (file_size(short["output"]),
                         file_size(frames["logfmt"]["output"]) if "logfmt" in frames else -1))
    else:
        for name in ("contract.short_reads", "contract.consumes_everything",
                     "contract.chunking_is_invisible"):
            sheet.add("contract", name, 0.0, why_not(short))

    if "logfmt" in frames:
        compressed = frames["logfmt"]
        produced = file_size(compressed["output"])
        at_eof = compressed.get("output_at_eof", -1)
        need = int(produced * INCREMENTAL_FRACTION)
        sheet.add(
            "contract",
            "contract.emits_before_the_end",
            1.0 if at_eof >= need else 0.0,
            "%d of %d output bytes existed when the input ran out (need %d): a "
            "header written up front is not streaming" % (at_eof, produced, need),
        )
        decompressed = runner.results.get("logfmt_d", {})
        sheet.add(
            "contract",
            "contract.no_forbidden_access",
            1.0 if not compressed.get("violations") and not decompressed.get("violations") else 0.0,
            "; ".join(compressed.get("violations", []) + decompressed.get("violations", []))[:200],
        )
    else:
        sheet.add("contract", "contract.emits_before_the_end", 0.0, "no usable compress run")
        sheet.add("contract", "contract.no_forbidden_access", 0.0, "no usable compress run")

    # ------------------------------------------------------------------ memory
    for label, kind in (("compress", "_c"), ("decompress", "_d")):
        worst = 0
        worst_name = None
        missing = []
        for name in roundtrip_set:
            result = runner.results.get("%s%s" % (name, kind))
            if not result or not result.get("ok"):
                missing.append(name)
                continue
            if result.get("working", 0) > worst:
                worst = result["working"]
                worst_name = name
        if missing:
            sheet.add("memory", "memory.%s_working_set" % (label,), 0.0,
                      "no usable run for: %s" % (", ".join(missing[:4]),))
        else:
            sheet.add(
                "memory",
                "memory.%s_working_set" % (label,),
                1.0 if worst <= WORKING_BUDGET else 0.0,
                "worst %d B on %s, budget %d B" % (worst, worst_name, WORKING_BUDGET),
            )

    # The import footprint on its own is not worth a point: the shipping codec
    # already imports cheaply, and crediting that would be crediting the seed.
    # It is graded as half of a conjunction with a clean large round trip.
    residents = [
        result.get("resident", 0)
        for result in runner.results.values()
        if result.get("ok")
    ]
    pair = [runner.results.get("logfmt_c"), runner.results.get("logfmt_d")]
    if residents and all(call_ok(result) for result in pair):
        sheet.add(
            "memory",
            "memory.import_footprint",
            1.0 if max(residents) <= RESIDENT_BUDGET else 0.0,
            "worst import footprint %d B, budget %d B, with a clean %d KiB round trip"
            % (max(residents), RESIDENT_BUDGET, BIG // 1024),
        )
    else:
        sheet.add("memory", "memory.import_footprint", 0.0,
                  "no clean round trip to measure it against: %s"
                  % (why_not(pair[0] if not call_ok(pair[0]) else pair[1]),))

    huge_path = write_stream(scratch, "huge", _corpus.generate("logfmt", HUGE, seed + 9))
    huge = runner.call("huge_c", "compress", huge_path)
    small = runner.results.get("logfmt_c")
    if call_ok(huge) and small and small.get("ok"):
        drift = huge.get("working", 0) - small.get("working", 0)
        sheet.add(
            "memory",
            "memory.constant_in_stream_length",
            1.0 if drift <= MEMORY_DRIFT else 0.0,
            "%d B at %d KiB, %d B at %d KiB: drift %d B (allowed %d)"
            % (small.get("working", 0), BIG // 1024, huge.get("working", 0),
               HUGE // 1024, drift, MEMORY_DRIFT),
        )
    else:
        sheet.add("memory", "memory.constant_in_stream_length", 0.0, why_not(huge))

    # ------------------------------------------------------------------- ratio
    for profile, target in sorted(RATIO_TARGETS.items()):
        if profile not in frames:
            sheet.add("ratio", "ratio.%s" % (profile,), 0.0, "no usable compress run")
            continue
        achieved = file_size(frames[profile]["output"])
        baseline = _baseline.baseline_size_of_file(streams[profile])
        goal = target * baseline
        if achieved <= goal:
            earned = 1.0
        elif achieved >= baseline:
            earned = 0.0
        else:
            earned = (baseline - achieved) / float(baseline - goal)
        sheet.add(
            "ratio",
            "ratio.%s" % (profile,),
            earned,
            "%d bytes = %.4f of the shipping codec's %d (target %.2f, ratio %.4f)"
            % (achieved, achieved / float(baseline), baseline, target, achieved / float(BIG)),
        )

    # ----------------------------------------------------------------- ceiling
    if "opaque" in frames:
        achieved = file_size(frames["opaque"]["output"])
        baseline = _baseline.baseline_size_of_file(streams["opaque"])
        sheet.add(
            "ceiling",
            "ceiling.six_bit_payload",
            1.0 if achieved <= OPAQUE_CEILING * baseline else 0.0,
            "%d bytes = %.4f of the shipping codec's %d (ceiling %.2f)"
            % (achieved, achieved / float(baseline), baseline, OPAQUE_CEILING),
        )
    else:
        sheet.add("ceiling", "ceiling.six_bit_payload", 0.0, "no usable compress run")

    for name, bound, label in (
        ("random", expansion_bound(BIG), "expansion on incompressible input"),
        ("repeated", BIG // 100 + 64, "a stream of one repeated byte"),
        ("cycle", BIG // 10 + 64, "a stream that is perfectly order-1 predictable"),
    ):
        if name not in frames:
            sheet.add("ceiling", "ceiling.%s" % (name,), 0.0, "no usable compress run")
            continue
        achieved = file_size(frames[name]["output"])
        sheet.add(
            "ceiling",
            "ceiling.%s" % (name,),
            1.0 if achieved <= bound else 0.0,
            "%s: %d bytes, bound %d" % (label, achieved, bound),
        )

    # -------------------------------------------------------------- adaptivity
    first_half = _corpus.generate("logfmt", BIG // 2, seed + 11)
    second_half = _corpus.generate("binlog", BIG // 2, seed + 12)
    paths = {
        "seg_a": write_stream(scratch, "seg_a", first_half),
        "seg_b": write_stream(scratch, "seg_b", second_half),
        "seg_ab": write_stream(scratch, "seg_ab", first_half + second_half),
        "seg_ba": write_stream(scratch, "seg_ba", second_half + first_half),
    }
    sizes = {}
    usable = True
    for key, path in paths.items():
        result = runner.call("%s_c" % (key,), "compress", path)
        if not call_ok(result):
            usable = False
            sizes[key] = None
        else:
            sizes[key] = file_size(result["output"])
    if usable:
        apart = sizes["seg_a"] + sizes["seg_b"]
        for order in ("seg_ab", "seg_ba"):
            allowed = ADAPTIVITY_SLACK * apart
            sheet.add(
                "adaptivity",
                "adaptivity.%s" % ("forwards" if order == "seg_ab" else "backwards",),
                1.0 if sizes[order] <= allowed else 0.0,
                "joined %d vs %d apart (allowed %.0f): a model that stops learning "
                "pays for the second half twice" % (sizes[order], apart, allowed),
            )
    else:
        sheet.add("adaptivity", "adaptivity.forwards", 0.0, "no usable compress run")
        sheet.add("adaptivity", "adaptivity.backwards", 0.0, "no usable compress run")

    # -------------------------------------------------------------- robustness
    if "logfmt" in frames:
        with open(frames["logfmt"]["output"], "rb") as handle:
            good = handle.read()
    else:
        good = b""

    # Only damage to a frame the SUBMISSION produced is scored here. Rejecting
    # an empty input, a random blob or a bare magic is behaviour the shipping
    # codec already has and the visible suite already pins, so scoring it again
    # would pay twice for something the starting workspace does on day one.
    damaged = [
        ("truncated_%d" % (int(fraction * 100),),
         good[: int(len(good) * fraction)] if good else None)
        for fraction in (0.3, 0.6, 0.95)
    ]
    damaged.append(("last_byte_gone", good[:-1] if good else None))

    for name, payload in damaged:
        if payload is None:
            sheet.add("robustness", "robustness.%s" % (name,), 0.0,
                      "no usable frame of its own to damage")
            continue
        path = write_stream(scratch, "bad_%s" % (name,), payload)
        result = runner.call("bad_%s_d" % (name,), "decompress", path)
        if result.get("unrun"):
            sheet.add("robustness", "robustness.%s" % (name,), 0.0, "not run")
            continue
        if result.get("ok"):
            sheet.add("robustness", "robustness.%s" % (name,), 0.0,
                      "decompress returned normally on damaged input")
            continue
        if result.get("is_corrupt_stream"):
            sheet.add("robustness", "robustness.%s" % (name,), 1.0,
                      "raised %s" % (result.get("exception_type"),))
        else:
            sheet.add("robustness", "robustness.%s" % (name,), 0.0,
                      "raised %s, not CorruptStream" % (result.get("exception_type"),))

    # -------------------------------------------------------------- regression
    run_regression(runner, sheet)


def run_regression(runner, sheet):
    """The visible suite, from the grader's own pristine copy."""
    suite = os.path.join(HERE, "public_reference", "test_public.py")
    if not os.path.isfile(suite):
        sheet.add("regression", "regression.public_suite", 0.0, "the pristine copy is missing")
        return
    left = runner.remaining()
    if left <= 5:
        sheet.add("regression", "regression.public_suite", 0.0, "not run: out of time")
        return
    environment = dict(os.environ)
    environment["PYTHONPATH"] = runner.impl_root
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    junit = os.path.join(runner.scratch, "regression.xml")
    try:
        finished = subprocess.run(
            [sys.executable, "-m", "pytest", suite, "-q", "-p", "no:cacheprovider",
             "--rootdir=%s" % (HERE,), "--junitxml=%s" % (junit,)],
            cwd=os.path.join(HERE, "public_reference"),
            env=environment,
            timeout=min(180, max(5, left)),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.TimeoutExpired:
        sheet.add("regression", "regression.public_suite", 0.0, "the visible suite timed out")
        return
    except OSError as exc:
        sheet.add("regression", "regression.public_suite", 0.0, "could not run pytest: %s" % (exc,))
        return

    # Per-test granularity, not pass/fail. This category's ratio multiplies the
    # whole score, so a binary result would turn one broken visible test into a
    # cliff from a good submission to zero. Breaking existing behaviour should
    # cost proportionally, not annihilate.
    total, failed, names = parse_junit(junit)
    tail = ((finished.stdout or "").strip().splitlines() or [""])[-1]
    if not total:
        sheet.add("regression", "regression.public_suite", 0.0,
                  "the visible suite collected nothing: %s" % (tail[:160],))
        return
    passed = total - failed
    detail = "%d of %d visible tests pass" % (passed, total)
    if names:
        detail += " -- broken: %s" % (", ".join(names[:4]),)
    sheet.add("regression", "regression.public_suite", passed / float(total), detail[:220],
              points=1.0)


def parse_junit(path):
    """(tests, failures+errors, failing test names) from a JUnit report."""
    try:
        import xml.etree.ElementTree as elementtree

        root = elementtree.parse(path).getroot()
    except Exception:
        return 0, 0, []
    suites = [root] if root.tag == "testsuite" else list(root)
    total = 0
    broken = 0
    names = []
    for suite in suites:
        for case in suite.iter("testcase"):
            total += 1
            for child in case:
                if child.tag in ("failure", "error"):
                    broken += 1
                    names.append(case.get("name", "?"))
                    break
    return total, broken, names


# ----------------------------------------------------------------------- scoring


def score_sheet(sheet):
    grouped = sheet.by_category()
    rows = []
    total = 0.0
    multiplier = 1.0
    for name, weight in CATEGORIES:
        checks = grouped.get(name, [])
        possible = sum(check["points"] for check in checks)
        earned = sum(check["earned"] for check in checks)
        fraction = (earned / possible) if possible else 0.0
        if name == "regression":
            multiplier = fraction
        else:
            total += weight * fraction
        rows.append(
            {"name": name, "weight": weight, "fraction": fraction,
             "earned": earned, "possible": possible, "checks": checks}
        )
    return rows, max(0.0, min(1.0, total * multiplier)), multiplier


def print_report(rows, total, multiplier, seed, runner):
    for row in rows:
        marker = "x" if row["fraction"] < 1.0 else " "
        print("%s %-12s weight %.2f  %6.1f%%  (%.2f/%.0f)" % (
            marker, row["name"], row["weight"], 100 * row["fraction"],
            row["earned"], row["possible"]))
        for check in row["checks"]:
            if check["earned"] >= check["points"]:
                mark = "PASS"
            elif check["earned"] > 0:
                mark = "PART"
            else:
                mark = "FAIL"
            print("      [%s] %-36s %s" % (mark, check["name"], check["detail"][:150]))
    print()
    print("regression multiplier: %.4f" % (multiplier,))
    print("codec calls: %d in %.1fs of child time" % (runner.calls, runner.seconds))
    print("seed: %s" % (seed,))


def main():
    clear_stale_rewards()
    publish(0.0, {"stage": "starting", "passed": False, "threshold": PASS_THRESHOLD})

    seed_text = os.environ.get("GRADER_SEED") or str(int.from_bytes(os.urandom(4), "big"))
    try:
        seed = int(seed_text)
    except ValueError:
        seed = abs(hash(seed_text)) % (1 << 31)

    print("=" * 72)
    print("zipstream verifier")
    print("implementation root: %s" % (IMPL_ROOT,))
    print("seed: %d   (set GRADER_SEED to reproduce)" % (seed,))
    print("budgets: working %d B, import %d B, streams %d B" % (
        WORKING_BUDGET, RESIDENT_BUDGET, BIG))
    print("=" * 72)
    print()

    scratch = tempfile.mkdtemp(prefix="zipstream-grade-")
    sheet = Sheet()
    report = {"seed": seed, "threshold": PASS_THRESHOLD}
    total = 0.0

    try:
        collected = _integrity.collect(IMPL_ROOT, scratch)
        findings, source_bytes = _integrity.scan(collected)
        report["source_bytes"] = source_bytes
        report["integrity"] = findings
        print("collected %d file(s), %d bytes of Python" % (len(collected), source_bytes))
        if findings:
            print()
            print("INTEGRITY VIOLATION -- the score is zero regardless of behaviour:")
            for finding in findings:
                print("  * %s" % (finding,))
            report["passed"] = False
            report["categories"] = []
            print()
            print("SCORE: 0.0000")
            print("THRESHOLD: %.2f" % (PASS_THRESHOLD,))
            print("RESULT: FAIL")
            publish(0.0, report)
            return 1

        runner = Runner(os.path.join(scratch, "impl"), scratch,
                        time.monotonic() + DEADLINE_SECONDS)
        os.makedirs(runner.impl_root, exist_ok=True)
        shutil.move(os.path.join(scratch, _integrity.PACKAGE),
                    os.path.join(runner.impl_root, _integrity.PACKAGE))
        print("grading from %s" % (runner.impl_root,))
        print()

        grade(runner, scratch, seed, sheet)
        rows, total, multiplier = score_sheet(sheet)
        print_report(rows, total, multiplier, seed, runner)
        report["categories"] = [
            {k: row[k] for k in ("name", "weight", "fraction", "earned", "possible", "checks")}
            for row in rows
        ]
        report["multiplier"] = multiplier
    except BaseException as exc:  # noqa: BLE001 - a dead grader must still publish
        total = 0.0
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()[-4000:]
        print("GRADER ERROR: %s" % (report["error"],))
        print(report["traceback"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    total = round(total, 6)
    passed = total >= PASS_THRESHOLD
    report["passed"] = passed

    print()
    print("=" * 72)
    print("SCORE: %.4f" % (total,))
    print("THRESHOLD: %.2f" % (PASS_THRESHOLD,))
    print("RESULT: %s" % ("PASS" if passed else "FAIL",))
    print("=" * 72)

    written = publish(total, report)
    print("reward written to %d location(s): %s" % (len(written), ", ".join(written[:4])))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        print("FATAL: %s" % (exc,))
        traceback.print_exc()
        publish(0.0, {"error": str(exc), "passed": False})
        raise SystemExit(2)
