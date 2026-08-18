<!-- The specification, as shipped in the image. This is the same text as the
     second half of the task instructions; it lives here so it is readable from
     inside /app. Where the two differ, they do not: they are one file split. -->

# zipstream v2 specification

## 1. What you are replacing

`/app` contains:

```
zipstream/__init__.py     the public API and the byte-oriented convenience wrappers
zipstream/codec.py        compress / decompress -- the part that has to change
zipstream/huffman.py      canonical Huffman code construction
zipstream/bitio.py        MSB-first bit packing over an in-memory buffer
zipstream/errors.py       ZipstreamError, CorruptStream, StreamError
public_tests/             the visible suite
samples/                  five frozen sample streams, one per data profile
SPEC.md                   this specification, again, in the tree
```

You may rewrite, delete or add to any of it. Every file you add MUST live
inside `/app/zipstream/`; nothing outside that directory is collected, so a
module you drop beside it will not exist when the grader runs.

The public API does not change:

```python
zipstream.compress(source, sink)     -> None
zipstream.decompress(source, sink)   -> None
zipstream.compress_bytes(data)       -> bytes
zipstream.decompress_bytes(frame)    -> bytes
zipstream.CorruptStream, zipstream.ZipstreamError, zipstream.StreamError
```

`compress_bytes` and `decompress_bytes` are conveniences for your own testing.
The grader only ever calls `compress` and `decompress`.

## 2. The stream protocol

### 2.1 The source

`source` has exactly one method, `read(size)`.

* `size` is always a positive integer. There is no `read()`, no `read(-1)`, and
  calling either raises — **the length of the stream is not knowable in
  advance**, and nothing about it is discoverable except by reading to the end.
* `read` returns **at most** `size` bytes. It MAY return fewer than `size`
  without that meaning anything is wrong; real sockets do this constantly. Only
  `b""` means end of stream. A codec that treats a short read as end of stream
  silently truncates its input, and the graded source deliberately returns
  short reads on part of its schedule.
* The source has **no other attributes**. `seek`, `tell`, `getvalue`, `fileno`,
  `__len__` and everything else raise `AttributeError`, and the attempt is
  recorded against you. There is no rewind.

### 2.2 The sink

`sink` has exactly one method, `write(payload)`, which accepts a bytes-like
object and returns the number of bytes taken. It has no other attributes: you
cannot seek back to patch a header you wrote earlier, and you cannot read back
what you wrote.

`compress` MUST emit output **as it goes**. By the moment the source first
returns `b""`, at least **25%** of the total frame MUST already have been
written to the sink. Writing a header up front and the rest at the end does not
satisfy this; the measurement is of bytes delivered, not of the first call.

### 2.3 Determinism

The frame `compress` produces MUST be a function of the input bytes alone.
Feeding the same payload through a source that returns different chunk sizes
MUST produce a **byte-identical** frame. The graded run compresses the same
stream twice, once with a well-behaved source and once with one that returns
short reads, and compares the two frames byte for byte.

Nothing else may influence the output: not the clock, not the environment, not
a random seed, not the process id.

## 3. The frame

* Every frame MUST begin with the two ASCII bytes `ZS`. Nothing else about the
  container is prescribed — the format inside it is entirely yours.
* `decompress` MUST reproduce the compressed bytes exactly, for any input at
  all, including empty input, single bytes, binary data, and incompressible
  data.
* Frames MUST be small. Across the seven small payloads the grader sends —
  0, 1, 1, 3, 7, 36 and 256 bytes, 304 bytes in total — the sum of the frame
  sizes MUST be at most **the total payload size plus 24 bytes per frame**. The
  shipping codec spends 1113 bytes on those seven against an allowance of 472 --
  2.36x over -- because it writes a 256-byte code table into every one of them.

## 4. Memory

This is the constraint that shapes the design. The device has a few hundred
kilobytes to spare and the streams are megabytes.

Each call runs in a fresh interpreter with `tracemalloc` started **before**
`zipstream` is imported. The package is byte-compiled once, before any call is
measured, so the cost of compiling your source is not charged to you and the
figures below do not depend on how many bytes of Python you wrote. Two figures
are taken:

* **import footprint** — traced bytes alive at the moment your entry point is
  called. MUST be under **393,216 bytes (384 KiB)**.
* **working set** — the peak traced bytes during the call, above that
  baseline. MUST be under **393,216 bytes (384 KiB)**.

Both apply to `compress` and to `decompress`, and to **every** graded stream:
the figure that is scored is the worst one across all of them. The graded
streams run from 192 KiB to 768 KiB, and the ones the budget is decided on are
512 KiB and 768 KiB, so there is no arrangement of the two budgets that lets
you hold a stream: buffering it during the call blows the working set, and
pre-allocating a buffer at import time blows the import footprint.

The working set MUST also be **independent of the length of the stream**: the
figure measured on the 768 KiB stream may exceed the figure measured on the
512 KiB stream by no more than **40,960 bytes**. That is 16% of the extra
quarter-megabyte, so a working set that grows with the stream at any real rate
fails it.

Two practical notes, because the measurement is exact and it is easy to be
surprised by it:

* `tracemalloc` counts transient allocations too. `array("i", [0]) * 65536`
  allocates a 256 KiB array; `[0] * 65536` allocates a 512 KiB list first.
* The measurement starts before your import, so a table you build at module
  level is counted in the import footprint, not forgiven.
* These modules are already loaded and cost you nothing: `array`, `bisect`,
  `collections`, `functools`, `heapq`, `io`, `itertools`, `math`, `operator`,
  `string`, `struct`, `types`.

**The memory budget is a precondition for every other measurement.** A call
that exceeds either figure produces no usable result, so every check that
depends on it scores zero — including the round-trip checks. This is
deliberate: the code in `/app` already round-trips correctly, and crediting
that would be crediting the starting workspace rather than your work.

## 5. Compression

The graded streams are synthesised telemetry in six profiles, 192 KiB to
512 KiB of each. Five of them carry a target. Each target is expressed as a
fraction of what the **shipping v1 codec** produces on that same stream,
computed by the grader on the same bytes, so the bar does not move with the
data:

| profile | what it is | target |
| --- | --- | --- |
| `logfmt` | `ts=… host=… svc=… lvl=INFO key=value msg="…"` lines | **0.52** |
| `csv` | `ts,series,value,count,tag` rows, mostly numeric | **0.56** |
| `jsonl` | one JSON object per line, repeated key names, nested metrics | **0.50** |
| `binlog` | a length-prefixed binary record format: varints and IEEE doubles | **0.92** |
| `mixed` | five segments, one per profile, concatenated | **0.65** |

Reaching a target earns the full point for that stream. Missing it earns
partial credit, interpolated linearly from the shipping codec's own size (zero)
to the target (one), so progress is always worth something.

`/app/samples/` holds one frozen sample of each profile so you can measure
yourself locally. **The graded streams are generated fresh on every run with a
different vocabulary** — different host names, service names, field names,
message words and series identifiers — so a dictionary or frequency table
trained on the samples transfers much less well than it appears to.

Two small payloads are graded the same way: a 200-byte prefix of a repeated
38-byte logfmt record MUST come back at 100 bytes or less, and a 400-byte prefix
of a repeated 61-byte JSON line at 260 bytes or less. Both are well inside what the container from
§3 allows; they are here because a codec that only performs on megabytes is not
useful to a collector that sends records.

## 6. Ceilings — what must not happen

Every bound above says "smaller". These say "not bigger", and they are graded
just as hard, because the cheap way to win a ratio target is a model that
falls apart on everything else.

* **Expansion.** For an input of `n` bytes the frame MUST be at most
  `n + 64 + n // 64` bytes. Graded on 192 KiB of incompressible random data.
* **Six-bit payloads.** On the `opaque` profile — base64 payload lines, which
  carry six bits of information in every eight-bit byte — the frame MUST be at
  most **1.04×** what the shipping codec produces. A match finder that gives up
  and a model that fragments both fail here, and so does anything that assumes
  its ratio target implies general competence.
* **A stream of one repeated byte** (192 KiB of it) MUST compress to at most
  `n // 100 + 64` bytes. Note what this rules out: a pure Huffman coder cannot
  spend less than one bit per symbol, which is `n // 8`, eight times over
  budget. Getting under it requires run-length coding, matches, or an
  arithmetic coder.
* **A stream cycling through all 256 byte values** MUST compress to at most
  `n // 10 + 64` bytes. It is perfectly predictable given one byte of context
  and perfectly flat without it.

## 7. Adaptivity

The model MUST keep learning for the whole stream. Let `A` be 96 KiB of
`logfmt` and `B` be 96 KiB of `binlog`. Compressing `A` and `B` separately
gives two sizes; compressing `A + B` as one stream, or `B + A`, MUST produce at
most **1.05×** their sum.

A model that trains on the first part of a stream and then freezes pays for the
second part at the wrong statistics and fails this. So does a codec that picks
one global table. The shipping codec comes in at 1.12×.

## 8. Errors

`decompress` MUST raise `zipstream.CorruptStream` — not return short output,
not raise something else, not hang — when the frame ends before the payload
does. It is graded on your own frames truncated at 30%, 60%, 95% and at one
byte short of complete.

Detecting damage *inside* an otherwise complete frame is **not** required: no
checksum is asked for, and a flipped bit in the middle of a frame may decode to
anything. What is required is that a frame which stops early is reported rather
than silently accepted as complete.

`CorruptStream` MUST remain a subclass of `ZipstreamError`, which MUST remain a
subclass of `Exception`.

## 9. What is out of scope

* **Speed.** Nothing in the grade is a wall-clock measurement. Every budget is
  a byte count or a traced-allocation figure, so the score does not move with
  the load on the grading host. There is a 120-second cap per call and a
  780-second deadline for the whole run purely so a hang cannot cost the
  report; the reference solution uses about three seconds per call.
* **Concurrency.** `compress` and `decompress` are called one at a time, from
  one thread. Nothing needs to be re-entrant or thread-safe.
* **Damage detection inside a frame** — see §8.
* **Compatibility with v1 frames.** Your decompressor only ever sees frames
  your compressor wrote. You do not need to read the old format.
* **Interoperability between runs.** Compression and decompression happen in
  different processes, but always with the same version of your code.

## 10. Implementation constraints

* **Standard library only, and no compression libraries.** `zlib`, `gzip`,
  `bz2`, `lzma`, `zipfile`, `tarfile` and every third-party equivalent are made
  unimportable in the grading process, along with `ctypes`, `subprocess`,
  `multiprocessing`, `socket` and `tracemalloc`. Naming any of them in your
  source is an integrity violation and scores zero on its own. Model the data
  yourself; that is the task.
* **Every file you add or change MUST live inside `/app/zipstream/`.** Only
  `zipstream/**.py` is copied into the tree the grader runs from. A
  `conftest.py`, `sitecustomize.py` or `pytest.ini` anywhere is ignored, and a
  `conftest.py` inside the package is dropped.
* **The package MUST be at most 96 KiB of Python in total**, across every file.
  The reference solution is about 28 KiB. The cap exists so a static dictionary
  cannot be scaled up indefinitely, not to make you count characters.
* **No filesystem writes, no sockets, no subprocesses** during a call. An audit
  hook enforces this, and the working directory is checked afterwards.
  Compression and decompression run in separate processes, so state left in a
  module global does not survive between them.
* **Do not consult the environment, the process tree, the call stack, the
  command line, or test-runner state** to decide how to behave. The grader
  tokenises your source and looks for it, and finding it scores zero.
* No network. There is none.
