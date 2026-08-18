"""randomized -- differential testing against the exhaustive oracle.

Each instance is a small random universe. The grader enumerates every
assignment, filters by validity and reduces by the preference comparison,
straight out of sections 3.1 and 3.2; the submission has to agree. When the
oracle finds no solution, the submission has to raise `Unsolvable` with an
explanation that passes (E1)-(E5).

Nothing here can be hard-coded: the universes come from a seed, and the
expected answers are computed at grading time.
"""

from __future__ import annotations

import random

import pytest

from _oracle import check_explanation, preferred_solution
from _support import (
    BALLAST_SOLUTION,
    Universe,
    case,
    core_of,
    format_solution,
    is_ballast,
    random_roots,
    random_spec,
    solve_within,
    unsolvable_within,
)

BUDGET = 180      # 5.3x the reference's worst (34)
SPARSE_BATCHES = 14
DENSE_BATCHES = 10
PER_BATCH = 5


def run_instance(spec, roots):
    core = Universe(spec)
    expected = preferred_solution(core, roots)
    universe, all_roots = case(spec, roots)

    if expected is None:
        error, _ = unsolvable_within(universe, all_roots, BUDGET)
        problems = check_explanation(universe, all_roots, error.causes)
        assert not problems, (
            "instance %r\n  roots %s\n  %s"
            % (spec, [str(r) for r in roots], "\n  ".join(problems))
        )
        return

    solution, _ = solve_within(universe, all_roots, BUDGET)
    assert core_of(solution) == expected, (
        "instance %r\n  roots %s\n  expected %s\n       got %s"
        % (spec, [str(r) for r in roots],
           format_solution(expected), format_solution(core_of(solution)))
    )
    ballast = {name: version for name, version in solution.items() if is_ballast(name)}
    assert ballast == BALLAST_SOLUTION, (
        "the independent component must resolve on its own terms: %s"
        % (format_solution(ballast),)
    )


@pytest.mark.parametrize("batch", range(SPARSE_BATCHES))
def test_random_sparse_universes(batch):
    rng = random.Random(0xC0FFEE + batch)
    for _ in range(PER_BATCH):
        spec = random_spec(rng, packages=5, versions=3, max_deps=2)
        run_instance(spec, random_roots(rng, spec, rng.randint(1, 2)))


@pytest.mark.parametrize("batch", range(DENSE_BATCHES))
def test_random_dense_universes(batch):
    rng = random.Random(0x5EED5 + batch)
    for _ in range(PER_BATCH):
        spec = random_spec(rng, packages=6, versions=3, max_deps=3)
        run_instance(spec, random_roots(rng, spec, rng.randint(1, 3)))
