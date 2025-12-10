# digital-budget-optimisation-engine
A full end-to-end optimisation wizard using Streamlit, Python LP modelling and KPI forecasting to intelligently allocate marketing budget across platforms.
A multi-stage optimisation wizard for intelligent digital budget planning.

This project implements a full analytical pipeline to optimise multi-platform marketing budgets using:

- Linear Programming (LP)
- KPI ratio modelling
- Cross-platform goal prioritisation
- Forecasting & automated insight generation
- Streamlit UI for interactive exploration
- Automated PDF report generation (with charts)

## Features

### Module 1 – Goal Selection & Budget Setup
Users select strategic objectives and specify overall budget (must be > 1).

### Module 2 – Platform Selection & Priority Weighting
Each platform (Facebook, Instagram, LinkedIn, YouTube) receives goal weights based on business priorities.

### Module 3 – Historical Data Collection
Collects historical KPI values per platform–goal and computes KPI-per-budget ratios.

### Module 4 – Data Transformation Layer
Builds a unified table and cost-per-unit per platform–goal–KPI to feed the optimisation model.

### Module 5 – Linear Programming Optimisation
Solves a continuous LP model to maximise weighted KPI output under a total budget constraint.

### Module 6 – Forecasting Engine
Predicts KPI outcomes based on optimal allocation, generates narrative insights, and exports a PDF report.

## Running the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
python tests/smoke_test.py
```

## Project structure

```text
marketing-allocation-optimizer/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── modules/
│   ├── module1.py
│   ├── module2.py
│   ├── module3.py
│   ├── module4.py
│   ├── module5.py
│   └── module6.py
├── core/
│   ├── wizard_state.py
│   ├── kpi_config.py
│   └── utils.py
├── reports/
│   └── samples/
│       └── example-output.pdf
├── screenshots/
│   ├── module1.png
│   ├── module2.png
│   ├── results.png
│   └── pdf_sample.png
└── tests/
    └── smoke_test.py
```

> NOTE: The Python files in this template are thin wrappers. Replace the placeholders with your existing logic from your local project.

## Author

Created by **Hoda Rezvanjoo**  
Insight Analyst & Optimisation Model Developer  
Portfolio: https://hodarezvanjoo.com

