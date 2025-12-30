from modules.module6 import Module6Result


def test_forecast_values_are_non_negative():
    rows = [
        type("Row", (), {
            "platform": "fb",
            "objective": "aw",
            "kpi_name": "fb_aw_impressions",
            "allocated_budget": 500,
            "predicted_kpi": 1000,
        })
    ]

    res = Module6Result(rows=rows)

    for r in res.rows:
        assert r.predicted_kpi >= 0
