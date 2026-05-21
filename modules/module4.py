from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.wizard_state import WizardState, FlowStateError
from core.kpi_config import KPI_CONFIG, KIND_COUNT, KIND_RATE


# CPU values more than this multiple of the per-goal median are flagged as outliers
# (likely caused by a tiny KPI count or a unit/scale error) and skipped.
CPU_OUTLIER_MULTIPLE = 100.0


class Module4ValidationError(Exception):
    pass


@dataclass
class Module4Result:
    # cpu_per_goal[platform][goal][var] = cost per unit KPI
    # For count KPIs:   cpu = budget / value   (currency per unit)
    # For rate KPIs:    cpu is omitted (a "cost per percentage point" is not meaningful here)
    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]]
    valid_platforms: Set[str]
    # Snapshot of policy data so downstream modules don't have to round-trip via state.
    min_spend_per_platform: Dict[str, float] = field(default_factory=dict)
    min_budget_per_goal: Dict[str, float] = field(default_factory=dict)
    scenario_multipliers: Dict[str, float] = field(default_factory=dict)
    scenario_goal_multipliers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    skipped_rows: List[str] = field(default_factory=list)


def _assert_module4_flow_allowed(state: WizardState) -> None:
    if state.current_step != 4:
        raise FlowStateError(
            f"Module 4 can only run when current_step == 4. Current value is {state.current_step!r}."
        )
    if not state.module3_finalised:
        raise FlowStateError("Module 4 requires Module 3 to be finalised.")
    if not state.valid_goals:
        raise Module4ValidationError("No valid goals available in wizard state.")
    if not state.active_platforms:
        raise Module4ValidationError("No active platforms found for Module 4.")
    if state.module4_finalised:
        raise FlowStateError("Module 4 has already been finalised. Reset to run again.")


def _index_kpi_config(kpi_config: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Return idx[platform][goal] -> list of KPI_CONFIG rows."""
    idx: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in kpi_config:
        idx.setdefault(row["platform"], {}).setdefault(row["goal"], []).append(row)
    return idx


def _is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def run_module4(
    state: WizardState,
    kpi_config: Optional[List[Dict[str, Any]]] = None,
) -> Module4Result:
    _assert_module4_flow_allowed(state)

    if kpi_config is None:
        kpi_config = KPI_CONFIG

    idx = _index_kpi_config(kpi_config)

    active_platforms: List[str] = state.active_platforms
    goals_by_platform: Dict[str, List[str]] = state.goals_by_platform
    platform_budgets: Dict[str, float] = state.platform_budgets
    platform_kpis: Dict[str, Dict[str, float]] = state.platform_kpis
    module3_data: Dict[str, Dict[str, Any]] = state.module3_data

    cpu_per_goal: Dict[str, Dict[str, Dict[str, float]]] = {}
    skipped: List[str] = []

    for platform in active_platforms:
        if platform not in platform_budgets:
            raise Module4ValidationError(f"Missing budget for platform {platform!r}.")

        try:
            budget = float(platform_budgets[platform])
        except (TypeError, ValueError) as e:
            raise Module4ValidationError(f"Budget for platform {platform!r} must be numeric.") from e

        if not _is_finite(budget):
            raise Module4ValidationError(f"Budget for platform {platform!r} must be finite.")
        if budget <= 1:
            raise Module4ValidationError(
                f"Budget for platform {platform!r} must be greater than 1. Got {budget!r}."
            )

        kpis_for_p = platform_kpis.get(platform) or module3_data.get(platform, {}).get("kpis", {})
        if not kpis_for_p:
            skipped.append(f"{platform}: no KPI values from Module 3")
            continue

        active_goals_for_p = goals_by_platform.get(platform, [])
        if not active_goals_for_p:
            skipped.append(f"{platform}: no prioritised goals from Module 2")
            continue

        for goal in active_goals_for_p:
            rows = idx.get(platform, {}).get(goal, [])
            if not rows:
                skipped.append(f"{platform}/{goal}: no KPI_CONFIG row")
                continue

            for row in rows:
                var = row["var"]
                kind = row.get("kind", KIND_COUNT)

                if var not in kpis_for_p:
                    skipped.append(f"{platform}/{goal}/{var}: no value from Module 3")
                    continue

                try:
                    kpi_val = float(kpis_for_p[var])
                except (TypeError, ValueError):
                    skipped.append(f"{platform}/{goal}/{var}: non-numeric value")
                    continue

                if not _is_finite(kpi_val) or kpi_val <= 0:
                    skipped.append(f"{platform}/{goal}/{var}: non-positive or non-finite value")
                    continue

                # Rate KPIs have no meaningful "cost per percentage point" — record
                # them in skipped and let Module 5 use them via kpi_ratios instead.
                if kind == KIND_RATE:
                    continue

                cpu = budget / kpi_val
                if not _is_finite(cpu) or cpu <= 0:
                    skipped.append(f"{platform}/{goal}/{var}: non-finite or non-positive CPU")
                    continue

                cpu_per_goal.setdefault(platform, {}).setdefault(goal, {})[var] = cpu

    # Outlier sweep: tiny KPI counts (e.g. 1 lead from a £5,000 spend) yield CPUs
    # that are orders of magnitude higher than their peers and would dominate the
    # LP if used directly. We bucket by (goal, kpi_label) — that's "cost per Lead",
    # "cost per Click" etc. across platforms — and drop rows above the threshold.
    label_lookup = {(row["platform"], row["var"]): row["kpi_label"] for row in kpi_config}

    by_goal_label: Dict[Tuple[str, str], List[float]] = {}
    for p, gdict in cpu_per_goal.items():
        for g, kdict in gdict.items():
            for var, cpu in kdict.items():
                label = label_lookup.get((p, var), var)
                by_goal_label.setdefault((g, label), []).append(cpu)

    medians: Dict[Tuple[str, str], float] = {
        key: sorted(vals)[len(vals) // 2]
        for key, vals in by_goal_label.items()
        if len(vals) >= 2  # cannot detect outliers with fewer than 2 peers
    }

    for p in list(cpu_per_goal.keys()):
        for g in list(cpu_per_goal[p].keys()):
            for var in list(cpu_per_goal[p][g].keys()):
                label = label_lookup.get((p, var), var)
                median = medians.get((g, label), 0.0)
                if median <= 0:
                    continue
                cpu = cpu_per_goal[p][g][var]
                if cpu > median * CPU_OUTLIER_MULTIPLE:
                    skipped.append(
                        f"{p}/{g}/{var}: CPU {cpu:.2f} is >{CPU_OUTLIER_MULTIPLE:.0f}x "
                        f"the cross-platform median for {label!r} ({median:.2f}); "
                        f"dropped as outlier."
                    )
                    del cpu_per_goal[p][g][var]
            if not cpu_per_goal[p][g]:
                del cpu_per_goal[p][g]
        if not cpu_per_goal[p]:
            del cpu_per_goal[p]

    valid_platforms: Set[str] = {p for p, gdict in cpu_per_goal.items() if gdict}

    if not cpu_per_goal:
        raise Module4ValidationError(
            "Module 4 computed an empty cpu_per_goal table. Check Module 3 data."
        )

    result = Module4Result(
        cpu_per_goal=cpu_per_goal,
        valid_platforms=valid_platforms,
        min_spend_per_platform=dict(state.min_spend_per_platform),
        min_budget_per_goal=dict(state.min_budget_per_goal),
        scenario_multipliers=dict(state.scenario_multipliers),
        scenario_goal_multipliers={s: dict(m) for s, m in state.scenario_goal_multipliers.items()},
        skipped_rows=skipped,
    )

    state.complete_module4_and_advance(module4_result=result)

    return result
