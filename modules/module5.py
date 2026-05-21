from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import math

import pulp

from core.wizard_state import WizardState, FlowStateError
from core.kpi_config import KPI_CONFIG, KIND_COUNT, KIND_RATE


class Module5ValidationError(Exception):
    pass


OBJECTIVE_SCALE = 1000.0

# Three diminishing-returns brackets per (platform, goal) cell.
# Each tuple is (cap_fraction_of_total_budget, yield_multiplier).
# The LP can pour budget into bracket b only after bracket b-1 is full,
# at a yield = base_r_pg × yield_multiplier for that bracket.
YIELD_BRACKETS: Tuple[Tuple[float, float], ...] = (
    (0.25, 1.00),
    (0.35, 0.65),
    (0.40, 0.35),
)


@dataclass
class Module5LPInput:
    valid_goals: List[str]
    total_budget: float
    system_goal_weights: Dict[str, float]
    platform_goal_weights: Dict[str, Dict[str, float]]
    r_pg: Dict[str, Dict[str, float]]
    goals_by_platform: Dict[str, List[str]]
    min_spend_per_platform: Dict[str, float]
    min_budget_per_goal: Dict[str, float]
    scenario_multipliers: Dict[str, float]
    scenario_goal_multipliers: Dict[str, Dict[str, float]]
    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)


@dataclass
class Module5LPResult:
    budget_per_platform_goal: Dict[str, Dict[str, float]]
    budget_per_platform: Dict[str, float]
    total_budget_used: float
    objective_value: float
    r_pg: Dict[str, Dict[str, float]]
    combined_weight_pg: Dict[str, Dict[str, float]]
    estimated_kpi_per_platform_goal: Dict[str, Dict[str, float]]
    objective_value_raw: float = 0.0
    effective_budget_cap: float = 0.0
    # M4's cost-per-unit-KPI table, attached for reporting/UI. Not used in the LP
    # itself (the LP needs yields, which are the reciprocals); exposed here so
    # downstream modules and the UI can present both views.
    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)


@dataclass
class Module5ScenarioBundle:
    results_by_scenario: Dict[str, Module5LPResult]
    scenario_multipliers: Dict[str, float]
    scenario_goal_multipliers: Dict[str, Dict[str, float]]

    def get_base(self) -> Module5LPResult:
        if "base" in self.results_by_scenario:
            return self.results_by_scenario["base"]
        if self.results_by_scenario:
            key = sorted(self.results_by_scenario.keys())[0]
            return self.results_by_scenario[key]
        raise Module5ValidationError("No scenario results available.")


def _to_finite_float(value: Any, *, label: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as e:
        raise Module5ValidationError(f"{label} must be numeric, got {value!r}.") from e
    if math.isnan(x) or math.isinf(x):
        raise Module5ValidationError(f"{label} must be finite, got {value!r}.")
    return x


def _safe_float(value: Any, default: float = 0.0) -> float:
    # Lenient coercion used for optional inputs only. Bad data still raises elsewhere.
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(x) or math.isinf(x):
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
    if not any(state.kpi_ratios.values()):
        raise Module5ValidationError(
            "Module 5 cannot run, state.kpi_ratios has no per-platform data. "
            "Check Module 3 (shape mismatch or no KPI values collected)."
        )

    if not getattr(state, "active_platforms", None):
        raise Module5ValidationError(
            "Module 5 cannot run, state.active_platforms is empty. Check Module 2."
        )

    # Look up KPI kind per (platform, var) so we know whether to treat r as rate or per-money.
    kind_lookup: Dict[Tuple[str, str], str] = {
        (row["platform"], row["var"]): row.get("kind", KIND_COUNT)
        for row in KPI_CONFIG
    }

    r_pg: Dict[str, Dict[str, float]] = {}
    populated_cells = 0

    for p in state.active_platforms:
        ratios_for_p = state.kpi_ratios.get(p, {})
        if not isinstance(ratios_for_p, dict) or not ratios_for_p:
            continue

        r_pg[p] = {}
        for g in state.valid_goals:
            ratios_for_pg = ratios_for_p.get(g, {})
            if not isinstance(ratios_for_pg, dict):
                ratios_for_pg = {}

            # Separate counts (per-money productivity) from rates (dimensionless).
            count_vals: List[float] = []
            rate_vals: List[float] = []
            for var, raw_val in ratios_for_pg.items():
                kind = kind_lookup.get((p, var), KIND_COUNT)
                val = _safe_float(raw_val, 0.0)
                if val <= 0.0:
                    continue
                if kind == KIND_RATE:
                    rate_vals.append(val)
                else:
                    count_vals.append(val)

            # When both kinds are present, the count productivity is the LP-meaningful
            # signal (currency-scaled). The rate becomes a soft multiplicative boost so
            # that, say, "engagement rate" still tilts the optimiser without distorting
            # units. When only rates exist (LI/IG/YT engagement), we use the rate itself.
            if count_vals:
                productivity = sum(count_vals) / float(len(count_vals))
                if rate_vals:
                    rate_mean = sum(rate_vals) / float(len(rate_vals))
                    productivity *= (1.0 + rate_mean)
            elif rate_vals:
                productivity = sum(rate_vals) / float(len(rate_vals))
            else:
                productivity = 0.0

            r_pg[p][g] = productivity
            if productivity > 0.0:
                populated_cells += 1

    r_pg = {p: gdict for p, gdict in r_pg.items() if any(v > 0 for v in gdict.values())}

    if populated_cells == 0 or not r_pg:
        raise Module5ValidationError(
            "Module 5 r_pg construction produced no positive productivities. "
            "Check that Module 3 KPI values align with KPI_CONFIG (variable names match) "
            "and that goals_by_platform from Module 2 covers at least one KPI per cell."
        )

    return r_pg


def _build_system_goal_weights(state: WizardState) -> Dict[str, float]:
    # 1) honour any caller-set weights
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
        raise Module5ValidationError("Cannot build system_goal_weights because valid_goals is empty.")

    # 2) derive from Module 2 platform priorities: each platform contributes
    #    rank-1 -> 2, rank-2 -> 1 to its respective goal. This makes the system-level
    #    weight a frequency-weighted preference instead of inert uniformity.
    derived: Dict[str, float] = {g: 0.0 for g in state.valid_goals}
    priority_map = getattr(state, "priority_rank", {}) or {}
    for p, ranks in priority_map.items():
        if not isinstance(ranks, dict):
            continue
        for g, rank in ranks.items():
            if g not in derived:
                continue
            if rank == 1:
                derived[g] += 2.0
            elif rank == 2:
                derived[g] += 1.0

    total = sum(derived.values())
    if total > 0.0:
        return {g: w / total for g, w in derived.items()}

    # 3) last resort: uniform
    n = float(len(state.valid_goals))
    return {g: 1.0 / n for g in state.valid_goals}


def _build_platform_goal_weights_from_state(state: WizardState) -> Dict[str, Dict[str, float]]:
    if not getattr(state, "platform_weights", None):
        raise Module5ValidationError("Module 5 cannot run, platform_weights is empty.")

    result: Dict[str, Dict[str, float]] = {}

    for p, weights in state.platform_weights.items():
        raw = {g: max(0.0, _safe_float(weights.get(g, 0.0), 0.0)) for g in state.valid_goals}
        total = sum(raw.values())
        if total > 0.0:
            norm = {g: w / total for g, w in raw.items()}
        else:
            norm = raw
        result[str(p)] = norm

    return result


def _default_scenario_multipliers() -> Dict[str, float]:
    return {"conservative": 0.85, "base": 1.0, "optimistic": 1.15}


def _default_scenario_goal_multipliers(valid_goals: List[str]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {
        "base": {g: 1.0 for g in valid_goals},
        "conservative": {g: 1.0 for g in valid_goals},
        "optimistic": {g: 1.0 for g in valid_goals},
    }
    return out


def _extract_policy_from_state(
    state: WizardState,
    valid_goals: List[str],
    active_platforms: List[str],
    total_budget: float,
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float], Dict[str, Dict[str, float]]]:
    min_spend_per_platform = _nonneg_dict(getattr(state, "min_spend_per_platform", None))
    min_budget_per_goal = _nonneg_dict(getattr(state, "min_budget_per_goal", None))

    scenario_multipliers_raw = getattr(state, "scenario_multipliers", None)
    if not isinstance(scenario_multipliers_raw, dict) or not scenario_multipliers_raw:
        scenario_multipliers_raw = _default_scenario_multipliers()

    sm: Dict[str, float] = {}
    for name, mult in scenario_multipliers_raw.items():
        m = _safe_float(mult, 1.0)
        if m <= 0.0:
            continue
        sm[str(name)] = m
    if "base" not in sm:
        sm["base"] = 1.0

    sgm_raw = getattr(state, "scenario_goal_multipliers", None)
    scenario_goal_multipliers: Dict[str, Dict[str, float]] = {}

    if isinstance(sgm_raw, dict) and sgm_raw:
        for scenario_name, gmap in sgm_raw.items():
            if not isinstance(gmap, dict) or not gmap:
                continue
            scenario_goal_multipliers[str(scenario_name)] = {}
            for g in valid_goals:
                v = _safe_float(gmap.get(g, 1.0), 1.0) if g in gmap else 1.0
                if v <= 0.0:
                    v = 1.0
                scenario_goal_multipliers[str(scenario_name)][g] = float(v)
    else:
        scenario_goal_multipliers = _default_scenario_goal_multipliers(valid_goals)

    if "base" not in scenario_goal_multipliers:
        scenario_goal_multipliers["base"] = {g: 1.0 for g in valid_goals}
    for g in valid_goals:
        scenario_goal_multipliers["base"].setdefault(g, 1.0)

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

    # Feasibility is checked against the *binding* floor (the larger of the two).
    binding_floor = max(sum_min_platform, sum_min_goal)
    if binding_floor > total_budget + 1e-9:
        raise Module5ValidationError(
            f"Infeasible policy: binding minimum spend {binding_floor:.2f} exceeds total "
            f"budget {total_budget:.2f}."
        )

    return min_spend_per_platform, min_budget_per_goal, sm, scenario_goal_multipliers


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
        raise Module5ValidationError("Module 5 cannot run, valid_goals list is empty.")
    if state.total_budget is None or float(state.total_budget) <= 1:
        raise Module5ValidationError("Module 5 cannot run, total_budget is missing or invalid.")

    system_goal_weights = _build_system_goal_weights(state)
    platform_goal_weights = _build_platform_goal_weights_from_state(state)
    r_pg = _build_r_pg_from_state(state)

    active_platforms = list(r_pg.keys())
    goals_by_platform = {
        p: list(state.goals_by_platform.get(p, []) or list(state.valid_goals))
        for p in active_platforms
    }

    min_spend_per_platform, min_budget_per_goal, scenario_multipliers, scenario_goal_multipliers = _extract_policy_from_state(
        state=state,
        valid_goals=list(state.valid_goals),
        active_platforms=active_platforms,
        total_budget=float(state.total_budget),
    )

    module4_result = getattr(state, "module4_result", None)
    cpu_per_goal = (
        {p: {g: dict(kdict) for g, kdict in gdict.items()}
         for p, gdict in module4_result.cpu_per_goal.items()}
        if module4_result is not None
        else {}
    )

    return Module5LPInput(
        valid_goals=list(state.valid_goals),
        total_budget=float(state.total_budget),
        system_goal_weights=system_goal_weights,
        platform_goal_weights=platform_goal_weights,
        r_pg=r_pg,
        goals_by_platform=goals_by_platform,
        min_spend_per_platform=min_spend_per_platform,
        min_budget_per_goal=min_budget_per_goal,
        scenario_multipliers=scenario_multipliers,
        scenario_goal_multipliers=scenario_goal_multipliers,
        cpu_per_goal=cpu_per_goal,
    )


def _solve_single_lp(
    *,
    valid_goals: List[str],
    total_budget: float,
    system_goal_weights: Dict[str, float],
    platform_goal_weights: Dict[str, Dict[str, float]],
    r_pg: Dict[str, Dict[str, float]],
    goals_by_platform: Dict[str, List[str]],
    min_spend_per_platform: Dict[str, float],
    min_budget_per_goal: Dict[str, float],
    budget_cap: float,
    cpu_per_goal: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None,
) -> Module5LPResult:
    if not valid_goals:
        raise Module5ValidationError("Module 5 LP, valid_goals is empty.")
    if total_budget <= 1:
        raise Module5ValidationError("Module 5 LP, total_budget must be greater than 1.")
    if budget_cap <= 0:
        raise Module5ValidationError("Module 5 LP, budget_cap must be greater than zero.")
    if not system_goal_weights:
        raise Module5ValidationError("Module 5 LP, system_goal_weights is empty.")
    if not platform_goal_weights:
        raise Module5ValidationError("Module 5 LP, platform_goal_weights is empty.")
    if not r_pg:
        raise Module5ValidationError("Module 5 LP, r_pg is empty.")

    platforms = list(r_pg.keys())

    # Effective goals per platform: only those that Module 2 prioritised AND that have a
    # positive productivity from Module 3.
    eff_goals: Dict[str, List[str]] = {}
    for p in platforms:
        allowed = set(goals_by_platform.get(p, [])) or set(valid_goals)
        eff_goals[p] = [g for g in valid_goals if g in allowed and r_pg.get(p, {}).get(g, 0.0) > 0]

    combined_weight_pg: Dict[str, Dict[str, float]] = {}
    for p in platforms:
        combined_weight_pg[p] = {}
        platform_weights = platform_goal_weights.get(p, {})
        for g in valid_goals:
            w_g = _safe_float(system_goal_weights.get(g, 0.0), 0.0)
            W_pg = _safe_float(platform_weights.get(g, 0.0), 0.0)
            combined_weight_pg[p][g] = w_g * W_pg

    model = pulp.LpProblem("Budget_Allocation_Per_Platform_And_Goal", pulp.LpMaximize)

    # Per-bracket decision variables: x[p][g][b]
    x_brackets: Dict[str, Dict[str, List[pulp.LpVariable]]] = {}
    bracket_caps: List[float] = [frac * total_budget for frac, _yield in YIELD_BRACKETS]
    bracket_yields: List[float] = [y for _frac, y in YIELD_BRACKETS]

    for p in platforms:
        x_brackets[p] = {}
        for g in valid_goals:
            if g not in eff_goals[p]:
                # Force allocation to zero by capping each bracket at zero.
                x_brackets[p][g] = [
                    pulp.LpVariable(f"x_{p}_{g}_b{i}", lowBound=0.0, upBound=0.0, cat="Continuous")
                    for i in range(len(YIELD_BRACKETS))
                ]
                continue
            x_brackets[p][g] = [
                pulp.LpVariable(
                    f"x_{p}_{g}_b{i}",
                    lowBound=0.0,
                    upBound=bracket_caps[i],
                    cat="Continuous",
                )
                for i in range(len(YIELD_BRACKETS))
            ]

    # Objective: Σ combined_weight × r_pg × Σ_b (yield_b × x_b)
    model += pulp.lpSum(
        combined_weight_pg[p][g]
        * _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0)
        * bracket_yields[b]
        * x_brackets[p][g][b]
        for p in platforms
        for g in valid_goals
        for b in range(len(YIELD_BRACKETS))
    )

    # Total budget cap (scenario-scaled).
    model += pulp.lpSum(
        x_brackets[p][g][b]
        for p in platforms
        for g in valid_goals
        for b in range(len(YIELD_BRACKETS))
    ) <= budget_cap

    # Per-platform minimums.
    for p in platforms:
        min_p = _safe_float(min_spend_per_platform.get(p, 0.0), 0.0)
        if min_p > 0.0:
            model += pulp.lpSum(
                x_brackets[p][g][b]
                for g in valid_goals
                for b in range(len(YIELD_BRACKETS))
            ) >= min_p

    # Per-goal minimums.
    for g in valid_goals:
        min_g = _safe_float(min_budget_per_goal.get(g, 0.0), 0.0)
        if min_g > 0.0:
            model += pulp.lpSum(
                x_brackets[p][g][b]
                for p in platforms
                for b in range(len(YIELD_BRACKETS))
            ) >= min_g

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
            cell_total = 0.0
            cell_yield_sum = 0.0
            for b in range(len(YIELD_BRACKETS)):
                v = _safe_float(getattr(x_brackets[p][g][b], "varValue", 0.0), 0.0)
                if v < 0.0:
                    v = 0.0
                cell_total += v
                cell_yield_sum += v * bracket_yields[b]

            budget_per_platform_goal[p][g] = cell_total
            total_p += cell_total

            r_val = _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0)
            estimated_kpi_per_platform_goal[p][g] = r_val * cell_yield_sum

        budget_per_platform[p] = total_p

    total_budget_used = sum(
        budget_per_platform_goal[p][g] for p in platforms for g in valid_goals
    )

    objective_value_raw = _safe_float(pulp.value(model.objective), 0.0)
    objective_value = objective_value_raw * float(OBJECTIVE_SCALE)

    return Module5LPResult(
        budget_per_platform_goal=budget_per_platform_goal,
        budget_per_platform=budget_per_platform,
        total_budget_used=total_budget_used,
        objective_value=objective_value,
        r_pg=r_pg,
        combined_weight_pg=combined_weight_pg,
        estimated_kpi_per_platform_goal=estimated_kpi_per_platform_goal,
        objective_value_raw=objective_value_raw,
        effective_budget_cap=budget_cap,
        cpu_per_goal=cpu_per_goal or {},
    )


def run_module5_lp(input_data: Module5LPInput) -> Module5LPResult:
    return _solve_single_lp(
        valid_goals=input_data.valid_goals,
        total_budget=input_data.total_budget,
        system_goal_weights=input_data.system_goal_weights,
        platform_goal_weights=input_data.platform_goal_weights,
        r_pg=input_data.r_pg,
        goals_by_platform=input_data.goals_by_platform,
        min_spend_per_platform=input_data.min_spend_per_platform,
        min_budget_per_goal=input_data.min_budget_per_goal,
        budget_cap=input_data.total_budget,
        cpu_per_goal=input_data.cpu_per_goal,
    )


def run_module5_lp_scenarios(input_data: Module5LPInput) -> Module5ScenarioBundle:
    if not input_data.scenario_multipliers:
        raise Module5ValidationError("scenario_multipliers is empty.")

    results: Dict[str, Module5LPResult] = {}

    base_goal_map = (
        dict(input_data.scenario_goal_multipliers.get("base", {}))
        if input_data.scenario_goal_multipliers
        else {}
    )
    for g in input_data.valid_goals:
        base_goal_map.setdefault(g, 1.0)

    for scenario_name, scalar_multiplier in input_data.scenario_multipliers.items():
        scalar_m = _safe_float(scalar_multiplier, 1.0)
        if scalar_m <= 0.0:
            continue

        goal_multipliers = input_data.scenario_goal_multipliers.get(scenario_name, {})
        if not isinstance(goal_multipliers, dict) or not goal_multipliers:
            goal_multipliers = base_goal_map

        # Goal multipliers shift r_pg per-goal (genuine relative re-ranking of cells).
        adjusted_r_pg: Dict[str, Dict[str, float]] = {}
        for p, gdict in input_data.r_pg.items():
            adjusted_r_pg[p] = {}
            for g, r in gdict.items():
                val = _safe_float(r, 0.0)
                gm = _safe_float(goal_multipliers.get(g, 1.0), 1.0)
                if gm <= 0.0:
                    gm = 1.0
                adjusted_r_pg[p][g] = max(0.0, val * gm)

        # The scalar multiplier moves to the constraint side: scenarios change capacity,
        # not just the objective. This is what makes scenarios meaningfully differ from
        # one another (positive scaling of a linear objective is argmax-invariant).
        budget_cap = input_data.total_budget * scalar_m

        # Re-check feasibility against the binding floor for this scenario.
        sum_min_p = sum(input_data.min_spend_per_platform.values())
        sum_min_g = sum(input_data.min_budget_per_goal.values())
        binding_floor = max(sum_min_p, sum_min_g)
        if binding_floor > budget_cap + 1e-9:
            # Skip this scenario rather than fail outright — caller still sees others.
            continue

        results[scenario_name] = _solve_single_lp(
            valid_goals=input_data.valid_goals,
            total_budget=input_data.total_budget,
            system_goal_weights=input_data.system_goal_weights,
            platform_goal_weights=input_data.platform_goal_weights,
            r_pg=adjusted_r_pg,
            goals_by_platform=input_data.goals_by_platform,
            min_spend_per_platform=input_data.min_spend_per_platform,
            min_budget_per_goal=input_data.min_budget_per_goal,
            budget_cap=budget_cap,
            cpu_per_goal=input_data.cpu_per_goal,
        )

    if not results:
        raise Module5ValidationError("No scenario results were produced.")

    return Module5ScenarioBundle(
        results_by_scenario=results,
        scenario_multipliers=dict(input_data.scenario_multipliers),
        scenario_goal_multipliers=dict(input_data.scenario_goal_multipliers),
    )


def run_module5(state: WizardState) -> WizardState:
    if state.module5_finalised:
        raise FlowStateError("Module 5 has already been finalised. Reset the wizard to change it.")

    lp_input = build_module5_input_from_state(state)
    bundle = run_module5_lp_scenarios(lp_input)
    base_result = bundle.get_base()

    state.complete_module5_and_advance(
        module5_result=base_result,
        module5_scenario_bundle=bundle,
        module5_results_by_scenario=bundle.results_by_scenario,
    )

    return state
