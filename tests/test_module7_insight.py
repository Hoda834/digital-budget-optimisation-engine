def test_insight_has_summary():
    from modules.module7 import ScenarioInsight

    ins = ScenarioInsight(
        executive_summary="Budget is concentrated on Facebook for awareness.",
        risks=["Over-reliance on single platform"],
        recommendations=["Monitor performance weekly"],
    )

    assert ins.executive_summary.strip() != ""
    assert len(ins.recommendations) > 0
