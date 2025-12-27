from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.wizard_state import WizardState
from modules.module5 import Module5LPResult, Module5ScenarioBundle, build_module5_input_from_state, run_module5_lp_scenarios_with_policy
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
    allocation: Dict[str, Dict[str, float]] = field(default_factory=dict)
    objective_value: float = 0.0
    objective_value_raw: float = 0.0
    tradeoff_percent: Optional[float] = None


@dataclass
class Module7ScenarioInsight:
    scenario_name: str
    decision_mode: str
    classification: str
    confidence_score: int
    confidence_breakdown: Dict[str, int] = field(default_factory=dict)
    dominance_gap_percent: Optional[float] = None
    allocation_is_corner_solution: bool = False
    concentration_ratio_top_platform: float = 0.0
    dominant_platform: Optional[str] = None
    dominant_objective: Optional[str] = None
    binding_constraints: List[str] = field(default_factory=list)
    non_binding_constraints: List[str] = field(default_factory=list)
    scenario_stability_explanation: str = ""
    data_quality_note: Optional[str] = None
    data_quality_table: List[Dict[str, Any]] = field(default_factory=list)
    plan_a: PlanOutput = field(default_factory=PlanOutput)
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


def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if v != v:
        return default
    if v in (float("inf"), float("-inf")):
        return default
    return v


def _k(x: Any) -> str:
    return str(x).strip().lower()


def _pname(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return PLATFORM_NAMES.get(_k(code), str(code))


def _gname(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return GOAL_NAMES.get(_k(code), str(code))


def _platform_totals(lp: Module5LPResult) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for p, v in (lp.budget_per_platform or {}).items():
        out[_k(p)] = max(0.0, _f(v))
    if out:
        return out
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        pk = _k(p)
        out[pk] = sum(max(0.0, _f(v)) for v in (gmap or {}).values())
    return out


def _goal_totals(lp: Module5LPResult) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for gmap in (lp.budget_per_platform_goal or {}).values():
        for g, v in (gmap or {}).items():
            gk = _k(g)
            out[gk] = out.get(gk, 0.0) + max(0.0, _f(v))
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
    return max(max(0.0, v) for v in d.values()) / t


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
        if _alloc_signature(bundle.results_by_scenario[k]) != base:
            return False
    return True


def _stability_text(bundle: Module5ScenarioBundle) -> str:
    keys = list((bundle.results_by_scenario or {}).keys())
    if len(keys) <= 1:
        return "Only one scenario result is available."
    if _allocations_identical(bundle):
        return (
            "The allocation decision is stable across scenarios. Scenario multipliers scale objective values, "
            "but they do not change the optimal ranking of channel and objective options in the tested range."
        )
    return (
        "The allocation changes across scenarios. This indicates the scenario assumptions shift the ranking "
        "between channel and objective options, so the decision is scenario sensitive."
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
        label = f"Minimum spend on {PLATFORM_NAMES.get(pk, pk)}"
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
        label = f"Minimum budget for {GOAL_NAMES.get(gk, gk)}"
        if abs(actual - req) <= max(1e-6, 1e-3 * req):
            b.append(label)
        elif actual > req:
            nb.append(label)

    return b, nb


def _dominance_gap_percent(lp: Module5LPResult) -> Optional[float]:
    rpg = getattr(lp, "r_pg", None)
    wpg = getattr(lp, "combined_weight_pg", None)
    if not isinstance(rpg, dict) or not isinstance(wpg, dict):
        return None

    scores: List[float] = []
    for p, gmap in rpg.items():
        if not isinstance(gmap, dict):
            continue
        for g, r in gmap.items():
            rr = max(0.0, _f(r))
            ww = max(0.0, _f((wpg.get(p, {}) or {}).get(g, 0.0)))
            s = rr * ww
            if s > 0:
                scores.append(s)

    if len(scores) < 2:
        return None

    scores.sort(reverse=True)
    top = scores[0]
    second = scores[1]
    if top <= 0:
        return None
    gap = max(0.0, (top - second) / top) * 100.0
    return gap


def _classification(bundle: Module5ScenarioBundle, lp: Module5LPResult) -> str:
    if not _allocations_identical(bundle):
        return "Scenario-sensitive"
    pt = _platform_totals(lp)
    pr = _ratio(pt)
    nz = _nonzero_allocations(lp)
    if pr >= 0.80 or nz <= 2:
        return "Corner-dominant"
    if nz >= 3 and pr <= 0.70:
        return "Balanced"
    return "Unclear"


def _forecast_table(fc: Optional[Module6Result]) -> List[Dict[str, Any]]:
    if fc is None:
        return []
    rows: List[Dict[str, Any]] = []
    for r in (fc.rows or []):
        rows.append(
            {
                "Platform": PLATFORM_NAMES.get(_k(r.platform), str(r.platform)),
                "Objective": GOAL_NAMES.get(_k(r.objective), str(r.objective)),
                "KPI": str(r.kpi_name),
                "Allocated Budget": _f(r.allocated_budget),
                "Predicted KPI": _f(r.predicted_kpi),
                "KPI per Budget": _f(r.ratio_kpi_per_budget),
            }
        )
    rows.sort(key=lambda x: x.get("Allocated Budget", 0.0), reverse=True)
    return rows


def _data_quality_note(lp: Module5LPResult, fc: Optional[Module6Result]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    issues: List[str] = []
    table = _forecast_table(fc)

    if fc is None or not getattr(fc, "rows", None):
        issues.append("No forecast rows are available for this scenario.")
        return (" ".join(issues), table)

    di = getattr(fc, "diagnostics", None)
    if di is not None:
        covered = int(getattr(di, "covered_platform_goal_pairs", 0) or 0)
        with_budget = int(getattr(di, "total_platform_goal_pairs_with_budget", 0) or 0)
        if with_budget > 0:
            cov = covered / float(with_budget)
            if cov < 0.70:
                issues.append("Forecast coverage is below 70 percent, which can reduce reliability.")

    small_count = 0
    total = 0
    for row in table:
        total += 1
        if _f(row.get("Predicted KPI", 0.0)) < 5.0:
            small_count += 1
            row["Flag"] = "Low or scaled"
        else:
            row["Flag"] = "OK"

    if total > 0 and (small_count / float(total)) >= 0.50:
        issues.append("Many forecast KPI values are very small. Check units and scaling in the historical inputs.")

    rpg = getattr(lp, "r_pg", None)
    if not isinstance(rpg, dict) or not rpg:
        issues.append("Productivity ratios are missing in the LP result.")

    note = " ".join(issues) if issues else None
    return (note, table)


def _confidence_breakdown(
    lp: Module5LPResult,
    bundle: Module5ScenarioBundle,
    fc: Optional[Module6Result],
    dq_note: Optional[str],
) -> Tuple[int, Dict[str, int]]:
    breakdown: Dict[str, int] = {}

    pr = _ratio(_platform_totals(lp))
    if pr >= 0.90:
        concentration = 55
    elif pr >= 0.80:
        concentration = 70
    elif pr >= 0.70:
        concentration = 82
    else:
        concentration = 92
    breakdown["Concentration"] = concentration

    stability = 95 if _allocations_identical(bundle) else 70
    breakdown["Stability"] = stability

    coverage = 65
    if fc is not None and getattr(fc, "diagnostics", None) is not None:
        di = fc.diagnostics
        covered = int(getattr(di, "covered_platform_goal_pairs", 0) or 0)
        with_budget = int(getattr(di, "total_platform_goal_pairs_with_budget", 0) or 0)
        if with_budget > 0:
            cov = covered / float(with_budget)
            if cov >= 0.90:
                coverage = 95
            elif cov >= 0.80:
                coverage = 85
            elif cov >= 0.70:
                coverage = 75
            else:
                coverage = 60
    breakdown["Forecast coverage"] = coverage

    data_quality = 90
    if dq_note:
        data_quality = 70
    breakdown["Data quality"] = data_quality

    score = int(round(0.35 * concentration + 0.20 * stability + 0.25 * coverage + 0.20 * data_quality))
    if score < 40:
        score = 40
    if score > 100:
        score = 100
    return score, breakdown


def _plan_from_lp(lp: Module5LPResult) -> PlanOutput:
    alloc: Dict[str, Dict[str, float]] = {}
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        alloc[_k(p)] = {}
        for g, v in (gmap or {}).items():
            alloc[_k(p)][_k(g)] = max(0.0, _f(v))
    return PlanOutput(
        allocation=alloc,
        objective_value=_f(getattr(lp, "objective_value", 0.0)),
        objective_value_raw=_f(getattr(lp, "objective_value_raw", 0.0)),
        tradeoff_percent=None,
    )


def _plan_b_from_reoptimisation(
    state: WizardState,
    scenario_name: str,
    max_platform_share: float,
) -> Optional[Module5LPResult]:
    try:
        input_data = build_module5_input_from_state(state)
        bundle_b = run_module5_lp_scenarios_with_policy(input_data, max_platform_share=max_platform_share)
    except Exception:
        return None
    return bundle_b.results_by_scenario.get(scenario_name)


def _risks_recs(
    classification: str,
    confidence: int,
    dominance_gap: Optional[float],
    stability_text: str,
    dq_note: Optional[str],
    plan_b_exists: bool,
) -> Tuple[List[str], List[str]]:
    risks: List[str] = []
    recs: List[str] = []

    if classification == "Corner-dominant":
        risks.append("Budget is highly concentrated, which increases dependency on a single channel.")
        if plan_b_exists:
            recs.append("Use Plan B if you want to reduce concentration risk while staying close to optimal.")
        else:
            recs.append("If concentration is not acceptable, add a platform cap policy and re-optimise.")

    if classification == "Scenario-sensitive":
        risks.append("The recommended allocation changes across scenarios, which suggests higher uncertainty.")
        recs.append("Hold a contingency budget portion and review performance after a short test cycle.")

    if dominance_gap is not None and dominance_gap >= 40.0:
        recs.append(f"Ranking is strongly dominated. The top lane outperforms the runner up by about {int(round(dominance_gap))} percent.")

    if dq_note:
        risks.append("Data quality flags suggest the outputs should be treated as conditional.")
        recs.append("Align KPI units and time windows across platforms and re-run the optimiser.")

    if confidence <= 55:
        risks.append("Overall confidence is moderate to low.")
        recs.append("Validate with a short pilot before committing the full budget.")

    recs.append(stability_text)

    return risks, recs


def _executive_summary(
    scenario_display: str,
    classification: str,
    confidence: int,
    lp: Module5LPResult,
    bindings: List[str],
    dominance_gap: Optional[float],
    dq_note: Optional[str],
) -> str:
    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    dp = _dominant(pt)
    dg = _dominant(gt)

    pr = int(round(_ratio(pt) * 100.0))
    gr = int(round(_ratio(gt) * 100.0))

    lane = []
    if dp:
        lane.append(_pname(dp) or "")
    if dg:
        lane.append(_gname(dg) or "")
    lane_txt = " and ".join([x for x in lane if x]) or "no dominant lane"

    parts: List[str] = []
    parts.append(f"{scenario_display}: {classification} decision with confidence {confidence}/100.")
    parts.append(f"The optimiser concentrates spend around {lane_txt}.")
    if dp:
        parts.append(f"Top platform share is about {pr} percent.")
    if dg:
        parts.append(f"Top objective share is about {gr} percent.")
    if dominance_gap is not None:
        parts.append(f"Productivity dominance gap is about {int(round(dominance_gap))} percent.")
    if bindings:
        parts.append("Binding constraints include " + ", ".join(bindings[:3]) + ".")
    if dq_note:
        parts.append("Data quality note: " + dq_note)
    return " ".join(parts)


def run_module7(
    state: WizardState,
    bundle: Module5ScenarioBundle,
    forecasts: Optional[Dict[str, Module6Result]] = None,
    decision_mode: str = "Performance first",
    *,
    max_platform_share_plan_b: float = 0.70,
) -> Module7BundleInsight:
    out = Module7BundleInsight()

    stability_text = _stability_text(bundle)
    out.global_stability_explanation = stability_text

    global_dq: List[str] = []

    for s_name, lp in (bundle.results_by_scenario or {}).items():
        fc = forecasts.get(s_name) if forecasts else None

        classification = _classification(bundle, lp)
        dq_note, dq_table = _data_quality_note(lp, fc)
        confidence, breakdown = _confidence_breakdown(lp, bundle, fc, dq_note)

        bindings, non_bindings = _constraints(state, lp)
        pt = _platform_totals(lp)
        gt = _goal_totals(lp)
        dp = _dominant(pt)
        dg = _dominant(gt)
        conc = _ratio(pt)
        dominance_gap = _dominance_gap_percent(lp)

        plan_a = _plan_from_lp(lp)

        plan_b: Optional[PlanOutput] = None
        plan_b_exists = False

        mode = decision_mode.strip().lower()
        want_b = (mode == "risk managed") or (classification == "Corner-dominant")
        if want_b:
            lp_b = _plan_b_from_reoptimisation(state, str(s_name), float(max_platform_share_plan_b))
            if lp_b is not None:
                plan_b_exists = True
                plan_b = _plan_from_lp(lp_b)
                if plan_a.objective_value > 1e-9:
                    plan_b.tradeoff_percent = max(0.0, (plan_a.objective_value - plan_b.objective_value) / plan_a.objective_value) * 100.0

        risks, recs = _risks_recs(classification, confidence, dominance_gap, stability_text, dq_note, plan_b_exists)

        scenario_display = f"Scenario {_k(s_name).capitalize()}"
        executive = _executive_summary(
            scenario_display=scenario_display,
            classification=classification,
            confidence=confidence,
            lp=lp,
            bindings=bindings,
            dominance_gap=dominance_gap,
            dq_note=dq_note,
        )

        if dq_note:
            global_dq.append(dq_note)

        out.scenario_insights[str(s_name)] = Module7ScenarioInsight(
            scenario_name=str(s_name),
            decision_mode=decision_mode,
            classification=classification,
            confidence_score=confidence,
            confidence_breakdown=breakdown,
            dominance_gap_percent=dominance_gap,
            allocation_is_corner_solution=_corner(lp),
            concentration_ratio_top_platform=float(conc),
            dominant_platform=_pname(dp),
            dominant_objective=_gname(dg),
            binding_constraints=bindings,
            non_binding_constraints=non_bindings,
            scenario_stability_explanation=stability_text,
            data_quality_note=dq_note,
            data_quality_table=dq_table,
            plan_a=plan_a,
            plan_b=plan_b,
            risks=risks,
            recommendations=recs,
            executive_summary=executive,
        )

    if global_dq:
        out.global_data_quality_note = " ".join(sorted(set(global_dq)))

    return out
