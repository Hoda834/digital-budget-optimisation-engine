"""Plan B (risk-managed alternative) must stay feasible under Module 2 floors.

Reviewer question: when the risk-managed alternative redistributes budget away
from the dominant platform, does the resulting plan still respect the
minimum-spend floors the LP was required to honour?

The concern only bites in the concentrated regime, where Plan B actually
scales the top platform down. These tests force that regime and assert the
top platform's total never falls below its own minimum-spend floor.
"""
from __future__ import annotations

from core.wizard_state import WizardState
from modules.module5 import Module5LPResult
from modules.module7 import _plan_b_risk_managed


def _lp_with(alloc, total_used):
    """Minimal Module5LPResult carrying just what Plan B reads."""
    lp = Module5LPResult.__new__(Module5LPResult)
    lp.budget_per_platform_goal = alloc
    lp.budget_per_platform = {p: sum(g.values()) for p, g in alloc.items()}
    lp.total_budget_used = total_used
    lp.objective_value = 0.0
    lp.shadow_prices = {}
    lp.binding_constraints = []
    lp.cell_bracket_cap_basis = total_used
    # _score_pg reads these to weight the redistribution; give every
    # (platform, goal) cell in the allocation a positive productivity and
    # weight so the freed budget has somewhere to go.
    lp.r_pg = {p: {g: 1.0 for g in gmap} for p, gmap in alloc.items()}
    lp.combined_weight_pg = {p: {g: 1.0 for g in gmap} for p, gmap in alloc.items()}
    return lp


def _top_total(plan, platform):
    return sum(plan.allocation.get(platform, {}).values())


def test_plan_b_respects_top_platform_floor():
    """Top platform has a floor; Plan B must not scale it below that floor."""
    state = WizardState()
    state.valid_goals = ["lg", "wt"]
    state.total_budget = 100000.0
    # Floor of 40,000 on the dominant platform.
    state.min_spend_per_platform = {"go_pmax": 40000.0}

    # Concentrated Plan A: go_pmax dominates well above the 70% cap.
    alloc_a = {
        "go_pmax": {"lg": 85000.0},
        "fb": {"lg": 10000.0},
        "ig": {"wt": 5000.0},
    }
    lp = _lp_with(alloc_a, 100000.0)

    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    assert plan_b is not None

    # 70% cap would put go_pmax at 70,000, but the run starts at 85,000 and the
    # floor is 40,000 — the floor is below the cap, so the cap governs here.
    top_b = _top_total(plan_b, "go_pmax")
    assert top_b >= 40000.0 - 1.0, f"floor violated: {top_b}"


def test_plan_b_floor_above_cap_wins():
    """When the floor exceeds the diversification cap, the floor governs."""
    state = WizardState()
    state.valid_goals = ["lg", "wt"]
    state.total_budget = 100000.0
    # Floor of 80,000 is ABOVE the 70,000 the 70% cap would impose.
    state.min_spend_per_platform = {"go_pmax": 80000.0}

    alloc_a = {
        "go_pmax": {"lg": 90000.0},
        "fb": {"lg": 6000.0},
        "ig": {"wt": 4000.0},
    }
    lp = _lp_with(alloc_a, 100000.0)

    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    assert plan_b is not None

    # The floor (80,000) is higher than the cap (70,000), so Plan B must not
    # push go_pmax below 80,000.
    top_b = _top_total(plan_b, "go_pmax")
    assert top_b >= 80000.0 - 1.0, f"floor-above-cap violated: {top_b}"


def test_plan_b_total_conserved():
    """Redistribution must not create or destroy budget."""
    state = WizardState()
    state.valid_goals = ["lg", "wt"]
    state.total_budget = 100000.0
    state.min_spend_per_platform = {"go_pmax": 30000.0}

    alloc_a = {
        "go_pmax": {"lg": 85000.0},
        "fb": {"lg": 10000.0},
        "ig": {"wt": 5000.0},
    }
    lp = _lp_with(alloc_a, 100000.0)

    plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=0.70)
    assert plan_b is not None

    total_b = sum(sum(g.values()) for g in plan_b.allocation.values())
    assert abs(total_b - 100000.0) < 1.0, f"budget not conserved: {total_b}"
