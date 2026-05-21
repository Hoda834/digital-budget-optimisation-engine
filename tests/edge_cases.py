"""Edge-case audit — exercises corners of the API to surface bugs that the
happy-path smoke tests miss.

Categories covered:
  1. CSV parsing edge cases (encoding, delimiters, malformed cells)
  2. Custom platform edge cases (rate-only, duplicates, special inputs)
  3. State machine boundaries (re-finalise guards, step rollback)
  4. Iterative re-solve edge cases (infeasibility, floor invalidation)
  5. Module 1 input boundary values (carve-out, seasonality, goal values)
  6. Module 5 / Monte Carlo edge cases (small budget, single platform)
  7. Catalog & lookup completeness for every built-in platform
"""
from __future__ import annotations

import pytest

from core.wizard_state import (
    WizardState, ALLOWED_PLATFORMS,
    GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG,
)
from core.kpi_config import KPI_CONFIG, effective_kpi_config, get_kpi_rows
from core.csv_import import parse_platform_csv, SUPPORTED_PLATFORMS
from modules.module1 import (
    complete_module1_and_advance, Module1ValidationError,
)
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import (
    run_module5, run_module5_montecarlo, build_module5_input_from_state,
    Module5ValidationError, PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH,
)
from modules.module6 import run_module6
from modules.module7 import run_module7


# ─────────────────────────────────────────────────────────────────────────────
# Group 1: CSV parsing edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_csv_empty_returns_error():
    assert "error" in parse_platform_csv(b"", "fb")


def test_csv_only_headers_returns_error():
    assert "error" in parse_platform_csv(b"Reach,Impressions\n", "fb")


def test_csv_semicolon_delimiter_is_sniffed():
    """European locale exports use ; as delimiter."""
    csv = b"Reach;Impressions;Amount Spent\n100000;200000;1000\n"
    result = parse_platform_csv(csv, "fb")
    assert "error" not in result
    assert result["budget"] == pytest.approx(1000.0)
    assert result["kpis"]["FB_AW_REACH"] == pytest.approx(100000.0)


def test_csv_with_bom_prefix():
    """Google sometimes prefixes UTF-8 BOM; should be stripped."""
    csv = "﻿Impressions,Clicks,Conversions,Cost\n1000,50,5,200\n".encode("utf-8")
    result = parse_platform_csv(csv, "go")
    assert "error" not in result
    assert result["kpis"].get("GO_LG_CONVERSIONS") == pytest.approx(5.0)


def test_csv_latin1_encoding_falls_back():
    """Some Windows exports use Latin-1 not UTF-8."""
    # 'Coût' (cost in French) — non-ASCII in Latin-1
    csv = "Impressions,Clicks,Conversions,Cost\n1000,50,5,200\n".encode("latin-1")
    result = parse_platform_csv(csv, "go")
    assert "error" not in result


def test_csv_with_blanks_and_dashes():
    """Cells like '--' or 'N/A' shouldn't crash; treated as missing."""
    csv = b"Reach,Impressions,Amount Spent\n--,200000,1000\nN/A,100000,500\n"
    result = parse_platform_csv(csv, "fb")
    # No reach values → no FB_AW_REACH; impressions still aggregated
    assert "FB_AW_REACH" not in result["kpis"]
    assert result["kpis"]["FB_AW_IMPRESSION"] == pytest.approx(300000.0)


def test_csv_with_currency_symbols():
    """Spend cells like '£1,200.50' should parse to 1200.50."""
    csv = b'Reach,Amount Spent\n100000,"\xc2\xa31,200.50"\n'
    result = parse_platform_csv(csv, "fb")
    assert result["budget"] == pytest.approx(1200.50)


def test_csv_google_ctr_decimal_form():
    """When Google exports CTR as decimal (0.045), parse to 0.045, not 0.00045."""
    csv = b"Impressions,Clicks,CTR,Conversions,Cost\n100000,4500,0.045,300,1000\n"
    result = parse_platform_csv(csv, "go")
    # CTR provided as decimal — should remain 0.045 (NOT divide by 100 again)
    assert result["kpis"]["GO_EN_CTR"] == pytest.approx(0.045)


def test_csv_thousand_separator_in_numbers():
    csv = b'Reach,Impressions,Amount Spent\n"200,000","1,500,000","3,200.50"\n'
    result = parse_platform_csv(csv, "fb")
    assert result["kpis"]["FB_AW_REACH"] == pytest.approx(200000.0)
    assert result["budget"] == pytest.approx(3200.50)


def test_csv_extra_irrelevant_columns_ignored():
    csv = b"Date,Account,Reach,Impressions,Amount Spent,Ad Set,Region\n"
    csv += b"2024-01-01,ACME,100000,200000,1000,Set 1,UK\n"
    result = parse_platform_csv(csv, "fb")
    assert result["kpis"]["FB_AW_REACH"] == pytest.approx(100000.0)


def test_csv_supported_platforms_covers_key_marketers():
    """The platforms a real marketer most needs CSV import for must be supported."""
    for p in ("fb", "ig", "li", "go", "tt", "yt"):
        assert p in SUPPORTED_PLATFORMS, f"{p!r} missing from CSV support"


def test_csv_google_ctr_bare_percentage_form():
    """Google exports sometimes show CTR as '4.5' (meaning 4.5%) without
    the '%' suffix.  The parser needs to recognise this — a bare 4.5
    cannot mean 'CTR = 450%' literally.  Rate KPIs must be normalised
    into [0, 1] regardless of presentation."""
    csv = b"Impressions,Clicks,CTR,Conversions,Cost\n100000,4500,4.50,300,1000\n"
    result = parse_platform_csv(csv, "go")
    # Should be 0.045 (CTR of 4.5%), not 4.5
    assert result["kpis"]["GO_EN_CTR"] == pytest.approx(0.045), (
        f"Bare '4.50' in CTR column should normalise to 0.045, got "
        f"{result['kpis']['GO_EN_CTR']}"
    )


def test_csv_engagement_rate_bare_percentage_form():
    """Same problem on TikTok/IG/LI: CTR/ER reported as a percentage
    without the % sign should not produce a 'rate' value > 1."""
    csv = b"Impressions,Engagement rate,Cost\n100000,5.5,1000\n"
    result = parse_platform_csv(csv, "tt")
    if "TT_EN_ENGRATERATE" in result["kpis"]:
        assert result["kpis"]["TT_EN_ENGRATERATE"] <= 1.0, (
            f"Rate KPIs must be in [0,1]; got {result['kpis']['TT_EN_ENGRATERATE']}"
        )


def test_csv_with_totals_row_doesnt_double_count():
    """Google's standard export appends a 'Total' row that contains the sum
    of all campaign rows.  If we naively sum, we double the spend."""
    csv = (
        b"Campaign,Impressions,Clicks,Conversions,Cost\n"
        b"Camp A,500000,2000,100,500\n"
        b"Camp B,500000,2000,100,500\n"
        b'"Total --",1000000,4000,200,1000\n'
    )
    result = parse_platform_csv(csv, "go")
    # Expected spend is 500 + 500 = 1000 (NOT 1000 + 1000 = 2000 from
    # naively summing the Total row too).
    assert result["budget"] == pytest.approx(1000.0), (
        f"Total row was summed into the budget: expected £1000, got £{result['budget']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Group 2: Custom platform edge cases
# ─────────────────────────────────────────────────────────────────────────────

def _basic_state_with_goals():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["aw", "lg"], raw_budget=10000.0)
    return s


def test_custom_platform_rate_only_kpis():
    """A custom platform defining only rate KPIs should still work end-to-end."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["en"], raw_budget=10000.0,
                                 raw_duration_days=30)
    s.register_custom_platform(
        code="aa", label="AlphaAds",
        kpis=[{"goal": "en", "var": "AA_EN_RATE",
               "kpi_label": "Engagement Rate", "kind": "rate"}],
    )
    run_module2(s, selected_platforms=["aa", "fb"],
                priorities_input={
                    "aa": {"priority_1": "en", "priority_2": None},
                    "fb": {"priority_1": "en", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "aa": {"budget": 3000.0, "historical_days": 30,
               "kpis": {"AA_EN_RATE": 0.05}},
        "fb": {"budget": 3000.0, "historical_days": 30,
               "kpis": {"FB_EN_ENGAGEMENT": 5000.0}},
    })
    run_module4(s)
    run_module5(s)
    # Both platforms should have non-zero r_pg for EN
    bundle = s.module5_scenario_bundle
    base = bundle.results_by_scenario["base"]
    assert base.r_pg.get("aa", {}).get("en", 0.0) > 0


def test_custom_platform_special_chars_in_code_rejected():
    s = _basic_state_with_goals()
    for bad in ("my-platform", "x!", "TT", "abcdefg"):  # too long, mixed case, dashes
        with pytest.raises(ValueError):
            s.register_custom_platform(
                code=bad, label="X",
                kpis=[{"goal": "lg", "var": "X_LG", "kpi_label": "x", "kind": "count"}],
            )


def test_custom_platform_empty_kpi_list_rejected():
    s = _basic_state_with_goals()
    with pytest.raises(ValueError):
        s.register_custom_platform(code="yz", label="MyChannel", kpis=[])


def test_custom_platform_kpi_with_invalid_goal_rejected():
    s = _basic_state_with_goals()
    with pytest.raises(ValueError):
        s.register_custom_platform(
            code="yz", label="MyChannel",
            kpis=[{"goal": "nonsense", "var": "Y_X",
                   "kpi_label": "x", "kind": "count"}],
        )


def test_custom_platform_two_kpis_same_var_rejected():
    s = _basic_state_with_goals()
    with pytest.raises(ValueError):
        s.register_custom_platform(
            code="yz", label="MyChannel",
            kpis=[
                {"goal": "lg", "var": "YZ_X", "kpi_label": "x", "kind": "count"},
                {"goal": "aw", "var": "YZ_X", "kpi_label": "y", "kind": "count"},
            ],
        )


def test_custom_platform_unselected_doesnt_break_pipeline():
    """Register a custom platform but don't actually select it in Module 2.
    The pipeline should ignore it cleanly."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    s.register_custom_platform(
        code="yz", label="MyChannel",
        kpis=[{"goal": "lg", "var": "YZ_LG", "kpi_label": "Leads", "kind": "count"}],
    )
    run_module2(s, selected_platforms=["fb", "li"],  # Note: yz NOT selected
                priorities_input={
                    "fb": {"priority_1": "lg", "priority_2": None},
                    "li": {"priority_1": "lg", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
        "li": {"budget": 3000.0, "historical_days": 30, "kpis": {"LI_LG_LEADS": 40.0}},
    })
    run_module4(s)
    run_module5(s)
    assert "yz" not in s.active_platforms


# ─────────────────────────────────────────────────────────────────────────────
# Group 3: Module 1 boundary values
# ─────────────────────────────────────────────────────────────────────────────

def test_module1_carveout_exact_boundary_rejected():
    s = WizardState()
    with pytest.raises(Module1ValidationError):
        complete_module1_and_advance(s, raw_objectives=["aw"], raw_budget=10000.0,
                                     raw_test_and_learn_pct=0.5)


def test_module1_carveout_just_below_boundary_accepted():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["aw"], raw_budget=10000.0,
                                 raw_test_and_learn_pct=0.499)
    assert s.test_and_learn_pct == pytest.approx(0.499)


def test_module1_negative_carveout_rejected():
    s = WizardState()
    with pytest.raises(Module1ValidationError):
        complete_module1_and_advance(s, raw_objectives=["aw"], raw_budget=10000.0,
                                     raw_test_and_learn_pct=-0.1)


def test_module1_seasonality_at_boundaries():
    """0.1 and 10.0 should be the inclusive limits."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_seasonality_index={"lg": 0.1})
    assert s.seasonality_index["lg"] == pytest.approx(0.1)
    s2 = WizardState()
    complete_module1_and_advance(s2, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_seasonality_index={"lg": 10.0})
    assert s2.seasonality_index["lg"] == pytest.approx(10.0)


def test_module1_seasonality_just_outside_bounds_rejected():
    s = WizardState()
    with pytest.raises(Module1ValidationError):
        complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                     raw_seasonality_index={"lg": 0.099})
    s2 = WizardState()
    with pytest.raises(Module1ValidationError):
        complete_module1_and_advance(s2, raw_objectives=["lg"], raw_budget=10000.0,
                                     raw_seasonality_index={"lg": 10.001})


def test_module1_seasonality_for_unselected_goal_dropped_silently():
    """A multiplier for a goal not in valid_goals shouldn't raise; just drop."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_seasonality_index={"lg": 1.5, "aw": 0.8})
    assert "aw" not in s.seasonality_index
    assert s.seasonality_index["lg"] == pytest.approx(1.5)


def test_module1_goal_value_zero_is_dropped():
    """Zero is non-actionable for a value weight; should be filtered out."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg", "aw"], raw_budget=10000.0,
                                 raw_goal_values={"lg": 100.0, "aw": 0.0})
    assert "aw" not in s.goal_value_per_unit
    assert s.goal_value_per_unit["lg"] == pytest.approx(100.0)


def test_module1_negative_goal_value_rejected():
    s = WizardState()
    with pytest.raises(Module1ValidationError):
        complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                     raw_goal_values={"lg": -50.0})


# ─────────────────────────────────────────────────────────────────────────────
# Group 4: Module 5 LP edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_module5_single_platform_single_goal():
    """The minimal feasible LP: one platform, one goal.  Should allocate the
    entire budget to the single cell."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 100.0}},
    })
    run_module4(s)
    run_module5(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    fb_total = sum(base.budget_per_platform_goal["fb"].values())
    assert fb_total > 9000.0  # ≈ entire budget (minus tiny rounding)


def test_module5_infeasible_floors_caught():
    """If floors sum to more than the budget, base scenario must raise."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=1000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb", "li"],
                priorities_input={
                    "fb": {"priority_1": "lg", "priority_2": None},
                    "li": {"priority_1": "lg", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
        "li": {"budget": 3000.0, "historical_days": 30, "kpis": {"LI_LG_LEADS": 40.0}},
    })
    run_module4(s)
    # Floors sum to £1500 > total £1000 → must fail
    s.min_spend_per_platform = {"fb": 800.0, "li": 700.0}
    with pytest.raises(Module5ValidationError):
        run_module5(s)


def test_module5_tiny_budget_still_works():
    """Budgets at the low end (£100) should still produce a valid plan."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=100.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
    })
    run_module4(s)
    s.min_spend_per_platform = {"fb": 0.0}
    run_module5(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert base.total_budget_used <= 100.0 + 1e-3


def test_module5_huge_budget_no_overflow():
    """Budgets at the high end (£10M) shouldn't break the LP."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10_000_000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb", "li"],
                priorities_input={
                    "fb": {"priority_1": "lg", "priority_2": None},
                    "li": {"priority_1": "lg", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 50000.0, "historical_days": 90, "kpis": {"FB_LG_LEADS": 500.0}},
        "li": {"budget": 50000.0, "historical_days": 90, "kpis": {"LI_LG_LEADS": 400.0}},
    })
    run_module4(s)
    run_module5(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert base.total_budget_used <= 10_000_000.0 + 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Group 5: State machine boundaries
# ─────────────────────────────────────────────────────────────────────────────

def test_running_module5_before_module4_raises():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
    })
    # Skip Module 4
    with pytest.raises(Exception):  # FlowStateError or similar
        run_module5(s)


def test_re_finalising_module1_raises():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0)
    with pytest.raises(Exception):
        complete_module1_and_advance(s, raw_objectives=["aw"], raw_budget=20000.0)


def test_reset_clears_custom_platforms():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0)
    s.register_custom_platform(
        code="yz", label="Test",
        kpis=[{"goal": "lg", "var": "YZ_LG", "kpi_label": "Leads", "kind": "count"}],
    )
    assert "yz" in s.allowed_platform_codes()
    s.reset()
    assert "yz" not in s.allowed_platform_codes()
    assert s.custom_platforms == []


# ─────────────────────────────────────────────────────────────────────────────
# Group 6: Monte Carlo edge cases
# ─────────────────────────────────────────────────────────────────────────────

def _mc_ready_state():
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
    })
    run_module4(s)
    return s


def test_montecarlo_single_platform_works():
    """One platform = nothing to shrink toward, but MC should still produce
    a valid (trivial) distribution."""
    s = _mc_ready_state()
    mc = run_module5_montecarlo(s, n_trials=20, seed=1)
    assert mc.n_trials > 0
    assert len(mc.per_platform) == 1
    # With one platform and a deterministic single cell, allocation is fixed
    assert mc.per_platform[0].cv >= 0.0


def test_montecarlo_exact_max_trials_accepted():
    s = _mc_ready_state()
    # n_trials=1000 is the documented max
    mc = run_module5_montecarlo(s, n_trials=1000, seed=1)
    assert mc.n_trials > 0


def test_montecarlo_over_max_trials_rejected():
    s = _mc_ready_state()
    with pytest.raises(Module5ValidationError):
        run_module5_montecarlo(s, n_trials=1001, seed=1)


def test_montecarlo_zero_seed_reproducible():
    """Seed=0 is a valid seed; must be reproducible like any other."""
    s1 = _mc_ready_state()
    s2 = _mc_ready_state()
    a = run_module5_montecarlo(s1, n_trials=15, seed=0)
    b = run_module5_montecarlo(s2, n_trials=15, seed=0)
    assert a.per_platform[0].mean == pytest.approx(b.per_platform[0].mean)


# ─────────────────────────────────────────────────────────────────────────────
# Group 7: Catalog completeness
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform", sorted(ALLOWED_PLATFORMS))
def test_every_builtin_platform_has_all_four_goals(platform):
    """Every built-in platform should have at least one KPI for each of the
    four canonical goals (aw, en, wt, lg) — otherwise some Module-2
    selections would silently drop the platform from the LP."""
    for goal in (GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG):
        rows = get_kpi_rows(platform, goal)
        assert rows, f"{platform!r} has no KPI for goal {goal!r}"


@pytest.mark.parametrize("platform", sorted(ALLOWED_PLATFORMS))
def test_every_builtin_platform_has_effective_minimum(platform):
    """Effective spend warnings depend on PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH;
    a missing entry produces a silent zero threshold."""
    assert platform in PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH, (
        f"{platform!r} missing from effective-minimums table"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Group 8: Iterative re-solve edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_to_infeasible_floors_raises():
    """If the user dials a floor higher than the budget, the re-solve must
    raise rather than silently producing a wrong plan."""
    from tests.smoke_test import _run_pipeline_to_module5
    s = _run_pipeline_to_module5()
    run_module6(s)

    # Set floors that exceed the budget
    s.min_spend_per_platform = {"fb": 6000.0, "ig": 6000.0, "li": 6000.0}
    s.module4_finalised = False
    s.module5_finalised = False
    s.module6_finalised = False
    s.current_step = 4
    run_module4(s)
    with pytest.raises(Module5ValidationError):
        run_module5(s)


def test_resolve_with_lower_carveout_releases_budget():
    """A smaller carve-out should make more budget available to the LP."""
    from tests.smoke_test import _run_pipeline_to_module5
    s = _run_pipeline_to_module5()
    s.test_and_learn_pct = 0.30
    run_module2  # unused; included to keep imports linted

    # First re-solve with heavy carve-out
    s.module4_finalised = False
    s.module5_finalised = False
    s.module6_finalised = False
    s.current_step = 4
    s.test_and_learn_pct = 0.30
    run_module4(s)
    run_module5(s)
    used_heavy = s.module5_scenario_bundle.results_by_scenario["base"].total_budget_used

    # Re-solve with light carve-out
    s.module4_finalised = False
    s.module5_finalised = False
    s.module6_finalised = False
    s.current_step = 4
    s.test_and_learn_pct = 0.05
    run_module4(s)
    run_module5(s)
    used_light = s.module5_scenario_bundle.results_by_scenario["base"].total_budget_used

    assert used_light > used_heavy, (
        f"Smaller carve-out should free more budget for the LP; "
        f"heavy ({used_heavy:.0f}) vs light ({used_light:.0f})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Group 9: Forecast edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_module6_forecast_with_zero_allocation():
    """A platform-goal cell with zero allocation must produce no forecast row,
    not a divide-by-zero or unit error."""
    from tests.smoke_test import _run_pipeline_to_module5
    s = _run_pipeline_to_module5()
    # Override allocation: zero IG entirely
    lp = s.module5_scenario_bundle.results_by_scenario["base"]
    for g in list(lp.budget_per_platform_goal.get("ig", {}).keys()):
        lp.budget_per_platform_goal["ig"][g] = 0.0
    run_module6(s)
    base_fc = s.module6_scenario_result.results_by_scenario["base"]
    ig_rows = [r for r in base_fc.rows if r.platform == "ig"]
    assert all(r.allocated_budget > 0 for r in ig_rows), (
        "IG had zero allocations across all goals; should produce no forecast rows"
    )


def test_csv_negative_spend_doesnt_corrupt_budget():
    """Refund/credit rows shouldn't drag the spend total below zero into
    nonsense — Module 3 expects budget > 1."""
    csv = b"Campaign,Reach,Amount Spent\nCamp A,100000,1500\nCredit,0,-200\n"
    result = parse_platform_csv(csv, "fb")
    # Sums to £1300; positive and meaningful
    assert result["budget"] > 1.0


def test_csv_with_only_irrelevant_columns_no_kpis_matched():
    """A CSV with columns we don't recognise should produce kpis={} and
    a missing list, not crash."""
    csv = b"Region,Population\nLondon,9000000\n"
    result = parse_platform_csv(csv, "fb")
    assert result.get("kpis", {}) == {} or all(v == 0 for v in result["kpis"].values())
    assert result.get("missing_kpis"), "Expected missing_kpis to be populated"


def test_csv_wrong_platform_doesnt_crash():
    """Upload a Google export to the FB parser: should produce mostly missing
    fields but not crash."""
    csv = b"Impressions,Clicks,CTR,Conversions,Cost\n100000,4500,4.50%,300,1000\n"
    result = parse_platform_csv(csv, "fb")
    # FB pattern won't match GO_EN_CTR or GO_LG_CONVERSIONS columns; only
    # 'Impressions' (matches FB_AW_IMPRESSION) and 'Cost' (FB _budget) match.
    assert "error" not in result
    assert result["kpis"].get("FB_AW_IMPRESSION") == pytest.approx(100000.0)


def test_csv_blank_value_cells_dont_zero_aggregate():
    """A column that's mostly blank shouldn't aggregate to zero (and then get
    filtered as <=0) silently."""
    csv = (
        b"Campaign,Reach,Impressions,Amount Spent\n"
        b"Camp A,,200000,1000\n"
        b"Camp B,,300000,1500\n"
    )
    result = parse_platform_csv(csv, "fb")
    # No Reach values → FB_AW_REACH should be in missing, not silently 0
    assert "FB_AW_REACH" in result["missing_kpis"]
    assert result["kpis"].get("FB_AW_IMPRESSION") == pytest.approx(500000.0)


def test_pipeline_with_all_nine_builtin_platforms():
    """Run the full pipeline with every built-in platform selected at once —
    stress test for the LP and the catalog lookups."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["aw", "lg"], raw_budget=100000.0,
                                 raw_duration_days=30)
    builtins = ["fb", "ig", "li", "yt", "tt", "pt", "tw", "sn", "rd", "go"]
    run_module2(s, selected_platforms=builtins,
                priorities_input={p: {"priority_1": "lg", "priority_2": "aw"}
                                  for p in builtins})
    # Each platform gets one credible LG count
    lg_vars = {
        "fb": "FB_LG_LEADS", "ig": "IG_LG_LEADS", "li": "LI_LG_LEADS",
        "yt": "YT_LG_LEADS", "tt": "TT_LG_LEADS", "pt": "PT_LG_LEADS",
        "tw": "TW_LG_LEADS", "sn": "SN_LG_LEADS", "rd": "RD_LG_LEADS",
        "go": "GO_LG_CONVERSIONS",
    }
    inputs = {}
    for p in builtins:
        inputs[p] = {
            "budget": 5000.0, "historical_days": 60,
            "kpis": {lg_vars[p]: 50.0 + 5 * builtins.index(p)},
        }
    finalise_module3_from_inputs(s, platform_inputs=inputs)
    run_module4(s)
    run_module5(s)
    run_module6(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert base.total_budget_used > 0
    # Every selected platform should appear in budget_per_platform
    for p in builtins:
        assert p in base.budget_per_platform


def test_montecarlo_with_high_carveout_still_valid():
    """A near-maximum carve-out (49%) should still let Monte Carlo run."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30, raw_test_and_learn_pct=0.49)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
    })
    run_module4(s)
    mc = run_module5_montecarlo(s, n_trials=20, seed=1)
    assert mc.n_trials > 0


def test_pipeline_with_custom_platform_then_csv_for_builtin():
    """A custom platform plus a CSV upload for a built-in in the same run —
    both should reach Module 5 alive."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    s.register_custom_platform(
        code="yz", label="MyChannel",
        kpis=[{"goal": "lg", "var": "YZ_LG", "kpi_label": "Leads", "kind": "count"}],
    )
    run_module2(s, selected_platforms=["fb", "yz"],
                priorities_input={
                    "fb": {"priority_1": "lg", "priority_2": None},
                    "yz": {"priority_1": "lg", "priority_2": None},
                })
    # Simulate the CSV path: a parsed Meta export feeds FB's KPI input
    parsed_fb = parse_platform_csv(
        b"Reach,Leads,Amount Spent\n200000,80,3000\n", "fb",
    )
    assert "error" not in parsed_fb
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": parsed_fb["budget"], "historical_days": 30,
               "kpis": parsed_fb["kpis"]},
        "yz": {"budget": 3000.0, "historical_days": 30, "kpis": {"YZ_LG": 60.0}},
    })
    run_module4(s)
    run_module5(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert sum(base.budget_per_platform_goal.get("yz", {}).values()) > 0
    assert sum(base.budget_per_platform_goal.get("fb", {}).values()) > 0


def test_csv_meta_export_with_total_row():
    """Meta sometimes adds a 'Results from ad sets' summary row; ensure
    that doesn't double-count."""
    csv = (
        b"Ad set name,Reach,Impressions,Amount spent\n"
        b"Set A,100000,200000,1000\n"
        b"Set B,150000,300000,1500\n"
        b'"Total results from ad sets",250000,500000,2500\n'
    )
    result = parse_platform_csv(csv, "fb")
    assert result["budget"] == pytest.approx(2500.0)
    assert result["kpis"]["FB_AW_REACH"] == pytest.approx(250000.0)


def test_resolve_then_montecarlo_uses_new_policy():
    """After re-solve with new policy, Monte Carlo should run against the
    new state — not the old one."""
    from tests.smoke_test import _run_pipeline_to_module5
    s = _run_pipeline_to_module5()
    initial_mc = run_module5_montecarlo(s, n_trials=20, seed=1)
    initial_total = sum(x.mean for x in initial_mc.per_platform)

    # Lower the budget by half, re-solve
    s.total_budget = float(s.total_budget) * 0.5
    s.module4_finalised = False
    s.module5_finalised = False
    s.module6_finalised = False
    s.current_step = 4
    run_module4(s)
    run_module5(s)

    new_mc = run_module5_montecarlo(s, n_trials=20, seed=1)
    new_total = sum(x.mean for x in new_mc.per_platform)
    # New total spend must be smaller (~half) since budget halved
    assert new_total < initial_total * 0.75, (
        f"Halved budget should halve MC total; got "
        f"{new_total:.0f} vs initial {initial_total:.0f}"
    )


def test_kpi_var_in_csv_for_unprioritised_goal_silently_dropped():
    """If a CSV carries data for a goal that Module 2 didn't prioritise on
    that platform, Module 3 should drop it — not error.  This is a normal
    case: the user exports everything Meta knows, but only AW was a
    priority on FB."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["aw", "lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb", "li"],
                priorities_input={
                    "fb": {"priority_1": "aw", "priority_2": None},  # FB on AW only
                    "li": {"priority_1": "lg", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {
            "FB_AW_REACH": 200000.0,
            "FB_LG_LEADS": 50.0,  # ← data for unprioritised goal; should be ignored
        }},
        "li": {"budget": 3000.0, "historical_days": 30, "kpis": {"LI_LG_LEADS": 80.0}},
    })
    run_module4(s)
    run_module5(s)
    # FB should serve only AW, not LG
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    fb_lg = base.budget_per_platform_goal.get("fb", {}).get("lg", 0.0)
    assert fb_lg == 0.0, f"FB shouldn't get LG budget; got £{fb_lg:.0f}"


def test_module7_runs_even_with_one_scenario():
    """If only the base scenario is feasible (conservative + optimistic skipped),
    Module 7 must still produce insights — not crash on missing scenarios."""
    from modules.module5 import run_module5_lp_scenarios

    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["lg"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "lg", "priority_2": None}})
    finalise_module3_from_inputs(s, platform_inputs={
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_LG_LEADS": 60.0}},
    })
    run_module4(s)
    # Force only a "base" scenario
    s.scenario_multipliers = {"base": 1.0}
    run_module5(s)
    run_module6(s)
    insights = run_module7(s, s.module5_scenario_bundle,
                          s.module6_scenario_result.results_by_scenario)
    assert "base" in insights.scenario_insights


def test_pipeline_with_only_rate_kpi_goal():
    """A campaign whose only goal is engagement (rate-only KPI) should
    still produce a working plan — no division by zero, no kind confusion."""
    s = WizardState()
    complete_module1_and_advance(s, raw_objectives=["en"], raw_budget=10000.0,
                                 raw_duration_days=30)
    run_module2(s, selected_platforms=["ig", "tt"],
                priorities_input={
                    "ig": {"priority_1": "en", "priority_2": None},
                    "tt": {"priority_1": "en", "priority_2": None},
                })
    finalise_module3_from_inputs(s, platform_inputs={
        "ig": {"budget": 3000.0, "historical_days": 60, "kpis": {"IG_EN_ENGRATERATE": 0.045}},
        "tt": {"budget": 3000.0, "historical_days": 60, "kpis": {"TT_EN_ENGRATERATE": 0.06}},
    })
    run_module4(s)
    run_module5(s)
    run_module6(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    assert base.total_budget_used > 0
    # Rate-only forecast must not multiply by budget
    base_fc = s.module6_scenario_result.results_by_scenario["base"]
    for row in base_fc.rows:
        if row.kpi_kind == "rate":
            assert row.predicted_kpi <= 1.0


def test_seasonality_doesnt_corrupt_goal_with_no_kpi_data():
    """Seasonality multiplier for a goal that has no historical data
    shouldn't blow up r_pg — multiplying zero is zero."""
    s = WizardState()
    complete_module1_and_advance(
        s, raw_objectives=["aw", "lg"], raw_budget=10000.0, raw_duration_days=30,
        raw_seasonality_index={"aw": 2.5, "lg": 0.6},
    )
    run_module2(s, selected_platforms=["fb"],
                priorities_input={"fb": {"priority_1": "aw", "priority_2": "lg"}})
    finalise_module3_from_inputs(s, platform_inputs={
        # AW data only; LG has no KPIs
        "fb": {"budget": 3000.0, "historical_days": 30, "kpis": {"FB_AW_REACH": 200000.0}},
    })
    run_module4(s)
    run_module5(s)
    base = s.module5_scenario_bundle.results_by_scenario["base"]
    # Should still solve; AW gets the budget; LG cell stays zero
    assert sum(base.budget_per_platform_goal.get("fb", {}).values()) > 0


def test_module6_rate_kpi_band_is_point_estimate():
    """Rate KPIs (engagement rate) should NOT get a ± band — they're already
    averages.  predicted_kpi_low / _high should equal predicted_kpi."""
    from tests.smoke_test import _run_pipeline_to_module5
    s = _run_pipeline_to_module5()
    run_module6(s)
    base_fc = s.module6_scenario_result.results_by_scenario["base"]
    rate_rows = [r for r in base_fc.rows if r.kpi_kind == "rate"]
    for row in rate_rows:
        assert row.predicted_kpi_low == row.predicted_kpi == row.predicted_kpi_high
