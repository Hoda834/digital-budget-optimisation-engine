from typing import Any, Dict, List, Optional

from core.wizard_state import GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


KIND_COUNT = "count"
KIND_RATE = "rate"


# Built-in KPI catalogue.  Each row pairs a (platform, goal) cell with the
# specific KPI a marketer would track on that platform for that objective,
# and whether the metric is a count (units/£) or a rate (dimensionless).
# Custom platforms registered via state.custom_platforms extend this set at
# runtime; see effective_kpi_config().
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
]


def get_kpi_rows(platform: str, goal: str) -> List[Dict[str, Any]]:
    return [row for row in KPI_CONFIG if row["platform"] == platform and row["goal"] == goal]


def get_kind(platform: str, var: str) -> str:
    for row in KPI_CONFIG:
        if row["platform"] == platform and row["var"] == var:
            return str(row.get("kind", KIND_COUNT))
    return KIND_COUNT


def effective_kpi_config(state: Any = None) -> List[Dict[str, Any]]:
    """Return the built-in KPI_CONFIG plus any custom-platform rows registered
    on the WizardState.  Modules that loop over KPI rows should consult this
    function instead of KPI_CONFIG directly so custom platforms are honoured.
    """
    if state is None:
        return list(KPI_CONFIG)
    custom = getattr(state, "custom_platforms", None) or []
    extra: List[Dict[str, Any]] = []
    for plat in custom:
        for row in (plat.get("kpis") or []):
            extra.append({
                "platform": plat.get("code"),
                "goal": row.get("goal"),
                "var": row.get("var"),
                "kpi_label": row.get("kpi_label", row.get("var", "")),
                "kind": row.get("kind", KIND_COUNT),
            })
    return list(KPI_CONFIG) + extra


def effective_get_kpi_rows(state: Any, platform: str, goal: str) -> List[Dict[str, Any]]:
    return [r for r in effective_kpi_config(state)
            if r["platform"] == platform and r["goal"] == goal]
