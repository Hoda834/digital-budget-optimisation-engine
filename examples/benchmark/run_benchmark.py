"""
Benchmarks the LP solver on synthetic problems of increasing size.

Wall-clock solve times are hardware-dependent: this script will produce
different absolute millisecond figures on different machines, which is
expected and normal for any solver benchmark. The reproducible claim is
the scaling behaviour: solve time grows sub-linearly with problem size
and stays well within interactive limits (sub-100ms) even at the
largest tested size (300 platform-objective cells, 900 LP variables).

Methodology:
  - Problem size is defined by platform-objective cells, 3 bracket
    variables per cell (LP variables = cells x 3).
  - Productivity ratios are randomised per trial (not fixed data).
  - Default scenario multipliers (conservative/base/optimistic).
  - Each timing is the median of 7 runs, after one untimed warm-up run
    (the first PuLP/CBC invocation in a process carries a one-time
    startup cost that would otherwise distort the smallest problem's
    timing).
  - This calls modules.module5.run_module5_lp_scenarios directly with a
    synthetic Module5LPInput, bypassing Modules 1-4 (the wizard/CSV
    layer), because the sweep uses problem sizes (up to 10 objectives)
    that exceed the 4 real canonical goals and are not expressible
    through the normal wizard inputs.

Run from the repo root:
    PYTHONPATH=src python examples/benchmark/run_benchmark.py
"""
from __future__ import annotations

import random
import statistics
import time
from typing import Dict, List, Tuple

from modules.module5 import Module5LPInput, run_module5_lp_scenarios

# (platforms, objectives) pairs defining the benchmark sizes.
SIZES: List[Tuple[int, int]] = [(2, 1), (5, 3), (10, 5), (20, 5), (30, 10)]
N_TRIALS = 7
TOTAL_BUDGET = 100_000.0

def _build_synthetic_input(n_platforms: int, n_goals: int, seed: int) -> Module5LPInput:
    rng = random.Random(seed)
    platforms = [f"p{i}" for i in range(n_platforms)]
    goals = [f"g{j}" for j in range(n_goals)]
    # Dense grid: every platform is eligible for every objective, so
    # cells = platforms x objectives.
    goals_by_platform: Dict[str, List[str]] = {p: list(goals) for p in platforms}
    r_pg = {p: {g: rng.uniform(0.01, 1.0) for g in goals} for p in platforms}
    platform_goal_weights = {p: {g: 1.0 for g in goals} for p in platforms}
    system_goal_weights = {g: 1.0 / n_goals for g in goals}
    return Module5LPInput(
        valid_goals=goals,
        total_budget=TOTAL_BUDGET,
        system_goal_weights=system_goal_weights,
        platform_goal_weights=platform_goal_weights,
        r_pg=r_pg,
        goals_by_platform=goals_by_platform,
        min_spend_per_platform={},
        min_budget_per_goal={},
        scenario_multipliers={"conservative": 0.85, "base": 1.0, "optimistic": 1.15},
        scenario_goal_multipliers={"conservative": {}, "base": {}, "optimistic": {}},
    )


if __name__ == "__main__":
    # Untimed warm-up: absorbs the one-time PuLP/CBC process-startup cost
    # so it doesn't distort the first (smallest) measured size.
    run_module5_lp_scenarios(_build_synthetic_input(2, 1, seed=-1))

    print(f"{'Platforms':>9} {'Objectives':>10} {'Cells':>6} {'LP vars':>8} "
          f"{'Median (ms)':>12}")
    print("-" * 50)
    for n_platforms, n_goals in SIZES:
        times_s = []
        for trial in range(N_TRIALS):
            inp = _build_synthetic_input(n_platforms, n_goals, seed=trial)
            t0 = time.perf_counter()
            run_module5_lp_scenarios(inp)
            times_s.append(time.perf_counter() - t0)
        median_s = statistics.median(times_s)
        cells = n_platforms * n_goals
        print(f"{n_platforms:>9} {n_goals:>10} {cells:>6} {cells * 3:>8} "
              f"{median_s * 1000:>12.1f}")

    print("\nExpected: monotonic, sub-linear growth, all sizes well under "
          "100ms on any modern machine. Absolute values vary by hardware; "
          "that is normal.")
