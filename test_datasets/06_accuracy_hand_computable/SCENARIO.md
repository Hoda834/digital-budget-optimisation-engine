# Scenario 6 — Accuracy-by-hand

A minimal two-platform, single-objective dataset whose every output can
be derived with a calculator. Designed to act as a regression backstop:
if a future refactor breaks any of these numbers, the test that loads
this folder fails with a clear arithmetic diff.

## Wizard inputs

- Objective: Lead Generation only
- Budget: £10,000
- Duration: 30 days
- Currency: GBP
- Platforms: Facebook (rank 1), LinkedIn (rank 2)
- Per-platform minima: none (both 0)
- Goal values: none (rank-based weights)
- Test-and-learn reserve: 0%
- Seasonality: 1.0 (none)
- Scenario multipliers: single `base = 1.0` scenario

## CSV inputs

- `fb.csv`: £1,000 spent over 30 days → 100 leads → **0.10 leads/£**
- `li.csv`: £1,000 spent over 30 days →  10 leads → **0.01 leads/£**

FB is 10× more productive than LI.

## Hand-computed expected outcomes

- `effective_budget_cap` (base) = `£10,000` (no carve-out)
- `total_budget_used` (base) ≈ `£10,000` (LP is budget-bound)
- `ratio_kpi_per_budget` for `FB_LG_LEADS` = `100 / 1000` = **0.10**
- `ratio_kpi_per_budget` for `LI_LG_LEADS` = `10 / 1000`  = **0.01**
- For every forecast row: `predicted_kpi = allocated_budget × ratio`
- `band_pct` for both rows = **0.30** (default at 30-day history,
  no per-row observations)
- `predicted_kpi_low  = predicted × 0.70`
- `predicted_kpi_high = predicted × 1.30`

## What this stresses

- Forecast formula correctness (count KPI)
- Uncertainty-band default at the reference 30-day window
- Budget closure on a one-objective LP
- The pipeline's ability to round-trip historical_count and
  historical_budget through M3 → M4 → M5 → M6 without distortion
