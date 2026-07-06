# Example case study: policy-constrained allocation

A five-platform, two-objective allocation problem run under three policy
configurations, showing how the policy layer reshapes a concentrated
optimum. All scripts in this folder read `campaign_data.xlsx`, a filled
copy of the app's unified import template; the same workbook can be
uploaded directly into Module 3 of the guided interface to reproduce
any run by hand.

## Provenance

The historical data is the bundled `test_datasets/02_dtc_ecommerce_purchases`
example with one documented change: Google Performance Max's Purchases
figure is raised from 1,840 to 5,200 at unchanged spend (22,000 over 60
days), so that one platform holds a productivity advantage large enough
to exercise the policy layer under concentration pressure. No other
platform's data differs from the bundled example.

## Wizard inputs

- Objectives: Lead Generation (purchases-led), Website Traffic
- Budget: 80,000
- Duration: 60 days
- Test-and-learn reserve: 15% (68,000 allocatable)
- Goal values: 45 per purchase (lg), 0.40 per click (wt)
- Platforms: Google Performance Max, Facebook, Instagram, TikTok, Pinterest
- Priorities: every platform leads on Lead Generation except TikTok,
  which leads on Website Traffic

## Three configurations (see `run_case_study.py`)

1. **Budget cap only**: `min_spend_per_platform = {}`,
   `min_budget_per_goal = {}`. Only the total-budget cap constrains the LP.
2. **Default policy**: the engine's own `run_module2` defaults, a 5%
   of budget floor on every platform plus 10% of budget pooled and split
   evenly across prioritised objectives. No manual override.
3. **Custom policy**: default policy, with TikTok's floor manually
   raised from 4,000 to 6,000.

## Verified output (regenerate with `PYTHONPATH=src python examples/case_study/run_case_study.py`)

| | Budget cap only | Default policy | Custom policy |
|---|---|---|---|
| Google Performance Max | 34,000 | 26,000 | 24,000 |
| Facebook | 17,000 | 17,000 | 17,000 |
| Instagram | 17,000 | 17,000 | 17,000 |
| TikTok | 0 | 4,000 | 6,000 |
| Pinterest | 0 | 4,000 | 4,000 |
| Top-platform share | 50.0% | 38.2% | 35.3% |
| Classification | Scenario-sensitive | Scenario-sensitive | Scenario-sensitive |
| Diagnostic index | 90 | 90 | 90 |

**Known wrinkle, not a bug:** under the default policy, TikTok's 4,000
floor and the 4,000 Website Traffic goal floor land on the same number,
so both register as binding at once (the binding check uses a relative
tolerance, and an exact tie trips it both ways). The underlying
allocation, classification, and diagnostic index are unaffected; the
binding-constraints list simply gains one extra true entry here.

## Other scripts in this folder

- `run_data_sensitivity.py`: sweeps Google Performance Max's purchase
  productivity (3,200 to 7,200) and records the top-platform share
  under the default policy.
- `run_parameter_sensitivity.py`: perturbs the engine's own heuristic
  constants (diversification cap, diagnostic-index deductions,
  classification thresholds, yield-bracket schedule, scenario
  multipliers) and records the effect on allocation, classification,
  and the diagnostic index. See `docs/CALIBRATION.md` for what each
  constant is and why its default was chosen.
