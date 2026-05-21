from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pulp

from core.wizard_state import WizardState, FlowStateError
from core.kpi_config import KPI_CONFIG, KIND_COUNT, KIND_RATE


_LOG = logging.getLogger(__name__)


class Module5ValidationError(Exception):
    pass


OBJECTIVE_SCALE = 1000.0

# Industry-typical monthly spend needed for a platform's auction / learning
# algorithm to leave the learning phase and produce stable performance.  These
# are *guidelines*, not hard constraints — Module 5 surfaces a warning when
# an allocation falls below the threshold so the user can choose to raise
# their floor in Module 2, accept the risk, or drop the platform.
#
# Sources: published Meta / LinkedIn / Google guidance for monthly minimums
# at which their delivery algorithms have enough signal to optimise.
PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH: Dict[str, float] = {
    "fb": 1000.0,
    "ig": 1000.0,
    "li": 2000.0,  # LinkedIn's "exit learning phase" threshold is the highest
    "yt": 1500.0,
}

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
    # The user's declared total budget.  Per-scenario LP caps are derived as
    # (total_budget × scenario_scalar) × (1 - test_and_learn_pct), so the
    # invariant lp_used + reserve ≤ total_budget × scenario_scalar always holds.
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
    # Fraction of every scenario's budget held back from the LP as a
    # test-and-learn reserve.  The LP cap shrinks proportionally; the reserve
    # scales with the scenario so the cross-scenario story is internally
    # consistent ("X% of every plan's budget goes to testing").
    test_and_learn_pct: float = 0.0
    # Per-platform effective spend thresholds (already scaled to campaign
    # duration).  Allocations below these are flagged as warnings on the
    # result; the LP is not constrained to respect them.
    effective_minimum_per_platform: Dict[str, float] = field(default_factory=dict)


@dataclass
class Module5BindingConstraint:
    """A constraint the LP hit (slack ≈ 0).  These are the constraints that
    are *actually shaping* the allocation — releasing one of them would let
    the optimiser do better.
    """
    name: str
    kind: str           # "budget_cap" | "min_platform" | "min_goal"
    target: Optional[str] = None  # platform code or goal code, when applicable
    rhs: float = 0.0    # the limit the LP hit
    shadow_price: float = 0.0  # marginal objective value per unit relaxation


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
    # £ amount held back from the LP as a test-and-learn reserve.  Reported
    # alongside the allocation so the user sees: total = optimised + reserve.
    test_and_learn_reserve: float = 0.0
    # ── Solver diagnostics ──────────────────────────────────────────────────
    # Which constraints the LP actually hit (slack ≤ tolerance).  This is the
    # auditable "why did the optimiser stop here?" answer.
    binding_constraints: List[Module5BindingConstraint] = field(default_factory=list)
    # Shadow prices on every named constraint (binding or not), keyed by name.
    # Useful for sensitivity analysis: "if I raised the LinkedIn floor by £1,
    # the objective would change by this much."
    shadow_prices: Dict[str, float] = field(default_factory=dict)
    # Groups of (platform, goal) cells whose normalised productivities were
    # within the degeneracy tolerance (Fix C).  When this list is non-empty,
    # the allocation between those cells was set by proportional
    # redistribution, not by the LP — the user should know it's a tie.
    near_degenerate_groups: List[Dict[str, Any]] = field(default_factory=list)
    solver_status: str = "Optimal"
    # Warnings for platforms whose allocation falls below the industry-typical
    # effective spend (PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH, scaled by the
    # campaign duration).  Below this threshold, the platform's auction /
    # learning algorithm typically has too little signal to optimise; the
    # campaign delivers but never tunes.  Informational only — the LP isn't
    # forced to respect these floors unless the user puts them in Module 2.
    effective_minimum_warnings: List[str] = field(default_factory=list)


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

    # ── Fix A: scale rate-only cells to count scale ───────────────────────────
    # A raw engagement-rate value (0.045) and a count productivity (3 eng/£) are
    # on different scales and cannot be compared directly.  When a (p,g) cell
    # has only rate KPIs while other platforms report a count KPI for the same
    # goal, multiply the rate-only values by the cross-platform count mean so
    # they compete on the same numerical footing inside the LP.
    for g in state.valid_goals:
        count_productivities: List[float] = []
        rate_only_ps: List[str] = []
        for p in list(r_pg.keys()):
            if g not in r_pg[p] or r_pg[p][g] <= 0.0:
                continue
            kpi_vars = state.kpi_ratios.get(p, {}).get(g, {})
            has_count = any(
                kind_lookup.get((p, var), KIND_COUNT) == KIND_COUNT
                for var in kpi_vars
            )
            if has_count:
                count_productivities.append(r_pg[p][g])
            else:
                rate_only_ps.append(p)
        if count_productivities and rate_only_ps:
            count_mean = sum(count_productivities) / len(count_productivities)
            for p in rate_only_ps:
                r_pg[p][g] *= count_mean

    # ── Fix B: normalise productivities per goal ──────────────────────────────
    # Without normalisation, "100 reach/£" and "0.016 leads/£" live on a
    # 6,000× scale gap; the LP then treats reach as far more valuable than
    # leads regardless of the goal weights, making multi-objective campaigns
    # uncontrollable.  After normalisation each goal's total sums to 1.0 across
    # platforms, so the goal weights set by Module 2 become the actual control
    # knob for cross-objective emphasis.
    for g in state.valid_goals:
        total = sum(r_pg.get(p, {}).get(g, 0.0) for p in r_pg)
        if total > 0.0:
            for p in r_pg:
                if g in r_pg[p] and r_pg[p][g] > 0.0:
                    r_pg[p][g] /= total

    return r_pg


def _representative_productivity_per_goal(state: WizardState) -> Dict[str, float]:
    """Mean raw productivity per goal across active platforms (pre-normalisation).

    For count KPIs the unit is count/£; for rate KPIs it is the rate value itself.
    Used to convert user-provided £-value-per-unit into a goal weight via
    weight[g] = value_per_unit[g] × representative_productivity[g] (= expected ROAS).
    """
    kind_lookup: Dict[Tuple[str, str], str] = {
        (row["platform"], row["var"]): row.get("kind", KIND_COUNT)
        for row in KPI_CONFIG
    }
    by_goal: Dict[str, List[float]] = {g: [] for g in state.valid_goals}
    for p in (getattr(state, "active_platforms", []) or []):
        for g in state.valid_goals:
            ratios = state.kpi_ratios.get(p, {}).get(g, {})
            if not ratios:
                continue
            count_vals: List[float] = []
            rate_vals: List[float] = []
            for var, val in ratios.items():
                kind = kind_lookup.get((p, var), KIND_COUNT)
                v = _safe_float(val, 0.0)
                if v <= 0.0:
                    continue
                if kind == KIND_RATE:
                    rate_vals.append(v)
                else:
                    count_vals.append(v)
            if count_vals:
                by_goal[g].append(sum(count_vals) / len(count_vals))
            elif rate_vals:
                by_goal[g].append(sum(rate_vals) / len(rate_vals))
    return {g: (sum(v) / len(v) if v else 0.0) for g, v in by_goal.items()}


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

    # 2a) Prefer user-provided economic values when available.
    # weight[g] = value_per_unit[g] × representative_productivity[g]
    # The product expresses expected £-return per £ invested in goal g —
    # i.e. a relative ROAS — which is what a CMO/strategist actually trades off.
    goal_values = getattr(state, "goal_value_per_unit", None) or {}
    if goal_values and any(_safe_float(v, 0.0) > 0 for v in goal_values.values()):
        rep_prod = _representative_productivity_per_goal(state)
        derived: Dict[str, float] = {}
        for g in state.valid_goals:
            val = max(0.0, _safe_float(goal_values.get(g, 0.0), 0.0))
            prod = max(0.0, _safe_float(rep_prod.get(g, 0.0), 0.0))
            if val > 0.0 and prod > 0.0:
                derived[g] = val * prod
        total = sum(derived.values())
        if total > 0.0:
            # When economic weights are present, the rank-based fallback at 2b
            # is deliberately skipped: the two value frameworks (utility vs.
            # ordinal preference) shouldn't compose.  Log once so operators
            # can audit the path the optimiser took.
            if getattr(state, "priority_rank", None):
                _LOG.info(
                    "Using economic goal weights from goal_value_per_unit; "
                    "rank-based weights from priority_rank are not consulted in this run. "
                    "derived_weights=%s",
                    {g: round(w / total, 4) for g, w in derived.items()},
                )
            return {g: w / total for g, w in derived.items()}

    # 2b) derive from Module 2 platform priorities: each platform contributes
    #    rank-1 -> 2, rank-2 -> 1 to its respective goal. This makes the system-level
    #    weight a frequency-weighted preference instead of inert uniformity.
    #    Used only when goal_value_per_unit is absent; surfaces as the
    #    "no per-goal economic values" caveat in Module 7.
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
        _LOG.info(
            "Using rank-based goal weights (no goal_value_per_unit provided). "
            "Supply economic values in Module 1 for utility-grounded weighting. "
            "derived_weights=%s",
            {g: round(w / total, 4) for g, w in derived.items()},
        )
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

    # Validate the test-and-learn carve-out strictly: bad state means a bug
    # upstream, and silently clamping would produce a plan the user didn't ask for.
    tl_pct = _safe_float(getattr(state, "test_and_learn_pct", 0.0), 0.0)
    if tl_pct < 0.0 or tl_pct >= 0.5:
        raise Module5ValidationError(
            f"Invalid test_and_learn_pct={tl_pct} in state; must be in [0.0, 0.5). "
            f"This is a Module 1 input — re-finalise Module 1 with a valid value."
        )
    base_lp_cap = float(state.total_budget) * (1.0 - tl_pct)
    if base_lp_cap <= 1.0:
        raise Module5ValidationError(
            f"LP cap after test-and-learn carve-out is too small ({base_lp_cap:.2f}). "
            f"Reduce test_and_learn_pct or raise total_budget."
        )

    system_goal_weights = _build_system_goal_weights(state)
    platform_goal_weights = _build_platform_goal_weights_from_state(state)
    r_pg = _build_r_pg_from_state(state)

    # Apply seasonality multipliers to expected productivities BEFORE the LP
    # runs.  Scenario goal multipliers compose multiplicatively on top of
    # this — seasonality is a calendar-driven prior, scenarios are uncertainty.
    seasonality = getattr(state, "seasonality_index", None) or {}
    if seasonality:
        for p in list(r_pg.keys()):
            for g in list(r_pg[p].keys()):
                mult = _safe_float(seasonality.get(g, 1.0), 1.0)
                if mult <= 0.0:
                    mult = 1.0
                r_pg[p][g] *= mult
        _LOG.info("Applied seasonality_index=%s to r_pg before LP.", seasonality)

    active_platforms = list(r_pg.keys())
    goals_by_platform = {
        p: list(state.goals_by_platform.get(p, []) or list(state.valid_goals))
        for p in active_platforms
    }

    # Feasibility check uses the base LP cap (post-carve-out, scalar=1.0).
    # Per-scenario re-checks in run_module5_lp_scenarios handle the conservative
    # case where the smaller cap may not clear the floors.
    min_spend_per_platform, min_budget_per_goal, scenario_multipliers, scenario_goal_multipliers = _extract_policy_from_state(
        state=state,
        valid_goals=list(state.valid_goals),
        active_platforms=active_platforms,
        total_budget=base_lp_cap,
    )

    module4_result = getattr(state, "module4_result", None)
    cpu_per_goal = (
        {p: {g: dict(kdict) for g, kdict in gdict.items()}
         for p, gdict in module4_result.cpu_per_goal.items()}
        if module4_result is not None
        else {}
    )

    # Compute effective-minimum thresholds, scaled to campaign duration.
    # A 60-day campaign should support twice the monthly threshold; a 15-day
    # campaign half of it.  Defaults to 30-day equivalence when duration is
    # unknown.
    campaign_days = _safe_float(getattr(state, "campaign_duration_days", None) or 30.0, 30.0)
    if campaign_days <= 0.0:
        campaign_days = 30.0
    scale = campaign_days / 30.0
    effective_minimums: Dict[str, float] = {}
    for p in active_platforms:
        threshold = PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH.get(p, 0.0) * scale
        if threshold > 0.0:
            effective_minimums[p] = threshold

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
        test_and_learn_pct=tl_pct,
        effective_minimum_per_platform=effective_minimums,
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
    effective_minimum_per_platform: Optional[Dict[str, float]] = None,
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

    # Total budget cap (scenario-scaled).  Named so we can read its shadow
    # price after solve.
    model += (
        pulp.lpSum(
            x_brackets[p][g][b]
            for p in platforms
            for g in valid_goals
            for b in range(len(YIELD_BRACKETS))
        )
        <= budget_cap,
        "budget_cap",
    )

    # Per-platform minimums.
    platform_floor_meta: Dict[str, Tuple[str, float]] = {}
    for p in platforms:
        min_p = _safe_float(min_spend_per_platform.get(p, 0.0), 0.0)
        if min_p > 0.0:
            name = f"min_platform_{p}"
            model += (
                pulp.lpSum(
                    x_brackets[p][g][b]
                    for g in valid_goals
                    for b in range(len(YIELD_BRACKETS))
                )
                >= min_p,
                name,
            )
            platform_floor_meta[name] = (p, min_p)

    # Per-goal minimums.
    goal_floor_meta: Dict[str, Tuple[str, float]] = {}
    for g in valid_goals:
        min_g = _safe_float(min_budget_per_goal.get(g, 0.0), 0.0)
        if min_g > 0.0:
            name = f"min_goal_{g}"
            model += (
                pulp.lpSum(
                    x_brackets[p][g][b]
                    for p in platforms
                    for b in range(len(YIELD_BRACKETS))
                )
                >= min_g,
                name,
            )
            goal_floor_meta[name] = (g, min_g)

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    status = pulp.LpStatus.get(model.status, "Unknown")
    if status not in ("Optimal", "Feasible"):
        _LOG.error(
            "LP solve failed: status=%s budget_cap=%.2f sum_min_platform=%.2f sum_min_goal=%.2f",
            status, budget_cap,
            sum(min_spend_per_platform.values()),
            sum(min_budget_per_goal.values()),
        )
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

    # ── Fix C: proportional redistribution for near-equal productivity cells ──
    # LP problems with identical (or near-identical) objective coefficients are
    # degenerate: any split across the tied cells is optimal, and the solver
    # picks an arbitrary corner (e.g. 60/40 instead of 50/50).  When two or more
    # platforms have the same goal and their normalised productivities are within
    # 2 % of each other, redistribute the total goal budget proportionally so the
    # allocation reflects relative efficiency rather than solver tie-breaking.
    near_degenerate_groups: List[Dict[str, Any]] = []
    for g in valid_goals:
        active = {
            p: _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0)
            for p in platforms
            if _safe_float(r_pg.get(p, {}).get(g, 0.0), 0.0) > 0.0
        }
        if len(active) < 2:
            continue
        max_r = max(active.values())
        min_r = min(active.values())
        if max_r <= 0.0 or (max_r - min_r) / max_r > 0.02:
            continue  # clear winner — keep LP allocation as-is
        total_g = sum(budget_per_platform_goal[p][g] for p in active)
        total_r = sum(active.values())
        if total_r > 0.0 and total_g > 0.0:
            for p in active:
                budget_per_platform_goal[p][g] = total_g * (active[p] / total_r)
            near_degenerate_groups.append({
                "goal": g,
                "platforms": list(active.keys()),
                "max_relative_gap": (max_r - min_r) / max_r,
            })
            _LOG.info(
                "Near-degenerate cell group for goal=%s across platforms=%s "
                "(max_relative_gap=%.4f); redistributed proportionally instead of "
                "taking the LP's arbitrary corner.",
                g, list(active.keys()), (max_r - min_r) / max_r,
            )

    # Recompute platform totals after any redistribution.
    for p in platforms:
        budget_per_platform[p] = sum(budget_per_platform_goal[p][g] for g in valid_goals)

    total_budget_used = sum(
        budget_per_platform_goal[p][g] for p in platforms for g in valid_goals
    )

    objective_value_raw = _safe_float(pulp.value(model.objective), 0.0)
    objective_value = objective_value_raw * float(OBJECTIVE_SCALE)

    # ── Solver diagnostics ─────────────────────────────────────────────────
    # Walk the named constraints, capture slack + shadow prices, and surface
    # which ones the LP actually hit.  Tolerance is relative to the RHS so a
    # floor of £10,000 and a floor of £100 use a sensible threshold each.
    binding: List[Module5BindingConstraint] = []
    shadow_prices: Dict[str, float] = {}
    for cons_name, cons in model.constraints.items():
        try:
            pi = _safe_float(getattr(cons, "pi", 0.0) or 0.0, 0.0)
        except Exception:
            pi = 0.0
        shadow_prices[cons_name] = pi

        rhs = -_safe_float(getattr(cons, "constant", 0.0), 0.0)  # PuLP stores -RHS
        # slack = |lhs - rhs|; CBC sometimes reports tiny non-zero slacks
        slack = abs(_safe_float(getattr(cons, "slack", 0.0), 0.0))
        tol = max(1e-4, 1e-3 * max(1.0, abs(rhs)))
        if slack <= tol:
            kind = "budget_cap"
            target: Optional[str] = None
            if cons_name in platform_floor_meta:
                kind = "min_platform"
                target = platform_floor_meta[cons_name][0]
                rhs = platform_floor_meta[cons_name][1]
            elif cons_name in goal_floor_meta:
                kind = "min_goal"
                target = goal_floor_meta[cons_name][0]
                rhs = goal_floor_meta[cons_name][1]
            elif cons_name == "budget_cap":
                rhs = budget_cap
            binding.append(Module5BindingConstraint(
                name=cons_name, kind=kind, target=target, rhs=rhs, shadow_price=pi,
            ))

    # ── Effective minimum spend warnings ───────────────────────────────────
    # Platforms whose allocation falls below the industry-typical effective
    # threshold typically can't exit the algorithm's learning phase; the
    # campaign delivers impressions but doesn't optimise.  Surfaced as
    # warnings (not enforced) so the user can decide whether to lift the
    # floor in Module 2, drop the platform, or accept the risk.
    effective_warnings: List[str] = []
    for p, threshold in (effective_minimum_per_platform or {}).items():
        if threshold <= 0.0:
            continue
        allocated = _safe_float(budget_per_platform.get(p, 0.0), 0.0)
        # Only warn when the platform got *something* but below the threshold —
        # a zero allocation means the LP chose to skip it entirely, which is
        # a separate, intentional outcome.
        if 0.0 < allocated < threshold:
            shortfall = threshold - allocated
            effective_warnings.append(
                f"{p}: allocated {allocated:.0f} but the industry-typical effective "
                f"minimum is {threshold:.0f} (short by {shortfall:.0f}). "
                f"Below this threshold the platform may not exit its learning phase."
            )
            _LOG.warning(
                "Platform %s allocated %.2f below effective minimum %.2f",
                p, allocated, threshold,
            )

    _LOG.info(
        "LP solved: status=%s objective_raw=%.4f budget_used=%.2f budget_cap=%.2f "
        "binding=%d degenerate_groups=%d effective_warnings=%d",
        status, objective_value_raw, total_budget_used, budget_cap,
        len(binding), len(near_degenerate_groups), len(effective_warnings),
    )

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
        binding_constraints=binding,
        shadow_prices=shadow_prices,
        near_degenerate_groups=near_degenerate_groups,
        solver_status=status,
        effective_minimum_warnings=effective_warnings,
    )


def run_module5_lp(input_data: Module5LPInput) -> Module5LPResult:
    tl_pct = _safe_float(input_data.test_and_learn_pct, 0.0)
    if tl_pct < 0.0 or tl_pct >= 0.5:
        raise Module5ValidationError(
            f"Invalid test_and_learn_pct={tl_pct}; must be in [0.0, 0.5)."
        )
    lp_cap = input_data.total_budget * (1.0 - tl_pct)
    result = _solve_single_lp(
        valid_goals=input_data.valid_goals,
        total_budget=lp_cap,
        system_goal_weights=input_data.system_goal_weights,
        platform_goal_weights=input_data.platform_goal_weights,
        r_pg=input_data.r_pg,
        goals_by_platform=input_data.goals_by_platform,
        min_spend_per_platform=input_data.min_spend_per_platform,
        min_budget_per_goal=input_data.min_budget_per_goal,
        budget_cap=lp_cap,
        cpu_per_goal=input_data.cpu_per_goal,
        effective_minimum_per_platform=input_data.effective_minimum_per_platform,
    )
    result.test_and_learn_reserve = input_data.total_budget - lp_cap
    return result


def run_module5_lp_scenarios(input_data: Module5LPInput) -> Module5ScenarioBundle:
    if not input_data.scenario_multipliers:
        raise Module5ValidationError("scenario_multipliers is empty.")

    tl_pct = _safe_float(input_data.test_and_learn_pct, 0.0)
    if tl_pct < 0.0 or tl_pct >= 0.5:
        raise Module5ValidationError(
            f"Invalid test_and_learn_pct={tl_pct}; must be in [0.0, 0.5)."
        )

    results: Dict[str, Module5LPResult] = {}

    base_goal_map = (
        dict(input_data.scenario_goal_multipliers.get("base", {}))
        if input_data.scenario_goal_multipliers
        else {}
    )
    for g in input_data.valid_goals:
        base_goal_map.setdefault(g, 1.0)

    # Bracket caps for diminishing returns are anchored to the base LP capacity
    # (post-carve-out, scalar=1.0).  This stays constant across scenarios so
    # diminishing-returns kick in at the same £ thresholds regardless of which
    # scenario the user is looking at — cleaner cross-scenario comparison.
    base_lp_cap = input_data.total_budget * (1.0 - tl_pct)

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

        # Apply the carve-out per scenario so the invariant holds in every cell:
        #   scenario_total = declared_total × scalar
        #   budget_cap     = scenario_total × (1 - tl_pct)
        #   reserve        = scenario_total × tl_pct
        # which guarantees lp_used + reserve ≤ scenario_total for every scenario,
        # including optimistic.  Without this, optimistic was spending the full
        # scenario uplift PLUS the base reserve, exceeding the user's declared total.
        scenario_total = input_data.total_budget * scalar_m
        budget_cap = scenario_total * (1.0 - tl_pct)
        scenario_reserve = scenario_total - budget_cap

        # Re-check feasibility against the binding floor for this scenario.
        sum_min_p = sum(input_data.min_spend_per_platform.values())
        sum_min_g = sum(input_data.min_budget_per_goal.values())
        binding_floor = max(sum_min_p, sum_min_g)
        if binding_floor > budget_cap + 1e-9:
            # Skip this scenario rather than fail outright — caller still sees others.
            continue

        result = _solve_single_lp(
            valid_goals=input_data.valid_goals,
            total_budget=base_lp_cap,
            system_goal_weights=input_data.system_goal_weights,
            platform_goal_weights=input_data.platform_goal_weights,
            r_pg=adjusted_r_pg,
            goals_by_platform=input_data.goals_by_platform,
            min_spend_per_platform=input_data.min_spend_per_platform,
            min_budget_per_goal=input_data.min_budget_per_goal,
            budget_cap=budget_cap,
            cpu_per_goal=input_data.cpu_per_goal,
            effective_minimum_per_platform=input_data.effective_minimum_per_platform,
        )
        result.test_and_learn_reserve = scenario_reserve
        results[scenario_name] = result

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


# ────────────────────────────────────────────────────────────────────────────
# Monte Carlo robustness analysis
# ────────────────────────────────────────────────────────────────────────────
# A reviewer-driven addition: the LP gives a single deterministic allocation,
# but a wrong productivity estimate can dominate the result without the
# system flagging the underlying uncertainty.  This block re-solves the LP
# many times with the productivities perturbed by their observed (or
# window-scaled) coefficient of variation, then reports the *distribution*
# of allocations.  Cells whose allocation has a wide spread are explicitly
# called out as unstable — that's the honest answer to "how robust are the
# assumptions?"

# Default cap on Monte Carlo trials.  200 keeps the runtime under ~5 s on
# typical small problems while giving stable p5/p95 estimates.
DEFAULT_MC_TRIALS = 200

# CV above which a per-platform total is treated as "unstable" — i.e. the
# rank ordering of platforms is sensitive to plausible productivity noise.
# 0.20 means "the platform's share moves by more than 20% of its mean
# under realistic data perturbation."
DEFAULT_INSTABILITY_CV = 0.20


@dataclass
class Module5MCCellSummary:
    platform: str
    goal: str               # empty string for platform totals
    mean: float
    std: float
    cv: float               # std / mean (0 when mean ≈ 0)
    p5: float
    p50: float
    p95: float


@dataclass
class Module5MonteCarloResult:
    n_trials: int
    seed: Optional[int]
    per_cell: List[Module5MCCellSummary] = field(default_factory=list)
    per_platform: List[Module5MCCellSummary] = field(default_factory=list)
    # Platforms whose share is sensitive to plausible productivity perturbation.
    # Populated when CV > instability_threshold.  These are the platforms whose
    # rank in the plan should be treated with caution.
    unstable_platforms: List[str] = field(default_factory=list)
    instability_threshold: float = DEFAULT_INSTABILITY_CV
    # Per-cell sigma used for sampling (the lognormal scale parameter).
    # Surfaced so the user can see *which* assumptions had the most noise.
    cell_sigma: Dict[str, Dict[str, float]] = field(default_factory=dict)


def _per_cell_sigma(state: WizardState) -> Dict[str, Dict[str, float]]:
    """Best estimate of per-(platform, goal) productivity noise.

    For each cell, prefer the coefficient of variation computed from
    module3_data['kpi_observations'] when ≥3 observations exist.  Else
    scale Module 6's DEFAULT_UNCERTAINTY_BAND by sqrt(30/historical_days).
    Final fallback: the flat default.
    """
    # Late import to avoid module-load cycle (module6 imports module5).
    from modules.module6 import (
        _coefficient_of_variation,
        DEFAULT_UNCERTAINTY_BAND,
    )

    module3_data = getattr(state, "module3_data", {}) or {}
    out: Dict[str, Dict[str, float]] = {}

    for p in (getattr(state, "active_platforms", []) or []):
        pdata = module3_data.get(p, {}) or {}
        hist_days = pdata.get("historical_days")
        observations_map = pdata.get("kpi_observations", {}) or {}
        kpi_ratios = (getattr(state, "kpi_ratios", {}) or {}).get(p, {}) or {}

        out[p] = {}
        for g in (getattr(state, "valid_goals", []) or []):
            # Aggregate CVs across all KPI vars in this cell — typically just
            # one or two count KPIs per (platform, goal).
            cell_cvs: List[float] = []
            for var in (kpi_ratios.get(g, {}) or {}).keys():
                cv = _coefficient_of_variation(observations_map.get(var) or [])
                if cv is not None:
                    cell_cvs.append(cv)

            if cell_cvs:
                sigma = sum(cell_cvs) / len(cell_cvs)
            elif hist_days and hist_days > 0:
                days = max(7.0, float(hist_days))
                sigma = DEFAULT_UNCERTAINTY_BAND * math.sqrt(30.0 / days)
            else:
                sigma = DEFAULT_UNCERTAINTY_BAND

            # Clamp: extreme values usually indicate bad data, and very large
            # sigmas turn the LP into white noise (every solve is different).
            sigma = max(0.05, min(1.0, sigma))
            out[p][g] = sigma

    return out


def _percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 100]).  Avoids the numpy dep."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = (q / 100.0) * (len(s) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _summarise(values: List[float], platform: str, goal: str) -> Module5MCCellSummary:
    n = len(values)
    if n == 0:
        return Module5MCCellSummary(platform=platform, goal=goal,
                                    mean=0.0, std=0.0, cv=0.0, p5=0.0, p50=0.0, p95=0.0)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / max(1, n - 1)
    std = math.sqrt(var)
    cv = (std / mean) if mean > 1e-9 else 0.0
    return Module5MCCellSummary(
        platform=platform, goal=goal,
        mean=mean, std=std, cv=cv,
        p5=_percentile(values, 5),
        p50=_percentile(values, 50),
        p95=_percentile(values, 95),
    )


def run_module5_montecarlo(
    state: WizardState,
    n_trials: int = DEFAULT_MC_TRIALS,
    seed: Optional[int] = None,
    instability_cv_threshold: float = DEFAULT_INSTABILITY_CV,
) -> Module5MonteCarloResult:
    """Re-solve the base-scenario LP with productivities perturbed by their
    observed noise, then report the resulting distribution over allocations.

    Each trial multiplies every r_pg[p][g] by a mean-preserving lognormal
    shock with scale sigma = the cell's coefficient of variation (from
    Module 3 observations, the historical-window prior, or the default).
    Productivities are re-normalised per goal after the shock so the LP's
    cross-platform comparison stays calibrated.

    Returns per-cell and per-platform mean/std/p5/p50/p95 of the allocation
    in £, plus the list of platforms whose share is sensitive (CV >
    instability_cv_threshold).

    Cost: n_trials LP solves.  At n=200 this is typically 1–5 s.
    """
    if not state.module4_finalised:
        raise FlowStateError("Monte Carlo analysis requires Module 4 to be finalised.")
    if n_trials < 10:
        raise Module5ValidationError(
            f"n_trials={n_trials} is too small to estimate percentiles. Use ≥10."
        )
    if n_trials > 1000:
        raise Module5ValidationError(
            f"n_trials={n_trials} > 1000 — refuse to run; that's >25 s of LP solves. "
            f"Reduce n_trials or implement a proper parallel runner first."
        )

    lp_input = build_module5_input_from_state(state)
    cell_sigma = _per_cell_sigma(state)
    rng = random.Random(seed)

    tl_pct = _safe_float(lp_input.test_and_learn_pct, 0.0)
    lp_cap = lp_input.total_budget * (1.0 - tl_pct)

    # Per-cell accumulator: platform → goal → list[£ allocated across trials]
    cell_alloc: Dict[str, Dict[str, List[float]]] = {
        p: {g: [] for g in lp_input.valid_goals} for p in lp_input.r_pg.keys()
    }
    platform_alloc: Dict[str, List[float]] = {p: [] for p in lp_input.r_pg.keys()}

    failed_trials = 0
    for _ in range(n_trials):
        # Perturb r_pg with mean-preserving lognormal shocks.
        perturbed: Dict[str, Dict[str, float]] = {}
        for p, gdict in lp_input.r_pg.items():
            perturbed[p] = {}
            for g, r in gdict.items():
                # Cell sigma is populated for every (p, g) that has a
                # ratio in Module 3.  0.30 fallback only fires if r_pg has
                # an entry the sigma table doesn't — defensive, not load-bearing.
                sigma = cell_sigma.get(p, {}).get(g, 0.30)
                # E[exp(sigma·Z - sigma²/2)] = 1, so the multiplier is unbiased.
                z = rng.gauss(0.0, 1.0)
                shock = math.exp(sigma * z - 0.5 * sigma * sigma)
                perturbed[p][g] = max(0.0, _safe_float(r, 0.0) * shock)

        # Re-normalise per goal so the cross-platform comparison stays at
        # the same overall scale the LP was calibrated for.
        for g in lp_input.valid_goals:
            tot = sum(perturbed[p].get(g, 0.0) for p in perturbed)
            if tot > 0.0:
                for p in perturbed:
                    if g in perturbed[p]:
                        perturbed[p][g] /= tot

        try:
            result = _solve_single_lp(
                valid_goals=lp_input.valid_goals,
                total_budget=lp_cap,
                system_goal_weights=lp_input.system_goal_weights,
                platform_goal_weights=lp_input.platform_goal_weights,
                r_pg=perturbed,
                goals_by_platform=lp_input.goals_by_platform,
                min_spend_per_platform=lp_input.min_spend_per_platform,
                min_budget_per_goal=lp_input.min_budget_per_goal,
                budget_cap=lp_cap,
                cpu_per_goal=lp_input.cpu_per_goal,
                effective_minimum_per_platform=lp_input.effective_minimum_per_platform,
            )
        except Module5ValidationError:
            # An individual trial can fail (e.g. all productivity zero by
            # chance).  Track but don't abort.
            failed_trials += 1
            continue

        for p, gdict in result.budget_per_platform_goal.items():
            ptotal = 0.0
            for g in lp_input.valid_goals:
                v = _safe_float(gdict.get(g, 0.0), 0.0)
                cell_alloc.setdefault(p, {}).setdefault(g, []).append(v)
                ptotal += v
            platform_alloc.setdefault(p, []).append(ptotal)

    if failed_trials >= n_trials:
        raise Module5ValidationError(
            f"All {n_trials} Monte Carlo trials failed. Check that historical "
            f"productivities are positive and CVs aren't extreme."
        )
    if failed_trials > 0:
        _LOG.warning(
            "Monte Carlo: %d/%d trials failed (skipped in aggregation).",
            failed_trials, n_trials,
        )

    per_cell: List[Module5MCCellSummary] = []
    for p, gdict in cell_alloc.items():
        for g, values in gdict.items():
            if values:
                per_cell.append(_summarise(values, platform=p, goal=g))

    per_platform: List[Module5MCCellSummary] = []
    unstable: List[str] = []
    for p, values in platform_alloc.items():
        if not values:
            continue
        summary = _summarise(values, platform=p, goal="")
        per_platform.append(summary)
        if summary.cv > instability_cv_threshold and summary.mean > 1.0:
            unstable.append(p)

    _LOG.info(
        "Monte Carlo: n_trials=%d failed=%d unstable=%s",
        n_trials, failed_trials, unstable,
    )

    return Module5MonteCarloResult(
        n_trials=n_trials - failed_trials,
        seed=seed,
        per_cell=per_cell,
        per_platform=per_platform,
        unstable_platforms=unstable,
        instability_threshold=instability_cv_threshold,
        cell_sigma=cell_sigma,
    )
