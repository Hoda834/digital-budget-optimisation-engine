# Decision Logic

This document explains the modelling choices and assumptions used in the system.

The goal is transparency and reviewability, not automation for its own sake.

---

## Decision Design

Decisions are structured before optimisation.

Objectives, constraints, and priorities must be explicitly defined before any computation takes place.

This avoids post-hoc rationalisation.

---

## Optimisation Approach

The system uses Linear Programming to allocate the budget under constraints.

Reasons for this choice:
- Deterministic and explainable behaviour
- Clear constraint handling
- Reproducible results
- Alignment with real-world planning problems

Diminishing returns are modelled with three piecewise-linear brackets per (platform, goal) cell. Each successive bracket yields less per unit of currency than the one before it, so the optimiser is discouraged from concentrating the entire budget on a single cell.

### Scenarios

Scenarios shift the optimisation in two ways at once:

- A per-scenario **total-budget cap multiplier** (e.g. conservative 0.85×, optimistic 1.15×) changes the LP's capacity constraint, not just the objective. This is required because positive scaling of a linear objective is argmax-invariant; without it, scenarios would only re-scale objective values and leave allocations identical.
- A per-scenario **goal multiplier** shifts the productivity coefficients relatively across goals, so the optimiser genuinely re-ranks cells in different scenarios.

### Priority Weights

Each platform supports up to two prioritised goals. Rank 1 contributes a score of 2.0 and Rank 2 contributes 1.0; goals not chosen as a priority on a platform receive a score of 0 and do not enter the optimisation for that platform.

System-level goal weights are derived from the frequency of priority choices across platforms (rank 1 weighted twice as much as rank 2), unless the caller sets them explicitly.

### KPI Kinds

KPI rows in `core/kpi_config.py` are tagged as `count` or `rate`:

- **Count** KPIs (Reach, Impressions, Clicks, Leads, Purchases, Engagements, Views) are normalised into a productivity of `value / historical_budget`.
- **Rate** KPIs (none in the current catalogue) would be kept as-is — folded in as a multiplicative boost on the count-derived productivity, not divided by budget. The uniform-units refactor switched every social-platform engagement KPI from rate to count (sum of likes / comments / shares / etc.) so that all KPIs on a platform share the same unit. The rate-handling branches in modules 3–7 are retained as forward-compatibility shims if a future platform re-introduces a rate canonical.

---

## Forecasting Logic

Forecasts are derived from historical performance ratios.

The forecasting layer is intentionally simple:
- No black-box models
- Direct traceability between input and output
- Easy to review and challenge

---

## Interpretation Logic

Interpretation is rule-based and explicit.

The system does not claim predictive certainty. Instead, it supports structured reasoning and informed judgement.
