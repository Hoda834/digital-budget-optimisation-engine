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
from modules.module1 import (
    complete_module1_and_advance as finalise_module1,
    Module1ValidationError,
)
from core.kpi_config import KPI_CONFIG, effective_kpi_config
from core.csv_import import (
    parse_platform_csv,
    SUPPORTED_PLATFORMS as CSV_SUPPORTED,
    generate_csv_template,
)
from modules.module3 import finalise_module3_from_inputs
from modules.module2 import run_module2
from modules.module4 import run_module4
from modules.module5 import (
    Module5LPResult,
    Module5ScenarioBundle,
    run_module5,
    run_module5_montecarlo,
    DEFAULT_MC_TRIALS,
    detect_missing_data_cells,
)
from modules.module6 import Module6Result, Module6ScenarioResult, run_module6

from modules.module7 import Module7BundleInsight, run_module7


PLATFORM_NAMES: Dict[str, str] = {
    "fb": "Facebook",
    "ig": "Instagram",
    "li": "LinkedIn",
    "yt": "YouTube",
    "tt": "TikTok",
    "pt": "Pinterest",
    "tw": "X (Twitter)",
    "sn": "Snapchat",
    "rd": "Reddit",
    "go": "Google (Search + Display)",
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


def _roll_back_to_step(state: WizardState, target_step: int) -> None:
    """Rewind the wizard to *target_step* without losing the input values.

    All module-finalised flags from target_step onwards are reset so the
    user can re-enter that step.  WizardState's data fields (valid_goals,
    total_budget, active_platforms, etc.) are preserved so the forms can
    re-render with the user's previous selections as defaults.
    """
    if target_step <= 1:
        state.module1_finalised = False
    if target_step <= 2:
        state.module2_finalised = False
    if target_step <= 3:
        state.module3_finalised = False
    if target_step <= 4:
        state.module4_finalised = False
    if target_step <= 5:
        state.module5_finalised = False
    if target_step <= 6:
        state.module6_finalised = False
    if target_step <= 7:
        state.module7_finalised = False
    state.current_step = target_step
    # Drop the cached Monte Carlo too; new policy may invalidate it.
    st.session_state.pop("_mc_result", None)


_CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}


def _render_sidebar(state: WizardState) -> None:
    """Persistent left rail: progress, decisions so far, back-nav buttons.

    Visible on every step so the user always sees where they are in the
    wizard, what they've already chosen, and how to edit a previous step
    without nuking the whole session.
    """
    with st.sidebar:
        st.markdown("### Wizard")
        steps = [
            ("1. Objectives & Budget", 1, state.module1_finalised),
            ("2. Platforms & Priorities", 2, state.module2_finalised),
            ("3. Historical Data", 3, state.module3_finalised),
            ("4. Results & Refine", 4, state.module6_finalised),
        ]
        for label, step_num, done in steps:
            current = (state.current_step == step_num) or \
                      (step_num == 4 and state.current_step >= 4)
            if done and not current:
                icon = "✅"
            elif current:
                icon = "▶"
            else:
                icon = "○"
            st.markdown(f"{icon} {label}")

        # Summary of decisions made so far
        if state.valid_goals or state.total_budget or state.active_platforms:
            st.markdown("---")
            st.markdown("**So far:**")
            if state.valid_goals:
                labels = [_GOAL_LABEL.get(g, g) for g in state.valid_goals]
                st.caption(f"_Objectives:_ {', '.join(labels)}")
            if state.total_budget:
                sym = _CURRENCY_SYMBOLS.get(state.currency or "GBP", "")
                st.caption(f"_Budget:_ {sym}{state.total_budget:,.0f} "
                           f"({state.currency or 'GBP'})")
            if state.campaign_duration_days:
                st.caption(f"_Duration:_ {state.campaign_duration_days} days")
            if getattr(state, "test_and_learn_pct", 0.0) > 0:
                st.caption(
                    f"_Test reserve:_ {state.test_and_learn_pct*100:.0f}%"
                )
            if state.active_platforms:
                names = [_platform_display_name(state, p)
                         for p in state.active_platforms]
                st.caption(f"_Platforms:_ {', '.join(names)}")

        # Back-navigation: jump to any earlier completed step
        any_complete = (state.module1_finalised or state.module2_finalised
                        or state.module3_finalised)
        if any_complete:
            st.markdown("---")
            st.markdown("**Edit a previous step:**")
            if state.module1_finalised and state.current_step != 1:
                if st.button("← Module 1: Objectives & Budget",
                             key="_back_m1",
                             use_container_width=True):
                    _roll_back_to_step(state, 1)
                    safe_rerun()
            if state.module2_finalised and state.current_step != 2:
                if st.button("← Module 2: Platforms",
                             key="_back_m2",
                             use_container_width=True):
                    _roll_back_to_step(state, 2)
                    safe_rerun()
            if state.module3_finalised and state.current_step != 3:
                if st.button("← Module 3: Historical Data",
                             key="_back_m3",
                             use_container_width=True):
                    _roll_back_to_step(state, 3)
                    safe_rerun()

        st.markdown("---")
        if st.button("Start over (reset everything)", key="_sidebar_reset",
                     type="secondary"):
            reset_state()


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
                summary_rows.append(
                    {
                        "Metric": "Objective Value (raw)",
                        "Value": float(getattr(lp_res, "objective_value_raw") or 0.0),
                    }
                )

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


def _allocation_to_plan_rows(allocation: Optional[Dict[str, Dict[str, float]]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if not allocation:
        return pd.DataFrame(rows)
    for p_code, gmap in allocation.items():
        p = PLATFORM_NAMES.get(str(p_code).lower(), str(p_code))
        if not isinstance(gmap, dict):
            continue
        for g_code, v in gmap.items():
            g = GOAL_NAMES.get(str(g_code), str(g_code))
            rows.append({"Platform": p, "Objective": g, "Allocated Budget": float(v or 0.0)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Platform", "Objective"]).reset_index(drop=True)
    return df


def create_pdf_bytes(
    state: WizardState,
    scenario_payload: List[Tuple[str, Module5LPResult, Optional[Module6Result]]],
    module7_bundle: Optional[Module7BundleInsight] = None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story: List[Any] = []

    story.append(Paragraph("Results Summary", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Optimisation method: Linear Programming (LP) to allocate budget across platform and objective.",
            styles["BodyText"],
        )
    )
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

    if module7_bundle is not None and module7_bundle.scenario_insights:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Decision Insights (Interpretation Layer)", styles["Heading2"]))
        story.append(Spacer(1, 6))
        if module7_bundle.global_stability_explanation:
            story.append(Paragraph(module7_bundle.global_stability_explanation, styles["BodyText"]))
            story.append(Spacer(1, 6))
        if getattr(module7_bundle, "global_data_quality_note", None):
            story.append(Paragraph(f"Data quality note: {module7_bundle.global_data_quality_note}", styles["BodyText"]))
            story.append(Spacer(1, 10))

    for scenario_name, lp_res, forecast_res in scenario_payload:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Scenario: {_human_scenario_name(scenario_name)}", styles["Heading2"]))
        story.append(Spacer(1, 6))

        ins = None
        if module7_bundle is not None and module7_bundle.scenario_insights:
            ins = module7_bundle.scenario_insights.get(scenario_name)

        if ins is not None:
            story.append(Paragraph("Decision summary", styles["Heading3"]))
            story.append(Paragraph(ins.executive_summary, styles["BodyText"]))
            story.append(Spacer(1, 6))

            if getattr(ins, "classification", None) is not None and getattr(ins, "confidence_score", None) is not None:
                story.append(
                    Paragraph(
                        f"Classification: {ins.classification} | Confidence: {int(ins.confidence_score)}/100",
                        styles["BodyText"],
                    )
                )
                story.append(Spacer(1, 6))

            if getattr(ins, "data_quality_note", None):
                story.append(Paragraph(f"Data quality note: {ins.data_quality_note}", styles["BodyText"]))
                story.append(Spacer(1, 6))

            if getattr(ins, "plan_a", None) is not None:
                pa = ins.plan_a
                story.append(Paragraph("Plan A (Performance first)", styles["Heading3"]))
                pa_rows = [
                    {"Metric": "Objective value (estimate)", "Value": number(getattr(pa, "objective_value_estimate", 0.0), 2)},
                    {"Metric": "Primary focus", "Value": str(getattr(pa, "kpi_focus", ""))},
                ]
                tpa = Table(_df_to_table_data(pd.DataFrame(pa_rows)))
                tpa.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ]
                    )
                )
                story.append(tpa)
                story.append(Spacer(1, 6))

                pa_alloc_df = _allocation_to_plan_rows(getattr(pa, "allocation", None))
                if not pa_alloc_df.empty:
                    tpa2 = Table(_df_to_table_data(pa_alloc_df, money_columns=["Allocated Budget"]))
                    tpa2.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ]
                        )
                    )
                    story.append(tpa2)
                    story.append(Spacer(1, 6))

            if getattr(ins, "plan_b", None) is not None:
                pb = ins.plan_b
                story.append(Paragraph("Plan B (Risk managed)", styles["Heading3"]))
                pb_rows = [
                    {"Metric": "Objective value (estimate)", "Value": number(getattr(pb, "objective_value_estimate", 0.0), 2)},
                    {"Metric": "Primary focus", "Value": str(getattr(pb, "kpi_focus", ""))},
                ]
                trade = getattr(pb, "tradeoff_percent", None)
                if trade is not None:
                    pb_rows.append({"Metric": "Trade off", "Value": f"{number(trade, 1)}%"})

                tpb = Table(_df_to_table_data(pd.DataFrame(pb_rows)))
                tpb.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ]
                    )
                )
                story.append(tpb)
                story.append(Spacer(1, 6))

                pb_alloc_df = _allocation_to_plan_rows(getattr(pb, "allocation", None))
                if not pb_alloc_df.empty:
                    tpb2 = Table(_df_to_table_data(pb_alloc_df, money_columns=["Allocated Budget"]))
                    tpb2.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ]
                        )
                    )
                    story.append(tpb2)
                    story.append(Spacer(1, 6))

            if ins.binding_constraints:
                story.append(Paragraph("Binding constraints", styles["Heading3"]))
                for r in ins.binding_constraints:
                    story.append(Paragraph(f"- {r}", styles["BodyText"]))
                story.append(Spacer(1, 6))

            if ins.risks:
                story.append(Paragraph("Risks", styles["Heading3"]))
                for r in ins.risks:
                    story.append(Paragraph(f"- {r}", styles["BodyText"]))
                story.append(Spacer(1, 6))

            if ins.recommendations:
                story.append(Paragraph("Recommendations", styles["Heading3"]))
                for r in ins.recommendations:
                    story.append(Paragraph(f"- {r}", styles["BodyText"]))
                story.append(Spacer(1, 10))

        summary_rows: List[Dict[str, Any]] = [
            {"Metric": "Total Budget Used", "Value": money(lp_res.total_budget_used or 0.0)},
            {"Metric": "Objective Value", "Value": number(lp_res.objective_value or 0.0, 2)},
        ]
        if hasattr(lp_res, "objective_value_raw"):
            summary_rows.append(
                {"Metric": "Objective Value (raw)", "Value": number(getattr(lp_res, "objective_value_raw") or 0.0, 6)}
            )

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


def module3_ui(state: WizardState) -> None:
    st.header("Historical data")
    st.caption(
        "Tell the optimiser what each platform delivered for £X over the historical window. "
        "Count KPIs (reach, leads, clicks) are totals; rate KPIs (engagement rate) are percentages. "
        "Decimals are fine throughout."
    )
    # Consolidate three notices (placeholders, normalisation, attribution) into
    # one collapsible disclosure.  Each is real and worth surfacing the first
    # time the user sees this step, but three stacked yellow boxes create
    # warning fatigue and get skimmed past.
    with st.expander("How Module 3 works (read once)", expanded=False):
        st.markdown(
            "**Form fields are pre-filled with placeholder values** "
            "(e.g. 1,000 leads, 2.5% engagement rate). These are *not* "
            "defaults you should accept — they're starter numbers to keep "
            "the form interactive. Replace each cell with your actual "
            "historical KPI, or upload a CSV to pre-fill from real data. "
            "The results page will warn you about any cells with no data, "
            "but it cannot tell when a placeholder was submitted as real."
        )
        st.markdown("---")
        st.markdown(
            "**How your numbers are used.** Values are compared *relative "
            "to other platforms* within the same objective — doubling every "
            "platform's reach won't shift the allocation, only their "
            "ranking does. Platforms with shorter historical windows are "
            "partially pooled toward the cross-platform average: the LP "
            "trusts a 90-day estimate more than a 7-day one. If you want "
            "your raw numbers honoured without pooling, give each platform "
            "a long history (180+ days)."
        )
        st.markdown("---")
        st.markdown(
            "**Attribution caveat.** The KPIs you enter reflect each "
            "platform's own attribution model — typically last-click. "
            "Platforms over-credit their own conversions: Meta tends to "
            "claim leads that Search also influenced; Google tends to "
            "claim conversions that brand awareness created. The "
            "optimiser treats these numbers as truth, so its "
            "recommendation is *conditional on your attribution model "
            "being correct*. Incrementality — would these conversions "
            "have happened anyway? — is not modelled. Treat productivity "
            "ratios as upper bounds, not facts."
        )

    default_days = int(getattr(state, "campaign_duration_days", None) or 30)
    catalog = effective_kpi_config(state)
    m3_inputs: Dict[str, Dict[str, Any]] = {}

    for platform in state.active_platforms:
        platform_name = _platform_display_name(state, platform)
        with st.expander(platform_name, expanded=True):
            # ── CSV import (for supported platforms) ──────────────────────
            # Stored extracted values in session_state so the widgets below
            # default to them when the user uploads a file.
            csv_defaults_key = f"_csv_defaults_{platform}"
            if platform in CSV_SUPPORTED:
                # Upload + download-template side by side so the user can
                # grab the canonical column-name template, fill it in, and
                # re-upload — no guessing at column names.
                col_upload, col_template = st.columns([3, 1])
                with col_upload:
                    uploaded = st.file_uploader(
                        f"Drop a {platform_name} export here to pre-fill (optional)",
                        type=["csv"],
                        key=f"_csv_upload_{platform}",
                        help="Upload the CSV you export from the platform's "
                             "reporting UI.  Column names are matched "
                             "heuristically — you can still adjust any "
                             "value below.",
                    )
                with col_template:
                    template_bytes = generate_csv_template(platform)
                    if template_bytes:
                        st.write("")  # vertical spacer to align with uploader
                        st.download_button(
                            "📥 Template",
                            data=template_bytes,
                            file_name=f"{platform}_template.csv",
                            mime="text/csv",
                            key=f"_csv_template_{platform}",
                            help=(
                                f"Download an empty {platform_name} template "
                                "with every column the parser recognises "
                                "(plus one example row).  Fill in your real "
                                "values and re-upload."
                            ),
                            use_container_width=True,
                        )
                if uploaded is not None:
                    parsed = parse_platform_csv(uploaded.getvalue(), platform)
                    if "error" in parsed:
                        st.error(parsed["error"])
                    else:
                        st.session_state[csv_defaults_key] = parsed
                        matched = parsed.get("matched_columns", {})
                        if matched:
                            st.success(
                                f"Matched {len(matched)} column"
                                f"{'s' if len(matched) != 1 else ''} "
                                f"from {parsed.get('row_count', 0)} row"
                                f"{'s' if parsed.get('row_count', 0) != 1 else ''}."
                            )
                        if parsed.get("missing_kpis"):
                            st.info(
                                "Couldn't find columns for: "
                                + ", ".join(parsed["missing_kpis"])
                                + ". Enter them manually below."
                            )

            csv_defaults = st.session_state.get(csv_defaults_key, {}) or {}

            # ── KPI composition breakdown (auditable view) ────────────────
            # Show how each canonical KPI was built from the raw CSV
            # columns so the user can audit the LP's input.  Marketers can
            # also use the "Customise composition" panel below to override
            # the default aggregation rules.
            breakdown = (csv_defaults.get("kpi_breakdown") or {}) if csv_defaults else {}
            if breakdown:
                with st.expander("How your KPIs were composed", expanded=False):
                    st.caption(
                        "Each canonical KPI is built from one or more raw columns "
                        "in your CSV.  This view shows the components and the "
                        "operator (sum / first / max) used to combine them."
                    )
                    for var, bd in breakdown.items():
                        components = bd.get("components", [])
                        op = bd.get("operator", "first")
                        total = bd.get("value", 0.0)
                        rationale = bd.get("rationale", "")
                        used_fallback = bd.get("used_fallback", False)

                        st.markdown(f"**{var}** = `{total:,.2f}` (operator: `{op}`)")
                        for c in components:
                            col_name = c.get("column", "?")
                            cval = c.get("value", 0.0)
                            st.caption(f"  • {col_name}: {cval:,.2f}")
                        if rationale:
                            if used_fallback:
                                st.warning(rationale, icon="⚠️")
                            else:
                                st.caption(f"_{rationale}_")
                        st.markdown("---")

            # ── Composition override (Option C) ──────────────────────────
            # Per-component weight editor.  The composed value is recomputed
            # live from the weights and replaces csv_defaults['kpis'][var]
            # so the form's number_input below picks up the new value.
            overrides_key = f"_csv_overrides_{platform}"
            if breakdown:
                with st.expander("Customise composition (advanced)",
                                 expanded=False):
                    st.caption(
                        "Re-weight the components that build each canonical "
                        "KPI.  Useful if you want to count saves more than "
                        "reactions, or exclude a component entirely (weight = 0)."
                    )
                    overrides = st.session_state.get(overrides_key, {}) or {}
                    new_overrides: Dict[str, Dict[str, float]] = {}
                    for var, bd in breakdown.items():
                        components = bd.get("components", [])
                        if len(components) < 2:
                            continue  # nothing to re-weight on a single-component KPI

                        st.markdown(f"**{var}** weights:")
                        var_overrides = overrides.get(var, {})
                        new_var_overrides: Dict[str, float] = {}
                        ccols = st.columns(min(len(components), 4))
                        for i, c in enumerate(components):
                            col_name = c.get("column", f"comp_{i}")
                            with ccols[i % len(ccols)]:
                                w = st.number_input(
                                    col_name,
                                    min_value=0.0, max_value=10.0,
                                    value=float(var_overrides.get(col_name, 1.0)),
                                    step=0.5,
                                    key=f"_cw_{platform}_{var}_{i}",
                                )
                                new_var_overrides[col_name] = float(w)
                        new_overrides[var] = new_var_overrides

                    if st.button(
                        f"Apply composition weights for {platform_name}",
                        key=f"_apply_overrides_{platform}",
                    ):
                        st.session_state[overrides_key] = new_overrides
                        # Recompose KPI values in csv_defaults so the form
                        # below picks them up on rerun.
                        for var, weights in new_overrides.items():
                            components = breakdown.get(var, {}).get("components", [])
                            if not components:
                                continue
                            op = breakdown[var].get("operator", "first")
                            vals = []
                            for c in components:
                                col_name = c.get("column")
                                w = float(weights.get(col_name, 1.0))
                                vals.append(float(c.get("value", 0.0)) * w)
                            if not vals:
                                continue
                            if op == "sum":
                                recomposed = sum(vals)
                            elif op == "max":
                                recomposed = max(vals)
                            elif op == "mean":
                                recomposed = sum(vals) / len(vals)
                            else:
                                recomposed = vals[0]
                            csv_defaults["kpis"][var] = recomposed
                        st.session_state[csv_defaults_key] = csv_defaults
                        safe_rerun()

            col_days, col_budget = st.columns([1, 2])
            with col_days:
                hist_days = st.number_input(
                    "Historical window (days)",
                    min_value=1,
                    value=int(csv_defaults.get("historical_days") or default_days),
                    step=1,
                    key=f"hist_days_{platform}",
                    help="How many days of past performance these numbers cover. "
                         "Confidence bands shrink as the window grows (more data → less noise).",
                )
            with col_budget:
                budget = st.number_input(
                    "Total budget spent in that window",
                    min_value=1.01,
                    value=float(csv_defaults.get("budget") or 1000.0),
                    step=100.0, format="%.2f",
                    key=f"budget_{platform}",
                    help="Combined ad spend over the historical window. Decimals OK.",
                )

            kpi_defs = [
                row for row in catalog
                if row["platform"] == platform
                and row["goal"] in state.goals_by_platform.get(platform, [])
            ]
            csv_kpis = (csv_defaults.get("kpis") or {}) if csv_defaults else {}

            kpi_values: Dict[str, float] = {}
            for kpi_def in kpi_defs:
                var = kpi_def["var"]
                label = kpi_def["kpi_label"]
                kind = kpi_def.get("kind", "count")
                goal_code = kpi_def["goal"]
                goal_name = _GOAL_LABEL.get(goal_code, goal_code)

                csv_val = csv_kpis.get(var)

                if kind == "rate":
                    # Rate KPIs are dimensionless ratios in [0, 1].  Show as a
                    # percent slider — much easier to reason about than typing
                    # "0.045"; store as fraction.
                    default_pct = float(csv_val) * 100.0 if csv_val else 2.5
                    default_pct = max(0.0, min(100.0, default_pct))
                    pct = st.slider(
                        f"{goal_name} · {label} (%)",
                        min_value=0.0, max_value=100.0, value=default_pct, step=0.1,
                        key=f"{platform}_{var}",
                        help=f"Average {label.lower()} as a percentage. Stored as a decimal."
                             + (" Pre-filled from CSV." if csv_val else ""),
                    )
                    kpi_values[var] = pct / 100.0
                else:
                    # Count KPIs: total units over the historical window.
                    # Decimals are accepted (some platforms report fractional values).
                    default_val = float(csv_val) if csv_val else 1000.0
                    val = st.number_input(
                        f"{goal_name} · {label} (total over window)",
                        min_value=0.0, value=default_val, step=10.0, format="%.2f",
                        key=f"{platform}_{var}",
                        help=f"Total {label.lower()} recorded during the historical window. "
                             f"Decimals OK (e.g. 1500.5 leads if you're averaging across multiple ad sets)."
                             + (" Pre-filled from CSV." if csv_val else ""),
                    )
                    kpi_values[var] = float(val)

            m3_inputs[platform] = {
                "time_window": f"{int(hist_days)} days",
                "historical_days": int(hist_days),
                "budget": float(budget),
                "kpis": kpi_values,
            }

    # Validate before allowing submit — keeps the button enabled until the
    # user has at least one positive KPI value per platform.
    can_run = bool(state.active_platforms)
    for d in m3_inputs.values():
        if float(d.get("budget", 0.0)) <= 1.0:
            can_run = False
            break
        if not any(float(v) > 0 for v in d.get("kpis", {}).values()):
            can_run = False
            break

    if st.button("Run optimisation", disabled=not can_run, type="primary"):
        try:
            finalise_module3_from_inputs(state, platform_inputs=m3_inputs)
            safe_rerun()
        except (ValueError, RuntimeError) as e:
            st.error(f"Could not finalise Module 3: {e}")


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
    st.caption(
        "⚠️ Recommendations inherit the attribution your KPIs came from.  If the "
        "platform-reported numbers over-credit one channel (a known last-click "
        "bias), the LP will over-allocate to that channel.  Cross-check against "
        "incrementality tests (geo lifts, holdout splits) before committing to "
        "material reallocations."
    )

    # ── Missing-data warning (silent zeros made loud) ──────────────────────
    # A platform/goal cell that got £0 because the user provided no input
    # data looks identical in the allocation table to one the optimiser
    # actively chose to skip.  Surface the distinction so users can't
    # mistake "we had no information" for "the LP ranked this low."
    missing_cells = detect_missing_data_cells(state)
    if missing_cells:
        lines = []
        for cell in missing_cells:
            pname = _platform_display_name(state, cell.platform)
            if cell.reason == "no_platform_data":
                lines.append(
                    f"- **{pname}** — no KPI data provided for any objective"
                )
            else:
                gname = _GOAL_LABEL.get(cell.goal or "", cell.goal or "")
                lines.append(
                    f"- **{pname} · {gname}** — no KPI value provided for this cell"
                )
        st.warning(
            "**Some cells couldn't be optimised because input data was missing.**\n\n"
            + "\n".join(lines)
            + "\n\n_These platforms/goals got £0 not because the optimiser "
              "ranked them low, but because there was nothing to rank.  "
              "Go back to Module 3 and supply the missing values if you "
              "want them considered._",
            icon="⚠️",
        )

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

    decision_mode = st.selectbox(
        "Decision mode",
        options=["Performance first", "Risk managed", "Exploration"],
        index=0,
    )

    module7_bundle: Optional[Module7BundleInsight] = None
    bundle = getattr(state, "module5_scenario_bundle", None)
    if isinstance(bundle, Module5ScenarioBundle):
        try:
            module7_bundle = run_module7(state, bundle, fc_by_scenario, decision_mode=decision_mode)
        except Exception:
            module7_bundle = None

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

    if module7_bundle is not None and module7_bundle.scenario_insights:
        st.subheader("Decision insights")
        if module7_bundle.global_stability_explanation:
            st.caption(module7_bundle.global_stability_explanation)
        if getattr(module7_bundle, "global_data_quality_note", None):
            st.warning(module7_bundle.global_data_quality_note)

        for sk in scenario_keys:
            ins = module7_bundle.scenario_insights.get(sk)
            if ins is None:
                continue

            st.markdown(f"**{_human_scenario_name(sk)}**")

            if getattr(ins, "classification", None) is not None and getattr(ins, "confidence_score", None) is not None:
                st.caption(f"Classification: {ins.classification} | Confidence: {int(ins.confidence_score)}/100")

            if getattr(ins, "data_quality_note", None):
                st.warning(ins.data_quality_note)

            st.write(ins.executive_summary)

            if getattr(ins, "plan_b", None) is not None:
                pb = ins.plan_b
                trade = getattr(pb, "tradeoff_percent", None)
                if trade is not None:
                    st.caption(f"Plan B trade off: {number(trade, 1)}%")

            if ins.risks:
                st.markdown("Risks")
                for r in ins.risks:
                    st.write(f"- {r}")

            if ins.recommendations:
                st.markdown("Recommendations")
                for r in ins.recommendations:
                    st.write(f"- {r}")

            st.markdown("---")

    # ── Refine policy and re-solve ────────────────────────────────────────
    # A marketer iterates: "what if I bump the LI floor by £2k?", "what if
    # I cut the carve-out to 5%?".  Walking the wizard from Module 1 to
    # explore those is painful.  This expander mutates the policy fields
    # on state and re-runs Modules 4-7 in place — sub-second on typical
    # problems.
    with st.expander("Refine policy and re-solve", expanded=False):
        st.caption(
            "Adjust the policy levers below and click Re-solve.  Historical "
            "data and platform selection from Modules 1-3 are preserved."
        )

        col_budget, col_carve = st.columns(2)
        with col_budget:
            new_budget = st.number_input(
                "Total budget",
                min_value=1.01,
                value=float(state.total_budget or 0.0),
                step=500.0, format="%.2f",
                key="_resolve_budget",
            )
        with col_carve:
            new_tl_pct = st.slider(
                "Test-and-learn reserve",
                min_value=0.0, max_value=0.40,
                value=float(getattr(state, "test_and_learn_pct", 0.0)),
                step=0.01, format="%.0f%%",
                key="_resolve_tl",
            )

        new_seasonality: Dict[str, float] = {}
        if state.valid_goals:
            st.markdown("**Seasonality multipliers** (1.0 = no adjustment):")
            current_si = getattr(state, "seasonality_index", None) or {}
            scols = st.columns(min(len(state.valid_goals), 4))
            for i, g in enumerate(state.valid_goals):
                with scols[i % len(scols)]:
                    cur = float(current_si.get(g, 1.0))
                    m = st.slider(
                        _GOAL_LABEL.get(g, g),
                        min_value=0.2, max_value=3.0, value=cur, step=0.05,
                        key=f"_resolve_seasonality_{g}",
                    )
                    if abs(m - 1.0) > 1e-6:
                        new_seasonality[g] = m

        new_min_spend: Dict[str, float] = {}
        if state.active_platforms:
            st.markdown("**Per-platform minimum spend** (LP must allocate at least this much):")
            current_floors = getattr(state, "min_spend_per_platform", None) or {}
            fcols = st.columns(min(len(state.active_platforms), 4))
            for i, p in enumerate(state.active_platforms):
                with fcols[i % len(fcols)]:
                    cur = float(current_floors.get(p, 0.0))
                    floor = st.number_input(
                        _platform_display_name(state, p),
                        min_value=0.0, value=cur, step=100.0, format="%.0f",
                        key=f"_resolve_floor_{p}",
                    )
                    new_min_spend[p] = float(floor)

        if st.button("Re-solve with these changes", type="primary", key="_resolve_button"):
            try:
                # Mutate the policy fields, then unset the M4-M7 finalised
                # flags so results_ui's auto-run picks them up on rerun.
                state.total_budget = float(new_budget)
                state.test_and_learn_pct = float(new_tl_pct)
                state.seasonality_index = dict(new_seasonality)
                state.min_spend_per_platform = dict(new_min_spend)
                state.module4_finalised = False
                state.module5_finalised = False
                state.module6_finalised = False
                state.module7_finalised = False
                # current_step is at 7+ after a full run; the per-module
                # entry guards check it before running.  Roll back to 4.
                state.current_step = 4
                # Drop the cached Monte Carlo too; the new policy invalidates it.
                st.session_state.pop("_mc_result", None)
                safe_rerun()
            except Exception as e:
                st.error(f"Could not re-solve: {e}")

    # ── Solver diagnostics (auditable "why this allocation?") ──────────────
    # Surfaces the LP signals that already exist on every Module5LPResult
    # but were previously hidden from the UI.  Focused on the base scenario;
    # the per-scenario tabs below still let the user dig deeper.
    base_lp = lp_by_scenario.get("base") or (
        lp_by_scenario.get(scenario_keys[0]) if scenario_keys else None
    )
    if base_lp is not None and (
        base_lp.binding_constraints
        or base_lp.shadow_prices
        or base_lp.effective_minimum_warnings
        or base_lp.near_degenerate_groups
        or base_lp.test_and_learn_reserve > 0.0
    ):
        with st.expander("Solver diagnostics", expanded=False):
            st.caption(
                "What constraints actually shaped the optimiser's choice, "
                "and how sensitive the allocation is to each one."
            )

            if base_lp.test_and_learn_reserve > 0.0:
                st.markdown(
                    f"**Test-and-learn reserve (base scenario):** "
                    f"{money(base_lp.test_and_learn_reserve)} held back from the LP."
                )

            if base_lp.binding_constraints:
                st.markdown("**Binding constraints** — these stopped the LP from doing better:")
                binding_rows = []
                for bc in base_lp.binding_constraints:
                    target_label = ""
                    if bc.kind == "min_platform":
                        target_label = PLATFORM_NAMES.get(str(bc.target).lower(), str(bc.target))
                    elif bc.kind == "min_goal":
                        target_label = _GOAL_LABEL.get(str(bc.target).lower(), str(bc.target))
                    elif bc.kind == "budget_cap":
                        target_label = "(total)"
                    binding_rows.append({
                        "Constraint": bc.name,
                        "Kind": bc.kind,
                        "Target": target_label,
                        "Limit": money(bc.rhs),
                        "Shadow price": number(bc.shadow_price, 4),
                    })
                st.dataframe(pd.DataFrame(binding_rows),
                             use_container_width=True, hide_index=True)
                st.caption(
                    "Shadow price ≈ how much the objective would change if you "
                    "relaxed the constraint by one unit.  Positive on min floors "
                    "(forcing spend hurts the objective), negative on the budget cap "
                    "(more budget would help)."
                )

            # Top-3 shadow prices (by absolute value), excluding the already-shown bindings
            if base_lp.shadow_prices:
                already_shown = {bc.name for bc in base_lp.binding_constraints}
                other = [
                    (name, pi) for name, pi in base_lp.shadow_prices.items()
                    if name not in already_shown and abs(pi) > 1e-9
                ]
                if other:
                    other.sort(key=lambda kv: abs(kv[1]), reverse=True)
                    top = other[:3]
                    st.markdown("**Largest non-binding sensitivities:**")
                    st.dataframe(
                        pd.DataFrame([
                            {"Constraint": name, "Shadow price": number(pi, 4)}
                            for name, pi in top
                        ]),
                        use_container_width=True, hide_index=True,
                    )

            if base_lp.effective_minimum_warnings:
                st.markdown("**Below industry-effective spend** — these platforms may not exit the learning phase:")
                for w in base_lp.effective_minimum_warnings:
                    st.warning(w)

            if base_lp.near_degenerate_groups:
                st.markdown("**Near-degenerate cells** — productivity was effectively tied:")
                for grp in base_lp.near_degenerate_groups:
                    g_label = _GOAL_LABEL.get(str(grp.get("goal", "")).lower(), str(grp.get("goal", "")))
                    plats = ", ".join(
                        PLATFORM_NAMES.get(str(p).lower(), str(p)) for p in grp.get("platforms", [])
                    )
                    st.caption(
                        f"{g_label}: {plats} — split was set by proportional "
                        f"redistribution, not by a meaningful productivity gap."
                    )

    # ── Monte Carlo robustness ─────────────────────────────────────────────
    # On-demand because n_trials LP solves is the expensive bit (~1-5 s).
    # Caches the result in session state so toggling other UI elements
    # doesn't re-run the whole batch.
    with st.expander("Robustness check (Monte Carlo)", expanded=False):
        st.caption(
            "Re-solves the base scenario hundreds of times with productivities "
            "perturbed by their observed noise.  Surfaces platforms whose share "
            "is sensitive to the underlying assumptions."
        )
        col_n, col_seed, col_run = st.columns([1, 1, 1])
        with col_n:
            n_trials = st.number_input(
                "Trials", min_value=20, max_value=500,
                value=int(DEFAULT_MC_TRIALS), step=20,
                help="More trials = tighter percentiles, more runtime.",
            )
        with col_seed:
            seed = st.number_input(
                "Seed", min_value=0, max_value=2_147_483_647,
                value=42, step=1,
                help="Reproducibility — same seed gives the same distribution.",
            )
        with col_run:
            st.write("")  # vertical spacer to line up with inputs
            run_mc = st.button("Run robustness check", type="primary")

        if run_mc:
            try:
                with st.spinner(f"Running {int(n_trials)} LP solves..."):
                    mc_result = run_module5_montecarlo(
                        state, n_trials=int(n_trials), seed=int(seed),
                    )
                st.session_state["_mc_result"] = mc_result
            except Exception as e:
                st.error(f"Monte Carlo failed: {e}")

        mc_result = st.session_state.get("_mc_result")
        if mc_result is not None:
            st.caption(
                f"{mc_result.n_trials} trials completed (seed={mc_result.seed}). "
                f"Instability threshold: CV > {mc_result.instability_threshold:.0%}."
            )

            if mc_result.unstable_platforms:
                names = ", ".join(
                    PLATFORM_NAMES.get(p, p) for p in mc_result.unstable_platforms
                )
                st.warning(
                    f"Unstable platforms: {names}. "
                    f"Allocation rank for these platforms is sensitive to "
                    f"plausible productivity noise — don't bet the campaign on them."
                )
            else:
                st.success(
                    "No platform's allocation moved meaningfully under perturbation — "
                    "the plan is robust to the noise in the input data."
                )

            platform_rows = []
            for s in mc_result.per_platform:
                platform_rows.append({
                    "Platform": PLATFORM_NAMES.get(s.platform, s.platform),
                    "Mean": money(s.mean),
                    "p5": money(s.p5),
                    "Median": money(s.p50),
                    "p95": money(s.p95),
                    "CV": f"{s.cv:.1%}",
                })
            if platform_rows:
                st.markdown("**Per-platform allocation distribution:**")
                st.dataframe(pd.DataFrame(platform_rows),
                             use_container_width=True, hide_index=True)

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
    pdf_bytes = create_pdf_bytes(state, scenario_payload_for_exports, module7_bundle=module7_bundle)

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


# Default £-per-unit values shown as placeholders in the Module 1 form.
# These are sensible starting points for a UK B2B SaaS context, not
# universal truths — the user is meant to override them.
_GOAL_VALUE_HINTS: Dict[str, Tuple[str, float]] = {
    GOAL_LG: ("£ per qualified lead", 100.0),
    GOAL_WT: ("£ per website click", 0.50),
    GOAL_EN: ("£ per engagement", 0.20),
    GOAL_AW: ("£ per reach impression", 0.001),
}

_GOAL_LABEL: Dict[str, str] = {
    GOAL_AW: "Awareness",
    GOAL_EN: "Engagement",
    GOAL_WT: "Website Traffic",
    GOAL_LG: "Lead Generation",
}


def module1_ui(state: WizardState) -> None:
    st.header("Objectives and total budget")

    # ── Core inputs ────────────────────────────────────────────────────────
    # Defaults read from state when present so back-navigation shows the
    # user's previous selections instead of a blank form.
    objective_options = [
        (GOAL_AW, "Awareness"),
        (GOAL_EN, "Engagement"),
        (GOAL_WT, "Website Traffic"),
        (GOAL_LG, "Lead Generation"),
    ]
    prior_goals = set(state.valid_goals or [])
    goals = st.multiselect(
        "Choose one or more marketing objectives:",
        options=objective_options,
        default=[opt for opt in objective_options if opt[0] in prior_goals],
        format_func=lambda x: x[1],
    )
    goal_codes = [code for code, _ in goals]

    col_budget, col_currency, col_duration = st.columns([2, 1, 1])
    with col_budget:
        total_budget = st.number_input(
            "Total budget",
            min_value=1.0,
            value=float(state.total_budget) if state.total_budget else 10000.0,
            step=500.0,
            help="The full campaign budget — including any test-and-learn reserve.",
        )
    with col_currency:
        currency_options = ["GBP", "USD", "EUR"]
        currency = st.selectbox(
            "Currency", options=currency_options,
            index=currency_options.index(state.currency)
                  if state.currency in currency_options else 0,
        )
    with col_duration:
        duration_days = st.number_input(
            "Campaign days",
            min_value=1,
            value=int(state.campaign_duration_days or 30),
            step=1,
            help="Used to scale industry-effective minimums and historical-window confidence bands.",
        )

    # ── Goal values (utility weights) ──────────────────────────────────────
    goal_values: Dict[str, float] = {}
    if goal_codes:
        st.markdown("### What is each result worth to the business?")
        st.caption(
            "Set the £ value of one unit of each objective's KPI.  The "
            "optimiser uses these as utility weights — without them it "
            "falls back to rank-based heuristics.  Leave at 0 to skip."
        )
        st.info(
            "ℹ️ **The values pre-filled below are illustrative — sized for "
            "UK B2B SaaS** (£100/lead, £0.50/click, £0.20/engagement, "
            "£0.001/impression).  A B2C e-commerce business would use very "
            "different numbers: a lead might be worth £20, a click "
            "£0.05, an impression £0.001.  **Replace them with your own "
            "economics before relying on the plan** — these aren't "
            "universal defaults, they're a starter for one specific "
            "vertical."
        )
        cols = st.columns(min(len(goal_codes), 4))
        prior_values = state.goal_value_per_unit or {}
        for i, gcode in enumerate(goal_codes):
            label, default = _GOAL_VALUE_HINTS.get(gcode, (f"£ per {gcode}", 1.0))
            current = float(prior_values.get(gcode, default))
            with cols[i % len(cols)]:
                v = st.number_input(
                    f"{_GOAL_LABEL.get(gcode, gcode)} — {label}",
                    min_value=0.0,
                    value=current,
                    step=max(default / 10.0, 0.001),
                    format="%.4f",
                    key=f"goal_value_{gcode}",
                )
                if v > 0:
                    goal_values[gcode] = v

    # ── Advanced policy inputs ─────────────────────────────────────────────
    with st.expander("Advanced policy (test-and-learn, seasonality)",
                     expanded=bool(getattr(state, "test_and_learn_pct", 0.0)
                                    or getattr(state, "seasonality_index", {}))):
        test_and_learn_pct = st.slider(
            "Test-and-learn reserve",
            min_value=0.0,
            max_value=0.40,
            value=float(getattr(state, "test_and_learn_pct", 0.0) or 0.10),
            step=0.01,
            format="%.0f%%",
            help=(
                "Fraction of every scenario's budget held back from the LP for "
                "new audiences, creative tests, and emerging placements. "
                "Standard strategist practice is 10–15%."
            ),
        )

        st.markdown(
            "**Seasonality multipliers** — set to >1 if you expect productivity "
            "to beat the historical baseline during the campaign window "
            "(e.g. January after the Q4 auction spike clears); <1 if you expect "
            "underperformance (e.g. December CPM inflation). Leave at 1.0 for no adjustment."
        )
        seasonality_index: Dict[str, float] = {}
        prior_seasonality = getattr(state, "seasonality_index", {}) or {}
        if goal_codes:
            scols = st.columns(min(len(goal_codes), 4))
            for i, gcode in enumerate(goal_codes):
                with scols[i % len(scols)]:
                    mult = st.slider(
                        _GOAL_LABEL.get(gcode, gcode),
                        min_value=0.2,
                        max_value=3.0,
                        value=float(prior_seasonality.get(gcode, 1.0)),
                        step=0.05,
                        key=f"seasonality_{gcode}",
                    )
                    if abs(mult - 1.0) > 1e-6:
                        seasonality_index[gcode] = mult

    if st.button("Continue", disabled=not goal_codes or total_budget <= 1):
        try:
            finalise_module1(
                state,
                raw_objectives=goal_codes,
                raw_budget=total_budget,
                raw_currency=currency,
                raw_duration_days=int(duration_days),
                raw_goal_values=goal_values or None,
                raw_test_and_learn_pct=test_and_learn_pct or None,
                raw_seasonality_index=seasonality_index or None,
            )
            safe_rerun()
        except (Module1ValidationError, ValueError) as e:
            st.error(f"Could not finalise Module 1: {e}")


def _platform_display_name(state: WizardState, code: str) -> str:
    """Display label for a platform code, consulting the built-in
    PLATFORM_NAMES map first and falling back to any custom platform
    registered on state."""
    code_l = str(code).lower()
    if code_l in PLATFORM_NAMES:
        return PLATFORM_NAMES[code_l]
    for cp in (state.custom_platforms or []):
        if str(cp.get("code", "")).lower() == code_l:
            return str(cp.get("label") or code_l)
    return code_l


def _render_custom_platform_form(state: WizardState) -> None:
    """A self-contained form for defining a single new custom platform.

    Kept inside the Module 2 step because that's where platform selection
    happens; the user defines it, then selects it like a built-in.
    """
    with st.expander("Add a custom platform", expanded=False):
        st.caption(
            "Define a platform that isn't in the built-in catalogue. "
            "You'll need to pick which objectives it supports and name "
            "the KPI you report for each (e.g. Reach, Leads, Engagement Rate)."
        )

        existing = [str(cp.get("code", "")) for cp in (state.custom_platforms or [])]
        if existing:
            st.markdown(
                "**Currently registered:** "
                + ", ".join(_platform_display_name(state, c) for c in existing)
            )

        with st.form("custom_platform_form", clear_on_submit=True):
            col_code, col_label, col_min = st.columns([1, 2, 1])
            with col_code:
                cp_code = st.text_input("Code", help="2–6 lowercase letters/digits, e.g. 'spc'")
            with col_label:
                cp_label = st.text_input("Display name", help="e.g. 'Spotify Ads'")
            with col_min:
                cp_min = st.number_input(
                    "Monthly effective minimum (£)",
                    min_value=0.0, value=1000.0, step=100.0,
                    help="Used to warn when allocations might be too small to optimise.",
                )

            selected_goals = st.multiselect(
                "Which objectives does this platform support?",
                options=list(state.valid_goals),
                format_func=lambda g: _GOAL_LABEL.get(g, g),
            )

            kpi_rows: List[Dict[str, Any]] = []
            for g in selected_goals:
                gcol_label, gcol_var, gcol_kind = st.columns([2, 2, 1])
                glabel = _GOAL_LABEL.get(g, g)
                with gcol_label:
                    st.markdown(f"**{glabel}**")
                with gcol_var:
                    kpi_label = st.text_input(
                        f"KPI for {glabel}",
                        value="",
                        key=f"_cp_kpi_label_{g}",
                        help="e.g. Listens, Saves, Reach",
                    )
                with gcol_kind:
                    kind = st.radio(
                        "Kind",
                        options=["count", "rate"],
                        index=0,
                        key=f"_cp_kpi_kind_{g}",
                        horizontal=True,
                        help=(
                            "count = absolute unit (Leads, Reach, Clicks); "
                            "rate = dimensionless ratio in [0,1] like Engagement Rate."
                        ),
                    )
                if kpi_label.strip():
                    # Auto-generate a unique var name from code + goal + label
                    safe_label = "".join(
                        ch.upper() if ch.isalnum() else "_"
                        for ch in (kpi_label or "X")
                    )[:20]
                    var = f"{(cp_code or 'X').upper()}_{g.upper()}_{safe_label}"
                    kpi_rows.append({
                        "goal": g, "var": var,
                        "kpi_label": kpi_label.strip(), "kind": kind,
                    })

            submitted = st.form_submit_button("Register platform")
            if submitted:
                try:
                    state.register_custom_platform(
                        code=cp_code,
                        label=cp_label,
                        kpis=kpi_rows,
                        monthly_effective_minimum=float(cp_min),
                    )
                    st.success(
                        f"Registered '{cp_label}' ({cp_code}) with "
                        f"{len(kpi_rows)} KPI{'s' if len(kpi_rows) != 1 else ''}."
                    )
                    safe_rerun()
                except (ValueError, TypeError) as e:
                    st.error(f"Could not register platform: {e}")


def module2_ui(state: WizardState) -> None:
    st.header("Platforms and priorities")

    _render_custom_platform_form(state)

    builtin_platforms = ["fb", "ig", "li", "yt", "tt", "pt", "tw", "sn", "rd", "go"]
    custom_codes = [str(cp.get("code", "")) for cp in (state.custom_platforms or [])]
    platforms = builtin_platforms + custom_codes

    # Default to previously-selected platforms on rollback so the user
    # doesn't have to re-pick them.
    prior_active = [p for p in (state.active_platforms or []) if p in platforms]
    selected_platforms = st.multiselect(
        "Choose one or more platforms:",
        options=platforms,
        default=prior_active,
        format_func=lambda p: _platform_display_name(state, str(p)),
    )

    priorities_input: Dict[str, Dict[str, Optional[str]]] = {}
    is_valid = True

    if selected_platforms:
        st.markdown("### Set objective priorities per platform")
        st.caption(
            "Each platform must have a Priority 1 objective; Priority 2 "
            "is optional.  Priorities determine which objectives the "
            "platform competes in inside the LP."
        )

    # Compact grid: 2 platforms per row instead of one column per platform.
    # On a typical screen this halves the vertical scroll for a 6-platform
    # plan and lets the user see most/all selections at once.
    goal_options = [None] + list(state.valid_goals)
    goal_format = lambda x: {
        None: "(none)",
        GOAL_AW: "Awareness",
        GOAL_EN: "Engagement",
        GOAL_WT: "Website Traffic",
        GOAL_LG: "Lead Generation",
    }.get(x, str(x))

    for i in range(0, len(selected_platforms), 2):
        cols = st.columns(2, gap="large")
        for j, p in enumerate(selected_platforms[i:i + 2]):
            platform_name = _platform_display_name(state, p)
            with cols[j]:
                st.markdown(f"**{platform_name}**")
                p1_key = f"{p}_p1"
                p2_key = f"{p}_p2"

                # Defensive cleanup: if the user went back to Module 1 and
                # removed a goal, the cached priority for this platform may
                # now reference a removed goal.
                if st.session_state.get(p1_key) not in goal_options:
                    st.session_state[p1_key] = None

                p1 = st.selectbox(
                    "Priority 1",
                    options=goal_options,
                    format_func=goal_format,
                    key=p1_key,
                )

                allowed_p2 = [None] + [g for g in state.valid_goals if g != p1]
                if st.session_state.get(p2_key) == p1 and p1 is not None:
                    st.session_state[p2_key] = None
                if st.session_state.get(p2_key) not in allowed_p2:
                    st.session_state[p2_key] = None

                p2 = st.selectbox(
                    "Priority 2 (optional)",
                    options=allowed_p2,
                    format_func=goal_format,
                    key=p2_key,
                )

                if p2 is not None and p1 is None:
                    is_valid = False
                    st.error("Priority 2 needs Priority 1.")
                if p1 is not None and p2 is not None and p1 == p2:
                    is_valid = False
                    st.error("Priorities must differ.")
                if len(state.valid_goals) == 1 and p2 is not None:
                    is_valid = False
                    st.error("Only one objective selected.")

                priorities_input[p] = {"priority_1": p1, "priority_2": p2}

    if st.button("Continue", disabled=(not selected_platforms) or (not is_valid),
                 type="primary"):
        try:
            run_module2(state, selected_platforms, priorities_input)
            safe_rerun()
        except Exception as e:
            st.error(f"Could not finalise Module 2: {e}")


def main() -> None:
    st.set_page_config(page_title="Marketing Budget Optimisation", layout="wide")
    initialise_state()

    state: WizardState = st.session_state["wizard_state"]
    _render_sidebar(state)

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
