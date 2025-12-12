from typing import Any, Dict, List

from core.wizard_state import GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


KPI_CONFIG: List[Dict[str, Any]] = [
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_REACH", "kpi_label": "Reach"},
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_IMPRESSION", "kpi_label": "Impression"},
    {"platform": "fb", "goal": GOAL_EN, "var": "FB_EN_ENGAGEMENT", "kpi_label": "Engagement"},
    {"platform": "fb", "goal": GOAL_WT, "var": "FB_WT_CLICKS", "kpi_label": "Link Clicks"},
    {"platform": "fb", "goal": GOAL_LG, "var": "FB_LG_LEADS", "kpi_label": "Leads"},
    {"platform": "ig", "goal": GOAL_AW, "var": "IG_AW_REACH", "kpi_label": "Reach"},
    {"platform": "ig", "goal": GOAL_EN, "var": "IG_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "ig", "goal": GOAL_WT, "var": "IG_WT_CLICKS", "kpi_label": "Link Clicks"},
    {"platform": "ig", "goal": GOAL_LG, "var": "IG_LG_LEADS", "kpi_label": "Leads"},
    {"platform": "li", "goal": GOAL_AW, "var": "LI_AW_REACH", "kpi_label": "Reach"},
    {"platform": "li", "goal": GOAL_EN, "var": "LI_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "li", "goal": GOAL_LG, "var": "LI_LG_LEADS", "kpi_label": "Leads"},
    {"platform": "yt", "goal": GOAL_AW, "var": "YT_AW_VIEWS", "kpi_label": "Views"},
    {"platform": "yt", "goal": GOAL_EN, "var": "YT_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "yt", "goal": GOAL_WT, "var": "YT_WT_CLICKS", "kpi_label": "Link Clicks"},
    {"platform": "yt", "goal": GOAL_LG, "var": "YT_LG_LEADS", "kpi_label": "Leads"},
]
