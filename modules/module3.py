from __future__ import annotations

import math
from typing import Any, Dict, List

from core.wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG
from core.kpi_config import (
    KPI_CONFIG,
    KIND_COUNT,
    KIND_RATE,
    get_kpi_rows,
    effective_kpi_config,
)


def get_platform_kpis(platform: str, active_goals_for_platform: List[str]) -> List[Dict[str, Any]]:
    return [
        row
        for row in KPI_CONFIG
        if row["platform"] == platform and row["goal"] in active_goals_for_platform
    ]


def reset_wizard(state: WizardState) -> WizardState:
    state.reset()
    return state


def _validate_finite(value: float, label: str) -> float:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{label} must be a finite number.")
    return value


def _parse_positive_int(value: Any, label: str) -> int:
    try:
        d = int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be a positive integer (got {value!r}).") from e
    if d <= 0:
        raise ValueError(f"{label} must be greater than zero (got {d}).")
    return d


def ask_required_string(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required. Please enter a value.")


def ask_required_positive_int(prompt: str) -> int:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            d = int(text)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if d <= 0:
            print("Value must be greater than zero.")
            continue
        return d


def ask_required_budget_gt1(prompt: str) -> float:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            value = float(text)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if math.isnan(value) or math.isinf(value):
            print("Please enter a finite number.")
            continue
        if value <= 1:
            print("Value must be greater than 1.")
            continue
        return value


def ask_required_kpi_count(prompt: str) -> float:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            value = float(text)
        except ValueError:
            print("Please enter a valid numeric value.")
            continue
        if math.isnan(value) or math.isinf(value):
            print("Please enter a finite number.")
            continue
        if value <= 0:
            print("Count KPIs must be greater than zero.")
            continue
        return value


def ask_required_kpi_rate(prompt: str) -> float:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            value = float(text)
        except ValueError:
            print("Please enter a valid numeric value.")
            continue
        if math.isnan(value) or math.isinf(value):
            print("Please enter a finite number.")
            continue
        # Accept either fractional form (0.04) or percent form (4 → 0.04)
        if value > 1.0:
            if value <= 100.0:
                value = value / 100.0
            else:
                print("Rate must be a fraction in [0, 1] or a percentage in [0, 100].")
                continue
        if value <= 0.0:
            print("Rate must be greater than zero.")
            continue
        return value


def _compute_kpi_ratios_for_platform(
    platform: str,
    budget: float,
    kpi_values: Dict[str, float],
    kpi_catalog: List[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, float]]:
    """Return kpi_ratios[goal][var] = productivity for one platform.

    For count KPIs the productivity is value / budget (units per money).
    For rate KPIs the productivity is the rate itself (already dimensionless;
    dividing by budget would be meaningless).

    ``kpi_catalog`` defaults to the built-in KPI_CONFIG; pass
    effective_kpi_config(state) to include custom-platform rows.
    """
    if kpi_catalog is None:
        kpi_catalog = KPI_CONFIG
    out: Dict[str, Dict[str, float]] = {}
    for row in kpi_catalog:
        if row["platform"] != platform:
            continue
        var = row["var"]
        if var not in kpi_values:
            continue
        goal = row["goal"]
        kind = row.get("kind", KIND_COUNT)
        value = float(kpi_values[var])
        if kind == KIND_RATE:
            productivity = value
        else:
            if budget <= 0:
                continue
            productivity = value / budget
        out.setdefault(goal, {})[var] = productivity
    return out


def run_module3(state: WizardState) -> WizardState:
    if state.module3_finalised:
        raise RuntimeError(
            "Module 3 has already been finalised. You cannot edit it. "
            "Reset the wizard to start again."
        )

    if not state.module2_finalised:
        raise RuntimeError("Module 2 must be finalised before running Module 3.")

    if not state.active_platforms:
        raise RuntimeError("No active platforms found. Nothing to do in Module 3.")

    temp_module3_data: Dict[str, Dict[str, Any]] = {}

    currency = getattr(state, "currency", "GBP")
    duration_hint = getattr(state, "campaign_duration_days", None)

    print("\n=== MODULE 3: Historical budget and KPI data collection ===\n")
    if duration_hint:
        print(f"(Use a comparable window to your planned {duration_hint}-day campaign.)\n")

    for platform in state.active_platforms:
        print("\n------------------------------------------")
        print(f"Platform: {platform}")
        print("------------------------------------------\n")

        historical_days = ask_required_positive_int(
            f"How many days of {platform} history are you reporting "
            f"(a positive integer, e.g. 30)? "
        )
        time_window_label = ask_required_string(
            f"Optional label for this window (e.g. 'last 30 days', 'Q4 2024'): "
        )

        budget = ask_required_budget_gt1(
            f"Enter the historical budget spent on {platform} "
            f"over {historical_days} days in {currency} (numeric > 1): "
        )

        active_goals = state.goals_by_platform.get(platform, [])
        platform_kpis: List[Dict[str, Any]] = (
            get_platform_kpis(platform, active_goals) if active_goals else []
        )

        kpi_values: Dict[str, float] = {}

        for kpi_def in platform_kpis:
            var = kpi_def["var"]
            label = kpi_def["kpi_label"]
            goal = kpi_def["goal"]
            kind = kpi_def.get("kind", KIND_COUNT)

            if kind == KIND_RATE:
                prompt = (
                    f"{platform} | Goal: {goal} | KPI: {label} ({var}) "
                    f"rate (0-1 or 0-100%): "
                )
                value = ask_required_kpi_rate(prompt)
            else:
                prompt = (
                    f"{platform} | Goal: {goal} | KPI: {label} ({var}) "
                    f"count (> 0): "
                )
                value = ask_required_kpi_count(prompt)
            kpi_values[var] = value

        temp_module3_data[platform] = {
            "time_window": time_window_label,
            "historical_days": historical_days,
            "budget": budget,
            "kpis": kpi_values,
        }

    while True:
        choice = input("Type 'submit' to confirm, or 'reset' to restart: ").strip().lower()

        if choice == "reset":
            return reset_wizard(state)

        if choice == "submit":
            return _finalise_module3(state, temp_module3_data)

        print("Invalid choice. Please type exactly 'submit' or 'reset'.")


def _finalise_module3(
    state: WizardState,
    temp_module3_data: Dict[str, Dict[str, Any]],
) -> WizardState:
    platform_budgets: Dict[str, float] = {}
    platform_kpis: Dict[str, Dict[str, float]] = {}
    kpi_ratios: Dict[str, Dict[str, Dict[str, float]]] = {}

    kpi_catalog = effective_kpi_config(state)
    for platform, pdata in temp_module3_data.items():
        budget = float(pdata["budget"])
        kpis: Dict[str, float] = pdata["kpis"]

        platform_budgets[platform] = budget
        platform_kpis[platform] = dict(kpis)
        kpi_ratios[platform] = _compute_kpi_ratios_for_platform(
            platform, budget, kpis, kpi_catalog=kpi_catalog,
        )

    state.complete_module3_and_advance(
        module3_data=temp_module3_data,
        platform_budgets=platform_budgets,
        platform_kpis=platform_kpis,
        kpi_ratios=kpi_ratios,
    )

    return state


def finalise_module3_from_inputs(
    state: WizardState,
    platform_inputs: Dict[str, Dict[str, Any]],
) -> WizardState:
    """Non-interactive entry point. ``platform_inputs[platform]`` must contain
    ``time_window``, ``budget`` and ``kpis`` keys, matching the shape produced by
    ``run_module3``."""
    if state.module3_finalised:
        raise RuntimeError("Module 3 has already been finalised. Reset to run again.")
    if not state.module2_finalised:
        raise RuntimeError("Module 2 must be finalised before running Module 3.")
    if not state.active_platforms:
        raise RuntimeError("No active platforms found. Nothing to do in Module 3.")

    cleaned: Dict[str, Dict[str, Any]] = {}
    campaign_days = getattr(state, "campaign_duration_days", None)

    for platform in state.active_platforms:
        if platform not in platform_inputs:
            raise ValueError(f"Module 3 inputs missing for platform {platform!r}.")
        pin = platform_inputs[platform]
        try:
            budget = _validate_finite(float(pin["budget"]), f"budget for {platform}")
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Module 3 inputs invalid for platform {platform!r}: {e}") from e
        if budget <= 1.0:
            raise ValueError(f"Historical budget for {platform!r} must be greater than 1.")

        historical_days = _parse_positive_int(
            pin.get("historical_days") if "historical_days" in pin else campaign_days,
            f"historical_days for {platform}",
        )
        time_window_label = str(pin.get("time_window", f"{historical_days} days")).strip()
        if not time_window_label:
            time_window_label = f"{historical_days} days"

        raw_kpis = pin.get("kpis", {})
        if not isinstance(raw_kpis, dict):
            raise ValueError(f"Module 3 inputs for {platform!r}: kpis must be a dict.")

        validated_kpis: Dict[str, float] = {}
        active_goals = state.goals_by_platform.get(platform, [])
        kpi_catalog = effective_kpi_config(state)
        allowed_vars = {row["var"] for row in kpi_catalog
                        if row["platform"] == platform and row["goal"] in active_goals}
        for var, raw_value in raw_kpis.items():
            if var not in allowed_vars:
                continue
            try:
                v = _validate_finite(float(raw_value), f"KPI {var}")
            except (TypeError, ValueError) as e:
                # Translate raw float() / None failures into a clean
                # ValueError with the offending value so API callers see
                # a useful message instead of a TypeError from inside float.
                raise ValueError(
                    f"KPI {var} for platform {platform!r} must be numeric, "
                    f"got {raw_value!r} ({type(raw_value).__name__})"
                ) from e
            kind = next((r.get("kind", KIND_COUNT) for r in kpi_catalog
                         if r["platform"] == platform and r["var"] == var), KIND_COUNT)
            if kind == KIND_RATE:
                if v > 1.0:
                    if v <= 100.0:
                        v = v / 100.0
                    else:
                        raise ValueError(f"Rate KPI {var} must be in [0,1] or [0,100], got {raw_value}.")
                if v <= 0.0:
                    raise ValueError(f"Rate KPI {var} must be greater than zero.")
            else:
                if v <= 0:
                    raise ValueError(f"Count KPI {var} must be greater than zero.")
            validated_kpis[var] = v

        # Optional multi-period observations for variance-based confidence
        # bands in Module 6.  Shape: {var: [v1, v2, ...]}.  Only count KPIs are
        # supported (rate KPIs are already an average).  Each list must contain
        # positive finite values; invalid entries are dropped, and lists with
        # <3 surviving values are dropped wholesale (the band falls back to
        # the window-scaled prior).
        validated_observations: Dict[str, List[float]] = {}
        raw_observations = pin.get("kpi_observations", {})
        if isinstance(raw_observations, dict):
            for var, raw_list in raw_observations.items():
                if var not in allowed_vars or not isinstance(raw_list, (list, tuple)):
                    continue
                kind = next((r.get("kind", KIND_COUNT) for r in kpi_catalog
                             if r["platform"] == platform and r["var"] == var), KIND_COUNT)
                if kind == KIND_RATE:
                    continue
                clean_list: List[float] = []
                for raw in raw_list:
                    try:
                        v = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if v > 0.0 and not (v != v or v == float("inf") or v == float("-inf")):
                        clean_list.append(v)
                if len(clean_list) >= 3:
                    validated_observations[var] = clean_list

        cleaned[platform] = {
            "time_window": time_window_label,
            "historical_days": historical_days,
            "budget": budget,
            "kpis": validated_kpis,
            "kpi_observations": validated_observations,
        }

    return _finalise_module3(state, cleaned)


if __name__ == "__main__":
    s = WizardState(
        current_step=3,
        module1_finalised=True,
        module2_finalised=True,
        total_budget=10000.0,
        valid_goals=[GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG],
        active_platforms=["fb", "ig"],
        goals_by_platform={
            "fb": [GOAL_AW, GOAL_EN],
            "ig": [GOAL_AW, GOAL_LG],
        },
    )
    try:
        run_module3(s)
    except RuntimeError as e:
        print(f"Error: {e}")
