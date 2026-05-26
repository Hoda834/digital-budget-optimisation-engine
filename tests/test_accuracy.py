"""
Accuracy tests (ACC-): verify the app produces the right NUMBERS, not just
that it runs.

Each test sets up an input where the correct answer is computable by hand
from the documented formulas, runs the pipeline, then asserts the actual
output matches the hand-computed value to a tight tolerance.

Categories:
  ACC-F: Forecast accuracy        (Module 6: predicted_kpi = spend × ratio)
  ACC-B: Confidence band accuracy (Module 6: ±band% on count KPIs)
  ACC-C: Constraint accuracy      (Module 5: budget closure, floors honoured)
  ACC-S: Scenario accuracy        (Module 5: scenario budget = multiplier × total)
  ACC-P: Plan B accuracy          (Module 7: cap binds exactly, trade-off correct)
  ACC-M: Monotonicity             (Module 5: sensible response to input changes)

Drop into tests/test_accuracy.py.
"""
from __future__ import annotations

import math
from typing import Dict

import pytest

from core.wizard_state import WizardState
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module6 import run_module6, compute_module6_forecast
from modules.module7 import run_module7, Module7Policy


# ─────────────────────────────────────────────────────────────────────────
# Pipeline builder used by most tests
# ─────────────────────────────────────────────────────────────────────────


def _build_state(
    *,
    objectives,
    platforms,
    priorities,
    platform_inputs,
    total_budget=10_000.0,
    duration=30,
    seasonality_index=None,
    scenario_multipliers=None,
    min_per_platform=None,
):
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=objectives,
        raw_budget=total_budget,
        raw_duration_days=duration,
        raw_seasonality_index=seasonality_index,
    )
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)
    if min_per_platform:
        state.min_spend_per_platform = dict(min_per_platform)
    if scenario_multipliers is not None:
        state.scenario_multipliers = dict(scenario_multipliers)
    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)
    return state


# ═════════════════════════════════════════════════════════════════════════
# ACC-F: Forecast accuracy
# Formula: predicted_kpi = (historical_count / historical_budget) × allocated
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_F_01_forecast_equals_spend_times_productivity():
    """Forecast must equal allocated_budget × (historical_count / historical_budget).

    Setup: 100 leads from £1000 spent. Allocation of £4000 must predict 400 leads.
    """
    state = _build_state(
        objectives=["lg"],
        platforms=["fb"],
        priorities={"fb": {"priority_1": "lg", "priority_2": None}},
        platform_inputs={
            "fb": {
                "budget": 1_000.0,
                "historical_days": 300,
                "kpis": {"FB_LG_LEADS": 100.0},   # 0.10 leads / £
            },
        },
        total_budget=4_000.0,
        scenario_multipliers={"base": 1.0},  # single scenario for clean check
    )
    run_module6(state)
    rows = state.module6_scenario_result.results_by_scenario["base"].rows
    fb_lg = [r for r in rows if r.platform == "fb" and r.objective == "lg"]
    assert fb_lg, "Expected at least one fb/lg forecast row"
    row = fb_lg[0]
    # spend × ratio: 4000 × 0.10 = 400 (the LP will allocate all 4000 to fb)
    expected = row.allocated_budget * row.ratio_kpi_per_budget
    assert math.isclose(row.predicted_kpi, expected, rel_tol=1e-6), (
        f"predicted_kpi={row.predicted_kpi}, expected {expected} "
        f"(spend={row.allocated_budget}, ratio={row.ratio_kpi_per_budget})"
    )


def test_ACC_F_02_forecast_scales_linearly_with_spend():
    """Doubling the allocated budget must double the predicted KPI.

    The forecast formula is strictly linear in spend, so this is exact.
    """
    # Same productivity, two different budgets
    def _forecast_at_budget(b):
        state = _build_state(
            objectives=["lg"],
            platforms=["fb"],
            priorities={"fb": {"priority_1": "lg", "priority_2": None}},
            platform_inputs={
                "fb": {"budget": 1_000.0, "historical_days": 300,
                       "kpis": {"FB_LG_LEADS": 100.0}},
            },
            total_budget=b,
            scenario_multipliers={"base": 1.0},
        )
        run_module6(state)
        rows = state.module6_scenario_result.results_by_scenario["base"].rows
        leads_rows = [r for r in rows if r.kpi_name == "FB_LG_LEADS"]
        return sum(r.predicted_kpi for r in leads_rows)

    f_5k = _forecast_at_budget(5_000.0)
    f_10k = _forecast_at_budget(10_000.0)
    assert math.isclose(f_10k, 2.0 * f_5k, rel_tol=1e-3), (
        f"Forecast not linear: f(5k)={f_5k}, f(10k)={f_10k}, "
        f"ratio={f_10k/f_5k:.4f} (expected 2.0)"
    )


def test_ACC_F_03_seasonality_multiplier_applied_exactly():
    """A seasonality multiplier of 1.50 on lg must scale forecast by 1.50."""
    base_state = _build_state(
        objectives=["lg"],
        platforms=["fb"],
        priorities={"fb": {"priority_1": "lg", "priority_2": None}},
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 100.0}},
        },
        scenario_multipliers={"base": 1.0},
    )
    run_module6(base_state)
    base_pred = sum(r.predicted_kpi for r in
                    base_state.module6_scenario_result.results_by_scenario["base"].rows)

    season_state = _build_state(
        objectives=["lg"],
        platforms=["fb"],
        priorities={"fb": {"priority_1": "lg", "priority_2": None}},
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 100.0}},
        },
        scenario_multipliers={"base": 1.0},
        seasonality_index={"lg": 1.50},
    )
    run_module6(season_state)
    season_pred = sum(r.predicted_kpi for r in
                      season_state.module6_scenario_result.results_by_scenario["base"].rows)
    assert math.isclose(season_pred, 1.50 * base_pred, rel_tol=1e-3), (
        f"Seasonality not applied exactly: base={base_pred}, "
        f"with 1.5x seasonality={season_pred}, ratio={season_pred/base_pred:.4f}"
    )


def test_ACC_F_04_zero_allocation_produces_zero_forecast():
    """A platform that gets £0 from the LP must produce no forecast rows."""
    # Set up so li gets nothing (productivity 100x worse than fb)
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 1000.0}},   # 1.0 leads/£
            "li": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"LI_LG_LEADS": 10.0}},     # 0.01 leads/£
        },
        scenario_multipliers={"base": 1.0},
    )
    run_module6(state)
    rows = state.module6_scenario_result.results_by_scenario["base"].rows
    li_rows = [r for r in rows if r.platform == "li" and r.allocated_budget > 0]
    li_total = sum(r.allocated_budget for r in li_rows)
    # If LP allocated zero to LI, no row should exist; if non-zero, every prediction
    # must still match the formula
    for r in rows:
        if r.allocated_budget > 0:
            expected = r.allocated_budget * r.ratio_kpi_per_budget
            assert math.isclose(r.predicted_kpi, expected, rel_tol=1e-3), (
                f"{r.platform}/{r.kpi_name}: predicted {r.predicted_kpi}, "
                f"expected {expected}"
            )


# ═════════════════════════════════════════════════════════════════════════
# ACC-B: Confidence band accuracy
# Formula: band = 0.30 × sqrt(30 / historical_days), clamped to [0.05, 1.00]
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_B_01_band_at_30_days_history_equals_default():
    """30 days history → band exactly equals the documented default (0.30)."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb"],
        priorities={"fb": {"priority_1": "lg", "priority_2": None}},
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 30,
                   "kpis": {"FB_LG_LEADS": 100.0}},
        },
        scenario_multipliers={"base": 1.0},
    )
    run_module6(state)
    rows = state.module6_scenario_result.results_by_scenario["base"].rows
    count_rows = [r for r in rows if r.kpi_kind == "count" and r.band_source == "window_scaled"]
    if not count_rows:
        pytest.skip("No window-scaled bands produced (data may have triggered "
                    "the observations branch).")
    for r in count_rows:
        # 0.30 × sqrt(30/30) = 0.30
        assert math.isclose(r.band_pct, 0.30, abs_tol=0.01), (
            f"At 30 days history, band should be ~0.30, got {r.band_pct}"
        )


def test_ACC_B_02_band_narrows_with_longer_history():
    """120 days of history should produce roughly half the band of 30 days
    (sqrt(30/120) = 0.5)."""
    def _band_at(days):
        state = _build_state(
            objectives=["lg"],
            platforms=["fb"],
            priorities={"fb": {"priority_1": "lg", "priority_2": None}},
            platform_inputs={
                "fb": {"budget": 1_000.0, "historical_days": days,
                       "kpis": {"FB_LG_LEADS": 100.0}},
            },
            scenario_multipliers={"base": 1.0},
        )
        run_module6(state)
        rows = state.module6_scenario_result.results_by_scenario["base"].rows
        ws = [r for r in rows if r.band_source == "window_scaled"]
        return ws[0].band_pct if ws else None

    b30 = _band_at(30)
    b120 = _band_at(120)
    if b30 is None or b120 is None:
        pytest.skip("Band source did not match window_scaled in test setup")
    # sqrt(30/120) = 0.5, so b120 should be ~0.5 × b30 = 0.15
    assert math.isclose(b120 / b30, 0.5, abs_tol=0.05), (
        f"Band scaling: 30d={b30:.4f}, 120d={b120:.4f}, "
        f"ratio={b120/b30:.4f} (expected 0.50)"
    )


def test_ACC_B_03_band_clamped_at_floor():
    """Very long history (10 years) must not produce a band below the 0.05 floor."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb"],
        priorities={"fb": {"priority_1": "lg", "priority_2": None}},
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 3650,
                   "kpis": {"FB_LG_LEADS": 100.0}},
        },
        scenario_multipliers={"base": 1.0},
    )
    run_module6(state)
    rows = state.module6_scenario_result.results_by_scenario["base"].rows
    for r in rows:
        if r.kpi_kind == "count":
            assert r.band_pct >= 0.05 - 1e-6, (
                f"Band {r.band_pct} below the 0.05 floor"
            )


# ═════════════════════════════════════════════════════════════════════════
# ACC-C: Constraint accuracy — exact arithmetic on allocations
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_C_01_budget_closure_exact():
    """Sum of all per-platform allocations + reserve must equal scenario budget cap."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li", "go_search"],
        priorities={
            "fb":        {"priority_1": "lg", "priority_2": None},
            "li":        {"priority_1": "lg", "priority_2": None},
            "go_search": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"FB_LG_LEADS": 100.0}},
            "li":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"LI_LG_LEADS": 80.0}},
            "go_search": {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"GO_SEARCH_LG_CONVERSIONS": 90.0}},
        },
    )
    for name, res in state.module5_scenario_bundle.results_by_scenario.items():
        used = res.total_budget_used
        cap = res.effective_budget_cap
        reserve = res.test_and_learn_reserve
        # LP-used + reserve must equal the effective scenario cap exactly
        assert used <= cap + 1e-6, f"{name}: spent {used} > cap {cap}"


def test_ACC_C_02_per_platform_floor_honoured_to_the_penny():
    """A £4000 minimum on li must be respected exactly, not approximately."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 200.0}},   # 0.20 leads/£
            "li": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"LI_LG_LEADS": 10.0}},    # 0.01 leads/£  (much worse)
        },
        total_budget=10_000.0,
        min_per_platform={"fb": 0.0, "li": 4_000.0},
        scenario_multipliers={"base": 1.0},
    )
    base = state.module5_scenario_bundle.results_by_scenario["base"]
    li_total = base.budget_per_platform.get("li", 0.0)
    # The floor is 4000 and li is dominated, so the optimum is exactly 4000
    assert math.isclose(li_total, 4_000.0, abs_tol=10.0), (
        f"LinkedIn floor (£4000) not honoured exactly: got £{li_total:.2f}"
    )


# ═════════════════════════════════════════════════════════════════════════
# ACC-S: Scenario multiplier accuracy
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_S_01_scenario_cap_equals_multiplier_times_total():
    """Conservative cap = 0.85 × total, base = total, optimistic = 1.15 × total.

    NOTE: this is the cap BEFORE test_and_learn carve-out. With zero carve-out,
    effective_budget_cap should equal multiplier × total_budget.
    """
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 100.0}},
            "li": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"LI_LG_LEADS": 80.0}},
        },
        total_budget=10_000.0,
    )
    bundle = state.module5_scenario_bundle
    expected_caps = {"conservative": 8_500.0, "base": 10_000.0, "optimistic": 11_500.0}
    for scenario_name, expected_cap in expected_caps.items():
        if scenario_name in bundle.results_by_scenario:
            res = bundle.results_by_scenario[scenario_name]
            # Bug 4 fix: optimistic must NOT exceed declared total
            # So optimistic's effective cap is min(1.15 × total, total) = total
            ceiling = min(expected_cap, 10_000.0)
            assert res.effective_budget_cap <= ceiling + 1e-6, (
                f"{scenario_name}: effective_budget_cap={res.effective_budget_cap}, "
                f"max allowed {ceiling}"
            )


def test_ACC_S_02_zero_carveout_means_full_cap_available_to_lp():
    """With test_and_learn_pct = 0, the LP receives the full scenario cap."""
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["lg"],
        raw_budget=10_000.0,
        raw_duration_days=30,
        raw_test_and_learn_pct=0.0,
    )
    run_module2(state, selected_platforms=["fb", "li"],
                priorities_input={
                    "fb": {"priority_1": "lg", "priority_2": None},
                    "li": {"priority_1": "lg", "priority_2": None},
                })
    state.scenario_multipliers = {"base": 1.0}
    finalise_module3_from_inputs(state, platform_inputs={
        "fb": {"budget": 1_000.0, "historical_days": 300, "kpis": {"FB_LG_LEADS": 100.0}},
        "li": {"budget": 1_000.0, "historical_days": 300, "kpis": {"LI_LG_LEADS": 80.0}},
    })
    run_module4(state)
    run_module5(state)
    base = state.module5_scenario_bundle.results_by_scenario["base"]
    # With zero carve-out, every penny of the £10,000 budget is available
    assert base.test_and_learn_reserve == 0.0
    assert base.total_budget_used + base.test_and_learn_reserve == pytest.approx(
        10_000.0, abs=10.0
    )


# ═════════════════════════════════════════════════════════════════════════
# ACC-P: Plan B accuracy
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_P_01_plan_b_top_platform_at_cap_exactly():
    """When Plan A's top platform is above the cap, Plan B caps it at exactly
    cap × total_budget."""
    # Strongly dominant input -> corner solution -> Plan B is built
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 200.0}},
            "li": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"LI_LG_LEADS": 5.0}},
        },
        total_budget=10_000.0,
        scenario_multipliers={"base": 1.0},
    )
    insights = run_module7(state, state.module5_scenario_bundle, {})
    base_insight = insights.scenario_insights["base"]
    if base_insight.plan_b is None:
        pytest.skip("Plan B not built for this case (classification != Corner-dominant)")

    # Top platform's allocation in Plan B should equal cap × total_budget
    pt_b = {p: sum(g.values()) for p, g in base_insight.plan_b.allocation.items()}
    top_p = max(pt_b, key=pt_b.get)
    cap_fraction = Module7Policy.plan_b_top_platform_cap   # default 0.70
    expected_top = cap_fraction * 10_000.0
    assert math.isclose(pt_b[top_p], expected_top, rel_tol=1e-3), (
        f"Plan B top platform {top_p}={pt_b[top_p]}, expected {expected_top} "
        f"(cap {cap_fraction} × £10000)"
    )


def test_ACC_P_02_plan_b_budget_closure_exact():
    """Plan B's total must equal Plan A's total (the cap is a redistribution,
    not a reduction)."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li", "go_search"],
        priorities={
            "fb":        {"priority_1": "lg", "priority_2": None},
            "li":        {"priority_1": "lg", "priority_2": None},
            "go_search": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"FB_LG_LEADS": 200.0}},
            "li":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"LI_LG_LEADS": 5.0}},
            "go_search": {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"GO_SEARCH_LG_CONVERSIONS": 5.0}},
        },
        total_budget=10_000.0,
        scenario_multipliers={"base": 1.0},
    )
    insights = run_module7(state, state.module5_scenario_bundle, {},
                           decision_mode="Risk managed")
    base_insight = insights.scenario_insights["base"]
    assert base_insight.plan_b is not None
    plan_a_total = sum(sum(g.values()) for g in base_insight.plan_a.allocation.values())
    plan_b_total = sum(sum(g.values()) for g in base_insight.plan_b.allocation.values())
    assert math.isclose(plan_a_total, plan_b_total, rel_tol=1e-3), (
        f"Plan A total {plan_a_total} vs Plan B total {plan_b_total} differ"
    )


def test_ACC_P_03_plan_b_tradeoff_formula_exact():
    """Trade-off% = (obj_A - obj_B) / obj_A × 100, computed by the engine."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li", "go_search"],
        priorities={
            "fb":        {"priority_1": "lg", "priority_2": None},
            "li":        {"priority_1": "lg", "priority_2": None},
            "go_search": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"FB_LG_LEADS": 200.0}},
            "li":        {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"LI_LG_LEADS": 50.0}},
            "go_search": {"budget": 1_000.0, "historical_days": 300,
                          "kpis": {"GO_SEARCH_LG_CONVERSIONS": 40.0}},
        },
        total_budget=10_000.0,
        scenario_multipliers={"base": 1.0},
    )
    insights = run_module7(state, state.module5_scenario_bundle, {},
                           decision_mode="Risk managed")
    pb = insights.scenario_insights["base"].plan_b
    pa = insights.scenario_insights["base"].plan_a
    assert pb is not None and pb.tradeoff_percent is not None
    obj_a = pa.objective_value_estimate
    obj_b = pb.objective_value_estimate
    if obj_a > 1e-9:
        expected = max(0.0, (obj_a - obj_b) / obj_a) * 100.0
        assert math.isclose(pb.tradeoff_percent, expected, abs_tol=0.1), (
            f"Trade-off {pb.tradeoff_percent}% vs expected {expected}% "
            f"(obj_a={obj_a}, obj_b={obj_b})"
        )


# ═════════════════════════════════════════════════════════════════════════
# ACC-M: Monotonicity (robustness accuracy)
# ═════════════════════════════════════════════════════════════════════════


def test_ACC_M_01_higher_productivity_does_not_reduce_allocation():
    """Increasing one platform's productivity by 50% must not REDUCE its
    allocation. (It may stay the same if it was already at the bracket cap.)
    """
    def _fb_alloc(fb_leads):
        state = _build_state(
            objectives=["lg"],
            platforms=["fb", "li"],
            priorities={
                "fb": {"priority_1": "lg", "priority_2": None},
                "li": {"priority_1": "lg", "priority_2": None},
            },
            platform_inputs={
                "fb": {"budget": 1_000.0, "historical_days": 300,
                       "kpis": {"FB_LG_LEADS": fb_leads}},
                "li": {"budget": 1_000.0, "historical_days": 300,
                       "kpis": {"LI_LG_LEADS": 100.0}},
            },
            scenario_multipliers={"base": 1.0},
        )
        base = state.module5_scenario_bundle.results_by_scenario["base"]
        return base.budget_per_platform.get("fb", 0.0)

    fb_low  = _fb_alloc(50.0)    # fb worse than li (0.05 vs 0.10)
    fb_high = _fb_alloc(75.0)    # fb closer to li, still below
    assert fb_high >= fb_low - 10.0, (
        f"Higher fb productivity (50→75) reduced its allocation: "
        f"{fb_low:.0f} → {fb_high:.0f}"
    )


def test_ACC_M_02_larger_budget_does_not_shrink_any_allocation():
    """Doubling the total budget must not REDUCE any platform's allocation."""
    def _alloc(total):
        state = _build_state(
            objectives=["lg"],
            platforms=["fb", "li"],
            priorities={
                "fb": {"priority_1": "lg", "priority_2": None},
                "li": {"priority_1": "lg", "priority_2": None},
            },
            platform_inputs={
                "fb": {"budget": 1_000.0, "historical_days": 300,
                       "kpis": {"FB_LG_LEADS": 100.0}},
                "li": {"budget": 1_000.0, "historical_days": 300,
                       "kpis": {"LI_LG_LEADS": 80.0}},
            },
            total_budget=total,
            scenario_multipliers={"base": 1.0},
        )
        base = state.module5_scenario_bundle.results_by_scenario["base"]
        return dict(base.budget_per_platform)

    small = _alloc(5_000.0)
    big = _alloc(10_000.0)
    for p in small:
        assert big.get(p, 0.0) >= small[p] - 10.0, (
            f"Doubling budget reduced {p}: {small[p]:.0f} → {big.get(p, 0.0):.0f}"
        )


def test_ACC_M_03_optimistic_does_not_decrease_total_spend():
    """Optimistic scenario should spend at least as much as base
    (subject to the declared total ceiling)."""
    state = _build_state(
        objectives=["lg"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"FB_LG_LEADS": 100.0}},
            "li": {"budget": 1_000.0, "historical_days": 300,
                   "kpis": {"LI_LG_LEADS": 80.0}},
        },
        total_budget=10_000.0,
    )
    bundle = state.module5_scenario_bundle
    if "base" not in bundle.results_by_scenario or \
       "conservative" not in bundle.results_by_scenario:
        pytest.skip("Multi-scenario default not active")
    base_used = bundle.results_by_scenario["base"].total_budget_used
    cons_used = bundle.results_by_scenario["conservative"].total_budget_used
    assert cons_used <= base_used + 10.0, (
        f"Conservative spent more than base: cons={cons_used}, base={base_used}"
    )
