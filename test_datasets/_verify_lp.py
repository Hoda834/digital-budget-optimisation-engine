"""
Deterministic verification of the LP optimiser.

Each case sets up small inputs whose optimum is computable by hand from
the diminishing-returns bracket schedule (caps 25%/35%/40%, yields
1.00/0.65/0.35) and the published shrinkage formula
(w = 30 / (30 + historical_days)).  We then run M1-M5 and assert the
LP's base-scenario allocation matches the hand-computed answer.

Run from repo root:
  PYTHONPATH=. python test_datasets/_verify_lp.py
"""
from __future__ import annotations

from typing import Dict, Tuple

from claro_engine.core.wizard_state import WizardState
from claro_engine.modules.module1 import complete_module1_and_advance
from claro_engine.modules.module2 import run_module2
from claro_engine.modules.module3 import finalise_module3_from_inputs
from claro_engine.modules.module4 import run_module4
from claro_engine.modules.module5 import run_module5


def _solve(
    *,
    platform_inputs: Dict[str, Dict],
    total_budget: float,
    min_spend_per_platform: Dict[str, float],
) -> Dict[str, float]:
    """Walk M1-M5 with a single LG objective and return per-platform
    £ allocation under the BASE scenario."""
    platforms = list(platform_inputs.keys())
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["lg"],
        raw_budget=total_budget,
        raw_duration_days=30,
    )
    priorities = {p: {"priority_1": "lg", "priority_2": None} for p in platforms}
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)

    # Clear the M2 defaults — we want only the floors we explicitly set,
    # and we disable the per-goal pool so the only binding constraints
    # are the per-platform minima.
    state.min_spend_per_platform = dict(min_spend_per_platform)
    state.min_budget_per_goal = {}
    # Single scenario, identical to base, so we can read base directly.
    state.scenario_multipliers = {"base": 1.0}

    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    return {
        p: sum(v for v in gmap.values() if v > 1e-6)
        for p, gmap in base.budget_per_platform_goal.items()
    }


def _assert_alloc(
    case: str,
    actual: Dict[str, float],
    expected: Dict[str, float],
    *,
    abs_tol: float = 50.0,
) -> bool:
    """Compare actual £ allocation to expected, within an absolute £ tolerance.
    Returns True on match."""
    ok = True
    print(f"\n── {case} ──")
    for p in expected:
        a = actual.get(p, 0.0)
        e = expected[p]
        match = abs(a - e) <= abs_tol
        marker = "OK  " if match else "FAIL"
        print(f"  {marker}  {p}: got £{a:>9,.0f}   expected £{e:>9,.0f}   diff £{a-e:>+8,.0f}")
        if not match:
            ok = False
    return ok


# Reusable platform inputs.  Long histories (300 days) keep the
# James-Stein shrinkage weight low (w = 30/(30+300) ≈ 0.091) so the
# hand-computed predictions hold without needing to absorb a large
# pooling correction into the arithmetic.
def _pinput(budget: float, leads: float) -> Dict:
    return {"budget": budget, "historical_days": 300, "kpis": {}}  # filled per-case


# ─────────────────────────────────────────────────────────────────────────
# T1: Pure dominance, no floors → corner solution at A
# A is 10× more productive than B on leads/£.  Even A's worst-bracket
# yield (≈ 0.1955×0.35 = 0.068) beats B's best-bracket yield (0.0105),
# so the LP should allocate the entire budget to A.
# ─────────────────────────────────────────────────────────────────────────
def t1() -> bool:
    inputs = {
        "fb": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"FB_LG_LEADS": 100.0}},          # 0.10 leads/£
        "li": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"LI_LG_LEADS": 10.0}},           # 0.01 leads/£
    }
    out = _solve(platform_inputs=inputs, total_budget=10_000.0,
                 min_spend_per_platform={"fb": 0.0, "li": 0.0})
    return _assert_alloc(
        "T1 — pure 10× dominance, no floors → A=100%, B=0%",
        out,
        {"fb": 10_000.0, "li": 0.0},
    )


# ─────────────────────────────────────────────────────────────────────────
# T2: Pure dominance + binding floor on B = 40% of budget
# A still wins per-unit but the floor forces 40% into B.
# ─────────────────────────────────────────────────────────────────────────
def t2() -> bool:
    inputs = {
        "fb": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"FB_LG_LEADS": 100.0}},
        "li": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"LI_LG_LEADS": 10.0}},
    }
    out = _solve(platform_inputs=inputs, total_budget=10_000.0,
                 min_spend_per_platform={"fb": 0.0, "li": 4_000.0})
    return _assert_alloc(
        "T2 — 10× dominance + 40% floor on B → A=60%, B=40%",
        out,
        {"fb": 6_000.0, "li": 4_000.0},
    )


# ─────────────────────────────────────────────────────────────────────────
# T3: Identical productivity, no floors
# Marginal yields are tied at every bracket; the LP is indifferent across
# any split that respects the per-cell bracket caps.  Multiple optima are
# valid; we only check that the total equals the budget and no per-cell
# cap is violated (B1 ≤ 25%, B2 ≤ 35%, B3 ≤ 40%, so total per cell ≤ 100%).
# ─────────────────────────────────────────────────────────────────────────
def t3() -> bool:
    inputs = {
        "fb": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"FB_LG_LEADS": 100.0}},
        "li": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"LI_LG_LEADS": 100.0}},
    }
    out = _solve(platform_inputs=inputs, total_budget=10_000.0,
                 min_spend_per_platform={"fb": 0.0, "li": 0.0})
    total = sum(out.values())
    fb = out.get("fb", 0.0)
    li = out.get("li", 0.0)
    print("\n── T3 — identical productivity, no floors → any valid split ──")
    print(f"  fb: £{fb:,.0f}   li: £{li:,.0f}   total: £{total:,.0f}")
    ok_total = abs(total - 10_000.0) <= 50.0
    ok_cap_fb = fb <= 10_000.0 + 50.0
    ok_cap_li = li <= 10_000.0 + 50.0
    print(f"  OK   total matches budget: {ok_total}")
    print(f"  OK   per-platform within 100% cap: {ok_cap_fb and ok_cap_li}")
    return ok_total and ok_cap_fb and ok_cap_li


# ─────────────────────────────────────────────────────────────────────────
# T4: 2× dominance, no floors → A=75%, B=25%
# Greedy fill of bracket marginal yields (post-shrinkage):
#   A: 0.1955 / 0.1271 / 0.0684   (caps 25/35/40 = £2.5k/£3.5k/£4k)
#   B: 0.1045 / 0.0679 / 0.0366   (same caps)
# Order: A-B1 (£2.5k) → A-B2 (£3.5k) → B-B1 (£2.5k) → A-B3 (£1.5k, last)
# Final: A = 2.5 + 3.5 + 1.5 = £7.5k.  B = £2.5k.
# ─────────────────────────────────────────────────────────────────────────
def t4() -> bool:
    inputs = {
        "fb": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"FB_LG_LEADS": 200.0}},          # 0.20 leads/£
        "li": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"LI_LG_LEADS": 100.0}},          # 0.10 leads/£
    }
    out = _solve(platform_inputs=inputs, total_budget=10_000.0,
                 min_spend_per_platform={"fb": 0.0, "li": 0.0})
    return _assert_alloc(
        "T4 — 2× dominance, no floors → A=75% (£7.5k), B=25% (£2.5k)",
        out,
        {"fb": 7_500.0, "li": 2_500.0},
    )


# ─────────────────────────────────────────────────────────────────────────
# T5: Same as T4 but min on B = 40% → floor overrides bracket logic
# Without floor: A=£7.5k, B=£2.5k.  With £4k floor on B: A=£6k, B=£4k.
# ─────────────────────────────────────────────────────────────────────────
def t5() -> bool:
    inputs = {
        "fb": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"FB_LG_LEADS": 200.0}},
        "li": {"budget": 1_000.0, "historical_days": 300,
               "kpis": {"LI_LG_LEADS": 100.0}},
    }
    out = _solve(platform_inputs=inputs, total_budget=10_000.0,
                 min_spend_per_platform={"fb": 0.0, "li": 4_000.0})
    return _assert_alloc(
        "T5 — 2× dominance + 40% floor on B → A=60% (£6k), B=40% (£4k)",
        out,
        {"fb": 6_000.0, "li": 4_000.0},
    )


if __name__ == "__main__":
    results = {
        "T1": t1(),
        "T2": t2(),
        "T3": t3(),
        "T4": t4(),
        "T5": t5(),
    }
    print("\n" + "=" * 60)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{len(results)} verification cases passed.")
    print("=" * 60)
