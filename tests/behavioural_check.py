"""
End-to-end behavioural sanity check.

Runs the full M1 → M7 pipeline under several real-world scenarios and prints
the allocation decisions for each, so we can judge whether the optimiser
behaves the way a marketing strategist would expect.
"""
from __future__ import annotations

from typing import Dict, List

from claro_engine.core.wizard_state import WizardState
from claro_engine.modules.module1 import complete_module1_and_advance
from claro_engine.modules.module2 import run_module2
from claro_engine.modules.module3 import finalise_module3_from_inputs
from claro_engine.modules.module4 import run_module4
from claro_engine.modules.module5 import run_module5
from claro_engine.modules.module6 import run_module6
from claro_engine.modules.module7 import run_module7


SEP = "=" * 78


def _run(
    title: str,
    objectives: List[str],
    total_budget: float,
    platforms: List[str],
    priorities: Dict[str, Dict[str, str]],
    platform_inputs: Dict[str, Dict],
    duration: int = 30,
    goal_values: Dict[str, float] = None,
    test_and_learn_pct: float = None,
) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")
    print(f"  Objectives : {objectives}")
    print(f"  Total budget: £{total_budget:,.0f}   Campaign: {duration} days")
    print(f"  Priorities : {priorities}")
    if goal_values:
        print(f"  Goal values: {goal_values}")
    if test_and_learn_pct:
        print(f"  Test-and-learn reserve: {test_and_learn_pct*100:.0f}% "
              f"(£{total_budget * test_and_learn_pct:,.0f})")
    print(f"  Platform historical inputs:")
    for p, pin in platform_inputs.items():
        print(f"    {p}: £{pin['budget']:,.0f} spent → {pin['kpis']}")

    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=objectives,
        raw_budget=total_budget,
        raw_duration_days=duration,
        raw_goal_values=goal_values,
        raw_test_and_learn_pct=test_and_learn_pct,
    )
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)
    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)
    run_module6(state)

    bundle = state.module5_scenario_bundle
    forecasts = state.module6_scenario_result.results_by_scenario if state.module6_scenario_result else {}
    insights = run_module7(state, bundle, forecasts)

    print("\n  Base-scenario allocation (£):")
    base = bundle.results_by_scenario["base"]
    for p in sorted(base.budget_per_platform_goal.keys()):
        gmap = base.budget_per_platform_goal[p]
        breakdown = ", ".join(f"{g}=£{v:,.0f}" for g, v in sorted(gmap.items()) if v > 1)
        if not breakdown:
            breakdown = "(zero)"
        platform_total = sum(v for v in gmap.values() if v > 1)
        print(f"    {p}: £{platform_total:,.0f}   → {breakdown}")
    print(f"    TOTAL ALLOCATED: £{base.total_budget_used:,.0f}  "
          f"(cap = £{base.effective_budget_cap:,.0f})")
    if base.test_and_learn_reserve > 0.0:
        print(f"    TEST-AND-LEARN RESERVE: £{base.test_and_learn_reserve:,.0f}  "
              f"(held back from LP for new audiences / creative tests)")

    print("\n  Scenario totals:")
    for name in ("conservative", "base", "optimistic"):
        if name in bundle.results_by_scenario:
            r = bundle.results_by_scenario[name]
            reserve_str = (
                f", reserve £{r.test_and_learn_reserve:,.0f}"
                if r.test_and_learn_reserve > 0.0
                else ""
            )
            print(f"    {name:>13}: £{r.total_budget_used:,.0f}  "
                  f"(cap £{r.effective_budget_cap:,.0f}{reserve_str}, "
                  f"objective={r.objective_value:,.0f})")

    print("\n  Module 6 base forecast (with ±30% band on count KPIs):")
    base_fc = forecasts.get("base")
    if base_fc:
        for row in base_fc.rows[:6]:
            if row.kpi_kind == "count":
                print(f"    {row.platform}/{row.objective}/{row.kpi_name}: "
                      f"~{row.predicted_kpi:,.0f}  (range {row.predicted_kpi_low:,.0f} – {row.predicted_kpi_high:,.0f})")
            else:
                print(f"    {row.platform}/{row.objective}/{row.kpi_name}: "
                      f"{row.predicted_kpi:.1%} rate (historical signal)")

    print("\n  Module 7 base insight:")
    base_ins = insights.scenario_insights.get("base")
    if base_ins:
        print(f"    Classification    : {base_ins.classification}")
        print(f"    Confidence        : {base_ins.confidence_score}/100")
        print(f"    Dominant platform : {base_ins.dominant_platform}")
        print(f"    Dominant objective: {base_ins.dominant_objective}")
        print(f"    Concentration     : {base_ins.concentration_ratio_top_platform:.0%}")
        if base_ins.binding_constraints:
            print(f"    Binding           : {base_ins.binding_constraints}")
    if insights.global_notes:
        print(f"    Global notes      : {insights.global_notes}")
    if insights.forecast_caveat:
        print(f"\n  Caveat: {insights.forecast_caveat}")


# ------------------------------------------------------------------------------
# 1) Single-objective sanity checks: AW only, EN only, WT only, LG only
# ------------------------------------------------------------------------------
def case_awareness_only() -> None:
    _run(
        "CASE 1A: AWARENESS only — should favour the cheapest reach",
        objectives=["aw"],
        total_budget=10000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "aw", "priority_2": None},
            "ig": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "aw", "priority_2": None},
        },
        # FB: 400,000 reach / £4,000 = 100 reach/£   (best)
        # IG: 150,000 reach / £4,000 =  37.5 reach/£
        # LI:  40,000 reach / £4,000 =  10 reach/£   (worst — B2B is expensive)
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_AW_REACH": 400000.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_AW_REACH": 150000.0}},
            "li": {"budget": 4000.0, "kpis": {"LI_AW_REACH": 40000.0}},
        },
    )


def case_leads_only() -> None:
    _run(
        "CASE 1B: LEAD GEN only — should favour the cheapest lead",
        objectives=["lg"],
        total_budget=10000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        # FB:  80 leads / £4,000 = £50/lead
        # IG: 100 leads / £4,000 = £40/lead   (cheapest)
        # LI:  50 leads / £4,000 = £80/lead   (most expensive but high quality typically)
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_LG_LEADS": 80.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_LG_LEADS": 100.0}},
            "li": {"budget": 4000.0, "kpis": {"LI_LG_LEADS": 50.0}},
        },
    )


def case_engagement_only() -> None:
    _run(
        "CASE 1C: ENGAGEMENT only — mix of count + rate KPIs",
        objectives=["en"],
        total_budget=10000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "en", "priority_2": None},
            "ig": {"priority_1": "en", "priority_2": None},
            "li": {"priority_1": "en", "priority_2": None},
        },
        # FB has a count KPI (Engagement count). IG/LI have rate KPIs.
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_EN_ENGAGEMENT": 12000.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_EN_ENGAGEMENT": 0.045}},   # 4.5 %
            "li": {"budget": 4000.0, "kpis": {"LI_EN_ENGAGEMENT": 0.015}},   # 1.5 %
        },
    )


def case_traffic_only() -> None:
    _run(
        "CASE 1D: WEBSITE TRAFFIC only",
        objectives=["wt"],
        total_budget=10000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "wt", "priority_2": None},
            "ig": {"priority_1": "wt", "priority_2": None},
            "li": {"priority_1": "wt", "priority_2": None},
        },
        # FB:  4,000 clicks / £4,000 = £1.00/click
        # IG:  3,000 clicks / £4,000 = £1.33/click
        # LI:    800 clicks / £4,000 = £5.00/click
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_WT_CLICKS": 4000.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_WT_CLICKS": 3000.0}},
            "li": {"budget": 4000.0, "kpis": {"LI_WT_CLICKS": 800.0}},
        },
    )


# ------------------------------------------------------------------------------
# 2) Big difference between platform outcomes
# ------------------------------------------------------------------------------
def case_big_difference() -> None:
    _run(
        "CASE 2: BIG DIFFERENCE — FB is 10× more productive than IG for leads",
        objectives=["lg"],
        total_budget=10000.0,
        platforms=["fb", "ig"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            # FB: 200 leads / £4,000 = £20/lead
            # IG:  20 leads / £4,000 = £200/lead
            "fb": {"budget": 4000.0, "kpis": {"FB_LG_LEADS": 200.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_LG_LEADS": 20.0}},
        },
    )


# ------------------------------------------------------------------------------
# 3) Same outcomes (identical productivity)
# ------------------------------------------------------------------------------
def case_identical() -> None:
    _run(
        "CASE 3: IDENTICAL — FB and IG have the same lead productivity",
        objectives=["lg"],
        total_budget=10000.0,
        platforms=["fb", "ig"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_LG_LEADS": 100.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_LG_LEADS": 100.0}},
        },
    )


# ------------------------------------------------------------------------------
# 4) Same KPI counts, different historical budgets (different unit cost)
# ------------------------------------------------------------------------------
def case_same_kpi_different_budget() -> None:
    _run(
        "CASE 4: SAME KPI COUNT, DIFFERENT BUDGETS — IG produced the same "
        "leads at half the cost",
        objectives=["lg"],
        total_budget=10000.0,
        platforms=["fb", "ig"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            # FB: 100 leads / £4,000 = £40/lead
            # IG: 100 leads / £2,000 = £20/lead  (cheaper per unit KPI)
            "fb": {"budget": 4000.0, "kpis": {"FB_LG_LEADS": 100.0}},
            "ig": {"budget": 2000.0, "kpis": {"IG_LG_LEADS": 100.0}},
        },
    )


# ------------------------------------------------------------------------------
# 5) Mixed multi-objective campaign (realistic)
# ------------------------------------------------------------------------------
def case_realistic_mixed() -> None:
    _run(
        "CASE 5: REALISTIC MIX — B2B SaaS launch (AW + EN + LG)",
        objectives=["aw", "en", "lg"],
        total_budget=20000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "li": {"priority_1": "lg", "priority_2": "en"},  # LI is the LG workhorse for B2B
        },
        platform_inputs={
            "fb": {
                "budget": 5000.0,
                "kpis": {
                    "FB_AW_REACH": 500000.0,
                    "FB_AW_IMPRESSION": 1200000.0,
                    "FB_EN_ENGAGEMENT": 8000.0,
                },
            },
            "ig": {
                "budget": 4000.0,
                "kpis": {
                    "IG_AW_REACH": 200000.0,
                    "IG_EN_ENGAGEMENT": 0.05,
                },
            },
            "li": {
                "budget": 5000.0,
                "kpis": {
                    "LI_LG_LEADS": 80.0,
                    "LI_EN_ENGAGEMENT": 0.025,
                },
            },
        },
    )


def case_realistic_mixed_with_goal_values() -> None:
    _run(
        "CASE 5B: SAME B2B MIX, but strategist provides goal values "
        "(1 lead = £200, 1 engagement = £0.20, 1 reach impression = £0.0005)",
        objectives=["aw", "en", "lg"],
        total_budget=20000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "li": {"priority_1": "lg", "priority_2": "en"},
        },
        goal_values={"lg": 200.0, "en": 0.20, "aw": 0.0005},
        platform_inputs={
            "fb": {
                "budget": 5000.0,
                "kpis": {
                    "FB_AW_REACH": 500000.0,
                    "FB_AW_IMPRESSION": 1200000.0,
                    "FB_EN_ENGAGEMENT": 8000.0,
                },
            },
            "ig": {
                "budget": 4000.0,
                "kpis": {
                    "IG_AW_REACH": 200000.0,
                    "IG_EN_ENGAGEMENT": 0.05,
                },
            },
            "li": {
                "budget": 5000.0,
                "kpis": {
                    "LI_LG_LEADS": 80.0,
                    "LI_EN_ENGAGEMENT": 0.025,
                },
            },
        },
    )


def case_realistic_mixed_with_test_and_learn() -> None:
    _run(
        "CASE 5C: SAME B2B MIX + goal values + 12% test-and-learn carve-out",
        objectives=["aw", "en", "lg"],
        total_budget=20000.0,
        platforms=["fb", "ig", "li"],
        priorities={
            "fb": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "li": {"priority_1": "lg", "priority_2": "en"},
        },
        goal_values={"lg": 200.0, "en": 0.20, "aw": 0.0005},
        test_and_learn_pct=0.12,
        platform_inputs={
            "fb": {
                "budget": 5000.0,
                "kpis": {
                    "FB_AW_REACH": 500000.0,
                    "FB_AW_IMPRESSION": 1200000.0,
                    "FB_EN_ENGAGEMENT": 8000.0,
                },
            },
            "ig": {
                "budget": 4000.0,
                "kpis": {
                    "IG_AW_REACH": 200000.0,
                    "IG_EN_ENGAGEMENT": 0.05,
                },
            },
            "li": {
                "budget": 5000.0,
                "kpis": {
                    "LI_LG_LEADS": 80.0,
                    "LI_EN_ENGAGEMENT": 0.025,
                },
            },
        },
    )


if __name__ == "__main__":
    case_awareness_only()
    case_leads_only()
    case_engagement_only()
    case_traffic_only()
    case_big_difference()
    case_identical()
    case_same_kpi_different_budget()
    case_realistic_mixed()
    case_realistic_mixed_with_goal_values()
    case_realistic_mixed_with_test_and_learn()
    print(f"\n{SEP}\nAll behavioural cases completed.\n{SEP}")
