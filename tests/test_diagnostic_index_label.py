"""Lock the renamed user-facing label.

The interpretation layer's score is presented to users as the "diagnostic
index" (v0.2.1). This test guards against a regression that reintroduces
the older "confidence score" wording in the narrative outputs, which would
desync the software from the manuscript.
"""
from __future__ import annotations

from core.wizard_state import WizardState
from modules.module1 import complete_module1_and_advance
from modules.module2 import run_module2
from modules.module3 import finalise_module3_from_inputs
from modules.module4 import run_module4
from modules.module5 import run_module5
from modules.module6 import run_module6
from modules.module7 import run_module7


def _pipeline():
    s = WizardState()
    complete_module1_and_advance(
        s, raw_objectives=["lg"], raw_budget=20000.0, raw_duration_days=30,
        raw_goal_values=None, raw_test_and_learn_pct=0.0, raw_seasonality_index=None)
    run_module2(s, selected_platforms=["li", "fb"], priorities_input={
        "li": {"priority_1": "lg"}, "fb": {"priority_1": "lg"}})
    finalise_module3_from_inputs(s, platform_inputs={
        "li": {"budget": 9500.0, "kpis": {"LI_LG_LEADS": 380.0}},
        "fb": {"budget": 4200.0, "kpis": {"FB_LG_LEADS": 30.0}}})
    run_module4(s); run_module5(s); run_module6(s)
    b = s.module5_scenario_bundle
    fc = (s.module6_scenario_result.results_by_scenario if s.module6_scenario_result else {})
    return run_module7(s, b, fc)


def test_narrative_uses_diagnostic_index_not_confidence():
    ins = _pipeline()
    blobs = []
    for si in ins.scenario_insights.values():
        blobs.append(getattr(si, "executive_summary", "") or "")
        blobs.extend(getattr(si, "risks", []) or [])
    text = "\n".join(blobs).lower()
    assert "diagnostic index" in text, "expected 'diagnostic index' in narrative output"
    assert "confidence score" not in text, "'confidence score' wording should be gone from narrative"


def test_score_value_still_present_and_bounded():
    ins = _pipeline()
    si = next(iter(ins.scenario_insights.values()))
    score = si.confidence_score  # field name unchanged in v0.2.1 (label-only rename)
    assert 40 <= int(score) <= 100
