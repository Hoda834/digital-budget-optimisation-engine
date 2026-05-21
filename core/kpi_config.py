from typing import Any, Dict, List, Optional

from core.wizard_state import GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


KIND_COUNT = "count"
KIND_RATE = "rate"


# KPI catalogue.  Each row pairs a (platform, goal) cell with the specific
# KPI a marketer would track on that platform for that objective, and
# whether the metric is a count (units/£) or a rate (dimensionless).
KPI_CONFIG: List[Dict[str, Any]] = [
    # ── Meta / Facebook ────────────────────────────────────────────────────
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_IMPRESSION",  "kpi_label": "Impression",       "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_EN, "var": "FB_EN_ENGAGEMENT",  "kpi_label": "Engagement",       "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_WT, "var": "FB_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "fb", "goal": GOAL_LG, "var": "FB_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── Instagram ──────────────────────────────────────────────────────────
    {"platform": "ig", "goal": GOAL_AW, "var": "IG_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "ig", "goal": GOAL_EN, "var": "IG_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "ig", "goal": GOAL_WT, "var": "IG_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "ig", "goal": GOAL_LG, "var": "IG_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── LinkedIn ───────────────────────────────────────────────────────────
    {"platform": "li", "goal": GOAL_AW, "var": "LI_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "li", "goal": GOAL_EN, "var": "LI_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "li", "goal": GOAL_WT, "var": "LI_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "li", "goal": GOAL_LG, "var": "LI_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── YouTube ────────────────────────────────────────────────────────────
    {"platform": "yt", "goal": GOAL_AW, "var": "YT_AW_VIEWS",       "kpi_label": "Views",            "kind": KIND_COUNT},
    {"platform": "yt", "goal": GOAL_EN, "var": "YT_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "yt", "goal": GOAL_WT, "var": "YT_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "yt", "goal": GOAL_LG, "var": "YT_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── TikTok ─────────────────────────────────────────────────────────────
    {"platform": "tt", "goal": GOAL_AW, "var": "TT_AW_VIEWS",       "kpi_label": "Video Views",      "kind": KIND_COUNT},
    {"platform": "tt", "goal": GOAL_EN, "var": "TT_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "tt", "goal": GOAL_WT, "var": "TT_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "tt", "goal": GOAL_LG, "var": "TT_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── Pinterest ──────────────────────────────────────────────────────────
    {"platform": "pt", "goal": GOAL_AW, "var": "PT_AW_IMPRESSION",  "kpi_label": "Impression",       "kind": KIND_COUNT},
    {"platform": "pt", "goal": GOAL_EN, "var": "PT_EN_SAVES",       "kpi_label": "Saves",            "kind": KIND_COUNT},
    {"platform": "pt", "goal": GOAL_WT, "var": "PT_WT_CLICKS",      "kpi_label": "Outbound Clicks",  "kind": KIND_COUNT},
    {"platform": "pt", "goal": GOAL_LG, "var": "PT_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── X / Twitter ────────────────────────────────────────────────────────
    {"platform": "tw", "goal": GOAL_AW, "var": "TW_AW_IMPRESSION",  "kpi_label": "Impression",       "kind": KIND_COUNT},
    {"platform": "tw", "goal": GOAL_EN, "var": "TW_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "tw", "goal": GOAL_WT, "var": "TW_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "tw", "goal": GOAL_LG, "var": "TW_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── Snapchat ───────────────────────────────────────────────────────────
    {"platform": "sn", "goal": GOAL_AW, "var": "SN_AW_REACH",       "kpi_label": "Reach",            "kind": KIND_COUNT},
    {"platform": "sn", "goal": GOAL_EN, "var": "SN_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "sn", "goal": GOAL_WT, "var": "SN_WT_CLICKS",      "kpi_label": "Swipe-ups",        "kind": KIND_COUNT},
    {"platform": "sn", "goal": GOAL_LG, "var": "SN_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── Reddit ─────────────────────────────────────────────────────────────
    {"platform": "rd", "goal": GOAL_AW, "var": "RD_AW_IMPRESSION",  "kpi_label": "Impression",       "kind": KIND_COUNT},
    {"platform": "rd", "goal": GOAL_EN, "var": "RD_EN_ENGRATERATE", "kpi_label": "Engagement Rate",  "kind": KIND_RATE},
    {"platform": "rd", "goal": GOAL_WT, "var": "RD_WT_CLICKS",      "kpi_label": "Link Clicks",      "kind": KIND_COUNT},
    {"platform": "rd", "goal": GOAL_LG, "var": "RD_LG_LEADS",       "kpi_label": "Leads",            "kind": KIND_COUNT},
    # ── Google Search (keyword auctions, intent-driven) ────────────────────
    # Search has the steepest CTR + Conversion productivity of any Google
    # surface — keyword intent does most of the work.  Reviewers care that
    # this lives separately from Display because lumping them obscures
    # ~10× differences in lead-gen productivity.
    {"platform": "go_search",  "goal": GOAL_AW, "var": "GO_SEARCH_AW_IMPRESSION",  "kpi_label": "Impression",         "kind": KIND_COUNT},
    {"platform": "go_search",  "goal": GOAL_EN, "var": "GO_SEARCH_EN_CTR",         "kpi_label": "Click-through Rate", "kind": KIND_RATE},
    {"platform": "go_search",  "goal": GOAL_WT, "var": "GO_SEARCH_WT_CLICKS",      "kpi_label": "Clicks",             "kind": KIND_COUNT},
    {"platform": "go_search",  "goal": GOAL_LG, "var": "GO_SEARCH_LG_CONVERSIONS", "kpi_label": "Conversions",        "kind": KIND_COUNT},
    # ── Google Display Network (CPM placements, lower intent) ──────────────
    # Display is upper-funnel — high reach per pound, low conversion rate.
    # Same KPI shape as Search so the LP can compare cells, but expect very
    # different productivity numbers in Module 3 (Display impressions/£ will
    # be much higher than Search; Search conversions/£ much higher than
    # Display).
    {"platform": "go_display", "goal": GOAL_AW, "var": "GO_DISPLAY_AW_IMPRESSION",  "kpi_label": "Impression",         "kind": KIND_COUNT},
    {"platform": "go_display", "goal": GOAL_EN, "var": "GO_DISPLAY_EN_CTR",         "kpi_label": "Click-through Rate", "kind": KIND_RATE},
    {"platform": "go_display", "goal": GOAL_WT, "var": "GO_DISPLAY_WT_CLICKS",      "kpi_label": "Clicks",             "kind": KIND_COUNT},
    {"platform": "go_display", "goal": GOAL_LG, "var": "GO_DISPLAY_LG_CONVERSIONS", "kpi_label": "Conversions",        "kind": KIND_COUNT},
    # ── Google Performance Max (Smart Bidding across all Google surfaces) ──
    # PMax mixes Search, Display, YouTube, Shopping and Maps behind a single
    # campaign type.  We keep it as a separate platform so the user reports
    # the *blended* productivity their PMax campaigns actually deliver —
    # rather than guessing how to split a PMax CSV row across the other two.
    {"platform": "go_pmax",    "goal": GOAL_AW, "var": "GO_PMAX_AW_IMPRESSION",  "kpi_label": "Impression",         "kind": KIND_COUNT},
    {"platform": "go_pmax",    "goal": GOAL_EN, "var": "GO_PMAX_EN_CTR",         "kpi_label": "Click-through Rate", "kind": KIND_RATE},
    {"platform": "go_pmax",    "goal": GOAL_WT, "var": "GO_PMAX_WT_CLICKS",      "kpi_label": "Clicks",             "kind": KIND_COUNT},
    {"platform": "go_pmax",    "goal": GOAL_LG, "var": "GO_PMAX_LG_CONVERSIONS", "kpi_label": "Conversions",        "kind": KIND_COUNT},
]


def get_kpi_rows(platform: str, goal: str) -> List[Dict[str, Any]]:
    return [row for row in KPI_CONFIG if row["platform"] == platform and row["goal"] == goal]


def get_kind(platform: str, var: str) -> str:
    for row in KPI_CONFIG:
        if row["platform"] == platform and row["var"] == var:
            return str(row.get("kind", KIND_COUNT))
    return KIND_COUNT


