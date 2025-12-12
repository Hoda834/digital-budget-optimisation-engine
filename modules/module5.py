from dataclasses import dataclass
from typing import Any, Dict, List

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


@dataclass
class Module5LPResult:
    budget_per_platform_goal: Dict[str, Dict[str, float]]
    budget_per_platform: Dict[str, float]
    total_budget_used: float
    objective_value: float
    r_pg: Dict[str, Dict[str, float]]
    combined_weight_pg: Dict[str, Dict[str, float]]
    estimated_kpi_per_platform_goal: Dict[str, Dict[str, float]]


def _build_r_pg_from_state(state: WizardState) -> Dict[str, Dict[str, float]]:
    if not state.kpi_ratios:
        raise Module5ValidationError(
            "Module 5 cannot run, state.kpi_ratios is empty. Check Module 3."
        )

    if not state.active_platforms:
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
                val = float(ratios_for_p[var])
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


def run_module5_lp(input_data: Module5LPInput) -> Module5LPResult:
    if not input_data.valid_goals:
        raise Module5ValidationError("Module 5 LP, valid_goals is empty.")

    if input_data.total_budget is None or input_data.total_budget <= 1:
        raise Module5ValidationError(
            "Module 5 LP, total_budget must be greater than 1."
        )

    if not input_data.system_goal_weights:
        raise Module5ValidationError(
            "Module 5 LP, system_goal_weights is empty."
        )

    if not input_data.platform_goal_weights:
        raise Module5ValidationError(
            "Module 5 LP, platform_goal_weights is empty."
        )

    if not input_data.r_pg:
        raise Module5ValidationError("Module 5 LP, r_pg is empty.")

    platforms = list(input_data.r_pg.keys())

    combined_weight_pg: Dict[str, Dict[str, float]] = {}
    for p in platforms:
        combined_weight_pg[p] = {}
        platform_weights = input_data.platform_goal_weights.get(p, {})
        for g in input_data.valid_goals:
            w_g = float(input_data.system_goal_weights.get(g, 0.0))
            W_pg = float(platform_weights.get(g, 0.0))
            combined_weight_pg[p][g] = w_g * W_pg

    model = pulp.LpProblem(
        "Budget_Allocation_Per_Platform_And_Goal",
        pulp.LpMaximize,
    )

    x_vars: Dict[str, Dict[str, pulp.LpVariable]] = {}
    for p in platforms:
        x_vars[p] = {}
        for g in input_data.valid_goals:
            var_name = f"x_{p}_{g}"
            x_vars[p][g] = pulp.LpVariable(
                var_name,
                lowBound=0.0,
                cat="Continuous",
            )

    model += pulp.lpSum(
        combined_weight_pg[p][g]
        * input_data.r_pg.get(p, {}).get(g, 0.0)
        * x_vars[p][g]
        for p in platforms
        for g in input_data.valid_goals
    ), "Weighted_Sum_Objective"

    model += pulp.lpSum(
        x_vars[p][g] for p in platforms for g in input_data.valid_goals
    ) <= input_data.total_budget, "Total_Budget_Upper_Bound"

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    budget_per_platform_goal: Dict[str, Dict[str, float]] = {}
    budget_per_platform: Dict[str, float] = {}
    estimated_kpi_per_platform_goal: Dict[str, Dict[str, float]] = {}

    for p in platforms:
        budget_per_platform_goal[p] = {}
        estimated_kpi_per_platform_goal[p] = {}
        total_p = 0.0

        for g in input_data.valid_goals:
            val = float(x_vars[p][g].varValue or 0.0)
            budget_per_platform_goal[p][g] = val
            total_p += val

            kpi_estimate = input_data.r_pg.get(p, {}).get(g, 0.0) * val
            estimated_kpi_per_platform_goal[p][g] = kpi_estimate

        budget_per_platform[p] = total_p

    total_budget_used = sum(
        budget_per_platform_goal[p][g]
        for p in platforms
        for g in input_data.valid_goals
    )
    objective_value = float(pulp.value(model.objective))

    return Module5LPResult(
        budget_per_platform_goal=budget_per_platform_goal,
        budget_per_platform=budget_per_platform,
        total_budget_used=total_budget_used,
        objective_value=objective_value,
        r_pg=input_data.r_pg,
        combined_weight_pg=combined_weight_pg,
        estimated_kpi_per_platform_goal=estimated_kpi_per_platform_goal,
    )


def _build_system_goal_weights(state: WizardState) -> Dict[str, float]:
    if state.system_goal_weights:
        raw = {
            g: max(0.0, float(w))
            for g, w in state.system_goal_weights.items()
            if g in state.valid_goals
        }
        total = sum(raw.values())
        if total > 0:
            return {g: w / total for g, w in raw.items()}

    if not state.valid_goals:
        raise Module5ValidationError(
            "Cannot build system_goal_weights because valid_goals is empty."
        )

    n = float(len(state.valid_goals))
    return {g: 1.0 / n for g in state.valid_goals}


def _build_platform_goal_weights_from_state(
    state: WizardState,
) -> Dict[str, Dict[str, float]]:
    if not state.platform_weights:
        raise Module5ValidationError(
            "Module 5 cannot run, platform_weights is empty."
        )

    result: Dict[str, Dict[str, float]] = {}

    for p, weights in state.platform_weights.items():
        raw = {
            g: max(0.0, float(weights.get(g, 0.0)))
            for g in state.valid_goals
        }
        total = sum(raw.values())
        if total > 0:
            norm = {g: w / total for g, w in raw.items()}
        else:
            norm = raw
        result[p] = norm

    return result


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
    if state.total_budget is None or state.total_budget <= 1:
        raise Module5ValidationError(
            "Module 5 cannot run, total_budget is missing or invalid."
        )

    system_goal_weights = _build_system_goal_weights(state)
    platform_goal_weights = _build_platform_goal_weights_from_state(state)
    r_pg = _build_r_pg_from_state(state)

    return Module5LPInput(
        valid_goals=list(state.valid_goals),
        total_budget=float(state.total_budget),
        system_goal_weights=system_goal_weights,
        platform_goal_weights=platform_goal_weights,
        r_pg=r_pg,
    )


def run_module5(state: WizardState) -> WizardState:
    if state.module5_finalised:
        raise FlowStateError(
            "Module 5 has already been finalised. Reset the wizard to change it."
        )

    lp_input = build_module5_input_from_state(state)
    lp_result = run_module5_lp(lp_input)

    state.complete_module5_and_advance(module5_result=lp_result)

    return state
