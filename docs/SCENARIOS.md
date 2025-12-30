# Scenario Modelling

This document explains how uncertainty is modelled and evaluated in the system.

Rather than producing a single optimal answer, the framework evaluates decisions across multiple scenarios.

---

## Scenario Types

The system supports three standard scenarios:

- Conservative  
- Base  
- Optimistic  

Each scenario represents a different set of assumptions about performance and uncertainty.

---

## Scenario Multipliers

Scenario behaviour is controlled through multipliers that adjust expected outcomes.

Multipliers can be applied:
- At a global level
- Per objective

This allows sensitivity testing without changing the optimisation model.

---

## Scenario Evaluation

For each scenario, the system produces:
- A full budget allocation
- Forecasted KPI outcomes
- Objective values

Results are compared side by side to assess robustness.

---

## Interpretation Across Scenarios

Scenario comparison is used to:
- Identify stable allocation patterns
- Understand risk–return trade-offs
- Avoid decisions driven by a single optimistic assumption

Scenarios support judgement rather than replacing it.
