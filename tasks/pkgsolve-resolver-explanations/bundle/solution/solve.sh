#!/usr/bin/env bash
# Reference solution: install the finished `pkgsolve` package into /app.
#
# The oracle run executes exactly this script and must then reach full reward.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${IMPL_ROOT:-${APP_DIR:-/app}}"

SRC=""
for candidate in "$HERE/reference" /solution/reference /app/solution/reference "$HERE/../solution/reference"; do
    if [ -d "$candidate/pkgsolve" ]; then
        SRC="$candidate"
        break
    fi
done

if [ -z "$SRC" ]; then
    echo "FATAL: reference sources not found next to $HERE" >&2
    exit 1
fi

rm -rf "$TARGET/pkgsolve"
mkdir -p "$TARGET/pkgsolve"
cp "$SRC/pkgsolve/"*.py "$TARGET/pkgsolve/"
find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "installed reference implementation into $TARGET/pkgsolve"

# Smoke test: the decision order, the registry budget and the explanation must
# all work here, so a broken drop-in fails in the oracle step rather than
# silently in the verifier.
cd "$TARGET"
python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.environ.get("IMPL_ROOT", os.environ.get("APP_DIR", "/app")))
from pkgsolve import InMemoryRegistry, Registry, Requirement, Unsolvable, Version, resolve


class Counting(Registry):
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def versions(self, package):
        self.calls += 1
        return self.inner.versions(package)

    def dependencies(self, package, version):
        self.calls += 1
        return self.inner.dependencies(package, version)


# Alphabetical decision order: deciding `zz` first would give {aa 2, zz 2},
# which is valid and wrong.
ordered = InMemoryRegistry({
    "aa": {"1.0.0": ["zz *"], "2.0.0": ["zz *"], "3.0.0": ["zz <=1.0.0"]},
    "zz": {"1.0.0": [], "2.0.0": []},
})
answer = resolve(ordered, [Requirement.parse("aa *"), Requirement.parse("zz *")])
assert answer == {"aa": Version(3, 0, 0), "zz": Version(1, 0, 0)}, answer

# A hopeless root must not be paid for once per release of an unrelated one.
spec = {"aa": {"%d.0.0" % major: ["aa-branch%02d *" % major] for major in range(1, 41)}}
for major in range(1, 41):
    spec["aa-branch%02d" % major] = {"1.0.0": [], "2.0.0": []}
spec["mm"] = {"%d.0.0" % major: ["ghost *"] for major in range(1, 6)}
counting = Counting(InMemoryRegistry(spec))
try:
    resolve(counting, [Requirement.parse("aa *"), Requirement.parse("mm *")])
except Unsolvable as error:
    assert error.causes, "the failure must be explained"
    assert counting.calls < 60, "spent %d registry calls; the search is not pruning" % (
        counting.calls,
    )
else:
    raise SystemExit("that manifest has no solution")

print("smoke test OK (%d registry calls on the pruning case)" % (counting.calls,))
PY
