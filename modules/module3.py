from typing import Any, Dict, List

from core.wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


KPI_CONFIG: List[Dict[str, Any]] = [
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_REACH",      "kpi_label": "Reach"},
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_IMPRESSION", "kpi_label": "Impression"},
    {"platform": "fb", "goal": GOAL_EN, "var": "FB_EN_ENGAGEMENT", "kpi_label": "Engagement"},
    {"platform": "fb", "goal": GOAL_WT, "var": "FB_WT_CLICKS",     "kpi_label": "Link Clicks"},
    {"platform": "fb", "goal": GOAL_LG, "var": "FB_LG_LEADS",      "kpi_label": "Leads"},
    {"platform": "ig", "goal": GOAL_AW, "var": "IG_AW_REACH",       "kpi_label": "Reach"},
    {"platform": "ig", "goal": GOAL_EN, "var": "IG_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "ig", "goal": GOAL_WT, "var": "IG_WT_CLICKS",      "kpi_label": "Link Clicks"},
    {"platform": "ig", "goal": GOAL_LG, "var": "IG_LG_LEADS",       "kpi_label": "Leads"},
    {"platform": "li", "goal": GOAL_AW, "var": "LI_AW_REACH",       "kpi_label": "Reach"},
    {"platform": "li", "goal": GOAL_EN, "var": "LI_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "li", "goal": GOAL_LG, "var": "LI_LG_LEADS",       "kpi_label": "Leads"},
    {"platform": "yt", "goal": GOAL_AW, "var": "YT_AW_VIEWS",       "kpi_label": "Views"},
    {"platform": "yt", "goal": GOAL_EN, "var": "YT_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "yt", "goal": GOAL_WT, "var": "YT_WT_CLICKS",      "kpi_label": "Link Clicks"},
    {"platform": "yt", "goal": GOAL_LG, "var": "YT_LG_LEADS",       "kpi_label": "Leads"},
]


def get_platform_kpis(platform: str, active_goals_for_platform: List[str]) -> List[Dict[str, Any]]:
    return [
        row
        for row in KPI_CONFIG
        if row["platform"] == platform and row["goal"] in active_goals_for_platform
    ]


def reset_wizard(state: WizardState) -> WizardState:
    state.reset()
    return state


def ask_required_string(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required. Please enter a value.")


def ask_required_budget_gt1(prompt: str) -> float:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            value = float(text)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if value <= 1:
            print("Value must be greater than 1.")
            continue
        return value


def ask_required_kpi_gt1(prompt: str) -> float:
    while True:
        text = input(prompt).strip()
        if not text:
            print("This field is required. Please enter a value.")
            continue
        try:
            value = float(text)
        except ValueError:
            print("Please enter a valid numeric value.")
            continue
        if value <= 1:
            print("Value must be greater than 1.")
            continue
        return value


def run_module3(state: WizardState) -> WizardState:
    if state.module3_finalised:
        raise RuntimeError(
            "Module 3 has already been finalised. You cannot edit it. "
            "Reset the wizard to start again."
        )

    if not state.module2_finalised:
        raise RuntimeError("Module 2 must be finalised before running Module 3.")

    if not state.active_platforms:
        raise RuntimeError("No active platforms found. Nothing to do in Module 3.")

    temp_module3_data: Dict[str, Dict[str, Any]] = {}

    print("\n=== MODULE 3: Historical budget and KPI data collection ===\n")

    for platform in state.active_platforms:
        print("\n------------------------------------------")
        print(f"Platform: {platform}")
        print("------------------------------------------\n")

        time_window = ask_required_string(
            f"Enter the time window for {platform} data "
            f"(for example: 'last 30 days', 'Q4 2024'): "
        )

        budget = ask_required_budget_gt1(
            f"Enter the total budget spent on {platform} in this period (numeric > 1): "
        )

        active_goals = state.goals_by_platform.get(platform, [])
        if not active_goals:
            platform_kpis: List[Dict[str, Any]] = []
        else:
            platform_kpis = get_platform_kpis(platform, active_goals)

        kpi_values: Dict[str, float] = {}

        for kpi_def in platform_kpis:
            var = kpi_def["var"]
            label = kpi_def["kpi_label"]
            goal = kpi_def["goal"]
            prompt = (
                f"{platform} | Goal: {goal} | KPI: {label} "
                f"({var}) value (> 1): "
            )
            value = ask_required_kpi_gt1(prompt)
            kpi_values[var] = value

        temp_module3_data[platform] = {
            "time_window": time_window,
            "budget": budget,
            "kpis": kpi_values,
        }

    while True:
        choice = input("Type 'submit' to confirm, or 'reset' to restart: ").strip().lower()

        if choice == "reset":
            return reset_wizard(state)

        if choice == "submit":
            platform_budgets: Dict[str, float] = {}
            platform_kpis: Dict[str, Dict[str, float]] = {}
            kpi_ratios: Dict[str, Dict[str, float]] = {}

            for platform, pdata in temp_module3_data.items():
                budget = float(pdata["budget"])
                kpis: Dict[str, float] = pdata["kpis"]

                platform_budgets[platform] = budget
                platform_kpis[platform] = dict(kpis)

                ratios_for_p: Dict[str, float] = {}
                if budget > 0:
                    for kpi_var, value in kpis.items():
                        ratios_for_p[kpi_var] = float(value) / budget
                kpi_ratios[platform] = ratios_for_p

            state.complete_module3_and_advance(
                module3_data=temp_module3_data,
                platform_budgets=platform_budgets,
                platform_kpis=platform_kpis,
                kpi_ratios=kpi_ratios,
            )

            return state

        print("Invalid choice. Please type exactly 'submit' or 'reset'.")


if __name__ == "__main__":
    s = WizardState(
        current_step=3,
        module1_finalised=True,
        module2_finalised=True,
        total_budget=10000.0,
        valid_goals=[GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG],
        active_platforms=["fb", "ig"],
        goals_by_platform={
            "fb": [GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG],
            "ig": [GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG],
        },
    )
    try:
        run_module3(s)
    except RuntimeError as e:
        print(f"Error: {e}")
