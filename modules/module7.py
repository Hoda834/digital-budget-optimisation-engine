from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.wizard_state import WizardState
from core.kpi_config import KIND_RATE
from modules.module5 import Module5LPResult, Module5ScenarioBundle, YIELD_BRACKETS
from modules.module6 import Module6Result


PLATFORM_NAMES: Dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
    "tt": "TikTok",
    "pt": "Pinterest",
    "tw": "X (Twitter)",
    "sn": "Snapchat",
    "rd": "Reddit",
    "go_search": "Google Search",
    "go_display": "Google Display",
    "go_pmax": "Google Performance Max",
}

GOAL_NAMES: Dict[str, str] = {
    "aw": "Awareness",
    "en": "Engagement",
    "wt": "Website Traffic",
    "lg": "Lead Generation",
}


@dataclass(frozen=True)
class Module7Policy:
    """Tunable thresholds for Module 7's classification, confidence scoring,
    and Plan B construction.  Defaults preserve the original hardcoded values
    so existing callers see no behaviour change.

    Pass a custom instance to ``run_module7`` to make the interpretation layer
    sensitive to a different business policy — e.g. a tighter
    ``corner_concentration`` for risk-averse organisations, or a lower
    ``plan_b_top_platform_cap`` for clients that demand more diversification.
    """
    # ── Classification thresholds ───────────────────────────────────────────
    # Top-platform share at or above which we call the allocation
    # "Corner-dominant" (extreme concentration on one platform).
    corner_concentration: float = 0.90
    # Top-platform share at or below which a multi-platform allocation
    # counts as "Balanced" (between this and corner_concentration is
    # "Concentrated").
    balanced_concentration: float = 0.75
    # Maximum number of funded (>0) platform-goal cells for a corner solution.
    corner_max_nonzero_cells: int = 2

    # ── Confidence-score penalties ─────────────────────────────────────────
    # Concentration breakpoints and the deductions applied at each.
    confidence_high_concentration: float = 0.90
    confidence_high_concentration_penalty: int = 20
    confidence_med_concentration: float = 0.80
    confidence_med_concentration_penalty: int = 12
    confidence_few_cells_penalty: int = 8
    confidence_unstable_scenarios_penalty: int = 10
    confidence_missing_forecast_penalty: int = 18
    confidence_dq_issue_penalty: int = 12
    confidence_floor: int = 40

    # ── Data-quality heuristics ────────────────────────────────────────────
    # Fraction of count-KPI forecast rows below dq_small_kpi_threshold that
    # triggers the "small values" data-quality flag.
    dq_small_kpi_share: float = 0.50
    dq_small_kpi_threshold: float = 5.0

    # ── Plan B (risk-managed) ──────────────────────────────────────────────
    # Cap on the top platform's share when constructing the risk-managed
    # alternative plan.  Lower = more diversification, larger trade-off.
    plan_b_top_platform_cap: float = 0.70
    # Trade-off (%) above which Plan B is worth surfacing prominently.
    plan_b_meaningful_tradeoff_pct: float = 5.0


_DEFAULT_POLICY = Module7Policy()


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
    "creative fatigue. The historical KPIs also reflect each platform's own "
    "(typically last-click) attribution — Facebook tends to over-claim leads "
    "that Search also influenced, Search tends to over-claim conversions that "
    "brand awareness created.  Incrementality is not modelled.  Treat the "
    "productivity ratios as upper bounds, not measurements, and validate "
    "against current platform benchmarks before committing the full budget."
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


def _classification(
    bundle: Module5ScenarioBundle,
    lp: Module5LPResult,
    policy: Module7Policy = _DEFAULT_POLICY,
) -> str:
    if not _allocations_identical(bundle):
        return "Scenario-sensitive"
    pt = _platform_totals(lp)
    pr = _ratio(pt)
    nz = _nonzero_allocations(lp)
    # Corner-dominant: a literal corner solution (few funded cells) or extreme
    # concentration. A 3-platform 80/10/10 split does NOT qualify under the
    # default 0.90 corner_concentration threshold.
    if nz <= policy.corner_max_nonzero_cells or pr >= policy.corner_concentration:
        return "Corner-dominant"
    if nz >= 3 and pr <= policy.balanced_concentration:
        return "Balanced"
    return "Concentrated"


def _data_quality_note(
    lp: Module5LPResult,
    fc: Optional[Module6Result],
    policy: Module7Policy = _DEFAULT_POLICY,
) -> Optional[str]:
    issues: List[str] = []

    if fc is None or not getattr(fc, "rows", None):
        issues.append("No forecast rows are available for this scenario.")
    else:
        small = 0
        total = 0
        for r in fc.rows:
            # Rate KPIs would be naturally in [0, 1] — applying a count-KPI
            # "small value" threshold would always fire falsely. No canonical KPI
            # is a rate today, but this guard keeps the threshold honest if one
            # is re-introduced.
            if getattr(r, "kpi_kind", None) == KIND_RATE:
                continue
            total += 1
            if _f(getattr(r, "predicted_kpi", 0.0)) < policy.dq_small_kpi_threshold:
                small += 1
        if total > 0 and small / float(total) >= policy.dq_small_kpi_share:
            issues.append("Many forecast KPI values are very small, which may indicate unit or scaling issues in the input data.")

    rpg = getattr(lp, "r_pg", None)
    if not isinstance(rpg, dict) or not rpg:
        issues.append("Productivity ratios are missing in the LP result.")

    if issues:
        return " ".join(issues)

    return None


def _confidence(
    lp: Module5LPResult,
    bundle: Module5ScenarioBundle,
    fc: Optional[Module6Result],
    dq_note: Optional[str],
    policy: Module7Policy = _DEFAULT_POLICY,
) -> int:
    score = 100

    pt = _platform_totals(lp)
    pr = _ratio(pt)
    nz = _nonzero_allocations(lp)

    if pr >= policy.confidence_high_concentration:
        score -= policy.confidence_high_concentration_penalty
    elif pr >= policy.confidence_med_concentration:
        score -= policy.confidence_med_concentration_penalty

    if nz <= policy.corner_max_nonzero_cells:
        score -= policy.confidence_few_cells_penalty

    if not _allocations_identical(bundle):
        score -= policy.confidence_unstable_scenarios_penalty

    if fc is None or not getattr(fc, "rows", None):
        # Missing forecast is a single root cause — don't also deduct for the
        # dq_note that was itself triggered by the missing forecast.
        score -= policy.confidence_missing_forecast_penalty
    elif dq_note:
        # Only penalise for data-quality issues when the forecast actually exists.
        score -= policy.confidence_dq_issue_penalty

    if score < policy.confidence_floor:
        score = policy.confidence_floor
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
    """Score an allocation using the same yield-bracket schedule as the LP.

    For each (platform, goal) cell, splits the allocated budget across three
    diminishing-returns brackets with caps (0.25, 0.35, 0.40) of the
    base LP cap (the post-carve-out, pre-scenario anchor) and yield
    multipliers (1.00, 0.65, 0.35). Using the same schedule for
    both Plan A and Plan B makes their reported objectives directly
    comparable, so the trade-off percentage reflects a real sacrifice
    rather than an artefact of two different scoring formulas.

    Anchoring the brackets to ``cell_bracket_cap_basis`` (rather than
    ``total_budget_used``) is what makes the estimator match the LP on
    non-base scenarios: the LP solves with brackets anchored to the
    same base across conservative/base/optimistic, so the estimator
    must too — otherwise a scenario that under-spends would see its
    bracket schedule scale down with the spend, producing a different
    yield distribution from the one the LP actually optimised.
    """
    from modules.module5 import YIELD_BRACKETS

    scores = _score_pg(lp_ref)
    scale = _objective_scale(lp_ref)
    cell_cap_basis = _f(getattr(lp_ref, "cell_bracket_cap_basis", 0.0))
    if cell_cap_basis <= 0.0:
        cell_cap_basis = max(1.0, _f(getattr(lp_ref, "total_budget_used", 0.0)))
    bracket_caps = [frac * cell_cap_basis for frac, _y in YIELD_BRACKETS]
    bracket_yields = [y for _frac, y in YIELD_BRACKETS]

    raw = 0.0
    for p, gmap in allocation.items():
        pk = _k(p)
        for g, b in (gmap or {}).items():
            gk = _k(g)
            spend = max(0.0, _f(b))
            base_score = max(0.0, _f((scores.get(pk, {}) or {}).get(gk, 0.0)))
            if spend <= 0.0 or base_score <= 0.0:
                continue
            remaining = spend
            for cap, yld in zip(bracket_caps, bracket_yields):
                fill = min(remaining, cap)
                raw += fill * base_score * yld
                remaining -= fill
                if remaining <= 0.0:
                    break
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

    # Score Plan A through the same bracket-aware estimator as Plan B so
    # the trade-off in _plan_b_risk_managed is apples-to-apples. Reading
    # lp.objective_value directly here would be bracket-aware too, but mixing
    # the two formulas produced cases where Plan B's redistributed-to-bracket-1
    # allocation appeared to beat Plan A's bracket-spanning LP optimum.
    return PlanOutput(
        allocation=alloc,
        objective_value_estimate=_estimate_objective_value(alloc, lp),
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
    policy: Module7Policy = _DEFAULT_POLICY,
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

    if plan_b and plan_b.tradeoff_percent is not None and plan_b.tradeoff_percent >= policy.plan_b_meaningful_tradeoff_pct:
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
    policy: Optional[Module7Policy] = None,
) -> Module7BundleInsight:
    pol = policy or _DEFAULT_POLICY
    out = Module7BundleInsight()

    stability_text = _stability_text(bundle)
    out.global_stability_explanation = stability_text

    global_dq: List[str] = []

    for s_name, lp in (bundle.results_by_scenario or {}).items():
        fc = forecasts.get(s_name) if forecasts else None

        classification = _classification(bundle, lp, pol)
        dq_note = _data_quality_note(lp, fc, pol)
        confidence = _confidence(lp, bundle, fc, dq_note, pol)

        bindings, non_bindings = _constraints(state, lp)

        pt = _platform_totals(lp)
        gt = _goal_totals(lp)
        dp = _dominant(pt)
        dg = _dominant(gt)
        conc = _ratio(pt)

        plan_a = _plan_a(lp)
        plan_b = None
        if decision_mode.strip().lower() == "risk managed":
            plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=pol.plan_b_top_platform_cap)
        elif classification == "Corner-dominant":
            plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=pol.plan_b_top_platform_cap)

        risks, recs = _risks_recs(classification, confidence, stability_text, dq_note, plan_b, pol)

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
