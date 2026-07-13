"""
Minimal example 1: a balanced two-platform optimum.

A 20,000 budget over 30 days, one objective (Lead Generation at 100 per
lead), split between two platforms of comparable productivity:
LinkedIn with 300 leads on 9,500 of history and Facebook with 150 leads
on 8,000, both with a 3,000 minimum spend. Run in risk-managed mode so
the alternative plan is computed for comparison.

Run from the repo root:
     python examples/minimal_examples/run_balanced_example.py
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from claro_engine.core.wizard_state import WizardState
from claro_engine.modules.module1 import complete_module1_and_advance
from claro_engine.modules.module2 import run_module2
from claro_engine.modules.module3 import finalise_module3_from_inputs
from claro_engine.modules.module4 import run_module4
from claro_engine.modules.module5 import run_module5
from claro_engine.modules.module6 import run_module6
from claro_engine.modules.module7 import run_module7

PER_LEAD_VALUE = 100.0

if __name__ == "__main__":
    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg"], raw_budget=20_000.0, raw_duration_days=30,
        raw_goal_values={"lg": PER_LEAD_VALUE}, raw_test_and_learn_pct=0.0,
    )
    run_module2(state, selected_platforms=["li", "fb"], priorities_input={
        "li": {"priority_1": "lg"}, "fb": {"priority_1": "lg"}})
    state.min_spend_per_platform = {"li": 3_000.0, "fb": 3_000.0}
    state.min_budget_per_goal = {}
    finalise_module3_from_inputs(state, platform_inputs={
        "li": {"budget": 9_500.0, "historical_days": 30, "kpis": {"LI_LG_LEADS": 300.0}},
        "fb": {"budget": 8_000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 150.0}},
    })
    run_module4(state)
    run_module5(state)
    run_module6(state)
    bundle = state.module5_scenario_bundle
    forecasts = state.module6_scenario_result.results_by_scenario
    ins = run_module7(state, bundle, forecasts,
                      decision_mode="Risk managed").scenario_insights["base"]
    lp = bundle.results_by_scenario["base"]
    pt = {p: sum(v for v in g.values() if v > 1)
          for p, g in lp.budget_per_platform_goal.items()}
    total = sum(pt.values()) or 1.0
    revenue = sum(r.predicted_kpi * PER_LEAD_VALUE for r in forecasts["base"].rows)

    print("Balanced two-platform example")
    print("-" * 50)
    for p in sorted(pt, key=lambda x: -pt[x]):
        print(f"  {p:4s} {pt[p]:>9,.0f}  ({pt[p]/total:.0%})")
    print(f"  Expected revenue : {revenue:,.2f}")
    print(f"  Return on spend  : {revenue/total:.2f}")
    print(f"  Classification   : {ins.classification}")
    print(f"  Diagnostic index : {ins.confidence_score}")
    print(f"  Binding floors   : {ins.binding_constraints or 'none (only the budget cap binds)'}")
    if ins.plan_b is not None:
        print(f"  Risk-managed alternative trade-off: {ins.plan_b.tradeoff_percent:.2f}%"
              f" (identical to the optimum when 0.00)")
