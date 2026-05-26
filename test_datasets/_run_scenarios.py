"""
End-to-end runner for the 5 test_datasets scenarios.

For each scenario:
  - Parses every per-platform CSV via core.csv_import.parse_platform_csv
  - Walks M1 -> M7 with the wizard inputs from each SCENARIO.md
  - Applies the scenario's per-platform minima as a post-M2 override
    (matches what the UI's "Refine and re-solve" panel would do)
  - Prints the base allocation, scenario totals, Module 7 classification
    and confidence.

Run from repo root:
  PYTHONPATH=. python test_datasets/_run_scenarios.py
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from core.csv_import import parse_platform_csv
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


def _parse_scenario_csvs(folder: str, platforms: List[str]) -> Dict[str, Dict[str, Any]]:
    """Load every per-platform CSV in folder/<platform>.csv and convert
    to the shape finalise_module3_from_inputs() expects."""
    out: Dict[str, Dict[str, Any]] = {}
    for p in platforms:
        path = os.path.join(folder, f"{p}.csv")
        with open(path, "rb") as f:
            raw = f.read()
        res = parse_platform_csv(raw, p)
        if res.get("error"):
            raise RuntimeError(f"{path}: {res['error']}")
        out[p] = {
            "budget": res["budget"],
            "historical_days": res.get("historical_days"),
            "kpis": res.get("kpis", {}),
        }
    return out


def _drive(
    title: str,
    folder: str,
    *,
    objectives: List[str],
    total_budget: float,
    duration: int,
    platforms: List[str],
    priorities: Dict[str, Dict[str, Optional[str]]],
    goal_values: Optional[Dict[str, float]] = None,
    test_and_learn_pct: Optional[float] = None,
    seasonality_index: Optional[Dict[str, float]] = None,
    scenario_multipliers: Optional[Dict[str, float]] = None,
    per_platform_min: Optional[Dict[str, float]] = None,
    scenario_goal_multipliers: Optional[Dict[str, Dict[str, float]]] = None,
) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")
    print(f"  Objectives: {objectives}   Budget: £{total_budget:,.0f}   Days: {duration}")
    if goal_values:
        print(f"  Goal values: {goal_values}")
    if test_and_learn_pct:
        print(f"  T&L reserve: {test_and_learn_pct*100:.0f}%")
    if seasonality_index:
        print(f"  Seasonality: {seasonality_index}")
    if per_platform_min:
        print(f"  Per-platform minima: {per_platform_min}")

    platform_inputs = _parse_scenario_csvs(folder, platforms)
    print(f"  Parsed CSVs:")
    for p, pin in platform_inputs.items():
        non_zero = {k: v for k, v in pin["kpis"].items() if v}
        print(f"    {p}: hist £{pin['budget']:,.0f} / {pin['historical_days']}d → "
              f"{len(non_zero)} KPIs")

    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=objectives,
        raw_budget=total_budget,
        raw_duration_days=duration,
        raw_goal_values=goal_values,
        raw_test_and_learn_pct=test_and_learn_pct,
        raw_seasonality_index=seasonality_index,
    )
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)

    # Apply scenario-specific overrides on top of M2 defaults
    if per_platform_min:
        merged = dict(getattr(state, "min_spend_per_platform", {}) or {})
        merged.update({p: float(v) for p, v in per_platform_min.items()})
        state.min_spend_per_platform = merged
    if scenario_multipliers:
        state.scenario_multipliers = dict(scenario_multipliers)
    if scenario_goal_multipliers:
        state.scenario_goal_multipliers = dict(scenario_goal_multipliers)

    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)
    run_module6(state)

    bundle = state.module5_scenario_bundle
    forecasts = (state.module6_scenario_result.results_by_scenario
                 if state.module6_scenario_result else {})
    insights = run_module7(state, bundle, forecasts)

    base = bundle.results_by_scenario["base"]
    plat_totals = {p: sum(v for v in gmap.values() if v > 1)
                   for p, gmap in base.budget_per_platform_goal.items()}
    total = sum(plat_totals.values()) or 1.0

    print("\n  BASE allocation (£ and % of LP-allocated):")
    for p in sorted(plat_totals, key=lambda x: -plat_totals[x]):
        gmap = base.budget_per_platform_goal[p]
        breakdown = ", ".join(f"{g}=£{v:,.0f}" for g, v in sorted(gmap.items()) if v > 1)
        print(f"    {p:11s} £{plat_totals[p]:>9,.0f}  ({plat_totals[p]/total:>5.1%})   {breakdown}")
    print(f"    {'TOTAL':11s} £{base.total_budget_used:>9,.0f}   cap £{base.effective_budget_cap:,.0f}"
          + (f"   reserve £{base.test_and_learn_reserve:,.0f}" if base.test_and_learn_reserve > 0 else ""))

    print("\n  Scenario totals:")
    for name in ("conservative", "base", "optimistic"):
        r = bundle.results_by_scenario.get(name)
        if r:
            print(f"    {name:>13}: spent £{r.total_budget_used:>9,.0f}  "
                  f"cap £{r.effective_budget_cap:>9,.0f}  obj={r.objective_value:>11,.1f}")

    base_ins = insights.scenario_insights.get("base")
    if base_ins:
        print("\n  Module 7 (base):")
        print(f"    Classification: {base_ins.classification}")
        print(f"    Confidence    : {base_ins.confidence_score}/100")
        print(f"    Dominant      : {base_ins.dominant_platform} / {base_ins.dominant_objective} "
              f"({base_ins.concentration_ratio_top_platform:.0%})")
        if base_ins.binding_constraints:
            print(f"    Binding       : {base_ins.binding_constraints[:4]}"
                  + ("..." if len(base_ins.binding_constraints) > 4 else ""))
        if base_ins.risks:
            print(f"    Risks         : {base_ins.risks[:2]}"
                  + ("..." if len(base_ins.risks) > 2 else ""))


# ─────────────────────────────────────────────────────────────────────────
# Scenarios — inputs mirror each SCENARIO.md
# ─────────────────────────────────────────────────────────────────────────

def run_s1() -> None:
    _drive(
        "Scenario 1 — B2B SaaS lead-gen",
        os.path.join(HERE, "01_b2b_saas_leadgen"),
        objectives=["lg", "aw"],
        total_budget=25_000.0,
        duration=30,
        platforms=["li", "go_search", "fb"],
        priorities={
            "li":        {"priority_1": "lg", "priority_2": "aw"},
            "go_search": {"priority_1": "lg", "priority_2": "aw"},
            "fb":        {"priority_1": "lg", "priority_2": "aw"},
        },
        goal_values={"lg": 200.0, "aw": 0.002},
        test_and_learn_pct=0.12,
        per_platform_min={"li": 5_000.0, "go_search": 4_000.0, "fb": 1_500.0},
    )


def run_s2() -> None:
    _drive(
        "Scenario 2 — D2C e-commerce purchases",
        os.path.join(HERE, "02_dtc_ecommerce_purchases"),
        objectives=["lg", "wt"],
        total_budget=80_000.0,
        duration=60,
        platforms=["go_pmax", "fb", "ig", "tt", "pt"],
        priorities={
            "go_pmax": {"priority_1": "lg", "priority_2": "wt"},
            "fb":      {"priority_1": "lg", "priority_2": "wt"},
            "ig":      {"priority_1": "lg", "priority_2": "wt"},
            "tt":      {"priority_1": "wt", "priority_2": "lg"},
            "pt":      {"priority_1": "wt", "priority_2": "lg"},
        },
        goal_values={"lg": 45.0, "wt": 0.40},
        test_and_learn_pct=0.15,
        seasonality_index={"aw": 1.2, "en": 1.0, "wt": 1.0, "lg": 1.0},
        per_platform_min={"go_pmax": 15_000.0, "fb": 8_000.0, "ig": 6_000.0,
                          "tt": 6_000.0, "pt": 4_000.0},
    )


def run_s3() -> None:
    _drive(
        "Scenario 3 — Brand-awareness launch",
        os.path.join(HERE, "03_brand_launch_awareness"),
        objectives=["aw", "en"],
        total_budget=200_000.0,
        duration=45,
        platforms=["yt", "tt", "ig", "sn", "tw"],
        priorities={
            "yt": {"priority_1": "aw", "priority_2": "en"},
            "tt": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "sn": {"priority_1": "aw", "priority_2": "en"},
            "tw": {"priority_1": "en", "priority_2": "aw"},
        },
        goal_values={"aw": 0.006, "en": 0.10},
        test_and_learn_pct=0.15,
        seasonality_index={"aw": 0.9, "en": 0.9, "wt": 1.0, "lg": 1.0},
        scenario_goal_multipliers={
            "conservative": {"aw": 0.85},
            "base":         {},
            "optimistic":   {"aw": 1.15},
        },
        per_platform_min={"yt": 25_000.0, "tt": 25_000.0, "ig": 20_000.0,
                          "sn": 8_000.0, "tw": 8_000.0},
    )


def run_s4() -> None:
    _drive(
        "Scenario 4 — Community / engagement",
        os.path.join(HERE, "04_community_engagement"),
        objectives=["en", "aw"],
        total_budget=40_000.0,
        duration=60,
        platforms=["ig", "tt", "rd", "tw"],
        priorities={
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "tt": {"priority_1": "en", "priority_2": "aw"},
            "rd": {"priority_1": "en", "priority_2": "aw"},
            "tw": {"priority_1": "en", "priority_2": "aw"},
        },
        goal_values={"en": 0.25, "aw": 0.004},
        test_and_learn_pct=0.10,
        per_platform_min={"ig": 8_000.0, "tt": 8_000.0, "rd": 4_000.0, "tw": 3_000.0},
    )


def run_s5() -> None:
    _drive(
        "Scenario 5 — Omnichannel, all four objectives",
        os.path.join(HERE, "05_omnichannel_all_goals"),
        objectives=["aw", "en", "wt", "lg"],
        total_budget=150_000.0,
        duration=90,
        platforms=["go_search", "go_display", "go_pmax", "fb", "ig", "li", "yt", "tt"],
        priorities={
            "go_search":  {"priority_1": "lg", "priority_2": "wt"},
            "go_display": {"priority_1": "aw", "priority_2": "wt"},
            "go_pmax":    {"priority_1": "lg", "priority_2": "wt"},
            "fb":         {"priority_1": "en", "priority_2": "wt"},
            "ig":         {"priority_1": "en", "priority_2": "wt"},
            "li":         {"priority_1": "lg", "priority_2": "en"},
            "yt":         {"priority_1": "aw", "priority_2": "en"},
            "tt":         {"priority_1": "aw", "priority_2": "en"},
        },
        goal_values={"aw": 0.005, "en": 0.12, "wt": 0.45, "lg": 55.0},
        test_and_learn_pct=0.12,
        seasonality_index={"aw": 0.95, "en": 0.95, "wt": 0.95, "lg": 0.95},
        scenario_goal_multipliers={
            "conservative": {"lg": 0.8},
            "base":         {},
            "optimistic":   {"lg": 1.2},
        },
        per_platform_min={"go_search": 10_000.0, "go_display": 4_000.0,
                          "go_pmax": 12_000.0, "fb": 10_000.0, "ig": 10_000.0,
                          "li": 8_000.0, "yt": 12_000.0, "tt": 8_000.0},
    )


if __name__ == "__main__":
    for fn in (run_s1, run_s2, run_s3, run_s4, run_s5):
        try:
            fn()
        except Exception as e:
            print(f"\n{SEP}\nSCENARIO FAILED: {fn.__name__}: {e}\n{SEP}")
            raise
    print(f"\n{SEP}\nAll scenarios executed.\n{SEP}")
