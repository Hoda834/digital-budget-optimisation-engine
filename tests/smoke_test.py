from wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT
from module2 import run_module2
from module3 import KPI_CONFIG
from module4 import run_module4
from module5 import run_module5
from module6 import run_module6


def build_fake_module3_data(state: WizardState):
    """
    ساختن داده‌ی فیک برای ماژول ۳ متناسب با KPI_CONFIG و پلتفرم‌های فعال.
    """
    module3_data = {}
    platform_budgets = {}
    platform_kpis = {}

    for platform in state.active_platforms:
        # بودجه ساختگی (نمونه)
        budget = 2000.0 if platform == "fb" else 3000.0
        platform_budgets[platform] = budget

        # همه KPIهایی که در KPI_CONFIG برای این پلتفرم و goal‌های معتبر وجود دارد
        kpis_for_p = {}
        for row in KPI_CONFIG:
            if row["platform"] != platform:
                continue
            if row["goal"] not in state.valid_goals:
                continue
            var = row["var"]

            # مقدار ساختگی > 1 بر اساس نام KPI
            if "REACH" in var:
                value = 1000.0
            elif "IMPRESSION" in var:
                value = 1500.0
            elif "CLICKS" in var:
                value = 3.0
            elif "LEADS" in var:
                value = 5.0
            elif "ENGRATERATE" in var:
                value = 2.0
            else:
                value = 100.0

            if value <= 1:
                value = 2.0

            kpis_for_p[var] = value

        module3_data[platform] = {
            "time_window": "last 30 days",
            "budget": budget,
            "kpis": kpis_for_p,
        }
        platform_kpis[platform] = kpis_for_p

    # نسبت‌ها
    kpi_ratios = {}
    for platform, pdata in module3_data.items():
        b = float(pdata["budget"])
        kpi_ratios[platform] = {
            k: float(v) / b for k, v in pdata["kpis"].items()
        }

    return module3_data, platform_budgets, platform_kpis, kpi_ratios


def main():
    # Module 1
    state = WizardState()
    state.complete_module1_and_advance(
        valid_goals=[GOAL_AW, GOAL_EN, GOAL_WT],
        total_budget=5000.0,
    )
    print("After module 1:")
    print("  current_step:", state.current_step)
    print("  valid_goals:", state.valid_goals)
    print("  total_budget:", state.total_budget)
    print()

    # Module 2
    selected_platforms = ["fb", "ig"]
    priorities_input = {
        "fb": {"priority_1": GOAL_AW, "priority_2": GOAL_EN},
        "ig": {"priority_1": GOAL_WT, "priority_2": None},
    }
    state = run_module2(state, selected_platforms, priorities_input)
    print("After module 2:")
    print("  current_step:", state.current_step)
    print("  active_platforms:", state.active_platforms)
    print("  goals_by_platform:", state.goals_by_platform)
    print("  platform_weights:", state.platform_weights)
    print()

    # Module 3 (fake data)
    m3_data, platform_budgets, platform_kpis, kpi_ratios = build_fake_module3_data(state)
    state.complete_module3_and_advance(
        module3_data=m3_data,
        platform_budgets=platform_budgets,
        platform_kpis=platform_kpis,
        kpi_ratios=kpi_ratios,
    )
    print("After module 3:")
    print("  current_step:", state.current_step)
    print("  platform_budgets:", state.platform_budgets)
    print("  kpi_ratios keys:", list(state.kpi_ratios.keys()))
    print()

    # Module 4
    result4 = run_module4(state, KPI_CONFIG)
    print("After module 4:")
    print("  current_step:", state.current_step)
    print("  cpu_per_goal keys:", list(result4.cpu_per_goal.keys()))
    # تعداد کل ورودی‌ها (platform-goal-kpi) را نمایش می‌دهد
    total_entries = sum(len(goal_dict) for goals in result4.cpu_per_goal.values() for goal_dict in goals.values())
    print("  number of platform-goal-kpi entries:", total_entries)
    print()

    # Module 5
    state = run_module5(state)
    print("After module 5:")
    print("  current_step:", state.current_step)
    print("  total_budget_used:", state.module5_result.total_budget_used)
    print("  budget_per_platform:", state.module5_result.budget_per_platform)
    print()

    # Module 6
    state.current_step = 6  # تنظیم برای اجرای ماژول 6
    state = run_module6(state)
    print("After module 6:")
    print("  current_step:", state.current_step)
    print("  forecast rows:", len(state.module6_result.rows))
    for row in state.module6_result.rows[:5]:
        print(
            row.platform, row.kpi_name,
            "budget:", row.allocated_budget,
            "ratio:", row.ratio_kpi_per_budget,
            "predicted:", row.predicted_kpi
        )


if __name__ == "__main__":
    main()
