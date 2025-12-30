from core.wizard_state import WizardState
from modules.module5 import run_module5


def test_optimisation_respects_budget():
    state = WizardState()
    state.total_budget = 1000
    state.valid_goals = ["aw"]
    state.active_platforms = ["fb"]

    state.kpi_ratios = {
        "fb": {"aw": {"fb_aw_impressions": 2}}
    }

    run_module5(state)

    res = state.module5_result
    assert res is not None
    assert res.total_budget_used <= state.total_budget
