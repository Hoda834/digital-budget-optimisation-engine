from core.wizard_state import WizardState
from modules.module2 import run_module2
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module6 import run_module6
from modules.module7 import run_module7
from modules.module5 import Module5ScenarioBundle

from core.kpi_config import KPI_CONFIG


def test_full_pipeline_smoke():
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
            "fb": {
                "time_window": "30 days",
                "budget": 500,
                "kpis": {"fb_aw_impressions": 1000},
            },
            "ig": {
                "time_window": "30 days",
                "budget": 500,
                "kpis": {"ig_en_engagements": 200},
            },
        },
        platform_budgets={"fb": 500, "ig": 500},
        platform_kpis={
            "fb": {"fb_aw_impressions": 1000},
            "ig": {"ig_en_engagements": 200},
        },
        kpi_ratios={
            "fb": {"aw": {"fb_aw_impressions": 2}},
            "ig": {"en": {"ig_en_engagements": 0.4}},
        },
    )

    run_module4(state, KPI_CONFIG)
    run_module5(state)
    run_module6(state)

    bundle = state.module5_scenario_bundle
    assert bundle is not None

    insights = run_module7(state, bundle, {})
    assert insights is not None
