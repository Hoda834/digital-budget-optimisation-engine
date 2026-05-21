from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from core.wizard_state import WizardState
from core.kpi_config import KPI_CONFIG, KIND_COUNT, KIND_RATE
from modules.module5 import Module5LPResult, Module5ScenarioBundle


# KPI variable name → kind, built once at import time
_KPI_KIND: Dict[str, str] = {
    row["var"]: row.get("kind", KIND_COUNT)
    for row in KPI_CONFIG
}

# Default ±30% confidence band on count-KPI forecasts.  This is the *fallback*
# used when no per-KPI history is available; whenever Module 3 has either
# multi-period observations or a historical_days length, the band is derived
# from data (see _band_for_kpi).
DEFAULT_UNCERTAINTY_BAND = 0.30

# Reference window the default 30% band represents: ~30 days of digital
# campaign data.  Bands scale by sqrt(REF_WINDOW_DAYS / observed_days) so a
# 90-day history produces a ~17% band and a 7-day history a ~62% band.
_REFERENCE_WINDOW_DAYS = 30.0

# Hard limits so noisy data or pathological inputs can't produce 0% (false
# precision) or >100% (the forecast becomes meaningless) bands.
_MIN_BAND = 0.05
_MAX_BAND = 1.00


def _coefficient_of_variation(observations: Sequence[float]) -> Optional[float]:
    """Sample CV (std / mean) when there's enough data to be honest about it.

    Returns None when observations are too few, non-positive, or yield a
    mean ≤ 0 — caller should fall back to a window-scaled prior.
    """
    vals = [float(x) for x in observations if x is not None]
    vals = [x for x in vals if not math.isnan(x) and not math.isinf(x) and x > 0.0]
    if len(vals) < 3:
        return None
    mean = sum(vals) / len(vals)
    if mean <= 0.0:
        return None
    variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    std = math.sqrt(variance)
    return std / mean


def _band_for_kpi(
    observations: Optional[Sequence[float]],
    historical_days: Optional[int],
    default_band: float,
) -> float:
    """Pick the most data-driven band available.

    Preference order:
      1. Coefficient of variation from ≥3 observations (true sample noise)
      2. Default band scaled by sqrt(30 / historical_days) (more days → narrower)
      3. The flat default

    Clamped to [_MIN_BAND, _MAX_BAND] to prevent false precision and runaway
    bands.
    """
    cv = _coefficient_of_variation(observations) if observations else None
    if cv is not None:
        return max(_MIN_BAND, min(_MAX_BAND, cv))

    if historical_days and historical_days > 0:
        days = max(7.0, float(historical_days))  # floor at 7 so the band doesn't blow up
        scaled = default_band * math.sqrt(_REFERENCE_WINDOW_DAYS / days)
        return max(_MIN_BAND, min(_MAX_BAND, scaled))

    return max(_MIN_BAND, min(_MAX_BAND, default_band))


@dataclass
class Module6ForecastRow:
    platform: str
    objective: str
    kpi_name: str
    kpi_kind: str          # KIND_COUNT or KIND_RATE
    ratio_kpi_per_budget: float   # count KPI: units/£; rate KPI: the rate value itself
    allocated_budget: float
    predicted_kpi: float          # count KPI: units; rate KPI: expected rate (dimensionless)
    predicted_kpi_low: float = 0.0    # lower bound of the confidence band
    predicted_kpi_high: float = 0.0   # upper bound of the confidence band
    band_source: str = "default"      # "observations" | "window_scaled" | "default"
    band_pct: float = 0.0             # the band fraction actually used for this row


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
                "predicted_kpi_low": r.predicted_kpi_low,
                "predicted_kpi_high": r.predicted_kpi_high,
                "band_source": r.band_source,
                "band_pct": r.band_pct,
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
    uncertainty_band: float = DEFAULT_UNCERTAINTY_BAND,
    module3_data: Optional[Dict[str, Dict[str, Any]]] = None,
    seasonality_index: Optional[Dict[str, float]] = None,
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

                # Apply seasonality multiplier to count KPIs so the forecast
                # matches the productivity the LP optimised against.  Rate
                # KPIs are not adjusted here — they're dimensionless and a
                # seasonality multiplier on a rate is a separate concept.
                if seasonality_index and kind != KIND_RATE:
                    s_mult = seasonality_index.get(g)
                    if s_mult is not None:
                        try:
                            s_val = float(s_mult)
                            if s_val > 0.0:
                                predicted *= s_val
                        except (TypeError, ValueError):
                            pass

                if predicted <= 0.0:
                    d.skipped_invalid_ratio_items += 1
                    continue

                # Confidence band: count KPIs get a ±band% range to reflect the
                # inherent noise of digital ad performance.  Rate KPIs already
                # bake in averaging across the historical window, so we keep
                # the point estimate without a wider band.
                band_pct = 0.0
                band_source = "default"
                if kind == KIND_COUNT and uncertainty_band > 0:
                    # Per-KPI data-driven band: prefer observations, then
                    # historical window length, then the flat default.
                    pdata = (module3_data or {}).get(p) or {}
                    observations = (
                        (pdata.get("kpi_observations") or {}).get(kpi_name)
                        if isinstance(pdata.get("kpi_observations"), dict)
                        else None
                    )
                    hist_days = pdata.get("historical_days")
                    band_pct = _band_for_kpi(observations, hist_days, uncertainty_band)
                    if observations and _coefficient_of_variation(observations) is not None:
                        band_source = "observations"
                    elif hist_days and hist_days > 0:
                        band_source = "window_scaled"
                    p_low = predicted * (1.0 - band_pct)
                    p_high = predicted * (1.0 + band_pct)
                else:
                    p_low = predicted
                    p_high = predicted

                rows.append(
                    Module6ForecastRow(
                        platform=p,
                        objective=g,
                        kpi_name=kpi_name,
                        kpi_kind=kind,
                        ratio_kpi_per_budget=ratio_val,
                        allocated_budget=budget_val,
                        predicted_kpi=predicted,
                        predicted_kpi_low=p_low,
                        predicted_kpi_high=p_high,
                        band_source=band_source,
                        band_pct=band_pct,
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
    uncertainty_band: float = DEFAULT_UNCERTAINTY_BAND,
    module3_data: Optional[Dict[str, Dict[str, Any]]] = None,
    seasonality_index: Optional[Dict[str, float]] = None,
) -> Module6ScenarioResult:
    results_by_scenario: Dict[str, Module6Result] = {}
    for scenario_name, lp_res in module5_bundle.results_by_scenario.items():
        results_by_scenario[str(scenario_name)] = compute_module6_forecast(
            kpi_ratios=kpi_ratios,
            module5_result=lp_res,
            min_budget_threshold=min_budget_threshold,
            uncertainty_band=uncertainty_band,
            module3_data=module3_data,
            seasonality_index=seasonality_index,
        )
    return Module6ScenarioResult(results_by_scenario=results_by_scenario)


def run_module6(
    state: WizardState,
    min_budget_threshold: float = 1.0,
    uncertainty_band: float = DEFAULT_UNCERTAINTY_BAND,
) -> WizardState:
    if not state.module3_finalised:
        raise ValueError("Module 6 requires Module 3 to be finalised.")
    if not state.module5_finalised:
        raise ValueError("Module 6 requires Module 5 to be finalised.")
    if not getattr(state, "kpi_ratios", None):
        raise ValueError("Module 6 requires state.kpi_ratios to be populated from Module 3.")

    bundle = getattr(state, "module5_scenario_bundle", None)

    seasonality = getattr(state, "seasonality_index", None) or None

    if isinstance(bundle, Module5ScenarioBundle):
        scenario_forecast = compute_module6_forecast_for_scenarios(
            kpi_ratios=state.kpi_ratios,
            module5_bundle=bundle,
            min_budget_threshold=min_budget_threshold,
            uncertainty_band=uncertainty_band,
            module3_data=getattr(state, "module3_data", None),
            seasonality_index=seasonality,
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
            uncertainty_band=uncertainty_band,
            module3_data=getattr(state, "module3_data", None),
            seasonality_index=seasonality,
        )
        state.complete_module6(
            module6_result=forecast,
            module6_scenario_result=None,
        )

    return state
