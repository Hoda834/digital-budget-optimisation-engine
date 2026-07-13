"""
Monte Carlo stability check for the example case study.

Resamples the full productivity matrix under the default-policy
configuration and reports the stability score: the fraction of platforms
whose share is robust to plausible productivity noise. The analysis is
stochastic (mean-preserving lognormal shocks per cell), so a fixed random
seed is used to make the reported figure exactly reproducible. Different
seeds produce slightly different scores by construction; the point of the
check is that several platforms sit close together in productivity and can
exchange rank under resampling, which is consistent with the
scenario-sensitive classification.

Run from the repo root:
    python examples/case_study/run_montecarlo_stability.py
"""
from __future__ import annotations

from run_case_study import run_configuration
from claro_engine.modules.module5 import run_module5_montecarlo

SEED = 42
N_TRIALS = 200

if __name__ == "__main__":
    state, _bundle, _insights = run_configuration("default", None)
    mc = run_module5_montecarlo(state, n_trials=N_TRIALS, seed=SEED)
    score = mc.stability_score
    score_pct = score * 100 if score <= 1 else score
    print("Monte Carlo stability check (default policy)")
    print("-" * 52)
    print(f"  Trials            : {N_TRIALS}")
    print(f"  Random seed       : {SEED}")
    print(f"  Stability score   : {score_pct:.1f}%")
    if mc.unstable_platforms:
        print(f"  Unstable platforms: {mc.unstable_platforms}")
    print("\nNote: the score is a stochastic estimate. The fixed seed makes "
          "this exact figure reproducible; other seeds shift it by a few "
          "points because the check resamples the productivity matrix.")
