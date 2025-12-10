from dataclasses import dataclass
from typing import Any, Dict, List, Set

from wizard_state import WizardState, FlowStateError


# ============================================
# Errors
# ============================================

class Module4ValidationError(Exception):
    """Raised when Module 4 cannot build a valid cpu_per_goal table."""
    pass


# ============================================
# Data structures expected by Module 5
# ============================================

@dataclass
class Module4Result:
    """
    Result of Module 4, used as bridge into Module 5.

    Attributes
    ----------
    cpu_per_goal : dict
        cpu_per_goal[p][g][kpi_name] = cost per 1 unit of KPI
        derived from Module 3 historical data.

    valid_platforms : set
        Platforms that had at least one valid KPI entry.
    """
    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]]
    valid_platforms: Set[str]


# ============================================
# Internal flow guard
# ============================================

def _assert_module4_flow_allowed(state: WizardState) -> None:
    """
    Ensure that Module 4 is called in a valid flow position.
    """
    if state.current_step != 4:
        raise FlowStateError(
            f"Module 4 can only run when current_step == 4. "
            f"Current value is {state.current_step!r}."
        )
    if not state.module3_finalised:
        raise FlowStateError("Module 4 requires Module 3 to be finalised.")
    if not state.valid_goals:
        raise Module4ValidationError("No valid goals available in wizard state.")
    if not state.active_platforms:
        raise Module4ValidationError(
            "No active platforms found when entering Module 4. "
            "Check Module 2 and 3 outputs."
        )
    if state.module4_finalised:
        raise FlowStateError(
            "Module 4 has already been finalised. "
            "Reset the wizard to run it again."
        )


# ============================================
# Core function
# ============================================

def run_module4(
    state: WizardState,
    kpi_config: List[Dict[str, Any]],  # kept for signature, not used internally
) -> Module4Result:
    """
    Build cpu_per_goal from Module 3 data to feed Module 5.

    این نسخه دیگر به KPI_CONFIG تکیه نمی‌کند.
    فقط از آنچه در WizardState هست استفاده می‌کند:

      - active_platforms
      - goals_by_platform
      - platform_budgets
      - platform_kpis (یا module3_data['kpis'])

    برای هر پلتفرم p و هر هدف g فعال در آن پلتفرم و هر KPI موجود:

        cpu_per_goal[p][g][kpi_name] = budget_p / kpi_value_{p,k}

    هدف فقط ساختن ساختار cost per unit برای ماژول ۵ است،
    نه نگه داشتن نگاشت دقیق KPI به goal.
    """
    _assert_module4_flow_allowed(state)

    active_platforms: List[str] = list(state.active_platforms)
    goals_by_platform: Dict[str, List[str]] = state.goals_by_platform or {}
    platform_budgets: Dict[str, float] = state.platform_budgets or {}
    platform_kpis: Dict[str, Dict[str, float]] = state.platform_kpis or {}
    module3_data: Dict[str, Dict[str, Any]] = state.module3_data or {}

    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]] = {}

    for platform in active_platforms:
        # Budget
        if platform not in platform_budgets:
            raise Module4ValidationError(
                f"Missing budget for platform {platform!r} in platform_budgets."
            )
        try:
            budget = float(platform_budgets[platform])
        except (TypeError, ValueError):
            raise Module4ValidationError(
                f"Budget for platform {platform!r} must be numeric."
            )
        if budget <= 1:
            raise Module4ValidationError(
                f"Budget for platform {platform!r} must be greater than 1. "
                f"Got {budget!r}."
            )

        # KPI values; prefer platform_kpis, fall back to module3_data['kpis']
        kpis_for_p = platform_kpis.get(platform)
        if not kpis_for_p:
            kpis_for_p = module3_data.get(platform, {}).get("kpis", {})

        if not kpis_for_p:
            # No KPI data for this platform
            continue

        # Active goals for platform
        active_goals_for_p = goals_by_platform.get(platform, [])
        if not active_goals_for_p:
            continue

        for g in active_goals_for_p:
            for kpi_name, raw_value in kpis_for_p.items():
                try:
                    kpi_value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if kpi_value <= 0:
                    continue

                cpu_value = budget / kpi_value
                if cpu_value <= 0:
                    continue

                platform_bucket = cpu_per_goal.setdefault(platform, {})
                goal_bucket = platform_bucket.setdefault(g, {})
                goal_bucket[kpi_name] = cpu_value

    valid_platforms: Set[str] = {
        p for p, goals_dict in cpu_per_goal.items() if goals_dict
    }

    if not cpu_per_goal:
        raise Module4ValidationError(
            "Module 4 computed an empty cpu_per_goal table. "
            "Check Module 3 platform_budgets/platform_kpis alignment."
        )

    result = Module4Result(
        cpu_per_goal=cpu_per_goal,
        valid_platforms=valid_platforms,
    )

    # ذخیره در WizardState و جلو بردن فلو
    state.complete_module4_and_advance(module4_result=result)

    return result
