"""
Generate 5 self-contained test datasets for the optimisation engine.

Each scenario writes:
  test_datasets/<scenario>/<platform>.csv      one CSV per platform, columns
                                               match the per-platform template
                                               so the app's CSV importer parses
                                               them without manual mapping.
  test_datasets/<scenario>/SCENARIO.md         wizard inputs + intent of the
                                               scenario (what it stresses).

Run from repo root:
  PYTHONPATH=. python test_datasets/_generate.py
"""
from __future__ import annotations

import os
from typing import Dict, List

from core.csv_import import generate_csv_template


HERE = os.path.dirname(os.path.abspath(__file__))


def _columns(platform: str) -> List[str]:
    return generate_csv_template(platform).decode("utf-8").splitlines()[0].split(",")


def _row(platform: str, values: Dict[str, float | int | str]) -> str:
    """Build one data row aligned to the template's column order.
    Any column not supplied in `values` defaults to 0."""
    cols = _columns(platform)
    cells: List[str] = []
    for col in cols:
        v = values.get(col, 0)
        if isinstance(v, float):
            cells.append(f"{v:.2f}".rstrip("0").rstrip("."))
        else:
            cells.append(str(v))
    return ",".join(cells)


def _write_csv(scenario: str, platform: str, rows: List[Dict[str, float | int | str]]) -> None:
    out_dir = os.path.join(HERE, scenario)
    os.makedirs(out_dir, exist_ok=True)
    header = ",".join(_columns(platform))
    body = "\n".join(_row(platform, r) for r in rows)
    with open(os.path.join(out_dir, f"{platform}.csv"), "w", encoding="utf-8") as f:
        f.write(header + "\n" + body + "\n")


def _write_readme(scenario: str, text: str) -> None:
    out_dir = os.path.join(HERE, scenario)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "SCENARIO.md"), "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 1 — B2B SaaS lead generation (small budget, intent-led platforms)
# Tests: lead-gen weighting, B2B platforms, goal-value-driven LP, short history.
# ──────────────────────────────────────────────────────────────────────────
def scenario_1_b2b_saas() -> None:
    s = "01_b2b_saas_leadgen"

    _write_csv(s, "li", [{
        "Impression": 1_250_000, "Reach": 380_000, "Video View": 0,
        "Reactions": 5_400, "Comments": 410, "Shares": 220, "Followers": 180,
        "Click": 14_800, "Website Visit": 9_200,
        "Leads": 320, "Conversions": 0,
        "Total Spent": 9_500, "Number Of Days": 30,
    }])
    _write_csv(s, "go_search", [{
        "Impr.": 480_000, "Clicks": 22_400, "Conversions": 410,
        "Leads": 0, "Calls": 42, "Purchases": 0,
        "Cost": 8_800, "Number Of Days": 30,
    }])
    _write_csv(s, "fb", [{
        "Reach": 540_000, "Impression": 1_400_000, "Video View": 220_000,
        "Post Reactions": 6_800, "Comments": 720, "Shares": 410, "Saves": 280, "Follows": 95,
        "Link Click": 9_400, "Landing Page View": 7_100, "Page View": 0,
        "On-facebook Lead": 88, "Conversions": 0, "Purchases": 0,
        "Amount Spent": 4_200, "Number Of Days": 30,
    }])

    _write_readme(s, """
# Scenario 1 — B2B SaaS lead generation

**Wizard inputs**

- Objective: Lead Generation (primary), Awareness (secondary)
- Budget: £25,000
- Duration: 30 days
- Currency: GBP
- Platforms: LinkedIn (rank 1), Google Search (rank 2), Facebook (rank 3)
- Per-platform minima: LI £5,000 · Google Search £4,000 · FB £1,500
- Goal values: £200 per lead, £0.002 per impression
- Test-and-learn reserve: 12%
- Seasonality: 1.0 (no adjustment)
- Scenario multipliers: defaults

**What this stresses**

- LP must prefer LinkedIn + Google Search for lead-gen despite Facebook's
  larger raw volume — goal weighting overrides rank-only logic.
- LinkedIn data is the strongest historical signal (30 days, clean composition);
  shrinkage should leave LI productivity largely untouched.
- Google Search has no engagement KPI — verifies the omitted-cell path.
- Expected: ~50–60% LinkedIn, ~25–35% Google Search, ~10–20% Facebook.
""")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 2 — D2C e-commerce, purchase-led (mid budget, consumer mix)
# Tests: separate Purchases canonical, multi-platform consumer, PMax.
# ──────────────────────────────────────────────────────────────────────────
def scenario_2_dtc_ecommerce() -> None:
    s = "02_dtc_ecommerce_purchases"

    _write_csv(s, "go_pmax", [{
        "Impr.": 3_200_000, "View": 480_000, "Clicks": 58_000,
        "Conversions": 210, "Leads": 0, "Store Visit": 0,
        "Purchases": 1_840, "Cost": 22_000, "Number Of Days": 60,
    }])
    _write_csv(s, "fb", [{
        "Reach": 1_900_000, "Impression": 6_400_000, "Video View": 1_100_000,
        "Post Reactions": 48_000, "Comments": 5_200, "Shares": 3_400, "Saves": 2_900, "Follows": 1_200,
        "Link Click": 96_000, "Landing Page View": 71_000, "Page View": 0,
        "On-facebook Lead": 0, "Conversions": 0, "Purchases": 1_420,
        "Amount Spent": 18_000, "Number Of Days": 60,
    }])
    _write_csv(s, "ig", [{
        "Reach": 1_650_000, "Impression": 5_200_000, "Reel View": 980_000,
        "Likes": 62_000, "Comments": 7_800, "Shares": 5_100, "Saves": 9_400, "Follows": 2_400,
        "Website Click": 72_000, "Profile Visit": 41_000,
        "Leads": 0, "Purchases": 1_180,
        "Amount Spent": 14_000, "Number Of Days": 60,
    }])
    _write_csv(s, "tt", [{
        "Video Views": 5_800_000, "Reach": 1_400_000,
        "Likes": 110_000, "Comments": 9_200, "Shares": 14_000, "Saves": 7_200, "Followers": 3_100,
        "Destination Click": 48_000, "Profile View": 22_000,
        "Leads": 0, "Purchases": 640,
        "Cost": 12_000, "Number Of Days": 60,
    }])
    _write_csv(s, "pt", [{
        "Impression": 2_100_000, "Video View": 180_000,
        "Saves": 18_000, "Outbound Click": 19_000, "Pin Click": 24_000,
        "Leads": 0, "Checkouts": 420,
        "Cost": 9_000, "Number Of Days": 60,
        "Closeups": 31_000, "Followers": 1_400,
    }])

    _write_readme(s, """
# Scenario 2 — D2C e-commerce, purchase-led

**Wizard inputs**

- Objective: Lead Generation (purchases-led), Website Traffic
- Budget: £80,000
- Duration: 60 days
- Currency: GBP
- Platforms: Google PMax (rank 1), Meta FB (rank 2), Meta IG (rank 2),
  TikTok (rank 3), Pinterest (rank 4)
- Per-platform minima: PMax £15k · FB £8k · IG £6k · TT £6k · PT £4k
- Goal values: £45 per purchase, £0.40 per link click
- Test-and-learn reserve: 15%
- Seasonality: 1.2 for Awareness (peak season), 1.0 elsewhere
- Scenario multipliers: defaults

**What this stresses**

- The new Purchases canonical (separate from Leads / Conversions) — each
  platform reports purchases on its own line; LP should treat them
  comparably across surfaces.
- Pinterest's `Checkouts` → `PT_LG_PURCHASES` rename path.
- Cross-platform consumer mix where IG and FB look similar but IG has a
  stronger save/share signal (engagement KPI) and weaker purchase volume.
- Expected: PMax dominant on purchases, FB/IG sharing the upper-funnel,
  TT and PT trimmed by diminishing-returns brackets.
""")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 3 — Brand-awareness launch (large budget, upper-funnel only)
# Tests: awareness-heavy, video-led, no lead-gen, infeasibility avoidance.
# ──────────────────────────────────────────────────────────────────────────
def scenario_3_brand_launch() -> None:
    s = "03_brand_launch_awareness"

    _write_csv(s, "yt", [{
        "Views": 8_400_000, "Impression": 14_000_000, "Unique Viewer": 5_200_000,
        "Likes": 96_000, "Comments": 4_400, "Shares": 11_000, "Subscribers": 14_500,
        "Clicks": 38_000, "Card Click": 0, "End Screen Click": 0,
        "Conversions": 0, "Purchases": 0,
        "Cost": 62_000, "Number Of Days": 45,
    }])
    _write_csv(s, "tt", [{
        "Video Views": 12_500_000, "Reach": 3_800_000,
        "Likes": 240_000, "Comments": 18_000, "Shares": 31_000, "Saves": 9_400, "Followers": 6_200,
        "Destination Click": 41_000, "Profile View": 88_000,
        "Leads": 0, "Purchases": 0,
        "Cost": 48_000, "Number Of Days": 45,
    }])
    _write_csv(s, "ig", [{
        "Reach": 4_100_000, "Impression": 12_800_000, "Reel View": 3_200_000,
        "Likes": 180_000, "Comments": 14_000, "Shares": 9_200, "Saves": 12_000, "Follows": 4_400,
        "Website Click": 22_000, "Profile Visit": 64_000,
        "Leads": 0, "Purchases": 0,
        "Amount Spent": 41_000, "Number Of Days": 45,
    }])
    _write_csv(s, "sn", [{
        "Reach": 2_200_000, "Impression": 6_800_000,
        "Story Opens": 84_000, "Shares": 3_100, "Subscribers": 1_900,
        "Swipe-up": 12_000, "Leads": 0, "Purchases": 0,
        "Cost": 22_000, "Number Of Days": 45,
    }])
    _write_csv(s, "tw", [{
        "Impression": 4_800_000, "Video View": 1_100_000,
        "Likes": 38_000, "Replies": 2_100, "Reposts": 7_400, "Bookmarks": 4_200, "Followers": 1_800,
        "Link Click": 9_400, "Profile Visit": 14_000,
        "Leads": 0,
        "Cost": 18_000, "Number Of Days": 45,
    }])

    _write_readme(s, """
# Scenario 3 — Brand-awareness launch

**Wizard inputs**

- Objective: Awareness (primary), Engagement (secondary)
- Budget: £200,000
- Duration: 45 days
- Currency: GBP
- Platforms: YouTube (rank 1), TikTok (rank 1), Instagram (rank 2),
  Snapchat (rank 3), X (rank 3)
- Per-platform minima: YT £25k · TT £25k · IG £20k · SN £8k · X £8k
- Goal values: £0.006 per reach/impression, £0.10 per engagement
- Test-and-learn reserve: 15%
- Seasonality: 0.9 (launch window, slightly inflated CPMs)
- Scenario multipliers: conservative {AW: 0.85}, base 1.0, optimistic {AW: 1.15}

**What this stresses**

- Awareness + Engagement only, no lead-gen — LP should leave the LG goal row
  entirely absent.
- Video-led mix: YT and TT have very different cost-per-view profiles;
  diminishing-returns brackets should prevent either from absorbing >40%.
- Snapchat composition (Story Opens + Shares + Subscribers) — verifies the
  non-obvious engagement KPI.
- Expected: TT and YT roughly co-dominant on awareness; IG carries
  engagement; SN and X get minimums + small top-ups.
""")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 4 — Engagement / community building (mid budget, social-led)
# Tests: engagement composition across diverse platforms (sum operator).
# ──────────────────────────────────────────────────────────────────────────
def scenario_4_community_engagement() -> None:
    s = "04_community_engagement"

    _write_csv(s, "ig", [{
        "Reach": 880_000, "Impression": 2_400_000, "Reel View": 720_000,
        "Likes": 84_000, "Comments": 9_800, "Shares": 7_200, "Saves": 14_000, "Follows": 3_400,
        "Website Click": 11_000, "Profile Visit": 38_000,
        "Leads": 0, "Purchases": 0,
        "Amount Spent": 14_000, "Number Of Days": 60,
    }])
    _write_csv(s, "tt", [{
        "Video Views": 4_800_000, "Reach": 1_100_000,
        "Likes": 220_000, "Comments": 24_000, "Shares": 41_000, "Saves": 11_000, "Followers": 5_400,
        "Destination Click": 19_000, "Profile View": 62_000,
        "Leads": 0, "Purchases": 0,
        "Cost": 12_000, "Number Of Days": 60,
    }])
    _write_csv(s, "rd", [{
        "Impression": 1_400_000, "Video View": 220_000,
        "Upvotes": 18_000, "Comments": 7_400, "Shares": 1_900, "Followers": 2_200,
        "Clicks": 9_800,
        "Leads": 0, "Conversions": 0,
        "Cost": 8_000, "Number Of Days": 60,
    }])
    _write_csv(s, "tw", [{
        "Impression": 1_800_000, "Video View": 410_000,
        "Likes": 24_000, "Replies": 3_400, "Reposts": 9_800, "Bookmarks": 5_200, "Followers": 2_100,
        "Link Click": 7_800, "Profile Visit": 18_000,
        "Leads": 0,
        "Cost": 6_000, "Number Of Days": 60,
    }])

    _write_readme(s, """
# Scenario 4 — Community building / engagement-led

**Wizard inputs**

- Objective: Engagement (primary), Awareness (secondary)
- Budget: £40,000
- Duration: 60 days
- Currency: GBP
- Platforms: Instagram (rank 1), TikTok (rank 1), Reddit (rank 2), X (rank 3)
- Per-platform minima: IG £8k · TT £8k · RD £4k · X £3k
- Goal values: £0.25 per engagement, £0.004 per reach/impression
- Test-and-learn reserve: 10%
- Seasonality: 1.0
- Scenario multipliers: defaults

**What this stresses**

- Engagement KPI is a different composite on every platform (sum of
  different component sets). Tests the composition layer end-to-end.
- TikTok engagement volume is an order of magnitude above IG — without
  per-goal productivity normalisation TT would absorb everything; with
  normalisation it should share the budget with IG.
- Reddit's `Upvotes + Comments + Shares + Followers` should be parsed and
  not double-counted against the Awareness Impression column.
- Expected: TT slightly ahead on engagement productivity, IG strong on
  saves/shares ratio, RD and X trimmed by diminishing returns.
""")


# ──────────────────────────────────────────────────────────────────────────
# Scenario 5 — Omnichannel multi-objective (large budget, all 4 goals)
# Tests: full-platform stress, three Google surfaces, all goals active.
# ──────────────────────────────────────────────────────────────────────────
def scenario_5_omnichannel() -> None:
    s = "05_omnichannel_all_goals"

    _write_csv(s, "go_search", [{
        "Impr.": 1_800_000, "Clicks": 84_000, "Conversions": 1_240,
        "Leads": 0, "Calls": 180, "Purchases": 980,
        "Cost": 32_000, "Number Of Days": 90,
    }])
    _write_csv(s, "go_display", [{
        "Impr.": 14_000_000, "View": 0, "Clicks": 32_000,
        "Conversions": 180, "Purchases": 92,
        "Cost": 14_000, "Number Of Days": 90,
    }])
    _write_csv(s, "go_pmax", [{
        "Impr.": 6_400_000, "View": 1_100_000, "Clicks": 78_000,
        "Conversions": 420, "Leads": 0, "Store Visit": 0,
        "Purchases": 1_640, "Cost": 24_000, "Number Of Days": 90,
    }])
    _write_csv(s, "fb", [{
        "Reach": 3_200_000, "Impression": 9_400_000, "Video View": 1_600_000,
        "Post Reactions": 71_000, "Comments": 8_400, "Shares": 5_900, "Saves": 4_100, "Follows": 1_800,
        "Link Click": 88_000, "Landing Page View": 64_000, "Page View": 0,
        "On-facebook Lead": 410, "Conversions": 0, "Purchases": 720,
        "Amount Spent": 22_000, "Number Of Days": 90,
    }])
    _write_csv(s, "ig", [{
        "Reach": 2_900_000, "Impression": 8_100_000, "Reel View": 1_900_000,
        "Likes": 84_000, "Comments": 11_000, "Shares": 7_400, "Saves": 14_000, "Follows": 3_900,
        "Website Click": 64_000, "Profile Visit": 38_000,
        "Leads": 220, "Purchases": 510,
        "Amount Spent": 18_000, "Number Of Days": 90,
    }])
    _write_csv(s, "li", [{
        "Impression": 1_900_000, "Reach": 540_000, "Video View": 0,
        "Reactions": 9_400, "Comments": 720, "Shares": 410, "Followers": 280,
        "Click": 22_000, "Website Visit": 14_000,
        "Leads": 380, "Conversions": 0,
        "Total Spent": 12_000, "Number Of Days": 90,
    }])
    _write_csv(s, "yt", [{
        "Views": 6_200_000, "Impression": 11_000_000, "Unique Viewer": 3_400_000,
        "Likes": 71_000, "Comments": 3_900, "Shares": 9_400, "Subscribers": 11_000,
        "Clicks": 32_000, "Card Click": 0, "End Screen Click": 0,
        "Conversions": 240, "Purchases": 180,
        "Cost": 28_000, "Number Of Days": 90,
    }])
    _write_csv(s, "tt", [{
        "Video Views": 9_200_000, "Reach": 2_400_000,
        "Likes": 180_000, "Comments": 14_000, "Shares": 24_000, "Saves": 9_400, "Followers": 4_800,
        "Destination Click": 38_000, "Profile View": 71_000,
        "Leads": 140, "Purchases": 280,
        "Cost": 16_000, "Number Of Days": 90,
    }])

    _write_readme(s, """
# Scenario 5 — Omnichannel, all four objectives

**Wizard inputs**

- Objective: Awareness, Engagement, Website Traffic, Lead Generation (all)
- Budget: £150,000
- Duration: 90 days
- Currency: GBP
- Platforms: Google Search, Google Display, Google PMax, Facebook,
  Instagram, LinkedIn, YouTube, TikTok
- Per-platform minima: Search £10k · Display £4k · PMax £12k · FB £10k ·
  IG £10k · LI £8k · YT £12k · TT £8k
- Goal values: £0.005 per reach/impression, £0.12 per engagement,
  £0.45 per click, £55 per purchase + £150 per non-purchase lead
- Test-and-learn reserve: 12%
- Seasonality: 0.95 across goals
- Scenario multipliers: conservative {LG: 0.8}, base 1.0,
  optimistic {LG: 1.2}

**What this stresses**

- All four goals active simultaneously — verifies per-goal productivity
  normalisation actually balances the LP across heterogeneous KPIs
  (reach in millions vs leads in hundreds).
- Three Google surfaces (Search / Display / PMax) with very different
  productivities — verifies the split-Google decision pays off.
- Long 90-day history means shrinkage barely fires (high data quality);
  good control for comparing against shorter-history scenarios.
- Monte Carlo on this scenario should flag Google Display (weakest LG
  productivity, mid-funnel) as rank-sensitive.
- Expected: PMax + Search dominate lead-gen; FB/IG carry engagement and
  WT; YT/TT carry awareness; Display gets near-minimum.
""")


SCENARIOS = [
    scenario_1_b2b_saas,
    scenario_2_dtc_ecommerce,
    scenario_3_brand_launch,
    scenario_4_community_engagement,
    scenario_5_omnichannel,
]


def main() -> None:
    for fn in SCENARIOS:
        fn()
    # Top-level index
    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write(
            "# Test datasets\n\n"
            "Five scenario folders, each with one CSV per selected platform\n"
            "(columns match the per-platform import templates) and a\n"
            "`SCENARIO.md` listing the wizard inputs to recreate the run.\n\n"
            "1. `01_b2b_saas_leadgen/` — small budget, intent-led lead-gen mix.\n"
            "2. `02_dtc_ecommerce_purchases/` — consumer purchases via PMax + Meta + TikTok + Pinterest.\n"
            "3. `03_brand_launch_awareness/` — large upper-funnel-only video push.\n"
            "4. `04_community_engagement/` — engagement-led social mix; stresses the composition layer.\n"
            "5. `05_omnichannel_all_goals/` — all four objectives, eight platforms, long history.\n\n"
            "Regenerate with:\n\n"
            "```bash\n"
            "PYTHONPATH=. python test_datasets/_generate.py\n"
            "```\n"
        )
    print("Generated 5 scenarios in", HERE)


if __name__ == "__main__":
    main()
