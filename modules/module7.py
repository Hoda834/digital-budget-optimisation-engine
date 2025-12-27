from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.wizard_state import WizardState
from modules.module5 import Module5LPResult, Module5ScenarioBundle
from modules.module6 import Module6Result


@dataclass
class Module7ScenarioInsight:
    scenario_name: str
    allocation_is_corner_solution: bool
    concentration_ratio_top_platform: float
    dominant_platform: Optional[str]
    dominant_objective: Optional[str]
    binding_constraints: List[str] = field(default_factory=list)
    non_binding_constraints: List[str] = field(default_factory=list)
    scenario_stability_explanation: str = ""
    risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    executive_summary: str = ""


@dataclass
class Module7BundleInsight:
    scenario_insights: Dict[str, Module7ScenarioInsight] = field(default_factory=dict)
    global_stability_explanation: str = ""
    global_notes: List[str] = field(default_factory=list)


def _f(x: object) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return v


def _n(x: object) -> str:
    return str(x).strip().lower()


def _platform_totals(lp: Module5LPResult) -> Dict[str, float]:
    if lp.budget_per_platform:
        return {_n(k): max(0.0, _f(v)) for k, v in lp.budget_per_platform.items()}
    out: Dict[str, float] = {}
    for p, gmap in (lp.budget_per_platform_goal or {}).items():
        s = 0.0
        for v in (gmap or {}).values():
            s += max(0.0, _f(v))
        out[_n(p)] = s
    return out


def _goal_totals(lp: Module5LPResult) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for gmap in (lp.budget_per_platform_goal or {}).values():
        for g, v in (gmap or {}).items():
            gg = _n(g)
            out[gg] = out.get(gg, 0.0) + max(0.0, _f(v))
    return out


def _dominant(d: Dict[str, float]) -> Optional[str]:
    if not d:
        return None
    k, v = max(d.items(), key=lambda x: x[1])
    return k if v > 0 else None


def _ratio(d: Dict[str, float]) -> float:
    t = sum(max(0.0, v) for v in d.values())
    if t <= 0:
        return 0.0
    return max(max(0.0, v) for v in d.values()) / t


def _corner(lp: Module5LPResult) -> bool:
    c = 0
    for gmap in (lp.budget_per_platform_goal or {}).values():
        for v in (gmap or {}).values():
            if _f(v) > 1e-6:
                c += 1
    return c <= 2


def _constraints(state: WizardState, lp: Module5LPResult) -> Tuple[List[str], List[str]]:
    b: List[str] = []
    nb: List[str] = []

    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    for p, m in (state.min_spend_per_platform or {}).items():
        r = max(0.0, _f(m))
        a = max(0.0, pt.get(_n(p), 0.0))
        if r <= 0:
            continue
        if abs(a - r) <= max(1e-6, 1e-3 * r):
            b.append(f"Minimum spend on {p}")
        elif a > r:
            nb.append(f"Minimum spend on {p}")

    for g, m in (state.min_budget_per_goal or {}).items():
        r = max(0.0, _f(m))
        a = max(0.0, gt.get(_n(g), 0.0))
        if r <= 0:
            continue
        if abs(a - r) <= max(1e-6, 1e-3 * r):
            b.append(f"Minimum budget for {g}")
        elif a > r:
            nb.append(f"Minimum budget for {g}")

    return b, nb


def _stability(bundle: Module5ScenarioBundle) -> str:
    keys = list(bundle.results_by_scenario.keys())
    if len(keys) <= 1:
        return "Single scenario result only."

    base = bundle.results_by_scenario[keys[0]].budget_per_platform_goal or {}

    for k in keys[1:]:
        cur = bundle.results_by_scenario[k].budget_per_platform_goal or {}
        if cur != base:
            return "Allocations change across scenarios."
    return "Allocations are stable across scenarios."


def _risks_recs(lp: Module5LPResult, fc: Optional[Module6Result]) -> Tuple[List[str], List[str]]:
    risks: List[str] = []
    recs: List[str] = []

    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    pr = _ratio(pt)
    gr = _ratio(gt)

    if pr >= 0.8:
        risks.append("High platform concentration risk.")
        recs.append("Consider introducing a soft platform cap.")

    if gr >= 0.8:
        risks.append("Single objective dominance risk.")
        recs.append("Consider minimum allocation for secondary objectives.")

    if fc and fc.rows:
        top = max(fc.rows, key=lambda r: _f(getattr(r, "predicted_kpi", 0.0)))
        recs.append(f"Operational focus on {top.platform} for {top.objective}.")

    return risks, recs


def _summary(
    scenario: str,
    lp: Module5LPResult,
    stab: str,
    bc: List[str],
) -> str:
    pt = _platform_totals(lp)
    gt = _goal_totals(lp)

    dp = _dominant(pt)
    dg = _dominant(gt)

    pr = int(_ratio(pt) * 100)
    gr = int(_ratio(gt) * 100)

    ptxt = f"{dp} receives about {pr}%" if dp else "No dominant platform"
    gtxt = f"{dg} receives about {gr}%" if dg else "No dominant objective"

    ctxt = ""
    if bc:
        ctxt = " Binding constraints affected the result."

    return f"Scenario {scenario}: {ptxt}, {gtxt}.{ctxt} {stab}"


def run_module7(
    state: WizardState,
    bundle: Module5ScenarioBundle,
    forecasts: Optional[Dict[str, Module6Result]] = None,
) -> Module7BundleInsight:
    out = Module7BundleInsight()
    stab = _stability(bundle)
    out.global_stability_explanation = stab

    for s, lp in bundle.results_by_scenario.items():
        fc = forecasts.get(s) if forecasts else None

        bc, nbc = _constraints(state, lp)
        risks, recs = _risks_recs(lp, fc)

        ins = Module7ScenarioInsight(
            scenario_name=s,
            allocation_is_corner_solution=_corner(lp),
            concentration_ratio_top_platform=_ratio(_platform_totals(lp)),
            dominant_platform=_dominant(_platform_totals(lp)),
            dominant_objective=_dominant(_goal_totals(lp)),
            binding_constraints=bc,
            non_binding_constraints=nbc,
            scenario_stability_explanation=stab,
            risks=risks,
            recommendations=recs,
            executive_summary=_summary(s, lp, stab, bc),
        )

        out.scenario_insights[s] = ins

    return out
