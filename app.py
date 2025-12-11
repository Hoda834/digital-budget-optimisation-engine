import streamlit as st
from typing import Any

def safe_rerun() -> None:
    
    # New API (Streamlit ≥1.52): st.rerun()
    if hasattr(st, "rerun"):
        try:
            st.rerun()  # type: ignore[attr-defined]
            return
        except Exception:
            # Fall back if something goes wrong
            pass
    # Legacy API (Streamlit <1.52): st.experimental_rerun()
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    # If neither exists just do nothing
    return

from wizard_state import (
    WizardState,
    GOAL_AW,
    GOAL_EN,
    GOAL_WT,
    GOAL_LG,
)

from module2 import run_module2
from module3 import KPI_CONFIG
from module4 import run_module4, Module4Result
from module5 import run_module5
from module6 import run_module6

import io  # for PDF generation
import matplotlib.pyplot as plt  # for charts
from reportlab.lib.pagesizes import letter  # for PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle  # type: ignore
from reportlab.lib.styles import getSampleStyleSheet

# -----------------------------------------------------------------------------
# Name mappings
#
# To avoid abbreviations in the user interface, define dictionaries that map
# canonical platform codes and goal codes to human‑readable names. These
# constants are used throughout the UI to display full platform names (e.g.
# "Instagram" instead of "IG") and goal names (e.g. "Awareness" instead of
# "aw"). A mapping for KPI variables to descriptive labels is built on
# demand in the results UI using KPI_CONFIG.

# Human‑friendly platform names
PLATFORM_NAMES: dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
}

# Human‑friendly goal names keyed by the canonical goal codes from wizard_state
GOAL_NAMES: dict[str, str] = {
    GOAL_AW: "Awareness",
    GOAL_EN: "Engagement",
    GOAL_WT: "Website Traffic",
    GOAL_LG: "Lead Generation",
}


def initialise_state() -> None:
    """Initialise the WizardState in Streamlit session state if absent."""
    if "wizard_state" not in st.session_state:
        st.session_state["wizard_state"] = WizardState()


def reset_state() -> None:
    """Reset the wizard by reinitialising the WizardState."""
    st.session_state.pop("wizard_state", None)
    initialise_state()


def module1_ui(state: WizardState) -> None:
    """Render UI for Module 1: goal selection and total budget."""
    st.header("🔹 Module 1: Select your objectives and total budget")
    goals = st.multiselect(
        "Choose one or more marketing objectives:",
        options=[(GOAL_AW, "Awareness"), (GOAL_EN, "Engagement"), (GOAL_WT, "Website Traffic"), (GOAL_LG, "Lead Generation")],
        format_func=lambda x: x[1],
    )
    goal_codes = [code for code, _ in goals]
    total_budget = st.number_input(
        "Enter your total budget (must be greater than 1)", min_value=1.0, value=1000.0, step=100.0
    )
    if st.button("Continue to Module 2", disabled=not goal_codes or total_budget <= 1):
        # Finalise Module 1 and advance
        state.complete_module1_and_advance(valid_goals=goal_codes, total_budget=total_budget)
        safe_rerun()


def module2_ui(state: WizardState) -> None:
    """Render UI for Module 2: platform selection and goal prioritisation."""
    st.header("🔹 Module 2: Select platforms and set goal priorities")
    platforms = ["fb", "ig", "li", "yt"]
    platform_names = {
        "fb": "Facebook",
        "ig": "Instagram",
        "li": "LinkedIn",
        "yt": "YouTube",
    }
    # Select platforms
    selected_platforms = st.multiselect(
        "Choose one or more platforms:", options=platforms, format_func=lambda p: platform_names.get(p, p)
    )
    # Collect priorities for each selected platform
    priorities_input: dict[str, dict[str, str | None]] = {}
    for p in selected_platforms:
        st.subheader(f"Priorities for {platform_names[p]}")
        p1 = st.selectbox(
            f"Primary objective on {platform_names[p]}",
            options=[None] + state.valid_goals,
            format_func=lambda x: {None: "(none)", GOAL_AW: "Awareness", GOAL_EN: "Engagement", GOAL_WT: "Website Traffic", GOAL_LG: "Lead Generation"}.get(x, x),
            key=f"{p}_p1",
        )
        p2_options = [None] + [g for g in state.valid_goals if g != p1]
        p2 = st.selectbox(
            f"Secondary objective on {platform_names[p]} (optional)",
            options=p2_options,
            format_func=lambda x: {None: "(none)", GOAL_AW: "Awareness", GOAL_EN: "Engagement", GOAL_WT: "Website Traffic", GOAL_LG: "Lead Generation"}.get(x, x),
            key=f"{p}_p2",
        )
        priorities_input[p] = {"priority_1": p1, "priority_2": p2}
    if st.button("Continue to Module 3", disabled=not selected_platforms):
        # Run Module 2 logic and finalise via WizardState
        state = run_module2(state, selected_platforms, priorities_input)
        safe_rerun()


def module3_ui(state: WizardState) -> None:
    """Render UI for Module 3: collect budget and KPI data."""
    st.header("🔹 Module 3: Provide historical data")
    m3_data: dict[str, dict[str, Any]] = {}
    platform_budgets: dict[str, float] = {}
    platform_kpis: dict[str, dict[str, float]] = {}
    # For each active platform ask time window, budget and KPI values
    for platform in state.active_platforms:
        # Use human‑friendly platform name in headings and prompts
        platform_name = PLATFORM_NAMES.get(platform, platform.upper())
        st.subheader(f"Data for {platform_name}")
        # Ask for time window with full platform name
        time_window = st.text_input(
            f"Time window for {platform_name} (e.g. 'last 30 days')",
            key=f"time_{platform}",
        )
        # Ask for historical budget with full platform name
        budget = st.number_input(
            f"Total historical budget on {platform_name} (> 1)",
            min_value=1.0,
            value=1000.0,
            step=100.0,
            key=f"budget_{platform}",
        )
        # Determine relevant KPIs using KPI_CONFIG and active goals
        kpi_defs = [
            row
            for row in KPI_CONFIG
            if row["platform"] == platform and row["goal"] in state.goals_by_platform.get(platform, [])
        ]
        kpi_values: dict[str, float] = {}
        for kpi_def in kpi_defs:
            var = kpi_def["var"]
            label = kpi_def["kpi_label"]
            goal_code = kpi_def["goal"]
            # Compose descriptive label: Goal – KPI label on Platform
            goal_name = GOAL_NAMES.get(goal_code, goal_code)
            descriptive_label = f"{goal_name} – {label} on {platform_name} (> 1)"
            val = st.number_input(
                descriptive_label,
                min_value=1.0,
                value=1.0,
                step=0.1,
                key=f"{platform}_{var}",
            )
            kpi_values[var] = val
        m3_data[platform] = {"time_window": time_window, "budget": budget, "kpis": kpi_values}
        platform_budgets[platform] = budget
        platform_kpis[platform] = kpi_values
    if st.button("Run optimisation", disabled=any(not d["time_window"] or d["budget"] <= 1 for d in m3_data.values())):
        # Compute KPI ratios. For each KPI value entered, divide by the platform
        # budget to obtain a historical KPI per unit of spend.
        kpi_ratios: dict[str, dict[str, float]] = {}
        for platform in m3_data:
            b = float(m3_data[platform]["budget"])
            ratios_for_p = {k: float(v) / b for k, v in m3_data[platform]["kpis"].items()}
            kpi_ratios[platform] = ratios_for_p
        # Finalise Module 3 and advance the wizard to step 4. Downstream
        # modules will be executed lazily in the results UI after the rerun.
        state.complete_module3_and_advance(
            module3_data=m3_data,
            platform_budgets=platform_budgets,
            platform_kpis=platform_kpis,
            kpi_ratios=kpi_ratios,
        )
        # Trigger a rerun to refresh the UI. The results page will handle
        # execution of modules 4–6.
        safe_rerun()


def results_ui(state: WizardState) -> None:
    """Display results after Module 6."""
    st.header("📊 Results")

    # --------------------------------------------------------------------
    # Auto-run Modules 4–6 if they haven't been executed yet. When the user
    # completes Module 3 the wizard moves to step 4 but modules 4, 5 and 6
    # aren't invoked immediately. Executing them here avoids flow errors
    # caused by calling downstream modules in the same Streamlit run cycle.
    if not state.module4_finalised and state.module3_finalised:
        run_module4(state, KPI_CONFIG)
    if not state.module5_finalised and state.module4_finalised:
        run_module5(state)
    if not state.module6_finalised and state.module5_finalised:
        # Keep the wizard on step 6 after Module 6 completes so that
        # results are still shown in this page.
        run_module6(state, next_step=6)

    # Display optimisation output
    if state.module5_result:
        # -----------------------------------------
        # Budget allocation summary
        # -----------------------------------------
        st.subheader("Budget allocation per platform and goal")
        # Display budget allocations with full platform and goal names
        for platform_code, goals in state.module5_result.budget_per_platform_goal.items():
            platform_name = PLATFORM_NAMES.get(platform_code.lower(), platform_code.upper())
            # Map goal codes to human‑friendly names
            goals_display: dict[str, float] = {
                GOAL_NAMES.get(goal_code, goal_code): value for goal_code, value in goals.items()
            }
            st.write(f"{platform_name}: {goals_display}")
        st.write("**Total budget used:**", state.module5_result.total_budget_used)

        # -----------------------------------------
        # Insight generation
        # -----------------------------------------
        # Generate simple insights from budget and predicted KPI data
        insights: list[str] = []
        # Identify platform with highest allocated budget
        max_budget_platform = max(
            state.module5_result.budget_per_platform.items(),
            key=lambda x: x[1],
            default=(None, 0.0),
        )
        if max_budget_platform[0] is not None:
            max_platform_code, max_budget = max_budget_platform
            max_platform_name = PLATFORM_NAMES.get(max_platform_code.lower(), max_platform_code)
            insights.append(
                f"The highest budget allocation is on {max_platform_name} with {max_budget:.2f} units."
            )
        # Identify KPI with highest predicted value
        if state.module6_result and state.module6_result.rows:
            max_kpi_row = max(
                state.module6_result.rows,
                key=lambda r: r.predicted_kpi,
            )
            max_kpi_platform = PLATFORM_NAMES.get(max_kpi_row.platform.lower(), max_kpi_row.platform)
            # Derive descriptive KPI name from KPI_CONFIG
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

        # -----------------------------------------
        # KPI forecast display
        # -----------------------------------------
        if state.module6_result:
            st.subheader("Predicted KPIs")
            # Build a mapping from KPI var to descriptive label (Goal – KPI label)
            var_to_description: dict[str, str] = {}
            for row in KPI_CONFIG:
                goal_code = row["goal"]
                goal_name = GOAL_NAMES.get(goal_code, goal_code)
                description = f"{goal_name} – {row['kpi_label']}"
                var_to_description[row["var"]] = description
            # Convert rows to DataFrame
            import pandas as pd  # type: ignore
            formatted_rows = []
            for row in state.module6_result.rows:
                platform_name = PLATFORM_NAMES.get(row.platform.lower(), row.platform)
                kpi_description = var_to_description.get(row.kpi_name, row.kpi_name)
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

        # -----------------------------------------
        # Chart generation
        # -----------------------------------------
        # Create bar charts for budget allocation and predicted KPI totals per platform
        if st.checkbox("Show budget and KPI distribution charts"):
            # Bar chart for budget per platform
            budget_labels = [PLATFORM_NAMES.get(p.lower(), p) for p in state.module5_result.budget_per_platform.keys()]
            budget_values = list(state.module5_result.budget_per_platform.values())
            fig1, ax1 = plt.subplots()
            ax1.bar(budget_labels, budget_values)
            ax1.set_title("Budget allocation per platform")
            ax1.set_xlabel("Platform")
            ax1.set_ylabel("Budget")
            st.pyplot(fig1)
            # Bar chart for total predicted KPI per platform
            if state.module6_result:
                kpi_totals: dict[str, float] = {}
                for row in state.module6_result.rows:
                    kpi_totals[row.platform] = kpi_totals.get(row.platform, 0.0) + row.predicted_kpi
                kpi_labels = [PLATFORM_NAMES.get(p.lower(), p) for p in kpi_totals.keys()]
                kpi_values = list(kpi_totals.values())
                fig2, ax2 = plt.subplots()
                ax2.bar(kpi_labels, kpi_values)
                ax2.set_title("Total predicted KPI per platform")
                ax2.set_xlabel("Platform")
                ax2.set_ylabel("Predicted KPI")
                st.pyplot(fig2)

        # -----------------------------------------
        # PDF generation and download
        # -----------------------------------------
        # Function to create a PDF summary of the results
        def create_pdf(state: WizardState, insights_list: list[str], df_data) -> bytes:
            buffer = io.BytesIO()
            # Create a PDF with reportlab
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story: list[Any] = []
            story.append(Paragraph("Results Summary", styles["Title"]))
            story.append(Spacer(1, 12))
            # Add budget allocation summary
            story.append(Paragraph("<b>Budget allocation per platform and goal</b>", styles["Heading2"]))
            for platform_code, goals in state.module5_result.budget_per_platform_goal.items():
                platform_name = PLATFORM_NAMES.get(platform_code.lower(), platform_code)
                goals_display = {GOAL_NAMES.get(goal_code, goal_code): value for goal_code, value in goals.items()}
                story.append(Paragraph(f"{platform_name}: {goals_display}", styles["Normal"]))
            story.append(Paragraph(f"<b>Total budget used:</b> {state.module5_result.total_budget_used:.2f}", styles["Normal"]))
            story.append(Spacer(1, 12))
            # Add insights
            if insights_list:
                story.append(Paragraph("<b>Insights</b>", styles["Heading2"]))
                for ins in insights_list:
                    story.append(Paragraph(f"• {ins}", styles["Normal"]))
                story.append(Spacer(1, 12))
            # Add KPI table
            if not df_data.empty:
                story.append(Paragraph("<b>Predicted KPIs</b>", styles["Heading2"]))
                # Convert DataFrame to list of lists for reportlab Table
                table_data = [list(df_data.columns)] + df_data.values.tolist()
                tbl = Table(table_data)
                tbl.setStyle(
                    TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), (0.85, 0.85, 0.85)),
                        ("GRID", (0, 0), (-1, -1), 1, (0, 0, 0)),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ])
                )
                story.append(tbl)
            doc.build(story)
            pdf = buffer.getvalue()
            buffer.close()
            return pdf

        # Provide PDF download button
        if st.button("Download results as PDF"):
            import pandas as pd  # type: ignore
            # Build DataFrame again to pass to PDF
            formatted_rows_pdf = []
            if state.module6_result:
                var_to_description_pdf = {}
                for row_conf in KPI_CONFIG:
                    goal_name = GOAL_NAMES.get(row_conf["goal"], row_conf["goal"])
                    var_to_description_pdf[row_conf["var"]] = f"{goal_name} – {row_conf['kpi_label']}"
                for row in state.module6_result.rows:
                    platform_name_pdf = PLATFORM_NAMES.get(row.platform.lower(), row.platform)
                    kpi_desc_pdf = var_to_description_pdf.get(row.kpi_name, row.kpi_name)
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
    # Provide a start over button
    if st.button("Start over"):
        reset_state()
        safe_rerun()


def main() -> None:
    """Main entry point for the Streamlit app."""
    initialise_state()
    state: WizardState = st.session_state["wizard_state"]
    # Navigation based on current_step
    if state.current_step == 1:
        module1_ui(state)
    elif state.current_step == 2:
        module2_ui(state)
    elif state.current_step == 3:
        module3_ui(state)
    else:
        # Steps 4–6 show results
        results_ui(state)


if __name__ == "__main__":
    main()
