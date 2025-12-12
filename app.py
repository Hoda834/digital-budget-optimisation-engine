import streamlit as st
from typing import Any

def safe_rerun() -> None:
    if hasattr(st, "rerun"):
        try:
            st.rerun()  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    return

from core.wizard_state import (
    WizardState,
    GOAL_AW,
    GOAL_EN,
    GOAL_WT,
    GOAL_LG,
)
from core.kpi_config import KPI_CONFIG

from modules.module2 import run_module2
from modules.module4 import run_module4, Module4Result
from modules.module5 import run_module5
from modules.module6 import run_module6

import io
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter  # type: ignore
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle  # type: ignore
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore


PLATFORM_NAMES: dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
}

GOAL_NAMES: dict[str, str] = {
    GOAL_AW: "Awareness",
    GOAL_EN: "Engagement",
    GOAL_WT: "Website Traffic",
    GOAL_LG: "Lead Generation",
}


def initialise_state() -> None:
    if "wizard_state" not in st.session_state:
        st.session_state["wizard_state"] = WizardState()


def reset_state() -> None:
    st.session_state.pop("wizard_state", None)
    initialise_state()


def module1_ui(state: WizardState) -> None:
    st.header("🔹 Module 1: Select your objectives and total budget")
    goals = st.multiselect(
        "Choose one or more marketing objectives:",
        options=[
            (GOAL_AW, "Awareness"),
            (GOAL_EN, "Engagement"),
            (GOAL_WT, "Website Traffic"),
            (GOAL_LG, "Lead Generation"),
        ],
        format_func=lambda x: x[1],
    )
    goal_codes = [code for code, _ in goals]
    total_budget = st.number_input(
        "Enter your total budget (must be greater than 1)",
        min_value=1.0,
        value=1000.0,
        step=100.0,
    )
    if st.button(
        "Continue to Module 2",
        disabled=not goal_codes or total_budget <= 1,
    ):
        state.complete_module1_and_advance(
            valid_goals=goal_codes,
            total_budget=total_budget,
        )
        safe_rerun()


def module2_ui(state: WizardState) -> None:
    st.header("🔹 Module 2: Select platforms and set goal priorities")
    platforms = ["fb", "ig", "li", "yt"]
    platform_names = {
        "fb": "Facebook",
        "ig": "Instagram",
        "li": "LinkedIn",
        "yt": "YouTube",
    }
    selected_platforms = st.multiselect(
        "Choose one or more platforms:",
        options=platforms,
        format_func=lambda p: platform_names.get(p, p),
    )
    priorities_input: dict[str, dict[str, str | None]] = {}
    for p in selected_platforms:
        st.subheader(f"Priorities for {platform_names[p]}")
        p1 = st.selectbox(
            f"Primary objective on {platform_names[p]}",
            options=[None] + state.valid_goals,
            format_func=lambda x: {
                None: "(none)",
                GOAL_AW: "Awareness",
                GOAL_EN: "Engagement",
                GOAL_WT: "Website Traffic",
                GOAL_LG: "Lead Generation",
            }.get(x, x),
            key=f"{p}_p1",
        )
        p2_options = [None] + [g for g in state.valid_goals if g != p1]
        p2 = st.selectbox(
            f"Secondary objective on {platform_names[p]} (optional)",
            options=p2_options,
            format_func=lambda x: {
                None: "(none)",
                GOAL_AW: "Awareness",
                GOAL_EN: "Engagement",
                GOAL_WT: "Website Traffic",
                GOAL_LG: "Lead Generation",
            }.get(x, x),
            key=f"{p}_p2",
        )
        priorities_input[p] = {"priority_1": p1, "priority_2": p2}
    if st.button("Continue to Module 3", disabled=not selected_platforms):
        run_module2(state, selected_platforms, priorities_input)
        safe_rerun()


def module3_ui(state: WizardState) -> None:
    st.header("🔹 Module 3: Provide historical data")
    m3_data: dict[str, dict[str, Any]] = {}
    platform_budgets: dict[str, float] = {}
    platform_kpis: dict[str, dict[str, float]] = {}

    for platform in state.active_platforms:
        platform_name = PLATFORM_NAMES.get(platform, platform.upper())
        st.subheader(f"Data for {platform_name}")
        time_window = st.text_input(
            f"Time window for {platform_name} (e.g. 'last 30 days')",
            key=f"time_{platform}",
        )
        budget = st.number_input(
            f"Total historical budget on {platform_name} (> 1)",
            min_value=1.0,
            value=1000.0,
            step=100.0,
            key=f"budget_{platform}",
        )
        kpi_defs = [
            row
            for row in KPI_CONFIG
            if row["platform"] == platform
            and row["goal"] in state.goals_by_platform.get(platform, [])
        ]
        kpi_values: dict[str, float] = {}
        for kpi_def in kpi_defs:
            var = kpi_def["var"]
            label = kpi_def["kpi_label"]
            goal_code = kpi_def["goal"]
            goal_name = GOAL_NAMES.get(goal_code, goal_code)
            descriptive_label = f"{goal_name} – {label} on {platform_name} (> 1)"
            val = st.number_input(
                descriptive_label,
                min_value=1.0,
                value=1.0,
                step=0.1,
                key=f"{platform}_{var}",
            )
            kpi_values[var] = val
        m3_data[platform] = {
            "time_window": time_window,
            "budget": budget,
            "kpis": kpi_values,
        }
        platform_budgets[platform] = budget
        platform_kpis[platform] = kpi_values

    if st.button(
        "Run optimisation",
        disabled=any(
            not d["time_window"] or d["budget"] <= 1 for d in m3_data.values()
        ),
    ):
        kpi_ratios: dict[str, dict[str, float]] = {}
        for platform in m3_data:
            b = float(m3_data[platform]["budget"])
            ratios_for_p = {
                k: float(v) / b for k, v in m3_data[platform]["kpis"].items()
            }
            kpi_ratios[platform] = ratios_for_p
        state.complete_module3_and_advance(
            module3_data=m3_data,
            platform_budgets=platform_budgets,
            platform_kpis=platform_kpis,
            kpi_ratios=kpi_ratios,
        )
        safe_rerun()


def results_ui(state: WizardState) -> None:
    st.header("📊 Results")

    if not state.module4_finalised and state.module3_finalised:
        run_module4(state, KPI_CONFIG)
    if not state.module5_finalised and state.module4_finalised:
        run_module5(state)
    if not state.module6_finalised and state.module5_finalised:
        run_module6(state, next_step=6)

    if state.module5_result:
        st.subheader("Budget allocation per platform and goal")
        for platform_code, goals in state.module5_result.budget_per_platform_goal.items():
            platform_name = PLATFORM_NAMES.get(platform_code.lower(), platform_code.upper())
            goals_display: dict[str, float] = {
                GOAL_NAMES.get(goal_code, goal_code): value
                for goal_code, value in goals.items()
            }
            st.write(f"{platform_name}: {goals_display}")
        st.write("**Total budget used:**", state.module5_result.total_budget_used)

        insights: list[str] = []
        max_budget_platform = max(
            state.module5_result.budget_per_platform.items(),
            key=lambda x: x[1],
            default=(None, 0.0),
        )
        if max_budget_platform[0] is not None:
            max_platform_code, max_budget = max_budget_platform
            max_platform_name = PLATFORM_NAMES.get(
                max_platform_code.lower(), max_platform_code
            )
            insights.append(
                f"The highest budget allocation is on {max_platform_name} with {max_budget:.2f} units."
            )
        if state.module6_result and state.module6_result.rows:
            max_kpi_row = max(
                state.module6_result.rows,
                key=lambda r: r.predicted_kpi,
            )
            max_kpi_platform = PLATFORM_NAMES.get(
                max_kpi_row.platform.lower(),
                max_kpi_row.platform,
            )
            var_to_desc: dict[str, str] = {}
            for row_conf in KPI_CONFIG:
                goal_name = GOAL_NAMES.get(row_conf["goal"], row_conf["goal"])
                var_to_desc[row_conf["var"]] = f"{goal_name} – {row_conf['kpi_label']}"
            max_kpi_desc = var_to_desc.get(max_kpi_row.kpi_name, max_kpi_row.kpi_name)
            insights.append(
                f"The highest predicted KPI is {max_kpi_desc} on {max_kpi_platform} with {max_kpi_row.predicted_kpi:.2f} units."
            )
        if insights:
            st.subheader("Insights")
            for ins in insights:
                st.write("- " + ins)

        if state.module6_result:
            st.subheader("Predicted KPIs")
            import pandas as pd  # type: ignore

            var_to_description: dict[str, str] = {}
            for row in KPI_CONFIG:
                goal_code = row["goal"]
                goal_name = GOAL_NAMES.get(goal_code, goal_code)
                description = f"{goal_name} – {row['kpi_label']}"
                var_to_description[row["var"]] = description

            formatted_rows = []
            for row in state.module6_result.rows:
                platform_name = PLATFORM_NAMES.get(
                    row.platform.lower(), row.platform
                )
                kpi_description = var_to_description.get(
                    row.kpi_name,
                    row.kpi_name,
                )
                formatted_rows.append(
                    {
                        "Platform": platform_name,
                        "KPI": kpi_description,
                        "KPI per budget": row.ratio_kpi_per_budget,
                        "Allocated budget": row.allocated_budget,
                        "Predicted KPI": row.predicted_kpi,
                    }
                )
            df = pd.DataFrame(formatted_rows)
            st.dataframe(df)

        if st.checkbox("Show budget and KPI distribution charts"):
            budget_labels = [
                PLATFORM_NAMES.get(p.lower(), p)
                for p in state.module5_result.budget_per_platform.keys()
            ]
            budget_values = list(
                state.module5_result.budget_per_platform.values()
            )
            fig1, ax1 = plt.subplots()
            ax1.bar(budget_labels, budget_values)
            ax1.set_title("Budget allocation per platform")
            ax1.set_xlabel("Platform")
            ax1.set_ylabel("Budget")
            st.pyplot(fig1)

            if state.module6_result:
                kpi_totals: dict[str, float] = {}
                for row in state.module6_result.rows:
                    kpi_totals[row.platform] = (
                        kpi_totals.get(row.platform, 0.0) + row.predicted_kpi
                    )
                kpi_labels = [
                    PLATFORM_NAMES.get(p.lower(), p)
                    for p in kpi_totals.keys()
                ]
                kpi_values = list(kpi_totals.values())
                fig2, ax2 = plt.subplots()
                ax2.bar(kpi_labels, kpi_values)
                ax2.set_title("Total predicted KPI per platform")
                ax2.set_xlabel("Platform")
                ax2.set_ylabel("Predicted KPI")
                st.pyplot(fig2)

        def create_pdf(state: WizardState, insights_list: list[str], df_data) -> bytes:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story: list[Any] = []
            story.append(Paragraph("Results Summary", styles["Title"]))
            story.append(Spacer(1, 12))
            story.append(
                Paragraph(
                    "<b>Budget allocation per platform and goal</b>",
                    styles["Heading2"],
                )
            )
            for platform_code, goals in state.module5_result.budget_per_platform_goal.items():
                platform_name = PLATFORM_NAMES.get(
                    platform_code.lower(),
                    platform_code,
                )
                goals_display = {
                    GOAL_NAMES.get(goal_code, goal_code): value
                    for goal_code, value in goals.items()
                }
                story.append(
                    Paragraph(f"{platform_name}: {goals_display}", styles["Normal"])
                )
            story.append(
                Paragraph(
                    f"<b>Total budget used:</b> {state.module5_result.total_budget_used:.2f}",
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 12))
            if insights_list:
                story.append(Paragraph("<b>Insights</b>", styles["Heading2"]))
                for ins in insights_list:
                    story.append(Paragraph(f"• {ins}", styles["Normal"]))
                story.append(Spacer(1, 12))
            if not df_data.empty:
                story.append(
                    Paragraph("<b>Predicted KPIs</b>", styles["Heading2"])
                )
                table_data = [list(df_data.columns)] + df_data.values.tolist()
                tbl = Table(table_data)
                tbl.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                            ("GRID", (0, 0), (-1, -1), 1, (0, 0, 0)),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ]
                    )
                )
                story.append(tbl)
            doc.build(story)
            pdf = buffer.getvalue()
            buffer.close()
            return pdf

        if st.button("Download results as PDF"):
            import pandas as pd  # type: ignore

            formatted_rows_pdf = []
            if state.module6_result:
                var_to_description_pdf: dict[str, str] = {}
                for row_conf in KPI_CONFIG:
                    goal_name = GOAL_NAMES.get(row_conf["goal"], row_conf["goal"])
                    var_to_description_pdf[row_conf["var"]] = (
                        f"{goal_name} – {row_conf['kpi_label']}"
                    )
                for row in state.module6_result.rows:
                    platform_name_pdf = PLATFORM_NAMES.get(
                        row.platform.lower(),
                        row.platform,
                    )
                    kpi_desc_pdf = var_to_description_pdf.get(
                        row.kpi_name,
                        row.kpi_name,
                    )
                    formatted_rows_pdf.append(
                        {
                            "Platform": platform_name_pdf,
                            "KPI": kpi_desc_pdf,
                            "KPI per budget": row.ratio_kpi_per_budget,
                            "Allocated budget": row.allocated_budget,
                            "Predicted KPI": row.predicted_kpi,
                        }
                    )
            df_pdf = pd.DataFrame(formatted_rows_pdf)
            pdf_bytes = create_pdf(state, insights, df_pdf)
            st.download_button(
                label="Click here to download the PDF",
                data=pdf_bytes,
                file_name="or_wizard_results.pdf",
                mime="application/pdf",
            )
    else:
        st.write("Optimisation has not been run yet.")

    if st.button("Start over"):
        reset_state()
        safe_rerun()


def main() -> None:
    initialise_state()
    state: WizardState = st.session_state["wizard_state"]
    if state.current_step == 1:
        module1_ui(state)
    elif state.current_step == 2:
        module2_ui(state)
    elif state.current_step == 3:
        module3_ui(state)
    else:
        results_ui(state)


if __name__ == "__main__":
    main()
