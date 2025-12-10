from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from wizard_state import WizardState
from module5 import Module5LPResult


# =========================
# 1. Data structures for Module 6
# =========================

@dataclass
class Module6ForecastRow:
    """
    Single row of the KPI forecast table for a given platform and KPI.

    Attributes
    ----------
    platform : str
        Platform code, for example "fb", "ig", "li", "yt".
    kpi_name : str
        Internal KPI identifier, for example "IG_AW_REACH".
    ratio_kpi_per_budget : float
        Historical KPI units per 1 unit of budget (from Module 3).
    allocated_budget : float
        New allocated budget for this platform (from Module 5).
    predicted_kpi : float
        Forecasted KPI value for this platform and KPI.
    """
    platform: str
    kpi_name: str
    ratio_kpi_per_budget: float
    allocated_budget: float
    predicted_kpi: float


@dataclass
class Module6Result:
    """
    Full KPI forecast result of Module 6.
    """
    rows: List[Module6ForecastRow] = field(default_factory=list)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """
        Convert rows to a list of dictionaries for easy serialisation
        or export (for example to JSON, CSV, or a DataFrame).
        """
        result: List[Dict[str, Any]] = []
        for row in self.rows:
            result.append(
                {
                    "platform": row.platform,
                    "kpi_name": row.kpi_name,
                    "ratio_kpi_per_budget": row.ratio_kpi_per_budget,
                    "allocated_budget": row.allocated_budget,
                    "predicted_kpi": row.predicted_kpi,
                }
            )
        return result

    def to_pandas(self):
        """
        Optional helper: convert forecast rows to a pandas DataFrame.
        This requires pandas to be installed. If pandas is not available,
        an ImportError will be raised.
        """
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pandas is required to use Module6Result.to_pandas()."
            ) from exc

        data = self.to_dict_list()
        return pd.DataFrame(data)


# =========================
# 2. Core logic of Module 6
# =========================

def compute_module6_forecast(
    kpi_ratios: Dict[str, Dict[str, float]],
    module5_result: Module5LPResult,
    min_budget_threshold: float = 1.0,
) -> Module6Result:
    """
    Compute KPI forecasts for each platform and KPI based on:
    - Historical KPI to budget ratios from Module 3 (kpi_ratios).
    - New budget allocations from Module 5 (budget_per_platform).

    For each platform p and KPI k:

        ratio_{p,k}  = historical KPI per 1 unit of budget
        budget_new_p = allocated budget from Module 5

        predicted_kpi_{p,k} = ratio_{p,k} * budget_new_p

    Parameters
    ----------
    kpi_ratios : Dict[str, Dict[str, float]]
        Historical KPI ratios per platform:
            kpi_ratios[platform][kpi_name] = KPI units per 1 unit budget.
        This is populated in Module 3.
    module5_result : Module5LPResult
        New budget allocations per platform from Module 5.
        Uses module5_result.budget_per_platform.
    min_budget_threshold : float, optional
        Minimum budget to consider a platform active. Platforms
        with allocated_budget < threshold will be skipped.

    Returns
    -------
    Module6Result
        Forecast table as a list of Module6ForecastRow.
    """
    if min_budget_threshold <= 0:
        raise ValueError("min_budget_threshold must be greater than 0.")

    rows: List[Module6ForecastRow] = []

    for platform, allocated_budget in module5_result.budget_per_platform.items():
        # Skip platforms with None, zero, or very small budget
        if allocated_budget is None or allocated_budget < min_budget_threshold:
            continue

        # Retrieve KPI ratios for this platform
        kpi_ratios_for_platform = kpi_ratios.get(platform, {})

        # If there are no ratios for this platform, skip it
        if not kpi_ratios_for_platform:
            continue

        for kpi_name, ratio in kpi_ratios_for_platform.items():
            # Defensive checks against invalid ratios
            if ratio is None or ratio <= 0:
                continue

            predicted_kpi = ratio * allocated_budget

            row = Module6ForecastRow(
                platform=platform,
                kpi_name=kpi_name,
                ratio_kpi_per_budget=ratio,
                allocated_budget=allocated_budget,
                predicted_kpi=predicted_kpi,
            )
            rows.append(row)

    return Module6Result(rows=rows)


# =========================
# 3. Wizard level orchestrator
# =========================

def run_module6(
    state: WizardState,
    min_budget_threshold: float = 1.0,
    next_step: Optional[int] = None,
) -> WizardState:
    """
    Run Module 6 as an internal, non interactive step of the wizard.

    Uses:
    - state.kpi_ratios from Module 3.
    - state.module5_result from Module 5.

    Behaviour:
    1) Validates that Modules 3 and 5 are finalised and inputs are present.
    2) Computes KPI forecast table.
    3) Saves the result into state.module6_result.
    4) Sets module6_finalised = True.
    5) Optionally advances current_step to `next_step`.

    Parameters
    ----------
    state : WizardState
        Global wizard state containing inputs from previous modules.
    min_budget_threshold : float, optional
        Minimum budget for a platform to be included in the forecast.
    next_step : int, optional
        If provided, state.current_step will be set to this value
        after Module 6 is successfully completed.

    Returns
    -------
    WizardState
        Updated wizard state with Module 6 results.
    """
    if not state.module3_finalised:
        raise ValueError("Module 6 requires Module 3 to be finalised.")
    if not state.module5_finalised:
        raise ValueError("Module 6 requires Module 5 to be finalised.")
    if state.module5_result is None:
        raise ValueError("Module 6 requires state.module5_result to be set.")
    if not state.kpi_ratios:
        raise ValueError("Module 6 requires state.kpi_ratios to be populated from Module 3.")

    # Compute forecast using the core logic
    forecast = compute_module6_forecast(
        kpi_ratios=state.kpi_ratios,
        module5_result=state.module5_result,
        min_budget_threshold=min_budget_threshold,
    )

    # Save result into state
    state.module6_result = forecast
    state.module6_finalised = True

    # Optionally move the wizard to the next step
    if next_step is not None:
        state.current_step = next_step
    else:
        # Ensure progression if next_step not given
        # Adjust this default if your wizard step numbering changes
        state.current_step = max(state.current_step, 7)

    return state


# =========================
# 4. Optional: simple demo
# =========================

if __name__ == "__main__":
    # Minimal example state as if Modules 3 and 5 are completed
    from module5 import Module5LPResult  # only for the local demo

    demo_state = WizardState(
        current_step=6,
        module1_finalised=True,
        module2_finalised=True,
        module3_finalised=True,
        module4_finalised=True,
        module5_finalised=True,
        valid_goals=["aw", "en"],
        total_budget=2000.0,
    )

    # Example kpi_ratios filled by Module 3
    demo_state.kpi_ratios = {
        "ig": {
            "IG_AW_REACH": 120.0,
            "IG_EN_ENGRATERATE": 3.5,
        },
        "fb": {
            "FB_AW_REACH": 80.0,
        },
    }

    # Example Module 5 result
    demo_state.module5_result = Module5LPResult(
        budget_per_platform_goal={
            "ig": {"aw": 1500.0, "en": 500.0},
            "fb": {"aw": 0.0, "en": 0.0},
        },
        budget_per_platform={
            "ig": 2000.0,
            "fb": 0.0,
        },
        total_budget_used=2000.0,
        objective_value=123.45,
        r_pg={"ig": {"aw": 0.1, "en": 0.05}, "fb": {"aw": 0.08, "en": 0.02}},
        combined_weight_pg={
            "ig": {"aw": 0.4, "en": 0.6},
            "fb": {"aw": 0.7, "en": 0.3},
        },
        estimated_kpi_per_platform_goal={
            "ig": {"aw": 200.0, "en": 100.0},
            "fb": {"aw": 0.0, "en": 0.0},
        },
    )

    demo_state = run_module6(demo_state, next_step=8)

    if demo_state.module6_result is not None:
        for row in demo_state.module6_result.rows:
            print(
                row.platform,
                row.kpi_name,
                "budget:", row.allocated_budget,
                "ratio:", row.ratio_kpi_per_budget,
                "predicted:", row.predicted_kpi,
            )
