from dataclasses import dataclass
from typing import Any, Dict, List, Set

from core.wizard_state import WizardState, FlowStateError


class Module4ValidationError(Exception):
    pass


@dataclass
class Module4Result:
    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]]
    valid_platforms: Set[str]


def _assert_module4_flow_allowed(state: WizardState) -> None:
    if state.current_step != 4:
        raise FlowStateError(
            f"Module 4 can only run when current_step == 4. Current value is {state.current_step!r}."
        )
    if not state.module3_finalised:
        raise FlowStateError("Module 4 requires Module 3 to be finalised.")
    if not state.valid_goals:
        raise Module4ValidationError("No valid goals available in wizard state.")
    if not state.active_platforms:
        raise Module4ValidationError("No active platforms found for Module 4.")
    if state.module4_finalised:
        raise FlowStateError("Module 4 has already been finalised. Reset to run again.")


def run_module4(
    state: WizardState,
    kpi_config: List[Dict[str, Any]],
) -> Module4Result:
    _assert_module4_flow_allowed(state)

    active_platforms: List[str] = state.active_platforms
    goals_by_platform: Dict[str, List[str]] = state.goals_by_platform
    platform_budgets: Dict[str, float] = state.platform_budgets
    platform_kpis: Dict[str, Dict[str, float]] = state.platform_kpis
    module3_data: Dict[str, Dict[str, Any]] = state.module3_data

    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]] = {}

    for platform in active_platforms:
        if platform not in platform_budgets:
            raise Module4ValidationError(f"Missing budget for platform {platform!r}.")

        try:
            budget = float(platform_budgets[platform])
        except Exception:
            raise Module4ValidationError(f"Budget for platform {platform!r} must be numeric.")

        if budget <= 1:
            raise Module4ValidationError(
                f"Budget for platform {platform!r} must be greater than 1. Got {budget!r}."
            )

        kpis_for_p = platform_kpis.get(platform)
        if not kpis_for_p:
            kpis_for_p = module3_data.get(platform, {}).get("kpis", {})

        if not kpis_for_p:
            continue

        active_goals_for_p = goals_by_platform.get(platform, [])
        if not active_goals_for_p:
            continue

        for goal in active_goals_for_p:
            for kpi_name, raw_value in kpis_for_p.items():
                try:
                    kpi_val = float(raw_value)
                except Exception:
                    continue
                if kpi_val <= 0:
                    continue

                cpu = budget / kpi_val
                if cpu <= 0:
                    continue

                platform_bucket = cpu_per_goal.setdefault(platform, {})
                goal_bucket = platform_bucket.setdefault(goal, {})
                goal_bucket[kpi_name] = cpu

    valid_platforms: Set[str] = {p for p, gdict in cpu_per_goal.items() if gdict}

    if not cpu_per_goal:
        raise Module4ValidationError(
            "Module 4 computed an empty cpu_per_goal table. Check Module 3 data."
        )

    result = Module4Result(cpu_per_goal=cpu_per_goal, valid_platforms=valid_platforms)

    state.complete_module4_and_advance(module4_result=result)

    return result
