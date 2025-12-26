from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pulp

from core.wizard_state import WizardState, FlowStateError
from core.kpi_config import KPI_CONFIG


class Module5ValidationError(Exception):
    pass


@dataclass
class Module5LPInput:
    valid_goals: List[str]
    total_budget: float
    system_goal_weights: Dict[str, float]
    platform_goal_weights: Dict[str, Dict[str, float]]
    r_pg: Dict[str, Dict[str, float]]
    min_spend_per_platform: Dict[str, float]
    min_budget_per_goal: Dict[str, float]
    scenario_multipliers: Dict[str, float]


@dataclass
class Module5LPResult:
    budget_per_platform_goal: Dict[str, Dict[str, float]]
    budget_per_platform: Dict[str, float]
    total_budget_used: float
    objective_value: float
    r_pg: Dict[str, Dict[str, float]]
    combined_weight_pg: Dict[str, Dict[str, float]]
    estimated_kpi_per_platform_goal: Dict[str, Dict[str, float]]


@dataclass
class Module5ScenarioBundle:
    results_by_scenario: Dict[str, Module5LPResult]
    scenario_multipliers: Dict[str, float]

    def get_base(self) -> Module5LPResult:
        if "base" in self.results_by_scenario:
            return self.results_by_scenario["base"]
        if self.results_by_scenario:
            key = sorted(self.results_by_scenario.keys())[0]
            return self.results_by_scenario[key]
        raise Module5ValidationError("No scenario results available.")


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


def _nonneg_dict(d: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not d:
        return {}
    out: Dict[str, float] = {}
    for k, v in d.items():
        x = _safe_float(v, 0.0)
        if x < 0.0:
            x = 0.0
        out[str(k)] = x
    return out


def _build_r_pg_from_state(state: WizardState) -> Dict[str, Dict[str, float]]:
    if not getattr(state, "kpi_ratios", None):
        raise Module5ValidationError(
            "Module 5 cannot run, state.kpi_ratios is empty. Check Module 3."
        )

    if not getattr(state, "active_platforms", None):
        raise Module5ValidationError(
            "Module 5 cannot run, state.active_platforms is empty. Check Module 2."
        )

    vars_by_platform_goal: Dict[str, Dict[str, List[str]]] = {}
    for row in KPI_CONFIG:
        p = row["platform"]
        g = row["goal"]
        var = row["var"]
        if p not in vars_by_platform_goal:
            vars_by_platform_goal[p] = {}
        vars_by_platform_goal[p].setdefault(g, []).append(var)

    r_pg: Dict[str, Dict[str, float]] = {}

    for p in state.active_platforms:
        ratios_for_p = state.kpi_ratios.get(p, {})
        r_pg[p] = {}
        for g in state.valid_goals:
            kpi_vars = vars_by_platform_goal.get(p, {}).get(g, [])
            productivities: List[float] = []
            for var in kpi_vars:
                if var not in ratios_for_p:
                    continue
                val = _safe_float(ratios_for_p[var], 0.0)
                if val > 0.0:
                    productivities.append(val)
            if productivities:
                r_pg[p][g] = sum(productivities) / float(len(productivities))
            else:
                r_pg[p][g] = 0.0

    r_pg = {p: gdict for p, gdict in r_pg.items() if gdict}

    if not r_pg:
        raise Module5ValidationError(
            "Module 5 r_pg construction produced an empty dictionary. "
            "Check KPI_CONFIG, kpi_ratios, active_platforms and valid_goals."
        )

    return r_pg


def _build_system_goal_weights(state: WizardState) -> Dict[str, float]:
    if getattr(state, "system_goal_weights", None):
        raw = {
            g: max(0.0, _safe_float(w, 0.0))
            for g, w in state.system_goal_weights.items()
            if g in state.valid_goals
        }
        total = sum(raw.values())
        if total > 0.0:
            return {g: w / total for g, w in raw.items()}

    if not getattr(state, "valid_goals", None):
        raise Module5ValidationError(
            "Cannot build system_goal_weights because valid_goals is empty."
        )

    n = float(len(state.valid_goals))
    return {g: 1.0 / n for g in state.valid_goals}


def _build_platform_goal_weights_from_state(
    state: WizardState,
) -> Dict[str, Dict[str, float]]:
    if not getattr(state, "platform_weights", None):
        raise Module5ValidationError(
            "Module 5 cannot run, platform_weights is empty."
        )

    result: Dict[str, Dict[str, float]] = {}

    for p, weights in state.platform_weights.items():
        raw = {g: max(0.0, _safe_float(weights.get(g, 0.0), 0.0)) for g in state.valid_goals}
        total = sum(raw.values())
        if total > 0.0:
            norm = {g: w / total for g, w in raw.items()}
        else:
            norm = raw
        result[p] = norm

    return result


def _default_scenario_multipliers() -> Dict[str, float]:
    return {"conservative": 0.85, "base": 1.0, "optimistic": 1.15}


def _extract_policy_from_state(
    state: WizardState,
    valid_goals: List[str],
    active_platforms: List[str],
    total_budget: float,
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    min_spend_per_platform = _nonneg_dict(getattr(state, "min_spend_per_platform", None))
    min_budget_per_goal = _nonneg_dict(getattr(state, "min_budget_per_goal", None))
    scenario_multipliers = getattr(state, "scenario_multipliers", None)

    if not isinstance(scenario_multipliers, dict) or not scenario_multipliers:
        scenario_multipliers = _default_scenario_multipliers()

    sm: Dict[str, float] = {}
    for name, mult in scenario_multipliers.items():
        m = _safe_float(mult, 1.0)
        if m <= 0.0:
            continue
        sm[str(name)] = m
    if "base" not in sm:
        sm["base"] = 1.0

    min_spend_per_platform = {
        p: max(0.0, _safe_float(min_spend_per_platform.get(p, 0.0), 0.0))
        for p in active_platforms
    }

    min_budget_per_goal = {
        g: max(0.0, _safe_float(min_budget_per_goal.get(g, 0.0), 0.0))
        for g in valid_goals
    }

    sum_min_platform = sum(min_spend_per_platform.values())
    sum_min_goal = sum(min_budget_per_goal.values())

    if sum_min_platform > total_budget + 1e-9:
        raise Module5ValidationError(
            "Infeasible policy: sum of minimum platform spends exceeds total budget."
        )
    if sum_min_goal > total_budget + 1e-9:
        raise Module5ValidationError(
            "Infeasible policy: sum of minimum goal budgets exceeds total budget."
        )

    return min_spend_per_platform, min_budget_per_goal, sm


def build_module5_input_from_state(state: WizardState) -> Module5LPInput:
    if not state.module1_finalised:
        raise FlowStateError("Module 5 cannot run, Module 1 is not finalised.")
    if not state.module2_finalised:
        raise FlowStateError("Module 5 cannot run, Module 2 is not finalised.")
    if not state.module3_finalised:
        raise FlowStateError("Module 5 cannot run, Module 3 is not finalised.")
    if not state.module4_finalised:
        raise FlowStateError("Module 5 cannot run, Module 4 is not finalised.")

    if not state.valid_goals:
        raise Module5ValidationError(
            "Module 5 cannot run, valid_goals list is empty."
        )
    if state.total_budget is None or float(state.total_budget) <= 1:
        raise Module5ValidationError(
            "Module 5 cannot run, total_budget is missing or invalid."
        )

    system_goal_weights = _build_system_goal_weights(state)
    platform_goal_weights = _build_platform_goal_weights_from_state(state)
    r_pg = _build_r_pg_from_state(state)

    active_platforms = list(r_pg.keys())
    min_spend_per_platform, min_budget_per_goal, scenario_multipliers = _extract_policy_from_state(
        state=state,
        valid_goals=list(state.valid_goals),
        active_platforms=active_platforms,
        total_budget=float(state.total_budget),
    )

    return Module5LPInput(
        valid_goals=list(state.valid_goals),
        total_budget=float(state.total_budget),
        system_goal_weights=system_goal_weights,
        platform_goal_weights=platform_goal_weights,
        r_pg=r_pg,
        min_spend_per_platform=min_spend_per_platform,
        min_budget_per_goal=min_budget_per_goal,
        scenario_multipliers=scenario_multipliers,
    )


def _solve_single_lp(
    *,
    valid_goals: List[str],
    total_budget: float,
    system_goal_weights: Dict[str, float],
    platform_goal_weights: Dict[str, Dict[str, float]],
    r_pg: Dict[str, Dict[str, float]],
    min_spend_per_platform: Dict[str, float],
    min_budget_per_goal: Dict[str, float],
) -> Module5LPResult:
    if not valid_goals:
        raise Module5ValidationError("Module 5 LP, valid_goals is empty.")
    if total_budget <= 1:
        raise Module5ValidationError("Module 5 LP, total_budget must be greater than 1.")
    if not system_goal_weights:
        raise Module5ValidationError("Module 5 LP, system_goal_weights is empty.")
    if not platform_goal_weights:
        raise Module5ValidationError("Module 5 LP, platform_goal_weights is empty.")
    if not r_pg:
        raise Module5ValidationError("Module 5 LP, r_pg is empty.")

    platforms = list(r_pg.keys())

    combined_weight_pg: Dict[str, Dict[str, float]] = {}
    for p in platforms:
        combined_weight_pg[p] = {}
        platform_weights = platform_goal_weights.get(p, {})
        for g in valid_goals:
            w_g = _safe_float(system_goal_weights.get(g, 0.0), 0.0)
            W_pg = _safe_float(platform_weights.get(g, 0.0), 0.0)
            combined_weight_pg[p][g] = w_g * W_pg

    model = pulp.LpProblem("Budget_Allocation_Per_Platform_And_Goal", pulp.LpMaximize)

    x_vars: Dict[str, Dict[str, pulp.LpVariable]] = {}
    for p in platforms:
        x_vars[p] = {}
        for g in valid_goals:
            x_vars[p][g] = pulp.LpVariable(f"x_{p}_{g}", lowBound=0.0, cat="Continuous")

    model += pulp.lpSum(
        combined_weight_pg[p][g] * _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0) * x_vars[p][g]
        for p in platforms
        for g in valid_goals
    )

    model += (
        pulp.lpSum(x_vars[p][g] for p in platforms for g in valid_goals) <= total_budget
    )

    for p in platforms:
        min_p = _safe_float(min_spend_per_platform.get(p, 0.0), 0.0)
        if min_p > 0.0:
            model += pulp.lpSum(x_vars[p][g] for g in valid_goals) >= min_p

    for g in valid_goals:
        min_g = _safe_float(min_budget_per_goal.get(g, 0.0), 0.0)
        if min_g > 0.0:
            model += pulp.lpSum(x_vars[p][g] for p in platforms) >= min_g

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    status = pulp.LpStatus.get(model.status, "Unknown")
    if status not in ("Optimal", "Feasible"):
        raise Module5ValidationError(f"LP solve failed with status: {status}")

    budget_per_platform_goal: Dict[str, Dict[str, float]] = {}
    budget_per_platform: Dict[str, float] = {}
    estimated_kpi_per_platform_goal: Dict[str, Dict[str, float]] = {}

    for p in platforms:
        budget_per_platform_goal[p] = {}
        estimated_kpi_per_platform_goal[p] = {}
        total_p = 0.0

        for g in valid_goals:
            val = _safe_float(getattr(x_vars[p][g], "varValue", 0.0), 0.0)
            if val < 0.0:
                val = 0.0
            budget_per_platform_goal[p][g] = val
            total_p += val

            kpi_estimate = _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0) * val
            estimated_kpi_per_platform_goal[p][g] = kpi_estimate

        budget_per_platform[p] = total_p

    total_budget_used = sum(
        budget_per_platform_goal[p][g] for p in platforms for g in valid_goals
    )
    objective_value = _safe_float(pulp.value(model.objective), 0.0)

    return Module5LPResult(
        budget_per_platform_goal=budget_per_platform_goal,
        budget_per_platform=budget_per_platform,
        total_budget_used=total_budget_used,
        objective_value=objective_value,
        r_pg=r_pg,
        combined_weight_pg=combined_weight_pg,
        estimated_kpi_per_platform_goal=estimated_kpi_per_platform_goal,
    )


def run_module5_lp(input_data: Module5LPInput) -> Module5LPResult:
    return _solve_single_lp(
        valid_goals=input_data.valid_goals,
        total_budget=input_data.total_budget,
        system_goal_weights=input_data.system_goal_weights,
        platform_goal_weights=input_data.platform_goal_weights,
        r_pg=input_data.r_pg,
        min_spend_per_platform=input_data.min_spend_per_platform,
        min_budget_per_goal=input_data.min_budget_per_goal,
    )


def run_module5_lp_scenarios(input_data: Module5LPInput) -> Module5ScenarioBundle:
    if not input_data.scenario_multipliers:
        raise Module5ValidationError("scenario_multipliers is empty.")

    results: Dict[str, Module5LPResult] = {}

    for scenario_name, multiplier in input_data.scenario_multipliers.items():
        m = _safe_float(multiplier, 1.0)
        if m <= 0.0:
            continue

        adjusted_r_pg: Dict[str, Dict[str, float]] = {}
        for p, gdict in input_data.r_pg.items():
            adjusted_r_pg[p] = {}
            for g, r in gdict.items():
                val = _safe_float(r, 0.0)
                adjusted_r_pg[p][g] = max(0.0, val * m)

        results[scenario_name] = _solve_single_lp(
            valid_goals=input_data.valid_goals,
            total_budget=input_data.total_budget,
            system_goal_weights=input_data.system_goal_weights,
            platform_goal_weights=input_data.platform_goal_weights,
            r_pg=adjusted_r_pg,
            min_spend_per_platform=input_data.min_spend_per_platform,
            min_budget_per_goal=input_data.min_budget_per_goal,
        )

    if not results:
        raise Module5ValidationError("No scenario results were produced.")

    return Module5ScenarioBundle(
        results_by_scenario=results,
        scenario_multipliers=dict(input_data.scenario_multipliers),
    )


def run_module5(state: WizardState) -> WizardState:
    if state.module5_finalised:
        raise FlowStateError(
            "Module 5 has already been finalised. Reset the wizard to change it."
        )

    lp_input = build_module5_input_from_state(state)
    bundle = run_module5_lp_scenarios(lp_input)
    base_result = bundle.get_base()

    state.complete_module5_and_advance(module5_result=base_result)

    try:
        setattr(state, "module5_scenario_bundle", bundle)
    except Exception:
        pass

    try:
        setattr(state, "module5_results_by_scenario", bundle.results_by_scenario)
    except Exception:
        pass

    return state
