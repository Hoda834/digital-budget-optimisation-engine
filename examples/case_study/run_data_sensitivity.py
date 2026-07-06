"""
Input-data sensitivity for the example case study: varies the dominant
platform's purchase productivity and records the resulting top-platform
share under the default-policy configuration.

Google Performance Max's Purchases figure is overridden in memory at
each sweep point; every other input comes unchanged from
campaign_data.xlsx in this folder. The workbook value itself (5,200) is
the case study's central point.

Run from the repo root:
    PYTHONPATH=src python examples/case_study/run_data_sensitivity.py
"""
from __future__ import annotations

from run_case_study import run_configuration

SWEEP = (3_200, 4_200, 5_200, 6_200, 7_200)

if __name__ == "__main__":
    print("Google Performance Max purchases | Top-platform share | PMax allocation")
    print("-" * 72)
    for purchases in SWEEP:
        _, bundle, insights = run_configuration("default", pmax_purchases_override=purchases)
        lp = bundle.results_by_scenario["base"]
        ins = insights.scenario_insights["base"]
        pt = {p: sum(v for v in g.values() if v > 1)
              for p, g in lp.budget_per_platform_goal.items()}
        total = sum(pt.values()) or 1.0
        share = max(pt.values()) / total
        marker = "  <- workbook value" if purchases == 5_200 else ""
        print(f"{purchases:>32,} | {share:>18.1%} | {pt.get('go_pmax', 0):>11,.0f}"
              f"  idx={ins.confidence_score} {ins.classification}{marker}")
    print("\nNote: the allocation moves in steps rather than continuously, "
          "because the diminishing-returns yield brackets cap how much any "
          "single platform can absorb at each productivity tier.")
