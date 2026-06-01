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
from core.kpi_config import KPI_CONFIG, KIND_RATE
from core.csv_import import (
    parse_platform_csv,
    SUPPORTED_PLATFORMS as CSV_SUPPORTED,
    generate_unified_template_xlsx,
    parse_unified_template_xlsx,
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
    "go_search": "Google Search",
    "go_display": "Google Display",
    "go_pmax": "Google Performance Max",
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


def _current_currency_symbol() -> str:
    """Resolve the currency symbol from the active WizardState.

    Read once per money() / format call rather than threaded through every
    caller, because Streamlit's session-state already gives us a single
    canonical state per session.  Falls back to '£' if state isn't
    initialised yet (initial page load) or the currency is unknown.
    """
    state = st.session_state.get("wizard_state") if hasattr(st, "session_state") else None
    code = getattr(state, "currency", None) or "GBP"
    return _CURRENCY_SYMBOLS.get(code, "£")


def money(x: Any, currency_symbol: Optional[str] = None) -> str:
    """Format a money value with the campaign's currency symbol.

    Pass currency_symbol explicitly to override (useful in tests and PDF
    generation where state isn't accessible).  Default reads from the
    active WizardState so every UI panel shows £/$/€ consistently with
    the user's Module 1 choice.
    """
    sym = currency_symbol if currency_symbol is not None else _current_currency_symbol()
    try:
        v = float(x)
    except Exception:
        return f"{sym}0.00"
    return f"{sym}{v:,.2f}"


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
            "kind": str(row.get("kind", "count")).strip().lower() or "count",
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


def build_forecast_df(
    module6_res: Module6Result,
    goal_values: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Build the per-KPI forecast table.

    Uncertainty bands surfaced by Module 6 (``predicted_kpi_low``,
    ``predicted_kpi_high``, ``band_pct``) are carried into the table so
    the report shows the ±range the engine knows, not just the central
    point estimate.

    When ``goal_values`` is provided and contains at least one positive
    value, the table gains ``Expected Revenue`` and ``ROAS`` columns.
    To avoid double-counting when a (Platform, Objective) cell exposes
    multiple count KPIs measuring overlapping value (e.g. Facebook
    Awareness: Reach + Impression), revenue/ROAS are concentrated on
    Awareness = Reach + Impression), revenue/ROAS are concentrated on
    the cell's top-contribution KPI; sibling rows in the same cell
    carry zeros. The per-row ``Allocated Budget`` is the cell budget
    shared by every KPI in that cell, so it is also blanked on the
    sibling rows — that keeps column-sums in Excel honest while
    preserving per-KPI predictions for every row.
    """
    kpi_meta = build_kpi_meta()
    rows: List[Dict[str, Any]] = []

    gv: Dict[str, float] = {}
    if goal_values:
        for k, v in goal_values.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                gv[str(k)] = fv
    revenue_enabled = bool(gv)

    for r in (module6_res.rows or []):
        var = str(r.kpi_name)
        meta = kpi_meta.get(var, {})

        platform_code = str(r.platform).lower()
        platform_name = PLATFORM_NAMES.get(platform_code, str(r.platform))

        objective_code = str(getattr(r, "objective", "") or "")
        objective_name = GOAL_NAMES.get(objective_code, objective_code) if objective_code else ""

        kpi_label = str(meta.get("kpi_label", "")).strip() or "KPI"
        kind = str(meta.get("kind", "count")).strip().lower() or "count"

        budget = float(r.allocated_budget or 0.0)
        predicted = float(r.predicted_kpi or 0.0)
        predicted_low = float(getattr(r, "predicted_kpi_low", 0.0) or 0.0)
        predicted_high = float(getattr(r, "predicted_kpi_high", 0.0) or 0.0)
        band_pct = float(getattr(r, "band_pct", 0.0) or 0.0)

        row: Dict[str, Any] = {
            "Platform": platform_name,
            "Objective": objective_name,
            "KPI": kpi_label,
            "Allocated Budget": budget,
            "Predicted KPI": predicted,
            "Predicted KPI (low)": predicted_low,
            "Predicted KPI (high)": predicted_high,
            "Band ±%": band_pct * 100.0,
        }

        if revenue_enabled:
            goal_value = gv.get(objective_code, 0.0)
            if kind == "count" and goal_value > 0 and predicted > 0:
                revenue = predicted * goal_value
                roas = revenue / budget if budget > 0 else 0.0
            else:
                revenue = 0.0
                roas = 0.0
            row["Expected Revenue"] = revenue
            row["ROAS"] = roas

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.sort_values(["Platform", "Objective", "KPI"]).reset_index(drop=True)

    # Collapse per-cell duplicates: only the row with the largest contribution
    # (max Expected Revenue when revenue is enabled, else max Predicted KPI)
    # keeps the cell's shared budget and revenue/ROAS. Sibling rows zero out
    # those fields so column-sums (Excel, PDF totals, headline metrics)
    # reflect real spend / real upper-bound revenue.
    rank_col = "Expected Revenue" if revenue_enabled else "Predicted KPI"
    # Stable ordering: rank descending by contribution within each cell.
    df["__rank"] = df.groupby(["Platform", "Objective"])[rank_col].rank(
        method="first", ascending=False
    )
    non_primary = df["__rank"] > 1
    df.loc[non_primary, "Allocated Budget"] = 0.0
    if revenue_enabled:
        df.loc[non_primary, "Expected Revenue"] = 0.0
        df.loc[non_primary, "ROAS"] = 0.0
    df = df.drop(columns="__rank")
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
    goal_values: Optional[Dict[str, float]] = None,
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
            reserve_amt = float(getattr(lp_res, "test_and_learn_reserve", 0.0) or 0.0)
            if reserve_amt > 0:
                summary_rows.append(
                    {"Metric": "Test-and-learn Reserve", "Value": reserve_amt}
                )
            if hasattr(lp_res, "objective_value_raw"):
                summary_rows.append(
                    {
                        "Metric": "Objective Value (raw)",
                        "Value": float(getattr(lp_res, "objective_value_raw") or 0.0),
                    }
                )

            if forecast_res is not None and goal_values:
                fdf_for_totals = build_forecast_df(forecast_res, goal_values=goal_values)
                if "Expected Revenue" in fdf_for_totals.columns:
                    total_rev = float(fdf_for_totals["Expected Revenue"].sum())
                    spend = float(lp_res.total_budget_used or 0.0)
                    summary_rows.append({"Metric": "Expected Revenue", "Value": total_rev})
                    summary_rows.append(
                        {"Metric": "ROAS", "Value": (total_rev / spend) if spend > 0 else 0.0}
                    )

            summary_df = pd.DataFrame(summary_rows)
            budget_df = build_budget_allocation_df(lp_res)
            platform_df = build_platform_totals_df(lp_res)

            summary_df.to_excel(writer, sheet_name=f"Summary_{suffix}"[:31], index=False)
            budget_df.to_excel(writer, sheet_name=f"Budget_{suffix}"[:31], index=False)
            platform_df.to_excel(writer, sheet_name=f"Platforms_{suffix}"[:31], index=False)

            if forecast_res is not None:
                forecast_df = build_forecast_df(forecast_res, goal_values=goal_values)
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
    """Build a user-facing PDF report.

    Structure (recommendation first, policy last):
      Page 1   Headline: the recommended plan for the base scenario
      Page 2   Scenario comparison table
      Page 3+  Per-scenario detail (allocation, forecasts, risks, recs)
      End      Appendix: your inputs and policy
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story: List[Any] = []

    def _table(df: pd.DataFrame, money_cols: Optional[List[str]] = None) -> Table:
        t = Table(_df_to_table_data(df, money_columns=money_cols))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        return t

    # Pick the base scenario for the headline, falling back to the first.
    base_idx = next(
        (i for i, (s, _, _) in enumerate(scenario_payload) if s == "base"),
        0,
    )
    base_scenario = scenario_payload[base_idx] if scenario_payload else None

    # ─────────────────────────────────────────────────────────────────
    # PAGE 1: HEADLINE
    # ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("Your recommended budget plan", styles["Title"]))
    story.append(Spacer(1, 12))

    if base_scenario is not None:
        scen_name, lp_res, fc_res = base_scenario

        total_budget = getattr(state, "total_budget", 0.0) or 0.0
        duration = getattr(state, "duration_days", 0) or 0
        story.append(
            Paragraph(
                f"Spend {money(total_budget)} over {duration} days as follows:",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 8))

        # Headline allocation table (platform, objective, £, % of plan).
        alloc_df = build_budget_allocation_df(lp_res)
        if not alloc_df.empty:
            total = alloc_df["Allocated Budget"].sum()
            if total > 0:
                alloc_df = alloc_df.copy()
                alloc_df["Share"] = (alloc_df["Allocated Budget"] / total * 100).round(1).astype(str) + "%"
            story.append(_table(alloc_df, money_cols=["Allocated Budget"]))
            story.append(Spacer(1, 10))

        # Expected outcome (predicted KPI totals).
        if fc_res is not None:
            forecast_df = build_forecast_df(
                fc_res,
                goal_values=getattr(state, "goal_value_per_unit", None) or None,
            )
            if not forecast_df.empty:
                story.append(Paragraph("Expected outcome", styles["Heading3"]))
                # Slim the forecast table down to the four columns that matter.
                kept_cols = [c for c in ["Platform", "Objective", "KPI", "Predicted KPI"]
                             if c in forecast_df.columns]
                slim = forecast_df[kept_cols]
                story.append(_table(slim))
                story.append(Spacer(1, 10))

        # Confidence, classification, stability — one line each.
        ins = None
        if module7_bundle is not None and module7_bundle.scenario_insights:
            ins = module7_bundle.scenario_insights.get(scen_name)

        if ins is not None:
            if getattr(ins, "classification", None) is not None and \
               getattr(ins, "confidence_score", None) is not None:
                story.append(
                    Paragraph(
                        f"<b>Confidence:</b> {int(ins.confidence_score)}/100 "
                        f"&nbsp;&nbsp; <b>Decision pattern:</b> {ins.classification}",
                        styles["BodyText"],
                    )
                )
                story.append(Spacer(1, 4))

        if module7_bundle is not None and module7_bundle.global_stability_explanation:
            story.append(
                Paragraph(
                    f"<b>Stability across scenarios:</b> {module7_bundle.global_stability_explanation}",
                    styles["BodyText"],
                )
            )
            story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────
    # PAGE 2: SCENARIO COMPARISON
    # ─────────────────────────────────────────────────────────────────
    if len(scenario_payload) > 1:
        story.append(Spacer(1, 16))
        story.append(Paragraph("How the three scenarios compare", styles["Heading2"]))
        story.append(Spacer(1, 6))

        comp_rows = []
        any_reserve = False
        for scen_name, lp_res, fc_res in scenario_payload:
            total_used = float(getattr(lp_res, "total_budget_used", 0.0) or 0.0)
            reserve = float(getattr(lp_res, "test_and_learn_reserve", 0.0) or 0.0)
            if reserve > 0:
                any_reserve = True
            # Find the top platform and its share.
            pt = getattr(lp_res, "budget_per_platform", {}) or {}
            if pt and total_used > 0:
                top_code, top_val = max(pt.items(), key=lambda kv: kv[1])
                top_name = PLATFORM_NAMES.get(str(top_code).lower(), str(top_code))
                top_share = f"{top_val / total_used * 100:.0f}%"
            else:
                top_name, top_share = "-", "-"
            # Sum predicted KPIs across all forecast rows.
            if fc_res is not None and fc_res.rows:
                pred_total = sum(float(getattr(r, "predicted_kpi", 0.0) or 0.0)
                                 for r in fc_res.rows)
                pred_str = number(pred_total, 0)
            else:
                pred_str = "-"
            comp_rows.append({
                "Scenario": _human_scenario_name(scen_name),
                "Total spend": total_used,
                "T&L reserve": reserve,
                "Top platform": top_name,
                "Top share": top_share,
                "Predicted KPI total": pred_str,
            })
        comp_df = pd.DataFrame(comp_rows)
        # Drop the reserve column when no scenario carved one out.
        if not any_reserve:
            comp_df = comp_df.drop(columns=["T&L reserve"])
            money_cols = ["Total spend"]
        else:
            money_cols = ["Total spend", "T&L reserve"]
        story.append(_table(comp_df, money_cols=money_cols))
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                "The optimistic scenario does not recommend overspending: it is "
                "capped at your declared total budget.",
                styles["BodyText"],
            )
        )

    # ─────────────────────────────────────────────────────────────────
    # PAGES 3+: PER-SCENARIO DETAIL
    # ─────────────────────────────────────────────────────────────────
    for scenario_name, lp_res, forecast_res in scenario_payload:
        story.append(Spacer(1, 16))
        story.append(
            Paragraph(f"Detail: {_human_scenario_name(scenario_name)} scenario",
                      styles["Heading2"])
        )
        story.append(Spacer(1, 6))

        ins = None
        if module7_bundle is not None and module7_bundle.scenario_insights:
            ins = module7_bundle.scenario_insights.get(scenario_name)

        if ins is not None:
            story.append(Paragraph("Summary", styles["Heading3"]))
            story.append(Paragraph(ins.executive_summary, styles["BodyText"]))
            story.append(Spacer(1, 6))

            if getattr(ins, "data_quality_note", None):
                story.append(
                    Paragraph(f"Data quality note: {ins.data_quality_note}",
                              styles["BodyText"])
                )
                story.append(Spacer(1, 6))

            # Plan A: only show the allocation table, drop the internal metrics.
            if getattr(ins, "plan_a", None) is not None:
                pa = ins.plan_a
                story.append(Paragraph("Plan A (Performance first)", styles["Heading3"]))
                pa_alloc_df = _allocation_to_plan_rows(getattr(pa, "allocation", None))
                if not pa_alloc_df.empty:
                    story.append(_table(pa_alloc_df, money_cols=["Allocated Budget"]))
                    story.append(Spacer(1, 6))

            # Plan B: same idea, but show the trade-off because it matters here.
            if getattr(ins, "plan_b", None) is not None:
                pb = ins.plan_b
                story.append(Paragraph("Plan B (Risk managed)", styles["Heading3"]))
                trade = getattr(pb, "tradeoff_percent", None)
                if trade is not None:
                    story.append(
                        Paragraph(
                            f"Trade-off vs Plan A: <b>{number(trade, 1)}%</b> "
                            f"less expected performance, in exchange for diversification.",
                            styles["BodyText"],
                        )
                    )
                    story.append(Spacer(1, 4))
                pb_alloc_df = _allocation_to_plan_rows(getattr(pb, "allocation", None))
                if not pb_alloc_df.empty:
                    story.append(_table(pb_alloc_df, money_cols=["Allocated Budget"]))
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

        # Forecast detail (full table, not the slim version on page 1).
        if forecast_res is not None:
            forecast_df = build_forecast_df(
                forecast_res,
                goal_values=getattr(state, "goal_value_per_unit", None) or None,
            )
            if not forecast_df.empty:
                story.append(Paragraph("Forecast KPIs", styles["Heading3"]))
                money_cols = ["Allocated Budget"]
                if "Expected Revenue" in forecast_df.columns:
                    money_cols.append("Expected Revenue")
                story.append(_table(forecast_df, money_cols=money_cols))
                story.append(Spacer(1, 10))

    # ─────────────────────────────────────────────────────────────────
    # APPENDIX: YOUR INPUTS AND POLICY
    # ─────────────────────────────────────────────────────────────────
    df_p, df_g, df_s = _policy_tables(state)
    df_sgm = _scenario_goal_multiplier_table(state)

    if not df_p.empty or not df_g.empty or not df_s.empty or not df_sgm.empty:
        story.append(Spacer(1, 20))
        story.append(Paragraph("Appendix: your inputs and policy", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                "These are the rules and multipliers that constrained the optimiser. "
                "Adjust them in the wizard if any value is unexpected.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 10))

        if not df_p.empty:
            story.append(Paragraph("Minimum spend per platform", styles["Heading3"]))
            story.append(_table(df_p, money_cols=["Minimum Spend"]))
            story.append(Spacer(1, 10))

        if not df_g.empty:
            story.append(Paragraph("Minimum budget per objective", styles["Heading3"]))
            story.append(_table(df_g, money_cols=["Minimum Budget"]))
            story.append(Spacer(1, 10))

        if not df_s.empty:
            story.append(Paragraph("Scenario multipliers (overall)", styles["Heading3"]))
            story.append(_table(df_s))
            story.append(Spacer(1, 10))

        if not df_sgm.empty:
            story.append(Paragraph("Scenario multipliers per objective", styles["Heading3"]))
            story.append(_table(df_sgm))
            story.append(Spacer(1, 10))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def module3_ui(state: WizardState) -> None:
    st.header("Historical data")
    sym = _current_currency_symbol()
    st.caption(
        f"Tell the optimiser what each platform delivered for {sym}X over the historical window. "
        "Every KPI is a count — reach, engagement (sum of likes/comments/shares/etc.), clicks, "
        "leads, purchases — so just enter the totals.  Decimals are fine."
    )
    # Consolidate three notices (placeholders, normalisation, attribution) into
    # one collapsible disclosure.  Each is real and worth surfacing the first
    # time the user sees this step, but three stacked yellow boxes create
    # warning fatigue and get skimmed past.
    with st.expander("How Module 3 works (read once)", expanded=False):
        st.markdown(
            "**Form fields are pre-filled with placeholder values** "
            "(e.g. 1,000 leads, 8,000 engagements). These are *not* "
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

    # Push parsed upload values into the form's widget session_state keys.
    # Streamlit's number_input/slider ignore the `value=` argument once the
    # widget has rendered with a given key, so without this the form keeps
    # showing 0 / 1000 even after a successful upload.
    def _apply_parsed_to_widgets(p_code: str, parsed: Dict[str, Any]) -> None:
        b = parsed.get("budget")
        if b is not None:
            try:
                st.session_state[f"budget_{p_code}"] = float(b)
            except (TypeError, ValueError):
                pass
        hd = parsed.get("historical_days")
        if hd is not None:
            try:
                st.session_state[f"hist_days_{p_code}"] = int(hd)
            except (TypeError, ValueError):
                pass
        for _row in KPI_CONFIG:
            if _row["platform"] != p_code:
                continue
            _var = _row["var"]
            _val = (parsed.get("kpis") or {}).get(_var)
            if _val is None:
                continue
            try:
                _fv = float(_val)
            except (TypeError, ValueError):
                continue
            if _row.get("kind") == KIND_RATE:
                st.session_state[f"{p_code}_{_var}"] = max(0.0, min(100.0, _fv * 100.0))
            else:
                st.session_state[f"{p_code}_{_var}"] = _fv

    # ── Top-of-step unified template download + upload ─────────────────────
    # One workbook covers every platform the user selected in Module 2.
    # Each sheet is one platform with the columns its parser recognises +
    # one example row.  The user fills in the sheets they have data for,
    # leaves the rest blank, and re-uploads — the parser routes each
    # sheet to its platform's pre-fill slot in one shot.
    supported_platforms_for_active = [
        p for p in (state.active_platforms or []) if p in CSV_SUPPORTED
    ]
    if supported_platforms_for_active:
        st.markdown("### Don't have the data ready? Download one template, fill it in for every platform.")
        st.caption(
            "One Excel workbook with a sheet per platform you selected. "
            "Each sheet has the columns the parser recognises plus one "
            "example row.  Fill in only the sheets you have data for "
            "(leave the others blank) and upload the workbook back here."
        )
        col_dl, col_ul = st.columns([1, 3])
        with col_dl:
            template_bytes = generate_unified_template_xlsx(
                supported_platforms_for_active,
                platform_display_names=PLATFORM_NAMES,
            )
            if template_bytes:
                st.download_button(
                    "📥 Download unified template",
                    data=template_bytes,
                    file_name="campaign_data_template.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="_unified_template_download",
                    use_container_width=True,
                )
        with col_ul:
            unified_uploaded = st.file_uploader(
                "Drop the filled-in workbook here to pre-fill every platform at once",
                type=["xlsx"],
                key="_unified_template_upload",
                help=(
                    "Parses every sheet whose name matches one of your "
                    "selected platforms; sheets you renamed or left blank "
                    "are skipped silently.  You can still adjust any "
                    "value in the per-platform forms below after upload."
                ),
            )
            if unified_uploaded is not None:
                upload_token = (
                    f"{getattr(unified_uploaded, 'file_id', '')}"
                    f"|{getattr(unified_uploaded, 'name', '')}"
                    f"|{getattr(unified_uploaded, 'size', '')}"
                )
                already_applied = (
                    st.session_state.get("_unified_upload_applied_token") == upload_token
                )
                parsed_all = parse_unified_template_xlsx(
                    unified_uploaded.getvalue(),
                    platform_display_names=PLATFORM_NAMES,
                )
                if "__error__" in parsed_all:
                    st.error(parsed_all["__error__"].get("error", "Could not read workbook."))
                else:
                    unknown = parsed_all.pop("__unknown_sheets__", None)
                    filled_count = 0
                    empty_platforms: List[str] = []
                    applied_any = False
                    for p_code, parsed in parsed_all.items():
                        if "error" in parsed:
                            st.warning(
                                f"{PLATFORM_NAMES.get(p_code, p_code)}: "
                                f"{parsed['error']}"
                            )
                            continue
                        kpis_found = parsed.get("kpis") or {}
                        missing = parsed.get("missing_kpis") or []
                        if not kpis_found:
                            # Sheet was present but no KPIs were extracted.
                            # Without this surface, the form falls back to
                            # default values and the LP would silently produce
                            # ratio = 1.0 for every cell.
                            empty_platforms.append(
                                PLATFORM_NAMES.get(p_code, p_code)
                            )
                            continue
                        st.session_state[f"_csv_defaults_{p_code}"] = parsed
                        if not already_applied:
                            _apply_parsed_to_widgets(p_code, parsed)
                            applied_any = True
                        filled_count += 1
                        if missing:
                            st.warning(
                                f"{PLATFORM_NAMES.get(p_code, p_code)}: "
                                f"couldn't find columns for "
                                f"{', '.join(missing)}. Enter them manually "
                                f"below if you have them."
                            )
                    if applied_any:
                        st.session_state["_unified_upload_applied_token"] = upload_token
                        safe_rerun()
                    if filled_count > 0:
                        st.success(
                            f"Pre-filled {filled_count} platform"
                            f"{'s' if filled_count != 1 else ''} from the workbook."
                        )
                    if empty_platforms:
                        st.error(
                            "No KPI values were parsed for: "
                            + ", ".join(empty_platforms)
                            + ". Check that you filled in the data rows below "
                            "the header on each sheet, then re-upload — "
                            "otherwise the optimiser will see only the default "
                            "placeholder values."
                        )
                    if unknown:
                        st.info(
                            "These sheet names didn't match any selected "
                            "platform and were skipped: "
                            + ", ".join(unknown.get("sheets", []))
                        )
        st.markdown("---")

    default_days = int(getattr(state, "campaign_duration_days", None) or 30)
    catalog = KPI_CONFIG
    m3_inputs: Dict[str, Dict[str, Any]] = {}

    for platform in state.active_platforms:
        platform_name = _platform_display_name(state, platform)
        with st.expander(platform_name, expanded=True):
            # ── CSV import (for supported platforms) ──────────────────────
            # Stored extracted values in session_state so the widgets below
            # default to them when the user uploads a file.
            csv_defaults_key = f"_csv_defaults_{platform}"
            if platform in CSV_SUPPORTED:
                # Per-platform CSV upload accepts an actual platform export
                # (filtered Google Ads CSV, Facebook Ads export, etc.) in
                # case the user prefers that over filling the unified
                # workbook.  The unified template at the top of the step
                # is the easier path for most users.
                uploaded = st.file_uploader(
                    f"Drop a {platform_name} export here to pre-fill (optional)",
                    type=["csv"],
                    key=f"_csv_upload_{platform}",
                    help="Upload the CSV you export from the platform's "
                         "reporting UI.  Column names are matched "
                         "heuristically — you can still adjust any "
                         "value below.  Alternatively, use the unified "
                         "Excel template at the top of this step.",
                )
                if uploaded is not None:
                    csv_upload_token = (
                        f"{getattr(uploaded, 'file_id', '')}"
                        f"|{getattr(uploaded, 'name', '')}"
                        f"|{getattr(uploaded, 'size', '')}"
                    )
                    csv_token_key = f"_csv_upload_applied_token_{platform}"
                    parsed = parse_platform_csv(uploaded.getvalue(), platform)
                    if "error" in parsed:
                        st.error(parsed["error"])
                    else:
                        st.session_state[csv_defaults_key] = parsed
                        if st.session_state.get(csv_token_key) != csv_upload_token:
                            _apply_parsed_to_widgets(platform, parsed)
                            st.session_state[csv_token_key] = csv_upload_token
                            safe_rerun()
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
                         "Uncertainty bands shrink as the window grows (more data → less noise).",
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
                    # Default 0.0 (not a placeholder positive value) so the
                    # "Run optimisation" button stays disabled until the user
                    # has entered at least one real KPI per platform — this
                    # prevents the silent-failure path where every cell would
                    # otherwise come out with productivity 1.0 per pound.
                    default_val = float(csv_val) if csv_val else 0.0
                    val = st.number_input(
                        f"{goal_name} · {label} (total over window)",
                        min_value=0.0, value=default_val, step=10.0, format="%.2f",
                        key=f"{platform}_{var}",
                        help=f"Total {label.lower()} recorded during the historical window. "
                             f"Decimals OK (e.g. 1500.5 leads if you're averaging across multiple ad sets)."
                             + (" Pre-filled from CSV." if csv_val else
                                " Leave at 0 if this KPI was not tracked in your window."),
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
    st.header("Your budget plan")
 
    if st.button("Reset", type="secondary"):
        reset_state()
        return
 
    # Auto-run any modules that haven't been run yet
    if state.module3_finalised and not state.module4_finalised:
        run_module4(state, KPI_CONFIG)
    if state.module4_finalised and not state.module5_finalised:
        run_module5(state)
    if state.module5_finalised and not state.module6_finalised:
        run_module6(state)
 
    if not state.module6_finalised:
        st.info("Results will appear after optimisation runs.")
        return
 
    # ─── Set-up: load all the data we will display ────────────────────────
    lp_by_scenario = _get_module5_scenarios(state)
    fc_by_scenario = _get_module6_scenarios(state)
    scenario_keys = _get_scenario_key_order(list(lp_by_scenario.keys()))
 
    if not scenario_keys:
        st.error("No results available.")
        return
 
    # Decision mode lives small at the top of the supporting detail.
    # The base scenario drives the headline.
    base_key = "base" if "base" in scenario_keys else scenario_keys[0]
    base_lp = lp_by_scenario.get(base_key)
    base_fc = fc_by_scenario.get(base_key)
 
    goal_values: Optional[Dict[str, float]] = getattr(state, "goal_value_per_unit", None) or None
    has_explicit_goal_values = bool(
        goal_values and any(float(v) > 0 for v in goal_values.values())
    )
 
    module7_bundle: Optional[Module7BundleInsight] = None
    bundle = getattr(state, "module5_scenario_bundle", None)
    decision_mode = st.session_state.get("_decision_mode", "Performance first")
    if isinstance(bundle, Module5ScenarioBundle):
        try:
            module7_bundle = run_module7(state, bundle, fc_by_scenario, decision_mode=decision_mode)
        except Exception:
            module7_bundle = None
 
    base_insight = None
    if module7_bundle is not None and module7_bundle.scenario_insights:
        base_insight = module7_bundle.scenario_insights.get(base_key)
 
    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1 — HEADLINE: the recommended plan
    # ═══════════════════════════════════════════════════════════════════════
    total_budget = float(getattr(state, "total_budget", 0.0) or 0.0)
    duration = int(getattr(state, "duration_days", 0) or 0)
    st.markdown(
        f"### Spend {money(total_budget)} over {duration} days as follows"
    )
 
    if base_lp is not None:
        alloc_df = build_budget_allocation_df(base_lp)
        if not alloc_df.empty:
            total_alloc = float(alloc_df["Allocated Budget"].sum())
            show_df = alloc_df.copy()
            if total_alloc > 0:
                show_df["Share"] = (show_df["Allocated Budget"] / total_alloc * 100).round(1).astype(str) + "%"
            show_df["Allocated Budget"] = show_df["Allocated Budget"].apply(money)
            st.dataframe(show_df, use_container_width=True, hide_index=True)
 
    # Expected outcome (forecast KPIs at the headline level)
    if base_fc is not None:
        forecast_df = build_forecast_df(base_fc, goal_values=goal_values)
        if not forecast_df.empty:
            st.markdown("**Expected outcome**")
            slim_cols = [c for c in ["Platform", "Objective", "KPI", "Predicted KPI"]
                         if c in forecast_df.columns]
            slim = forecast_df[slim_cols].copy()
            if "Predicted KPI" in slim.columns:
                slim["Predicted KPI"] = slim["Predicted KPI"].apply(lambda x: number(x, 2))
            st.dataframe(slim, use_container_width=True, hide_index=True)
 
    # Confidence + classification + stability — one row each, big
    if base_insight is not None:
        cls = getattr(base_insight, "classification", None)
        conf = getattr(base_insight, "confidence_score", None)
        if cls is not None and conf is not None:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Confidence", f"{int(conf)} / 100")
            with col_b:
                st.metric("Decision pattern", str(cls))
 
    if module7_bundle is not None and module7_bundle.global_stability_explanation:
        st.caption(f"**Stability:** {module7_bundle.global_stability_explanation}")
 
    # Revenue and ROAS ONLY when the user actually entered goal values.
    if has_explicit_goal_values and base_lp is not None and base_fc is not None:
        forecast_preview = build_forecast_df(base_fc, goal_values=goal_values)
        if "Expected Revenue" in forecast_preview.columns:
            total_revenue = float(forecast_preview["Expected Revenue"].sum())
            spend = float(base_lp.total_budget_used or 0.0)
            if total_revenue > 0 and spend > 0:
                col_r, col_s = st.columns(2)
                with col_r:
                    st.metric("Expected revenue", money(total_revenue))
                with col_s:
                    st.metric("ROAS", f"{number(total_revenue / spend, 2)}×")
                st.caption(
                    "Based on the per-unit goal values you set in Module 1. "
                    "Update those values if the numbers look off."
                )
 
    # Missing-data warning is important enough to surface here, not buried.
    missing_cells = detect_missing_data_cells(state)
    if missing_cells:
        lines = []
        for cell in missing_cells:
            pname = _platform_display_name(state, cell.platform)
            if cell.reason == "no_platform_data":
                lines.append(f"- **{pname}** — no KPI data provided for any objective")
            else:
                gname = _GOAL_LABEL.get(cell.goal or "", cell.goal or "")
                lines.append(f"- **{pname} · {gname}** — no KPI value provided")
        sym = _current_currency_symbol()
        st.warning(
            "**Some cells could not be optimised because input data was missing.**\n\n"
            + "\n".join(lines)
            + f"\n\n_These platforms got {sym}0 because there was no data to rank them, "
              "not because the optimiser ranked them low._",
            icon="⚠️",
        )
 
    st.divider()
 
    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2 — SCENARIO COMPARISON: a single table
    # ═══════════════════════════════════════════════════════════════════════
    if len(scenario_keys) > 1:
        st.subheader("How the scenarios compare")
        comp_rows = []
        for sk in scenario_keys:
            lp_res = lp_by_scenario.get(sk)
            fc_res = fc_by_scenario.get(sk)
            if lp_res is None:
                continue
            total_used = float(lp_res.total_budget_used or 0.0)
            pt = getattr(lp_res, "budget_per_platform", {}) or {}
            if pt and total_used > 0:
                top_code, top_val = max(pt.items(), key=lambda kv: kv[1])
                top_name = PLATFORM_NAMES.get(str(top_code).lower(), str(top_code))
                top_share = f"{top_val / total_used * 100:.0f}%"
            else:
                top_name, top_share = "—", "—"
            if fc_res is not None and fc_res.rows:
                pred_total = sum(float(getattr(r, "predicted_kpi", 0.0) or 0.0)
                                 for r in fc_res.rows)
                pred_str = number(pred_total, 2)
            else:
                pred_str = "—"
            comp_rows.append({
                "Scenario": _human_scenario_name(sk),
                "Spend": money(total_used),
                "Top platform": top_name,
                "Top share": top_share,
                "Predicted KPI total": pred_str,
            })
        comp_df = pd.DataFrame(comp_rows)
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        st.caption(
            "The optimistic scenario does not recommend overspending. "
            "It is capped at your declared total budget."
        )
 
        st.divider()
 
    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3 — WHY THIS PLAN: a single consolidated insight block
    # If every scenario produced the same classification, recommendations,
    # and risks, we show them once. Otherwise we list the differences.
    # ═══════════════════════════════════════════════════════════════════════
    if module7_bundle is not None and module7_bundle.scenario_insights:
        st.subheader("Why this plan, and what to watch")
 
        all_insights = [module7_bundle.scenario_insights.get(sk) for sk in scenario_keys
                        if module7_bundle.scenario_insights.get(sk) is not None]
 
        if all_insights:
            # Check whether risks and recommendations are identical across scenarios.
            risks_sets = [tuple(sorted(getattr(i, "risks", []) or [])) for i in all_insights]
            recs_sets = [tuple(sorted(getattr(i, "recommendations", []) or [])) for i in all_insights]
            same_risks = len(set(risks_sets)) <= 1
            same_recs = len(set(recs_sets)) <= 1
 
            ref_insight = base_insight if base_insight is not None else all_insights[0]
 
            if same_risks and same_recs:
                # One block covers all three scenarios.
                if ref_insight.risks:
                    st.markdown("**Risks**")
                    for r in ref_insight.risks:
                        st.write(f"- {r}")
                if ref_insight.recommendations:
                    st.markdown("**Recommendations**")
                    for r in ref_insight.recommendations:
                        st.write(f"- {r}")
            else:
                # Genuine differences across scenarios.
                for sk in scenario_keys:
                    ins = module7_bundle.scenario_insights.get(sk)
                    if ins is None:
                        continue
                    if ins.risks or ins.recommendations:
                        st.markdown(f"**{_human_scenario_name(sk)} scenario**")
                        if ins.risks:
                            st.markdown("Risks")
                            for r in ins.risks:
                                st.write(f"- {r}")
                        if ins.recommendations:
                            st.markdown("Recommendations")
                            for r in ins.recommendations:
                                st.write(f"- {r}")
 
            # Binding constraints from the base scenario (if any).
            if base_insight is not None and base_insight.binding_constraints:
                st.markdown("**Binding constraints (base scenario)**")
                for c in base_insight.binding_constraints:
                    st.write(f"- {c}")
 
        st.caption(
            "ℹ Recommendations inherit the attribution your KPIs came from. "
            "If platform-reported numbers over-credit a channel (last-click bias), "
            "the optimiser will over-allocate to that channel. Cross-check against "
            "incrementality tests before committing to material reallocations."
        )
 
        st.divider()
 
    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4 — PER-SCENARIO DETAIL (collapsed by default)
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("Per-scenario detail (allocation, forecast, alternative plans)",
                     expanded=False):
        # Reorder so Base is the default visible tab
        order = ["base"] + [k for k in scenario_keys if k != "base"]
        order = [k for k in order if k in scenario_keys]
        tabs = st.tabs([_human_scenario_name(k) for k in order])
 
        scenario_payload_for_exports: List[Tuple[str, Module5LPResult, Optional[Module6Result]]] = []
        for tab, sk in zip(tabs, order):
            lp_res = lp_by_scenario.get(sk)
            if lp_res is None:
                continue
            forecast_res = fc_by_scenario.get(sk)
            scenario_payload_for_exports.append((sk, lp_res, forecast_res))
 
            with tab:
                # Compact metric row: budget + this-scenario's T&L reserve
                # (each scenario has its own reserve = tl_pct × scenario cap,
                # so showing only base's was hiding genuine differences).
                spend = float(lp_res.total_budget_used or 0.0)
                reserve = float(getattr(lp_res, "test_and_learn_reserve", 0.0) or 0.0)
                if reserve > 0:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric("Total budget used", money(spend))
                    with c2:
                        st.metric("Test-and-learn reserve (this scenario)", money(reserve))
                else:
                    st.metric("Total budget used", money(spend))

                # Budget allocation
                st.markdown("**Budget allocation**")
                budget_df = build_budget_allocation_df(lp_res)
                if budget_df.empty:
                    st.info("No allocation to display.")
                else:
                    show_budget = budget_df.copy()
                    show_budget["Allocated Budget"] = show_budget["Allocated Budget"].apply(money)
                    st.dataframe(show_budget, use_container_width=True, hide_index=True)

                # Forecast KPIs
                if forecast_res is not None:
                    forecast_df = build_forecast_df(forecast_res, goal_values=goal_values)
                    if not forecast_df.empty:
                        st.markdown("**Forecast KPIs**")
                        show_forecast = forecast_df.copy()
                        # Allocated Budget is the shared cell budget — blanked
                        # on sibling KPI rows so column sums reflect real spend.
                        show_forecast["Allocated Budget"] = show_forecast["Allocated Budget"].apply(
                            lambda x: money(x) if float(x) > 0 else ""
                        )
                        show_forecast["Predicted KPI"] = show_forecast["Predicted KPI"].apply(
                            lambda x: number(x, 2)
                        )
                        if "Predicted KPI (low)" in show_forecast.columns:
                            show_forecast["Predicted KPI (low)"] = show_forecast["Predicted KPI (low)"].apply(
                                lambda x: number(x, 2)
                            )
                        if "Predicted KPI (high)" in show_forecast.columns:
                            show_forecast["Predicted KPI (high)"] = show_forecast["Predicted KPI (high)"].apply(
                                lambda x: number(x, 2)
                            )
                        if "Band ±%" in show_forecast.columns:
                            show_forecast["Band ±%"] = show_forecast["Band ±%"].apply(
                                lambda x: f"±{number(x, 1)}%" if float(x) > 0 else ""
                            )
                        if "Expected Revenue" in show_forecast.columns and has_explicit_goal_values:
                            show_forecast["Expected Revenue"] = show_forecast["Expected Revenue"].apply(
                                lambda x: money(x) if float(x) > 0 else ""
                            )
                        else:
                            show_forecast = show_forecast.drop(
                                columns=[c for c in ["Expected Revenue", "ROAS"]
                                         if c in show_forecast.columns],
                                errors="ignore",
                            )
                        if "ROAS" in show_forecast.columns and has_explicit_goal_values:
                            show_forecast["ROAS"] = show_forecast["ROAS"].apply(
                                lambda x: f"{number(x, 2)}×" if float(x) > 0 else ""
                            )
                        st.dataframe(show_forecast, use_container_width=True, hide_index=True)
                        st.caption(
                            "Predicted KPI is the central forecast; low / high and ±% "
                            "show the uncertainty band Module 6 derived from data "
                            "(observation CV when available, otherwise scaled by the "
                            "historical window length). Allocated Budget shows the shared "
                            "(Platform, Objective) cell budget once per cell; sibling KPIs "
                            "in the same cell are blank to avoid double-counting "
                            "overlapping measures (e.g. Reach + Impression both index awareness)."
                        )
 
                # Plan A vs Plan B (if Module 7 produced them)
                if module7_bundle is not None and module7_bundle.scenario_insights:
                    ins = module7_bundle.scenario_insights.get(sk)
                    if ins is not None:
                        if getattr(ins, "plan_a", None) is not None:
                            pa = ins.plan_a
                            st.markdown("**Plan A (Performance first)**")
                            pa_alloc = _allocation_to_plan_rows(getattr(pa, "allocation", None))
                            if not pa_alloc.empty:
                                show = pa_alloc.copy()
                                show["Allocated Budget"] = show["Allocated Budget"].apply(money)
                                st.dataframe(show, use_container_width=True, hide_index=True)
                        if getattr(ins, "plan_b", None) is not None:
                            pb = ins.plan_b
                            st.markdown("**Plan B (Risk managed)**")
                            trade = getattr(pb, "tradeoff_percent", None)
                            if trade is not None:
                                st.caption(
                                    f"Trade-off vs Plan A: **{number(trade, 1)}%** "
                                    f"less expected performance, in exchange for diversification."
                                )
                            pb_alloc = _allocation_to_plan_rows(getattr(pb, "allocation", None))
                            if not pb_alloc.empty:
                                show = pb_alloc.copy()
                                show["Allocated Budget"] = show["Allocated Budget"].apply(money)
                                st.dataframe(show, use_container_width=True, hide_index=True)
 
    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5 — ADVANCED CONTROLS (refine, diagnostics, robustness)
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("Decision mode and refine policy", expanded=False):
        st.selectbox(
            "Decision mode",
            options=["Performance first", "Risk managed", "Exploration"],
            index=["Performance first", "Risk managed", "Exploration"].index(decision_mode),
            key="_decision_mode",
            help="Performance first chooses the LP optimum. Risk managed always offers Plan B. "
                 "Exploration loosens scenario coupling.",
        )
 
        st.caption(
            "Adjust the policy levers below and click Re-solve. Historical data "
            "and platform selection from Modules 1-3 are preserved."
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
            new_tl_pct_int = st.slider(
                "Test-and-learn reserve",
                min_value=0, max_value=40,
                value=int(round(float(getattr(state, "test_and_learn_pct", 0.0)) * 100)),
                step=1, format="%d%%",
                key="_resolve_tl",
            )
            new_tl_pct = new_tl_pct_int / 100.0
 
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
                state.total_budget = float(new_budget)
                state.test_and_learn_pct = float(new_tl_pct)
                state.seasonality_index = dict(new_seasonality)
                state.min_spend_per_platform = dict(new_min_spend)
                state.module4_finalised = False
                state.module5_finalised = False
                state.module6_finalised = False
                state.module7_finalised = False
                state.current_step = 4
                st.session_state.pop("_mc_result", None)
                safe_rerun()
            except Exception as e:
                st.error(f"Could not re-solve: {e}")
 
    # Solver diagnostics
    if base_lp is not None and (
        base_lp.binding_constraints
        or base_lp.shadow_prices
        or base_lp.effective_minimum_warnings
        or base_lp.near_degenerate_groups
        or base_lp.test_and_learn_reserve > 0.0
    ):
        with st.expander("Solver diagnostics (advanced)", expanded=False):
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
                        target_label = _platform_display_name(state, bc.target)
                    elif bc.kind == "min_goal":
                        target_label = _GOAL_LABEL.get(bc.target, bc.target)
                    elif bc.kind == "budget_cap":
                        target_label = "Total budget"
                    binding_rows.append({
                        "Constraint": bc.name,
                        "Kind": bc.kind,
                        "Target": target_label,
                        "Limit": money(bc.rhs),
                        "Shadow price": number(bc.shadow_price, 4),
                    })
                if binding_rows:
                    st.dataframe(pd.DataFrame(binding_rows),
                                 use_container_width=True, hide_index=True)

            if base_lp.shadow_prices:
                st.markdown("**Shadow prices** — value of relaxing each constraint by £1:")
                already_shown = {bc.name for bc in (base_lp.binding_constraints or [])}
                sp_rows = []
                for name, price in base_lp.shadow_prices.items():
                    if name in already_shown:
                        continue
                    sp_rows.append({
                        "Constraint": name,
                        "Shadow price": number(price, 4),
                    })
                if sp_rows:
                    st.dataframe(pd.DataFrame(sp_rows),
                                 use_container_width=True, hide_index=True)
 
            if base_lp.effective_minimum_warnings:
                st.markdown("**Effective-minimum warnings:**")
                for w in base_lp.effective_minimum_warnings:
                    st.write(f"- {w}")
 
            if base_lp.near_degenerate_groups:
                st.markdown("**Near-degenerate platform groups:**")
                for grp in base_lp.near_degenerate_groups:
                    names = ", ".join(
                        _platform_display_name(state, p) for p in grp
                    )
                    st.write(f"- {names}")
 
    # Robustness check (Monte Carlo)
    with st.expander("Robustness check (Monte Carlo, advanced)", expanded=False):
        st.caption(
            "Resamples the productivity matrix many times and reports how stable "
            "each platform's allocation is. Use this to spot platforms whose rank "
            "is sensitive to small data noise."
        )
 
        mc_trials = st.slider(
            "Number of trials", min_value=50, max_value=1000,
            value=int(DEFAULT_MC_TRIALS), step=50,
        )
        if st.button("Run robustness check", key="_mc_button"):
            try:
                mc_result = run_module5_montecarlo(state, n_trials=mc_trials)
                st.session_state["_mc_result"] = mc_result
            except Exception as e:
                st.error(f"Monte Carlo failed: {e}")
 
        mc_result = st.session_state.get("_mc_result")
        if mc_result is not None:
            st.markdown(
                f"**{mc_result.n_trials} trials.** "
                f"Stability score: **{number(mc_result.stability_score * 100, 1)}%** "
                f"(higher is better)."
            )
 
            if mc_result.unstable_platforms:
                names = ", ".join(
                    PLATFORM_NAMES.get(p, p) for p in mc_result.unstable_platforms
                )
                st.warning(
                    f"Unstable platforms: {names}. "
                    f"Their allocation rank is sensitive to plausible productivity noise."
                )
            else:
                st.success(
                    "No platform's allocation moved meaningfully under perturbation. "
                    "The plan is robust to the noise in the input data."
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
 
    # ═══════════════════════════════════════════════════════════════════════
    # APPENDIX — POLICY (collapsed at the bottom)
    # ═══════════════════════════════════════════════════════════════════════
    df_p, df_g, df_s = _policy_tables(state)
    df_sgm = _scenario_goal_multiplier_table(state)
    if not df_p.empty or not df_g.empty or not df_s.empty or not df_sgm.empty:
        with st.expander("Your inputs and policy", expanded=False):
            st.caption(
                "These are the rules and multipliers that constrained the optimiser. "
                "Go back to the wizard if any value is unexpected."
            )
            cols = st.columns(2)
            with cols[0]:
                if not df_p.empty:
                    show = df_p.copy()
                    show["Minimum Spend"] = show["Minimum Spend"].apply(money)
                    st.markdown("**Minimum spend per platform**")
                    st.dataframe(show, use_container_width=True, hide_index=True)
                if not df_s.empty:
                    show = df_s.copy()
                    show["Multiplier"] = show["Multiplier"].apply(lambda x: number(x, 2))
                    st.markdown("**Scenario multipliers (overall)**")
                    st.dataframe(show, use_container_width=True, hide_index=True)
            with cols[1]:
                if not df_g.empty:
                    show = df_g.copy()
                    show["Minimum Budget"] = show["Minimum Budget"].apply(money)
                    st.markdown("**Minimum budget per objective**")
                    st.dataframe(show, use_container_width=True, hide_index=True)
                if not df_sgm.empty:
                    show = df_sgm.copy()
                    for c in show.columns:
                        if c != "Scenario":
                            show[c] = show[c].apply(lambda x: number(x, 2))
                    st.markdown("**Scenario multipliers per objective**")
                    st.dataframe(show, use_container_width=True, hide_index=True)
 
    # ═══════════════════════════════════════════════════════════════════════
    # DOWNLOADS — at the very end
    # ═══════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("Downloads")
    pdf_bytes = create_pdf_bytes(state, scenario_payload_for_exports,
                                  module7_bundle=module7_bundle)
 
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
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
 
    with col_d2:
        if excel_available:
            xlsx_bytes = create_excel_bytes(
                scenario_payload_for_exports, goal_values=goal_values
            )
            st.download_button(
                label="Download Excel",
                data=xlsx_bytes,
                file_name="results_summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.info("Excel export needs `openpyxl` installed.")
 
    with col_d3:
        if st.button("Start over"):
            reset_state()


# Default value-per-unit illustrations for the Module 1 form.  The numeric
# magnitudes are anchored in UK B2B SaaS; the leading symbol is filled in at
# render time so the label matches whatever currency the user picked in
# Module 1 (GBP / USD / EUR).
_GOAL_VALUE_HINTS: Dict[str, Tuple[str, float]] = {
    GOAL_LG: ("{sym} per qualified lead", 100.0),
    GOAL_WT: ("{sym} per website click", 0.50),
    GOAL_EN: ("{sym} per engagement", 0.20),
    GOAL_AW: ("{sym} per reach impression", 0.001),
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
            help="Used to scale industry-effective minimums and historical-window uncertainty bands.",
        )

    # ── Goal values (utility weights) ──────────────────────────────────────
    goal_values: Dict[str, float] = {}
    if goal_codes:
        st.markdown("### What is each result worth to the business?")
        sym_display = _CURRENCY_SYMBOLS.get(currency, "£")
        st.caption(
            f"Set the {sym_display} value of one unit of each objective's KPI.  "
            "The optimiser uses these as utility weights — without them it "
            "falls back to rank-based heuristics.  Leave at 0 to skip."
        )
        st.info(
            f"ℹ️ **The values pre-filled below are illustrative — sized for "
            f"UK B2B SaaS** ({sym_display}100/lead, {sym_display}0.50/click, "
            f"{sym_display}0.20/engagement, {sym_display}0.001/impression).  "
            f"A B2C e-commerce business would use very different numbers: a "
            f"lead might be worth {sym_display}20, a click {sym_display}0.05, "
            f"an impression {sym_display}0.001.  **Replace them with your own "
            "economics before relying on the plan** — these aren't universal "
            "defaults, they're a starter for one specific vertical."
        )
        cols = st.columns(min(len(goal_codes), 4))
        prior_values = state.goal_value_per_unit or {}
        sym = _CURRENCY_SYMBOLS.get(currency, "£")
        for i, gcode in enumerate(goal_codes):
            label_tpl, default = _GOAL_VALUE_HINTS.get(
                gcode, ("{sym} per " + gcode, 1.0),
            )
            label = label_tpl.format(sym=sym)
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
        test_and_learn_pct_int = st.slider(
            "Test-and-learn reserve",
            min_value=0,
            max_value=40,
            value=int(round(float(getattr(state, "test_and_learn_pct", 0.0) or 0.10) * 100)),
            step=1,
            format="%d%%",
            help=(
                "Fraction of every scenario's budget held back from the LP for "
                "new audiences, creative tests, and emerging placements. "
                "Standard strategist practice is 10–15%."
            ),
        )
        test_and_learn_pct = test_and_learn_pct_int / 100.0

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
    """Display label for a platform code (built-in catalogue only)."""
    code_l = str(code).lower()
    return PLATFORM_NAMES.get(code_l, code_l)


def module2_ui(state: WizardState) -> None:
    st.header("Platforms and priorities")

    platforms = [
        "fb", "ig", "li", "yt", "tt", "pt", "tw", "sn", "rd",
        "go_search", "go_display", "go_pmax",
    ]

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
    st.set_page_config(page_title="CLARO — Marketing Budget Optimisation", layout="wide")
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
