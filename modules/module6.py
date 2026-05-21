from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.wizard_state import WizardState
from core.kpi_config import KPI_CONFIG, KIND_COUNT, KIND_RATE
from modules.module5 import Module5LPResult, Module5ScenarioBundle


# KPI variable name → kind, built once at import time
_KPI_KIND: Dict[str, str] = {
    row["var"]: row.get("kind", KIND_COUNT)
    for row in KPI_CONFIG
}


@dataclass
class Module6ForecastRow:
    platform: str
    objective: str
    kpi_name: str
    kpi_kind: str          # KIND_COUNT or KIND_RATE
    ratio_kpi_per_budget: float   # count KPI: units/£; rate KPI: the rate value itself
    allocated_budget: float
    predicted_kpi: float          # count KPI: units; rate KPI: expected rate (dimensionless)


@dataclass
class Module6Diagnostics:
    total_rows: int = 0
    covered_platform_goal_pairs: int = 0
    skipped_zero_budget: int = 0
    skipped_missing_ratios: int = 0
    skipped_invalid_ratio_items: int = 0


@dataclass
class Module6Result:
    rows: List[Module6ForecastRow] = field(default_factory=list)
    diagnostics: Module6Diagnostics = field(default_factory=Module6Diagnostics)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "platform": r.platform,
                "objective": r.objective,
                "kpi_name": r.kpi_name,
                "kpi_kind": r.kpi_kind,
                "ratio_kpi_per_budget": r.ratio_kpi_per_budget,
                "allocated_budget": r.allocated_budget,
                "predicted_kpi": r.predicted_kpi,
            }
            for r in self.rows
        ]

    def to_pandas(self):
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError("pandas is required to use Module6Result.to_pandas().") from exc
        return pd.DataFrame(self.to_dict_list())

    def summary(self) -> Dict[str, Any]:
        d = self.diagnostics
        return {
            "total_rows": d.total_rows,
            "covered_platform_goal_pairs": d.covered_platform_goal_pairs,
            "skipped_zero_budget": d.skipped_zero_budget,
            "skipped_missing_ratios": d.skipped_missing_ratios,
            "skipped_invalid_ratio_items": d.skipped_invalid_ratio_items,
        }


@dataclass
class Module6ScenarioResult:
    results_by_scenario: Dict[str, Module6Result] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        return {name: res.to_dict_list() for name, res in self.results_by_scenario.items()}

    def to_pandas_dict(self):
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError("pandas is required to use Module6ScenarioResult.to_pandas_dict().") from exc
        return {name: pd.DataFrame(res.to_dict_list()) for name, res in self.results_by_scenario.items()}

    def get_base(self) -> Module6Result:
        if "base" in self.results_by_scenario:
            return self.results_by_scenario["base"]
        if self.results_by_scenario:
            key = sorted(self.results_by_scenario.keys())[0]
            return self.results_by_scenario[key]
        return Module6Result(rows=[])


def _norm_platform(value: Any) -> str:
    return str(value).strip().lower()


def _norm_goal(value: Any) -> str:
    return str(value).strip().lower()


def _norm_kpi(value: Any) -> str:
    return str(value).strip()


def compute_module6_forecast(
    kpi_ratios: Dict[str, Dict[str, Dict[str, float]]],
    module5_result: Module5LPResult,
    min_budget_threshold: float = 1.0,
) -> Module6Result:
    """Produce per-KPI forecasts from the LP allocation.

    For count KPIs (e.g. Reach, Leads):
        predicted = (historical_count / historical_budget) × allocated_budget

    For rate KPIs (e.g. Engagement Rate):
        predicted = historical_rate  (rates don't scale with spend; multiplying by
        budget would produce meaningless units)
    """
    if min_budget_threshold <= 0:
        raise ValueError("min_budget_threshold must be greater than 0.")

    d = Module6Diagnostics()
    rows: List[Module6ForecastRow] = []

    allocation_pg = module5_result.budget_per_platform_goal or {}

    for p_raw, gmap in allocation_pg.items():
        if not isinstance(gmap, dict) or not gmap:
            continue
        p = _norm_platform(p_raw)

        for g_raw, allocated in gmap.items():
            g = _norm_goal(g_raw)

            try:
                budget_val = float(allocated)
            except (TypeError, ValueError):
                budget_val = 0.0

            if budget_val < min_budget_threshold:
                d.skipped_zero_budget += 1
                continue

            ratios_for_goal = (kpi_ratios.get(p) or {}).get(g) or {}
            if not ratios_for_goal:
                d.skipped_missing_ratios += 1
                continue

            any_row = False
            for kpi_name_raw, ratio in ratios_for_goal.items():
                kpi_name = _norm_kpi(kpi_name_raw)

                try:
                    ratio_val = float(ratio)
                except (TypeError, ValueError):
                    d.skipped_invalid_ratio_items += 1
                    continue

                if ratio_val <= 0.0:
                    d.skipped_invalid_ratio_items += 1
                    continue

                kind = _KPI_KIND.get(kpi_name, KIND_COUNT)

                if kind == KIND_RATE:
                    # Engagement-rate style KPIs are dimensionless proportions.
                    # The ratio stored by Module 3 IS the rate value (not rate/budget),
                    # so the forecast is simply that rate — multiplying by budget would
                    # give wrong units (e.g. "4.5% × £3,000 = ???").
                    predicted = ratio_val
                else:
                    # Count KPIs: ratio = historical_count / historical_budget
                    # → predicted count = ratio × allocated_budget
                    predicted = ratio_val * budget_val

                if predicted <= 0.0:
                    d.skipped_invalid_ratio_items += 1
                    continue

                rows.append(
                    Module6ForecastRow(
                        platform=p,
                        objective=g,
                        kpi_name=kpi_name,
                        kpi_kind=kind,
                        ratio_kpi_per_budget=ratio_val,
                        allocated_budget=budget_val,
                        predicted_kpi=predicted,
                    )
                )
                any_row = True

            if any_row:
                d.covered_platform_goal_pairs += 1

    rows.sort(key=lambda r: (r.platform, r.objective, r.kpi_name))
    d.total_rows = len(rows)

    return Module6Result(rows=rows, diagnostics=d)


def compute_module6_forecast_for_scenarios(
    kpi_ratios: Dict[str, Dict[str, Dict[str, float]]],
    module5_bundle: Module5ScenarioBundle,
    min_budget_threshold: float = 1.0,
) -> Module6ScenarioResult:
    results_by_scenario: Dict[str, Module6Result] = {}
    for scenario_name, lp_res in module5_bundle.results_by_scenario.items():
        results_by_scenario[str(scenario_name)] = compute_module6_forecast(
            kpi_ratios=kpi_ratios,
            module5_result=lp_res,
            min_budget_threshold=min_budget_threshold,
        )
    return Module6ScenarioResult(results_by_scenario=results_by_scenario)


def run_module6(
    state: WizardState,
    min_budget_threshold: float = 1.0,
) -> WizardState:
    if not state.module3_finalised:
        raise ValueError("Module 6 requires Module 3 to be finalised.")
    if not state.module5_finalised:
        raise ValueError("Module 6 requires Module 5 to be finalised.")
    if not getattr(state, "kpi_ratios", None):
        raise ValueError("Module 6 requires state.kpi_ratios to be populated from Module 3.")

    bundle = getattr(state, "module5_scenario_bundle", None)

    if isinstance(bundle, Module5ScenarioBundle):
        scenario_forecast = compute_module6_forecast_for_scenarios(
            kpi_ratios=state.kpi_ratios,
            module5_bundle=bundle,
            min_budget_threshold=min_budget_threshold,
        )
        state.complete_module6(
            module6_result=scenario_forecast.get_base(),
            module6_scenario_result=scenario_forecast,
        )
    else:
        if state.module5_result is None:
            raise ValueError("Module 6 requires state.module5_result to be set.")
        forecast = compute_module6_forecast(
            kpi_ratios=state.kpi_ratios,
            module5_result=state.module5_result,
            min_budget_threshold=min_budget_threshold,
        )
        state.complete_module6(
            module6_result=forecast,
            module6_scenario_result=None,
        )

    return state
