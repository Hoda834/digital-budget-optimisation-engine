# Marketing Budget Optimisation and Decision Support Framework

## Overview

This project provides a complete decision support system that helps decision-makers allocate a limited marketing budget across platforms and objectives, accounting for real-world constraints.

Instead of looking at channels separately, the system treats marketing as a constrained optimisation problem. It integrates past performance data, business goals, and uncertainty to generate clear, structured recommendations.

The framework is designed to help managers make better decisions, not just to automate processes.

---

## What Problem Does This Solve?

In practice, marketing decisions rarely fail because of a lack of data. They fail because:

* Budgets are limited and must satisfy competing objectives
* Platform performance is interdependent, not independent
* Business constraints are applied informally or too late
* Scenario uncertainty is ignored or oversimplified
* Outputs lack interpretation, making decisions hard to justify

This project fills these gaps by dividing decision design, optimisation, and interpretation into clear, reviewable steps.

---

## Core Capabilities

### 1. Structured Decision Design (Wizard-Based)

The system guides users through a structured decision flow:

* Selection of marketing objectives (Awareness, Engagement, Website Traffic, Lead Generation)
* Definition of total budget and validation rules
* Platform selection with priority ranking per objective
* Constraint definition (minimum spend per platform, minimum budget per objective)
* Scenario configuration (conservative, base, optimistic)

This approach makes sure the optimisation is based on clear assumptions, not on hidden settings.

---

### 2. Linear Programming Optimisation Engine

At its core, the framework uses Linear Programming (LP) to optimise budget allocation across platform-objective combinations.

The LP model:

* Maximises a weighted objective function derived from business priorities
* Respects all budgetary and policy constraints
* Produces transparent, reproducible allocations
* Supports multi-scenario evaluation without rewriting the model

This method aligns with how optimisation is actually used in real-world business and strategic situations.

---

### 3. KPI Forecasting Layer

Using historical performance ratios, the system forecasts expected KPI outcomes for each scenario:

* Forecasts are goal-aligned, not generic
* Outputs are tied directly to allocated budgets
* Results are aggregated by platform and KPI for clarity

The forecasting layer is kept simple and easy to understand, avoiding complex models, so results are precise.

---

### 4. Scenario Comparison

All scenarios are evaluated side-by-side, allowing decision-makers to assess:

* Trade-offs between risk and return
* Sensitivity of outcomes to scenario assumptions
* Stability of allocations across uncertainty levels

This helps decision-makers exercise their judgement rather than relying on a single metric.

---

### 5. Decision Interpretation Layer (Module 7)

A dedicated interpretation layer translates numerical results into decision-ready insights.

For each scenario, the system generates:

* An executive summary explaining the allocation logic
* A classification of the decision as corner-dominant, balanced, or scenario-sensitive
* A confidence score on a 0 to 100 scale
* Identification of binding and non-binding policy constraints
* Two contrasting plans: a performance-first allocation and a risk-managed alternative with an explicit efficiency trade-off
* Identified risks and practical recommendations

A global stability explanation identifies patterns that persist across scenarios, helping decision-makers identify robust strategies.

This layer uses clear rules and is easy to review, which builds trust.

---

### 6. Exportable Decision Artefacts

The system produces professional outputs suitable for stakeholders:

* PDF decision reports with structured summaries and tables
* Excel files containing all allocation and forecast data
* Clear separation between inputs, assumptions, and results

These outputs are made to help with accountability, review, and oversight.

---

## Technical Architecture

* Language: Python 3.11
* UI: Streamlit
* Optimisation: Linear Programming (PuLP with CBC solver)
* State Management: Wizard-based state controller
* Reporting: PDF (ReportLab), Excel (OpenPyXL)

The system is built to be modular and easy to expand, with each decision layer working as its own module.

---

## Running the App

```bash
pip install -r requirements.txt
streamlit run app.py
```

The application opens in your browser at `http://localhost:8501`.

---

## Tests

The test suite uses pytest:

```bash
pip install pytest
pytest -q
```

The same command runs automatically on every push and pull request via GitHub Actions.

---

## Project Structure

```text
.
├── app.py                  # UI orchestration and workflow control
├── core/
│   ├── wizard_state.py     # State management and step gating
│   └── kpi_config.py       # KPI definitions and mappings
├── modules/
│   ├── module1.py          # Objective selection and budget setup
│   ├── module2.py          # Platform selection and weighting
│   ├── module3.py          # Historical data ingestion
│   ├── module4.py          # Constraint preparation
│   ├── module5.py          # LP-based optimisation
│   ├── module6.py          # KPI forecasting and validation
│   └── module7.py          # Decision insight and interpretation
├── docs/                   # Detailed design and modelling documentation
├── tests/                  # Test suite
├── LICENSE                 # MIT License
├── CITATION.cff            # Citation metadata
├── requirements.txt
└── README.md
```

---

## Documentation

Detailed explanations of system behaviour and modelling choices are provided in the `docs/` directory:

* **modules.md** – role and responsibility of each module
* **scenarios.md** – scenario design and interpretation logic
* **decision_logic.md** – optimisation assumptions and modelling rationale

These documents expand on the architectural and decision principles outlined above.

---

## Intended Use

This framework is intended for:

* Marketing and growth decision-makers
* Analytics and strategy professionals
* SMEs operating under constrained budgets
* Researchers working on decision support systems and explainable optimisation

The system supports decisions; it does not automate them.

---

## Why This Project Matters

This project demonstrates applied expertise in:

* Decision Support Systems
* Constrained optimisation
* Data-driven strategy under uncertainty
* Translating analytics into managerial insight
* Responsible and explainable decision design

---

## Citation

If you use this software in academic work, please cite it using the metadata in `CITATION.cff`, or as follows:

> Rezvanjoo, H. (2026). *Marketing Budget Optimisation and Decision Support Framework* (Version 0.1.0) [Computer software]. https://github.com/Hoda834/REPO-NAME-HERE

---

## Feedback

The project is shared openly to invite technical review and constructive feedback, particularly on:

* Optimisation logic and constraints
* Scenario design and robustness
* Decision interpretability and usefulness

Issues and discussions are welcome.

---

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.

---

## Author

**Hoda Rezvanjoo**
Independent Researcher
ORCID: [0009-0006-3882-2669](https://orcid.org/0009-0006-3882-2669)
Website: [hodarezvanjoo.com](https://hodarezvanjoo.com)
