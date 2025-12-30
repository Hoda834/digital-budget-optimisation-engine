from __future__ import annotations

from core.wizard_state import WizardState
from core.kpi_config import KPI_CONFIG
from modules.module2 import run_module2
from modules.module4 import run_module4
from modules.module5 import run_module5, Module5ScenarioBundle
from modules.module6 import run_module6, Module6ScenarioResult
from modules.module7 import run_module7


def _get_module5_bundle(state: WizardState) -> Module5ScenarioBundle:
    bundle = getattr(state, "module5_scenario_bundle", None)
    if bundle is None:
        raise AssertionError("Module 5 did not produce a scenario bundle.")
    if not isinstance(bundle, Module5ScenarioBundle):
        raise AssertionError("module5_scenario_bundle is not a Module5ScenarioBundle.")
    if not getattr(bundle, "results_by_scenario", None):
        raise AssertionError("Module 5 scenario bundle is empty.")
    return bundle


def _get_module6_by_scenario(state: WizardState) -> dict:
    sres = getattr(state, "module6_scenario_result", None)
    if isinstance(sres, Module6ScenarioResult):
        return dict(sres.results_by_scenario)
    m6 = getattr(state, "module6_result", None)
    if m6 is not None:
        return {"base": m6}
    return {}


def test_full_pipeline_smoke() -> None:
    state = WizardState()

    state.complete_module1_and_advance(
        valid_goals=["aw", "en"],
        total_budget=1000.0,
    )

    run_module2(
        state,
        selected_platforms=["fb", "ig"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": None},
            "ig": {"priority_1": "en", "priority_2": None},
        },
    )

    state.complete_module3_and_advance(
        module3_data={
            "fb": {"time_window": "30 days", "budget": 500.0, "kpis": {"fb_aw_impressions": 1000.0}},
            "ig": {"time_window": "30 days", "budget": 500.0, "kpis": {"ig_en_engagements": 200.0}},
        },
        platform_budgets={"fb": 500.0, "ig": 500.0},
        platform_kpis={
            "fb": {"fb_aw_impressions": 1000.0},
            "ig": {"ig_en_engagements": 200.0},
        },
        kpi_ratios={
            "fb": {"aw": {"fb_aw_impressions": 2.0}},
            "ig": {"en": {"ig_en_engagements": 0.4}},
        },
    )

    run_module4(state, KPI_CONFIG)
    assert getattr(state, "module4_finalised", False) is True

    run_module5(state)
    assert getattr(state, "module5_finalised", False) is True

    run_module6(state)
    assert getattr(state, "module6_finalised", False) is True

    bundle = _get_module5_bundle(state)
    fc_by_scenario = _get_module6_by_scenario(state)

    m7 = run_module7(state, bundle, fc_by_scenario)
    assert m7 is not None

    scenario_insights = getattr(m7, "scenario_insights", None)
    assert isinstance(scenario_insights, dict)
    assert len(scenario_insights) > 0

    total_budget = float(getattr(state, "total_budget", 0.0) or 0.0)
    assert total_budget > 0.0

    for _, lp_res in bundle.results_by_scenario.items():
        used = float(getattr(lp_res, "total_budget_used", 0.0) or 0.0)
        assert used <= total_budget + 1e-6
