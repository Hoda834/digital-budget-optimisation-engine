"""
Runs the bundled example case study: a five-platform, two-objective
allocation under three policy configurations (budget cap only, default
policy, custom policy), from the unified Excel workbook in this folder.

The workbook `campaign_data.xlsx` is in the same format the app's
Module 3 accepts as a direct upload, so the same run can be reproduced
by hand through the guided interface using this exact file. See
SCENARIO.md for the full inputs and provenance.

Run from the repo root:
    PYTHONPATH=src python examples/case_study/run_case_study.py
"""
from __future__ import annotations

import os
from typing import Dict

from core.csv_import import parse_unified_template_xlsx
from core.wizard_state import WizardState
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module6 import run_module6
from modules.module7 import run_module7

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = "=" * 78

PLATFORM_NAMES = {
    "fb": "Facebook", "ig": "Instagram", "tt": "TikTok",
    "pt": "Pinterest", "go_pmax": "Google Performance Max",
}
PLATFORMS = ["go_pmax", "fb", "ig", "tt", "pt"]
PRIORITIES = {
    "go_pmax": {"priority_1": "lg", "priority_2": "wt"},
    "fb":      {"priority_1": "lg", "priority_2": "wt"},
    "ig":      {"priority_1": "lg", "priority_2": "wt"},
    "tt":      {"priority_1": "wt", "priority_2": "lg"},
    "pt":      {"priority_1": "lg", "priority_2": "wt"},
}
GOAL_VALUES = {"lg": 45.0, "wt": 0.40}
TOTAL_BUDGET = 80_000.0
DURATION_DAYS = 60
TEST_AND_LEARN_PCT = 0.15


def load_platform_inputs(pmax_purchases_override: float = None) -> Dict[str, Dict]:
    """Load the workbook through the same parser the app's upload uses."""
    with open(os.path.join(HERE, "campaign_data.xlsx"), "rb") as f:
        parsed = parse_unified_template_xlsx(f.read(), platform_display_names=PLATFORM_NAMES)
    out: Dict[str, Dict] = {}
    for code, res in parsed.items():
        if code.startswith("__"):
            continue
        if res.get("error"):
            raise RuntimeError(f"{code}: {res['error']}")
        budget = res.get("budget")
        if budget is None or float(budget) <= 0:
            raise ValueError(f"{code}: invalid budget in workbook: {budget!r}")
        kpis = dict(res.get("kpis", {}))
        if code == "go_pmax" and pmax_purchases_override is not None:
            kpis["GO_PMAX_LG_PURCHASES"] = float(pmax_purchases_override)
        out[code] = {"budget": float(budget),
                     "historical_days": res.get("historical_days"),
                     "kpis": kpis}
    return out


def run_configuration(floors_mode: str, custom_floor_overrides: Dict[str, float] = None,
                      pmax_purchases_override: float = None):
    """floors_mode: 'none' (budget cap only), 'default', or 'custom'."""
    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg", "wt"], raw_budget=TOTAL_BUDGET,
        raw_duration_days=DURATION_DAYS, raw_goal_values=GOAL_VALUES,
        raw_test_and_learn_pct=TEST_AND_LEARN_PCT,
    )
    run_module2(state, selected_platforms=PLATFORMS, priorities_input=PRIORITIES)
    if floors_mode == "none":
        state.min_spend_per_platform = {}
        state.min_budget_per_goal = {}
    elif floors_mode == "custom":
        merged = dict(state.min_spend_per_platform)
        merged.update(custom_floor_overrides or {})
        state.min_spend_per_platform = merged
    finalise_module3_from_inputs(
        state, platform_inputs=load_platform_inputs(pmax_purchases_override))
    run_module4(state)
    run_module5(state)
    run_module6(state)
    bundle = state.module5_scenario_bundle
    forecasts = (state.module6_scenario_result.results_by_scenario
                 if state.module6_scenario_result else {})
    insights = run_module7(state, bundle, forecasts)
    return state, bundle, insights


if __name__ == "__main__":
    print("Example case study: three policy configurations")
    configs = [
        ("Configuration 1: budget cap only", "none", None),
        ("Configuration 2: default policy", "default", None),
        ("Configuration 3: custom policy (TikTok floor raised to 6,000)", "custom", {"tt": 6_000.0}),
    ]
    for label, mode, custom in configs:
        _, bundle, insights = run_configuration(mode, custom)
        lp = bundle.results_by_scenario["base"]
        ins = insights.scenario_insights["base"]
        pt = {p: sum(v for v in g.values() if v > 1)
              for p, g in lp.budget_per_platform_goal.items()}
        total = sum(pt.values()) or 1.0
        print(f"\n{SEP}\n{label}\n{SEP}")
        for p in sorted(pt, key=lambda x: -pt[x]):
            print(f"    {p:10s} {pt[p]:>9,.0f}  ({pt[p]/total:>5.1%})")
        print(f"    TOTAL      {lp.total_budget_used:>9,.0f}   "
              f"reserve {getattr(lp, 'test_and_learn_reserve', 0.0):,.0f}")
        print(f"  Classification   : {ins.classification}")
        print(f"  Diagnostic index : {ins.confidence_score}")
        print(f"  Binding          : {ins.binding_constraints}")
    print(f"\n{SEP}\nDone.\n{SEP}")
