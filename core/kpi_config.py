from typing import Any, Dict, List

from core.wizard_state import GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


KIND_COUNT = "count"
KIND_RATE = "rate"


KPI_CONFIG: List[Dict[str, Any]] = [
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_IMPRESSION",  "kpi_label": "Impression",       "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_EN, "var": "FB_EN_ENGAGEMENT",  "kpi_label": "Engagement",       "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_WT, "var": "FB_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_LG, "var": "FB_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    {"platform": "ig", "goal": GOAL_AW, "var": "IG_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "ig", "goal": GOAL_EN, "var": "IG_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "ig", "goal": GOAL_WT, "var": "IG_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "ig", "goal": GOAL_LG, "var": "IG_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    {"platform": "li", "goal": GOAL_AW, "var": "LI_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "li", "goal": GOAL_EN, "var": "LI_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "li", "goal": GOAL_WT, "var": "LI_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "li", "goal": GOAL_LG, "var": "LI_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    {"platform": "yt", "goal": GOAL_AW, "var": "YT_AW_VIEWS",       "kpi_label": "Views",            "kind": KIND_COUNT},
    {"platform": "yt", "goal": GOAL_EN, "var": "YT_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "yt", "goal": GOAL_WT, "var": "YT_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "yt", "goal": GOAL_LG, "var": "YT_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
]


def get_kpi_rows(platform: str, goal: str) -> List[Dict[str, Any]]:
    return [row for row in KPI_CONFIG if row["platform"] == platform and row["goal"] == goal]


def get_kind(platform: str, var: str) -> str:
    for row in KPI_CONFIG:
        if row["platform"] == platform and row["var"] == var:
            return str(row.get("kind", KIND_COUNT))
    return KIND_COUNT
