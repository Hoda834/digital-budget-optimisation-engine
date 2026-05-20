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
    currency="GBP",
    campaign_duration_days=30,
) -> WizardState:
    state = WizardState()

    complete_module1_and_advance(
        state,
        raw_objectives=list(valid_goals),
        raw_budget=total_budget,
        raw_currency=currency,
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


def test_currency_and_duration_persisted() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "lg"],
        raw_budget="£1,200.50",
        raw_currency=None,  # should auto-detect GBP from symbol
        raw_duration_days="45",
    )
    assert state.currency == "GBP"
    assert state.campaign_duration_days == 45
    assert state.total_budget == pytest.approx(1200.50)


def test_module2_excludes_non_priority_goals() -> None:
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "en", "wt", "lg"],
        raw_budget=10000.0,
        raw_currency="GBP",
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
