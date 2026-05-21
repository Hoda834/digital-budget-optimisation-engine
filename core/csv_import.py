"""CSV import + canonical-KPI composition layer.

Marketers report different metrics on each platform — Facebook's
"engagement" is a different beast from LinkedIn's, and that's a different
beast from TikTok's.  The LP needs *one* number per (platform, goal) cell,
so something has to compose the raw platform metrics into the canonical
category the LP optimises against.

This module makes that composition explicit instead of inheriting
whichever number the platform's CSV happens to bundle.  Each canonical
KPI declares:

  - one or more *components* (alternative column names that all measure
    the same atomic signal — e.g. "Reactions" or "Post reactions");
  - an *operator* combining the components (sum / first / max / mean);
  - a *rationale* explaining the choice, including any deduplication
    against other canonical categories.

For example, FB_EN_ENGAGEMENT is the sum of reactions + comments +
shares + saves — explicitly excluding link clicks because those are in
FB_WT_CLICKS and would otherwise be double-counted.

The composition is auditable: every parsed CSV returns a kpi_breakdown
showing which raw columns went into each canonical KPI, with the
operator that combined them, so the user can see exactly what produced
the LP's input.  Users can override the value directly in the form, or
re-weight components via the optional "Customise composition" panel.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ─────────────────────────────────────────────────────────────────────────────
# Composition rules
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KPIComposition:
    """How a canonical KPI is built from raw CSV columns.

    components: list of component groups.  Each group is a tuple of
        alternate column-name needles — the first column matching any
        needle in the group provides the component's value.  Different
        groups produce different components that get combined.

    operator: how to combine component values across groups.
        - 'first': take the first non-zero component value (used when
                   the needles in a single group are alternatives, e.g.
                   "leads" OR "lead form submissions").
        - 'sum':   add component values (used for genuine composites
                   like engagement = reactions + comments + shares).
        - 'max':   take the largest component value (e.g. reach vs
                   impressions when both are reported).
        - 'mean':  average component values (used for rates).

    rationale: short human-readable text the UI surfaces to explain
        why this composition was chosen and which atomic signals it
        deliberately excludes to avoid double-counting.

    fallback: a second composition to try if the primary one matches no
        columns.  Used when the platform offers both a clean break-out
        ("Reactions", "Comments", ...) and a bundled rollup ("Post
        engagement").  The rollup is usually less safe — it can include
        signals that already live in another canonical category — so the
        fallback rationale should warn the user about that.
    """
    components: Tuple[Tuple[str, ...], ...]
    operator: str = "first"
    rationale: str = ""
    fallback: Optional["KPIComposition"] = None


# Pseudo-KPI markers for non-KPI columns we still want from the CSV.
_BUDGET = "_budget"
_DAYS = "_days"


_CSV_PATTERNS: Dict[str, Dict[str, KPIComposition]] = {
    # ── Meta / Facebook ────────────────────────────────────────────────────
    "fb": {
        "FB_AW_REACH": KPIComposition(
            components=(("reach",),), operator="first",
            rationale="Unique people who saw the ad. Distinct from impressions.",
        ),
        "FB_AW_IMPRESSION": KPIComposition(
            components=(("impression",),), operator="first",
            rationale="Total impressions served (includes repeats).",
        ),
        "FB_EN_ENGAGEMENT": KPIComposition(
            components=(
                ("post reactions", "reactions"),
                ("comments", "post comments"),
                ("shares", "post shares"),
                ("saves",),
            ),
            operator="sum",
            rationale=(
                "Reactions + comments + shares + saves.  Link clicks are "
                "excluded — they live under Website Traffic, so including "
                "them here would double-count."
            ),
            fallback=KPIComposition(
                components=(("post engagement", "engagement"),),
                operator="first",
                rationale=(
                    "Using Meta's bundled 'Post engagement' column because "
                    "the broken-out components weren't in your export.  "
                    "Be aware: this number includes link clicks, which are "
                    "ALSO in the Traffic category — the LP may see a small "
                    "amount of double-counting for FB.  To fix, export "
                    "reactions / comments / shares / saves as separate "
                    "columns and re-upload."
                ),
            ),
        ),
        "FB_WT_CLICKS": KPIComposition(
            components=(("link click", "outbound click", "click (all)"),),
            operator="first",
            rationale="Clicks to your destination URL. Link / outbound are alternatives.",
        ),
        "FB_LG_LEADS": KPIComposition(
            components=(("on-facebook lead", "leads", "lead"),),
            operator="first",
            rationale="On-platform lead form submissions.",
        ),
        _BUDGET: KPIComposition(
            components=(("amount spent", "spend", "cost"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
    # ── Instagram ──────────────────────────────────────────────────────────
    "ig": {
        "IG_AW_REACH": KPIComposition(
            components=(("reach",),), operator="first",
            rationale="Unique people who saw the ad.",
        ),
        "IG_EN_ENGRATERATE": KPIComposition(
            components=(("engagement rate", "er"),), operator="mean",
            rationale="Engagement rate (Instagram reports as a single percentage).",
        ),
        "IG_WT_CLICKS": KPIComposition(
            components=(("link click", "outbound click"),), operator="first",
            rationale="Clicks to your destination URL.",
        ),
        "IG_LG_LEADS": KPIComposition(
            components=(("leads", "lead"),), operator="first",
            rationale="Lead form submissions.",
        ),
        _BUDGET: KPIComposition(
            components=(("amount spent", "spend", "cost"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
    # ── LinkedIn ───────────────────────────────────────────────────────────
    "li": {
        "LI_AW_REACH": KPIComposition(
            components=(("impression",),), operator="first",
            rationale="LinkedIn reports Impressions, not unique Reach.",
        ),
        "LI_EN_ENGRATERATE": KPIComposition(
            components=(("engagement rate", "average ctr"),), operator="mean",
            rationale="Engagement rate (LinkedIn reports a single weighted rate).",
        ),
        "LI_WT_CLICKS": KPIComposition(
            components=(("click",),), operator="first",
            rationale="Clicks on the ad.",
        ),
        "LI_LG_LEADS": KPIComposition(
            components=(("leads", "lead"),), operator="first",
            rationale="Lead Gen Form completions.",
        ),
        _BUDGET: KPIComposition(
            components=(("total spent", "amount spent", "spend", "cost"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
    # ── Google (Search + Display) ──────────────────────────────────────────
    "go": {
        "GO_AW_IMPRESSION": KPIComposition(
            components=(("impr.", "impressions", "impression"),), operator="first",
            rationale="Total impressions across Search + Display.",
        ),
        "GO_EN_CTR": KPIComposition(
            components=(("ctr",),), operator="mean",
            rationale="Click-through rate, reported as a single percentage.",
        ),
        "GO_WT_CLICKS": KPIComposition(
            components=(("clicks", "click"),), operator="first",
            rationale="Total clicks on Search/Display ads.",
        ),
        "GO_LG_CONVERSIONS": KPIComposition(
            components=(("conversions", "conv."),), operator="first",
            rationale="Google's reported conversions (whatever event you tagged).",
        ),
        _BUDGET: KPIComposition(
            components=(("cost", "spend"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
    # ── TikTok ─────────────────────────────────────────────────────────────
    "tt": {
        "TT_AW_VIEWS": KPIComposition(
            components=(("video views", "views"),), operator="first",
            rationale="Total video views (2 seconds+).",
        ),
        "TT_EN_ENGRATERATE": KPIComposition(
            components=(("engagement rate", "er"),), operator="mean",
            rationale="Engagement rate.  If your export has likes/comments/shares as "
                      "separate columns, use override to sum them as an alternative.",
        ),
        "TT_WT_CLICKS": KPIComposition(
            components=(("destination click", "clicks"),), operator="first",
            rationale="Clicks to your destination URL (destination preferred over "
                      "in-app clicks).",
        ),
        "TT_LG_LEADS": KPIComposition(
            components=(("leads", "lead"),), operator="first",
            rationale="Lead form submissions.",
        ),
        _BUDGET: KPIComposition(
            components=(("cost", "spend"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
    # ── YouTube ────────────────────────────────────────────────────────────
    "yt": {
        "YT_AW_VIEWS": KPIComposition(
            components=(("views",),), operator="first",
            rationale="Total ad views (TrueView etc).",
        ),
        "YT_EN_ENGRATERATE": KPIComposition(
            components=(("view rate", "engagement rate"),), operator="mean",
            rationale="View-through rate as engagement proxy.",
        ),
        "YT_WT_CLICKS": KPIComposition(
            components=(("clicks", "click"),), operator="first",
            rationale="Clicks on the ad / companion banner.",
        ),
        "YT_LG_LEADS": KPIComposition(
            components=(("conversions", "leads"),), operator="first",
            rationale="Tagged conversions.",
        ),
        _BUDGET: KPIComposition(
            components=(("cost", "spend"),), operator="first",
        ),
        _DAYS: KPIComposition(
            components=(("number of days", "days"),), operator="first",
        ),
    },
}


_RATE_KPIS = {
    "IG_EN_ENGRATERATE", "LI_EN_ENGRATERATE",
    "GO_EN_CTR", "TT_EN_ENGRATERATE", "YT_EN_ENGRATERATE",
}


SUPPORTED_PLATFORMS: Tuple[str, ...] = tuple(_CSV_PATTERNS.keys())


def get_composition(platform: str, var: str) -> Optional[KPIComposition]:
    """Return the KPIComposition for a (platform, var) pair, or None if
    the platform isn't in the CSV-import set or the var isn't recognised."""
    return _CSV_PATTERNS.get(platform.lower(), {}).get(var)


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────


def _normalise(s: str) -> str:
    """Lowercase + collapse separators so 'Amount_Spent (GBP)' matches 'amount spent'."""
    return (
        str(s or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("(gbp)", "")
        .replace("(usd)", "")
        .replace("(eur)", "")
        .replace("£", "")
        .strip()
    )


def _parse_number(raw: Any) -> Optional[float]:
    """Parse a single cell into a float; handle %, thousand separators, blanks."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("£", "").replace("$", "").replace("€", "")
    if not s or s.lower() in ("--", "n/a", "na", "none"):
        return None
    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    if is_percent:
        v = v / 100.0
    return v


def _aggregate(rows: List[Dict[str, Any]], col: str, op: str) -> Optional[float]:
    """Reduce a column to a scalar.  op ∈ {'sum', 'mean', 'first', 'max'}."""
    vals: List[float] = []
    for row in rows:
        v = _parse_number(row.get(col))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    if op == "mean":
        return sum(vals) / len(vals)
    if op == "first":
        return vals[0]
    if op == "max":
        return max(vals)
    return sum(vals)


_TOTALS_ROW_MARKERS = ("total", "subtotal", "all conversions", "grand total")


def _is_totals_row(row: Dict[str, Any]) -> bool:
    """Detect summary rows that platforms append at the bottom of exports."""
    for v in row.values():
        if v is None:
            continue
        s = str(v).strip().lower()
        if not s:
            continue
        for marker in _TOTALS_ROW_MARKERS:
            if s.startswith(marker):
                return True
        return False
    return False


def _find_column(needles: Tuple[str, ...], column_index: Dict[str, str]) -> Optional[str]:
    """Return the actual CSV column name for the first matching needle."""
    for needle in needles:
        n = _normalise(needle)
        for norm_col, real_col in column_index.items():
            if n in norm_col:
                return real_col
    return None


def _aggregate_components_across_rows(
    rows: List[Dict[str, Any]],
    composition: KPIComposition,
    column_index: Dict[str, str],
) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Aggregate one KPI from its composition rule, returning the composed
    value AND a per-component breakdown showing which columns matched.
    """
    component_values: List[Dict[str, Any]] = []
    for needle_group in composition.components:
        col = _find_column(needle_group, column_index)
        if col is None:
            continue
        # Aggregation per row-set depends on KPI type:
        #   - rates inside a composition operate on a single column via 'mean'
        #     across rows;
        #   - all other components sum within a column (one row per ad-set or
        #     campaign aggregates naturally).
        per_row_op = "mean" if composition.operator == "mean" else "sum"
        v = _aggregate(rows, col, per_row_op)
        if v is None:
            continue
        component_values.append({
            "needles": needle_group,
            "column": col,
            "value": v,
        })

    if not component_values:
        return None, []

    # Combine component values via the composition operator
    vals = [c["value"] for c in component_values]
    if composition.operator == "sum":
        total = sum(vals)
    elif composition.operator == "max":
        total = max(vals)
    elif composition.operator == "mean":
        total = sum(vals) / len(vals)
    else:  # "first"
        total = vals[0]

    return total, component_values


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def parse_platform_csv(
    content: Union[bytes, str],
    platform: str,
) -> Dict[str, Any]:
    """Parse a CSV export for one platform.

    Returns a dict shaped for Module 3 plus auditable composition data:
        {
          "budget": <float>,
          "historical_days": <int or None>,
          "kpis": {VAR: composed_value, ...},
          "kpi_breakdown": {
            VAR: {
              "value": composed_value,
              "operator": "sum" | "first" | ...,
              "rationale": "...",
              "components": [{column, value, needles}, ...],
            },
            ...
          },
          "matched_columns": {VAR: column_name, ...},
          "missing_kpis": [VAR, ...],
          "row_count": <int>,
        }

    Returns {"error": "..."} on a parse failure.
    """
    plat = (platform or "").strip().lower()
    if plat not in _CSV_PATTERNS:
        return {"error": f"CSV import is not supported for platform {plat!r}. "
                f"Supported: {', '.join(SUPPORTED_PLATFORMS)}."}

    if isinstance(content, bytes):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                content = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return {"error": "Could not decode CSV — try saving as UTF-8."}

    try:
        sample = content[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    except (csv.Error, ValueError) as e:
        return {"error": f"Could not parse CSV: {e}"}

    if not rows:
        return {"error": "CSV is empty or has no data rows."}

    rows = [r for r in rows if not _is_totals_row(r)]
    if not rows:
        return {"error": "CSV has no data rows after filtering totals."}

    column_index: Dict[str, str] = {}
    for col in rows[0].keys():
        if col is None:
            continue
        column_index.setdefault(_normalise(col), col)

    patterns = _CSV_PATTERNS[plat]
    kpis: Dict[str, float] = {}
    breakdown: Dict[str, Dict[str, Any]] = {}
    matched: Dict[str, str] = {}
    missing: List[str] = []
    budget_val: Optional[float] = None
    days_val: Optional[int] = None

    for var, comp in patterns.items():
        value, components = _aggregate_components_across_rows(rows, comp, column_index)
        # When primary composition matched nothing, try the documented
        # fallback (e.g. Meta's bundled 'Post engagement' when reactions
        # etc weren't exported separately).  The breakdown records which
        # composition won so the UI can show the fallback's warning.
        used_fallback = False
        if value is None and comp.fallback is not None:
            value, components = _aggregate_components_across_rows(
                rows, comp.fallback, column_index,
            )
            if value is not None:
                used_fallback = True
                comp = comp.fallback  # use fallback's rationale + operator

        if var == _BUDGET:
            budget_val = value
            if components:
                matched["budget"] = components[0]["column"]
            continue

        if var == _DAYS:
            if value is not None:
                days_val = int(value)
                matched["historical_days"] = components[0]["column"]
            continue

        if value is None or value <= 0:
            missing.append(var)
            continue

        # Rate KPIs live in [0, 1].  Some exports report percentages without
        # the '%' suffix (e.g. CTR shown as 4.50 meaning 4.5%); _parse_number
        # can't tell those apart from a literal 4.5.  If the composed rate
        # exceeds 1.0, treat the column as a bare-percentage form.
        if var in _RATE_KPIS and value > 1.0:
            if value <= 100.0:
                value = value / 100.0
                # Mirror the same correction in the component values for
                # auditability — otherwise the breakdown would look wrong.
                for c in components:
                    if c.get("value", 0.0) > 1.0:
                        c["value"] = c["value"] / 100.0
            else:
                missing.append(var)
                continue

        kpis[var] = value
        # First component's column is what we record for the legacy
        # matched_columns dict (back-compat with existing UI code).
        if components:
            matched[var] = components[0]["column"]
        breakdown[var] = {
            "value": value,
            "operator": comp.operator,
            "rationale": comp.rationale,
            "components": components,
            "used_fallback": used_fallback,
        }

    return {
        "budget": budget_val,
        "historical_days": days_val,
        "kpis": kpis,
        "kpi_breakdown": breakdown,
        "matched_columns": matched,
        "missing_kpis": missing,
        "row_count": len(rows),
    }
