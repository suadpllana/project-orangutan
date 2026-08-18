"""Run one named case and print a canonical line, for the hash-seed test.

The parent starts this twice with different PYTHONHASHSEED values and compares
the output byte for byte, so everything printed here is sorted.
"""

from __future__ import annotations

import sys

from _support import determinism_case, format_solution, sealed_registry
from pkgsolve import Unsolvable, resolve


def main():
    universe, roots = determinism_case(sys.argv[1])
    registry, counter = sealed_registry(universe, hard_limit=200_000)
    try:
        solution = resolve(registry, list(roots))
    except Unsolvable as error:
        print("UNSOLVABLE " + " | ".join(sorted(str(fact) for fact in error.causes)))
    else:
        print("SOLUTION " + format_solution(solution))
    print("CALLS %d" % (counter["calls"],))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
