from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.wizard_state import WizardState
from core.kpi_config import KIND_RATE
from modules.module5 import Module5LPResult, Module5ScenarioBundle
from modules.module6 import Module6Result


PLATFORM_NAMES: Dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
}

GOAL_NAMES: Dict[str, str] = {
    "aw": "Awareness",
    "en": "Engagement",
    "wt": "Website Traffic",
    "lg": "Lead Generation",
}


@dataclass
class PlanOutput:
    allocation: Dict[str, Dict[str, float]]
    objective_value_estimate: float
    kpi_focus: str
    tradeoff_percent: Optional[float] = None


@dataclass
class Module7ScenarioInsight:
    scenario_name: str
    decision_mode: str
    classification: str
    confidence_score: int
    allocation_is_corner_solution: bool
    concentration_ratio_top_platform: float
    dominant_platform: Optional[str]
    dominant_objective: Optional[str]
    binding_constraints: List[str] = field(default_factory=list)
    non_binding_constraints: List[str] = field(default_factory=list)
    scenario_stability_explanation: str = ""
    data_quality_note: Optional[str] = None
    plan_a: Optional[PlanOutput] = None
    plan_b: Optional[PlanOutput] = None
    risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    executive_summary: str = ""


@dataclass
class Module7BundleInsight:
    scenario_insights: Dict[str, Module7ScenarioInsight] = field(default_factory=dict)
    global_stability_explanation: str = ""
    global_data_quality_note: Optional[str] = None
    global_notes: List[str] = field(default_factory=list)
    # Standard caveat shown alongside every plan: digital ad performance changes
    # week to week, so historical ratios should be validated against live
    # platform data before committing the full budget.
    forecast_caveat: str = ""


_FORECAST_CAVEAT = (
    "Forecasts assume historical KPI ratios will hold over the campaign window. "
    "Actual results commonly differ by 20-40% due to algorithm updates, "
    "seasonality, competitive bidding pressure, audience saturation, and "
    "creative fatigue. Validate against current platform benchmarks before "
    "committing the full budget."
)

_NO_VALUE_WEIGHTS_NOTE = (
    " No per-goal economic values were provided, so goal weights were derived "
    "from priority frequency. This approximates but does not measure the relative "
    "business value of each objective. For multi-objective campaigns, supply "
    "raw_goal_values (e.g. {'lg': 100.0, 'aw': 0.001}) in Module 1 to get a "
    "ROAS-weighted allocation."
)


def _f(x: object) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return v


def _k(x: object) -> str:
    return str(x).strip().lower()


def _pname(code: Optional[str]) -> str:
    if not code:
        return ""
    return PLATFORM_NAMES.get(_k(code), str(code))


def _gname(code: Optional[str]) -> str:
    if not code:
        return ""
    return GOAL_NAMES.get(_k(code), str(code))


def _platform_totals(lp: Module5LPResult) -> Dict[str, float]:
    if lp.budget_per_platform:
        return {_k(k): max(0.0, _f(v)) for k, v in lp.budget_per_platform.items()}
    out: Dict[str, float] = {}
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        s = 0.0
        for v in (gmap or {}).values():
            s += max(0.0, _f(v))
        out[_k(p)] = s
    return out


def _goal_totals(lp: Module5LPResult) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for gmap in (lp.budget_per_platform_goal or {}).values():
        for g, v in (gmap or {}).items():
            gg = _k(g)
            out[gg] = out.get(gg, 0.0) + max(0.0, _f(v))
    return out


def _dominant(d: Dict[str, float]) -> Optional[str]:
    if not d:
        return None
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
    if not items or items[0][1] <= 0.0:
        return None
    return items[0][0]


def _ratio(d: Dict[str, float]) -> float:
    t = sum(max(0.0, v) for v in d.values())
    if t <= 0:
        return 0.0
    top = max(max(0.0, v) for v in d.values())
    return float(top / t)


def _nonzero_allocations(lp: Module5LPResult) -> int:
    c = 0
    for gmap in (lp.budget_per_platform_goal or {}).values():
        for v in (gmap or {}).values():
            if _f(v) > 1e-6:
                c += 1
    return c


def _corner(lp: Module5LPResult) -> bool:
    return _nonzero_allocations(lp) <= 2


def _alloc_signature(lp: Module5LPResult) -> Dict[str, Dict[str, float]]:
    sig: Dict[str, Dict[str, float]] = {}
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        pk = _k(p)
        sig[pk] = {}
        for g, v in (gmap or {}).items():
            sig[pk][_k(g)] = round(max(0.0, _f(v)), 6)
    return sig


def _allocations_identical(bundle: Module5ScenarioBundle) -> bool:
    keys = list((bundle.results_by_scenario or {}).keys())
    if len(keys) <= 1:
        return True
    base = _alloc_signature(bundle.results_by_scenario[keys[0]])
    for k in keys[1:]:
        cur = _alloc_signature(bundle.results_by_scenario[k])
        if cur != base:
            return False
    return True


def _stability_text(bundle: Module5ScenarioBundle) -> str:
    keys = list((bundle.results_by_scenario or {}).keys())
    if len(keys) <= 1:
        return "Only one scenario result is available."
    if _allocations_identical(bundle):
        return (
            "The allocation decision is stable across scenarios. Scenario multipliers change the available "
            "budget cap, but they do not shift the optimal ranking of channel and objective options in the "
            "tested range."
        )
    return (
        "The allocation changes across scenarios. Scenario multipliers change the budget cap, which shifts "
        "how much can flow into each channel and objective, making the decision scenario-sensitive."
    )


def _constraints(state: WizardState, lp: Module5LPResult) -> Tuple[List[str], List[str]]:
    b: List[str] = []
    nb: List[str] = []

    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    for p, m in (getattr(state, "min_spend_per_platform", {}) or {}).items():
        pk = _k(p)
        req = max(0.0, _f(m))
        if req <= 0:
            continue
        actual = max(0.0, _f(pt.get(pk, 0.0)))
        label = f"Minimum spend on {_pname(pk)}"
        if abs(actual - req) <= max(1e-6, 1e-3 * req):
            b.append(label)
        elif actual > req:
            nb.append(label)

    for g, m in (getattr(state, "min_budget_per_goal", {}) or {}).items():
        gk = _k(g)
        req = max(0.0, _f(m))
        if req <= 0:
            continue
        actual = max(0.0, _f(gt.get(gk, 0.0)))
        label = f"Minimum budget for {_gname(gk)}"
        if abs(actual - req) <= max(1e-6, 1e-3 * req):
            b.append(label)
        elif actual > req:
            nb.append(label)

    return b, nb


def _classification(bundle: Module5ScenarioBundle, lp: Module5LPResult) -> str:
    if not _allocations_identical(bundle):
        return "Scenario-sensitive"
    pt = _platform_totals(lp)
    pr = _ratio(pt)
    nz = _nonzero_allocations(lp)
    # Corner-dominant: a literal corner solution (≤2 funded cells) or extreme
    # concentration (≥90 %). A 3-platform 80/10/10 split does NOT qualify.
    if nz <= 2 or pr >= 0.90:
        return "Corner-dominant"
    if nz >= 3 and pr <= 0.75:
        return "Balanced"
    return "Concentrated"  # moderate concentration: 75–90 % to one platform


def _data_quality_note(lp: Module5LPResult, fc: Optional[Module6Result]) -> Optional[str]:
    issues: List[str] = []

    if fc is None or not getattr(fc, "rows", None):
        issues.append("No forecast rows are available for this scenario.")
    else:
        small = 0
        total = 0
        for r in fc.rows:
            # Rate KPIs (engagement rate etc.) are naturally in [0, 1] — applying a
            # count-KPI "small value" threshold to them would always fire falsely.
            if getattr(r, "kpi_kind", None) == KIND_RATE:
                continue
            total += 1
            if _f(getattr(r, "predicted_kpi", 0.0)) < 5.0:
                small += 1
        if total > 0 and small / float(total) >= 0.50:
            issues.append("Many forecast KPI values are very small, which may indicate unit or scaling issues in the input data.")

    rpg = getattr(lp, "r_pg", None)
    if not isinstance(rpg, dict) or not rpg:
        issues.append("Productivity ratios are missing in the LP result.")

    if issues:
        return " ".join(issues)

    return None


def _confidence(lp: Module5LPResult, bundle: Module5ScenarioBundle, fc: Optional[Module6Result], dq_note: Optional[str]) -> int:
    score = 100

    pt = _platform_totals(lp)
    pr = _ratio(pt)
    nz = _nonzero_allocations(lp)

    if pr >= 0.90:
        score -= 20
    elif pr >= 0.80:
        score -= 12

    if nz <= 2:
        score -= 8

    if not _allocations_identical(bundle):
        score -= 10

    if fc is None or not getattr(fc, "rows", None):
        # Missing forecast is a single root cause — don't also deduct for the
        # dq_note that was itself triggered by the missing forecast.
        score -= 18
    elif dq_note:
        # Only penalise for data-quality issues when the forecast actually exists.
        score -= 12

    if score < 40:
        score = 40
    if score > 100:
        score = 100

    return int(score)


def _score_pg(lp: Module5LPResult) -> Dict[str, Dict[str, float]]:
    scores: Dict[str, Dict[str, float]] = {}
    rpg = getattr(lp, "r_pg", {}) or {}
    wpg = getattr(lp, "combined_weight_pg", {}) or {}

    for p, gmap in (rpg if isinstance(rpg, dict) else {}).items():
        pk = _k(p)
        if pk not in scores:
            scores[pk] = {}
        for g, r in (gmap if isinstance(gmap, dict) else {}).items():
            gk = _k(g)
            rr = max(0.0, _f(r))
            ww = max(0.0, _f(((wpg.get(p, {}) or {}) if isinstance(wpg, dict) else {}).get(g, 0.0)))
            val = rr * ww
            if val > 0:
                scores[pk][gk] = val

    scores = {p: gmap for p, gmap in scores.items() if gmap}
    return scores


def _objective_scale(lp: Module5LPResult) -> float:
    raw = _f(getattr(lp, "objective_value_raw", 0.0))
    scaled = _f(getattr(lp, "objective_value", 0.0))
    if raw > 0 and scaled > 0:
        return scaled / raw
    return 1000.0


def _estimate_objective_value(allocation: Dict[str, Dict[str, float]], lp_ref: Module5LPResult) -> float:
    scores = _score_pg(lp_ref)
    scale = _objective_scale(lp_ref)
    raw = 0.0
    for p, gmap in allocation.items():
        pk = _k(p)
        for g, b in (gmap or {}).items():
            gk = _k(g)
            raw += max(0.0, _f(b)) * max(0.0, _f((scores.get(pk, {}) or {}).get(gk, 0.0)))
    return raw * scale


def _plan_a(lp: Module5LPResult) -> PlanOutput:
    pt = _platform_totals(lp)
    gt = _goal_totals(lp)
    dp = _dominant(pt)
    dg = _dominant(gt)
    focus = ""
    if dp and dg:
        focus = f"{_pname(dp)} and {_gname(dg)}"
    elif dp:
        focus = _pname(dp)
    elif dg:
        focus = _gname(dg)
    else:
        focus = "No clear primary lane"

    alloc: Dict[str, Dict[str, float]] = {}
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        pk = _k(p)
        alloc[pk] = {}
        for g, v in (gmap or {}).items():
            alloc[pk][_k(g)] = max(0.0, _f(v))

    return PlanOutput(
        allocation=alloc,
        objective_value_estimate=_f(getattr(lp, "objective_value", 0.0)),
        kpi_focus=focus,
        tradeoff_percent=None,
    )


def _plan_b_risk_managed(
    state: WizardState,
    lp: Module5LPResult,
    cap_top_platform_share: float = 0.70,
) -> Optional[PlanOutput]:
    """Return a diversified alternative that caps the dominant platform.

    The LP (Plan A) already satisfies all minimum-spend constraints set in
    Module 2, so we do not re-enforce them here — that would re-implement
    policy independently and risk inconsistency.  We simply scale down the
    top platform and redistribute the freed budget to the remaining platforms
    in proportion to their LP productivity scores.
    """
    total_budget = max(0.0, _f(getattr(lp, "total_budget_used", 0.0)))
    if total_budget <= 0:
        total_budget = max(0.0, _f(getattr(state, "total_budget", 0.0)))
    if total_budget <= 0:
        return None

    valid_goals = [_k(g) for g in (getattr(state, "valid_goals", []) or [])]
    if not valid_goals:
        return None

    plan_a = _plan_a(lp)
    pt_a: Dict[str, float] = {
        p: sum(max(0.0, _f(v)) for v in (gmap or {}).values())
        for p, gmap in plan_a.allocation.items()
    }

    top_p = _dominant(pt_a)
    if not top_p:
        return None

    cap_value = max(0.0, float(cap_top_platform_share)) * total_budget
    current_top = max(0.0, _f(pt_a.get(top_p, 0.0)))

    if current_top <= cap_value + 1e-6:
        # Already within the cap — Plan B = Plan A.
        return PlanOutput(
            allocation=plan_a.allocation,
            objective_value_estimate=_estimate_objective_value(plan_a.allocation, lp),
            kpi_focus="Diversified execution",
            tradeoff_percent=0.0,
        )

    scores = _score_pg(lp)
    if not scores:
        return None

    # Start from Plan A and scale down the top platform.
    alloc_b: Dict[str, Dict[str, float]] = {
        p: {_k(g): max(0.0, _f(v)) for g, v in (gmap or {}).items()}
        for p, gmap in plan_a.allocation.items()
    }
    factor = cap_value / current_top
    for g in list(alloc_b.get(top_p, {}).keys()):
        alloc_b[top_p][g] *= factor

    freed = total_budget - sum(
        sum(v for v in gmap.values()) for gmap in alloc_b.values()
    )
    if freed < 0:
        freed = 0.0

    # Distribute freed budget to other platforms proportionally by LP scores.
    weights: List[Tuple[str, str, float]] = []
    for p, gmap in scores.items():
        pk = _k(p)
        if pk == top_p:
            continue
        for g, s in (gmap or {}).items():
            gk = _k(g)
            if gk not in valid_goals:
                continue
            w = max(0.0, _f(s))
            if w > 0:
                weights.append((pk, gk, w))

    total_w = sum(w for _, _, w in weights)
    if total_w > 0 and freed > 0:
        for pk, gk, w in weights:
            alloc_b.setdefault(pk, {})[gk] = (
                alloc_b.get(pk, {}).get(gk, 0.0) + freed * (w / total_w)
            )

    obj_a = _estimate_objective_value(plan_a.allocation, lp)
    obj_b = _estimate_objective_value(alloc_b, lp)

    tradeoff = None
    if obj_a > 1e-9:
        tradeoff = max(0.0, (obj_a - obj_b) / obj_a) * 100.0

    return PlanOutput(
        allocation=alloc_b,
        objective_value_estimate=obj_b,
        kpi_focus="Diversified execution",
        tradeoff_percent=tradeoff,
    )


def _risks_recs(
    classification: str,
    confidence: int,
    stability_text: str,
    dq_note: Optional[str],
    plan_b: Optional[PlanOutput],
) -> Tuple[List[str], List[str]]:
    risks: List[str] = []
    recs: List[str] = []

    if classification == "Corner-dominant":
        risks.append("Budget is highly concentrated, which increases dependency on a single channel.")
        recs.append("Use the risk managed plan if you want to reduce concentration risk.")

    if classification == "Concentrated":
        risks.append("Budget leans toward one channel; performance is sensitive to that channel's delivery.")
        recs.append("Monitor the dominant channel closely and consider the risk managed plan as a hedge.")

    if classification == "Scenario-sensitive":
        risks.append("The recommended allocation changes across scenarios, which suggests higher uncertainty.")
        recs.append("Keep a contingency portion of budget to switch lanes if performance deviates.")

    if dq_note:
        risks.append("Data quality signals suggest the outputs should be treated as conditional.")
        recs.append("Review the historical KPI values and ensure consistent units and time windows across platforms.")

    if confidence <= 55:
        risks.append("Overall confidence is moderate to low.")
        recs.append("Use this allocation as a starting point and validate with a short test cycle before committing the full budget.")

    if plan_b and plan_b.tradeoff_percent is not None and plan_b.tradeoff_percent >= 5.0:
        recs.append("Expect some efficiency loss when diversifying. The trade off is reported in Plan B.")

    return risks, recs


def _summary_text(
    scenario_name: str,
    classification: str,
    confidence: int,
    lp: Module5LPResult,
    bindings: List[str],
    stability_text: str,
    dq_note: Optional[str],
) -> str:
    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    dp = _dominant(pt)
    dg = _dominant(gt)

    pr = int(round(_ratio(pt) * 100.0))
    gr = int(round(_ratio(gt) * 100.0))

    lane = ""
    if dp and dg:
        lane = f"{_pname(dp)} and {_gname(dg)}"
    elif dp:
        lane = _pname(dp)
    elif dg:
        lane = _gname(dg)
    else:
        lane = "no dominant lane"

    parts: List[str] = []
    parts.append(f"Scenario {scenario_name}: {classification} decision with confidence score {confidence}/100.")
    parts.append(f"The optimiser concentrates spend around {lane}.")
    if dp:
        parts.append(f"Top platform share is about {pr} percent.")
    if dg:
        parts.append(f"Top objective share is about {gr} percent.")
    if bindings:
        parts.append("Binding constraints include " + ", ".join(bindings) + ".")
    if stability_text:
        parts.append(stability_text)
    if dq_note:
        parts.append("Data quality note: " + dq_note)
    return " ".join(parts)


def run_module7(
    state: WizardState,
    bundle: Module5ScenarioBundle,
    forecasts: Optional[Dict[str, Module6Result]] = None,
    decision_mode: str = "Performance first",
) -> Module7BundleInsight:
    out = Module7BundleInsight()

    stability_text = _stability_text(bundle)
    out.global_stability_explanation = stability_text

    global_dq: List[str] = []

    for s_name, lp in (bundle.results_by_scenario or {}).items():
        fc = forecasts.get(s_name) if forecasts else None

        classification = _classification(bundle, lp)
        dq_note = _data_quality_note(lp, fc)
        confidence = _confidence(lp, bundle, fc, dq_note)

        bindings, non_bindings = _constraints(state, lp)

        pt = _platform_totals(lp)
        gt = _goal_totals(lp)
        dp = _dominant(pt)
        dg = _dominant(gt)
        conc = _ratio(pt)

        plan_a = _plan_a(lp)
        plan_b = None
        if decision_mode.strip().lower() == "risk managed":
            plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
        elif classification == "Corner-dominant":
            plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)

        risks, recs = _risks_recs(classification, confidence, stability_text, dq_note, plan_b)

        executive = _summary_text(
            scenario_name=str(s_name).capitalize(),
            classification=classification,
            confidence=confidence,
            lp=lp,
            bindings=bindings[:3],
            stability_text="",
            dq_note=dq_note,
        )

        if dq_note:
            global_dq.append(dq_note)

        out.scenario_insights[str(s_name)] = Module7ScenarioInsight(
            scenario_name=str(s_name),
            decision_mode=decision_mode,
            classification=classification,
            confidence_score=confidence,
            allocation_is_corner_solution=_corner(lp),
            concentration_ratio_top_platform=float(conc),
            dominant_platform=_pname(dp) if dp else None,
            dominant_objective=_gname(dg) if dg else None,
            binding_constraints=bindings,
            non_binding_constraints=non_bindings,
            scenario_stability_explanation=stability_text,
            data_quality_note=dq_note,
            plan_a=plan_a,
            plan_b=plan_b,
            risks=risks,
            recommendations=recs,
            executive_summary=executive,
        )

    if global_dq:
        out.global_data_quality_note = " ".join(sorted(set(global_dq)))

    # Standard forecast caveat, extended when goal-value weights are missing.
    caveat = _FORECAST_CAVEAT
    if not (getattr(state, "goal_value_per_unit", None) or {}):
        caveat += _NO_VALUE_WEIGHTS_NOTE
    out.forecast_caveat = caveat

    # Populate global notes with campaign-level context.
    n_platforms = len(getattr(state, "active_platforms", []) or [])
    n_goals = len(getattr(state, "valid_goals", []) or [])
    if n_platforms > 0 and n_goals > 0:
        out.global_notes.append(
            f"Optimisation covers {n_platforms} platform{'s' if n_platforms != 1 else ''} "
            f"across {n_goals} objective{'s' if n_goals != 1 else ''}."
        )

    scalars = list((bundle.scenario_multipliers or {}).values())
    if len(scalars) >= 2:
        lo, hi = min(scalars), max(scalars)
        out.global_notes.append(
            f"Scenario budget caps range from {lo:.0%} to {hi:.0%} of the total budget."
        )

    state.module7_finalised = True
    state.current_step = max(state.current_step, 8)

    return out
