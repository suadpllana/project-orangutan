# zipstream

The compression codec the fleet telemetry agent uses to ship log and metric
streams back to the collector.

```
zipstream/          the package
  __init__.py       public API + byte-oriented convenience wrappers
  codec.py          compress / decompress
  huffman.py        canonical Huffman code construction
  bitio.py          MSB-first bit packing
  errors.py         ZipstreamError, CorruptStream, StreamError
public_tests/       the visible suite -- what must not regress
samples/            one frozen sample per data profile, for local measurement
SPEC.md             the specification you are working to
```

## Running things

```bash
python -m pytest public_tests -q
```

## Measuring yourself

The samples are real instances of the five profiles the collector sees. They
are frozen; the streams you are graded on are generated fresh with a different
vocabulary, so treat these as a shape to design against rather than a corpus to
fit.

```python
import os, tracemalloc, zipstream

data = open("samples/logfmt.bin", "rb").read()

class Reader:                       # what the grader passes: read(n) and nothing else
    def __init__(self, blob): self.blob, self.at = blob, 0
    def read(self, n):
        assert n > 0
        chunk = self.blob[self.at:self.at + n]; self.at += len(chunk); return chunk

class Writer:
    def __init__(self): self.n = 0
    def write(self, payload): self.n += len(payload); return len(payload)

tracemalloc.start()
tracemalloc.reset_peak()
base = tracemalloc.get_traced_memory()[0]
sink = Writer()
zipstream.compress(Reader(data), sink)
peak = tracemalloc.get_traced_memory()[1]

print("ratio  %.4f" % (sink.n / len(data),))
print("working set %d B  (budget %d)" % (peak - base, 384 * 1024))
```

That is close to what the grader does, with two differences that matter: it
starts tracing *before* importing the package, so anything you allocate at
module level counts; and it runs compression and decompression in separate
processes, so nothing survives between them.

## The current design, and why it is the wrong one

`codec.py` reads the whole stream, counts byte frequencies, builds one
canonical Huffman code, writes the 256-byte table of code lengths, and then
writes the payload. Three consequences, all of them measured in `SPEC.md`:

* it cannot emit anything until it has seen everything, so its memory grows
  with the stream;
* the table costs 265 bytes on every frame, however small the frame is;
* an order-0 model cannot see that `host=` follows a space, that timestamps
  climb slowly, or that the same field names recur on every line.
