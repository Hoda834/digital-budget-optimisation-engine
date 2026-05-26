"""
Regression tests for the five bugs fixed on 2026-05-26.

Each test asserts the specific failure mode that was observed before the
fix, so a future change that re-introduces the bug fails CI.
"""
from __future__ import annotations

import pytest

from core.wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module7 import PLATFORM_NAMES, run_module7


def _run_pipeline(
    *,
    objectives,
    platforms,
    priorities,
    platform_inputs,
    total_budget=10_000.0,
    duration=30,
    test_and_learn_pct=None,
):
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=objectives,
        raw_budget=total_budget,
        raw_duration_days=duration,
        raw_test_and_learn_pct=test_and_learn_pct,
    )
    run_module2(state, selected_platforms=platforms, priorities_input=priorities)
    finalise_module3_from_inputs(state, platform_inputs=platform_inputs)
    run_module4(state)
    run_module5(state)
    return state


# ─────────────────────────────────────────────────────────────────────────
# Bug 2: zero count KPI used to raise "must be greater than zero" and block
# the entire run. It must now be accepted and silently dropped (treated as
# absent data) so a lead-only campaign with no purchase pixel can still run.
# ─────────────────────────────────────────────────────────────────────────
def test_zero_count_kpi_does_not_block_lead_only_campaign() -> None:
    state = _run_pipeline(
        objectives=["lg"],
        platforms=["fb", "go_search"],
        priorities={
            "fb":        {"priority_1": "lg", "priority_2": None},
            "go_search": {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "fb": {
                "budget": 4000.0,
                "historical_days": 30,
                # FB_LG_LEADS positive, FB_LG_PURCHASES zero (no purchase tracking)
                "kpis": {"FB_LG_LEADS": 100.0, "FB_LG_PURCHASES": 0.0},
            },
            "go_search": {
                "budget": 4000.0,
                "historical_days": 30,
                # GO_SEARCH_LG_CONVERSIONS positive, _PURCHASES zero
                "kpis": {"GO_SEARCH_LG_CONVERSIONS": 80.0, "GO_SEARCH_LG_PURCHASES": 0.0},
            },
        },
    )
    # The pipeline ran to completion — that alone proves Bug 2 is fixed.
    # As an extra check: the zero KPI must be absent from module3_data, not
    # stored as a literal zero (which would imply zero productivity).
    fb_kpis = state.module3_data["fb"]["kpis"]
    assert "FB_LG_LEADS" in fb_kpis and fb_kpis["FB_LG_LEADS"] == 100.0
    assert "FB_LG_PURCHASES" not in fb_kpis, (
        "Zero KPIs must be dropped, not stored as zero — storing zero would "
        "make the LP treat the cell as having zero productivity."
    )


# ─────────────────────────────────────────────────────────────────────────
# Bug 3: Module 7 used to surface internal platform keys ('go_search')
# instead of display names ('Google Search') because PLATFORM_NAMES was
# only populated for fb / ig / li / yt.
# ─────────────────────────────────────────────────────────────────────────
def test_module7_uses_display_names_for_all_platforms() -> None:
    # Every supported platform code must round-trip to a non-code display name.
    for code in ("fb", "ig", "li", "yt", "tt", "pt", "tw", "sn", "rd",
                 "go_search", "go_display", "go_pmax"):
        assert code in PLATFORM_NAMES, f"{code!r} missing from module7.PLATFORM_NAMES"
        name = PLATFORM_NAMES[code]
        # Display name must not be the raw code itself.
        assert name != code
        # And must not look like a code (no underscore, all caps not allowed).
        assert "_" not in name or code == "tw"  # "X (Twitter)" is allowed punctuation


def test_module7_summary_does_not_leak_platform_code() -> None:
    state = _run_pipeline(
        objectives=["lg"],
        platforms=["go_search", "fb"],
        priorities={
            "go_search": {"priority_1": "lg", "priority_2": None},
            "fb":        {"priority_1": "lg", "priority_2": None},
        },
        platform_inputs={
            "go_search": {
                "budget": 4000.0, "historical_days": 30,
                "kpis": {"GO_SEARCH_LG_CONVERSIONS": 200.0},
            },
            "fb": {
                "budget": 4000.0, "historical_days": 30,
                "kpis": {"FB_LG_LEADS": 50.0},
            },
        },
    )
    insights = run_module7(state, state.module5_scenario_bundle, {})
    for name, insight in insights.scenario_insights.items():
        summary = insight.executive_summary
        # The internal code must never appear in the user-facing summary.
        assert "go_search" not in summary, (
            f"Scenario {name!r} leaks raw platform code in summary: {summary!r}"
        )


# ─────────────────────────────────────────────────────────────────────────
# Bug 4: optimistic scenario used to scale total spend by 1.15× the user's
# declared total. Cap must hold: every scenario's lp_used + reserve must
# stay within the declared total.
# ─────────────────────────────────────────────────────────────────────────
def test_optimistic_does_not_exceed_declared_total_budget() -> None:
    state = _run_pipeline(
        objectives=["lg", "aw"],
        platforms=["fb", "li"],
        priorities={
            "fb": {"priority_1": "lg", "priority_2": "aw"},
            "li": {"priority_1": "lg", "priority_2": "aw"},
        },
        platform_inputs={
            "fb": {
                "budget": 4000.0, "historical_days": 30,
                "kpis": {"FB_LG_LEADS": 100.0, "FB_AW_REACH": 300_000.0},
            },
            "li": {
                "budget": 4000.0, "historical_days": 30,
                "kpis": {"LI_LG_LEADS": 80.0, "LI_AW_REACH": 60_000.0},
            },
        },
        total_budget=10_000.0,
        test_and_learn_pct=0.12,
    )

    declared_total = float(state.total_budget)
    bundle = state.module5_scenario_bundle

    for name, res in bundle.results_by_scenario.items():
        spent_plus_reserve = res.total_budget_used + res.test_and_learn_reserve
        assert spent_plus_reserve <= declared_total + 1e-6, (
            f"Scenario {name!r}: lp_used £{res.total_budget_used:,.2f} + "
            f"reserve £{res.test_and_learn_reserve:,.2f} = "
            f"£{spent_plus_reserve:,.2f} exceeds declared total "
            f"£{declared_total:,.2f}."
        )


# ─────────────────────────────────────────────────────────────────────────
# Bug 5: default scenario_goal_multipliers used to have conservative > 1
# and optimistic < 1 for Awareness and Engagement (a defensible-but-
# confusing convention). They must now follow the intuitive direction:
# conservative < 1 across the board, optimistic > 1 across the board.
# ─────────────────────────────────────────────────────────────────────────
def test_scenario_goal_multipliers_follow_intuitive_direction() -> None:
    # scenario_goal_multipliers is populated by complete_module2_and_advance,
    # so the pipeline must run at least through Module 2 to see the defaults.
    state = WizardState()
    complete_module1_and_advance(
        state,
        raw_objectives=["aw", "en", "wt", "lg"],
        raw_budget=10_000.0,
        raw_duration_days=30,
    )
    run_module2(
        state,
        selected_platforms=["fb", "li"],
        priorities_input={
            "fb": {"priority_1": "aw", "priority_2": "lg"},
            "li": {"priority_1": "lg", "priority_2": "en"},
        },
    )
    sgm = state.scenario_goal_multipliers
    conservative = sgm["conservative"]
    optimistic = sgm["optimistic"]

    for goal in (GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG):
        assert conservative[goal] < 1.0, (
            f"Conservative {goal!r} multiplier must be < 1.0, "
            f"got {conservative[goal]}"
        )
        assert optimistic[goal] > 1.0, (
            f"Optimistic {goal!r} multiplier must be > 1.0, "
            f"got {optimistic[goal]}"
        )
