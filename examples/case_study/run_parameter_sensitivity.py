"""
Sensitivity of outputs to the software's own heuristic parameters (as
distinct from input data; for input-data sensitivity see
run_data_sensitivity.py). Each sub-analysis perturbs one set of
constants documented in docs/CALIBRATION.md and records the effect on
allocation, classification, and the diagnostic index.

  A. Diversification cap (plan_b_top_platform_cap, default 0.70).
     Uses the case-study workbook pushed to a genuinely concentrated
     point (Google Performance Max at 20,000 purchases, 76.5% share
     under budget-cap-only) so the risk-managed redistribution has
     something to do; at the case study's own three configurations the
     top share never exceeds 50%, so the default cap never binds there.

  B. Diagnostic-index deductions (the six penalty weights in
     module7.py). Each is independently halved and increased by 50% at
     the case study's default-policy configuration.

  C. Classification thresholds (corner_concentration 0.90,
     balanced_concentration 0.75). Multi-scenario runs usually classify
     as Scenario-sensitive before concentration is considered, because
     the scenario multipliers change the budget cap and therefore the
     allocation between scenarios almost by construction. To isolate
     the thresholds, this sub-analysis uses a controlled synthetic
     input with equal scenario multipliers held at a fixed 84%
     concentration, and sweeps the two thresholds around it.

  D. Yield-bracket schedule (module5.py YIELD_BRACKETS: cap fractions
     0.25/0.35/0.40, marginal-yield multipliers 1.00/0.65/0.35). A
     module-level constant, monkeypatched per trial and restored
     (try/finally), at the case-study default-policy configuration.

  E. Scenario multipliers (default conservative 0.85, optimistic 1.15),
     swept out to 0.60/1.40 at three configurations: mid-bracket, at a
     yield-bracket transition, and deep concentration, reporting both
     share and absolute allocation.

Honest note on the findings: D moves the allocation far more than A, B,
or C (top share 25.0% to 60.0% across plausible alternative bracket
schedules, versus single-digit or no movement for the interpretation
parameters). That is a real difference in how much each parameter
matters, reported as such rather than smoothed over: the bracket
schedule is the core of the diminishing-returns model and is expected
to be the most influential constant in the system.

Run from the repo root:
    PYTHONPATH=src python examples/case_study/run_parameter_sensitivity.py
"""
from __future__ import annotations

from run_case_study import (
    load_platform_inputs, PLATFORMS, PRIORITIES, GOAL_VALUES,
    TOTAL_BUDGET, DURATION_DAYS, TEST_AND_LEARN_PCT, run_configuration,
)

from claro_engine.core.wizard_state import WizardState
from claro_engine.modules.module1 import complete_module1_and_advance
from claro_engine.modules.module2 import run_module2
from claro_engine.modules.module3 import finalise_module3_from_inputs
from claro_engine.modules.module4 import run_module4
from claro_engine.modules.module5 import Module5LPInput, run_module5_lp_scenarios
import claro_engine.modules.module5 as _module5
from claro_engine.modules.module7 import run_module7, Module7Policy, _plan_b_risk_managed

SEP = "=" * 78


def _built_state(pmax_purchases=None):
    """Wizard state completed through Module 4, ready for a Module 5 run."""
    state = WizardState()
    complete_module1_and_advance(
        state, raw_objectives=["lg", "wt"], raw_budget=TOTAL_BUDGET,
        raw_duration_days=DURATION_DAYS, raw_goal_values=GOAL_VALUES,
        raw_test_and_learn_pct=TEST_AND_LEARN_PCT,
    )
    run_module2(state, selected_platforms=PLATFORMS, priorities_input=PRIORITIES)
    finalise_module3_from_inputs(
        state, platform_inputs=load_platform_inputs(pmax_purchases))
    run_module4(state)
    return state


def sub_analysis_a():
    print(f"\n{SEP}\nA. Diversification cap sensitivity\n{SEP}")
    print("Base: case-study workbook at 20,000 purchases (76.5% share under "
          "the default policy floors).\n")
    state, bundle, _ = run_configuration("default", pmax_purchases_override=20_000)
    lp = bundle.results_by_scenario["base"]
    pt0 = {p: sum(v for v in g.values() if v > 1)
           for p, g in lp.budget_per_platform_goal.items()}
    total0 = sum(pt0.values())
    print(f"  Plan A (no cap applied)      : top share {max(pt0.values())/total0:.1%}")
    print(f"  {'Cap':>6}  {'Resulting top share':>20}  {'PMax':>10}  {'Trade-off %':>12}")
    for cap in (0.60, 0.65, 0.70, 0.75, 0.80):
        plan_b = _plan_b_risk_managed(state, lp, cap_top_platform_share=cap)
        pt = {p: sum(v for v in g.values() if v > 1) for p, g in plan_b.allocation.items()}
        total = sum(pt.values()) or 1.0
        marker = "  <- default" if cap == 0.70 else ""
        print(f"  {cap:>6.2f}  {max(pt.values())/total:>19.1%}  "
              f"{pt.get('go_pmax', 0):>10,.0f}  {plan_b.tradeoff_percent:>11.2f}{marker}")
    print("\n  Reading: the trade-off grows smoothly and monotonically as the "
          "cap tightens, with no jumps or infeasibility across 0.60 to 0.80. "
          "At 0.80 (looser than the natural 76.5% share), the redistribution "
          "correctly does nothing (trade-off 0.00), matching Plan A exactly.")


def sub_analysis_b():
    print(f"\n{SEP}\nB. Diagnostic-index deduction sensitivity\n{SEP}")
    print("Base: case-study default-policy configuration. Each deduction "
          "tested at 0.5x and 1.5x its default, one at a time.\n")

    def index_with(policy=None):
        state, bundle, insights = run_configuration("default")
        if policy is None:
            return insights.scenario_insights["base"].confidence_score
        forecasts = (state.module6_scenario_result.results_by_scenario
                     if state.module6_scenario_result else {})
        return run_module7(state, bundle, forecasts,
                           policy=policy).scenario_insights["base"].confidence_score

    baseline = index_with(None)
    print(f"  Default weights -> diagnostic index = {baseline}\n")
    fields = ["confidence_high_concentration_penalty", "confidence_med_concentration_penalty",
              "confidence_few_cells_penalty", "confidence_unstable_scenarios_penalty",
              "confidence_missing_forecast_penalty", "confidence_dq_issue_penalty"]
    defaults = {f: getattr(Module7Policy(), f) for f in fields}
    print(f"  {'Deduction':<42}{'0.5x':>8}{'1.5x':>8}")
    for f in fields:
        scores = [index_with(Module7Policy(**{f: defaults[f] * m})) for m in (0.5, 1.5)]
        print(f"  {f:<42}{scores[0]:>8}{scores[1]:>8}")
    print("\n  Reading: only the unstable-scenarios deduction moves the index "
          "here (it is the one deduction actually triggered in this "
          "scenario); the other five are inert because their trigger "
          "conditions (high concentration, missing forecast, etc.) are "
          "absent. Where a deduction does apply, halving or raising it by "
          "50% moves the index by a few points, not a reclassification.")


def sub_analysis_c():
    print(f"\n{SEP}\nC. Classification-threshold sensitivity\n{SEP}")
    print("Controlled synthetic input, equal scenario multipliers, fixed at "
          "84% concentration, to isolate the two thresholds.\n")

    def build(dominant_ratio=3.0, n_platforms=5):
        platforms = [f"p{i}" for i in range(n_platforms)]
        goals = ["g0", "g1"]
        r_pg = {p: {g: (dominant_ratio if i == 0 else 1.0) for g in goals}
                for i, p in enumerate(platforms)}
        weights = {p: {g: 1.0 for g in goals} for p in platforms}
        floors = {p: 4_000.0 for i, p in enumerate(platforms) if i != 0}
        return Module5LPInput(
            valid_goals=goals, total_budget=100_000.0,
            system_goal_weights={"g0": 0.5, "g1": 0.5}, platform_goal_weights=weights,
            r_pg=r_pg, goals_by_platform={p: goals for p in platforms},
            min_spend_per_platform=floors, min_budget_per_goal={},
            scenario_multipliers={"conservative": 1.0, "base": 1.0, "optimistic": 1.0},
            scenario_goal_multipliers={"conservative": {}, "base": {}, "optimistic": {}},
        )

    state = WizardState()
    bundle = run_module5_lp_scenarios(build())
    conc = run_module7(state, bundle, {}).scenario_insights["base"].concentration_ratio_top_platform
    print(f"  Fixed concentration = {conc:.1%} (classifies as Concentrated by default)\n")
    print(f"  {'corner_concentration':<24}{'classification':>18}   (default 0.90)")
    for corner in (0.80, 0.85, 0.90, 0.95):
        ins = run_module7(state, bundle, {},
                          policy=Module7Policy(corner_concentration=corner)).scenario_insights["base"]
        marker = "  <- default" if corner == 0.90 else ""
        print(f"  {corner:<24.2f}{ins.classification:>18}{marker}")
    print(f"\n  {'balanced_concentration':<24}{'classification':>18}   (default 0.75)")
    for balanced in (0.70, 0.75, 0.80, 0.85):
        ins = run_module7(state, bundle, {},
                          policy=Module7Policy(balanced_concentration=balanced)).scenario_insights["base"]
        marker = "  <- default" if balanced == 0.75 else ""
        print(f"  {balanced:<24.2f}{ins.classification:>18}{marker}")
    print("\n  Reading: at a fixed 84% concentration the label stays "
          "'Concentrated' across the plausible range on both sides and only "
          "flips at the extremes where a threshold crosses the actual "
          "concentration value, exactly the behaviour expected of a real "
          "breakpoint.")


def sub_analysis_d():
    print(f"\n{SEP}\nD. Yield-bracket schedule sensitivity\n{SEP}")
    print("Base: case-study default-policy configuration. YIELD_BRACKETS is "
          "monkeypatched per trial and restored immediately after.\n")

    def run_with_brackets(brackets):
        state = _built_state()
        original = _module5.YIELD_BRACKETS
        try:
            _module5.YIELD_BRACKETS = brackets
            _module5.run_module5(state)
        finally:
            _module5.YIELD_BRACKETS = original
        lp = state.module5_scenario_bundle.results_by_scenario["base"]
        pt = {p: sum(v for v in g.values() if v > 1)
              for p, g in lp.budget_per_platform_goal.items()}
        total = sum(pt.values()) or 1.0
        return max(pt.values()) / total, pt.get("go_pmax", 0.0)

    default_brackets = ((0.25, 1.00), (0.35, 0.65), (0.40, 0.35))
    variants = {
        "default (0.25/0.35/0.40 caps, 1.00/0.65/0.35 yields)": default_brackets,
        "steeper falloff (yields decay faster)": ((0.25, 1.00), (0.35, 0.50), (0.40, 0.20)),
        "gentler falloff (yields decay slower)": ((0.25, 1.00), (0.35, 0.80), (0.40, 0.55)),
        "smaller first bracket (0.15 cap)": ((0.15, 1.00), (0.35, 0.65), (0.50, 0.35)),
        "larger first bracket (0.35 cap)": ((0.35, 1.00), (0.35, 0.65), (0.30, 0.35)),
    }
    print(f"  {'Variant':<52}{'Top share':>10}{'PMax':>10}")
    for name, brackets in variants.items():
        share, pmax = run_with_brackets(brackets)
        marker = "  <- default" if brackets == default_brackets else ""
        print(f"  {name:<52}{share:>9.1%}{pmax:>10,.0f}{marker}")
    print("\n  Reading: unlike the interpretation-layer parameters above, "
          "this one moves the actual allocation substantially (25.0% to "
          "60.0% top share). It is the core of the diminishing-returns "
          "model, so it should matter more than an interpretation threshold; "
          "the point of this test is to show that honestly rather than claim "
          "uniform robustness across every constant in the system.")


def sub_analysis_e():
    print(f"\n{SEP}\nE. Scenario-multiplier sensitivity (multi-point)\n{SEP}")
    print("Defaults are conservative 0.85 / optimistic 1.15, widened here "
          "out to 0.60 / 1.40, at three configurations so the stability "
          "finding is not a single-point artefact. Shares and absolute "
          "allocations are both reported.\n")

    def run_with_multipliers(pmax_purchases, cons, opt):
        state = _built_state(pmax_purchases)
        original = _module5._default_scenario_multipliers
        try:
            _module5._default_scenario_multipliers = lambda: {
                "conservative": cons, "base": 1.0, "optimistic": opt}
            _module5.run_module5(state)
        finally:
            _module5._default_scenario_multipliers = original
        bundle = state.module5_scenario_bundle
        shares = {}
        for s_name, lp in bundle.results_by_scenario.items():
            pt = {p: sum(v for v in g.values() if v > 1)
                  for p, g in lp.budget_per_platform_goal.items()}
            total = sum(pt.values()) or 1.0
            shares[s_name] = (max(pt.values()) / total, pt.get("go_pmax", 0.0))
        ins = run_module7(state, bundle, {}).scenario_insights["base"]
        return shares, ins.classification

    configs = [
        (5_200, "workbook value (mid-bracket)"),
        (3_800, "at a yield-bracket transition"),
        (20_000, "deep concentration"),
    ]
    for purchases, label in configs:
        print(f"\n  Configuration: {label} (PMax purchases = {purchases:,})")
        print(f"  {'Cons/Opt':<12}{'Conservative':>20}{'Base':>18}{'Optimistic':>18}  Classification")
        for cons, opt in [(0.85, 1.15), (0.70, 1.30), (0.90, 1.10), (0.60, 1.40)]:
            shares, cls = run_with_multipliers(purchases, cons, opt)
            row = f"  {f'{cons}/{opt}':<12}"
            for s in ("conservative", "base", "optimistic"):
                sh, gbp = shares[s]
                row += f"{f'{sh:.1%} ({gbp:,.0f})':>18}"
            marker = "  <- default" if (cons, opt) == (0.85, 1.15) else ""
            print(row + f"  {cls}{marker}")

    print("\n  Reading, two separate findings:")
    print("  (1) The conservative scenario has a real effect in absolute "
          "terms: at the workbook value it pulls the top platform from "
          "26,000 down to 17,000; at deep concentration from 52,000 to "
          "41,800. The multipliers are not decorative; they feed the "
          "cross-scenario stability signal that the classification and "
          "diagnostic index depend on.")
    print("  (2) The magnitude of the multiplier does not matter at any of "
          "the three configurations, including the one placed exactly at a "
          "bracket transition. This is by construction: bracket caps are "
          "anchored to the base budget cap (module5.py, "
          "cell_bracket_cap_basis), deliberately constant across scenarios, "
          "and the optimistic cap is clamped at the declared budget "
          "(min(total x scalar, total)) so an optimistic plan can never "
          "spend money the user does not have. What matters is that a "
          "conservative scenario exists at all; the exact choice of 0.85 or "
          "0.70 is absorbed by the design across the tested range.")


if __name__ == "__main__":
    sub_analysis_a()
    sub_analysis_b()
    sub_analysis_c()
    sub_analysis_d()
    sub_analysis_e()
    print(f"\n{SEP}\nDone.\n{SEP}")
