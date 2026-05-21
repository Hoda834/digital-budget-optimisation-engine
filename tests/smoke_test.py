from __future__ import annotations

import pytest

from core.wizard_state import WizardState
from core.kpi_config import KPI_CONFIG
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5, Module5ScenarioBundle, run_module5_lp_scenarios, build_module5_input_from_state
from modules.module6 import run_module6, Module6ScenarioResult
from modules.module7 import run_module7


def _get_module5_bundle(state: WizardState) -> Module5ScenarioBundle:
    bundle = getattr(state, "module5_scenario_bundle", None)
    assert bundle is not None, "Module 5 did not produce a scenario bundle."
    assert isinstance(bundle, Module5ScenarioBundle)
    assert bundle.results_by_scenario, "Module 5 scenario bundle is empty."
    return bundle


def _get_module6_by_scenario(state: WizardState) -> dict:
    sres = getattr(state, "module6_scenario_result", None)
    if isinstance(sres, Module6ScenarioResult):
        return dict(sres.results_by_scenario)
    m6 = getattr(state, "module6_result", None)
    if m6 is not None:
        return {"base": m6}
    return {}


def _run_pipeline_to_module5(
    *,
    valid_goals=("aw", "en", "lg"),
    total_budget=10000.0,
    campaign_duration_days=30,
) -> WizardState:
    state = WizardState()

    complete_module1_and_advance(
        state,
        raw_objectives=list(valid_goals),
        raw_budget=total_budget,
        raw_duration_days=campaign_duration_days,
    )

    run_module2(
        state,
        selected_platforms=["fb", "ig", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "lg"},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )

    # Use canonical KPI variable names so the M3 -> M4 -> M5 chain finds them.
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {
                "time_window": "last 30 days",
                "budget": 4000.0,
                "kpis": {
                    "FB_AW_REACH": 200000.0,
                    "FB_AW_IMPRESSION": 500000.0,
                    "FB_EN_ENGAGEMENT": 8000.0,
                },
            },
            "ig": {
                "time_window": "last 30 days",
                "budget": 3000.0,
                "kpis": {
                    "IG_EN_ENGRATERATE": 0.045,
                    "IG_LG_LEADS": 120.0,
                },
            },
            "li": {
                "time_window": "last 30 days",
                "budget": 3000.0,
                "kpis": {
                    "LI_LG_LEADS": 80.0,
                },
            },
        },
    )

    run_module4(state, KPI_CONFIG)
    run_module5(state)
    return state


def test_full_pipeline_smoke() -> None:
    state = _run_pipeline_to_module5()

    assert state.module4_finalised is True
    assert state.module5_finalised is True

    run_module6(state)
    assert state.module6_finalised is True

    bundle = _get_module5_bundle(state)
    fc_by_scenario = _get_module6_by_scenario(state)

    m7 = run_module7(state, bundle, fc_by_scenario)
    assert m7 is not None

    scenario_insights = getattr(m7, "scenario_insights", None)
    assert isinstance(scenario_insights, dict)
    assert len(scenario_insights) > 0

    total_budget = float(state.total_budget or 0.0)
    assert total_budget > 0.0

    for _, lp_res in bundle.results_by_scenario.items():
        used = float(lp_res.total_budget_used or 0.0)
        # Each scenario has its own cap = scalar_m * total_budget; check the recorded cap.
        assert used <= lp_res.effective_budget_cap + 1e-6


def test_module2_excludes_non_priority_goals() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "en", "wt", "lg"],
        raw_budget=10000.0,
    )
    run_module2(
        state,
        selected_platforms=["fb"],
        priorities_input={"fb": {"priority_1": "aw", "priority_2": None}},
    )
    # Only AW is prioritised on FB; EN/WT/LG must not appear in goals_by_platform[fb].
    assert state.goals_by_platform["fb"] == ["aw"]
    assert state.platform_weights["fb"]["aw"] == pytest.approx(1.0)
    for g in ("en", "wt", "lg"):
        assert state.platform_weights["fb"].get(g, 0.0) == 0.0


def test_module2_requires_priority_1_on_selected_platform() -> None:
    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["aw"], raw_budget=10000.0)
    with pytest.raises(ValueError, match="Priority 1"):
        run_module2(
            state,
            selected_platforms=["fb"],
            priorities_input={"fb": {"priority_1": None, "priority_2": None}},
        )


def test_scenarios_produce_distinct_allocations() -> None:
    state = _run_pipeline_to_module5()
    bundle = _get_module5_bundle(state)

    assert {"base", "conservative", "optimistic"}.issubset(bundle.results_by_scenario.keys())

    base_alloc = bundle.results_by_scenario["base"].budget_per_platform_goal
    cons_alloc = bundle.results_by_scenario["conservative"].budget_per_platform_goal
    opti_alloc = bundle.results_by_scenario["optimistic"].budget_per_platform_goal

    def _flatten(a):
        return [round(a.get(p, {}).get(g, 0.0), 4) for p in a for g in a[p]]

    assert _flatten(base_alloc) != _flatten(cons_alloc), (
        "Conservative scenario should produce a different allocation from base."
    )
    assert _flatten(base_alloc) != _flatten(opti_alloc), (
        "Optimistic scenario should produce a different allocation from base."
    )

    # Total spend should also differ because scenarios change the budget cap.
    base_used = bundle.results_by_scenario["base"].total_budget_used
    cons_used = bundle.results_by_scenario["conservative"].total_budget_used
    opti_used = bundle.results_by_scenario["optimistic"].total_budget_used
    assert cons_used < base_used < opti_used


def test_rate_kpi_accepted_and_routed_through_r_pg() -> None:
    state = _run_pipeline_to_module5()
    lp_input = None
    # Re-extract the LP input from state to inspect r_pg directly.
    # We need a fresh state because module5_finalised blocks rebuild.
    fresh = _run_pipeline_to_module5()
    fresh.module5_finalised = False
    lp_input = build_module5_input_from_state(fresh)
    # IG has engagement rate; r_pg[ig][en] should be positive even though no count KPI was given for IG-EN.
    assert lp_input.r_pg.get("ig", {}).get("en", 0.0) > 0.0


def test_module3_rejects_nan_budget() -> None:
    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["aw"], raw_budget=10000.0)
    run_module2(
        state,
        selected_platforms=["fb"],
        priorities_input={"fb": {"priority_1": "aw", "priority_2": None}},
    )
    with pytest.raises(ValueError):
        finalise_module3_from_inputs(
            state,
            platform_inputs={
                "fb": {
                    "time_window": "last 30 days",
                    "budget": float("nan"),
                    "kpis": {"FB_AW_REACH": 1000.0},
                },
            },
        )


def test_wizard_state_reset() -> None:
    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["aw"], raw_budget=5000.0)
    assert state.module1_finalised is True
    state.reset()
    assert state.module1_finalised is False
    assert state.valid_goals == []
    assert state.current_step == 1


def test_module1_rejects_absurd_budget() -> None:
    from modules.module1 import MAX_REASONABLE_BUDGET, Module1ValidationError

    state = WizardState()
    with pytest.raises(Module1ValidationError, match="sanity ceiling"):
        complete_module1_and_advance(
            state,
            raw_objectives=["aw"],
            raw_budget=MAX_REASONABLE_BUDGET * 10,
        )


def test_module2_min_budget_per_goal_only_covers_prioritised_goals() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "en", "wt", "lg"],
        raw_budget=10000.0,
    )
    run_module2(
        state,
        selected_platforms=["fb"],
        priorities_input={"fb": {"priority_1": "aw", "priority_2": None}},
    )
    # Only AW is prioritised anywhere; WT/EN/LG should not reserve budget.
    assert set(state.min_budget_per_goal.keys()) == {"aw"}
    assert state.min_budget_per_goal["aw"] > 0


def test_module3_records_historical_days() -> None:
    state = _run_pipeline_to_module5()
    for p, pdata in state.module3_data.items():
        assert "historical_days" in pdata
        assert isinstance(pdata["historical_days"], int)
        assert pdata["historical_days"] > 0


def test_module3_falls_back_to_campaign_duration_for_historical_days() -> None:
    from modules.module3 import finalise_module3_from_inputs as fin

    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["aw"], raw_budget=10000.0)
    state.campaign_duration_days = 30  # not set by M1; caller sets directly
    run_module2(
        state,
        selected_platforms=["fb"],
        priorities_input={"fb": {"priority_1": "aw", "priority_2": None}},
    )
    fin(
        state,
        platform_inputs={
            "fb": {
                "budget": 4000.0,
                "kpis": {"FB_AW_REACH": 200000.0},
                # historical_days intentionally omitted
            }
        },
    )
    assert state.module3_data["fb"]["historical_days"] == 30


def test_module4_drops_extreme_cpu_outliers() -> None:
    from modules.module4 import run_module4, CPU_OUTLIER_MULTIPLE
    from modules.module3 import finalise_module3_from_inputs

    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["lg"], raw_budget=10000.0)
    state.campaign_duration_days = 30
    run_module2(
        state,
        selected_platforms=["fb", "ig", "li"],
        priorities_input={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    # FB and IG: 100 leads from £4k → CPU 40. LI: 0.001 leads from £4k → CPU 4M (outlier).
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 4000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 100.0}},
            "ig": {"budget": 4000.0, "historical_days": 30, "kpis": {"IG_LG_LEADS": 100.0}},
            "li": {"budget": 4000.0, "historical_days": 30, "kpis": {"LI_LG_LEADS": 0.001}},
        },
    )
    result = run_module4(state)
    assert "li" not in result.cpu_per_goal or "lg" not in result.cpu_per_goal.get("li", {})
    assert any("outlier" in row for row in result.skipped_rows)


def test_module5_attaches_cpu_per_goal_to_results() -> None:
    state = _run_pipeline_to_module5()
    bundle = _get_module5_bundle(state)
    base = bundle.results_by_scenario["base"]
    assert base.cpu_per_goal, "cpu_per_goal should be populated on the LP result"
    for name, res in bundle.results_by_scenario.items():
        assert res.cpu_per_goal == base.cpu_per_goal


def test_currency_and_duration_persisted() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw"],
        raw_budget="1.200,50",
        raw_currency="EUR",
        raw_duration_days=60,
    )
    assert state.currency == "EUR"
    assert state.total_budget == pytest.approx(1200.50)
    assert state.campaign_duration_days == 60


def test_module1_eu_decimal_budget() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw"],
        raw_budget="1.200,50",
    )
    assert state.total_budget == pytest.approx(1200.50)


def test_module1_currency_auto_detected_from_symbol() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw"],
        raw_budget="£5000",
    )
    assert state.currency == "GBP"
    assert state.total_budget == pytest.approx(5000.0)


def test_multi_objective_goal_normalisation_prevents_scale_dominance() -> None:
    """With three objectives and dedicated platforms, every platform should get
    meaningful budget — not just the one with the largest raw KPI count.

    Before goal normalisation FB-AW (100 reach/£) dominated LI-LG (0.016 leads/£)
    by 6,000× and swallowed £18k of a £20k budget, leaving LinkedIn with only the
    5% floor.  After normalisation the goal weights drive allocation, so LI (the
    only lead-gen platform) must receive more than its floor.
    """
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["aw", "en", "lg"], raw_budget=20000.0, raw_duration_days=30
    )
    run_module2(
        state,
        selected_platforms=["fb", "ig", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": "en"},
            "ig": {"priority_1": "en", "priority_2": "aw"},
            "li": {"priority_1": "lg", "priority_2": "en"},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 5000.0, "kpis": {"FB_AW_REACH": 500000.0, "FB_AW_IMPRESSION": 1200000.0, "FB_EN_ENGAGEMENT": 8000.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_AW_REACH": 200000.0, "IG_EN_ENGRATERATE": 0.05}},
            "li": {"budget": 5000.0, "kpis": {"LI_LG_LEADS": 80.0, "LI_EN_ENGRATERATE": 0.025}},
        },
    )
    run_module4(state)
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    alloc = base.budget_per_platform_goal
    li_total = sum(alloc.get("li", {}).values())
    fb_total = sum(alloc.get("fb", {}).values())

    assert li_total > 2000.0, (
        f"LinkedIn (only LG platform) should get >£2,000 but got £{li_total:.0f}. "
        "Goal normalisation may have regressed."
    )
    assert fb_total < 17000.0, (
        f"Facebook should not absorb >£17,000 of £20,000 but got £{fb_total:.0f}. "
        "Multi-objective scale bias may have regressed."
    )


def test_equal_productivity_gives_balanced_allocation() -> None:
    """When two platforms have identical KPI productivity the budget should be
    split roughly 50/50, not piled into one by LP solver tie-breaking."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    state = WizardState()
    complete_module1_and_advance(state, raw_objectives=["lg"], raw_budget=10000.0, raw_duration_days=30)
    run_module2(
        state,
        selected_platforms=["fb", "ig"],
        priorities_input={
            "fb": {"priority_1": "lg", "priority_2": None},
            "ig": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_LG_LEADS": 100.0}},
            "ig": {"budget": 4000.0, "kpis": {"IG_LG_LEADS": 100.0}},
        },
    )
    run_module4(state)
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    fb = sum(base.budget_per_platform_goal.get("fb", {}).values())
    ig = sum(base.budget_per_platform_goal.get("ig", {}).values())
    total = fb + ig
    assert total > 0
    assert abs(fb - ig) / total < 0.10, (
        f"Equal productivity should give a near-equal split. Got FB=£{fb:.0f}, IG=£{ig:.0f}."
    )


def test_goal_value_weights_shift_allocation_toward_high_value_goal() -> None:
    """When the user declares 'a lead is worth £200 to me, an impression £0.0005',
    the LP should allocate substantially more to lead-gen than when goal weights
    fall back to priority frequency.

    Same inputs as the multi-objective regression test, plus explicit goal values.
    """
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    def _alloc(goal_values=None) -> dict:
        s = WizardState()
        complete_module1_and_advance(
            s,
            raw_objectives=["aw", "en", "lg"],
            raw_budget=20000.0,
            raw_duration_days=30,
            raw_goal_values=goal_values,
        )
        run_module2(
            s,
            selected_platforms=["fb", "ig", "li"],
            priorities_input={
                "fb": {"priority_1": "aw", "priority_2": "en"},
                "ig": {"priority_1": "en", "priority_2": "aw"},
                "li": {"priority_1": "lg", "priority_2": "en"},
            },
        )
        finalise_module3_from_inputs(
            s,
            platform_inputs={
                "fb": {"budget": 5000.0, "kpis": {"FB_AW_REACH": 500000.0, "FB_AW_IMPRESSION": 1200000.0, "FB_EN_ENGAGEMENT": 8000.0}},
                "ig": {"budget": 4000.0, "kpis": {"IG_AW_REACH": 200000.0, "IG_EN_ENGRATERATE": 0.05}},
                "li": {"budget": 5000.0, "kpis": {"LI_LG_LEADS": 80.0, "LI_EN_ENGRATERATE": 0.025}},
            },
        )
        run_module4(s)
        run_module5(s)
        return s.module5_scenario_bundle.results_by_scenario["base"].budget_per_platform_goal

    baseline = _alloc(goal_values=None)
    weighted = _alloc(goal_values={"lg": 200.0, "en": 0.20, "aw": 0.0005})

    li_baseline = sum(baseline.get("li", {}).values())
    li_weighted = sum(weighted.get("li", {}).values())

    assert li_weighted > li_baseline, (
        f"With high £/lead value, LI (the LG platform) should get more than baseline. "
        f"Baseline LI=£{li_baseline:.0f}, weighted LI=£{li_weighted:.0f}."
    )


def test_test_and_learn_carveout_reduces_lp_budget() -> None:
    """A 10% test-and-learn carve-out should cap LP spend at 90% of the
    declared total and surface the reserved £ amount on every scenario."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    def _alloc(carve_out_pct=None) -> WizardState:
        s = WizardState()
        complete_module1_and_advance(
            s,
            raw_objectives=["aw", "lg"],
            raw_budget=10000.0,
            raw_duration_days=30,
            raw_test_and_learn_pct=carve_out_pct,
        )
        run_module2(
            s,
            selected_platforms=["fb", "li"],
            priorities_input={
                "fb": {"priority_1": "aw", "priority_2": None},
                "li": {"priority_1": "lg", "priority_2": None},
            },
        )
        finalise_module3_from_inputs(
            s,
            platform_inputs={
                "fb": {"budget": 4000.0, "kpis": {"FB_AW_REACH": 200000.0}},
                "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
            },
        )
        run_module4(s)
        run_module5(s)
        return s

    no_carve = _alloc(carve_out_pct=None)
    with_carve = _alloc(carve_out_pct=0.10)

    base_no = no_carve.module5_scenario_bundle.results_by_scenario["base"]
    base_yes = with_carve.module5_scenario_bundle.results_by_scenario["base"]

    # No carve-out → reserve is zero, LP can use the full £10k
    assert base_no.test_and_learn_reserve == pytest.approx(0.0)

    # 10% carve-out → £1,000 reserve, LP cap is £9,000
    assert base_yes.test_and_learn_reserve == pytest.approx(1000.0)
    assert base_yes.total_budget_used <= 9000.0 + 1e-6
    assert base_yes.effective_budget_cap == pytest.approx(9000.0)


def test_test_and_learn_carveout_rejects_out_of_range() -> None:
    """Carve-out >= 50% must be rejected; the LP would have nothing meaningful
    to allocate against."""
    from modules.module1 import Module1ValidationError

    state = WizardState()
    with pytest.raises(Module1ValidationError, match="below 50%"):
        complete_module1_and_advance(
            state,
            raw_objectives=["aw"],
            raw_budget=10000.0,
            raw_test_and_learn_pct=0.60,
        )


def test_test_and_learn_carveout_accepts_percentage_string() -> None:
    """Percentage strings like '15%' should be parsed to fractions."""
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw"],
        raw_budget=10000.0,
        raw_test_and_learn_pct="15%",
    )
    assert state.test_and_learn_pct == pytest.approx(0.15)


def test_module6_count_kpi_has_confidence_band() -> None:
    """Module 6 must surface a ±band on every count-KPI forecast so the
    output cannot be mistaken for a precise commitment."""
    from modules.module6 import compute_module6_forecast, DEFAULT_UNCERTAINTY_BAND
    from modules.module5 import Module5LPResult
    from core.kpi_config import KIND_COUNT

    lp = Module5LPResult(
        budget_per_platform_goal={"fb": {"lg": 5000.0}},
        budget_per_platform={"fb": 5000.0},
        total_budget_used=5000.0,
        objective_value=1.0,
        r_pg={"fb": {"lg": 1.0}},
        combined_weight_pg={"fb": {"lg": 1.0}},
        estimated_kpi_per_platform_goal={"fb": {"lg": 100.0}},
    )
    result = compute_module6_forecast({"fb": {"lg": {"FB_LG_LEADS": 0.025}}}, lp)
    count_rows = [r for r in result.rows if r.kpi_kind == KIND_COUNT]
    assert count_rows, "Expected at least one count-KPI row"
    row = count_rows[0]
    assert row.predicted_kpi_low < row.predicted_kpi < row.predicted_kpi_high
    expected_low = row.predicted_kpi * (1.0 - DEFAULT_UNCERTAINTY_BAND)
    assert row.predicted_kpi_low == pytest.approx(expected_low)


def test_module7_includes_forecast_caveat() -> None:
    """Every Module 7 output should include the standard caveat about
    historical-vs-future performance, plus an extension when goal values
    are missing."""
    state = _run_pipeline_to_module5()
    from modules.module6 import run_module6
    from modules.module7 import run_module7

    run_module6(state)
    bundle = state.module5_scenario_bundle
    fc = state.module6_scenario_result.results_by_scenario
    insights = run_module7(state, bundle, fc)

    assert insights.forecast_caveat
    assert "historical" in insights.forecast_caveat.lower()
    # No goal_value_per_unit set → extended note must appear
    assert "no per-goal economic values" in insights.forecast_caveat.lower()


def test_module6_rate_kpi_not_multiplied_by_budget() -> None:
    from modules.module6 import compute_module6_forecast, Module6ForecastRow
    from modules.module5 import Module5LPResult
    from core.kpi_config import KIND_RATE, KIND_COUNT

    lp_result = Module5LPResult(
        budget_per_platform_goal={"ig": {"en": 3000.0}},
        budget_per_platform={"ig": 3000.0},
        total_budget_used=3000.0,
        objective_value=1.0,
        r_pg={"ig": {"en": 0.045}},
        combined_weight_pg={"ig": {"en": 1.0}},
        estimated_kpi_per_platform_goal={"ig": {"en": 135.0}},
    )

    kpi_ratios = {"ig": {"en": {"IG_EN_ENGRATERATE": 0.045}}}
    result = compute_module6_forecast(kpi_ratios, lp_result)

    rate_rows = [r for r in result.rows if r.kpi_kind == KIND_RATE]
    assert len(rate_rows) == 1, "Expected one rate KPI row for IG engagement rate"
    row = rate_rows[0]
    # Predicted value must equal the rate itself, NOT rate × budget
    assert row.predicted_kpi == pytest.approx(0.045), (
        f"Rate KPI predicted value should be 0.045 (the rate), got {row.predicted_kpi}. "
        "Multiplying by budget would give wrong units."
    )
    assert row.predicted_kpi != pytest.approx(0.045 * 3000.0)
