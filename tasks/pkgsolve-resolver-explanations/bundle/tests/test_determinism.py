"""determinism -- section 6.

A resolver that iterates a `set` of package names without sorting gets a
different answer depending on the hash seed. It passes every other category and
fails here, which is exactly the point: the same manifest must build the same
image tomorrow.
"""

from __future__ import annotations

import os
import subprocess
import sys

from _oracle import check_explanation
from _support import (
    assert_solution,
    conflict_case,
    determinism_case,
    sample_case,
    sample_solution,
    solve_within,
    unsolvable_within,
)

BUDGET = 150      # 5.2x the reference's worst (29)
HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = os.path.join(HERE, "determinism_child.py")


def run_child(name, seed):
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = str(seed)
    environment["PYTHONPATH"] = os.pathsep.join(
        [HERE, os.path.dirname(HERE), environment.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    finished = subprocess.run(
        [sys.executable, CHILD, name],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert finished.returncode == 0, (
        "the child exited %s\n%s\n%s"
        % (finished.returncode, finished.stdout[-2000:], finished.stderr[-2000:])
    )
    return finished.stdout


def test_two_calls_in_one_process_agree():
    universe, roots = sample_case()
    first, first_counter = solve_within(universe, roots, BUDGET)
    second, second_counter = solve_within(universe, roots, BUDGET)
    assert_solution(first, sample_solution())
    assert first == second
    assert first_counter["calls"] == second_counter["calls"], (
        "the second call spent %d registry calls against the first call's %d; "
        "resolve() must hold no state between calls"
        % (second_counter["calls"], first_counter["calls"])
    )


def test_no_state_survives_a_different_instance_in_between():
    universe, roots = sample_case()
    _, before = solve_within(universe, roots, BUDGET)
    other, other_roots = conflict_case()
    unsolvable_within(other, other_roots, BUDGET)
    solution, after = solve_within(universe, roots, BUDGET)
    assert_solution(solution, sample_solution())
    assert before["calls"] == after["calls"], (
        "%d calls before an unrelated instance, %d after"
        % (before["calls"], after["calls"])
    )


def test_the_solution_does_not_depend_on_the_hash_seed():
    outputs = [run_child("solvable", seed) for seed in (0, 1, 987654321)]
    assert len(set(outputs)) == 1, (
        "three hash seeds gave %d different answers:\n%s"
        % (len(set(outputs)), "\n".join(sorted(set(outputs))))
    )
    assert outputs[0].startswith("SOLUTION ")


def test_the_explanation_does_not_depend_on_the_hash_seed():
    outputs = [run_child("unsolvable", seed) for seed in (0, 1, 987654321)]
    assert len(set(outputs)) == 1, (
        "three hash seeds gave %d different explanations:\n%s"
        % (len(set(outputs)), "\n".join(sorted(set(outputs))))
    )
    first = outputs[0].splitlines()[0]
    assert first.startswith("UNSOLVABLE ")
    cited = [item for item in first[len("UNSOLVABLE "):].split(" | ") if item.strip()]
    assert cited, "the explanation is empty; causes has to prove something"
    # And the explanation the child printed has to be a real one.
    universe, roots = conflict_case()
    error, _ = unsolvable_within(universe, roots, BUDGET)
    assert not check_explanation(universe, roots, error.causes)
    assert sorted(str(fact) for fact in error.causes) == sorted(cited), (
        "the in-process run and the subprocess disagree about the explanation"
    )


def test_the_named_cases_are_the_ones_the_child_runs():
    # Keeps the child and the parent honest about which universes they compare,
    # and solves both of them here so the check cannot pass on a workspace that
    # cannot solve anything.
    parent_universe, parent_roots = determinism_case("solvable")
    universe, roots = sample_case()
    assert parent_universe.names() == universe.names()
    assert [str(r) for r in parent_roots] == [str(r) for r in roots]

    solution, _ = solve_within(parent_universe, parent_roots, BUDGET)
    assert_solution(solution, sample_solution())
    failing, failing_roots = determinism_case("unsolvable")
    error, _ = unsolvable_within(failing, failing_roots, BUDGET)
    assert not check_explanation(failing, failing_roots, error.causes)
