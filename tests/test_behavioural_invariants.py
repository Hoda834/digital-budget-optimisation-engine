"""Behavioural invariants, Plan B guarantees, and property-style checks.

Complements the printed walkthroughs in behavioural_check.py (which are a
human-readable demo, not collected by pytest) with the same expectations
stated as assertions, plus invariants that hold for randomised inputs:

- Behavioural expectations previously stated only in comments (a 10x more
  productive platform must dominate; identical platforms must split evenly)
  are asserted here.
- Plan B: every platform, not only the scaled-down top one, stays at or
  above its Module 2 floor; the freed budget is conserved; and the
  objective degradation stays within a stated bound for the bundled
  concentrated scenario.
- Diagnostic index: bounded, deductions never applied twice (the
  missing-forecast and data-quality deductions are mutually exclusive),
  and consistent with the classification.
- Golden regression: allocation shares, classification, and diagnostic
  index for a fixed reference scenario are pinned, so any change to a
  heuristic constant that silently moves the reference output fails here
  rather than being discovered by hand.
- Property checks: for randomised budgets and productivities, total
  allocation never exceeds the cap and floors are always respected.
"""
from __future__ import annotations

import random

import pytest

from core.wizard_state import WizardState
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module6 import run_module6
from modules.module7 import run_module7, _plan_b_risk_managed


def _pipeline(objectives, budget, duration, platforms, priorities,
              platform_inputs, floors=None, goal_values=None, reserve=0.0):
    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=objectives, raw_budget=budget,
        raw_duration_days=duration, raw_goal_values=goal_values or {},
        raw_test_and_learn_pct=reserve,
    )
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)
    if floors is not None:
        state.min_spend_per_platform = dict(floors)
        state.min_budget_per_goal = {}
    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)
    return state


def _platform_totals(lp):
    return {p: sum(v for v in g.values() if v > 1e-9)
            for p, g in lp.budget_per_platform_goal.items()}


# ---------------------------------------------------------------------------
# Behavioural expectations, asserted (previously comment-only in the demo)
# ---------------------------------------------------------------------------

def test_ten_times_more_productive_platform_dominates():
    state = _pipeline(
        ["lg"], 10_000.0, 30, ["fb", "ig"],
        {"fb": {"priority_1": "lg"}, "ig": {"priority_1": "lg"}},
        {"fb": {"budget": 4_000.0, "kpis": {"FB_LG_LEADS": 200.0}},
         "ig": {"budget": 4_000.0, "kpis": {"IG_LG_LEADS": 20.0}}},
        floors={},
    )
    pt = _platform_totals(state.module5_scenario_bundle.results_by_scenario["base"])
    assert pt.get("fb", 0) > pt.get("ig", 0), (
        "The 10x more productive platform must receive more budget.")
    total = sum(pt.values())
    assert pt["fb"] / total >= 0.5


def test_identical_platforms_split_evenly():
    state = _pipeline(
        ["lg"], 10_000.0, 30, ["fb", "ig"],
        {"fb": {"priority_1": "lg"}, "ig": {"priority_1": "lg"}},
        {"fb": {"budget": 4_000.0, "kpis": {"FB_LG_LEADS": 100.0}},
         "ig": {"budget": 4_000.0, "kpis": {"IG_LG_LEADS": 100.0}}},
        floors={},
    )
    pt = _platform_totals(state.module5_scenario_bundle.results_by_scenario["base"])
    assert pt.get("fb", 0) == pytest.approx(pt.get("ig", 0), rel=1e-6), (
        "Identical productivities must produce an even, non-arbitrary split.")


# ---------------------------------------------------------------------------
# Plan B: all-platform floors, conservation, and bounded degradation
# ---------------------------------------------------------------------------

def _concentrated_state():
    """Three platforms, one strongly dominant, generous floors on ALL of
    them, so the redistribution has floors to respect on every side."""
    return _pipeline(
        ["lg", "wt"], 60_000.0, 45, ["go_pmax", "fb", "ig"],
        {"go_pmax": {"priority_1": "lg", "priority_2": "wt"},
         "fb": {"priority_1": "lg", "priority_2": "wt"},
         "ig": {"priority_1": "lg", "priority_2": "wt"}},
        {"go_pmax": {"budget": 20_000.0, "historical_days": 45,
                      "kpis": {"GO_PMAX_LG_PURCHASES": 5_200.0,
                               "GO_PMAX_WT_CLICKS": 58_000.0}},
         "fb": {"budget": 8_000.0, "historical_days": 45,
                 "kpis": {"FB_LG_LEADS": 200.0}},
         "ig": {"budget": 8_000.0, "historical_days": 45,
                 "kpis": {"IG_LG_LEADS": 150.0}}},
        floors={"go_pmax": 3_000.0, "fb": 3_000.0, "ig": 3_000.0},
        goal_values={"lg": 45.0, "wt": 0.35},
        reserve=0.10,
    )


def test_plan_b_respects_every_platforms_floor_not_only_the_top():
    state = _concentrated_state()
    lp = state.module5_scenario_bundle.results_by_scenario["base"]
    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    assert plan_b is not None
    pb = {p: sum(v for v in g.values()) for p, g in plan_b.allocation.items()}
    for p, floor in state.min_spend_per_platform.items():
        assert pb.get(p, 0.0) >= floor - 1e-6, (
            f"Plan B allocation for {p} ({pb.get(p, 0):.2f}) fell below its "
            f"floor ({floor:.2f}); redistribution must never take a platform "
            f"under its Module 2 minimum.")


def test_plan_b_conserves_total_budget():
    state = _concentrated_state()
    lp = state.module5_scenario_bundle.results_by_scenario["base"]
    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    total_a = lp.total_budget_used
    total_b = sum(sum(g.values()) for g in plan_b.allocation.values())
    assert total_b == pytest.approx(total_a, rel=1e-9), (
        "Plan B must redistribute, not create or destroy, budget.")


def test_plan_b_objective_degradation_is_bounded():
    """The trade-off must be non-negative (Plan B never beats the optimum)
    and bounded: for the bundled concentrated scenario the cost of the
    default 0.70 diversification cap is a few per cent, so a reading above
    25% signals the redistribution heuristic has regressed badly."""
    state = _concentrated_state()
    lp = state.module5_scenario_bundle.results_by_scenario["base"]
    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    assert plan_b.tradeoff_percent is not None
    assert plan_b.tradeoff_percent >= -1e-9
    assert plan_b.tradeoff_percent <= 25.0, (
        f"Trade-off {plan_b.tradeoff_percent:.2f}% is implausibly large for "
        f"this scenario; the redistribution heuristic has likely regressed.")


# ---------------------------------------------------------------------------
# Diagnostic index invariants
# ---------------------------------------------------------------------------

def _full_insights(state, decision_mode=None):
    run_module6(state)
    bundle = state.module5_scenario_bundle
    fc = (state.module6_scenario_result.results_by_scenario
          if state.module6_scenario_result else {})
    if decision_mode is not None:
        return run_module7(state, bundle, fc, decision_mode=decision_mode)
    return run_module7(state, bundle, fc)


def test_diagnostic_index_bounded_and_consistent_with_classification():
    state = _concentrated_state()
    insights = _full_insights(state)
    for name, ins in insights.scenario_insights.items():
        assert 40 <= int(ins.confidence_score) <= 100
        # Consistency: a Corner-dominant scenario must carry at least the
        # high-concentration deduction, so its index cannot be pristine.
        if ins.classification == "Corner-dominant":
            assert ins.confidence_score <= 80, (
                f"{name}: Corner-dominant with index "
                f"{ins.confidence_score} implies a deduction was skipped.")


def test_missing_forecast_and_data_quality_deductions_are_exclusive():
    """With no forecasts supplied, three deductions legitimately apply to
    this two-cell scenario: missing forecast (18), two or fewer funded
    cells (8), and cross-scenario instability (10), giving exactly
    100 - 36 = 64. The data-quality deduction (12) must NOT stack on top
    of the missing-forecast one (a missing forecast is its root cause);
    if it did, the score would be 52 or lower."""
    state = _pipeline(
        ["lg"], 10_000.0, 30, ["fb", "ig"],
        {"fb": {"priority_1": "lg"}, "ig": {"priority_1": "lg"}},
        {"fb": {"budget": 4_000.0, "kpis": {"FB_LG_LEADS": 100.0}},
         "ig": {"budget": 4_000.0, "kpis": {"IG_LG_LEADS": 100.0}}},
        floors={},
    )
    bundle = state.module5_scenario_bundle
    insights = run_module7(state, bundle, {})  # no forecasts at all
    ins = insights.scenario_insights["base"]
    assert ins.confidence_score == 64, (
        f"Expected 100 - 18 - 8 - 10 = 64; got {ins.confidence_score}. A "
        f"lower value implies the data-quality deduction stacked on the "
        f"missing-forecast one; a higher value implies a deduction was "
        f"skipped.")


# ---------------------------------------------------------------------------
# Golden regression: pin the reference scenario's key outputs
# ---------------------------------------------------------------------------

def test_golden_reference_concentrated_scenario():
    """Reference outputs for the bundled concentrated scenario. If an
    intended change to a heuristic constant moves these, update the values
    here and in the documentation in the same commit; an unintended change
    fails loudly instead of shipping silently."""
    state = _concentrated_state()
    insights = _full_insights(state, decision_mode="Risk managed")
    lp = state.module5_scenario_bundle.results_by_scenario["base"]
    ins = insights.scenario_insights["base"]
    pt = _platform_totals(lp)
    total = sum(pt.values())

    assert max(pt.values()) / total == pytest.approx(0.889, abs=0.001)
    assert pt["go_pmax"] == pytest.approx(48_000.0, abs=1.0)
    assert pt["fb"] == pytest.approx(3_000.0, abs=1.0)
    assert pt["ig"] == pytest.approx(3_000.0, abs=1.0)
    assert ins.classification == "Scenario-sensitive"
    assert int(ins.confidence_score) == 78
    pb = {p: sum(v for v in g.values()) for p, g in ins.plan_b.allocation.items()}
    assert pb["go_pmax"] == pytest.approx(37_800.0, abs=1.0)
    assert ins.plan_b.tradeoff_percent == pytest.approx(2.38, abs=0.05)


# ---------------------------------------------------------------------------
# Property-style checks over randomised inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(8))
def test_property_allocation_never_exceeds_cap_and_respects_floors(seed):
    rng = random.Random(seed)
    budget = rng.uniform(5_000, 150_000)
    floor_fb = rng.uniform(0, budget * 0.10)
    floor_ig = rng.uniform(0, budget * 0.10)
    state = _pipeline(
        ["lg"], budget, 30, ["fb", "ig"],
        {"fb": {"priority_1": "lg"}, "ig": {"priority_1": "lg"}},
        {"fb": {"budget": rng.uniform(1_000, 20_000),
                 "kpis": {"FB_LG_LEADS": rng.uniform(10, 500)}},
         "ig": {"budget": rng.uniform(1_000, 20_000),
                 "kpis": {"IG_LG_LEADS": rng.uniform(10, 500)}}},
        floors={"fb": floor_fb, "ig": floor_ig},
    )
    for name, lp in state.module5_scenario_bundle.results_by_scenario.items():
        pt = _platform_totals(lp)
        assert sum(pt.values()) <= lp.effective_budget_cap + 0.01, (
            f"seed={seed} scenario={name}: allocation exceeds the cap.")
        for p, floor in state.min_spend_per_platform.items():
            assert pt.get(p, 0.0) >= floor - 0.01, (
                f"seed={seed} scenario={name}: {p} below its floor.")


# ---------------------------------------------------------------------------
# Scenario budget scaling: conservative scales down, optimistic is clamped
# ---------------------------------------------------------------------------

def test_scenario_budget_scaling_and_optimistic_clamp():
    """The conservative cap must be exactly 0.85x the base cap; the
    optimistic cap must EQUAL the base cap, not exceed it, because the
    optimistic envelope is deliberately clamped at the declared total
    budget (an optimistic plan can never demand more money than the user
    said they have). Asserting equality here codifies that design so a
    future change cannot silently reintroduce over-spending."""
    state = _pipeline(
        ["lg"], 10_000.0, 30, ["fb", "ig"],
        {"fb": {"priority_1": "lg"}, "ig": {"priority_1": "lg"}},
        {"fb": {"budget": 4_000.0, "kpis": {"FB_LG_LEADS": 200.0}},
         "ig": {"budget": 4_000.0, "kpis": {"IG_LG_LEADS": 20.0}}},
        floors={},
    )
    bundle = state.module5_scenario_bundle
    base = bundle.results_by_scenario["base"].effective_budget_cap
    cons = bundle.results_by_scenario["conservative"].effective_budget_cap
    opti = bundle.results_by_scenario["optimistic"].effective_budget_cap
    assert cons == pytest.approx(base * 0.85)
    assert opti == pytest.approx(base), (
        "Optimistic cap must be clamped at the declared budget, not scaled "
        "above it.")


def test_plan_b_recipients_actually_gain():
    """The budget freed from the top platform must land on the other
    platforms: each non-top platform's Plan B total is at least its Plan A
    total, and at least one strictly gains."""
    state = _concentrated_state()
    lp = state.module5_scenario_bundle.results_by_scenario["base"]
    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    pa = _platform_totals(lp)
    pb = {p: sum(v for v in g.values()) for p, g in plan_b.allocation.items()}
    top = max(pa, key=pa.get)
    gained = 0
    for p in pa:
        if p == top:
            continue
        assert pb.get(p, 0.0) >= pa[p] - 0.01, (
            f"{p} lost budget under Plan B; redistribution must only add "
            f"to non-top platforms.")
        if pb.get(p, 0.0) > pa[p] + 0.01:
            gained += 1
    assert gained >= 1, "No platform received any of the freed budget."
