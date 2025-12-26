from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.wizard_state import WizardState
from modules.module5 import Module5LPResult, Module5ScenarioBundle


@dataclass
class Module6ForecastRow:
    platform: str
    objective: str
    kpi_name: str
    ratio_kpi_per_budget: float
    allocated_budget: float
    predicted_kpi: float


@dataclass
class Module6Diagnostics:
    total_rows: int = 0
    skipped_zero_or_small_budget_pg: int = 0
    skipped_missing_ratios_pg: int = 0
    skipped_invalid_ratio_items: int = 0
    covered_platform_goal_pairs: int = 0
    total_platform_goal_pairs_with_budget: int = 0


@dataclass
class Module6Result:
    rows: List[Module6ForecastRow] = field(default_factory=list)
    diagnostics: Module6Diagnostics = field(default_factory=Module6Diagnostics)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for row in self.rows:
            result.append(
                {
                    "platform": row.platform,
                    "objective": row.objective,
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
            raise ImportError("pandas is required to use Module6Result.to_pandas().") from exc
        return pd.DataFrame(self.to_dict_list())

    def summary(self) -> Dict[str, Any]:
        d = self.diagnostics
        return {
            "total_rows": int(d.total_rows),
            "total_platform_goal_pairs_with_budget": int(d.total_platform_goal_pairs_with_budget),
            "covered_platform_goal_pairs": int(d.covered_platform_goal_pairs),
            "skipped_zero_or_small_budget_pg": int(d.skipped_zero_or_small_budget_pg),
            "skipped_missing_ratios_pg": int(d.skipped_missing_ratios_pg),
            "skipped_invalid_ratio_items": int(d.skipped_invalid_ratio_items),
        }


@dataclass
class Module6ScenarioResult:
    results_by_scenario: Dict[str, Module6Result] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for name, res in self.results_by_scenario.items():
            out[str(name)] = res.to_dict_list()
        return out

    def to_pandas_dict(self):
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError("pandas is required to use Module6ScenarioResult.to_pandas_dict().") from exc

        out: Dict[str, Any] = {}
        for name, res in self.results_by_scenario.items():
            out[str(name)] = pd.DataFrame(res.to_dict_list())
        return out

    def get_base(self) -> Module6Result:
        if "base" in self.results_by_scenario:
            return self.results_by_scenario["base"]
        if self.results_by_scenario:
            key = sorted(self.results_by_scenario.keys())[0]
            return self.results_by_scenario[key]
        return Module6Result(rows=[])


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
    except Exception:
        return default
    if x != x:
        return default
    if x == float("inf") or x == float("-inf"):
        return default
    return x


def _normalise_keys_pg(
    allocation_pg: Dict[Any, Dict[Any, Any]]
) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for p, gmap in (allocation_pg or {}).items():
        p_key = str(p)
        if not isinstance(gmap, dict) or not gmap:
            continue
        out[p_key] = {}
        for g, v in gmap.items():
            out[p_key][str(g)] = _safe_float(v, 0.0)
    return out


def _normalise_ratios_pgv(
    kpi_ratios: Dict[Any, Dict[Any, Dict[Any, Any]]]
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for p, gmap in (kpi_ratios or {}).items():
        if not isinstance(gmap, dict) or not gmap:
            continue
        p_key = str(p)
        out[p_key] = {}
        for g, vmap in gmap.items():
            if not isinstance(vmap, dict) or not vmap:
                continue
            g_key = str(g)
            out[p_key][g_key] = {}
            for var, val in vmap.items():
                out[p_key][g_key][str(var)] = _safe_float(val, 0.0)
    return out


def compute_module6_forecast(
    kpi_ratios: Dict[str, Dict[str, Dict[str, float]]],
    module5_result: Module5LPResult,
    min_budget_threshold: float = 1.0,
) -> Module6Result:
    if min_budget_threshold <= 0:
        raise ValueError("min_budget_threshold must be greater than 0.")

    diagnostics = Module6Diagnostics()
    rows: List[Module6ForecastRow] = []

    allocation_pg = _normalise_keys_pg(module5_result.budget_per_platform_goal or {})
    ratios_pgv = _normalise_ratios_pgv(kpi_ratios)

    pg_with_budget: List[Tuple[str, str, float]] = []
    for p, gmap in allocation_pg.items():
        for g, b in gmap.items():
            if b >= min_budget_threshold:
                pg_with_budget.append((p, g, b))
    diagnostics.total_platform_goal_pairs_with_budget = len(pg_with_budget)

    covered_pairs = 0

    for platform, goal, budget_val in pg_with_budget:
        ratios_for_goal = ratios_pgv.get(platform, {}).get(goal, {})
        if not ratios_for_goal:
            diagnostics.skipped_missing_ratios_pg += 1
            continue

        valid_item_found = False
        for kpi_name, ratio in ratios_for_goal.items():
            ratio_val = _safe_float(ratio, 0.0)
            if ratio_val <= 0.0:
                diagnostics.skipped_invalid_ratio_items += 1
                continue

            predicted_kpi = ratio_val * budget_val
            if predicted_kpi <= 0.0:
                diagnostics.skipped_invalid_ratio_items += 1
                continue

            valid_item_found = True
            rows.append(
                Module6ForecastRow(
                    platform=str(platform),
                    objective=str(goal),
                    kpi_name=str(kpi_name),
                    ratio_kpi_per_budget=ratio_val,
                    allocated_budget=budget_val,
                    predicted_kpi=predicted_kpi,
                )
            )

        if valid_item_found:
            covered_pairs += 1

    diagnostics.covered_platform_goal_pairs = covered_pairs
    diagnostics.total_rows = len(rows)

    rows.sort(key=lambda r: (r.platform, r.objective, r.kpi_name))
    return Module6Result(rows=rows, diagnostics=diagnostics)


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
    next_step: Optional[int] = None,
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
        state.module6_scenario_result = scenario_forecast
        state.module6_result = scenario_forecast.get_base()
    else:
        if state.module5_result is None:
            raise ValueError("Module 6 requires state.module5_result to be set.")
        forecast = compute_module6_forecast(
            kpi_ratios=state.kpi_ratios,
            module5_result=state.module5_result,
            min_budget_threshold=min_budget_threshold,
        )
        state.module6_result = forecast
        state.module6_scenario_result = None

    try:
        state.module6_diagnostics = (
            state.module6_result.diagnostics.summary() if state.module6_result is not None else {}
        )
    except Exception:
        pass

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
            "aw": {"IG_AW_REACH": 120.0},
            "en": {"IG_EN_ENGRATERATE": 3.5},
        },
        "fb": {
            "aw": {"FB_AW_REACH": 80.0},
            "en": {"FB_EN_ENGAGEMENT": 3.75},
        },
    }

    base_res = Module5LPResult(
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

    demo_state.module5_result = base_res
    demo_state = run_module6(demo_state, next_step=8)

    if demo_state.module6_result is not None:
        print(demo_state.module6_result.summary())
        for row in demo_state.module6_result.rows:
            print(
                row.platform,
                row.objective,
                row.kpi_name,
                "budget:", row.allocated_budget,
                "ratio:", row.ratio_kpi_per_budget,
                "predicted:", row.predicted_kpi,
            )
