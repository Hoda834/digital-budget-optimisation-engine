from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from reportlab.lib import colors  # type: ignore
from reportlab.lib.pagesizes import letter  # type: ignore
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # type: ignore

from core.wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_LG, GOAL_WT
from core.kpi_config import KPI_CONFIG
from modules.module2 import run_module2
from modules.module4 import run_module4
from modules.module5 import Module5LPResult, Module5ScenarioBundle, run_module5
from modules.module6 import Module6Result, Module6ScenarioResult, run_module6


PLATFORM_NAMES: Dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
}

GOAL_NAMES: Dict[str, str] = {
    GOAL_AW: "Awareness",
    GOAL_EN: "Engagement",
    GOAL_WT: "Website Traffic",
    GOAL_LG: "Lead Generation",
}

SCENARIO_DISPLAY_ORDER: List[str] = ["conservative", "base", "optimistic"]


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


def initialise_state() -> None:
    if "wizard_state" not in st.session_state:
        st.session_state["wizard_state"] = WizardState()


def reset_state() -> None:
    st.session_state["wizard_state"] = WizardState()
    safe_rerun()


def money(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        return "£0.00"
    return f"£{v:,.2f}"


def number(x: Any, decimals: int = 2) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(v)


def build_kpi_meta() -> Dict[str, Dict[str, Any]]:
    meta: Dict[str, Dict[str, Any]] = {}
    for row in KPI_CONFIG:
        var = str(row.get("var", "")).strip()
        if not var:
            continue
        meta[var] = {
            "platform": str(row.get("platform", "")).strip(),
            "goal": str(row.get("goal", "")).strip(),
            "kpi_label": str(row.get("kpi_label", "")).strip(),
        }
    return meta


def build_budget_allocation_df(lp_res: Module5LPResult) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for platform_code, goals_map in (lp_res.budget_per_platform_goal or {}).items():
        p_code = str(platform_code).lower()
        platform_name = PLATFORM_NAMES.get(p_code, str(platform_code))
        for goal_code, value in (goals_map or {}).items():
            g_code = str(goal_code)
            rows.append(
                {
                    "Platform": platform_name,
                    "Objective": GOAL_NAMES.get(g_code, g_code),
                    "Allocated Budget": float(value or 0.0),
                }
            )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Platform", "Objective"]).reset_index(drop=True)
    return df


def build_platform_totals_df(lp_res: Module5LPResult) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for platform_code, value in (lp_res.budget_per_platform or {}).items():
        p_code = str(platform_code).lower()
        rows.append(
            {
                "Platform": PLATFORM_NAMES.get(p_code, str(platform_code)),
                "Total Allocated Budget": float(value or 0.0),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Platform"]).reset_index(drop=True)
    return df


def build_forecast_df(module6_res: Module6Result) -> pd.DataFrame:
    kpi_meta = build_kpi_meta()
    rows: List[Dict[str, Any]] = []

    for r in (module6_res.rows or []):
        var = str(r.kpi_name)
        meta = kpi_meta.get(var, {})

        platform_code = str(r.platform).lower()
        platform_name = PLATFORM_NAMES.get(platform_code, str(r.platform))

        objective_code = str(getattr(r, "objective", "") or "")
        objective_name = GOAL_NAMES.get(objective_code, objective_code) if objective_code else ""

        kpi_label = str(meta.get("kpi_label", "")).strip() or "KPI"

        rows.append(
            {
                "Platform": platform_name,
                "Objective": objective_name,
                "KPI": kpi_label,
                "Allocated Budget": float(r.allocated_budget or 0.0),
                "Predicted KPI": float(r.predicted_kpi or 0.0),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Platform", "Objective", "KPI"]).reset_index(drop=True)
    return df


def build_budget_matrix_df(lp_res: Module5LPResult) -> pd.DataFrame:
    df = build_budget_allocation_df(lp_res)
    if df.empty:
        return df
    pivot = (
        df.pivot_table(
            index="Platform",
            columns="Objective",
            values="Allocated Budget",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    return pivot


def build_forecast_matrix_df(fc_res: Module6Result) -> pd.DataFrame:
    df = build_forecast_df(fc_res)
    if df.empty:
        return df
    pivot = (
        df.pivot_table(
            index="Platform",
            columns="KPI",
            values="Predicted KPI",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    return pivot


def _get_scenario_key_order(keys: List[str]) -> List[str]:
    lower_map = {k.lower(): k for k in keys}
    ordered: List[str] = []
    for k in SCENARIO_DISPLAY_ORDER:
        if k in lower_map:
            ordered.append(lower_map[k])
    for k in sorted(keys):
        if k not in ordered:
            ordered.append(k)
    return ordered


def _human_scenario_name(name: str) -> str:
    n = name.strip().lower()
    if n == "base":
        return "Base"
    if n == "conservative":
        return "Conservative"
    if n == "optimistic":
        return "Optimistic"
    return name


def _policy_tables(state: WizardState) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    p_rows: List[Dict[str, Any]] = []
    for p, v in (getattr(state, "min_spend_per_platform", {}) or {}).items():
        p_code = str(p).lower()
        p_rows.append({"Platform": PLATFORM_NAMES.get(p_code, str(p)), "Minimum Spend": float(v or 0.0)})
    df_p = pd.DataFrame(p_rows)
    if not df_p.empty:
        df_p = df_p.sort_values(["Platform"]).reset_index(drop=True)

    g_rows: List[Dict[str, Any]] = []
    for g, v in (getattr(state, "min_budget_per_goal", {}) or {}).items():
        g_code = str(g)
        g_rows.append({"Objective": GOAL_NAMES.get(g_code, g_code), "Minimum Budget": float(v or 0.0)})
    df_g = pd.DataFrame(g_rows)
    if not df_g.empty:
        df_g = df_g.sort_values(["Objective"]).reset_index(drop=True)

    s_rows: List[Dict[str, Any]] = []
    for k, v in (getattr(state, "scenario_multipliers", {}) or {}).items():
        s_rows.append({"Scenario": _human_scenario_name(str(k)), "Multiplier": float(v or 0.0)})
    df_s = pd.DataFrame(s_rows)
    if not df_s.empty:
        df_s = df_s.sort_values(["Scenario"]).reset_index(drop=True)

    return df_p, df_g, df_s


def _scenario_goal_multiplier_table(state: WizardState) -> pd.DataFrame:
    sgm = getattr(state, "scenario_goal_multipliers", {}) or {}
    if not isinstance(sgm, dict) or not sgm:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for s_name, gmap in sgm.items():
        if not isinstance(gmap, dict):
            continue
        row: Dict[str, Any] = {"Scenario": _human_scenario_name(str(s_name))}
        for g in state.valid_goals:
            row[GOAL_NAMES.get(str(g), str(g))] = float(gmap.get(g, 1.0) or 1.0)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    cols = ["Scenario"] + [GOAL_NAMES.get(str(g), str(g)) for g in state.valid_goals]
    df = df[cols]
    df = df.sort_values(["Scenario"]).reset_index(drop=True)
    return df


def create_excel_bytes(
    scenario_payload: List[Tuple[str, Module5LPResult, Optional[Module6Result]]],
) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for scenario_name, lp_res, forecast_res in scenario_payload:
            suffix = scenario_name.strip().lower()
            suffix = suffix[:10] if suffix else "base"

            summary_rows: List[Dict[str, Any]] = [
                {"Metric": "Total Budget Used", "Value": float(lp_res.total_budget_used or 0.0)},
                {"Metric": "Objective Value", "Value": float(lp_res.objective_value or 0.0)},
            ]
            if hasattr(lp_res, "objective_value_raw"):
                summary_rows.append({"Metric": "Objective Value (raw)", "Value": float(getattr(lp_res, "objective_value_raw") or 0.0)})

            summary_df = pd.DataFrame(summary_rows)
            budget_df = build_budget_allocation_df(lp_res)
            platform_df = build_platform_totals_df(lp_res)

            summary_df.to_excel(writer, sheet_name=f"Summary_{suffix}"[:31], index=False)
            budget_df.to_excel(writer, sheet_name=f"Budget_{suffix}"[:31], index=False)
            platform_df.to_excel(writer, sheet_name=f"Platforms_{suffix}"[:31], index=False)

            if forecast_res is not None:
                forecast_df = build_forecast_df(forecast_res)
                forecast_df.to_excel(writer, sheet_name=f"Forecast_{suffix}"[:31], index=False)

    buffer.seek(0)
    return buffer.getvalue()


def _df_to_table_data(df: pd.DataFrame, money_columns: Optional[List[str]] = None) -> List[List[str]]:
    money_columns = money_columns or []
    cols = list(df.columns)
    out: List[List[str]] = [cols]
    for _, row in df.iterrows():
        r: List[str] = []
        for c in cols:
            v = row[c]
            if c in money_columns:
                r.append(money(v))
            else:
                if isinstance(v, (int, float)):
                    r.append(number(v, 2))
                else:
                    r.append(str(v))
        out.append(r)
    return out


def create_pdf_bytes(
    state: WizardState,
    scenario_payload: List[Tuple[str, Module5LPResult, Optional[Module6Result]]],
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story: List[Any] = []

    story.append(Paragraph("Results Summary", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Optimisation method: Linear Programming (LP) to allocate budget across platform and objective.", styles["BodyText"]))
    story.append(Spacer(1, 12))

    df_p, df_g, df_s = _policy_tables(state)

    story.append(Paragraph("Policy Summary", styles["Heading2"]))
    story.append(Spacer(1, 6))

    if not df_p.empty:
        story.append(Paragraph("Minimum Spend per Platform", styles["Heading3"]))
        t = Table(_df_to_table_data(df_p, money_columns=["Minimum Spend"]))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    if not df_g.empty:
        story.append(Paragraph("Minimum Budget per Objective", styles["Heading3"]))
        t = Table(_df_to_table_data(df_g, money_columns=["Minimum Budget"]))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    if not df_s.empty:
        story.append(Paragraph("Scenario Multipliers (overall)", styles["Heading3"]))
        t = Table(_df_to_table_data(df_s))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    df_sgm = _scenario_goal_multiplier_table(state)
    if not df_sgm.empty:
        story.append(Paragraph("Scenario Multipliers per Objective", styles["Heading3"]))
        t = Table(_df_to_table_data(df_sgm))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    for scenario_name, lp_res, forecast_res in scenario_payload:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Scenario: {_human_scenario_name(scenario_name)}", styles["Heading2"]))
        story.append(Spacer(1, 6))

        summary_rows: List[Dict[str, Any]] = [
            {"Metric": "Total Budget Used", "Value": money(lp_res.total_budget_used or 0.0)},
            {"Metric": "Objective Value", "Value": number(lp_res.objective_value or 0.0, 2)},
        ]
        if hasattr(lp_res, "objective_value_raw"):
            summary_rows.append({"Metric": "Objective Value (raw)", "Value": number(getattr(lp_res, "objective_value_raw") or 0.0, 6)})

        summary_df = pd.DataFrame(summary_rows)
        t = Table(_df_to_table_data(summary_df))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

        budget_df = build_budget_allocation_df(lp_res)
        if not budget_df.empty:
            story.append(Paragraph("Budget Allocation", styles["Heading3"]))
            t = Table(_df_to_table_data(budget_df, money_columns=["Allocated Budget"]))
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 10))

        if forecast_res is not None:
            forecast_df = build_forecast_df(forecast_res)
            if not forecast_df.empty:
                story.append(Paragraph("Forecast KPIs (goal-aligned)", styles["Heading3"]))
                t = Table(_df_to_table_data(forecast_df, money_columns=["Allocated Budget"]))
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ]
                    )
                )
                story.append(t)
                story.append(Spacer(1, 10))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def module1_ui(state: WizardState) -> None:
    st.header("Objectives and total budget")

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

    if st.button("Continue", disabled=not goal_codes or total_budget <= 1):
        state.complete_module1_and_advance(valid_goals=goal_codes, total_budget=total_budget)
        safe_rerun()


def module2_ui(state: WizardState) -> None:
    st.header("Platforms and priorities")

    platforms = ["fb", "ig", "li", "yt"]
    selected_platforms = st.multiselect(
        "Choose one or more platforms:",
        options=platforms,
        format_func=lambda p: PLATFORM_NAMES.get(str(p).lower(), str(p)),
    )

    priorities_input: Dict[str, Dict[str, Optional[str]]] = {}
    is_valid = True

    for p in selected_platforms:
        platform_name = PLATFORM_NAMES.get(p, p)
        st.subheader(platform_name)

        p1_key = f"{p}_p1"
        p2_key = f"{p}_p2"

        p1 = st.selectbox(
            f"Priority 1 objective for {platform_name}",
            options=[None] + list(state.valid_goals),
            format_func=lambda x: {
                None: "(none)",
                GOAL_AW: "Awareness",
                GOAL_EN: "Engagement",
                GOAL_WT: "Website Traffic",
                GOAL_LG: "Lead Generation",
            }.get(x, str(x)),
            key=p1_key,
        )

        allowed_p2_options = [None] + [g for g in state.valid_goals if g != p1]

        current_p2 = st.session_state.get(p2_key, None)
        if current_p2 == p1 and current_p2 is not None:
            st.session_state[p2_key] = None
            current_p2 = None

        p2 = st.selectbox(
            f"Priority 2 objective for {platform_name}",
            options=allowed_p2_options,
            format_func=lambda x: {
                None: "(none)",
                GOAL_AW: "Awareness",
                GOAL_EN: "Engagement",
                GOAL_WT: "Website Traffic",
                GOAL_LG: "Lead Generation",
            }.get(x, str(x)),
            key=p2_key,
        )

        if p2 is not None and p1 is None:
            is_valid = False
            st.error("Priority 2 cannot be set without Priority 1.")

        if p1 is not None and p2 is not None and p1 == p2:
            is_valid = False
            st.error("Priority 1 and Priority 2 must be different.")

        if len(state.valid_goals) == 1 and p2 is not None:
            is_valid = False
            st.error("Priority 2 cannot be set when there is only one selected objective.")

        priorities_input[p] = {"priority_1": p1, "priority_2": p2}

    if st.button("Continue", disabled=(not selected_platforms) or (not is_valid)):
        try:
            run_module2(state, selected_platforms, priorities_input)
            safe_rerun()
        except Exception:
            st.error("Please review your selections and try again.")


def module3_ui(state: WizardState) -> None:
    st.header("Historical data")

    m3_data: Dict[str, Dict[str, Any]] = {}
    platform_budgets: Dict[str, float] = {}
    platform_kpis: Dict[str, Dict[str, float]] = {}

    for platform in state.active_platforms:
        platform_name = PLATFORM_NAMES.get(platform, platform.upper())
        st.subheader(f"Data for {platform_name}")

        time_window = st.text_input(
            f"Time window for {platform_name} (for example: last 30 days)",
            key=f"time_{platform}",
        )

        budget = st.number_input(
            f"Total historical budget on {platform_name} (must be greater than 1)",
            min_value=1.01,
            value=1000.0,
            step=100.0,
            key=f"budget_{platform}",
        )

        kpi_defs = [
            row
            for row in KPI_CONFIG
            if row["platform"] == platform and row["goal"] in state.goals_by_platform.get(platform, [])
        ]

        kpi_values: Dict[str, float] = {}
        for kpi_def in kpi_defs:
            var = kpi_def["var"]
            label = kpi_def["kpi_label"]
            goal_code = kpi_def["goal"]
            goal_name = GOAL_NAMES.get(goal_code, goal_code)
            descriptive_label = f"{goal_name} - {label} on {platform_name} (must be greater than 1)"

            val = st.number_input(
                descriptive_label,
                min_value=1.01,
                value=1.01,
                step=0.1,
                key=f"{platform}_{var}",
            )
            kpi_values[var] = float(val)

        m3_data[platform] = {"time_window": time_window, "budget": float(budget), "kpis": kpi_values}
        platform_budgets[platform] = float(budget)
        platform_kpis[platform] = kpi_values

    can_run = True
    for _, d in m3_data.items():
        if not d.get("time_window"):
            can_run = False
            break
        if float(d.get("budget", 0.0)) <= 1.0:
            can_run = False
            break
        for _, kpi_val in (d.get("kpis", {}) or {}).items():
            if float(kpi_val) <= 1.0:
                can_run = False
                break
        if not can_run:
            break

    if st.button("Run optimisation", disabled=not can_run):
        kpi_ratios: Dict[str, Dict[str, Dict[str, float]]] = {}

        for platform in m3_data:
            b = float(m3_data[platform]["budget"])
            goals_for_platform = state.goals_by_platform.get(platform, [])

            kpi_ratios[platform] = {}
            for g in goals_for_platform:
                kpi_ratios[platform][g] = {}

            for row in KPI_CONFIG:
                p = row["platform"]
                g = row["goal"]
                var = row["var"]

                if p != platform:
                    continue
                if g not in goals_for_platform:
                    continue

                val = float(m3_data[platform]["kpis"].get(var, 0.0))
                if val <= 0.0 or b <= 0.0:
                    continue

                kpi_ratios[platform][g][var] = val / b

            kpi_ratios[platform] = {g: d for g, d in kpi_ratios[platform].items() if d}

        state.complete_module3_and_advance(
            module3_data=m3_data,
            platform_budgets=platform_budgets,
            platform_kpis=platform_kpis,
            kpi_ratios=kpi_ratios,
        )
        safe_rerun()


def _get_module5_scenarios(state: WizardState) -> Dict[str, Module5LPResult]:
    bundle = getattr(state, "module5_scenario_bundle", None)
    if isinstance(bundle, Module5ScenarioBundle):
        return dict(bundle.results_by_scenario)

    by_scenario = getattr(state, "module5_results_by_scenario", None)
    if isinstance(by_scenario, dict) and by_scenario:
        return dict(by_scenario)

    if state.module5_result is not None:
        return {"base": state.module5_result}

    return {}


def _get_module6_scenarios(state: WizardState) -> Dict[str, Module6Result]:
    sres = getattr(state, "module6_scenario_result", None)
    if isinstance(sres, Module6ScenarioResult):
        return dict(sres.results_by_scenario)

    if state.module6_result is not None:
        return {"base": state.module6_result}

    return {}


def results_ui(state: WizardState) -> None:
    st.header("Results")

    if st.button("Reset", type="secondary"):
        reset_state()
        return

    if state.module3_finalised and not state.module4_finalised:
        run_module4(state, KPI_CONFIG)
    if state.module4_finalised and not state.module5_finalised:
        run_module5(state)
    if state.module5_finalised and not state.module6_finalised:
        run_module6(state)

    if not state.module6_finalised:
        st.info("Results will appear after optimisation runs.")
        return

    st.markdown("Optimisation method: Linear Programming (LP) to allocate budget across platform and objective.")

    df_p, df_g, df_s = _policy_tables(state)
    df_sgm = _scenario_goal_multiplier_table(state)

    if not df_p.empty or not df_g.empty or not df_s.empty or not df_sgm.empty:
        st.subheader("Policy summary")
        cols = st.columns(4)
        with cols[0]:
            if not df_p.empty:
                show = df_p.copy()
                show["Minimum Spend"] = show["Minimum Spend"].apply(money)
                st.markdown("Minimum spend per platform")
                st.dataframe(show, use_container_width=True, hide_index=True)
        with cols[1]:
            if not df_g.empty:
                show = df_g.copy()
                show["Minimum Budget"] = show["Minimum Budget"].apply(money)
                st.markdown("Minimum budget per objective")
                st.dataframe(show, use_container_width=True, hide_index=True)
        with cols[2]:
            if not df_s.empty:
                show = df_s.copy()
                show["Multiplier"] = show["Multiplier"].apply(lambda x: number(x, 2))
                st.markdown("Scenario multipliers (overall)")
                st.dataframe(show, use_container_width=True, hide_index=True)
        with cols[3]:
            if not df_sgm.empty:
                show = df_sgm.copy()
                for c in show.columns:
                    if c != "Scenario":
                        show[c] = show[c].apply(lambda x: number(x, 2))
                st.markdown("Scenario multipliers per objective")
                st.dataframe(show, use_container_width=True, hide_index=True)

    lp_by_scenario = _get_module5_scenarios(state)
    fc_by_scenario = _get_module6_scenarios(state)
    scenario_keys = _get_scenario_key_order(list(lp_by_scenario.keys()))

    if not scenario_keys:
        st.error("No results available.")
        return

    comparison_rows: List[Dict[str, Any]] = []
    for sk in scenario_keys:
        lp_res = lp_by_scenario.get(sk)
        if lp_res is None:
            continue
        row: Dict[str, Any] = {
            "Scenario": _human_scenario_name(sk),
            "Total Budget Used": float(lp_res.total_budget_used or 0.0),
            "Objective Value": float(lp_res.objective_value or 0.0),
        }
        if hasattr(lp_res, "objective_value_raw"):
            row["Objective Value (raw)"] = float(getattr(lp_res, "objective_value_raw") or 0.0)
        comparison_rows.append(row)

    df_compare = pd.DataFrame(comparison_rows)
    if not df_compare.empty:
        st.subheader("Scenario comparison")
        show_df = df_compare.copy()
        show_df["Total Budget Used"] = show_df["Total Budget Used"].apply(money)
        show_df["Objective Value"] = show_df["Objective Value"].apply(lambda x: number(x, 2))
        if "Objective Value (raw)" in show_df.columns:
            show_df["Objective Value (raw)"] = show_df["Objective Value (raw)"].apply(lambda x: number(x, 6))
        st.dataframe(show_df, use_container_width=True, hide_index=True)

        chart_df = df_compare.copy()
        chart_df["Scenario"] = chart_df["Scenario"].apply(_human_scenario_name)

        st.subheader("Chart: objective value by scenario")
        st.bar_chart(chart_df.set_index("Scenario")[["Objective Value"]])

        st.subheader("Chart: total budget used by scenario")
        st.bar_chart(chart_df.set_index("Scenario")[["Total Budget Used"]])

    tabs = st.tabs([_human_scenario_name(k) for k in scenario_keys])
    scenario_payload_for_exports: List[Tuple[str, Module5LPResult, Optional[Module6Result]]] = []

    def rule_based_summary(lp_res: Module5LPResult, fc_res: Optional[Module6Result]) -> List[str]:
        bullets: List[str] = []

        platform_totals = build_platform_totals_df(lp_res)
        if not platform_totals.empty:
            top_p = platform_totals.sort_values("Total Allocated Budget", ascending=False).iloc[0]
            bullets.append(f"Highest allocated platform: {top_p['Platform']} with {money(top_p['Total Allocated Budget'])}.")

        alloc = build_budget_allocation_df(lp_res)
        if not alloc.empty:
            goal_totals = alloc.groupby("Objective", as_index=False)["Allocated Budget"].sum()
            if not goal_totals.empty:
                top_g = goal_totals.sort_values("Allocated Budget", ascending=False).iloc[0]
                bullets.append(f"Highest allocated objective: {top_g['Objective']} with {money(top_g['Allocated Budget'])}.")

        if fc_res is not None:
            fdf = build_forecast_df(fc_res)
            if not fdf.empty:
                top_kpi = fdf.sort_values("Predicted KPI", ascending=False).iloc[0]
                bullets.append(f"Top predicted KPI: {top_kpi['KPI']} on {top_kpi['Platform']} at {number(top_kpi['Predicted KPI'], 2)}.")

        if hasattr(lp_res, "objective_value_raw"):
            bullets.append(f"Objective (raw): {number(getattr(lp_res, 'objective_value_raw') or 0.0, 6)}.")

        return bullets

    for tab, sk in zip(tabs, scenario_keys):
        lp_res = lp_by_scenario.get(sk)
        if lp_res is None:
            continue
        forecast_res = fc_by_scenario.get(sk)
        scenario_payload_for_exports.append((sk, lp_res, forecast_res))

        with tab:
            st.subheader("Summary")
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Total budget used", money(lp_res.total_budget_used or 0.0))
            with c2:
                st.metric("Objective value", number(lp_res.objective_value or 0.0, 2))

            if hasattr(lp_res, "objective_value_raw"):
                st.caption(f"Objective value (raw): {number(getattr(lp_res, 'objective_value_raw') or 0.0, 6)}")

            bullets = rule_based_summary(lp_res, forecast_res)
            if bullets:
                st.markdown("Key points")
                for b in bullets:
                    st.write(b)

            st.subheader("Matrix: budget allocation (platform x objective)")
            budget_matrix = build_budget_matrix_df(lp_res)
            if budget_matrix.empty:
                st.info("No allocation matrix available.")
            else:
                show = budget_matrix.copy()
                for c in show.columns:
                    if c != "Platform":
                        show[c] = show[c].apply(money)
                st.dataframe(show, use_container_width=True, hide_index=True)

            st.subheader("Budget allocation table")
            budget_df = build_budget_allocation_df(lp_res)
            if budget_df.empty:
                st.warning("No budget allocation to display.")
            else:
                show_budget = budget_df.copy()
                show_budget["Allocated Budget"] = show_budget["Allocated Budget"].apply(money)
                st.dataframe(show_budget, use_container_width=True, hide_index=True)

            st.subheader("Platform totals")
            platform_df = build_platform_totals_df(lp_res)
            if not platform_df.empty:
                show_platform = platform_df.copy()
                show_platform["Total Allocated Budget"] = show_platform["Total Allocated Budget"].apply(money)
                st.dataframe(show_platform, use_container_width=True, hide_index=True)

            st.subheader("Matrix: forecast KPIs (platform x KPI)")
            if forecast_res is None:
                st.info("Forecast is not available for this scenario.")
            else:
                forecast_matrix = build_forecast_matrix_df(forecast_res)
                if forecast_matrix.empty:
                    st.info("No forecast matrix available.")
                else:
                    show = forecast_matrix.copy()
                    for c in show.columns:
                        if c != "Platform":
                            show[c] = show[c].apply(lambda x: number(x, 2))
                    st.dataframe(show, use_container_width=True, hide_index=True)

            st.subheader("Forecast KPIs table")
            if forecast_res is None:
                st.info("Forecast is not available for this scenario.")
            else:
                forecast_df = build_forecast_df(forecast_res)
                if forecast_df.empty:
                    st.warning("No forecast KPIs to display.")
                else:
                    show_forecast = forecast_df.copy()
                    show_forecast["Allocated Budget"] = show_forecast["Allocated Budget"].apply(money)
                    show_forecast["Predicted KPI"] = show_forecast["Predicted KPI"].apply(lambda x: number(x, 2))
                    st.dataframe(show_forecast, use_container_width=True, hide_index=True)

    st.subheader("Downloads")
    pdf_bytes = create_pdf_bytes(state, scenario_payload_for_exports)

    st.download_button(
        label="Download PDF",
        data=pdf_bytes,
        file_name="results_summary.pdf",
        mime="application/pdf",
    )

    excel_available = True
    try:
        import openpyxl  # type: ignore  # noqa: F401
    except Exception:
        excel_available = False

    if excel_available:
        xlsx_bytes = create_excel_bytes(scenario_payload_for_exports)
        st.download_button(
            label="Download Excel",
            data=xlsx_bytes,
            file_name="results_summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("Excel export is unavailable because the required dependency is not installed.")

    if st.button("Start over"):
        reset_state()


def main() -> None:
    st.set_page_config(page_title="Marketing Budget Optimisation", layout="wide")
    initialise_state()

    state: WizardState = st.session_state["wizard_state"]
    if state.current_step == 1:
        module1_ui(state)
        return
    if state.current_step == 2:
        module2_ui(state)
        return
    if state.current_step == 3:
        module3_ui(state)
        return

    results_ui(state)


if __name__ == "__main__":
    main()
