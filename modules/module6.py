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
    total_platform_goal_pairs_seen: int = 0
    total_platform_goal_pairs_with_budget: int = 0
    covered_platform_goal_pairs: int = 0

    skipped_zero_or_small_budget_pg: int = 0
    skipped_missing_ratios_pg: int = 0
    skipped_invalid_ratio_items: int = 0

    allocation_platforms_seen: int = 0
    ratios_platforms_seen: int = 0

    allocation_goals_seen: int = 0
    ratios_goals_seen: int = 0

    unknown_platform_in_ratios: int = 0
    unknown_goal_in_ratios: int = 0

    budget_missing_or_invalid_in_allocation: int = 0
    ratios_non_dict_or_invalid: int = 0

    ratios_items_total: int = 0
    ratios_items_positive_used: int = 0


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
            "total_platform_goal_pairs_seen": int(d.total_platform_goal_pairs_seen),
            "total_platform_goal_pairs_with_budget": int(d.total_platform_goal_pairs_with_budget),
            "covered_platform_goal_pairs": int(d.covered_platform_goal_pairs),
            "skipped_zero_or_small_budget_pg": int(d.skipped_zero_or_small_budget_pg),
            "skipped_missing_ratios_pg": int(d.skipped_missing_ratios_pg),
            "skipped_invalid_ratio_items": int(d.skipped_invalid_ratio_items),
            "allocation_platforms_seen": int(d.allocation_platforms_seen),
            "ratios_platforms_seen": int(d.ratios_platforms_seen),
            "allocation_goals_seen": int(d.allocation_goals_seen),
            "ratios_goals_seen": int(d.ratios_goals_seen),
            "unknown_platform_in_ratios": int(d.unknown_platform_in_ratios),
            "unknown_goal_in_ratios": int(d.unknown_goal_in_ratios),
            "budget_missing_or_invalid_in_allocation": int(d.budget_missing_or_invalid_in_allocation),
            "ratios_non_dict_or_invalid": int(d.ratios_non_dict_or_invalid),
            "ratios_items_total": int(d.ratios_items_total),
            "ratios_items_positive_used": int(d.ratios_items_positive_used),
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


def _norm_platform(value: Any) -> str:
    s = str(value).strip().lower()
    return s


def _norm_goal(value: Any) -> str:
    s = str(value).strip().lower()
    return s


def _norm_kpi(value: Any) -> str:
    s = str(value).strip()
    return s


def _normalise_allocation_pg(
    allocation_pg: Any,
) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(allocation_pg, dict):
        return out

    for p, gmap in allocation_pg.items():
        p_key = _norm_platform(p)
        if not isinstance(gmap, dict) or not gmap:
            continue
        out.setdefault(p_key, {})
        for g, v in gmap.items():
            g_key = _norm_goal(g)
            out[p_key][g_key] = _safe_float(v, 0.0)

    return out


def _normalise_ratios_pgv(
    kpi_ratios: Any,
    *,
    known_platforms: Optional[List[str]] = None,
    known_goals: Optional[List[str]] = None,
    diagnostics: Optional[Module6Diagnostics] = None,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    if not isinstance(kpi_ratios, dict):
        if diagnostics is not None:
            diagnostics.ratios_non_dict_or_invalid += 1
        return out

    platforms_seen: set[str] = set()
    goals_seen: set[str] = set()

    known_p = set([_norm_platform(p) for p in (known_platforms or [])])
    known_g = set([_norm_goal(g) for g in (known_goals or [])])

    for p, gmap in kpi_ratios.items():
        p_key = _norm_platform(p)
        platforms_seen.add(p_key)

        if known_p and p_key not in known_p:
            if diagnostics is not None:
                diagnostics.unknown_platform_in_ratios += 1

        if not isinstance(gmap, dict) or not gmap:
            continue

        out.setdefault(p_key, {})

        for g, vmap in gmap.items():
            g_key = _norm_goal(g)
            goals_seen.add(g_key)

            if known_g and g_key not in known_g:
                if diagnostics is not None:
                    diagnostics.unknown_goal_in_ratios += 1

            if not isinstance(vmap, dict) or not vmap:
                continue

            out[p_key].setdefault(g_key, {})

            for var, val in vmap.items():
                k_key = _norm_kpi(var)
                out[p_key][g_key][k_key] = _safe_float(val, 0.0)

    if diagnostics is not None:
        diagnostics.ratios_platforms_seen = len(platforms_seen)
        diagnostics.ratios_goals_seen = len(goals_seen)

    return out


def _collect_allocation_stats(
    allocation_pg: Dict[str, Dict[str, float]],
    diagnostics: Module6Diagnostics,
) -> Tuple[List[str], List[str]]:
    p_set: set[str] = set()
    g_set: set[str] = set()

    for p, gmap in allocation_pg.items():
        p_set.add(p)
        if isinstance(gmap, dict):
            for g in gmap.keys():
                g_set.add(g)

    diagnostics.allocation_platforms_seen = len(p_set)
    diagnostics.allocation_goals_seen = len(g_set)

    return sorted(p_set), sorted(g_set)


def compute_module6_forecast(
    kpi_ratios: Dict[str, Dict[str, Dict[str, float]]],
    module5_result: Module5LPResult,
    min_budget_threshold: float = 1.0,
) -> Module6Result:
    if min_budget_threshold <= 0:
        raise ValueError("min_budget_threshold must be greater than 0.")

    d = Module6Diagnostics()
    rows: List[Module6ForecastRow] = []

    allocation_pg_raw = getattr(module5_result, "budget_per_platform_goal", None)
    allocation_pg = _normalise_allocation_pg(allocation_pg_raw)

    known_platforms, known_goals = _collect_allocation_stats(allocation_pg, d)
    ratios_pgv = _normalise_ratios_pgv(
        kpi_ratios,
        known_platforms=known_platforms,
        known_goals=known_goals,
        diagnostics=d,
    )

    for p, gmap in allocation_pg.items():
        if not isinstance(gmap, dict) or not gmap:
            continue

        for g, allocated in gmap.items():
            d.total_platform_goal_pairs_seen += 1

            budget_val = _safe_float(allocated, 0.0)
            if budget_val <= 0.0:
                d.budget_missing_or_invalid_in_allocation += 1

            if budget_val < min_budget_threshold:
                d.skipped_zero_or_small_budget_pg += 1
                continue

            d.total_platform_goal_pairs_with_budget += 1

            ratios_for_goal = ratios_pgv.get(p, {}).get(g, {})
            if not isinstance(ratios_for_goal, dict) or not ratios_for_goal:
                d.skipped_missing_ratios_pg += 1
                continue

            any_row = False

            for kpi_name, ratio in ratios_for_goal.items():
                d.ratios_items_total += 1

                ratio_val = _safe_float(ratio, 0.0)
                if ratio_val <= 0.0:
                    d.skipped_invalid_ratio_items += 1
                    continue

                predicted = ratio_val * budget_val
                if predicted <= 0.0:
                    d.skipped_invalid_ratio_items += 1
                    continue

                d.ratios_items_positive_used += 1
                any_row = True

                rows.append(
                    Module6ForecastRow(
                        platform=str(p),
                        objective=str(g),
                        kpi_name=str(kpi_name),
                        ratio_kpi_per_budget=ratio_val,
                        allocated_budget=budget_val,
                        predicted_kpi=predicted,
                    )
                )

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

    state.module6_finalised = True

    if next_step is not None:
        state.current_step = next_step
    else:
        state.current_step = max(state.current_step, 7)

    return state
