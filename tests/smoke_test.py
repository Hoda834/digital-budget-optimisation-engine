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
                    "IG_EN_ENGAGEMENT": 0.045,
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
        # Tolerance is 1e-3 (= £0.001 on a £10k budget) to cover CBC's internal
        # tolerance plus cumulative FP error from summing many bracket variables.
        assert used <= lp_res.effective_budget_cap + 1e-3


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
            "ig": {"budget": 4000.0, "kpis": {"IG_AW_REACH": 200000.0, "IG_EN_ENGAGEMENT": 0.05}},
            "li": {"budget": 5000.0, "kpis": {"LI_LG_LEADS": 80.0, "LI_EN_ENGAGEMENT": 0.025}},
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
                "ig": {"budget": 4000.0, "kpis": {"IG_AW_REACH": 200000.0, "IG_EN_ENGAGEMENT": 0.05}},
                "li": {"budget": 5000.0, "kpis": {"LI_LG_LEADS": 80.0, "LI_EN_ENGAGEMENT": 0.025}},
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


def _run_carveout_pipeline(carve_out_pct=None) -> WizardState:
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

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


def test_test_and_learn_carveout_reduces_lp_budget() -> None:
    """A 10% test-and-learn carve-out should cap base LP spend at 90% of the
    declared total and surface the reserved £ amount on every scenario."""
    no_carve = _run_carveout_pipeline(carve_out_pct=None)
    with_carve = _run_carveout_pipeline(carve_out_pct=0.10)

    base_no = no_carve.module5_scenario_bundle.results_by_scenario["base"]
    base_yes = with_carve.module5_scenario_bundle.results_by_scenario["base"]

    # No carve-out → reserve is zero, LP can use the full £10k
    assert base_no.test_and_learn_reserve == pytest.approx(0.0)

    # 10% carve-out → £1,000 reserve at base, LP cap is £9,000
    assert base_yes.test_and_learn_reserve == pytest.approx(1000.0)
    assert base_yes.total_budget_used <= 9000.0 + 1e-6
    assert base_yes.effective_budget_cap == pytest.approx(9000.0)


def test_carveout_invariant_lp_used_plus_reserve_within_scenario_total() -> None:
    """Across every scenario, lp_used + reserve must not exceed
    declared_total × scenario_scalar. This is the contract that was broken
    when the carve-out was applied before scenario scaling (optimistic
    used to over-spend the declared total)."""
    state = _run_carveout_pipeline(carve_out_pct=0.12)
    declared_total = float(state.total_budget)
    bundle = state.module5_scenario_bundle

    for name, res in bundle.results_by_scenario.items():
        scalar = bundle.scenario_multipliers.get(name, 1.0)
        scenario_total = declared_total * scalar
        # reserve = scenario_total × tl_pct
        assert res.test_and_learn_reserve == pytest.approx(scenario_total * 0.12)
        # lp_used + reserve must not exceed scenario_total
        assert res.total_budget_used + res.test_and_learn_reserve <= scenario_total + 1e-6, (
            f"Scenario {name!r}: lp_used={res.total_budget_used:.2f} + "
            f"reserve={res.test_and_learn_reserve:.2f} exceeds scenario_total={scenario_total:.2f}."
        )


def test_zero_carveout_equivalent_to_no_carveout() -> None:
    """Explicit 0.0 must produce identical allocations to omitting the param."""
    none_state = _run_carveout_pipeline(carve_out_pct=None)
    zero_state = _run_carveout_pipeline(carve_out_pct=0.0)

    for name in ("conservative", "base", "optimistic"):
        none_alloc = none_state.module5_scenario_bundle.results_by_scenario[name].budget_per_platform_goal
        zero_alloc = zero_state.module5_scenario_bundle.results_by_scenario[name].budget_per_platform_goal
        for p in none_alloc:
            for g in none_alloc[p]:
                assert zero_alloc[p][g] == pytest.approx(none_alloc[p][g]), (
                    f"0% carve-out diverged from no carve-out at {name}/{p}/{g}."
                )


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


def test_test_and_learn_carveout_bare_string_treated_as_fraction() -> None:
    """A string '15' (no '%' suffix) must be treated as a fraction, not 15%,
    so the contract matches int/float behaviour. 15.0 is out of range so it
    must be rejected — proving the heuristic is gone."""
    from modules.module1 import Module1ValidationError

    state = WizardState()
    with pytest.raises(Module1ValidationError, match="below 50%"):
        complete_module1_and_advance(
            state,
            raw_objectives=["aw"],
            raw_budget=10000.0,
            raw_test_and_learn_pct="15",
        )


def test_module5_rejects_invalid_state_carveout() -> None:
    """If state.test_and_learn_pct somehow holds an out-of-range value
    (direct mutation, future bug), Module 5 must raise rather than silently
    optimise the full budget."""
    from modules.module5 import build_module5_input_from_state, Module5ValidationError

    state = _run_carveout_pipeline(carve_out_pct=0.10)
    state.module5_finalised = False
    state.test_and_learn_pct = 0.75  # bypass Module 1 validation
    with pytest.raises(Module5ValidationError, match="test_and_learn_pct"):
        build_module5_input_from_state(state)


def test_montecarlo_produces_per_platform_distribution() -> None:
    """Monte Carlo should produce a per-platform distribution with non-trivial
    spread reflecting the productivity noise."""
    from modules.module5 import run_module5_montecarlo

    state = _run_pipeline_to_module5()
    mc = run_module5_montecarlo(state, n_trials=50, seed=42)

    assert mc.n_trials > 0
    assert len(mc.per_platform) >= 2
    for s in mc.per_platform:
        assert s.mean >= 0.0
        assert s.p5 <= s.p50 <= s.p95
        if s.mean > 1.0:
            # Real allocations should have some spread under perturbation
            assert s.std >= 0.0


def test_montecarlo_seed_reproducibility() -> None:
    """Same seed → same distribution.  This is the floor for any honest
    Monte Carlo: results must be reproducible for audit."""
    from modules.module5 import run_module5_montecarlo

    state = _run_pipeline_to_module5()
    a = run_module5_montecarlo(state, n_trials=30, seed=123)
    b = run_module5_montecarlo(state, n_trials=30, seed=123)

    a_by_p = {s.platform: s.mean for s in a.per_platform}
    b_by_p = {s.platform: s.mean for s in b.per_platform}
    assert a_by_p.keys() == b_by_p.keys()
    for p in a_by_p:
        assert a_by_p[p] == pytest.approx(b_by_p[p])


def test_montecarlo_flags_unstable_platform() -> None:
    """When productivity noise is high enough that the LP picks materially
    different winners across trials, the unstable platform list should
    surface those platforms."""
    from modules.module5 import run_module5_montecarlo
    from modules.module6 import _coefficient_of_variation
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg"], raw_budget=10000.0, raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    # Two platforms with near-identical productivity AND high observed
    # variance → LP picks an arbitrary winner each trial → high allocation CV.
    high_variance_obs = [50.0, 100.0, 150.0, 200.0, 60.0]
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 3000.0, "kpis": {"FB_LG_LEADS": 100.0},
                   "kpi_observations": {"FB_LG_LEADS": high_variance_obs}},
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 100.0},
                   "kpi_observations": {"LI_LG_LEADS": high_variance_obs}},
        },
    )
    run_module4(state)
    state.min_spend_per_platform = {"fb": 0.0, "li": 0.0}
    run_module5(state)

    # The CV on the observed data should be well above the instability threshold
    obs_cv = _coefficient_of_variation(high_variance_obs)
    assert obs_cv is not None and obs_cv > 0.30, f"Setup CV too low: {obs_cv}"

    mc = run_module5_montecarlo(state, n_trials=80, seed=7, instability_cv_threshold=0.15)
    # At least one of the two platforms should be flagged unstable given the
    # combination of degenerate productivity + high noise.
    assert mc.unstable_platforms, (
        f"Expected at least one unstable platform under high-variance setup, "
        f"got: unstable={mc.unstable_platforms}, "
        f"per_platform_cv={[(s.platform, s.cv) for s in mc.per_platform]}"
    )


def test_montecarlo_rejects_tiny_n_trials() -> None:
    from modules.module5 import run_module5_montecarlo, Module5ValidationError

    state = _run_pipeline_to_module5()
    with pytest.raises(Module5ValidationError, match="too small"):
        run_module5_montecarlo(state, n_trials=5)


def test_using_economic_weights_logs_rank_skip(caplog) -> None:
    """When goal_value_per_unit is present, the rank-based fallback must be
    skipped — and that decision should be auditable in the logs."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    import logging

    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "lg"],
        raw_budget=10000.0,
        raw_duration_days=30,
        raw_goal_values={"lg": 200.0, "aw": 0.0005},
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_AW_REACH": 200000.0}},
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
        },
    )
    run_module4(state)

    with caplog.at_level(logging.INFO, logger="modules.module5"):
        run_module5(state)

    text = " ".join(rec.message for rec in caplog.records)
    assert "economic goal weights" in text.lower()
    assert "rank-based weights from priority_rank are not consulted" in text


def test_using_rank_weights_logs_recommendation(caplog) -> None:
    """When goal_value_per_unit is absent, the rank-based path is used and
    we should suggest switching to economic values."""
    import logging

    state = _run_pipeline_to_module5()  # no goal values
    with caplog.at_level(logging.INFO, logger="modules.module5"):
        # Re-run M5 by bypassing the finalised guard.  Reset just enough state.
        state.module5_finalised = False
        from modules.module5 import build_module5_input_from_state, run_module5_lp_scenarios
        bundle = run_module5_lp_scenarios(build_module5_input_from_state(state))
        assert bundle is not None  # use it

    text = " ".join(rec.message for rec in caplog.records)
    assert "rank-based goal weights" in text.lower()
    assert "supply economic values" in text.lower()


def test_data_quality_shrinkage_compresses_productivity_gap() -> None:
    """A short-window platform's productivity (post-shrinkage) should be
    closer to the cross-platform mean than the same platform with a long
    window.  We assert on the r_pg values the LP actually sees, not on
    final allocations — shrinkage compresses ranking magnitudes but can't
    flip them within a goal, so the LP's *ordering* is unchanged."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import build_module5_input_from_state

    def _r_pg(hist_days_li: int) -> dict:
        s = WizardState()
        complete_module1_and_advance(
            s, raw_objectives=["lg"], raw_budget=10000.0, raw_duration_days=30,
        )
        run_module2(
            s,
            selected_platforms=["fb", "li"],
            priorities_input={
                "fb": {"priority_1": "lg", "priority_2": None},
                "li": {"priority_1": "lg", "priority_2": None},
            },
        )
        finalise_module3_from_inputs(
            s,
            platform_inputs={
                "fb": {"budget": 5000.0, "historical_days": 365,
                       "kpis": {"FB_LG_LEADS": 100.0}},  # 0.02 leads/£
                "li": {"budget": 5000.0, "historical_days": hist_days_li,
                       "kpis": {"LI_LG_LEADS": 500.0}},  # 0.10 leads/£ raw
            },
        )
        run_module4(s)
        return build_module5_input_from_state(s).r_pg

    # After per-goal normalisation, sums to 1.0.  The DIFFERENCE between
    # FB and LI shares is what shrinkage compresses: short LI history →
    # smaller gap, long LI history → larger gap.
    short_rpg = _r_pg(hist_days_li=7)
    long_rpg = _r_pg(hist_days_li=365)

    short_gap = abs(short_rpg["li"]["lg"] - short_rpg["fb"]["lg"])
    long_gap = abs(long_rpg["li"]["lg"] - long_rpg["fb"]["lg"])

    assert long_gap > short_gap, (
        f"With 365-day LI history the LP should see a wider productivity "
        f"gap (got {long_gap:.4f}) than with 7-day LI history "
        f"({short_gap:.4f}) — shrinkage is not pooling short-window "
        f"estimates toward the mean."
    )


def test_iterative_resolve_after_policy_mutation() -> None:
    """The library must support iterative re-solve: mutate policy fields,
    reset M4-M7 finalised flags, re-run the pipeline.  This is the
    library half of the Streamlit 'Re-solve with these changes' button —
    if it doesn't work in Python, it won't work in the UI either."""
    from modules.module4 import run_module4
    from modules.module5 import run_module5
    from modules.module6 import run_module6

    state = _run_pipeline_to_module5()
    run_module6(state)
    initial_alloc = state.module5_scenario_bundle.results_by_scenario["base"].budget_per_platform_goal
    initial_fb = sum(initial_alloc.get("fb", {}).values())

    # Mutate: heavy carve-out + LinkedIn floor + reset flags + current_step
    state.test_and_learn_pct = 0.20
    state.min_spend_per_platform = {"fb": 0.0, "ig": 0.0, "li": 5000.0}
    state.module4_finalised = False
    state.module5_finalised = False
    state.module6_finalised = False
    state.module7_finalised = False
    state.current_step = 4

    # Re-run the downstream pipeline
    run_module4(state)
    run_module5(state)
    run_module6(state)

    new_alloc = state.module5_scenario_bundle.results_by_scenario["base"].budget_per_platform_goal
    new_li = sum(new_alloc.get("li", {}).values())
    new_fb = sum(new_alloc.get("fb", {}).values())

    # LI was floored at £5k, so it must take at least £5k
    assert new_li >= 5000.0 - 1e-3, (
        f"LI floor of £5,000 should bind; got £{new_li:.0f}"
    )
    # FB was the dominant platform in the original allocation; with a £5k LI
    # floor and a 20% carve-out, FB should now get materially less
    assert new_fb < initial_fb, (
        f"Adding LI floor + carve-out should reduce FB allocation; "
        f"initial £{initial_fb:.0f} → new £{new_fb:.0f}"
    )


def test_csv_import_parses_meta_export() -> None:
    """A Meta Ads Manager-style CSV should pre-fill Reach, Impressions,
    Engagement, Link Clicks, Leads, and Amount Spent without the user
    typing anything."""
    from core.csv_import import parse_platform_csv

    csv = (
        "Campaign name,Reach,Impressions,Post engagement,Link clicks,Leads,Amount spent (GBP)\n"
        "Campaign A,200000,500000,8000,4500,80,3000\n"
        "Campaign B,150000,300000,4000,2500,40,2000\n"
    )
    result = parse_platform_csv(csv.encode("utf-8"), "fb")
    assert "error" not in result
    assert result["budget"] == pytest.approx(5000.0)
    assert result["kpis"]["FB_AW_REACH"] == pytest.approx(350000.0)
    assert result["kpis"]["FB_AW_IMPRESSION"] == pytest.approx(800000.0)
    assert result["kpis"]["FB_EN_ENGAGEMENT"] == pytest.approx(12000.0)
    assert result["kpis"]["FB_WT_CLICKS"] == pytest.approx(7000.0)
    assert result["kpis"]["FB_LG_LEADS"] == pytest.approx(120.0)


def test_csv_import_google_no_engagement_kpi() -> None:
    """Google surfaces have no engagement KPI (Engagement category
    dropped — see KPI_CONFIG comment for rationale: CTR was a rate and
    'engaged clicks' would duplicate WT_CLICKS).  A CTR column in the
    upload is silently ignored; counts still parse normally."""
    from core.csv_import import parse_platform_csv

    csv_pct = (
        "Campaign,Impressions,Clicks,CTR,Conversions,Cost\n"
        "Camp,1000000,45000,4.50%,300,2500\n"
    )
    result = parse_platform_csv(csv_pct.encode("utf-8"), "go_search")
    assert "GO_SEARCH_EN_CTR" not in result["kpis"], (
        "Google engagement KPI should no longer exist"
    )
    assert result["kpis"]["GO_SEARCH_LG_CONVERSIONS"] == pytest.approx(300.0)
    assert result["kpis"]["GO_SEARCH_AW_IMPRESSION"] == pytest.approx(1000000.0)
    assert result["kpis"]["GO_SEARCH_WT_CLICKS"] == pytest.approx(45000.0)
    assert result["budget"] == pytest.approx(2500.0)


def test_csv_import_unsupported_platform_returns_error() -> None:
    """A platform code that isn't in the CSV-import catalogue should
    return a helpful error rather than silently failing.  All 12 active
    platforms (fb/ig/li/yt/tt/pt/tw/sn/rd/go_search/go_display/go_pmax)
    are now supported, so use a made-up code to exercise the rejection
    path."""
    from core.csv_import import parse_platform_csv

    result = parse_platform_csv(b"x,y\n1,2\n", "made_up_platform")
    assert "error" in result and "not supported" in result["error"].lower()


def test_csv_import_reports_missing_kpis() -> None:
    """A CSV that's missing a column we'd expect should be reported in
    missing_kpis so the UI can prompt the user to fill it in manually."""
    from core.csv_import import parse_platform_csv

    # Meta export missing Leads column
    csv = "Reach,Impressions,Amount spent\n100000,200000,1000\n"
    result = parse_platform_csv(csv.encode("utf-8"), "fb")
    assert "FB_LG_LEADS" in result["missing_kpis"]
    assert result["kpis"].get("FB_AW_REACH") == pytest.approx(100000.0)


def test_google_pipeline_end_to_end() -> None:
    """Google Search — typically the #1 paid-media channel for UK
    marketers — should flow through M1 → M7 just like a Meta platform.
    Verifies that the three Google surfaces (Search / Display / PMax)
    each have their own catalogue, minimum, and platform code."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import (
        run_module5,
        PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH,
    )
    from modules.module6 import run_module6
    from modules.module7 import run_module7
    from core.kpi_config import KPI_CONFIG

    for code in ("go_search", "go_display", "go_pmax"):
        assert code in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH, (
            f"{code} missing from minimums table"
        )
    catalog = KPI_CONFIG
    search_vars = {row["var"] for row in catalog if row["platform"] == "go_search"}
    # Google has no engagement KPI (CTR was a rate, dropped to keep
    # platform-uniform-units invariant); Awareness / Traffic / Conversion
    # / Purchases remain.
    assert {
        "GO_SEARCH_AW_IMPRESSION",
        "GO_SEARCH_WT_CLICKS", "GO_SEARCH_LG_CONVERSIONS",
    } <= search_vars

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["wt", "lg"], raw_budget=10000.0, raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["go_search", "fb"],
        priorities_input={
            "go_search": {"priority_1": "lg", "priority_2": "wt"},
            "fb": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "go_search": {"budget": 3000.0, "historical_days": 90,
                          "kpis": {"GO_SEARCH_LG_CONVERSIONS": 120.0,
                                   "GO_SEARCH_WT_CLICKS": 4500.0}},
            "fb": {"budget": 3000.0, "historical_days": 90,
                   "kpis": {"FB_LG_LEADS": 90.0}},
        },
    )
    run_module4(state)
    run_module5(state)
    run_module6(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    go_allocated = sum(base.budget_per_platform_goal.get("go_search", {}).values())
    assert go_allocated > 0, "Google Search should receive non-zero allocation"

    insights = run_module7(state, state.module5_scenario_bundle,
                          state.module6_scenario_result.results_by_scenario)
    assert "base" in insights.scenario_insights


def test_tiktok_pipeline_end_to_end() -> None:
    """A new-catalog platform (TikTok) should flow through M1 → M5 → M6 → M7
    without special-casing, with its own KPI vars and effective minimum."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import (
        run_module5,
        PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH,
    )
    from modules.module6 import run_module6
    from modules.module7 import run_module7

    assert "tt" in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH, "TikTok missing from catalog"

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["aw", "lg"], raw_budget=10000.0, raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["tt", "li"],
        priorities_input={
            "tt": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "tt": {"budget": 3000.0, "kpis": {"TT_AW_VIEWS": 500000.0}},
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
        },
    )
    run_module4(state)
    run_module5(state)
    run_module6(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    tt_allocated = sum(base.budget_per_platform_goal.get("tt", {}).values())
    li_allocated = sum(base.budget_per_platform_goal.get("li", {}).values())
    assert tt_allocated > 0, "TikTok should receive non-zero allocation"
    assert li_allocated > 0, "LinkedIn should receive non-zero allocation"

    insights = run_module7(state, state.module5_scenario_bundle,
                          state.module6_scenario_result.results_by_scenario)
    assert "base" in insights.scenario_insights


def test_seasonality_shifts_allocation_toward_boosted_goal() -> None:
    """A seasonality boost for one goal should pull more LP budget toward
    the platform serving that goal."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    def _alloc(seasonality=None) -> dict:
        s = WizardState()
        complete_module1_and_advance(
            s,
            raw_objectives=["aw", "lg"],
            raw_budget=10000.0,
            raw_duration_days=30,
            raw_seasonality_index=seasonality,
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
        return s.module5_scenario_bundle.results_by_scenario["base"].budget_per_platform_goal

    flat = _alloc(seasonality=None)
    boosted = _alloc(seasonality={"lg": 3.0, "aw": 0.5})

    flat_li = sum(flat.get("li", {}).values())
    boosted_li = sum(boosted.get("li", {}).values())
    assert boosted_li > flat_li, (
        f"3× boost on LG + 0.5× on AW should shift budget toward LI (the LG platform). "
        f"Flat LI=£{flat_li:.0f}, boosted LI=£{boosted_li:.0f}."
    )


def test_seasonality_scales_count_kpi_forecast() -> None:
    """A 0.4× seasonality multiplier on reach should produce a forecast
    that is 0.4× the un-seasoned forecast for the same allocation."""
    from modules.module6 import compute_module6_forecast
    from modules.module5 import Module5LPResult

    lp = Module5LPResult(
        budget_per_platform_goal={"fb": {"aw": 5000.0}},
        budget_per_platform={"fb": 5000.0},
        total_budget_used=5000.0,
        objective_value=1.0,
        r_pg={"fb": {"aw": 1.0}},
        combined_weight_pg={"fb": {"aw": 1.0}},
        estimated_kpi_per_platform_goal={"fb": {"aw": 500000.0}},
    )
    kpi_ratios = {"fb": {"aw": {"FB_AW_REACH": 100.0}}}

    flat = compute_module6_forecast(kpi_ratios=kpi_ratios, module5_result=lp)
    seasoned = compute_module6_forecast(
        kpi_ratios=kpi_ratios, module5_result=lp,
        seasonality_index={"aw": 0.4},
    )
    flat_row = next(r for r in flat.rows if r.kpi_name == "FB_AW_REACH")
    seasoned_row = next(r for r in seasoned.rows if r.kpi_name == "FB_AW_REACH")
    assert seasoned_row.predicted_kpi == pytest.approx(0.4 * flat_row.predicted_kpi)


def test_seasonality_rejects_implausible_multiplier() -> None:
    """Values >10× or <0.1× should be rejected as likely typos (percentage
    entered instead of multiplier)."""
    from modules.module1 import Module1ValidationError

    state = WizardState()
    with pytest.raises(Module1ValidationError, match="implausible"):
        complete_module1_and_advance(
            state, raw_objectives=["aw"], raw_budget=10000.0,
            raw_seasonality_index={"aw": 250.0},  # user typed "250%" expecting 2.5
        )


def test_module5_warns_when_platform_below_effective_minimum() -> None:
    """LinkedIn's industry-typical learning-phase exit threshold is ~£2k/month.
    When the LP allocates LI below that — even because the user floor forces
    a small allocation — Module 5 should surface a warning."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5, PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg"], raw_budget=10000.0, raw_duration_days=30,
    )
    # Both platforms compete on the same goal (LG); FB will dominate because
    # it has 10× the productivity per £.  LI only gets money because of the
    # forced floor.
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "lg", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            # Generous historical_days so data-quality shrinkage doesn't pool
            # the productivity gap away — we want a clean 10× advantage that
            # the LP can honour.
            "fb": {"budget": 3000.0, "historical_days": 365,
                   "kpis": {"FB_LG_LEADS": 300.0}},  # 0.1 leads/£
            "li": {"budget": 3000.0, "historical_days": 365,
                   "kpis": {"LI_LG_LEADS": 30.0}},   # 0.01 leads/£
        },
    )
    run_module4(state)
    # Floor LI at £1,000 — below the £2,000 effective threshold but above zero.
    # FB has no floor; the LP will minimise LI to exactly £1,000.
    state.min_spend_per_platform = {"fb": 0.0, "li": 1000.0}
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    li_allocated = sum(base.budget_per_platform_goal.get("li", {}).values())
    li_threshold = PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH["li"]  # 2000 for 30 days
    assert 0.0 < li_allocated < li_threshold, (
        f"Test setup expected LI allocated below £{li_threshold:.0f} threshold, "
        f"got £{li_allocated:.0f}"
    )
    assert any("li" in w.lower() for w in base.effective_minimum_warnings), (
        f"LI was allocated £{li_allocated:.0f} (below £{li_threshold:.0f} threshold) "
        f"but no warning was surfaced. Warnings: {base.effective_minimum_warnings}"
    )


def test_module5_effective_minimum_scales_with_campaign_duration() -> None:
    """A 60-day campaign should require twice the per-platform monthly
    threshold; a 15-day campaign half of it."""
    from modules.module5 import (
        build_module5_input_from_state,
        PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH,
    )

    state_60 = _run_pipeline_to_module5(campaign_duration_days=60)
    state_60.module5_finalised = False
    inp_60 = build_module5_input_from_state(state_60)

    state_15 = _run_pipeline_to_module5(campaign_duration_days=15)
    state_15.module5_finalised = False
    inp_15 = build_module5_input_from_state(state_15)

    for p, monthly in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH.items():
        if p in inp_60.effective_minimum_per_platform:
            assert inp_60.effective_minimum_per_platform[p] == pytest.approx(monthly * 2.0)
        if p in inp_15.effective_minimum_per_platform:
            assert inp_15.effective_minimum_per_platform[p] == pytest.approx(monthly * 0.5)


def test_module5_reports_binding_budget_cap() -> None:
    """With no per-platform / per-goal floors, the only constraint the LP can
    hit is the total budget cap — and it should always hit it for a problem
    with positive productivity."""
    state = _run_pipeline_to_module5()
    base = state.module5_scenario_bundle.results_by_scenario["base"]
    names = [bc.name for bc in base.binding_constraints]
    assert "budget_cap" in names, (
        f"Expected budget_cap to bind on a budget-limited problem, got: {names}"
    )
    # Shadow prices dict should be populated for every named constraint
    assert "budget_cap" in base.shadow_prices


def test_module5_reports_binding_platform_floor() -> None:
    """When a platform minimum forces the LP into a sub-optimal allocation,
    that floor must appear in binding_constraints with the right target."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["aw", "lg"], raw_budget=10000.0, raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_AW_REACH": 50000.0}},   # low productivity
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 200.0}},     # high productivity
        },
    )
    run_module4(state)
    # Override default floors: force FB to take at least £4,000 even though
    # LI is more productive.  This is what makes the floor *bind*.
    state.min_spend_per_platform = {"fb": 4000.0, "li": 0.0}
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    platform_floors = [bc for bc in base.binding_constraints if bc.kind == "min_platform"]
    assert any(bc.target == "fb" for bc in platform_floors), (
        f"FB floor of £4,000 should bind when LI is more productive, got "
        f"binding={[(bc.name, bc.kind, bc.target) for bc in base.binding_constraints]}"
    )


def test_module5_detects_near_degenerate_groups() -> None:
    """When two platforms have effectively identical productivity for a goal,
    the LP solution is ambiguous; the redistribution logic should fire AND
    surface the ambiguity in near_degenerate_groups."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["aw"], raw_budget=10000.0, raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["fb", "ig"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "ig": {"priority_1": "aw", "priority_2": None},
        },
    )
    # Same productivity per £ on both platforms → ambiguous LP
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 5000.0, "kpis": {"FB_AW_REACH": 500000.0}},
            "ig": {"budget": 5000.0, "kpis": {"IG_AW_REACH": 500000.0}},
        },
    )
    run_module4(state)
    run_module5(state)

    base = state.module5_scenario_bundle.results_by_scenario["base"]
    aw_groups = [g for g in base.near_degenerate_groups if g["goal"] == "aw"]
    assert aw_groups, (
        f"Expected near-degenerate group for AW across FB/IG, got: "
        f"{base.near_degenerate_groups}"
    )
    assert set(aw_groups[0]["platforms"]) == {"fb", "ig"}


def test_module7_policy_thresholds_change_classification() -> None:
    """A custom Module7Policy should produce different classifications/
    confidence scores than the defaults, proving the thresholds are
    actually externalised (not just renamed)."""
    from modules.module7 import run_module7, Module7Policy

    state = _run_pipeline_to_module5()
    from modules.module6 import run_module6
    run_module6(state)
    bundle = state.module5_scenario_bundle
    fc_by_scenario = _get_module6_by_scenario(state)

    default = run_module7(state, bundle, fc_by_scenario)
    # A policy that calls anything above 30% concentration "Corner-dominant"
    # and penalises it heavily should produce different output for the same input.
    strict = Module7Policy(
        corner_concentration=0.30,
        balanced_concentration=0.20,
        confidence_high_concentration=0.30,
        confidence_high_concentration_penalty=40,
    )
    strict_insight = run_module7(state, bundle, fc_by_scenario, policy=strict)

    # At least one scenario must classify or score differently under the
    # tightened policy.
    diffs = 0
    for name in default.scenario_insights:
        d = default.scenario_insights[name]
        s = strict_insight.scenario_insights[name]
        if (d.classification != s.classification
                or d.confidence_score != s.confidence_score):
            diffs += 1
    assert diffs > 0, (
        "Custom Module7Policy did not change any scenario's classification or "
        "confidence — thresholds may not be fully externalised."
    )


def test_module7_default_policy_preserves_existing_behaviour() -> None:
    """Calling run_module7 with no policy must produce byte-identical output
    to passing Module7Policy() — the defaults are the contract."""
    from modules.module7 import run_module7, Module7Policy

    state = _run_pipeline_to_module5()
    from modules.module6 import run_module6
    run_module6(state)
    bundle = state.module5_scenario_bundle
    fc_by_scenario = _get_module6_by_scenario(state)

    implicit = run_module7(state, bundle, fc_by_scenario)
    explicit = run_module7(state, bundle, fc_by_scenario, policy=Module7Policy())

    for name in implicit.scenario_insights:
        a = implicit.scenario_insights[name]
        b = explicit.scenario_insights[name]
        assert a.classification == b.classification
        assert a.confidence_score == b.confidence_score
        assert a.binding_constraints == b.binding_constraints


def test_module6_band_uses_observations_when_present() -> None:
    """With ≥3 historical observations, the band should equal the sample
    coefficient of variation, not the flat default."""
    from modules.module6 import compute_module6_forecast, _coefficient_of_variation
    from modules.module5 import Module5LPResult

    lp = Module5LPResult(
        budget_per_platform_goal={"fb": {"lg": 5000.0}},
        budget_per_platform={"fb": 5000.0},
        total_budget_used=5000.0,
        objective_value=1.0,
        r_pg={"fb": {"lg": 1.0}},
        combined_weight_pg={"fb": {"lg": 1.0}},
        estimated_kpi_per_platform_goal={"fb": {"lg": 100.0}},
    )
    observations = [80.0, 100.0, 120.0, 90.0, 110.0]
    expected_cv = _coefficient_of_variation(observations)
    assert expected_cv is not None and expected_cv > 0

    result = compute_module6_forecast(
        kpi_ratios={"fb": {"lg": {"FB_LG_LEADS": 0.025}}},
        module5_result=lp,
        module3_data={"fb": {"historical_days": 30,
                             "kpi_observations": {"FB_LG_LEADS": observations}}},
    )
    row = next(r for r in result.rows if r.kpi_kind == "count")
    assert row.band_source == "observations"
    assert row.band_pct == pytest.approx(expected_cv)
    # Different from default 30% — proves we didn't fall back
    assert abs(row.band_pct - 0.30) > 0.01


def test_module6_band_window_scaled_when_no_observations() -> None:
    """Without observations but with historical_days, the band should scale
    by sqrt(30 / days): more history → tighter band."""
    from modules.module6 import compute_module6_forecast, DEFAULT_UNCERTAINTY_BAND
    from modules.module5 import Module5LPResult
    import math as _m

    lp = Module5LPResult(
        budget_per_platform_goal={"fb": {"lg": 5000.0}},
        budget_per_platform={"fb": 5000.0},
        total_budget_used=5000.0,
        objective_value=1.0,
        r_pg={"fb": {"lg": 1.0}},
        combined_weight_pg={"fb": {"lg": 1.0}},
        estimated_kpi_per_platform_goal={"fb": {"lg": 100.0}},
    )

    result_90 = compute_module6_forecast(
        kpi_ratios={"fb": {"lg": {"FB_LG_LEADS": 0.025}}},
        module5_result=lp,
        module3_data={"fb": {"historical_days": 90}},
    )
    row_90 = next(r for r in result_90.rows if r.kpi_kind == "count")
    assert row_90.band_source == "window_scaled"
    expected_90 = DEFAULT_UNCERTAINTY_BAND * _m.sqrt(30.0 / 90.0)
    assert row_90.band_pct == pytest.approx(expected_90, rel=1e-6)

    # 7-day window should produce a wider band than 90-day
    result_7 = compute_module6_forecast(
        kpi_ratios={"fb": {"lg": {"FB_LG_LEADS": 0.025}}},
        module5_result=lp,
        module3_data={"fb": {"historical_days": 7}},
    )
    row_7 = next(r for r in result_7.rows if r.kpi_kind == "count")
    assert row_7.band_pct > row_90.band_pct


def test_module6_band_falls_back_to_default_without_module3_data() -> None:
    """Backwards-compatibility: callers that don't pass module3_data must still
    get the flat default band (no breaking change for existing call sites)."""
    from modules.module6 import compute_module6_forecast, DEFAULT_UNCERTAINTY_BAND
    from modules.module5 import Module5LPResult

    lp = Module5LPResult(
        budget_per_platform_goal={"fb": {"lg": 5000.0}},
        budget_per_platform={"fb": 5000.0},
        total_budget_used=5000.0,
        objective_value=1.0,
        r_pg={"fb": {"lg": 1.0}},
        combined_weight_pg={"fb": {"lg": 1.0}},
        estimated_kpi_per_platform_goal={"fb": {"lg": 100.0}},
    )
    result = compute_module6_forecast(
        kpi_ratios={"fb": {"lg": {"FB_LG_LEADS": 0.025}}},
        module5_result=lp,
    )
    row = next(r for r in result.rows if r.kpi_kind == "count")
    assert row.band_source == "default"
    assert row.band_pct == pytest.approx(DEFAULT_UNCERTAINTY_BAND)


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
    historical-vs-future performance, an extension when goal values are
    missing, AND the attribution / incrementality disclosure that warns
    the user the LP is conditional on their attribution model."""
    state = _run_pipeline_to_module5()
    from modules.module6 import run_module6
    from modules.module7 import run_module7

    run_module6(state)
    bundle = state.module5_scenario_bundle
    fc = state.module6_scenario_result.results_by_scenario
    insights = run_module7(state, bundle, fc)

    assert insights.forecast_caveat
    text = insights.forecast_caveat.lower()
    assert "historical" in text
    assert "attribution" in text
    assert "incrementality" in text
    # No goal_value_per_unit set → extended note must appear
    assert "no per-goal economic values" in text


def test_module6_rate_kpi_math_path_still_safe(monkeypatch) -> None:
    """Locks the rate-vs-count branch in compute_module6_forecast.  As
    of the all-counts refactor no KPI in KPI_CONFIG is a rate, but the
    engine's KIND_RATE machinery is retained for future use — this test
    monkeypatches a synthetic rate KPI to confirm the math path doesn't
    silently multiply by budget."""
    from modules import module6 as m6
    from modules.module6 import compute_module6_forecast
    from modules.module5 import Module5LPResult
    from core.kpi_config import KIND_RATE

    # Inject a fake rate KPI into the kind lookup the forecaster reads
    monkeypatch.setitem(m6._KPI_KIND, "SYNTH_EN_RATE", KIND_RATE)

    lp_result = Module5LPResult(
        budget_per_platform_goal={"ig": {"en": 3000.0}},
        budget_per_platform={"ig": 3000.0},
        total_budget_used=3000.0,
        objective_value=1.0,
        r_pg={"ig": {"en": 0.045}},
        combined_weight_pg={"ig": {"en": 1.0}},
        estimated_kpi_per_platform_goal={"ig": {"en": 135.0}},
    )

    kpi_ratios = {"ig": {"en": {"SYNTH_EN_RATE": 0.045}}}
    result = compute_module6_forecast(kpi_ratios, lp_result)

    rate_rows = [r for r in result.rows if r.kpi_kind == KIND_RATE]
    assert len(rate_rows) == 1
    row = rate_rows[0]
    # Predicted value must equal the rate itself, NOT rate × budget
    assert row.predicted_kpi == pytest.approx(0.045), (
        f"Rate KPI predicted value should be 0.045 (the rate), got {row.predicted_kpi}. "
        "Multiplying by budget would give wrong units."
    )
    assert row.predicted_kpi != pytest.approx(0.045 * 3000.0)


# ─────────────────────────────────────────────────────────────────────────────
# build_forecast_df: Expected Revenue / ROAS columns (Item 1 of the audit)
# ─────────────────────────────────────────────────────────────────────────────


def _run_pipeline_with_goal_values(goal_values=None) -> WizardState:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "lg"],
        raw_budget=10000.0,
        raw_duration_days=30,
        raw_goal_values=goal_values,
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {"budget": 4000.0, "kpis": {"FB_AW_REACH": 200000.0}},
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
        },
    )
    run_module4(state, KPI_CONFIG)
    run_module5(state)
    run_module6(state)
    return state


def test_build_forecast_df_omits_revenue_columns_when_no_goal_values() -> None:
    """Without goal_value_per_unit, the forecast df should match its
    pre-feature shape: Platform / Objective / KPI / Allocated Budget /
    Predicted KPI, no revenue or ROAS columns."""
    from app import build_forecast_df

    state = _run_pipeline_with_goal_values(goal_values=None)
    fc = state.module6_scenario_result.results_by_scenario["base"]
    df = build_forecast_df(fc)

    assert "Expected Revenue" not in df.columns
    assert "ROAS" not in df.columns
    assert set(df.columns) >= {"Platform", "Objective", "KPI", "Allocated Budget", "Predicted KPI"}


def test_build_forecast_df_adds_revenue_columns_when_goal_values_provided() -> None:
    """When goal_value_per_unit has positive values, count KPI rows should
    get Expected Revenue = predicted × goal_value and ROAS = revenue / budget."""
    from app import build_forecast_df

    state = _run_pipeline_with_goal_values(goal_values={"lg": 200.0, "aw": 0.001})
    fc = state.module6_scenario_result.results_by_scenario["base"]
    df = build_forecast_df(fc, goal_values=state.goal_value_per_unit)

    assert "Expected Revenue" in df.columns
    assert "ROAS" in df.columns
    assert not df.empty

    for _, row in df.iterrows():
        if row["KPI"] == "Leads" and row["Predicted KPI"] > 0:
            expected_rev = row["Predicted KPI"] * 200.0
            expected_roas = expected_rev / row["Allocated Budget"]
            assert row["Expected Revenue"] == pytest.approx(expected_rev, rel=1e-6)
            assert row["ROAS"] == pytest.approx(expected_roas, rel=1e-6)
            break
    else:
        raise AssertionError("Expected at least one Leads row with positive predicted volume.")


def test_build_forecast_df_engagement_count_gets_normal_revenue() -> None:
    """Engagement is now a count (all-counts refactor: same unit as the
    other KPIs on each social platform).  Counts × £/unit = revenue
    works normally — no special-casing needed.  Locks the post-refactor
    behaviour so revenue is computed for engagement, not zeroed."""
    from app import build_forecast_df

    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["en", "lg"],
        raw_budget=8000.0,
        raw_duration_days=30,
        raw_goal_values={"en": 0.20, "lg": 100.0},
    )
    run_module2(
        state,
        selected_platforms=["ig", "li"],
        priorities_input={
            "ig": {"priority_1": "en", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            # Engagement as a COUNT (summed Likes+Comments+Shares+Saves+Follows etc.)
            "ig": {"budget": 3000.0, "kpis": {"IG_EN_ENGAGEMENT": 9000.0}},
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
        },
    )
    run_module4(state, KPI_CONFIG)
    run_module5(state)
    run_module6(state)

    fc = state.module6_scenario_result.results_by_scenario["base"]
    df = build_forecast_df(fc, goal_values=state.goal_value_per_unit)

    # Engagement KPI label is now "Engagement" (not "Engagement Rate"),
    # and revenue should compute normally as count × £/unit.
    en_rows = df[df["KPI"] == "Engagement"]
    assert not en_rows.empty, "Expected at least one Engagement row."
    for _, row in en_rows.iterrows():
        if row["Predicted KPI"] > 0:
            expected_rev = row["Predicted KPI"] * 0.20
            assert row["Expected Revenue"] == pytest.approx(expected_rev, rel=1e-6), (
                f"Engagement count revenue should be predicted × £0.20; "
                f"got {row['Expected Revenue']} vs expected {expected_rev}"
            )
            break
    else:
        raise AssertionError("Expected at least one Engagement row with positive predicted volume.")


def test_build_forecast_df_zero_goal_value_treated_as_unset() -> None:
    """A goal value of 0 (the user 'skipped' that goal) should not trigger
    the revenue columns — equivalent to no goal values at all for that
    objective."""
    from app import build_forecast_df

    state = _run_pipeline_with_goal_values(goal_values={"lg": 200.0})  # aw skipped (0)
    fc = state.module6_scenario_result.results_by_scenario["base"]
    df = build_forecast_df(fc, goal_values=state.goal_value_per_unit)

    # Columns exist because lg has a value
    assert "Expected Revenue" in df.columns

    # AW rows (Reach, Impression) get goal_value=0 → revenue=0
    aw_rows = df[df["Objective"] == "Awareness"]
    if not aw_rows.empty:
        for _, row in aw_rows.iterrows():
            assert row["Expected Revenue"] == 0.0


def test_build_forecast_df_roas_uses_total_cell_budget() -> None:
    """For cells with multiple count KPIs (e.g. FB AW: Reach + Impression),
    each row's ROAS divides by the cell's allocated budget — both rows share
    the same budget so their ROAS values stack correctly."""
    from app import build_forecast_df

    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "lg"],
        raw_budget=10000.0,
        raw_duration_days=30,
        raw_goal_values={"aw": 0.001, "lg": 100.0},
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "li": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        state,
        platform_inputs={
            "fb": {
                "budget": 4000.0,
                "kpis": {"FB_AW_REACH": 200000.0, "FB_AW_IMPRESSION": 500000.0},
            },
            "li": {"budget": 3000.0, "kpis": {"LI_LG_LEADS": 80.0}},
        },
    )
    run_module4(state, KPI_CONFIG)
    run_module5(state)
    run_module6(state)

    fc = state.module6_scenario_result.results_by_scenario["base"]
    df = build_forecast_df(fc, goal_values=state.goal_value_per_unit)

    fb_aw_rows = df[(df["Platform"] == "Facebook") & (df["Objective"] == "Awareness")]
    assert len(fb_aw_rows) == 2, "Expected Reach AND Impression rows for FB Awareness."

    budgets = set(fb_aw_rows["Allocated Budget"].tolist())
    assert len(budgets) == 1, (
        "Both KPI rows for the same (platform, objective) cell should share the "
        f"same allocated budget; got {budgets}."
    )

    for _, row in fb_aw_rows.iterrows():
        expected_roas = (row["Predicted KPI"] * 0.001) / row["Allocated Budget"]
        assert row["ROAS"] == pytest.approx(expected_roas, rel=1e-6)


def test_build_forecast_df_invalid_goal_values_ignored() -> None:
    """Non-numeric, negative, or NaN goal values should be silently dropped
    by build_forecast_df rather than raise.  Verified concretely by
    asserting the corresponding objective's rows get zero revenue while
    the valid lg=200.0 entry still drives positive revenue."""
    from app import build_forecast_df

    state = _run_pipeline_with_goal_values(goal_values={"lg": 200.0})
    fc = state.module6_scenario_result.results_by_scenario["base"]

    # Mix of bad and good values passed directly (state.goal_value_per_unit
    # itself is validated at finalise_module1; this guards the build_forecast_df
    # entry point against future callers that pass raw dicts).
    df = build_forecast_df(
        fc,
        goal_values={"lg": 200.0, "aw": -5.0, "en": "not a number", "wt": float("nan")},  # type: ignore[dict-item]
    )

    assert "Expected Revenue" in df.columns  # lg=200 enabled it

    # The valid entry still drives positive revenue
    lg_rows = df[df["Objective"] == "Lead Generation"]
    assert (lg_rows["Expected Revenue"] > 0).any()

    # The negative aw value must have been silently filtered — every AW row's
    # revenue stays at 0.  A future regression that allowed -5.0 through would
    # produce *negative* expected revenue (predicted_kpi × -5.0) and fail here.
    aw_rows = df[df["Objective"] == "Awareness"]
    if not aw_rows.empty:
        assert (aw_rows["Expected Revenue"] == 0.0).all(), (
            "Negative goal value (-5.0) leaked through and produced non-zero "
            f"revenue on Awareness rows: {aw_rows['Expected Revenue'].tolist()}"
        )


def test_build_forecast_df_all_zero_goal_values_omits_columns() -> None:
    """When every goal value in the dict is 0 (or any falsy non-positive
    sentinel), build_forecast_df should behave as if no goal values were
    provided at all — no Expected Revenue / ROAS columns.  Separately
    covers the 'dict provided but every entry zero' branch that
    test_build_forecast_df_omits_revenue_columns_when_no_goal_values
    (which passes None) doesn't exercise."""
    from app import build_forecast_df

    state = _run_pipeline_with_goal_values(goal_values=None)
    fc = state.module6_scenario_result.results_by_scenario["base"]

    df = build_forecast_df(fc, goal_values={"lg": 0.0, "aw": 0.0, "wt": 0.0, "en": 0.0})

    assert "Expected Revenue" not in df.columns, (
        "All-zero goal_values dict should omit the revenue column, same as "
        "passing goal_values=None."
    )
    assert "ROAS" not in df.columns


def test_kpi_meta_includes_kind() -> None:
    """build_kpi_meta must expose 'kind' so callers can tell count from rate
    KPIs without re-importing KPI_CONFIG."""
    from app import build_kpi_meta

    meta = build_kpi_meta()
    assert "FB_AW_REACH" in meta
    assert meta["FB_AW_REACH"]["kind"] == "count"
    # IG engagement is now a count (sum of Likes+Comments+Shares+Saves+Follows),
    # not a rate — same unit as the other KPIs on Instagram.
    assert "IG_EN_ENGAGEMENT" in meta
    assert meta["IG_EN_ENGAGEMENT"]["kind"] == "count"


# ─────────────────────────────────────────────────────────────────────────────
# Google split: Search / Display / PMax (Item 4 of the audit)
# ─────────────────────────────────────────────────────────────────────────────


def test_google_search_and_display_are_separate_platforms_in_catalogue() -> None:
    """The aggregate 'go' code no longer exists — three distinct surfaces
    (go_search / go_display / go_pmax) replace it.  Each has its own KPI
    catalogue rows and its own monthly effective minimum, since their
    auctions and learning phases behave very differently."""
    from core.kpi_config import KPI_CONFIG
    from modules.module5 import PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH
    from core.wizard_state import ALLOWED_PLATFORMS

    # No aggregate 'go' should leak through
    assert "go" not in ALLOWED_PLATFORMS
    assert "go" not in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH

    # Three distinct codes exist
    for code in ("go_search", "go_display", "go_pmax"):
        assert code in ALLOWED_PLATFORMS, f"{code} missing from ALLOWED_PLATFORMS"
        assert code in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH

    # Each surface has its own 4-KPI row block in the catalogue
    for code in ("go_search", "go_display", "go_pmax"):
        rows = [r for r in KPI_CONFIG if r["platform"] == code]
        assert len(rows) == 4, f"{code} should have 4 KPI rows (AW/EN/WT/LG), got {len(rows)}"

    # Effective minimums differ across the three — they're calibrated separately
    mins = {
        c: PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH[c]
        for c in ("go_search", "go_display", "go_pmax")
    }
    assert len(set(mins.values())) == 3, (
        f"Search / Display / PMax should have three distinct minimums, "
        f"got {mins}.  Distinct values are the calibration story for splitting them."
    )
    # PMax > Search > Display ordering reflects published Google guidance:
    # PMax needs ~50 conversions for Smart Bidding; Display learns on less.
    assert mins["go_pmax"] > mins["go_search"] > mins["go_display"]


def test_google_search_outranks_google_display_on_lead_gen() -> None:
    """When Search reports 10× higher lead-gen productivity than Display
    on the same budget, the LP should reward Search with substantially
    more allocation.  This is the audit's headline justification for
    splitting them — lumped into one cell, the optimiser couldn't make
    this distinction."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5

    s = WizardState()
    complete_module1_and_advance(
        s,
        raw_objectives=["lg"],
        raw_budget=10000.0,
        raw_duration_days=30,
        raw_goal_values={"lg": 100.0},
    )
    run_module2(
        s,
        selected_platforms=["go_search", "go_display"],
        priorities_input={
            "go_search":  {"priority_1": "lg", "priority_2": None},
            "go_display": {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        s,
        platform_inputs={
            # Same £3k spent — Search drove 300 conversions, Display drove 30.
            # 10× productivity gap is realistic for B2B lead-gen.
            "go_search":  {"budget": 3000.0, "historical_days": 60,
                           "kpis": {"GO_SEARCH_LG_CONVERSIONS": 300.0}},
            "go_display": {"budget": 3000.0, "historical_days": 60,
                           "kpis": {"GO_DISPLAY_LG_CONVERSIONS": 30.0}},
        },
    )
    run_module4(s)
    run_module5(s)

    base = s.module5_scenario_bundle.results_by_scenario["base"]
    search_alloc  = sum(base.budget_per_platform_goal.get("go_search",  {}).values())
    display_alloc = sum(base.budget_per_platform_goal.get("go_display", {}).values())

    assert search_alloc > display_alloc, (
        f"With Search producing 10× more conversions/£, the LP should allocate "
        f"more to Search than Display, got Search={search_alloc:.0f}, "
        f"Display={display_alloc:.0f}."
    )


def test_google_pmax_independently_allocatable_alongside_search() -> None:
    """A marketer running both a Search campaign and a Performance Max
    campaign should be able to enter both into the optimiser and have
    each receive a separate allocation reflecting its own productivity.
    Lumping them into one 'go' cell would force the user to pre-decide
    the split themselves before the LP saw the numbers."""
    from modules.module2 import run_module2
    from modules.module3 import finalise_module3_from_inputs
    from modules.module4 import run_module4
    from modules.module5 import run_module5
    from modules.module6 import run_module6

    s = WizardState()
    complete_module1_and_advance(
        s,
        raw_objectives=["lg"],
        raw_budget=15000.0,
        raw_duration_days=30,
        raw_goal_values={"lg": 100.0},
    )
    run_module2(
        s,
        selected_platforms=["go_search", "go_pmax"],
        priorities_input={
            "go_search": {"priority_1": "lg", "priority_2": None},
            "go_pmax":   {"priority_1": "lg", "priority_2": None},
        },
    )
    finalise_module3_from_inputs(
        s,
        platform_inputs={
            "go_search": {"budget": 5000.0, "historical_days": 60,
                          "kpis": {"GO_SEARCH_LG_CONVERSIONS": 150.0}},
            "go_pmax":   {"budget": 6000.0, "historical_days": 60,
                          "kpis": {"GO_PMAX_LG_CONVERSIONS": 220.0}},
        },
    )
    run_module4(s)
    run_module5(s)
    run_module6(s)

    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert "go_search" in base.budget_per_platform_goal
    assert "go_pmax"   in base.budget_per_platform_goal
    # Both receive non-zero allocation
    assert sum(base.budget_per_platform_goal["go_search"].values()) > 0
    assert sum(base.budget_per_platform_goal["go_pmax"].values()) > 0


def test_csv_export_works_for_each_google_surface() -> None:
    """Each Google surface needs its own CSV-template download so a user
    can populate Search numbers separately from Display from PMax,
    regardless of which surface their export was filtered to."""
    from core.csv_import import generate_csv_template, SUPPORTED_PLATFORMS

    for code in ("go_search", "go_display", "go_pmax"):
        assert code in SUPPORTED_PLATFORMS, f"CSV not supported for {code}"
        template_bytes = generate_csv_template(code)
        assert template_bytes, f"Empty template for {code}"
        header = template_bytes.decode("utf-8").split("\n", 1)[0].lower()
        # All three Google surfaces share the same column shape — that's by
        # design (Google Ads exports look identical regardless of campaign
        # type; the user filters server-side before exporting).  The
        # 'impressions' column appears as 'impr.' in Google's export, so
        # accept either form.
        assert "impr" in header, (
            f"{code} template missing impressions column. Header: {header}"
        )
        # CTR column dropped from Google templates (no engagement KPI on
        # Google any more — see KPI_CONFIG comment).  Click / Conversion /
        # Cost remain.
        for needle in ("click", "conversion", "cost"):
            assert needle in header, (
                f"{code} template missing {needle!r} column. Header: {header}"
            )
