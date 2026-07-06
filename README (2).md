# CLARO — Constrained Linear Allocation and Resource Optimiser

[![DOI](https://zenodo.org/badge/1114086677.svg)](https://doi.org/10.5281/zenodo.20517492)

*A decision-support framework for marketing budget allocation.*

## Overview

This project provides a complete decision support system that helps decision-makers allocate a limited marketing budget across platforms and objectives, accounting for real-world constraints.

Instead of looking at channels separately, the system treats marketing as a constrained optimisation problem. It integrates past performance data, business goals, and uncertainty to generate clear, structured recommendations.

The framework is designed to help managers make better decisions, not just to automate processes.

📖 Project wiki: https://github.com/Hoda834/digital-budget-optimisation-engine/wiki

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

The wizard collects every input the optimiser needs, with nothing hidden:

* Marketing objectives (Awareness, Engagement, Website Traffic, Lead Generation)
* Total budget, currency, and campaign duration
* Platform selection with priority ranking per objective
* Per-platform minimum spend and per-objective minimum budget
* Three scenarios (conservative / base / optimistic) with editable multipliers
* **Goal value weights** — what £ value the business places on one unit of each KPI (e.g. £200 per lead, £0.001 per impression). When present, drives utility-weighted optimisation instead of rank-based heuristics.
* **Test-and-learn reserve** — % of every scenario's budget held back for new audiences / creative tests (10–15% is standard strategist practice).
* **Seasonality multipliers** — per-goal expected productivity vs. historical (e.g. 0.4× for December reach if Q4 CPMs typically inflate).

All assumptions are visible on the results page and editable via the **Refine and re-solve** panel — no need to walk the wizard from step 1 to try a different floor or carve-out.

---

### 2. Linear Programming Optimisation Engine

A PuLP/CBC LP allocates budget across platform-objective cells, maximising weighted productivity subject to all declared constraints.

The LP:

* **Diminishing-returns brackets** per cell (25% / 35% / 40% of budget at yields 1.0 / 0.65 / 0.35) so a single cell can't absorb the whole plan even when it has the best productivity.
* **Per-goal productivity normalisation** so cross-objective comparisons are scale-free — the goal weights are the actual control knob.
* **Data-quality shrinkage** (James-Stein-style) pulls short-history platforms toward the cross-platform mean so a 7-day estimate doesn't get the same authority as a 365-day one.
* **Named, auditable constraints** — every floor and cap is named, and the LP returns binding constraints + shadow prices so you can see exactly what's shaping the allocation.

---

### 3. Platform Catalogue + CSV Import

Twelve built-in platforms with curated KPI configs.  Google appears as three distinct surfaces — Search, Display, and Performance Max — because their lead-gen productivities differ by an order of magnitude and lumping them obscures decisions a marketer actually needs to make.

**Every canonical KPI is a count** (the uniform-units refactor folded Engagement Rate / View Rate / CTR into summed count components like `likes + comments + shares + saves`).  This means all four KPIs on a platform share the same unit, so the LP doesn't mix percentages and totals.  Where the schema lists Purchases as a distinct conversion event, it has its own canonical alongside Leads / Conversions:

| Platform | KPIs (Awareness · Engagement · Traffic · Lead Gen) |
|---|---|
| Facebook | Reach · Engagement (reactions+comments+shares+saves+follows) · Link Clicks · Leads + Purchases |
| Instagram | Reach · Engagement (likes+comments+shares+saves+follows) · Link Clicks · Leads + Purchases |
| LinkedIn | Impressions · Engagement (reactions+comments+shares+followers) · Clicks · Leads |
| YouTube | Views · Engagement (likes+comments+shares+subscribers) · Clicks · Conversions + Purchases |
| Google Search | Impressions · *(no engagement KPI)* · Clicks · Conversions + Purchases |
| Google Display | Impressions · *(no engagement KPI)* · Clicks · Conversions + Purchases |
| Google Performance Max | Impressions · *(no engagement KPI)* · Clicks · Conversions + Purchases |
| TikTok | Video Views · Engagement (likes+comments+shares+saves+followers) · Clicks · Leads + Purchases |
| Pinterest | Impressions · Saves · Outbound Clicks · Leads + Checkouts |
| X (Twitter) | Impressions · Engagement (likes+replies+reposts+bookmarks+followers) · Link Clicks · Leads |
| Snapchat | Reach · Engagement (story opens+shares+subscribers) · Swipe-ups · Leads + Purchases |
| Reddit | Impressions · Engagement (upvotes+comments+shares+followers) · Clicks · Leads |

Google surfaces have no engagement KPI because CTR was a rate (violates uniform units within a platform) and "engaged clicks" would duplicate the Traffic KPI.

**CSV import** for every supported platform — drop the platform's standard export into the form and the parser:

* Sniffs encoding (UTF-8, UTF-8-BOM, Latin-1) and delimiter (`,` / `;` / `\t`)
* Filters totals rows (Google's `Total --`, Meta's summary rows)
* Composes canonical KPIs from raw columns with documented rationale (see below)
* **Legacy back-compat**: an older export with only an `Engagement Rate` column (no individual count breakouts) is still parsed — engagement count is derived as `rate × awareness_count`

---

### 4. KPI Composition (the layer between platform metrics and the LP)

Each platform reports its own metrics — Facebook's "engagement" is a different beast from LinkedIn's. The LP needs *one* number per canonical category, so this layer makes the composition explicit:

* Every canonical KPI declares its **components** (raw columns the platform exports), an **operator** (sum / first / max / mean), and a **rationale** explaining what's included and what's deliberately excluded to avoid double-counting.
* Example: `FB_EN_ENGAGEMENT = reactions + comments + shares + saves`. Link clicks are explicitly excluded — they're in the Traffic category, so including them here would double-count.
* When the broken-out columns aren't in the export, the parser falls back to the platform's bundled metric (Meta's "Post engagement") with a prominent warning that surfaces the double-count risk.
* **User override**: the "Customise composition" panel lets a marketer re-weight components per platform (count saves 3× because they're high-intent, reactions 0.5×, etc.) and recompose.

The composition is auditable — every parsed CSV returns a breakdown showing per-component values, the operator, and which fallback (if any) was taken.

---

### 5. Forecasting Layer with Honest Uncertainty

Module 6 produces per-KPI forecasts from the LP allocation. Uncertainty bands are **data-driven** (and are deliberately *not* called "confidence" — that concept is reserved for Module 7's diagnostic index, a separate concept):

* If Module 3 has ≥3 historical observations per KPI, the band is the sample coefficient of variation — true noise from data.
* Otherwise, the band scales by `√(30 / historical_days)` — a 90-day history produces a ~17% band, a 7-day history ~62%.
* Seasonality multipliers apply to count-KPI forecasts so the predicted volume matches what the LP optimised against.

---

### 6. Scenario Comparison and Monte Carlo Robustness

* Three scenarios (conservative / base / optimistic) run side-by-side with their own goal multipliers — optimistic raises conversion productivity, conservative raises upper-funnel.
* Test-and-learn reserve scales per scenario so `lp_used + reserve ≤ scenario_total` always holds.
* **Opt-in Monte Carlo** re-solves the base LP hundreds of times with productivities perturbed by their observed noise. Flags platforms whose share is sensitive to plausible data perturbation — the platforms whose rank should be treated with caution.

---

### 7. Decision Interpretation Layer (Module 7)

Configurable via `Module7Policy` — every threshold (corner concentration, diagnostic-index penalties, Plan B cap) is a named, defaulted field on a frozen dataclass, not a magic literal.

Outputs per scenario:

* Executive summary explaining the allocation logic
* Classification (Corner-dominant / Concentrated / Balanced / Scenario-sensitive)
* Diagnostic-index (40–100) penalising concentration, instability, missing forecasts, data-quality flags
* Binding vs non-binding constraints (with shadow prices)
* Plan A (performance-first) and Plan B (risk-managed) with the efficiency trade-off explicit
* Risks and recommendations
* **Forecast caveat** — every output carries a paragraph about attribution bias, last-click over-crediting, and the absence of incrementality modelling. The tool is honest about its own epistemic limits.

---

### 8. Exportable Decision Artefacts

* PDF decision reports with structured summaries and tables
* Excel files containing all allocation and forecast data
* Clear separation between inputs, assumptions, and results

---

## Technical Architecture

* Language: Python 3.11
* UI: Streamlit
* Optimisation: Linear Programming (PuLP with CBC solver)
* State Management: Wizard-based state controller
* Reporting: PDF (ReportLab), Excel (OpenPyXL)

The system is built to be modular and easy to expand, with each decision layer working as its own module.

---

## What This Tool Is (and Isn't)

**It is** a decision-support framework for media-mix planning: given declared constraints (budget, floors, goal values, seasonality), it produces an auditable allocation across platform-objective cells, with diagnostics for *why* the optimiser stopped there and how robust the recommendation is.

**It isn't** a marketing optimisation engine in the operator sense. Specifically:

* The CSV import is a last-mile parser, not an ETL pipeline. There are no platform-API connectors, no persistent staging, no scheduled refresh.
* Allocations are produced at the platform-objective level, not at the campaign / ad-set / creative level. The hard part of paid media starts *after* the channel split.
* The LP inherits whatever attribution is in your KPIs. If your platform-reported numbers over-credit Meta or under-credit Search (last-click bias), the LP will inherit that. Incrementality (would these conversions have happened anyway?) is not modelled.
* "Productivity" is a sample mean — there is no Bayesian recalibration between runs, no learning from outcomes, no causal estimation.

For the audiences this is designed for (strategists, agency planning leads, in-house quarterly planning, decision-science teaching), the scope is right-sized. For continuous budget optimisation against live platform data, you'd want a different product (Northbeam, Triple Whale, Funnel.io class).

---

## Running the App

```bash
pip install -r requirements.txt
streamlit run src/app.py
```

The application opens in your browser at `http://localhost:8501`.
A hosted demo is also available at https://claro-decision-support.streamlit.app/

A quick way to verify the pipeline without the UI:

```bash
PYTHONPATH=src python tests/behavioural_check.py
```

That runs 10+ realistic scenarios (B2B SaaS, leads-only, engagement-only, with and without goal values, with and without test-and-learn reserve, with and without seasonality) and prints the full M1→M7 output for each.

---

## Tests

The test suite uses pytest:

```bash
pip install pytest
pytest -q
```

The suite covers 225 cases across seven files — `tests/smoke_test.py` (happy-path and feature regressions), `tests/test_edge_cases.py` (encoding, malformed input, infeasibility, custom platforms, rate-only campaigns, multi-component composition, Monte Carlo, all-platforms stress), `tests/test_accuracy.py` (hand-computable numeric checks), `tests/test_bug_fixes.py` (named regression guards), `tests/test_plan_b_feasibility.py` (the risk-managed alternative stays within Module 2's floors), `tests/test_diagnostic_index_label.py` (narrative wording and score bounds), and `tests/test_examples_reproduce.py` (runs every script in `examples/` and pins its documented figures).

The same command runs automatically on every push and pull request via GitHub Actions.

---

## Examples and reproducibility

The `examples/` folder contains runnable, self-verifying examples. Every
script executes the full pipeline (no mocked components) and prints the
allocation, classification, and diagnostic index it produces.

```bash
PYTHONPATH=src python examples/case_study/run_case_study.py
PYTHONPATH=src python examples/case_study/run_data_sensitivity.py
PYTHONPATH=src python examples/case_study/run_parameter_sensitivity.py
PYTHONPATH=src python examples/minimal_examples/run_balanced_example.py
PYTHONPATH=src python examples/minimal_examples/run_concentrated_example.py
PYTHONPATH=src python examples/benchmark/run_benchmark.py
```

- `examples/case_study/` is a five-platform, two-objective allocation
  under three policy configurations. Its `campaign_data.xlsx` is a
  filled copy of the app's unified import template, so the same run can
  be reproduced by hand by uploading that exact workbook into Module 3
  of the guided interface. `SCENARIO.md` documents the inputs,
  provenance, and expected output. The two sensitivity scripts sweep
  the input data and the engine's own heuristic constants respectively.
- `examples/minimal_examples/` holds two small end-to-end cases: a
  balanced two-platform optimum, and a concentrated three-platform
  optimum where the risk-managed alternative visibly redistributes.
- `examples/benchmark/` times the LP solver across problem sizes.
  Absolute timings vary by hardware; the reproducible claim is the
  sub-linear, sub-100ms scaling.

---

## Project Structure

```text
.
├── src/                         # Source code
│   ├── app.py                   # Streamlit UI + wizard orchestration
│   ├── core/
│   │   ├── wizard_state.py      # State machine, custom platforms, goal values,
│   │   │                        #   carve-out, seasonality
│   │   ├── kpi_config.py        # Built-in + custom platform KPI catalogue
│   │   └── csv_import.py        # CSV parsing + composition layer
│   └── modules/
│       ├── module1.py           # Objective, budget, currency, duration,
│       │                        #   goal values, carve-out, seasonality
│       ├── module2.py           # Platform selection + priority ranks
│       ├── module3.py           # Historical KPIs (manual or via CSV)
│       ├── module4.py           # Cost-per-unit + outlier sweep
│       ├── module5.py           # LP with shrinkage, Monte Carlo, diagnostics
│       ├── module6.py           # Forecasts with data-driven uncertainty bands
│       └── module7.py           # Insights + Module7Policy
├── conftest.py                  # Puts src/ on sys.path for tests
├── docs/                        # Design + modelling documentation
├── examples/                    # Runnable, self-verifying examples
│   ├── case_study/
│   │   ├── campaign_data.xlsx           # Filled unified import workbook
│   │   ├── SCENARIO.md                  # Inputs, provenance, expected output
│   │   ├── run_case_study.py            # Three policy configurations
│   │   ├── run_data_sensitivity.py      # Input-data productivity sweep
│   │   └── run_parameter_sensitivity.py # Heuristic-parameter sweep (5 sub-analyses)
│   ├── minimal_examples/
│   │   ├── run_balanced_example.py      # Balanced two-platform optimum
│   │   └── run_concentrated_example.py  # Concentrated optimum + risk-managed plan
│   └── benchmark/
│       └── run_benchmark.py             # LP solve-time scaling
├── tests/
│   ├── conftest.py                  # Headless session-state fixture
│   ├── smoke_test.py                # Happy-path + feature regressions
│   ├── test_edge_cases.py           # Adversarial: encoding, malformed, infeasible
│   ├── test_accuracy.py             # Hand-computable numeric checks
│   ├── test_bug_fixes.py            # Named regression guards
│   ├── test_plan_b_feasibility.py   # Risk-managed plan stays within Module 2 floors
│   ├── test_diagnostic_index_label.py  # Narrative wording + score bounds
│   ├── test_examples_reproduce.py   # Runs every examples/ script, pins its figures
│   └── behavioural_check.py         # Realistic scenarios printed end-to-end
├── test_datasets/                   # Scenario fixtures + internal verifiers
│   ├── 01_b2b_saas_leadgen/ … 06_accuracy_hand_computable/
│   ├── _generate.py                 # Regenerates the fixture CSVs
│   ├── _run_scenarios.py            # Runs all scenarios end-to-end
│   └── _verify_lp.py                # Hand-checked LP cases
├── .github/workflows/tests.yml      # CI runs pytest on every push
├── LICENSE.txt
├── CITATION.cff
├── requirements.txt
└── README.md
```

---

## Documentation

Detailed explanations of system behaviour and modelling choices are provided in the `docs/` directory:

* **MODULES.md** – role and responsibility of each module
* **SCENARIOS.md** – scenario design and interpretation logic
* **DECISION_LOGIC.md** – optimisation assumptions and modelling rationale
* **CALIBRATION.md** – every hand-set numeric constant in the engine, its source / intuition, what changes if the value moves, and whether a user-facing override exists

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

> Rezvanjoo, H. (2026). *CLARO: Constrained Linear Allocation and Resource Optimiser — a Decision-Support Framework for Marketing Budget Allocation* (Version 0.2.1). https://github.com/Hoda834/digital-budget-optimisation-engine

---

## Feedback

The project is shared openly to invite technical review and constructive feedback, particularly on:

* Optimisation logic and constraints
* Scenario design and robustness
* Decision interpretability and usefulness

Issues and discussions are welcome.

---

## License

This project is released under the MIT License. See [LICENSE.txt](LICENSE.txt) for details.

---

## Author

**Hoda Rezvanjoo**
Independent Researcher
ORCID: [0009-0006-3882-2669](https://orcid.org/0009-0006-3882-2669)
Website: [hodarezvanjoo.com](https://hodarezvanjoo.com)
