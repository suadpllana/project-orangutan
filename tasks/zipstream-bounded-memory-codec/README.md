# zipstream-bounded-memory-codec

Replace a working-but-wrong-shaped telemetry codec with one that streams. Four
requirements hold at once and each rules out the cheap way of getting the
others: the source is one-pass, non-seekable and of unknown length and the sink
cannot be rewound, so there is no second pass to build a global code table
with; the traced working set must stay under 384 KiB against 512 KiB streams,
so the stream cannot be buffered to fake one; five per-profile size targets are
measured against the shipping codec on the same bytes, so neither correctness
nor frugality alone is enough; and four ceilings — expansion, six-bit payloads,
a repeated byte, a byte cycle — are graded as hard as the targets, so a model
that wins one profile by collapsing everywhere else does not pass.

| | |
| --- | --- |
| collection family | Algorithmic optimization |
| task family | `performance` |
| verifier family | `optimization` |
| expert estimate | 7 hours |
| network | `none` (all phases except the image build) |
| graded checks | 38 across 9 categories |
| pass threshold | 0.88 (`[verifier] pass_threshold`) |
| oracle | **1.0000**, PASS, 48 codec calls, 151 s of child time on a 2.8 GHz core |
| nop (untouched `/app`) | **0.0000**, FAIL |
| nothing is timed | every graded quantity is a byte count or a `tracemalloc` figure |

## Layout

```
draft.yaml                 every draft field - the single source of the prose
submission.md              generated; paste-ready render of draft.yaml
bundle/                    exactly what gets zipped and uploaded
  task.toml                [metadata] [agent] [verifier] [environment]
  instruction.md           the problem statement + the normative specification
  environment/             the build context; COPY . /app/
    Dockerfile             python:3.11-slim + pytest; builds /app
    zipstream/             the working v1 codec: order-0 static Huffman
    public_tests/          23 visible tests - the public half of the verifier
    samples/               five frozen streams, one per profile
    SPEC.md                the spec again, in the tree
    README.md              orientation + a worked example of measuring yourself
    selfcheck.py           build-time assertion; deleted from the image
  tests/                   sealed
    test.sh                the verifier entrypoint declared in task.toml
    grade.py               collection, integrity scan, measurement plan, reward
    child_codec.py         one codec call, in a process of its own
    _harness.py            the stream contract, the module blocker, the audit hook
    _corpus.py             the sealed generator: six profiles, fresh vocabulary
    _baseline.py           what the v1 codec would have produced, computed exactly
    _integrity.py          collection into a grader-owned tree + the tokenised scan
    public_reference/      the grader's pristine copy of the visible suite
    samples/               the samples again, for that copy
  solution/
    solve.sh               the entrypoint the oracle runs
    reference/zipstream/   the reference implementation (29,088 bytes, 8 modules)
```

## Reproducing the oracle & nop stage locally

```bash
cd bundle

# oracle: install the reference into a copy of /app, then grade it
mkdir -p /tmp/app /tmp/logs && cp -r environment/zipstream environment/public_tests environment/samples /tmp/app/
IMPL_ROOT=/tmp/app bash solution/solve.sh
IMPL_ROOT=/tmp/app LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 1.0000, PASS

# nop: grade the untouched starting state
mkdir -p /tmp/nop && cp -r environment/zipstream environment/public_tests environment/samples /tmp/nop/
IMPL_ROOT=/tmp/nop LOG_DIR=/tmp/logs bash tests/test.sh    # SCORE: 0.0000, FAIL

docker build -t zipstream-task environment/   # unverified here: no docker daemon

# a local run publishes the reward into every candidate directory, including
# this one; clear them before building the archive
find . \( -name __pycache__ -o -name verifier \) -type d -prune -exec rm -rf {} +
rm -f reward.* score.* tests/reward.* tests/score.* tests/junit.xml
```

`tools/check_bundle.py` fails the bundle if any of those are still there, so
the cleanup is checked rather than remembered.

The image build has **not** been run in this repository's authoring
environment. `environment/selfcheck.py` — the build-time assertion that the
seed both works and is still inadequate — was run directly instead and passes,
as does the visible suite (23/23). Build the image once before submitting.

## Attempt 1: "your verifier completed without writing a reward file"

The first upload cleared **Bundle structure** and **Similarity screening** and
failed **Oracle & nop** with:

> Your verifier completed without writing a reward file
> (`verifier/reward.txt` or `reward.json`) — every trial must produce one.

The nop trial cannot have been the one that failed: it grades in 13 s and ends
by publishing `0.000000`, reproducibly. The oracle trial is the long one, and
two things about it combined into a verifier that could end with no reward file
at all:

* **The run was slow enough to be killable.** `task.toml` claimed 87 s of child
  time, measured on the authoring host. On an ordinary 2.8 GHz core the same
  suite took **264 s** — a 3x spread between two unremarkable machines, against
  a 1000 s verifier limit. A grading host at the slow end of that spread lands
  on the limit, and a killed container copies nothing out.
* **The 0.0 floor was being deleted.** `test.sh` wrote a floor before grading,
  which is right; then `grade.py` started by *unlinking* every stale reward
  artefact — including that floor — before writing its own. Any kill after that
  unlink left the trial with no reward file anywhere. The one defence against a
  kill was being removed by the thing it was defending.

Both are fixed, and the fix for each is structural rather than a bigger number:

* **Nothing deletes a reward file any more.** A stale value is *overwritten in
  place*, so there is no instant in the trial without one. The floor is now
  written in POSIX shell rather than by a Python heredoc, so it does not need
  an interpreter; a `trap` re-asserts it on `EXIT`, `TERM`, `INT` and `HUP`;
  the grader publishes again after every scoring category, so a kill reports a
  partial score instead of nothing; and `test.sh` parses `SCORE:` back out of
  the grader's own report and republishes it from the shell, so the reward does
  not depend on the grader's writer either. Every location is written under
  both names and in a `verifier/` subdirectory, since the platform's message
  names that path.
* **The run is 1.7x shorter.** Every graded call runs under `tracemalloc`,
  which costs about **14x** on an allocation-heavy codec — the verifier's
  runtime is essentially proportional to the number of graded bytes. The memory
  proof needs large streams and keeps them (512 KiB and 768 KiB); the
  scale-free properties — a ratio against the shipping codec on the same bytes,
  a bound that is a multiple of the input length — measure the same thing at
  192 KiB and now use it. 264 s became **151 s**, and the grader's own deadline
  came down from 780 s to 600 s, so 600 + 120 (one call's cap) = 720 s is
  still comfortably inside the 1000 s the verifier declares.

Verified three ways after the change: a normal run writes `1.000000`, a grader
exception writes `0.0000` with the traceback in the report, and `SIGKILL` 20 s
in leaves `0.090000` — the categories that had finished — in both `reward.txt`
and `verifier/reward.txt`.

## Design notes

**Nothing is timed.** Every graded quantity is a byte count on disk or a
`tracemalloc` figure. Both are exactly reproducible for a given submission and
seed, so a score does not move with the load on the grading host. The only
wall-clock numbers are safety limits — 120 s per codec call, 600 s for the
whole run, 1000 s for the verifier — and they exist so a hang costs one
measurement rather than the report. The reference averages 3.1 s per call.

That was checked rather than assumed: the whole suite pinned to a single core
with `taskset -c 0` still scores **1.0000**, which is what `cpus = 1` in
`task.toml` claims. The grader runs one child process at a time and never
threads, so it is a single-core workload by construction.

**Targets are self-calibrating.** Graded streams are synthesised at grading
time from the run seed, so an absolute ratio target would drift. Every target
is instead a fraction of what the shipping v1 codec produces *on the same
bytes*, which `_baseline.py` computes exactly from the byte histogram. Across
six seeds the reference's fraction stays inside a 2.5-point band on every
profile: logfmt 0.384-0.409, csv 0.427-0.442, jsonl 0.359-0.373, binlog
0.863-0.869, mixed 0.572-0.577, and the `opaque` ceiling 1.0150-1.0151. The
targets are 0.52, 0.56, 0.50, 0.92 and 0.65, so the reference sits 21-28%
inside on the text profiles, 11% on mixed and 6% on binlog — the tightest of
the five, which is why `binlog` is one of the streams graded at 512 KiB.

**Four structural defences**, each a property of the harness rather than a test
somebody remembered to write:

| defence | what it kills |
| --- | --- |
| compress and decompress run in **different processes** | keeping the payload in a global and returning a receipt |
| the source and sink expose **one method each** | any two-pass design; `read()` with no size; rewinding |
| only `zipstream/**.py` is copied into a **grader-owned tree** | `conftest.py`, `sitecustomize.py`, `pytest.ini`, edited visible tests |
| compression libraries **unimportable** before the submission loads | `zlib.compress`, and `codecs.encode(x, "zlib_codec")` with it |

Measured landing points, all through the real entrypoint:

| submission | score | why |
| --- | --- | --- |
| the reference | **1.0000** | — |
| streams correctly, models nothing (LZ off) | **0.7332** | ratio 42.6%, framing 33%, ceiling 50% |
| keeps the payload in a module global | **0.0000** | decompression is a different process |
| writes the payload to a side file | **0.0000** | the audit hook denies the write |
| a syntax error | **0.0000** | reported per check, reward file still written |
| the untouched starting workspace | **0.0000** | every category |

The LZ-disabled variant is the interesting one: it satisfies the stream
protocol, the memory budget, adaptivity and robustness in full and still lands
0.15 below the threshold, because doing the streaming work without the
modelling work is not the task.

### Three bugs the suite caught, all in the reference

**A frame truncated by exactly one byte was accepted as complete.** The bit
reader invents zero padding past the end of the source so the final symbol can
be peeked; that padded `0x00` is indistinguishable from the end-of-frame tag.
The reference passed `robustness.last_byte_gone` by luck of bit alignment while
the LZ-disabled variant failed it, which is what exposed it — the check was
right and the reference was wrong. `BitReader` now tracks how many bits in its
accumulator came from the source, and the structural reads refuse to be served
invented bytes. Re-verified over 442 truncation points: all detected.

**An index overrun in the match finder** when a candidate reached the end of
the available window, on the very first run against real data.

**Rebuilding code tables by allocation** kept two full sets of five tables
alive at hand-over and cost about 35 KiB of a 384 KiB budget. Tables are now
rewritten in place — which is itself the kind of decision the memory bound is
there to force.

### Getting the nop to its floor

The first measurement put the untouched workspace at **0.1275**. Three sources
of free credit, all authoring bugs rather than agent exploits:

* **`memory.import_footprint` had no teeth.** The shipping codec already
  imports cheaply, so the check credited the seed for something it was born
  with. It is now one half of a conjunction with a clean 512 KiB round trip.
* **Four of eight per-frame bounds were passable by the stored-block path.** An
  empty frame really is cheap for the v1 container, and no bound tight enough
  to fail its 9 bytes would leave an honest design room. The category now
  scores the seven small frames **in aggregate** — total output against total
  input plus 24 bytes a frame, which the seed misses by 2.1× — plus two small
  payloads that genuinely compress, where its 256-byte table is fatal.
* **Three robustness checks were free**, and worse, the truncation checks
  silently vanished from the denominator when no frame could be produced.
  Rejecting an empty input or a random blob is behaviour the seed already has
  and the visible suite already pins; scoring it again paid twice. Robustness
  now grades only damage to frames the submission itself produced, and the
  denominator is fixed whether or not a frame exists.

Everything else is zero because **the memory budget is a precondition for every
measurement**: the seed's working set is 1.0-1.6 MB against a 393,216 B budget on
every graded stream, so no check that depends on a call survives. That is
deliberate and stated in `instruction.md` — the seed round-trips correctly, and
crediting correctness would be crediting the starting workspace.

### A design choice worth recording

The memory bound started as a single `tracemalloc` peak. That has a hole: a
codec can allocate its buffer at *import* time, where a peak measured from the
call's start never sees it. Measuring the absolute peak instead closes the hole
but charges every submission for the ~300 KiB of code objects the interpreter
allocates while importing the standard library, which is noise, not design.

The resolution is two figures rather than one — an import footprint and a
working set, both bounded at 384 KiB — plus graded streams of 512 KiB and
768 KiB, which are larger than either. Neither budget can absorb a stream, and
the common stdlib modules are pre-imported in the child before tracing starts,
so nobody is charged for `heapq`.

The import footprint needed one more correction, found while investigating the
failed upload. It was charging every submission for **compiling its own
source**: a module imported from a `.py` leaves roughly eight times the source
size alive that the same module imported from a `.pyc` does, so the 28 KiB
reference was paying 225 KiB of a 384 KiB budget for nothing but the length of
its own text, and a submission using the 96 KiB the spec allows could not have
fitted whatever it did. The grader now byte-compiles the tree it owns once,
before any call is measured; the reference's import footprint went from
345,633 B to 121,143 B and the figure now measures what the spec says it
measures.
