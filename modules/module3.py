"""
Updated Module 3 for the OR project.

This module populates the KPI_CONFIG with concrete entries for each
platform and goal, provides helpers for collecting historical data,
and integrates with WizardState to store the results.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


# ============================================
# 1. KPI CONFIGURATION
# ============================================

# This list defines which KPI variables are expected for each platform and goal.
# Each entry specifies the platform (fb, ig, li, yt), the goal code, the
# internal KPI variable name used in the code, and a human-readable label.
KPI_CONFIG: List[Dict[str, Any]] = [
    # --- Facebook KPIs ---
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_REACH",      "kpi_label": "Reach"},
    {"platform": "fb", "goal": GOAL_AW, "var": "FB_AW_IMPRESSION", "kpi_label": "Impression"},
    {"platform": "fb", "goal": GOAL_EN, "var": "FB_EN_ENGAGEMENT", "kpi_label": "Engagement"},
    {"platform": "fb", "goal": GOAL_WT, "var": "FB_WT_CLICKS",     "kpi_label": "Link Clicks"},
    {"platform": "fb", "goal": GOAL_LG, "var": "FB_LG_LEADS",      "kpi_label": "Leads"},

    # --- Instagram KPIs ---
    {"platform": "ig", "goal": GOAL_AW, "var": "IG_AW_REACH",       "kpi_label": "Reach"},
    {"platform": "ig", "goal": GOAL_EN, "var": "IG_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "ig", "goal": GOAL_WT, "var": "IG_WT_CLICKS",      "kpi_label": "Link Clicks"},
    {"platform": "ig", "goal": GOAL_LG, "var": "IG_LG_LEADS",       "kpi_label": "Leads"},

    # --- LinkedIn KPIs ---
    {"platform": "li", "goal": GOAL_AW, "var": "LI_AW_REACH",       "kpi_label": "Reach"},
    {"platform": "li", "goal": GOAL_EN, "var": "LI_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "li", "goal": GOAL_LG, "var": "LI_LG_LEADS",       "kpi_label": "Leads"},

    # --- YouTube KPIs ---
    {"platform": "yt", "goal": GOAL_AW, "var": "YT_AW_VIEWS",       "kpi_label": "Views"},
    {"platform": "yt", "goal": GOAL_EN, "var": "YT_EN_ENGRATERATE", "kpi_label": "Engagement Rate"},
    {"platform": "yt", "goal": GOAL_WT, "var": "YT_WT_CLICKS",      "kpi_label": "Link Clicks"},
    {"platform": "yt", "goal": GOAL_LG, "var": "YT_LG_LEADS",       "kpi_label": "Leads"},
]


def get_platform_kpis(platform: str, active_goals_for_platform: List[str]) -> List[Dict[str, Any]]:
    """
    Filter KPI_CONFIG for a given platform and its active goals.
    Returns a list of KPI definition dictionaries.
    """
    return [
        row
        for row in KPI_CONFIG
        if row["platform"] == platform and row["goal"] in active_goals_for_platform
    ]


# ============================================
# 2. RESET FUNCTION
# ============================================

def reset_wizard(state: WizardState) -> WizardState:
    """
    Reset the whole wizard. All modules are cleared and we go back to step 1.
    """
    print("\n*** Resetting the whole wizard. All data will be lost. ***\n")
    state.reset()
    return state


# ============================================
# 3. INPUT HELPERS WITH STRICT VALIDATION
# ============================================

def ask_required_string(prompt: str) -> str:
    """
    Ask the user for a non-empty string.
    Used for time window descriptions or other text fields.
    """
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required. Please enter a value.")


def ask_required_budget_gt1(prompt: str) -> float:
    """
    Ask user for a required numeric input strictly greater than 1.
    Used for platform budgets.
    """
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
    """
    Ask the user for a KPI value strictly greater than 1.
    Zero, 1 and negative numbers are not allowed.
    """
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


# ============================================
# 4. MODULE 3 MAIN LOGIC
# ============================================

def run_module3(state: WizardState) -> WizardState:
    """
    Module 3: Historical budget and KPI data collection.

    Behaviour:
    - One way only: after module3_finalised is True, this function cannot be executed
      again unless the whole wizard is reset.
    - Requires Module 2 to be finalised.
    - For each active platform (from Module 2), in sequence:
        * Ask for time window (required, non-empty string)
        * Ask for total historical budget for that platform (required, > 1)
        * For all KPIs relevant to that platform and its active goals:
              - Ask user to input KPI values (all required, > 1)
    - All answers are mandatory.
    - At first, results are stored in a temporary dictionary.
    - Only when the user presses "submit" (confirmation step),
      data are copied into state.module3_data, state.platform_budgets,
      state.platform_kpis, state.kpi_ratios, module3_finalised is set to True, and
      the wizard moves to the next step (Module 4).
    - The only way to discard the data is to reset the whole wizard.
    """

    # Guard: no rerun after finalisation
    if state.module3_finalised:
        raise RuntimeError(
            "Module 3 has already been finalised. You cannot go back or edit it. "
            "To change the data, you must reset the whole wizard."
        )

    # Guard: Module 2 must be done before Module 3
    if not state.module2_finalised:
        raise RuntimeError("Module 2 must be finalised before running Module 3.")

    # Guard: we need at least one active platform
    if not state.active_platforms:
        raise RuntimeError("No active platforms found. Nothing to do in Module 3.")

    # Temporary container; will only be committed to state after "submit"
    temp_module3_data: Dict[str, Dict[str, Any]] = {}

    print("\n=== MODULE 3: Historical budget and KPI data collection ===\n")
    print("For each active platform, you will be asked to provide:\n"
          "  1) The time window for the data (for example: 'last 30 days', 'Q4 2024')\n"
          "  2) The total budget spent on that platform in this period (numeric > 1)\n"
          "  3) The values of all relevant KPIs for the same period (each > 1)\n")
    print("All fields are mandatory.\n")
    print("Note: you cannot go back to previous modules from here.\n"
          "      At the end you will confirm with a single 'submit' action.\n")

    # Iterate over active platforms one by one (no going back inside Module 3)
    for platform in state.active_platforms:
        print("\n------------------------------------------")
        print(f"Platform: {platform}")
        print("------------------------------------------\n")

        # 1) Time window (required)
        time_window = ask_required_string(
            f"Enter the time window for {platform} data "
            f"(for example: 'last 30 days', 'Q4 2024'): "
        )

        # 2) Budget for this platform (required, strictly > 1)
        budget = ask_required_budget_gt1(
            f"Enter the total budget spent on {platform} in this period (numeric > 1): "
        )

        # 3) Determine which KPIs to ask for, based on active goals for this platform
        active_goals = state.goals_by_platform.get(platform, [])
        if not active_goals:
            print(
                f"Warning: no active goals registered for platform {platform}. "
                f"No KPIs will be collected for this platform."
            )
            platform_kpis: List[Dict[str, Any]] = []
        else:
            platform_kpis = get_platform_kpis(platform, active_goals)

        kpi_values: Dict[str, float] = {}

        # Ask KPI values one by one (all required, each > 1)
        if platform_kpis:
            print(
                f"\nNow enter KPI values for {platform} "
                f"for the same time window and budget.\n"
                f"All KPI fields are required, and each value must be greater than 1.\n"
            )

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

        # Save everything for this platform into the temporary container
        temp_module3_data[platform] = {
            "time_window": time_window,
            "budget": budget,
            "kpis": kpi_values,
        }

    # ------------------------------------------
    # SUBMIT STEP: lock data and move to Module 4
    # ------------------------------------------

    print("\n------------------------------------------")
    print("Data entry for all active platforms is complete.\n")
    print("At this stage you have two options:")
    print("  - 'submit' : lock all data, finalise Module 3 and move to Module 4")
    print("  - 'reset'  : discard everything and restart the wizard from Module 1")
    print("------------------------------------------\n")

    while True:
        choice = input("Type 'submit' to confirm, or 'reset' to restart: ").strip().lower()

        if choice == "reset":
            # Discard temp data and reset the whole wizard
            return reset_wizard(state)

        if choice == "submit":
            # Build platform_budgets, platform_kpis, and kpi_ratios
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

            # Delegate finalisation and flow to WizardState
            state.complete_module3_and_advance(
                module3_data=temp_module3_data,
                platform_budgets=platform_budgets,
                platform_kpis=platform_kpis,
                kpi_ratios=kpi_ratios,
            )

            print("\nModule 3 has been submitted and locked.")
            print("Inputs are now read only. Proceeding to Module 4...\n")

            # The outer controller is responsible for calling Module 4
            return state

        print("Invalid choice. Please type exactly 'submit' or 'reset'.")


if __name__ == "__main__":
    # Minimal usage example:
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
