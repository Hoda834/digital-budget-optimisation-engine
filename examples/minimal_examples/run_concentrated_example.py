"""
Minimal example 2: a concentrated optimum with risk-managed
redistribution.

Three platforms, a 60,000 budget over 45 days with a 10% test-and-learn
reserve, two objectives (Lead Generation at 45 per lead, Website
Traffic at 0.35 per click), and one strongly dominant platform: Google
Performance Max with 5,200 purchases and 58,000 clicks on 20,000 of
history, against much weaker Facebook (200 leads on 8,000) and
Instagram (150 leads on 8,000). All three platforms carry a 3,000
minimum-spend floor. Run in risk-managed mode so the alternative plan
redistributes visibly.

Run from the repo root:
    python examples/minimal_examples/run_concentrated_example.py
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

GOAL_VALUES = {"lg": 45.0, "wt": 0.35}

if __name__ == "__main__":
    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg", "wt"], raw_budget=60_000.0, raw_duration_days=45,
        raw_goal_values=GOAL_VALUES, raw_test_and_learn_pct=0.10,
    )
    run_module2(state, selected_platforms=["go_pmax", "fb", "ig"], priorities_input={
        "go_pmax": {"priority_1": "lg", "priority_2": "wt"},
        "fb":      {"priority_1": "lg", "priority_2": "wt"},
        "ig":      {"priority_1": "lg", "priority_2": "wt"}})
    state.min_spend_per_platform = {"go_pmax": 3_000.0, "fb": 3_000.0, "ig": 3_000.0}
    state.min_budget_per_goal = {}
    finalise_module3_from_inputs(state, platform_inputs={
        "go_pmax": {"budget": 20_000.0, "historical_days": 45,
                     "kpis": {"GO_PMAX_LG_PURCHASES": 5_200.0, "GO_PMAX_WT_CLICKS": 58_000.0}},
        "fb": {"budget": 8_000.0, "historical_days": 45, "kpis": {"FB_LG_LEADS": 200.0}},
        "ig": {"budget": 8_000.0, "historical_days": 45, "kpis": {"IG_LG_LEADS": 150.0}},
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
    revenue = sum(r.predicted_kpi * GOAL_VALUES[r.objective]
                  for r in forecasts["base"].rows)

    print("Concentrated three-platform example")
    print("-" * 54)
    print("Plan A (performance first):")
    for p in sorted(pt, key=lambda x: -pt[x]):
        print(f"  {p:8s} {pt[p]:>9,.0f}  ({pt[p]/total:.1%})")
    print(f"  Expected revenue : {revenue:,.2f}")
    print(f"  Binding          : {ins.binding_constraints}")
    if ins.plan_b is not None:
        pb = {p: sum(v for v in g.values() if v > 1)
              for p, g in ins.plan_b.allocation.items()}
        freed = pb.get("fb", 0) + pb.get("ig", 0) - 6_000.0
        print("Plan B (risk managed):")
        for p in sorted(pb, key=lambda x: -pb[x]):
            print(f"  {p:8s} {pb[p]:>9,.0f}")
        print(f"  Redistributed    : {freed:,.0f}")
        print(f"  Trade-off        : {ins.plan_b.tradeoff_percent:.2f}%")
