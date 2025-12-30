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
