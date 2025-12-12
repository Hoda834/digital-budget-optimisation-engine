from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.wizard_state import WizardState
from modules.module5 import Module5LPResult


@dataclass
class Module6ForecastRow:
    platform: str
    kpi_name: str
    ratio_kpi_per_budget: float
    allocated_budget: float
    predicted_kpi: float


@dataclass
class Module6Result:
    rows: List[Module6ForecastRow] = field(default_factory=list)

    def to_dict_list(self) -> List[Dict[str, Any]]:
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
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pandas is required to use Module6Result.to_pandas()."
            ) from exc

        data = self.to_dict_list()
        return pd.DataFrame(data)


def compute_module6_forecast(
    kpi_ratios: Dict[str, Dict[str, float]],
    module5_result: Module5LPResult,
    min_budget_threshold: float = 1.0,
) -> Module6Result:
    if min_budget_threshold <= 0:
        raise ValueError("min_budget_threshold must be greater than 0.")

    rows: List[Module6ForecastRow] = []

    for platform, allocated_budget in module5_result.budget_per_platform.items():
        if allocated_budget is None or allocated_budget < min_budget_threshold:
            continue

        kpi_ratios_for_platform = kpi_ratios.get(platform, {})
        if not kpi_ratios_for_platform:
            continue

        for kpi_name, ratio in kpi_ratios_for_platform.items():
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


def run_module6(
    state: WizardState,
    min_budget_threshold: float = 1.0,
    next_step: Optional[int] = None,
) -> WizardState:
    if not state.module3_finalised:
        raise ValueError("Module 6 requires Module 3 to be finalised.")
    if not state.module5_finalised:
        raise ValueError("Module 6 requires Module 5 to be finalised.")
    if state.module5_result is None:
        raise ValueError("Module 6 requires state.module5_result to be set.")
    if not state.kpi_ratios:
        raise ValueError("Module 6 requires state.kpi_ratios to be populated from Module 3.")

    forecast = compute_module6_forecast(
        kpi_ratios=state.kpi_ratios,
        module5_result=state.module5_result,
        min_budget_threshold=min_budget_threshold,
    )

    state.module6_result = forecast
    state.module6_finalised = True

    if next_step is not None:
        state.current_step = next_step
    else:
        state.current_step = max(state.current_step, 7)

    return state


if __name__ == "__main__":
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

    demo_state.kpi_ratios = {
        "ig": {
            "IG_AW_REACH": 120.0,
            "IG_EN_ENGRATERATE": 3.5,
        },
        "fb": {
            "FB_AW_REACH": 80.0,
        },
    }

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
